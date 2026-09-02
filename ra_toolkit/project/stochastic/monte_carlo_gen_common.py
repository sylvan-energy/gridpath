# Copyright 2016-2025 Blue Marble Analytics LLC.
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

from multiprocessing import current_process, get_context
import os.path
import pandas as pd

from ra_toolkit.project.stochastic.iterations import (
    create_iterations_csv,
)

from db.common_functions import connect_to_database

BINS_ID_DEFAULT = 1
DRAWS_ID_DEFAULT = 1
VAR_ID_DEFAULT = 1
VAR_NAME_DEFAULT = "ra_toolkit"
STAGE_ID_DEFAULT = 1


def get_monte_carlo_timeseries_project_pool_and_make_profile_csvs(
    db_path,
    weather_bins_id,
    weather_draws_id,
    output_directory,
    profile_scenario_id,
    profile_scenario_name,
    stage_id,
    overwrite,
    n_parallel_projects,
    units_table,
    param_name,
    raw_data_table,
    study_year,
    print_default_values,
    default_value,
    no_hydro_iteration=False,
):
    conn = connect_to_database(db_path=db_path)

    # Get project units and their weights and timeseries
    df = pd.read_sql(f"""SELECT * FROM {units_table};""", conn)

    # Close before spawning workers: on Windows, holding an open SQLite file
    # handle in the main process conflicts with the spawn workers trying to
    # open the same file (WinError 32). Workers each open their own connection.
    conn.close()

    # Create a dictionary of the form {timeseries: project: [units]}
    timeseries_project_unit_dict = {}

    for index, row in df.iterrows():
        if row["timeseries_name"] not in timeseries_project_unit_dict.keys():
            timeseries_project_unit_dict[row["timeseries_name"]] = {
                row["project"]: [(row["unit"], row["unit_weight"])]
            }
        else:
            if (
                row["project"]
                not in timeseries_project_unit_dict[row["timeseries_name"]].keys()
            ):
                timeseries_project_unit_dict[row["timeseries_name"]][row["project"]] = [
                    (row["unit"], row["unit_weight"])
                ]
            else:
                timeseries_project_unit_dict[row["timeseries_name"]][
                    row["project"]
                ].append((row["unit"], row["unit_weight"]))

    if overwrite:
        for timeseries in timeseries_project_unit_dict.keys():
            for project in timeseries_project_unit_dict[timeseries]:
                filename = os.path.join(
                    output_directory,
                    f"{project}-{profile_scenario_id}-" f"{profile_scenario_name}.csv",
                )

                if os.path.exists(filename):
                    os.remove(filename)

    # Get the respective draws for the timeseries_name and then find the data
    # from the raw_data tables
    pool_data = tuple(
        [
            [
                db_path,
                weather_bins_id,
                weather_draws_id,
                timeseries_project_unit_dict,
                timeseries_name,
                project,
                profile_scenario_id,
                profile_scenario_name,
                stage_id,
                output_directory,
                param_name,
                raw_data_table,
                study_year,
                print_default_values,
                default_value,
                no_hydro_iteration,
            ]
            for timeseries_name in timeseries_project_unit_dict.keys()
            for project in timeseries_project_unit_dict[timeseries_name].keys()
        ]
    )

    # Pool must use spawn to work properly on Linux.
    # Guard against re-entry on Windows: spawn re-imports __main__ in each
    # worker, triggering this function again. parent_process() looks correct
    # but is set in _bootstrap(), which runs *after* prepare() re-imports
    # __main__, so it's still None when the guard is evaluated. Use
    # current_process().name instead — it's set during prepare() before the
    # __main__ import.
    if current_process().name != "MainProcess":
        return

    pool = get_context("spawn").Pool(int(n_parallel_projects))

    pool.map(create_project_profile_csv_pool, pool_data)
    pool.close()
    pool.join()


