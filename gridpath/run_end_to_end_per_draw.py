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

* The main loop writes one draw's inputs, solves it (subproblems within the
  draw are parallelized with the usual ``--n_parallel_solve`` machinery),
  and hands the solved draw to the importer queue.
* A single importer thread -- the only database writer -- imports queued
  draws while later draws are still solving, and, with
  ``--cleanup_after_import``/``--archive_after_import``, cleans each draw's
  directory as soon as its import succeeds. The queue is bounded
  (``--max_draws_pending_import``), so if importing falls behind, solving
  pauses and the on-disk footprint stays bounded.
* The database is switched to WAL journal mode for the duration of the run
  so the main loop's input-writing reads can proceed alongside the
  importer's writes; the prior journal mode is restored at the end.

Each draw's import is idempotent: the importer first deletes the draw's
prior database rows, so a crashed or killed run can simply be re-run.
Completed draws are recognized on re-run by their rows in the cleanup
marker file (with cleanup/archiving on) and are skipped entirely; all other
draws are re-solved by default, exactly like the classic whole-scenario
mode -- pass ``--incomplete_only`` to skip re-solving subproblems whose
results are already on disk.

Linked-subproblem scenarios are refused: subproblems then depend on each
other's inputs and the draws cannot be processed independently.
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
    build_single_draw_structure,
    get_scenario_structure_from_csv,
    get_scenario_structure_from_db,
    iterate_directory_structure,
    iterate_draws,
    OptionalFeatures,
    ScenarioDirectoryStructure,
    SolverOptions,
    SubScenarios,
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
        self.error = None
        self.lock = threading.Lock()

    def record_statuses(self, statuses):
        with self.lock:
            self.statuses.update(statuses)

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
):
    """
    The importer thread: the run's only database writer. Imports queued
    draws one at a time -- deleting the draw's prior rows first, so a
    re-imported draw can't duplicate -- and cleans up/archives each draw's
    directory once its import has succeeded. Stops on the first error,
    leaving all remaining draws' directories untouched.
    """
    conn = connect_to_database(db_path=db_path)
    try:
        while True:
            item = draw_queue.get()
            if item is _NO_MORE_DRAWS:
                break
            draw, draw_structure = item
            try:
                # All the draw's cells share the same iteration directory
                # strings; the delete needs both the integer and the
                # directory-string iteration keys (the results tables use
                # both conventions)
                a_cell = next(
                    iterate_directory_structure(
                        ScenarioDirectoryStructure(
                            draw_structure
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
                statuses = import_scenario_results_into_database(
                    import_rule=import_rule,
                    loaded_modules=loaded_modules,
                    scenario_id=scenario_id,
                    scenario_structure=draw_structure,
                    db=conn,
                    scenario_directory=scenario_directory,
                    ignore_incomplete=False,
                    quiet=quiet,
                    # Draws are solved fresh in this run, so a missing
                    # export-complete file is a real interrupted export,
                    # never a legacy directory
                    require_results_export_complete=True,
                )
                conn.commit()
                if cleanup_after_import or archive_format is not None:
                    cleanup_scenario_directory(
                        scenario_directory=scenario_directory,
                        scenario_structure=draw_structure,
                        import_statuses=statuses,
                        archive_format=archive_format,
                        quiet=quiet,
                    )
                import_state.record_statuses(statuses)
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
        },
        name="gridpath-draw-importer",
    )

    prior_journal_mode = set_wal_journal_mode(db_path=db_path)
    importer.started = False
    try:
        importer.start()
        importer.started = True

        n_draws = 0
        n_skipped_completed = 0
        for draw in iterate_draws(scenario_structure):
            n_draws += 1
            draw_structure = build_single_draw_structure(scenario_structure, *draw)
            unit, cells = get_draw_unit(scenario_structure, draw)

            if unit in completed_units:
                # Completed in a previous run; record its cells as imported
                # so the end-of-run summary covers the whole scenario
                import_state.record_statuses(
                    {cell: IMPORT_STATUS_IMPORTED for cell in cells}
                )
                n_skipped_completed += 1
                continue

            if import_state.get_error() is not None:
                break

            # Draws not recorded as completed are always re-solved (the same
            # default as the classic whole-scenario mode); run_scenario
            # itself skips already-solved subproblems if the user passed
            # --incomplete_only. Files left by other runs must not skip the
            # solve here: their presence doesn't mean they are complete
            # (e.g. the committed example directories carry only the
            # termination/status files, not the results CSVs)
            write_model_inputs(
                scenario_directory=scenario_directory,
                scenario_structure=draw_structure,
                modules_to_use=modules_to_use,
                scenario_id=scenario_id,
                subscenarios=subscenarios,
                db_path=db_path,
                n_parallel_subproblems=int(parsed_args.n_parallel_get_inputs),
                delete_prior_aux=False,
            )
            run_scenario.run_scenario(
                scenario_directory=scenario_directory,
                scenario_structure=draw_structure,
                parsed_arguments=run_scenario_parsed_args,
            )

            if not quiet:
                unit_name = unit if unit else SCENARIO_ROOT_UNIT_NAME
                print(f"Draw {unit_name} solved; queueing for import.")

            # Bounded queue: block until the importer catches up, but keep
            # checking for importer errors so we don't block forever
            while True:
                if import_state.get_error() is not None:
                    break
                try:
                    draw_queue.put((draw, draw_structure), timeout=5)
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
    warn_on_import_gaps(import_state.statuses)

    return import_state.statuses
