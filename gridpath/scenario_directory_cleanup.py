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
Optional lifecycle management for the on-disk scenario directory after
results have been imported into the database.

For database-driven workflows the scenario directory is a regenerable
intermediate: inputs are written from the database and results are read back
into it. Monte Carlo cases with many iterations accumulate millions of small
files, so *gridpath_run_e2e* offers ``--cleanup_after_import`` (delete) and
``--archive_after_import`` (one tarball per iteration "draw", then delete)
to reclaim the directory once its contents are safely in the database.

The unit of cleanup is one iteration draw -- a (weather iteration, hydro
iteration, availability iteration) directory path, or the scenario
directory's own contents when the scenario has no iteration levels. A draw
is only cleaned if EVERY one of its subproblems/stages has import status
"imported" (see *import_scenario_results*); by default, draws with any
skipped or failed subproblem are left fully intact. With
``--cleanup_granularity subproblem``, the imported subproblems WITHIN such
partially imported draws are cleaned too, retaining only the not-imported
subproblems (useful when a single stuck subproblem would otherwise strand a
large draw on disk); fully imported draws are still cleaned as whole draws,
so re-run resume bookkeeping is the same at both granularities.

Retained in all cases: the scenario-level files
(``scenario_description.csv``, ``features.csv``, ``solver_options.csv``,
``units.csv``, ``multi_stage_flag.txt``, ``linked_subproblems_map.csv``) and
the scenario-level ``logs`` directory (small, and the only non-regenerable
content).

Cleanup writes a marker file (``scenario_directory_cleaned.csv``, one row
per cleaned draw) to the scenario directory. Each entry point has a
deliberate, different relationship with the marker:

