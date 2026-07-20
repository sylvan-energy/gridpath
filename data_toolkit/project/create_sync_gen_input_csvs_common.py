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
from argparse import Namespace
from multiprocessing import get_context
from sqlite3 import Connection

import pandas as pd

from data_toolkit.project.common_methods import create_iterations_csv
from db.common_functions import connect_to_database


def get_sync_project_pool_and_make_profile_csvs(
    db_path,
    param_name,
    raw_data_table_name,
    raw_data_units_table_name,
    profile_scenario_id,
    profile_scenario_name,
    stage_id,
    output_directory,
    overwrite,
    varies_by_weather,
    varies_by_hydro,
    include_hydro_iteration_column,
    n_parallel_projects,
    print_default_values,
    default_value,
):

    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    projects = [
        prj[0]
        for prj in c.execute(
            f"SELECT DISTINCT project FROM {raw_data_units_table_name};"
        ).fetchall()
    ]

    pool_data = tuple(
        [
            [
                db_path,
                prj,
                param_name,
                raw_data_table_name,
                raw_data_units_table_name,
                profile_scenario_id,
                profile_scenario_name,
                stage_id,
                output_directory,
                overwrite,
                varies_by_weather,
                varies_by_hydro,
                include_hydro_iteration_column,
                print_default_values,
                default_value,
            ]
            for prj in projects
        ]
    )

    # Pool must use spawn to work properly on Linux
    pool = get_context("spawn").Pool(int(n_parallel_projects))

    pool.map(create_project_profile_csv_pool, pool_data)
    pool.close()
    pool.join()

    conn.close()


def create_project_profile_csv(
    db_path,
    project,
    profile_scenario_id,
    profile_scenario_name,
    stage_id,
    output_directory,
    overwrite,
    param_name,
    raw_data_table_name,
    raw_data_units_table_name,
    varies_by_weather,
    varies_by_hydro,
    include_hydro_iteration_column,
    print_default_values,
    default_value,
):
    conn = connect_to_database(db_path=db_path)

    # Get the weighted value for each of the project's constituent units,
    # get the UNION of these tables, and then find the project value
    # with SUM and GROUP BY
    hydro_iter_sql = "0 AS hydro_iteration," if include_hydro_iteration_column else ""
    query = f"""
        SELECT year AS weather_iteration, 
        {hydro_iter_sql}
        {stage_id} AS stage_id, 
        hour_of_year as timepoint, sum(weighted_{param_name}) as {param_name}
            FROM (
            SELECT year, month, day_of_month, hour_of_day, unit, 
            project, unit_weight, value, unit_weight * value as 
            weighted_{param_name},
                (CAST(
                    strftime('%j',
                        year || '-' || 
                        CASE
                        WHEN month > 9 THEN month
                        ELSE '0' || month END
                        || '-' || 
                        CASE
                        WHEN day_of_month > 9 THEN day_of_month
                        ELSE '0' || day_of_month END
                        ) AS DECIMAL
                    ) - 1) * 24 + hour_of_day AS hour_of_year
            FROM {raw_data_table_name}
            JOIN {raw_data_units_table_name}
            USING (unit)
            WHERE project = '{project}'
            )
        GROUP BY year, hour_of_year
        ORDER BY year, hour_of_year
    """

    # Put into a dataframe and add to file
    df = pd.read_sql(query, con=conn)

    # Filter out rows where the value is at the default, unless
    # print_default_values is True
    if not print_default_values:
        df = df[df[param_name] != default_value]

    filename = os.path.join(
        output_directory,
        f"{project}-{profile_scenario_id}-" f"{profile_scenario_name}.csv",
    )

    if overwrite:
        mode = "w"
    else:
        mode = "a"

    write_header = not os.path.exists(filename)

    df.to_csv(
        filename,
        mode=mode,
        header=True if mode == "w" or write_header else False,
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
        varies_by_weather=varies_by_weather,
        varies_by_hydro=varies_by_hydro,
        overwrite=overwrite,
    )

    conn.commit()
    conn.close()


def create_project_profile_csv_pool(pool_datum):
    [
        db_path,
        project,
        param_name,
        raw_data_table_name,
        raw_data_units_table_name,
        profile_scenario_id,
        profile_scenario_name,
        stage_id,
        output_directory,
        overwrite,
        varies_by_weather,
        varies_by_hydro,
        include_hydro_iteration_column,
        print_default_values,
        default_value,
    ] = pool_datum

    create_project_profile_csv(
        db_path=db_path,
        project=project,
        profile_scenario_id=profile_scenario_id,
        profile_scenario_name=profile_scenario_name,
        stage_id=stage_id,
        output_directory=output_directory,
        overwrite=overwrite,
        param_name=param_name,
        raw_data_table_name=raw_data_table_name,
        raw_data_units_table_name=raw_data_units_table_name,
        varies_by_weather=varies_by_weather,
        varies_by_hydro=varies_by_hydro,
        include_hydro_iteration_column=include_hydro_iteration_column,
        print_default_values=print_default_values,
        default_value=default_value,
    )
