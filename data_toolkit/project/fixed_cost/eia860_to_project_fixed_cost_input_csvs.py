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
Form EIA 860 Projects -- Create CSV with Fixed Costs Set to Zero
****************************************************************

Create fixed cost CSV for a EIA860-based project portfolio **with fixed costs
set to zero** as fixed cost data are not available at this time. The CSV is
necessary to create since fixed costs are currently a required GridPath input.

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_fixed_cost_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_eia860_generators
    * user_defined_eia_gridpath_key

=========
Settings
=========
    * database
    * output_directory
    * study_year
    * region
    * project_fixed_cost_scenario_id
    * project_fixed_cost_scenario_name

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

    parser.add_argument("-db", "--database", default="../../../db/open_data_raw.db")
    parser.add_argument("-y", "--study_year", default=2026)
    parser.add_argument("-r", "--region", default="WECC")
    parser.add_argument(
        "-o",
        "--output_directory",
        default="../../../db/csvs_open_data/project/fixed_cost",
    )
    parser.add_argument("-fcost_id", "--project_fixed_cost_scenario_id", default=1)
    parser.add_argument(
        "-fcost_name", "--project_fixed_cost_scenario_name", default="base"
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


def get_project_fixed_cost(
    conn,
    eia860_sql_filter_string,
    var_gen_filter_str,
    hydro_filter_str,
    disagg_project_name_str,
    agg_project_name_str,
    study_year,
    output_directory,
    subscenario_id,
    subscenario_name,
    aggregate_projects=False,
):
    if aggregate_projects:
        sql = f"""
        SELECT {agg_project_name_str} AS project,
            {study_year} as period,
            0 AS fixed_cost_per_mw_yr,
            0 AS fixed_cost_per_energy_mwh_yr,
            0 AS fixed_cost_per_shaping_mw_yr,
            NULL AS hyb_gen_fixed_cost_per_mw_yr,
            NULL AS hyb_stor_fixed_cost_per_mw_yr,
            CASE
                WHEN energy_storage_capacity_mwh IS NULL THEN NULL
                ELSE 0
                END
                AS fixed_cost_per_stor_mwh_yr,
            NULL AS fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr,
            NULL AS fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr,
            NULL AS fuel_storage_capacity_fixed_cost_per_fuelunit_yr
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
    SELECT {disagg_project_name_str} AS project,
        {study_year} as period,
        0 AS fixed_cost_per_mw_yr,
        0 AS fixed_cost_per_energy_mwh_yr,
        0 AS fixed_cost_per_shaping_mw_yr,
        NULL AS hyb_gen_fixed_cost_per_mw_yr,
        NULL AS hyb_stor_fixed_cost_per_mw_yr,
        CASE WHEN raw_data_eia860_generators.prime_mover_code NOT IN ('BA', 
        'ES', 'FW', 'PS') 
            THEN NULL
            ELSE 0
        END
            AS fixed_cost_per_stor_mwh_yr,
        NULL AS fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr,
        NULL AS fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr,
        NULL AS fuel_storage_capacity_fixed_cost_per_fuelunit_yr
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
        {study_year} as period,
        0 AS specified_fixed_cost_mw,
        0 AS fixed_cost_per_energy_mwh_yr,
        0 AS fixed_cost_per_shaping_mw_yr,
        NULL AS hyb_gen_specified_fixed_cost_mw,
        NULL AS hyb_stor_specified_fixed_cost_mw,
        CASE
            WHEN energy_storage_capacity_mwh IS NULL THEN NULL
            ELSE 0
            END 
            AS fixed_cost_per_stor_mwh_yr,
        NULL AS fuel_production_fixed_cost_fuelunitperhour,
        NULL AS fuel_release_fixed_cost_fuelunitperhour,
        NULL AS fuel_storage_fixed_cost_fuelunit
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
        os.path.join(output_directory, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project fixed cost inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    get_project_fixed_cost(
        conn=conn,
        eia860_sql_filter_string=get_eia860_sql_filter_string(
            study_year=parsed_args.study_year, region=parsed_args.region
        ),
        study_year=parsed_args.study_year,
        var_gen_filter_str=VAR_GEN_FILTER_STR,
        hydro_filter_str=HYDRO_FILTER_STR,
        disagg_project_name_str=DISAGG_PROJECT_NAME_STR,
        agg_project_name_str=AGG_PROJECT_NAME_STR,
        output_directory=parsed_args.output_directory,
        subscenario_id=parsed_args.project_fixed_cost_scenario_id,
        subscenario_name=parsed_args.project_fixed_cost_scenario_name,
        aggregate_projects=parsed_args.aggregate_projects,
    )

    conn.close()


if __name__ == "__main__":
    main()
