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
Form EIA 860 Project Heat Rates (User-Defined by Tech)
******************************************************

Create project heat rate CSV for a EIA860-based project portfolio.

.. note:: Heat rates are user-specified and generic by technology. If you
    need more granular heat rates by, say, project, you would need to modify
    this module.

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_heat_rate_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_eia860_generators
    * user_defined_eia_gridpath_key
    * user_defined_heat_rate_curve

=========
Settings
=========
    * database
    * output_directory
    * study_year
    * region
    * project_hr_scenario_id
    * project_hr_scenario_name

"""

import csv
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import sys

from db.common_functions import connect_to_database
from data_toolkit.project.project_data_filters_common import (
    get_eia860_sql_filter_string,
    HEAT_RATE_FILTER_STR,
    DISAGG_PROJECT_NAME_STR,
)


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="../../open_data_raw.db")
    parser.add_argument("-y", "--study_year", default=2026)
    parser.add_argument("-r", "--region", default="WECC")

    parser.add_argument(
        "-o",
        "--output_directory",
        default="../../csvs_open_data/project/opchar/heat_rates",
    )
    parser.add_argument("-hr_id", "--project_hr_scenario_id", default=1)
    parser.add_argument("-hr_name", "--project_hr_scenario_name", default="generic")

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_project_heat_rates(
    conn,
    eia860_sql_filter_string,
    heat_rate_filter_str,
    disagg_project_name_str,
    csv_location,
    subscenario_id,
    subscenario_name,
):

    # Only coal, gas, and fuel oil for now (with aeo prices)
    sql = f"""
        SELECT {disagg_project_name_str} AS project, 
            raw_data_eia860_generators.prime_mover_code, gridpath_generic_fuel, 
            heat_rate_mmbtu_per_mwh, min_load_fraction
        FROM raw_data_eia860_generators
        JOIN user_defined_eia_gridpath_key ON
            raw_data_eia860_generators.prime_mover_code = 
            user_defined_eia_gridpath_key.prime_mover_code
            AND energy_source_code_1 = energy_source_code
        WHERE 1 = 1
        AND {eia860_sql_filter_string}
        AND {heat_rate_filter_str}
        """

    c = conn.cursor()
    header = ["period", "load_point_fraction", "average_heat_rate_mmbtu_per_mwh"]
    for (
        project,
        prime_mover_code,
        fuel,
        heat_rate_mmbtu_per_mwh,
        min_load_fraction,
    ) in c.execute(sql).fetchall():
        c2 = conn.cursor()
        min_load_heat_rate_coefficient = c2.execute(f"""
            SELECT average_heat_rate_coefficient
            FROM user_defined_heat_rate_curve
            WHERE load_point_fraction = {min_load_fraction}
            ;
            """).fetchone()[0]
        with open(
            os.path.join(
                csv_location,
                f"{project}-{subscenario_id}" f"-{subscenario_name}.csv",
            ),
            "w",
        ) as filepath:
            writer = csv.writer(filepath, delimiter=",")
            writer.writerow(header)
            writer.writerow(
                [
                    0,
                    min_load_fraction,
                    min_load_heat_rate_coefficient * heat_rate_mmbtu_per_mwh,
                ]
            )
            writer.writerow([0, 1, heat_rate_mmbtu_per_mwh])


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project heat rate inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    get_project_heat_rates(
        conn=conn,
        eia860_sql_filter_string=get_eia860_sql_filter_string(
            study_year=parsed_args.study_year, region=parsed_args.region
        ),
        heat_rate_filter_str=HEAT_RATE_FILTER_STR,
        disagg_project_name_str=DISAGG_PROJECT_NAME_STR,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_hr_scenario_id,
        subscenario_name=parsed_args.project_hr_scenario_name,
    )

    conn.close()


if __name__ == "__main__":
    main()
