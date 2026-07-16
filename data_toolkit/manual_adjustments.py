# Copyright 2016-2024 Blue Marble Analytics LLC.
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

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import duckdb
import os.path
import shutil
import sys
import pandas as pd

from db.common_functions import connect_to_database
from data_toolkit.load_raw_data import read_and_import_csv
from data_toolkit.project.project_data_filters_common import (
    get_eia860_sql_filter_string,
    DISAGG_PROJECT_NAME_STR,
    AGG_PROJECT_NAME_STR,
)

# Storage durations
STORAGE_DURATION_DEFAULTS = {"BA": 1, "PS": 12}
SPEC_CAP_ID_DEFAULT = 1
SPEC_CAP_NAME_DEFAULT = "base"
STUDY_YEAR_DEFAULT = 2026
REGION_DEFAULT = "WECC"


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="../../open_data_raw.db")

    # Missing storage durations
    parser.add_argument(
        "-copy",
        "--files_to_copy_csv",
        default="../db/csvs_open_data/raw_data"
        "/user_defined_manual_adjustments_copy_files.csv",
    )

    # Missing storage durations
    parser.add_argument(
        "-cap_dir",
        "--capacity_specified_directory",
        default="../../csvs_open_data/project/capacity_specified",
    )
    parser.add_argument(
        "-cap_id",
        "--project_specified_capacity_scenario_id",
        default=SPEC_CAP_ID_DEFAULT,
    )
    parser.add_argument(
        "-cap_name",
        "--project_specified_capacity_scenario_name",
        default=SPEC_CAP_NAME_DEFAULT,
    )
    parser.add_argument("-y", "--study_year", default=STUDY_YEAR_DEFAULT)
    parser.add_argument("-r", "--region", default=REGION_DEFAULT)
    parser.add_argument(
        "-ba_dur",
        "--battery_duration",
        default=STORAGE_DURATION_DEFAULTS["BA"],
        help=f"Defaults to '{STORAGE_DURATION_DEFAULTS['PS']}'.",
    )
    parser.add_argument(
        "-ps_dur",
        "--pumped_storage_duration",
        default=STORAGE_DURATION_DEFAULTS["PS"],
        help=f"Defaults to '{STORAGE_DURATION_DEFAULTS['PS']}'.",
    )

    # Overwrite existing files
    parser.add_argument(
        "-o",
        "--overwrite",
        default=False,
        action="store_true",
        help="Overwrite existing CSV files.",
    )

    parser.add_argument(
        "-agg",
        "--aggregate_projects",
        default=False,
        action="store_true",
        help="Aggregate all projects to the BA-technology level.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def make_copy_files(
    new_file_directory,
    new_project,
    new_project_scenario_id,
    new_project_scenario_name,
    file_to_copy_directory,
    copy_project,
    copy_project_scenario_id,
    copy_project_scenario_name,
):

    file_to_copy = os.path.join(
        file_to_copy_directory,
        f"{copy_project}-{copy_project_scenario_id}-{copy_project_scenario_name}.csv",
    )

    new_file = os.path.join(
        new_file_directory,
        f"{new_project}-{new_project_scenario_id}-{new_project_scenario_name}_MANUAL_copy_from"
        f"_{copy_project}_{copy_project_scenario_id}.csv",
    )

    shutil.copyfile(file_to_copy, new_file)


def add_battery_durations(
    conn,
    project_name_str,
    study_year,
    eia860_sql_filter_string,
    csv_location,
    subscenario_id,
    subscenario_name,
    tech_dur_dict,
    aggregate_projects=False,
):
    duckdb_conn = duckdb.connect(database=":memory:")
    spec_cap_df = pd.read_csv(
        os.path.join(csv_location, f"{subscenario_id}_" f"{subscenario_name}.csv")
    )

    spec_cap_updated_df = duckdb_conn.sql(
        """CREATE TABLE spec_cap_table AS SELECT * FROM spec_cap_df;"""
    )

    for tech in tech_dur_dict.keys():
        group_by = "GROUP BY project" if aggregate_projects else ""
        sql = f"""
            SELECT {project_name_str} AS project,
            {study_year} as period
            FROM raw_data_eia860_generators
            JOIN user_defined_eia_gridpath_key ON
                    raw_data_eia860_generators.prime_mover_code =
                    user_defined_eia_gridpath_key.prime_mover_code
                    AND energy_source_code_1 = energy_source_code
            WHERE 1 = 1
            AND {eia860_sql_filter_string}
            AND raw_data_eia860_generators.prime_mover_code = '{tech}'
            {group_by}
            ;
        """
        relevant_projects_df = pd.read_sql(sql, conn)

        if not relevant_projects_df.empty:
            spec_cap_updated_df = duckdb_conn.sql(f"""
                CREATE TABLE {tech}_relevant_projects_table
                AS SELECT * FROM relevant_projects_df
                ;
                --SELECT * FROM relevant_projects_table;
                UPDATE spec_cap_table
                SET specified_stor_capacity_mwh = {tech_dur_dict[tech]}*specified_capacity_mw
                WHERE (project, period) IN (SELECT (project, period) FROM {tech}_relevant_projects_table)
                AND specified_stor_capacity_mwh IS NULL
                ;
                """)

    spec_cap_updated_df = duckdb_conn.sql("""
        SELECT * FROM spec_cap_table
        ;
        """).df()

    spec_cap_updated_df.to_csv(
        os.path.join(csv_location, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args)

    if not parsed_args.quiet:
        print("Making manual adjustments")

    conn = connect_to_database(db_path=parsed_args.database)

    # Add missing project files
    copy_files_df = pd.read_csv(parsed_args.files_to_copy_csv, index_col=False)
    for index, row in copy_files_df.iterrows():
        make_copy_files(
            new_file_directory=row["new_file_directory"],
            new_project=row["new_project"],
            new_project_scenario_id=row["new_project_scenario_id"],
            new_project_scenario_name=row["new_project_scenario_name"],
            file_to_copy_directory=row["file_to_copy_directory"],
            copy_project=row["copy_project"],
            copy_project_scenario_id=row["copy_project_scenario_id"],
            copy_project_scenario_name=row["copy_project_scenario_name"],
        )

    # Add missing storage durations
    tech_dur_dict = {
        "BA": parsed_args.battery_duration,
        "PS": parsed_args.pumped_storage_duration,
    }

    project_name_str = (
        AGG_PROJECT_NAME_STR
        if parsed_args.aggregate_projects
        else DISAGG_PROJECT_NAME_STR
    )

    add_battery_durations(
        conn=conn,
        project_name_str=project_name_str,
        study_year=parsed_args.study_year,
        eia860_sql_filter_string=get_eia860_sql_filter_string(
            study_year=parsed_args.study_year, region=parsed_args.region
        ),
        csv_location=parsed_args.capacity_specified_directory,
        subscenario_id=parsed_args.project_specified_capacity_scenario_id,
        subscenario_name=parsed_args.project_specified_capacity_scenario_name,
        tech_dur_dict=tech_dur_dict,
        aggregate_projects=parsed_args.aggregate_projects,
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
