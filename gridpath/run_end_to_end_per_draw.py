# Copyright 2026 Sylvan Energy Analytics LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Per-draw end-to-end mode (``gridpath_run_e2e --per_draw_lifecycle``) for
Monte Carlo scenarios with many iteration draws.

Instead of writing all inputs, solving everything, and then importing
everything -- which materializes the entire scenario directory (millions of
small files for large Monte Carlo cases) before any of it can be reclaimed
-- this mode pipelines the run one iteration draw (weather iteration, hydro
iteration, availability iteration) at a time:

* The main loop writes a batch of draws' inputs (``--n_draws_per_solve_batch``
  draws per batch, default 1), solves the batch with one run_scenario call
  -- whose ``--n_parallel_solve`` pool parallelizes over the batch's draws
  x subproblems -- and hands the solved batch to the importer queue.
* A single importer thread -- the only database writer -- imports queued
  batches while other draws are still solving, and, with
  ``--cleanup_after_import``/``--archive_after_import``, cleans each draw's
  directory as soon as its batch's import succeeds. The queue is bounded
  (``--max_draws_pending_import`` batches), so if importing falls behind,
  solving pauses and the on-disk footprint stays bounded.
* The database is switched to WAL journal mode for the duration of the run
  so the main loop's input-writing reads can proceed alongside the
  importer's writes; the prior journal mode is restored at the end.

Choosing the parallelization settings (peak on-disk footprint is about
(1 + --max_draws_pending_import) x --n_draws_per_solve_batch draws):

* ``--n_parallel_solve`` is the CPU (and memory) knob: each in-flight
  subproblem occupies roughly one core -- assuming single-threaded solver
  settings; if the solver is configured to use multiple threads, budget
  cores ~= --n_parallel_solve x solver threads instead -- plus the memory
  for its model and the solver's workspace. Start at about the machine's
  core count minus one (the importer thread and the main loop overlap with
  solving), and lower it if memory binds first: in-flight subproblems x
  per-subproblem peak memory must fit in RAM.
* ``--n_draws_per_solve_batch`` is NOT a CPU knob -- it only determines
  how much work the pool can see at once. Actual concurrency is
  min(--n_parallel_solve, batch size x subproblems per draw), so make the
  batch just large enough to feed the pool:

  - Many subproblems per draw (e.g. weekly subproblems over a year): the
    default batch of 1 already offers a full pool of tasks; leave it.
  - One subproblem per draw: set the batch to --n_parallel_solve (e.g. on
    a 10-core budget, both 10) -- with the default batch of 1, the draws
    solve sequentially no matter how many cores are available.
  - In-between shapes: the smallest batch with batch size x subproblems
    per draw >= --n_parallel_solve.

* Batches larger than needed add no speed -- the pool caps concurrency --
  and only raise the disk footprint and delay each batch's import/cleanup
  (a batch is imported only once it has fully solved). One exception: if
  solve times vary a lot across a batch, workers idle while the last
  tasks finish, so a batch of 2-3x the pool size amortizes that
  end-of-batch tail at proportionally higher footprint.

Each draw's import is idempotent: the importer first deletes the draw's
prior database rows, so a crashed or killed run can simply be re-run.
Completed draws are recognized on re-run by their rows in the cleanup
marker file (with cleanup/archiving on) and are skipped entirely; all other
draws are re-solved by default, exactly like the classic whole-scenario
mode -- pass ``--incomplete_only`` to skip re-solving subproblems whose
results are already on disk.

Some more notes:

Linked-subproblem scenarios are refused: subproblems then depend on each
other's inputs and the draws cannot be processed independently.

