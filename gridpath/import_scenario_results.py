# Copyright 2016-2023 Blue Marble Analytics LLC.
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
This script iterates over all modules required for a GridPath scenario and
calls their *import_results_into_database()* method, which loads the
scenario results files into their respective database table.

The main()_ function of this script can also be called with the
*gridpath_import_results* command when GridPath is installed.

The import assigns each (weather iteration, hydro iteration, availability
iteration, subproblem, stage) an import status -- see the
``IMPORT_STATUS_*`` constants -- and *main()* returns the statuses as a
dictionary keyed by that tuple. If results were imported for none or only some of the
subproblems/stages, a warning is printed regardless of the --quiet setting:
skipped subproblems are otherwise silent, and, since all prior results for
the scenario are deleted at the start of the import step, an import that
skips everything leaves the scenario with no results in the database while
appearing to have succeeded.
"""

import warnings
from argparse import ArgumentParser
import datetime
import os.path
import pandas as pd
import sys

from gridpath.auxiliary.db_interface import get_scenario_id_and_name
from gridpath.auxiliary.import_export_rules import import_export_rules
from gridpath.common_functions import (
    determine_scenario_directory,
    get_db_parser,
    get_required_e2e_arguments_parser,
    get_temporal_structure_csv_overwrite_parser,
    get_import_results_parser,
    get_version_parser,
    ensure_empty_string,
)
from db.common_functions import (
    connect_to_database,
    spin_on_database_lock,
    update_db_last_modified,
)
from db.utilities.scenario import delete_scenario_results
from gridpath.auxiliary.module_list import determine_modules, load_modules
from gridpath.auxiliary.scenario_chars import (
    get_scenario_structure_from_db,
    get_scenario_structure_from_csv,
    ScenarioDirectoryStructure,
)

# Statuses assigned to each (weather iteration, hydro iteration,
# availability iteration, subproblem, stage) during results import
IMPORT_STATUS_IMPORTED = "imported"
# Solver status file not found (only reachable with --ignore_incomplete;
# without it, a missing file raises)
IMPORT_STATUS_SKIPPED_NOT_SOLVED = "skipped_not_solved"
IMPORT_STATUS_SKIPPED_SOLVER_STATUS_NOT_OK = "skipped_solver_status_not_ok"
# Module results skipped by the results-import rule; the termination
# condition and objective function value are still recorded
IMPORT_STATUS_SKIPPED_BY_IMPORT_RULE = "skipped_by_import_rule"


def _import_rule(results_directory, quiet):
    """
    :return: boolean

    Rule for whether to import results for a subproblem/stage. Write your
    custom rule here to use this functionality. Must return True or False.
    """
    import_results = True

    return import_results


def import_scenario_results_into_database(
    import_rule,
    loaded_modules,
    scenario_id,
    scenario_structure,
    db,
    scenario_directory,
    ignore_incomplete,
    quiet,
):
    """
    :param import_rule:
    :param loaded_modules:
    :param scenario_id:
    :param scenario_structure:
    :param db:
    :param scenario_directory:
    :param ignore_incomplete: boolean
    :param quiet: boolean

    :return: dictionary keyed by (weather_iteration, hydro_iteration,
        availability_iteration, subproblem, stage) tuples (integers, 0 where
        the level does not apply) with the ``IMPORT_STATUS_*`` constant for
        each
    """

    scenario_directory_structure = ScenarioDirectoryStructure(
        scenario_structure
    ).SCENARIO_DIRECTORY_STRUCTURE

    import_statuses = {}

    # Hydro years first
    for weather_iteration_str in scenario_directory_structure.keys():
        for hydro_iteration_str in scenario_directory_structure[
            weather_iteration_str
        ].keys():
            for availability_iteration_str in scenario_directory_structure[
                weather_iteration_str
            ][hydro_iteration_str]:
                # We may have passed "empty_string" to avoid actual empty
                # strings as dictionary keys; convert to actual empty
                # strings here to pass to the directory creation methods
                weather_iteration_str = ensure_empty_string(weather_iteration_str)
                hydro_iteration_str = ensure_empty_string(hydro_iteration_str)
                availability_iteration_str = ensure_empty_string(
                    availability_iteration_str
                )

                weather_iteration = (
                    0
                    if weather_iteration_str == ""
                    else int(weather_iteration_str.replace("weather_iteration_", ""))
                )
                hydro_iteration = (
                    0
                    if hydro_iteration_str == ""
                    else int(hydro_iteration_str.replace("hydro_iteration_", ""))
                )
                availability_iteration = (
                    0
                    if availability_iteration_str == ""
                    else int(
                        availability_iteration_str.replace(
                            "availability_iteration_", ""
                        )
                    )
                )
                for subproblem_str in scenario_directory_structure[
                    weather_iteration_str
                ][hydro_iteration_str][availability_iteration_str].keys():
                    subproblem = 0 if subproblem_str == "" else int(subproblem_str)
                    for stage_str in scenario_directory_structure[
                        weather_iteration_str
                    ][hydro_iteration_str][availability_iteration_str][subproblem_str]:
                        stage = 0 if stage_str == "" else int(stage_str)
                        results_directory = os.path.join(
                            scenario_directory,
                            weather_iteration_str,
                            hydro_iteration_str,
                            availability_iteration_str,
                            subproblem_str,
                            stage_str,
                            "results",
                        )
                        if not quiet:
                            current_suproblem = os.path.join(
                                weather_iteration_str,
                                hydro_iteration_str,
                                availability_iteration_str,
                                subproblem_str,
                                stage_str,
                            )
                            if current_suproblem.endswith("/"):
                                current_suproblem = current_suproblem[:-1]

                            print(f"--- subproblem: {current_suproblem}")

                        # Import termination condition data
                        c = db.cursor()
                        try:
                            with open(
                                os.path.join(
                                    results_directory, "termination_condition.txt"
                                ),
                                "r",
                            ) as f:
                                termination_condition = f.read()
                        except FileNotFoundError:
                            if ignore_incomplete:
                                warnings.warn(
                                    "GridPath Warning: termination "
                                    "condition file not found."
                                )
                                termination_condition = (
                                    "termination condition file not found"
                                )
                            else:
                                tc_fname = os.path.join(
                                    results_directory, "termination_condition.txt"
                                )
                                raise FileNotFoundError(f"{tc_fname} not " f"found.")

                        termination_condition_sql = """
                            INSERT INTO results_scenario
                            (scenario_id, weather_iteration, hydro_iteration, availability_iteration, subproblem_id, 
                            stage_id, solver_termination_condition)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ;"""

                        termination_condition_data = (
                            scenario_id,
                            weather_iteration,
                            hydro_iteration,
                            availability_iteration,
                            subproblem,
                            stage,
                            termination_condition,
                        )
                        spin_on_database_lock(
                            conn=db,
                            cursor=c,
                            sql=termination_condition_sql,
                            data=termination_condition_data,
                            many=False,
                        )

                        try:
                            with open(
                                os.path.join(results_directory, "solver_status.txt"),
                                "r",
                            ) as status_f:
                                solver_status = status_f.read()
                        except FileNotFoundError:
                            if ignore_incomplete:
                                warnings.warn(
                                    "GridPath Warning: solver status " "file not found."
                                )
                                solver_status = None
                            else:
                                ss_fname = os.path.join(
                                    results_directory, "solver_status.txt"
                                )
                                raise FileNotFoundError(f"{ss_fname} not found.")

                        cell = (
                            weather_iteration,
                            hydro_iteration,
                            availability_iteration,
                            subproblem,
                            stage,
                        )

                        # Only import other results if solver status was "ok"
                        # When the problem is infeasible, the solver status is "warning"
                        # If there's no solution, variables remain uninitialized,
                        # throwing an error at some point during results-export,
                        # so we don't attempt to import missing results into the database
                        if solver_status == "ok":
                            import_objective_function_value(
                                db=db,
                                scenario_id=scenario_id,
                                weather_iteration=weather_iteration,
                                hydro_iteration=hydro_iteration,
                                availability_iteration=availability_iteration,
                                subproblem=subproblem,
                                stage=stage,
                                results_directory=results_directory,
                            )
                            module_results_imported = (
                                import_subproblem_stage_results_into_database(
                                    import_rule=import_rule,
                                    conn=db,
                                    scenario_id=scenario_id,
                                    weather_iteration=weather_iteration_str,
                                    hydro_iteration=hydro_iteration_str,
                                    availability_iteration=availability_iteration_str,
                                    subproblem=subproblem_str,
                                    stage=stage_str,
                                    results_directory=results_directory,
                                    loaded_modules=loaded_modules,
                                    quiet=quiet,
                                )
                            )
                            import_statuses[cell] = (
                                IMPORT_STATUS_IMPORTED
                                if module_results_imported
                                else IMPORT_STATUS_SKIPPED_BY_IMPORT_RULE
                            )
                        elif solver_status is None:
                            import_statuses[cell] = IMPORT_STATUS_SKIPPED_NOT_SOLVED
                        else:
                            import_statuses[cell] = (
                                IMPORT_STATUS_SKIPPED_SOLVER_STATUS_NOT_OK
                            )
                            if not quiet:
                                print(f"""
                                Solver status for weather iteration {weather_iteration_str},
                                hydro_iteration {hydro_iteration_str}, subproblem {subproblem_str},
                                stage {stage_str} was '{solver_status}',
                                not 'ok', so there are no results to import.
                                Termination condition was '{termination_condition}'.
                                """)

    return import_statuses


def import_objective_function_value(
    db,
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    results_directory,
):
    """
    Import the objective function value for the subproblem/stage. Delete
    prior results first.
    """

    c = db.cursor()
    with open(
        os.path.join(results_directory, "objective_function_value.txt"), "r"
    ) as f:
        objective_function = f.read()

    obj_sql = """
        UPDATE results_scenario
        SET objective_function_value = ?
        WHERE scenario_id = ?
        AND weather_iteration = ?
        AND hydro_iteration = ?
        AND availability_iteration = ?
        AND subproblem_id = ?
        AND stage_id = ?
    ;"""

    obj_data = (
        objective_function,
        scenario_id,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    )
    spin_on_database_lock(conn=db, cursor=c, sql=obj_sql, data=obj_data, many=False)


def import_subproblem_stage_results_into_database(
    import_rule,
    conn,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    scenario_id,
    subproblem,
    stage,
    results_directory,
    loaded_modules,
    quiet,
):
    """
    Import results for a subproblem/stage. We first check the import rule to
    determine whether to import.

    :return: boolean, whether module results were imported (False if skipped
        based on the import rule)
    """
    if import_rule is None:
        import_results = _import_rule(results_directory=results_directory, quiet=quiet)
    else:
        import_results = import_export_rules[import_rule]["import"](
            results_directory=results_directory, quiet=quiet
        )

    if import_results:
        c = conn.cursor()
        for m in loaded_modules:
            if hasattr(m, "import_results_into_database"):
                m.import_results_into_database(
                    scenario_id=scenario_id,
                    weather_iteration=weather_iteration,
                    hydro_iteration=hydro_iteration,
                    availability_iteration=availability_iteration,
                    subproblem=subproblem,
                    stage=stage,
                    c=c,
                    db=conn,
                    results_directory=results_directory,
                    quiet=quiet,
                )
    else:
        if not quiet:
            print("Results-import skipped based on import rule.")

    return import_results


def warn_on_import_gaps(import_statuses):
    """
    :param import_statuses: dictionary of import statuses by
        (weather_iteration, hydro_iteration, availability_iteration,
        subproblem, stage), as returned by
        import_scenario_results_into_database()

    Print a warning -- deliberately regardless of the --quiet setting -- if
    results were imported for none or only some of the scenario's
    subproblems/stages. Skipped subproblems are otherwise silent and an
    import that skips everything looks identical to a successful one, while
    all prior results for the scenario have already been deleted at the
    start of the import step.
    """
    n_total = len(import_statuses)
    n_imported = sum(
        1 for status in import_statuses.values() if status == IMPORT_STATUS_IMPORTED
    )

    if n_imported == n_total:
        return

    cells_by_status = {}
    for cell, status in import_statuses.items():
        if status != IMPORT_STATUS_IMPORTED:
            cells_by_status.setdefault(status, []).append(cell)

    if n_imported == 0:
        header = (
            f"WARNING: results were imported for NONE of the {n_total} "
            f"subproblems/stages of this scenario. Prior results for the "
            f"scenario were deleted at the start of the import step, so the "
            f"database now contains no results for this scenario."
        )
    else:
        header = (
            f"WARNING: results were imported for only {n_imported} of "
            f"{n_total} subproblems/stages of this scenario."
        )

    lines = [header]
    max_examples = 10
    for status, cells in cells_by_status.items():
        examples = ", ".join(str(cell) for cell in cells[:max_examples])
        if len(cells) > max_examples:
            examples += f", ... and {len(cells) - max_examples} more"
        lines.append(
            f"  {status}: {len(cells)} subproblem/stage(s) "
            f"(weather_iteration, hydro_iteration, availability_iteration, "
            f"subproblem, stage): {examples}"
        )

    print("\n".join(lines))


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    :param args:
    :return:
    """
    parser = ArgumentParser(
        add_help=True,
        parents=[
            get_db_parser(),
            get_required_e2e_arguments_parser(),
            get_temporal_structure_csv_overwrite_parser(),
            get_import_results_parser(),
            get_version_parser(),
        ],
    )
    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    """
    :return: dictionary of import statuses by (weather_iteration,
        hydro_iteration, availability_iteration, subproblem, stage) -- see
        import_scenario_results_into_database()
    """
    if args is None:
        args = sys.argv[1:]

    parsed_arguments = parse_arguments(args=args)

    db_path = parsed_arguments.database
    scenario_id_arg = parsed_arguments.scenario_id
    scenario_name_arg = parsed_arguments.scenario
    scenario_location = parsed_arguments.scenario_location
    quiet = parsed_arguments.quiet
    import_rule = parsed_arguments.results_import_rule
    ignore_incomplete = parsed_arguments.ignore_incomplete
    temporal_structure_csv_overwrite = parsed_arguments.temporal_structure_csv_overwrite
    temporal_structure_csv_path = parsed_arguments.temporal_structure_csv_path

    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    if not parsed_arguments.quiet:
        print(
            "Importing results, started on {}... (connected to database {})".format(
                datetime.datetime.now(), db_path
            )
        )

    scenario_id, scenario_name = get_scenario_id_and_name(
        scenario_id_arg=scenario_id_arg,
        scenario_name_arg=scenario_name_arg,
        c=c,
        script="import_scenario_results",
    )

    if temporal_structure_csv_overwrite:
        scenario_structure = get_scenario_structure_from_csv(
            temporal_structure_csv_path
        )
    else:
        scenario_structure = get_scenario_structure_from_db(
            conn=conn, scenario_id=scenario_id
        )

    # Determine scenario directory
    scenario_directory = determine_scenario_directory(
        scenario_location=scenario_location, scenario_name=scenario_name
    )

    # Check that the saved scenario_id matches
    sc_df = pd.read_csv(
        os.path.join(scenario_directory, "scenario_description.csv"),
        header=None,
        index_col=0,
    )
    scenario_id_saved = int(sc_df.loc["scenario_id", 1])
    if scenario_id_saved != scenario_id:
        raise AssertionError("ERROR: saved scenario_id does not match")

    # Delete all previous results for this scenario_id
    # Each module also makes sure results are deleted, but this step ensures
    # that if a scenario_id was run with different modules before, we also
    # delete previously imported "phantom" results
    delete_scenario_results(conn=conn, scenario_id=scenario_id)

    # Go through modules
    modules_to_use = determine_modules(scenario_directory=scenario_directory)
    loaded_modules = load_modules(modules_to_use)

    # Import appropriate results into database
    import_statuses = import_scenario_results_into_database(
        import_rule=import_rule,
        loaded_modules=loaded_modules,
        scenario_id=scenario_id,
        scenario_structure=scenario_structure,
        db=conn,
        scenario_directory=scenario_directory,
        ignore_incomplete=ignore_incomplete,
        quiet=quiet,
    )

    update_db_last_modified(conn=conn, modification_type="results_import")

    # Close the database connection
    conn.commit()
    conn.close()

    if not quiet:
        n_imported = sum(
            1 for status in import_statuses.values() if status == IMPORT_STATUS_IMPORTED
        )
        print(
            f"Imported results for {n_imported} of {len(import_statuses)} "
            f"subproblems/stages."
        )
    warn_on_import_gaps(import_statuses)

    return import_statuses


if __name__ == "__main__":
    main()
