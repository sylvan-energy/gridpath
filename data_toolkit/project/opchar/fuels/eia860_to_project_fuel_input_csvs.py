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
Form EIA 860 Project Fuels
**************************

Create project fuels CSV for a EIA860-based project portfolio.

.. note:: Some fuel regions in the EIA AEO are more disaggragated than the BA
    in Form EIA 860 (e.g. CA South and North regions in the AEO, and CISO BA in
    Form EIA 860). This module currently can only assign one fuel region to
    each BA. If you need the extra resolution, you will need to modify it.

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_fuel_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_eia860_generators
    * user_defined_eia_gridpath_key
    * user_defined_baa_key

=========
Settings
=========
    * database
    * output_directory
    * study_year
    * region
    * project_fuel_scenario_id
    * project_fuel_scenario_name

"""

import csv
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import sys

from db.common_functions import connect_to_database
from data_toolkit.project.project_data_filters_common import (
    get_eia860_sql_filter_string,
    FUEL_FILTER_STR,
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
        default="../../csvs_open_data/project/opchar/fuels",
    )
    parser.add_argument("-fuel_id", "--project_fuel_scenario_id", default=1)
    parser.add_argument("-fuel_name", "--project_fuel_scenario_name", default="base")

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


# Fuels and heat rates for gen_commit_bin/lin
def get_project_fuels(
    conn,
    eia860_sql_filter_string,
    fuel_filter_str,
    disagg_project_name_str,
    csv_location,
    subscenario_id,
    subscenario_name,
):

    # Only coal, gas, and fuel oil for now (with aeo prices)
    sql = f"""
        SELECT {disagg_project_name_str} AS project, 
            gridpath_generic_fuel || '_' || fuel_region as fuel
        FROM raw_data_eia860_generators
        JOIN user_defined_eia_gridpath_key ON
            raw_data_eia860_generators.prime_mover_code = 
            user_defined_eia_gridpath_key.prime_mover_code
            AND energy_source_code_1 = energy_source_code
        JOIN user_defined_baa_key ON (balancing_authority_code_eia = baa)
        WHERE 1 = 1
        AND {eia860_sql_filter_string}
        AND {fuel_filter_str}
        """

    c = conn.cursor()
    header = ["fuel", "min_fraction_in_fuel_blend", "max_fraction_in_fuel_blend"]
    for project, fuel in c.execute(sql).fetchall():
        if fuel is not None:
            with open(
                os.path.join(
                    csv_location,
                    f"{project}-{subscenario_id}" f"-{subscenario_name}.csv",
                ),
                "w",
            ) as filepath:
                writer = csv.writer(filepath, delimiter=",")
                writer.writerow(header)
                writer.writerow([fuel, None, None])


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project fuel inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    get_project_fuels(
        conn=conn,
        eia860_sql_filter_string=get_eia860_sql_filter_string(
            study_year=parsed_args.study_year, region=parsed_args.region
        ),
        fuel_filter_str=FUEL_FILTER_STR,
        disagg_project_name_str=DISAGG_PROJECT_NAME_STR,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_fuel_scenario_id,
        subscenario_name=parsed_args.project_fuel_scenario_name,
    )

    conn.close()


if __name__ == "__main__":
    main()