* *import_scenario_results* refuses to run on a marked directory, with NO
  override: it deletes all of the scenario's database results before
  importing, so importing from a cleaned directory would wipe the results
  and find nothing to re-import. (``gridpath_run_e2e --per_draw_lifecycle
  --single_draw`` is the sanctioned way to re-import one draw: it deletes
  only that draw's rows.)
* *run_scenario* refuses unless passed ``--ignore_cleanup_marker``: the
  scenario structure is inferred from the directory tree, so a partially
  cleaned tree yields a silently wrong structure -- but deliberately
  solving just what is on disk (a re-materialized subset) is a legitimate,
  explicit choice.
* *get_scenario_inputs* is never blocked -- it is the recovery path: a full
  regeneration of the database-derived structure removes the marker, while
  a partial regeneration (``--single_draw`` or a temporal-structure CSV)
  leaves it in place, since the rest of the tree is still cleaned.
"""

import csv
import datetime
import os
import shutil
import tarfile

from db.common_functions import connect_to_database
from gridpath.auxiliary.db_interface import get_scenario_id_and_name
from gridpath.auxiliary.scenario_chars import (
    get_scenario_structure_from_csv,
    get_scenario_structure_from_db,
    iterate_directory_structure,
    ScenarioDirectoryStructure,
)
from gridpath.common_functions import determine_scenario_directory

CLEANUP_MARKER_FILENAME = "scenario_directory_cleaned.csv"
ARCHIVE_DIRECTORY_NAME = "archive"

# Scenario-root items never touched by cleanup
RETAINED_ROOT_ITEMS = {
    "scenario_description.csv",
    "features.csv",
    "solver_options.csv",
    "units.csv",
    "multi_stage_flag.txt",
    "linked_subproblems_map.csv",
    "logs",
    ARCHIVE_DIRECTORY_NAME,
    CLEANUP_MARKER_FILENAME,
}

ARCHIVE_FORMATS = {"tar": ("w", ".tar"), "tar.gz": ("w:gz", ".tar.gz")}

# The cleanup-unit name used in the marker file for the scenario root (the
# empty relative path, when the scenario has no iteration levels)
SCENARIO_ROOT_UNIT_NAME = "."


def get_cleanup_marker_path(scenario_directory):
    return os.path.join(scenario_directory, CLEANUP_MARKER_FILENAME)


def check_scenario_directory_not_cleaned(scenario_directory, attempted_action):
    """
    Raise if the scenario directory has been cleaned after import. Called by
    the entry points that consume the directory's inputs/results.
    """
    marker_path = get_cleanup_marker_path(scenario_directory)
    if os.path.exists(marker_path):
        raise RuntimeError(
            f"Scenario directory {scenario_directory} was cleaned after its "
            f"results were imported ({CLEANUP_MARKER_FILENAME} is present): "
            f"its inputs/results directories were deleted or archived. "
            f"{attempted_action} "
            f"To use this scenario directory again, re-generate the inputs "
            f"with gridpath_get_inputs (which removes the marker) and "
            f"re-solve, or restore the directory contents from the "
            f"'{ARCHIVE_DIRECTORY_NAME}' tarballs and delete "
            f"{marker_path} yourself -- the latter only if the directory "
            f"has not since been partially regenerated with a different "
            f"layout (e.g. via a temporal-structure CSV), as the restored "
            f"and regenerated directories would not line up."
        )


def clear_cleanup_marker(scenario_directory):
    """
    Remove the cleanup marker (called by get_scenario_inputs after
    regenerating the scenario directory's inputs).
    """
    marker_path = get_cleanup_marker_path(scenario_directory)
    if os.path.exists(marker_path):
        os.remove(marker_path)


def write_cleanup_marker(scenario_directory, action, cleaned_units):
    marker_path = get_cleanup_marker_path(scenario_directory)
    marker_exists = os.path.exists(marker_path)
    with open(marker_path, "a", newline="") as marker_file:
        writer = csv.writer(marker_file)
        if not marker_exists:
            writer.writerow(["timestamp", "action", "cleaned_unit"])
        timestamp = datetime.datetime.now().isoformat(sep=" ")
        for unit in cleaned_units:
            writer.writerow(
                [timestamp, action, unit if unit else SCENARIO_ROOT_UNIT_NAME]
            )


def get_cells_by_cleanup_unit(scenario_structure, granularity="draw"):
    """
    :param granularity: "draw" (the default) groups by the iteration-draw
        directory path; "subproblem" additionally includes the subproblem
        directory in the unit (all of a subproblem's stages stay in one
        unit). For scenarios without subproblem directories the two are the
        same.
    :return: dictionary of {unit_relative_path: [cell_key]} where the unit
        is the directory path relative to the scenario directory ("" when
        the scenario has no directories at the requested granularity) and
        the cell keys are the (weather_iteration, hydro_iteration,
        availability_iteration, subproblem, stage) tuples used in the import
        statuses
    """
    scenario_directory_structure = ScenarioDirectoryStructure(
        scenario_structure
    ).SCENARIO_DIRECTORY_STRUCTURE

    cells_by_unit = {}
    for cell in iterate_directory_structure(scenario_directory_structure):
        unit_components = [
            cell.weather_iteration_str,
            cell.hydro_iteration_str,
            cell.availability_iteration_str,
        ]
        if granularity == "subproblem":
            unit_components.append(cell.subproblem_str)
        unit = os.path.join(*unit_components).rstrip(os.sep)
        cell_key = (
            cell.weather_iteration,
            cell.hydro_iteration,
            cell.availability_iteration,
            cell.subproblem,
            cell.stage,
        )
        cells_by_unit.setdefault(unit, []).append(cell_key)

    return cells_by_unit


def remove_scenario_root_contents(scenario_directory):
    for item in os.listdir(scenario_directory):
        if item in RETAINED_ROOT_ITEMS:
            continue
        item_path = os.path.join(scenario_directory, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)


def archive_unit(scenario_directory, unit, archive_format):
    """
    Write one tarball for the unit into the scenario's archive directory
    (via a temporary name, so an interrupted write can't leave a
    valid-looking partial tarball). Archive member paths are relative to the
    scenario directory, so extracting into the scenario directory restores
    the tree in place.
    """
    archive_directory = os.path.join(scenario_directory, ARCHIVE_DIRECTORY_NAME)
    os.makedirs(archive_directory, exist_ok=True)

    tar_mode, extension = ARCHIVE_FORMATS[archive_format]
    archive_name = (
        unit.replace(os.sep, "__") if unit else "scenario_root_contents"
    ) + extension
    archive_path = os.path.join(archive_directory, archive_name)

    with tarfile.open(archive_path + ".part", tar_mode) as tar:
        if unit:
            tar.add(os.path.join(scenario_directory, unit), arcname=unit)
        else:
            for item in os.listdir(scenario_directory):
                if item not in RETAINED_ROOT_ITEMS:
                    tar.add(os.path.join(scenario_directory, item), arcname=item)
    os.replace(archive_path + ".part", archive_path)


def prune_empty_iteration_parents(scenario_directory, unit):
    """
    After removing e.g. weather_iteration_1/hydro_iteration_2, remove
    weather_iteration_1 too if nothing else is left in it.
    """
    parent = os.path.dirname(unit)
    while parent:
        parent_path = os.path.join(scenario_directory, parent)
        try:
            os.rmdir(parent_path)
        except OSError:
            # Not empty (or already gone): keep it and stop
            break
        parent = os.path.dirname(parent)


def cleanup_scenario_directory(
    scenario_directory,
    scenario_structure,
    import_statuses,
    archive_format=None,
    quiet=False,
    granularity="draw",
):
    """
    :param scenario_directory: the scenario directory to clean
    :param scenario_structure: ScenarioStructure for the scenario
    :param import_statuses: the per-subproblem/stage import statuses
        returned by import_scenario_results
    :param archive_format: None to delete without archiving, or a key of
        ARCHIVE_FORMATS to write one tarball per cleaned unit first
    :param quiet: boolean
    :param granularity: "draw" (the default) retains a draw fully if ANY of
        its subproblems/stages was not imported. "subproblem" additionally
        cleans the imported subproblems WITHIN such partially imported
        draws, retaining only the not-imported subproblems -- useful when a
        single stuck subproblem would otherwise strand a large draw on
        disk. Fully imported draws are always cleaned as one draw unit
        (with one marker row), so re-run resume bookkeeping is identical at
        both granularities; note that re-running a partially cleaned draw
        re-solves its cleaned subproblems (their files are gone), so
        --incomplete_only cannot skip them anymore.
    :return: (cleaned_units, retained_units) lists of unit relative paths

    Delete (or archive, then delete) each iteration draw whose
    subproblems/stages were all imported successfully. Draws with any
    other import status are retained (fully, or minus their imported
    subproblems at "subproblem" granularity), as is the whole directory
    if the import statuses don't cover the directory structure.
    """
    # Local import: import_scenario_results imports this module's marker
    # guard at module level, so this direction must be lazy
    from gridpath.import_scenario_results import IMPORT_STATUS_IMPORTED

    if import_statuses is None:
        raise ValueError(
            "Scenario-directory cleanup requires the import statuses from "
            "a results import in the same run."
        )

    cells_by_unit = get_cells_by_cleanup_unit(scenario_structure)
    cells_by_subproblem_unit = (
        get_cells_by_cleanup_unit(scenario_structure, granularity="subproblem")
        if granularity == "subproblem"
        else {}
    )

    def clean_unit(unit):
        if archive_format is not None:
            archive_unit(
                scenario_directory=scenario_directory,
                unit=unit,
                archive_format=archive_format,
            )
        if unit:
            shutil.rmtree(os.path.join(scenario_directory, unit))
            prune_empty_iteration_parents(scenario_directory, unit)
        else:
            remove_scenario_root_contents(scenario_directory)
        cleaned_units.append(unit)

    cleaned_units = []
    retained_units = []
    for unit, cells in cells_by_unit.items():
        # A unit whose directory no longer exists was already cleaned (e.g.
        # in a previous run): skip it rather than failing on it
        if unit and not os.path.exists(os.path.join(scenario_directory, unit)):
            continue
        if all(import_statuses.get(cell) == IMPORT_STATUS_IMPORTED for cell in cells):
            clean_unit(unit)
        else:
            if granularity == "subproblem":
                # Within a partially imported draw, clean the subproblems
                # whose stages were all imported; the draw stays retained
                # (and is reprocessed in full on a resumed run)
                draw_key = cells[0][:3]
                for (
                    subproblem_unit,
                    subproblem_cells,
                ) in cells_by_subproblem_unit.items():
                    if subproblem_cells[0][:3] != draw_key:
                        continue
                    # No subproblem directories: nothing finer to clean
                    if subproblem_unit == unit:
                        continue
                    if not os.path.exists(
                        os.path.join(scenario_directory, subproblem_unit)
                    ):
                        continue
                    if all(
                        import_statuses.get(cell) == IMPORT_STATUS_IMPORTED
                        for cell in subproblem_cells
                    ):
                        clean_unit(subproblem_unit)
            retained_units.append(unit)

    if cleaned_units:
        action = "archive" if archive_format is not None else "cleanup"
        write_cleanup_marker(
            scenario_directory=scenario_directory,
            action=action,
            cleaned_units=cleaned_units,
        )

    if not quiet:
        action_str = "Archived" if archive_format is not None else "Cleaned up"
        print(
            f"{action_str} {len(cleaned_units)} of {len(cells_by_unit)} "
            f"iteration draw(s) in {scenario_directory}."
        )
        if retained_units:
            print(
                f"Retained {len(retained_units)} draw(s) with "
                f"not-fully-imported results: "
                f"{', '.join(unit if unit else SCENARIO_ROOT_UNIT_NAME for unit in retained_units)}"
            )

    return cleaned_units, retained_units


def cleanup_scenario_directory_for_run(
    db_path,
    scenario_id_arg,
    scenario_name_arg,
    scenario_location,
    import_statuses,
    archive_format,
    quiet,
    temporal_structure_csv_overwrite=False,
    temporal_structure_csv_path=None,
    granularity="draw",
):
    """
    Resolve the scenario directory and structure the same way the results
    import does, then clean up the directory. Called as the final E2E step
    by run_end_to_end.
    """
    conn = connect_to_database(db_path=db_path)
    try:
        c = conn.cursor()
        scenario_id, scenario_name = get_scenario_id_and_name(
            scenario_id_arg=scenario_id_arg,
            scenario_name_arg=scenario_name_arg,
            c=c,
            script="scenario_directory_cleanup",
        )
        if temporal_structure_csv_overwrite:
            scenario_structure = get_scenario_structure_from_csv(
                temporal_structure_csv_path
            )
        else:
            scenario_structure = get_scenario_structure_from_db(
                conn=conn, scenario_id=scenario_id
            )
    finally:
        conn.close()

    scenario_directory = determine_scenario_directory(
        scenario_location=scenario_location, scenario_name=scenario_name
    )

    return cleanup_scenario_directory(
        scenario_directory=scenario_directory,
        scenario_structure=scenario_structure,
        import_statuses=import_statuses,
        archive_format=archive_format,
        quiet=quiet,
        granularity=granularity,
    )
