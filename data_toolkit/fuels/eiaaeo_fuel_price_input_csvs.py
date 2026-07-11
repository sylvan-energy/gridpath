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
EIA AEO Fuel Prices
*******************

Create GridPath fuel price inputs (fuel_scenario_id) based on the EIA AEO.

.. warning:: The user is reponsible for ensuring that all prices and costs in
    their model are in a consistent real currency year.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eiaaeo_fuel_price_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

Thios module assumes the following raw input database tables have been
populated:

* raw_data_eiaaeo_fuel_prices
* user_defined_eiaaeo_region_key

=========
Settings
=========

* database
* output_directory
* model_case
* report_year
* fuel_price_id

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
        default="../../db/csvs_open_data/fuels/fuel_prices",
    )
    parser.add_argument("-fuel_price_id", "--fuel_price_scenario_id", default=1)
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
    SELECT gridpath_generic_fuel || '_' || fuel_region as fuel, projection_year as period, 
    fuel_cost_real_per_mmbtu_eiaaeo as fuel_price_per_mmbtu
    FROM raw_data_eiaaeo_fuel_prices
    JOIN (SELECT DISTINCT gridpath_generic_fuel, fuel_type_eiaaeo FROM user_defined_eia_gridpath_key) USING (fuel_type_eiaaeo)
    JOIN user_defined_eiaaeo_region_key using (
    electricity_market_module_region_eiaaeo)
    WHERE report_year = {report_year}
    AND model_case_eiaaeo = '{model_case}'
    ORDER BY fuel, period
    """

    df = pd.read_sql(sql, conn)
    month_df_list = []
    for month in range(1, 13):
        month_df = df
        month_df["month"] = month
        cols = month_df.columns.tolist()
        cols = cols[:2] + [cols[3]] + [cols[2]]
        month_df = month_df[cols]

        month_df_list.append(month_df)

    final_df = pd.concat(month_df_list)

    final_df.to_csv(
        os.path.join(output_directory, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating fuel prices...")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    get_fuel_prices(
        conn=conn,
        output_directory=parsed_args.output_directory,
        subscenario_id=parsed_args.fuel_price_scenario_id,
        subscenario_name=parsed_args.model_case,
        report_year=parsed_args.report_year,
        model_case=parsed_args.model_case,
    )

    conn.close()


if __name__ == "__main__":
    main()
