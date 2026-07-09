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
Weather Derates (Monte Carlo)
*****************************

Create GridPath Monte Carlo weather iteration availability inputs. Before
running this module, you will need to create weather draws with the
``create_monte_carlo_draws`` module (see :ref:`monte-carlo-draws-section-ref`).

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_monte_carlo_weather_derate_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_unit_availability_params
    * raw_data_availability_profiles
    * aux_weather_iterations (see the ``create_monte_carlo_draws`` step for how to create synthetic weather years and populate this table)

=========
Settings
=========
    * database
    * output_directory
    * exogenous_availability_weather_scenario_id
    * exogenous_availability_weather_scenario_name
    * overwrite
    * n_parallel_projects
    * weather_bins_id
    * weather_draws_id

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import sys

from db.common_functions import connect_to_database
from data_toolkit.load_raw_data import read_and_import_csv
from data_toolkit.project.create_monte_carlo_gen_input_csvs_common import (
    get_monte_carlo_timeseries_project_pool_and_make_profile_csvs,
)

BINS_ID_DEFAULT = 1
DRAWS_ID_DEFAULT = 1
WEATHER_AV_ID_DEFAULT = 1
WEATHER_AV_NAME_DEFAULT = "ra_toolkit"
STAGE_ID_DEFAULT = 1


# TODO: make sure hybrids are properly incorporated
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
        "-av_csv",
        "--availability_profile_input_csv",
        default=None,
        help="""Path to the availability profiles CSV file to load into the 
        database. If not specified, data will be assumed to have been
        already loaded into the database.""",
    )
    parser.add_argument(
        "-u_csv",
        "--units_input_csv",
        default=None,
        help="""Path to the unit availability params CSV file to load into the 
        database. If not specified, data will be assumed to have been
        already loaded into the database.""",
    )

    parser.add_argument(
        "-bins_id",
        "--weather_bins_id",
        default=BINS_ID_DEFAULT,
        help=f"Defaults to {BINS_ID_DEFAULT}.",
    )
    parser.add_argument(
        "-draws_id",
        "--weather_draws_id",
        default=DRAWS_ID_DEFAULT,
        help=f"Defaults to {DRAWS_ID_DEFAULT}.",
    )

    parser.add_argument(
        "-s_y",
        "--study_year",
        default=0,
        help=f"Defaults to 0. Timepoint IDs will start at 1. Set to YYYY to "
        f"have timepoint IDs start at YYYY0001.",
    )

    parser.add_argument("-out_dir", "--output_directory")
    parser.add_argument(
        "-id",
        "--exogenous_availability_weather_scenario_id",
        default=WEATHER_AV_ID_DEFAULT,
        help=f"Defaults to {WEATHER_AV_ID_DEFAULT}.",
    )
    parser.add_argument(
        "-name",
        "--exogenous_availability_weather_scenario_name",
        default=WEATHER_AV_NAME_DEFAULT,
        help=f"Defaults to '{WEATHER_AV_NAME_DEFAULT}'.",
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
        help="Overwrite existing CSV files. Defaults to False.",
    )

    parser.add_argument(
        "-parallel",
        "--n_parallel_projects",
        default=1,
        help="The number of projects to simulate in parallel. Defaults to 1.",
    )

    parser.add_argument(
        "-ones",
        "--print_ones",
        default=False,
        action="store_true",
        help="Include rows where derate values equal 1. " "Defaults to False.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    if args is None:
        args = sys.argv[1:]
    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating Monte Carlo gen weather-dependent derates CSVs...")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    # ### Load data from CSV
    if parsed_args.availability_profile_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.input_csv,
            table="raw_data_availability_profiles",
        )

    if parsed_args.units_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.input_csv,
            table="raw_data_unit_availability_params",
        )

    conn.commit()
    conn.close()

    get_monte_carlo_timeseries_project_pool_and_make_profile_csvs(
        db_path=parsed_args.database,
        weather_bins_id=parsed_args.weather_bins_id,
        weather_draws_id=parsed_args.weather_draws_id,
        output_directory=parsed_args.output_directory,
        profile_scenario_id=parsed_args.exogenous_availability_weather_scenario_id,
        profile_scenario_name=parsed_args.exogenous_availability_weather_scenario_name,
        stage_id=parsed_args.stage_id,
        overwrite=parsed_args.overwrite,
        n_parallel_projects=parsed_args.n_parallel_projects,
        units_table="raw_data_unit_availability_params",
        param_name="availability_derate_weather",
        raw_data_table="raw_data_availability_profiles",
        study_year=int(parsed_args.study_year),
        print_default_values=parsed_args.print_ones,
        default_value=1,
        no_hydro_iteration=True,
    )


if __name__ == "__main__":
    main()
