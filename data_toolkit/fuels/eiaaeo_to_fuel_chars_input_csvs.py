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
EIA AEO Fuel Chars (User-Defined)
*********************************

Create GridPath fuel chars inputs (fuel_scenario_id) for fuels in the EIA
AEO. The fuel characteristics are user-defined.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eiaaeo_to_fuel_chars_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

Thios module assumes the following raw input database tables have been
populated:

* raw_data_eiaaeo_fuel_prices
* user_defined_eia_gridpath_key
* user_defined_generic_fuel_intensities
* user_defined_eiaaeo_region_key


=========
Settings
=========

* database
* output_directory
* model_case
* report_year
* fuel_scenario_id
* fuel_scenario_name

"""

import csv
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from db.common_functions import connect_to_database


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="../../db/open_data_raw.db")

    parser.add_argument(
        "-o",
        "--output_directory",
        default="../../db/csvs_open_data/fuels/fuel_chars",
    )
    parser.add_argument("-f_id", "--fuel_scenario_id", default=1)
    parser.add_argument("-f_name", "--fuel_scenario_name", default="generic")
    parser.add_argument(
        "-case",
        "--model_case",
        default="aeo2022",
    )
    parser.add_argument("-r_yr", "--report_year", default=2023)

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_fuel_prices(
    conn, output_directory, subscenario_id, subscenario_name, report_year, model_case
):
    """ """

    sql = f"""
    SELECT DISTINCT fuel, co2_intensity_emissionsunit_per_fuelunit AS 
    co2_intensity_tons_per_mmbtu, NULL as fuel_group 
    FROM (
        SELECT gridpath_generic_fuel || '_' || fuel_region as fuel, co2_intensity_emissionsunit_per_fuelunit
        FROM raw_data_eiaaeo_fuel_prices
        JOIN (
            SELECT DISTINCT gridpath_generic_fuel, fuel_type_eiaaeo, co2_intensity_emissionsunit_per_fuelunit
            FROM user_defined_eia_gridpath_key
            JOIN user_defined_generic_fuel_intensities
            USING (gridpath_generic_fuel)
        ) USING (fuel_type_eiaaeo)
        JOIN user_defined_eiaaeo_region_key using (electricity_market_module_region_eiaaeo)
    WHERE report_year = {report_year}
    AND model_case_eiaaeo = '{model_case}'
    )
    ORDER BY fuel
    """

    df = pd.read_sql(sql, conn)
    df.to_csv(
        os.path.join(output_directory, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating fuel chars...")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    get_fuel_prices(
        conn=conn,
        output_directory=parsed_args.output_directory,
        subscenario_id=parsed_args.fuel_scenario_id,
        subscenario_name=parsed_args.fuel_scenario_name,
        report_year=parsed_args.report_year,
        model_case=parsed_args.model_case,
    )

    conn.close()


if __name__ == "__main__":
    main()