``--temporal_structure_csv_overwrite`` works with this mode: the draws
are then iterated from the CSV's structure instead of the database's, so a
per-draw run can be restricted to a subset of the scenario's draws. The CSV
must list WHOLE draws here (each processed draw's database results are
deleted in full before its re-import, so a partial draw would lose its
unlisted subproblems' results -- refused with a clear error); sub-draw
subsets belong in the classic pipeline.

``gridpath_run_e2e --per_draw_lifecycle --single_draw WEATHER HYDRO
AVAILABILITY`` (0 for iteration levels the scenario doesn't use; the two
flags are required together, --single_draw being a selector for this mode)
runs this same machinery for one
requested draw: its inputs are (re)written, it is solved and imported --
deleting only THIS draw's prior database rows, so the scenario's other
results are untouched -- and it is cleaned/archived if those options are
set. An explicitly requested draw is never skipped as already-completed,
and a scenario directory cleaned after import needs no special handling
(the draw is simply re-materialized). This is the one-command way to re-run
or debug a single draw of a large Monte Carlo case.
"""

import datetime
import os
import queue
import sys
import threading

from db.common_functions import connect_to_database, update_db_last_modified
from db.utilities.scenario import delete_scenario_results_for_draw
from gridpath.auxiliary.db_interface import get_scenario_id_and_name
from gridpath.auxiliary.module_list import determine_modules, load_modules
from gridpath.auxiliary.scenario_chars import (
    build_draws_structure,
    build_single_draw_structure,
    get_scenario_structure_from_csv,
    get_scenario_structure_from_db,
    iterate_directory_structure,
    iterate_draws,
    OptionalFeatures,
    resolve_requested_draw,
    ScenarioDirectoryStructure,
    SolverOptions,
    SubScenarios,
    validate_csv_structure_against_db,
)
from gridpath.common_functions import (
    create_directory_if_not_exists,
    determine_scenario_directory,
)
from gridpath import run_scenario
from gridpath.get_scenario_inputs import (
    delete_prior_aux_files,
    write_model_inputs,
    write_scenario_level_files,
)
from gridpath.import_scenario_results import (
    import_scenario_results_into_database,
    IMPORT_STATUS_IMPORTED,
    warn_on_import_gaps,
)
from gridpath.scenario_directory_cleanup import (
    cleanup_scenario_directory,
    get_cells_by_cleanup_unit,
    get_cleanup_marker_path,
    SCENARIO_ROOT_UNIT_NAME,
)

# Sentinel telling the importer thread no more draws are coming
_NO_MORE_DRAWS = None


class _ImportState:
    """
    Shared between the main (solve) loop and the importer thread: the
    accumulated per-cell import statuses and the first importer error.
    """

    def __init__(self):
        self.statuses = {}
        self.termination_conditions = {}
        self.error = None
        self.lock = threading.Lock()

    def record_statuses(self, statuses, termination_conditions=None):
        with self.lock:
            self.statuses.update(statuses)
            if termination_conditions is not None:
                self.termination_conditions.update(termination_conditions)

    def record_error(self, error):
        with self.lock:
            if self.error is None:
                self.error = error

    def get_error(self):
        with self.lock:
            return self.error


def get_draw_unit(scenario_structure, draw):
    """
    :return: the draw's cleanup-unit relative path ("" when the scenario has
        no iteration levels) and its list of (weather_iteration,
        hydro_iteration, availability_iteration, subproblem, stage) cells
    """
    draw_structure = build_single_draw_structure(scenario_structure, *draw)
    cells_by_unit = get_cells_by_cleanup_unit(draw_structure)
    # A single-draw structure has exactly one cleanup unit by construction
    unit, cells = next(iter(cells_by_unit.items()))

    return unit, cells


def get_completed_draw_units(scenario_directory):
    """
    :return: set of unit relative paths recorded in the cleanup marker file
        (draws whose import and cleanup completed in a previous run)
    """
    marker_path = get_cleanup_marker_path(scenario_directory)
    completed_units = set()
    if os.path.exists(marker_path):
        with open(marker_path, "r") as marker_file:
            import csv

            for row in csv.DictReader(marker_file):
                unit = row["cleaned_unit"]
                completed_units.add("" if unit == SCENARIO_ROOT_UNIT_NAME else unit)

    return completed_units


def check_csv_draws_are_whole(csv_structure, db_structure):
    """
    Per-draw mode deletes each processed draw's database results IN FULL
    before re-importing it (that is what makes the re-import safe), so a
    temporal-structure CSV used with per-draw mode must list whole draws: if
    it listed only some of a draw's subproblems/stages, the rest of that
    draw's imported results would be deleted and not re-imported. Sub-draw
    subsets belong in the classic (non-per-draw) pipeline.
    """

    def normalized(subproblem_stage_dict):
        return {
            int(subproblem): sorted(int(stage) for stage in stages)
            for subproblem, stages in subproblem_stage_dict.items()
        }

    # The database structure has the same subproblem/stage set for every
    # draw; use any draw's as the canonical set
    a_db_draw = next(iterate_draws(db_structure))
    canonical = normalized(
        db_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[a_db_draw[0]][
            a_db_draw[1]
        ][a_db_draw[2]]
    )

    for draw in iterate_draws(csv_structure):
        csv_draw_cells = normalized(
            csv_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[draw[0]][draw[1]][
                draw[2]
            ]
        )
        if csv_draw_cells != canonical:
            raise ValueError(
                f"The temporal structure CSV lists only part of draw "
                f"(weather {draw[0]}, hydro {draw[1]}, availability "
                f"{draw[2]}): its subproblems/stages {csv_draw_cells} vs "
                f"the scenario's {canonical}. Per-draw mode deletes and "
                f"re-imports each listed draw's database results in full, "
                f"so a partial draw would lose its unlisted "
                f"subproblems'/stages' results. List whole draws, or use "
                f"the classic (non-per-draw) pipeline for sub-draw subsets."
            )


def refuse_linked_subproblems(conn, subscenarios):
    """
    Per-draw mode requires draws (and their subproblems) to be independent;
    linked subproblems pass inputs between subproblems, so refuse.
    """
    linked_rows = conn.execute(
        """SELECT COUNT(*) FROM inputs_temporal
        WHERE linked_timepoint IS NOT NULL
        AND temporal_scenario_id = ?;""",
        (subscenarios.TEMPORAL_SCENARIO_ID,),
    ).fetchone()[0]
    if linked_rows > 0:
        raise ValueError(
            "The scenario has linked subproblems, which pass inputs from "
            "one subproblem to the next; --per_draw_lifecycle requires "
            "independent draws/subproblems and cannot be used with linked "
            "subproblems."
        )


def set_wal_journal_mode(db_path):
    """
    Switch the database to WAL journal mode for the run, so the main loop's
    input-writing reads can proceed alongside the importer thread's writes.
    :return: the prior journal mode, to restore at the end of the run
    """
    conn = connect_to_database(db_path=db_path)
    try:
        prior_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        conn.execute("PRAGMA journal_mode=WAL;")
    finally:
        conn.close()

    return prior_mode


def restore_journal_mode(db_path, journal_mode):
    """
    Checkpoint the WAL into the database file and restore the prior journal
    mode (a hot -wal sidecar left behind is a copy hazard for other
    tooling).
    """
    conn = connect_to_database(db_path=db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.execute(f"PRAGMA journal_mode={journal_mode};")
    finally:
        conn.close()


def import_draws_worker(
    draw_queue,
    import_state,
    db_path,
    scenario_id,
    scenario_directory,
    loaded_modules,
    import_rule,
    cleanup_after_import,
    archive_format,
    quiet,
    cleanup_granularity="draw",
):
    """
    The importer thread: the run's only database writer. Imports queued
    draw batches one at a time -- deleting each of the batch's draws' prior
    rows first, so a re-imported draw can't duplicate -- and cleans
    up/archives the batch's directories once its import has succeeded.
    Stops on the first error, leaving all remaining draws' directories
    untouched.
    """
    conn = connect_to_database(db_path=db_path)
    try:
        while True:
            item = draw_queue.get()
            if item is _NO_MORE_DRAWS:
                break
            batch_draws, batch_structure = item
            try:
                for draw in batch_draws:
                    # All of a draw's cells share the same iteration
                    # directory strings; the delete needs both the integer
                    # and the directory-string iteration keys (the results
                    # tables use both conventions)
                    a_cell = next(
                        iterate_directory_structure(
                            ScenarioDirectoryStructure(
                                build_single_draw_structure(batch_structure, *draw)
                            ).SCENARIO_DIRECTORY_STRUCTURE
                        )
                    )
                    delete_scenario_results_for_draw(
                        conn=conn,
                        scenario_id=scenario_id,
                        weather_iteration=draw[0],
                        hydro_iteration=draw[1],
                        availability_iteration=draw[2],
                        weather_iteration_str=a_cell.weather_iteration_str,
                        hydro_iteration_str=a_cell.hydro_iteration_str,
                        availability_iteration_str=a_cell.availability_iteration_str,
                    )
                statuses, termination_conditions = (
                    import_scenario_results_into_database(
                        import_rule=import_rule,
                        loaded_modules=loaded_modules,
                        scenario_id=scenario_id,
                        scenario_structure=batch_structure,
                        db=conn,
                        scenario_directory=scenario_directory,
                        ignore_incomplete=False,
                        quiet=quiet,
                        # Draws are solved fresh in this run, so a missing
                        # export-complete file is a real interrupted export,
                        # never a legacy directory
                        require_results_export_complete=True,
                    )
                )
                conn.commit()
                if cleanup_after_import or archive_format is not None:
                    cleanup_scenario_directory(
                        scenario_directory=scenario_directory,
                        scenario_structure=batch_structure,
                        import_statuses=statuses,
                        archive_format=archive_format,
                        quiet=quiet,
                        granularity=cleanup_granularity,
                    )
                import_state.record_statuses(statuses, termination_conditions)
            except Exception as e:
                import_state.record_error(e)
                break
    finally:
        conn.close()


def run_end_to_end_per_draw(args, parsed_args):
    """
    :param args: the raw argument list (passed through to run_scenario's
        parser for the solve stage)
    :param parsed_args: run_end_to_end's parsed arguments
    :return: the per-cell import statuses accumulated over all draws

    The per-draw driver: fused get_inputs -> solve -> import -> clean, one
    iteration draw at a time, with imports running concurrently with later
    draws' solves.
    """
    db_path = parsed_args.database
    scenario_location = parsed_args.scenario_location
    quiet = parsed_args.quiet

    conn = connect_to_database(db_path=db_path)
    try:
        c = conn.cursor()
        scenario_id, scenario_name = get_scenario_id_and_name(
            scenario_id_arg=parsed_args.scenario_id,
            scenario_name_arg=parsed_args.scenario,
            c=c,
            script="run_end_to_end_per_draw",
        )

        if parsed_args.temporal_structure_csv_overwrite:
            scenario_structure = get_scenario_structure_from_csv(
                parsed_args.temporal_structure_csv_path
            )
            db_structure = get_scenario_structure_from_db(
                conn=conn, scenario_id=scenario_id
            )
            validate_csv_structure_against_db(
                csv_structure=scenario_structure, db_structure=db_structure
            )
            # A CSV-selected subset must additionally consist of whole
            # draws in this mode: each processed draw's database results
            # are deleted in full before its re-import
            check_csv_draws_are_whole(
                csv_structure=scenario_structure, db_structure=db_structure
            )
        else:
            scenario_structure = get_scenario_structure_from_db(
                conn=conn, scenario_id=scenario_id
            )

        scenario_directory = determine_scenario_directory(
            scenario_location=scenario_location, scenario_name=scenario_name
        )
        create_directory_if_not_exists(directory=scenario_directory)

        optional_features = OptionalFeatures(conn=conn, scenario_id=scenario_id)
        subscenarios = SubScenarios(conn=conn, scenario_id=scenario_id)
        solver_options = SolverOptions(conn=conn, scenario_id=scenario_id)

        refuse_linked_subproblems(conn=conn, subscenarios=subscenarios)

        # With --single_draw, run the pipeline for only the requested draw
        requested_draw = None
        if parsed_args.single_draw is not None:
            requested_draw = resolve_requested_draw(
                scenario_structure=scenario_structure,
                weather_iteration=parsed_args.single_draw[0],
                hydro_iteration=parsed_args.single_draw[1],
                availability_iteration=parsed_args.single_draw[2],
            )

        feature_list = optional_features.get_active_features()
        modules_to_use = determine_modules(
            features=feature_list, multi_stage=scenario_structure.STAGE_FLAG
        )
        loaded_modules = load_modules(modules_to_use)

        # Draws completed in a previous run (from the cleanup marker file);
        # read BEFORE rewriting the scenario-level files
        completed_units = get_completed_draw_units(scenario_directory)

        # Scenario-level files are draw-independent: written once up front.
        # NOTE: the cleanup marker is deliberately NOT cleared here (unlike
        # in get_scenario_inputs.main) -- in per-draw mode it is the record
        # of completed draws
        delete_prior_aux_files(scenario_directory=scenario_directory)
        write_scenario_level_files(
            scenario_directory=scenario_directory,
            conn=conn,
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            scenario_structure=scenario_structure,
            optional_features=optional_features,
            subscenarios=subscenarios,
            solver_options=solver_options,
            feature_list=feature_list,
        )
    finally:
        conn.close()

    # The solve stage takes run_scenario's parsed arguments
    run_scenario_parsed_args = run_scenario.parse_arguments(
        args + ["--scenario", scenario_name]
    )

    import_state = _ImportState()
    draw_queue = queue.Queue(maxsize=parsed_args.max_draws_pending_import)
    importer = threading.Thread(
        target=import_draws_worker,
        kwargs={
            "draw_queue": draw_queue,
            "import_state": import_state,
            "db_path": db_path,
            "scenario_id": scenario_id,
            "scenario_directory": scenario_directory,
            "loaded_modules": loaded_modules,
            "import_rule": parsed_args.results_import_rule,
            "cleanup_after_import": parsed_args.cleanup_after_import,
            "archive_format": parsed_args.archive_after_import,
            "quiet": quiet,
            "cleanup_granularity": parsed_args.cleanup_granularity,
        },
        name="gridpath-draw-importer",
    )

    prior_journal_mode = set_wal_journal_mode(db_path=db_path)
    importer.started = False
    try:
        importer.start()
        importer.started = True

        draws_to_run = (
            [requested_draw]
            if requested_draw is not None
            else list(iterate_draws(scenario_structure))
        )

        # Filter out draws completed in a previous run (an explicitly
        # requested draw is never skipped: the user asked for it to be
        # re-run, whatever the marker says)
        n_draws = 0
        n_skipped_completed = 0
        pending_draws = []
        for draw in draws_to_run:
            n_draws += 1
            unit, cells = get_draw_unit(scenario_structure, draw)
            if requested_draw is None and unit in completed_units:
                # Record its cells as imported so the end-of-run summary
                # covers the whole scenario
                import_state.record_statuses(
                    {cell: IMPORT_STATUS_IMPORTED for cell in cells}
                )
                n_skipped_completed += 1
            else:
                pending_draws.append(draw)

        # Solve the remaining draws in batches of --n_draws_per_solve_batch
        # (default 1): --n_parallel_solve parallelizes over the batch's
        # draws x subproblems, so batching restores cross-draw parallelism
        # for draws with few subproblems
        batch_size = parsed_args.n_draws_per_solve_batch
        for batch_start in range(0, len(pending_draws), batch_size):
            batch_draws = pending_draws[batch_start : batch_start + batch_size]

            if import_state.get_error() is not None:
                break

            # Draws not recorded as completed are always re-solved (the same
            # default as the classic whole-scenario mode); run_scenario
            # itself skips already-solved subproblems if the user passed
            # --incomplete_only. Files left by other runs must not skip the
            # solve here: their presence doesn't mean they are complete
            # (e.g. the committed example directories carry only the
            # termination/status files, not the results CSVs)
            batch_structure = build_draws_structure(scenario_structure, batch_draws)
            write_model_inputs(
                scenario_directory=scenario_directory,
                scenario_structure=batch_structure,
                modules_to_use=modules_to_use,
                scenario_id=scenario_id,
                subscenarios=subscenarios,
                db_path=db_path,
                n_parallel_subproblems=int(parsed_args.n_parallel_get_inputs),
                delete_prior_aux=False,
            )
            run_scenario.run_scenario(
                scenario_directory=scenario_directory,
                scenario_structure=batch_structure,
                parsed_arguments=run_scenario_parsed_args,
            )

            if not quiet:
                unit_names = ", ".join(
                    get_draw_unit(scenario_structure, draw)[0]
                    or SCENARIO_ROOT_UNIT_NAME
                    for draw in batch_draws
                )
                print(f"Draw(s) {unit_names} solved; queueing for import.")

            # Bounded queue: block until the importer catches up, but keep
            # checking for importer errors so we don't block forever
            while True:
                if import_state.get_error() is not None:
                    break
                try:
                    draw_queue.put((batch_draws, batch_structure), timeout=5)
                    break
                except queue.Full:
                    continue
    finally:
        if importer.started:
            draw_queue.put(_NO_MORE_DRAWS)
            importer.join()
        restore_journal_mode(db_path=db_path, journal_mode=prior_journal_mode)

    importer_error = import_state.get_error()
    if importer_error is not None:
        raise importer_error

    conn = connect_to_database(db_path=db_path)
    try:
        update_db_last_modified(conn=conn, modification_type="results_import")
        conn.commit()
    finally:
        conn.close()

    if not quiet:
        n_imported = sum(
            1
            for status in import_state.statuses.values()
            if status == IMPORT_STATUS_IMPORTED
        )
        print(
            f"Per-draw run complete: {n_draws} draw(s), "
            f"{n_skipped_completed} previously completed, "
            f"{n_imported} of {len(import_state.statuses)} subproblems/stages "
            f"imported."
        )
    warn_on_import_gaps(import_state.statuses, import_state.termination_conditions)

    return import_state.statuses
