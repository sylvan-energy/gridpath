# Copyright 2016-2023 Blue Marble Analytics LLC.
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

import os.path
import pandas as pd

from db.common_functions import spin_on_database_lock, spin_on_database_lock_generic


def get_required_capacity_types_from_database(conn, scenario_id):
    """
    Get the required type modules based on the database inputs
    for the specified scenario_id. Required modules are the unique set of
    generator capacity types in the scenario's portfolio.

    :param conn: database connection
    :param scenario_id: int, user-specified scenario ID
    :return: List of the required type modules
    """
    c = conn.cursor()

    project_portfolio_scenario_id = c.execute("""SELECT project_portfolio_scenario_id 
        FROM scenarios 
        WHERE scenario_id = {}""".format(scenario_id)).fetchone()[0]

    required_capacity_type_modules = [
        p[0]
        for p in c.execute(
            """SELECT DISTINCT capacity_type 
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = ?""",
            (project_portfolio_scenario_id,),
        ).fetchall()
    ]

    return required_capacity_type_modules


# TODO: handle non-existing scenarios/scenario_ids
def get_scenario_id_and_name(scenario_id_arg, scenario_name_arg, c, script):
    """
    Get the scenario_id and the scenario_ name. Usually only one is given (the
    other one will be 'None'), so this functions determine the missing one from
    the one that is provided. If both are provided, this function checks
    whether they match.

    :param scenario_id_arg:
    :param scenario_name_arg:
    :param c:
    :param script:
    :return: (scenario_id, scenario_name)
    """

    if scenario_id_arg is None and scenario_name_arg is None:
        raise TypeError(
            """ERROR: Either scenario_id or scenario_name must be specified. 
            Run 'python """ + script + """'.py --help' for help."""
        )

    elif scenario_id_arg is not None and scenario_name_arg is None:
        result = c.execute("""SELECT scenario_name
               FROM scenarios
               WHERE scenario_id = {};""".format(scenario_id_arg)).fetchone()
        if result is None:
            raise ValueError(
                """ERROR: No matching scenario found for scenario_id '{}'""".format(
                    scenario_id_arg
                )
            )
        else:
            return scenario_id_arg, result[0]

    elif scenario_id_arg is None and scenario_name_arg is not None:
        result = c.execute("""SELECT scenario_id
               FROM scenarios
               WHERE scenario_name = '{}';""".format(scenario_name_arg)).fetchone()
        if result is None:
            raise ValueError(
                """ERROR: No matching scenario found for scenario_name '{}'""".format(
                    scenario_name_arg
                )
            )
        else:
            return result[0], scenario_name_arg

    else:
        # If both scenario_id and scenario_name are specified
        result = c.execute("""SELECT scenario_name
               FROM scenarios
               WHERE scenario_id = {};""".format(scenario_id_arg)).fetchone()
        if result is None:
            raise ValueError(
                """ERROR: No matching scenario found for scenario_id '{}'""".format(
                    scenario_id_arg
                )
            )
        elif result[0] != scenario_name_arg:
            raise ValueError("""ERROR: scenario_id and scenario_name don't match in 
                database.""")
        else:
            return scenario_id_arg, scenario_name_arg


def get_results_table_iteration_keys(
    weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
):
    """
    Convert the directory-name strings for a subproblem/stage to the integer
    keys used in the results tables: 0 for iteration levels the scenario
    doesn't use, 1 for an absent subproblem/stage.
    """
    return (
        (
            0
            if weather_iteration == ""
            else int(str(weather_iteration).replace("weather_iteration_", ""))
        ),
        (
            0
            if hydro_iteration == ""
            else int(str(hydro_iteration).replace("hydro_iteration_", ""))
        ),
        (
            0
            if availability_iteration == ""
            else int(str(availability_iteration).replace("availability_iteration_", ""))
        ),
        1 if subproblem == "" else int(subproblem),
        1 if stage == "" else int(stage),
    )


def import_csv(
    conn,
    cursor,
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    quiet,
    results_directory,
    which_results,
):
    # First import the capacity_all results; the capacity type modules will
    # then update the database tables rather than insert (all projects
    # should have been inserted here)
    # Delete prior results and create temporary import table for ordering
    if not quiet:
        print(which_results)

    results_filepath = os.path.join(results_directory, f"{which_results}.csv")
    if not os.path.exists(results_filepath):
        if not quiet:
            print("...not found, skipping...")
    else:
        df = pd.read_csv(results_filepath)
        df["scenario_id"] = scenario_id

        # TODO: DB defaults need to be specified somewhere
        (
            df["weather_iteration"],
            df["hydro_iteration"],
            df["availability_iteration"],
            df["subproblem_id"],
            df["stage_id"],
        ) = get_results_table_iteration_keys(
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
        )

        spin_on_database_lock_generic(
            command=df.to_sql(
                name=f"results_{which_results}",
                con=conn,
                if_exists="append",
                index=False,
            )
        )


def update_prj_zone_column(
    conn, scenario_id, subscenarios, subscenario, subsc_tbl, prj_tbl, col
):
    """
    :param conn:
    :param scenario_id:
    :param subscenarios:
    :param subscenario:
    :param prj_tbl:
    :param col:

    Update a column of a project table based on the scenario's relevant
    subscenario ID.
    """
    c = conn.cursor()

    # Determine the zones for each project
    project_zones = c.execute(
        """SELECT project, {}
            FROM {}
            WHERE {} = {}""".format(
            col, subsc_tbl, subscenario, getattr(subscenarios, subscenario.upper())
        )
    ).fetchall()

    updates = []
    for prj, zone in project_zones:
        updates.append((zone, scenario_id, prj))

    sql = """
        UPDATE {}
        SET {} = ?
        WHERE scenario_id = ?
        AND project = ?;
        """.format(prj_tbl, col)
    spin_on_database_lock(conn=conn, cursor=c, sql=sql, data=updates)


def determine_table_subset_by_start_and_column(conn, tbl_start, cols):
    """
    :param conn:
    :param tbl_start: str
    :param cols: list of column names
    :return: list of table names

    Determine which tables that start with a particular string have a
    particular column.
    """
    all_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    table_subset = []

    c = conn.cursor()
    for tbl_tuple in all_tables:
        table = tbl_tuple[0]
        if table.startswith(tbl_start):
            table_data_query = c.execute("""SELECT * FROM {};""".format(table))
            column_names = [s[0] for s in table_data_query.description]
            if all(col in column_names for col in cols):
                table_subset.append(table)

    return table_subset


def directories_to_db_values(
    weather_iteration_dir,
    hydro_iteration_dir,
    availability_iteration_dir,
    subproblem,
    stage,
):
    db_weather_iteration = (
        0
        if weather_iteration_dir == ""
        else int(weather_iteration_dir.replace("weather_iteration_", ""))
    )
    db_hydro_iteration = (
        0
        if hydro_iteration_dir == ""
        else int(hydro_iteration_dir.replace("hydro_iteration_", ""))
    )
    db_availability_iteration = (
        0
        if availability_iteration_dir == ""
        else int(availability_iteration_dir.replace("availability_iteration_", ""))
    )
    db_subproblem = 1 if subproblem == "" else subproblem
    db_stage = 1 if stage == "" else stage

    return (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    )
