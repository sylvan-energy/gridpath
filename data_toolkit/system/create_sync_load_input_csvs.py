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

"""
Sync Loads
**********

Create GridPath sync load profile inputs.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_sync_load_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_system_load
    * user_defined_load_zone_units

=========
Settings
=========
    * database
    * output_directory
    * load_scenario_id
    * load_scenario_name
    * overwrite

"""

import sys
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd

from data_toolkit.system.common_methods import (
    create_load_scenario_csv,
    create_load_components_scenario_csv,
)
from db.common_functions import connect_to_database
from data_toolkit.load_raw_data import read_and_import_csv

LOAD_SCENARIO_ID_DEFAULT = 1  # it's 6 in the test examples
LOAD_SCENARIO_NAME_DEFAULT = "ra_toolkit"
LOAD_COMPONENTS_SCENARIO_ID_DEFAULT = 1  # it's 6 in the test examples
LOAD_COMPONENTS_SCENARIO_NAME_DEFAULT = "ra_toolkit"
LOAD_LEVELS_SCENARIO_ID_DEFAULT = 1  # it's 6 in the test examples
LOAD_LEVELS_SCENARIO_NAME_DEFAULT = "ra_toolkit"
STAGE_ID_DEFAULT = 1
LOAD_COMPONENT_NAME_DEFAULT = "all"


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
        "-l_csv",
        "--load_profile_input_csv",
        default=None,
        help="""Path to the availability profiles CSV file to load into the 
        raw_data_system_load table. If not specified, data will be assumed to 
        have been already loaded into the database.""",
    )
    parser.add_argument(
        "-u_csv",
        "--units_input_csv",
        default=None,
        help="""Path to the unit availability params CSV file to load into the 
        user_defined_load_zone_units table. If not specified, data will be 
        assumed to have been already loaded into the database.""",
    )

    parser.add_argument(
        "-out_dir",
        "--output_directory",
        help="""This will be the location of the load_scenario_id file. The 
        load components and load levels files are assumed to be in the 
        'load_components' and 'load_levels' subdirectories respectively.""",
    )
    parser.add_argument(
        "-id",
        "--load_scenario_id",
        default=LOAD_SCENARIO_ID_DEFAULT,
        help=f"Defaults to {LOAD_SCENARIO_ID_DEFAULT}.",
    )
    parser.add_argument(
        "-name",
        "--load_scenario_name",
        default=LOAD_SCENARIO_NAME_DEFAULT,
        help=f"Defaults to '{LOAD_SCENARIO_NAME_DEFAULT}'.",
    )
    parser.add_argument(
        "-lc_id",
        "--load_components_scenario_id",
        default=LOAD_COMPONENTS_SCENARIO_ID_DEFAULT,
        help=f"Defaults to {LOAD_COMPONENTS_SCENARIO_ID_DEFAULT}.",
    )
    parser.add_argument(
        "-lc_name",
        "--load_components_scenario_name",
        default=LOAD_COMPONENTS_SCENARIO_NAME_DEFAULT,
        help=f"Defaults to '{LOAD_COMPONENTS_SCENARIO_NAME_DEFAULT}'.",
    )
    parser.add_argument(
        "-ll_id",
        "--load_levels_scenario_id",
        default=LOAD_LEVELS_SCENARIO_ID_DEFAULT,
        help=f"Defaults to {LOAD_LEVELS_SCENARIO_ID_DEFAULT}.",
    )
    parser.add_argument(
        "-ll_name",
        "--load_levels_scenario_name",
        default=LOAD_LEVELS_SCENARIO_NAME_DEFAULT,
        help=f"Defaults to '{LOAD_LEVELS_SCENARIO_NAME_DEFAULT}'.",
    )

    parser.add_argument(
        "-stage",
        "--stage_id",
        default=STAGE_ID_DEFAULT,
        help=f"Defaults to '{STAGE_ID_DEFAULT}",
    )

    parser.add_argument(
        "-comp",
        "--load_component",
        default=LOAD_COMPONENT_NAME_DEFAULT,
        help=f"Defaults to '{LOAD_COMPONENT_NAME_DEFAULT}",
    )

    parser.add_argument(
        "-l_o",
        "--load_scenario_overwrite",
        default=False,
        action="store_true",
        help="Overwrite existing CSV files.",
    )
    parser.add_argument(
        "-lc_o",
        "--load_components_overwrite",
        default=False,
        action="store_true",
        help="Overwrite existing CSV files.",
    )
    parser.add_argument(
        "-ll_o",
        "--load_levels_overwrite",
        default=False,
        action="store_true",
        help="Overwrite existing CSV files.",
    )

    parser.add_argument(
        "-skip_l",
        "--skip_load_scenario",
        default=False,
        action="store_true",
        help="Don't create load_scenario file.",
    )
    parser.add_argument(
        "-skip_lc",
        "--skip_load_components",
        default=False,
        action="store_true",
        help="Don't create load components file.",
    )
    parser.add_argument(
        "-skip_ll",
        "--skip_load_levels",
        default=False,
        action="store_true",
        help="Don't create load levels file.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def create_load_levels_csv(
    conn,
    output_directory,
    load_levels_scenario_id,
    load_levels_scenario_name,
    stage_id,
    load_component_name,
    overwrite,
):
    """
    This module currently assumes timepoint IDs will be 1 through 8760 for
    each year. The query will aggregate loads based on the aggregations and
    weights defined in the user_defined_load_zone_units
    table.
    """

    query = f"""
        SELECT load_zone, year AS weather_iteration, {stage_id} as stage_id, 
        hour_of_year as timepoint, 
        '{load_component_name}' AS load_component, sum(weighted_load_mw) as 
        load_mw
        FROM (
        SELECT year, month, day_of_month, hour_of_day, unit, load_zone, 
        unit_weight, value, unit_weight * value as weighted_load_mw,
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
        FROM raw_data_system_load
        JOIN user_defined_load_zone_units
        USING (unit)
        )
    GROUP BY load_zone, year, hour_of_year
    """

    # Put into a dataframe and add to file
    df = pd.read_sql(query, con=conn)

    filename = os.path.join(
        output_directory,
        "load_levels",
        f"{load_levels_scenario_id}_{load_levels_scenario_name}.csv",
    )
    if overwrite:
        mode = "w"
        write_header = True
    else:
        mode = "a"
        write_header = not os.path.exists(filename)

    df.to_csv(
        filename,
        mode=mode,
        header=write_header,
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating sync load profile CSVs...")

    os.makedirs(parsed_args.output_directory, exist_ok=True)
    os.makedirs(
        os.path.join(parsed_args.output_directory, "load_components"), exist_ok=True
    )
    os.makedirs(
        os.path.join(parsed_args.output_directory, "load_levels"), exist_ok=True
    )

    conn = connect_to_database(db_path=parsed_args.database)

    # ### Load data from CSV
    if parsed_args.load_profile_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.load_profile_input_csv,
            table="raw_data_system_load",
        )

    if parsed_args.units_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.units_input_csv,
            table="user_defined_load_zone_units",
        )

    if not parsed_args.skip_load_scenario:
        create_load_scenario_csv(
            output_directory=parsed_args.output_directory,
            load_scenario_id=parsed_args.load_scenario_id,
            load_scenario_name=parsed_args.load_scenario_name,
            load_components_scenario_id=parsed_args.load_components_scenario_id,
            load_levels_scenario_id=parsed_args.load_levels_scenario_id,
            overwrite_load_scenario_csv=parsed_args.load_scenario_overwrite,
        )

    if not parsed_args.skip_load_components:
        create_load_components_scenario_csv(
            conn=conn,
            output_directory=parsed_args.output_directory,
            load_component_name=parsed_args.load_component,
            load_components_scenario_id=parsed_args.load_components_scenario_id,
            load_components_scenario_name=parsed_args.load_components_scenario_name,
            overwrite_load_components_csv=parsed_args.load_components_overwrite,
        )

    if not parsed_args.skip_load_levels:
        create_load_levels_csv(
            conn=conn,
            output_directory=parsed_args.output_directory,
            load_levels_scenario_id=parsed_args.load_levels_scenario_id,
            load_levels_scenario_name=parsed_args.load_levels_scenario_name,
            stage_id=parsed_args.stage_id,
            load_component_name=parsed_args.load_component,
            overwrite=parsed_args.load_levels_overwrite,
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