def create_project_profile_csv(
    db_path,
    weather_bins_id,
    weather_draws_id,
    timeseries_project_unit_dict,
    timeseries_name,
    project,
    profile_scenario_id,
    profile_scenario_name,
    stage_id,
    output_directory,
    param_name,
    raw_data_table,
    study_year,
    print_default_values,
    default_value,
    no_hydro_iteration=False,
):
    # Connect to database
    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    # Get all the draws
    draws = c.execute(f"""
                SELECT weather_iteration, draw_number,
                {timeseries_name}_year, {timeseries_name}_month,
                {timeseries_name}_day_of_month
                FROM aux_weather_iterations
                WHERE weather_bins_id = {weather_bins_id}
                AND weather_draws_id = {weather_draws_id}
                ORDER BY weather_iteration, draw_number
                ;
                """).fetchall()

    for weather_iteration, draw_number, year, month, day_of_month in draws:
        # For each project, get the weighted cap factor for each of its
        # constituent units, get the UNION of these tables, and then find
        # the project cap factor with SUM and GROUP BY
        unit_queries = [
            f"""
            SELECT year, month, day_of_month, hour_of_day, unit, 
            value * {weight} as weighted_{param_name}
            FROM {raw_data_table}
            WHERE year = {year}
            AND month = {month}
            AND day_of_month = {day_of_month}
            AND unit = '{unit}'
            """
            for (unit, weight) in timeseries_project_unit_dict[timeseries_name][project]
        ]

        union_query = " UNION ".join(unit_queries)

        # Get the project cap factor
        # TODO: start draw numbers at 0 and remove -1 here
        # We're assuming draws are days, so multiplying the draw
        # number by 24 here, then adding hour of day to get the
        # timepoint ID
        hydro_iter_sql = "" if no_hydro_iteration else "0 AS hydro_iteration,"
        project_query = (
            f"""
                SELECT {weather_iteration} AS weather_iteration,  
                {hydro_iter_sql}
                {stage_id} AS stage_id,
                {study_year}*10000+({draw_number}-1)*24+hour_of_day AS 
                timepoint, 
                sum(weighted_{param_name}) as {param_name}
                FROM (
            """
            + union_query
            + f""")
            GROUP BY year, month, day_of_month, hour_of_day
            ORDER BY year, month, day_of_month, hour_of_day
            ;
            """
        )

        # Put into a dataframe and add to file
        df = pd.read_sql(project_query, con=conn)

        # Filter out rows where the value is the default, unless
        # print_default_values is True
        if not print_default_values:
            df = df[df[param_name] != default_value]

        filename = os.path.join(
            output_directory,
            f"{project}-{profile_scenario_id}-" f"{profile_scenario_name}.csv",
        )

        if not os.path.exists(filename):
            mode = "w"
            write_header = True
        else:
            mode = "a"
            write_header = False

        df.to_csv(
            filename,
            mode=mode,
            header=write_header,
            index=False,
        )

        # Create iterations CSV
        iterations_directory = os.path.join(output_directory, "iterations")
        os.makedirs(iterations_directory, exist_ok=True)
        create_iterations_csv(
            iterations_directory=iterations_directory,
            project=project,
            profile_id=profile_scenario_id,
            profile_name=profile_scenario_name,
            varies_by_weather=1,
            varies_by_hydro=0,
            overwrite=True,
        )

    conn.commit()
    conn.close()


def create_project_profile_csv_pool(pool_datum):
    [
        db_path,
        weather_bins_id,
        weather_draws_id,
        timeseries_project_unit_dict,
        timeseries_name,
        project,
        variable_generator_profile_scenario_id,
        variable_generator_profile_scenario_name,
        stage_id,
        output_directory,
        param_name,
        raw_data_table,
        study_year,
        print_default_values,
        default_value,
        no_hydro_iteration,
    ] = pool_datum

    create_project_profile_csv(
        db_path=db_path,
        weather_bins_id=weather_bins_id,
        weather_draws_id=weather_draws_id,
        timeseries_project_unit_dict=timeseries_project_unit_dict,
        timeseries_name=timeseries_name,
        project=project,
        profile_scenario_id=variable_generator_profile_scenario_id,
        profile_scenario_name=variable_generator_profile_scenario_name,
        stage_id=stage_id,
        output_directory=output_directory,
        param_name=param_name,
        raw_data_table=raw_data_table,
        study_year=study_year,
        print_default_values=print_default_values,
        default_value=default_value,
        no_hydro_iteration=no_hydro_iteration,
    )
