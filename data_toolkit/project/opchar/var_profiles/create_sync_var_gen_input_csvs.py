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

"""
Variable Gen Profiles (Sync)
****************************

Create GridPath sync variable generation profile inputs.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_sync_var_gen_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_var_profiles
    * raw_data_var_project_units

=========
Settings
=========
    * database
    * output_directory
    * variable_generator_profile_scenario_id
    * variable_generator_profile_scenario_name
    * overwrite
    * n_parallel_projects

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import sys

from db.common_functions import connect_to_database
from data_toolkit.load_raw_data import read_and_import_csv
from data_toolkit.project.create_sync_gen_input_csvs_common import (
    get_sync_project_pool_and_make_profile_csvs,
)

VAR_ID_DEFAULT = 1
VAR_NAME_DEFAULT = "ra_toolkit"
STAGE_ID_DEFAULT = 1


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database")
    parser.add_argument(
        "-v_csv",
        "--variable_generator_profile_input_csv",
        default=None,
        help="""Path to the availability profiles CSV file to load into the 
        database. If not specified, data will be assumed to have been
        already loaded into the database.""",
    )
    parser.add_argument(
        "-u_csv",
        "--units_input_csv",
        default=None,
        help="""Path to the CSV file to load into the database.
            If not specified, data will be assumed to have been
            already loaded into the database.""",
    )
    parser.add_argument("-out_dir", "--output_directory")
    parser.add_argument(
        "-id",
        "--variable_generator_profile_scenario_id",
        default=VAR_ID_DEFAULT,
        help=f"Defaults to {VAR_ID_DEFAULT}.",
    )
    parser.add_argument(
        "-name",
        "--variable_generator_profile_scenario_name",
        default=VAR_NAME_DEFAULT,
        help=f"Defaults to '{VAR_NAME_DEFAULT}'.",
    )

    parser.add_argument(
        "-stage",
        "--stage_id",
        default=STAGE_ID_DEFAULT,
        help=f"Defaults to '{STAGE_ID_DEFAULT}",
    )

    parser.add_argument(
        "-o",
        "--overwrite",
        default=False,
        action="store_true",
        help="Overwrite existing CSV files.",
    )

    parser.add_argument(
        "-parallel",
        "--n_parallel_projects",
        default=1,
        help="The number of projects to simulate in parallel. Defaults to 1.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating sync variable gen CSVs...")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    # ### Load data from CSV
    if parsed_args.variable_generator_profile_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.variable_generator_profile_input_csv,
            table="raw_data_var_profiles",
        )

    if parsed_args.units_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.units_input_csv,
            table="raw_data_var_project_units",
        )

    conn.commit()
    conn.close()

    get_sync_project_pool_and_make_profile_csvs(
        db_path=parsed_args.database,
        param_name="cap_factor",
        raw_data_table_name="raw_data_var_profiles",
        raw_data_units_table_name="raw_data_var_project_units",
        profile_scenario_id=parsed_args.variable_generator_profile_scenario_id,
        profile_scenario_name=parsed_args.variable_generator_profile_scenario_name,
        stage_id=parsed_args.stage_id,
        output_directory=parsed_args.output_directory,
        overwrite=parsed_args.overwrite,
        varies_by_weather=1,
        varies_by_hydro=0,
        include_hydro_iteration_column=True,
        n_parallel_projects=parsed_args.n_parallel_projects,
        print_default_values=True,
        default_value=None,
    )


if __name__ == "__main__":
    main()
