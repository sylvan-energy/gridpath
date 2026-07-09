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
Form EIA 860 Project Portfolios
*******************************

This module creates project portfolios from EIA 860 data.

The project capacity_types will be based on the data in the
user_defined_eia_gridpath_key table.

Wind, solar, and hydro are aggregated to the BA level.

.. note:: Hybrid projects are currently not treated separately by this module.
    Their renewable generation components are lumped with wind/solar, and the
    storage components show up as individual units.

Project portfolios are created based on the data from a particular report
date. The user selects the region (determines subset of generators to use)
and the study date (determines which generators are operational, i.e.,
after their online date and before their retirement date in the EIA data.)

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_portfolio_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

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
    * project_portfolio_scenario_id
    * project_portfolio_scenario_name

TODO: disaggregate the hybrids out of the wind/solar project and combine
     with their battery components
"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from db.common_functions import connect_to_database
from data_toolkit.project.project_data_filters_common import (
    get_eia860_sql_filter_string,
    VAR_GEN_FILTER_STR,
    HYDRO_FILTER_STR,
    DISAGG_PROJECT_NAME_STR,
    AGG_PROJECT_NAME_STR,
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
        default="../../csvs_open_data/project/portfolios",
    )
    parser.add_argument("-p_id", "--project_portfolio_scenario_id", default=1)
    parser.add_argument(
        "-p_name", "--project_portfolio_scenario_name", default="wecc_plants_units"
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


def get_project_portfolio_for_region(
    conn,
    eia860_sql_filter_string,
    var_gen_filter_str,
    hydro_filter_str,
    disagg_project_name_str,
    agg_project_name_str,
    csv_location,
    subscenario_id,
    subscenario_name,
    aggregate_projects=False,
):
    if aggregate_projects:
        sql = f"""
        SELECT {agg_project_name_str} AS project,
        NULL as specified,
        NULL as new_build,
        gridpath_capacity_type AS capacity_type
        FROM raw_data_eia860_generators
        JOIN user_defined_eia_gridpath_key ON
                raw_data_eia860_generators.prime_mover_code =
                user_defined_eia_gridpath_key.prime_mover_code
                AND energy_source_code_1 = energy_source_code
         WHERE 1 = 1
         AND {eia860_sql_filter_string}
         GROUP BY project
        ;
        """
    else:
        sql = f"""
        -- Disaggregated units
        SELECT {disagg_project_name_str} AS project,
        NULL as specified,
        NULL as new_build,
        gridpath_capacity_type AS capacity_type
        FROM raw_data_eia860_generators
        JOIN user_defined_eia_gridpath_key ON
                raw_data_eia860_generators.prime_mover_code =
                user_defined_eia_gridpath_key.prime_mover_code
                AND energy_source_code_1 = energy_source_code
         WHERE 1 = 1
         AND {eia860_sql_filter_string}
         AND NOT {var_gen_filter_str}
         AND NOT {hydro_filter_str}
        UNION
        -- Aggregated units include wind, offshore wind, solar, and hydro
        SELECT {agg_project_name_str} AS project,
            NULL as specified,
            NULL as new_build,
            gridpath_capacity_type AS capacity_type
        FROM raw_data_eia860_generators
        JOIN user_defined_eia_gridpath_key
        USING (prime_mover_code)
        WHERE 1 = 1
        AND {eia860_sql_filter_string}
        AND ({var_gen_filter_str} OR {hydro_filter_str})
        ;
        """

    df = pd.read_sql(sql, conn)
    df.to_csv(
        os.path.join(csv_location, f"{subscenario_id}_{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project portfolio inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    get_project_portfolio_for_region(
        conn=conn,
        eia860_sql_filter_string=get_eia860_sql_filter_string(
            study_year=parsed_args.study_year, region=parsed_args.region
        ),
        var_gen_filter_str=VAR_GEN_FILTER_STR,
        hydro_filter_str=HYDRO_FILTER_STR,
        disagg_project_name_str=DISAGG_PROJECT_NAME_STR,
        agg_project_name_str=AGG_PROJECT_NAME_STR,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_portfolio_scenario_id,
        subscenario_name=parsed_args.project_portfolio_scenario_name,
        aggregate_projects=parsed_args.aggregate_projects,
    )

    conn.close()


if __name__ == "__main__":
    main()
