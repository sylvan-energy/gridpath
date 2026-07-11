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
Variable Gen Profiles (Monte Carlo)
***********************************

Create GridPath Monte Carlo variable generation profile inputs. Before running
this module,you will need to create weather draws with the
``create_monte_carlo_draws`` module (see :ref:`monte-carlo-draws-section-ref`).

===================
What this step does
===================

This is the variable energy resource (VER) counterpart to the load-CSV step. It
reads the synthetic per-iteration variable generation profiles -- assembled from
``raw_data_var_profiles`` (the raw hourly unit-level ``cap_factor`` data) and
``raw_data_var_project_units`` (the project-to-unit mapping and per-unit
weights), resampled according to the weather draws stored in
``aux_weather_iterations`` -- and writes them out as GridPath variable-generator
profile input CSVs in ``--output_directory``, tagged with the given
``--variable_generator_profile_scenario_id`` and
``--variable_generator_profile_scenario_name``. These CSVs are the files the
GridPath model consumes for variable generation.

===========
Methodology
===========

For each project, the per-unit ``cap_factor`` values from ``raw_data_var_profiles``
are multiplied by their ``unit_weight`` and summed to produce a single
project-level ``cap_factor`` time series. The weather draws in
``aux_weather_iterations`` (selected by ``--weather_bins_id`` and
``--weather_draws_id``) determine, for each Monte Carlo ``weather_iteration`` and
``draw_number``, which historical day's data to pull, and the draw number is used
to compute the ``timepoint`` ID. One output CSV is written per project, named
``{project}-{scenario_id}-{scenario_name}.csv``, with an accompanying iterations
CSV written to an ``iterations`` subdirectory of ``--output_directory``.

``--n_parallel_projects N`` processes up to ``N`` projects concurrently (via a
multiprocessing pool over the project pool) to speed things up. ``--overwrite``
deletes any existing CSVs with the matching project/scenario filename before
writing; without it, output is appended to existing files.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_monte_carlo_var_gen_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_var_profiles
    * raw_data_var_project_units
    * aux_weather_iterations (see the ``create_monte_carlo_draws`` step for how to create synthetic weather years and populate this table)

You must run **create_monte_carlo_draw_profiles** before running this module to
populate the database with the raw data and the synthetic weather draws.


=========
Settings
=========
    * database
    * output_directory
    * variable_generator_profile_scenario_id
    * variable_generator_profile_scenario_name
    * overwrite
    * n_parallel_projects
    * weather_bins_id
    * weather_draws_id

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import sys

from data_toolkit.load_raw_data import read_and_import_csv
from data_toolkit.project.create_monte_carlo_gen_input_csvs_common import (
    get_monte_carlo_timeseries_project_pool_and_make_profile_csvs,
)

BINS_ID_DEFAULT = 1
DRAWS_ID_DEFAULT = 1
VAR_ID_DEFAULT = 1
VAR_NAME_DEFAULT = "ra_toolkit"
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
        help="Overwrite existing CSV files. Defaults to False.",
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
        print("Creating Monte Carlo variable gen CSVs...")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    # Create the variable generation profile CSVs
    get_monte_carlo_timeseries_project_pool_and_make_profile_csvs(
        db_path=parsed_args.database,
        weather_bins_id=parsed_args.weather_bins_id,
        weather_draws_id=parsed_args.weather_draws_id,
        output_directory=parsed_args.output_directory,
        profile_scenario_id=parsed_args.variable_generator_profile_scenario_id,
        profile_scenario_name=parsed_args.variable_generator_profile_scenario_name,
        stage_id=parsed_args.stage_id,
        overwrite=parsed_args.overwrite,
        n_parallel_projects=parsed_args.n_parallel_projects,
        units_table="raw_data_var_project_units",
        param_name="cap_factor",
        raw_data_table="raw_data_var_profiles",
        study_year=parsed_args.study_year,
        print_default_values=True,
        default_value=None,
    )


if __name__ == "__main__":
    main()
