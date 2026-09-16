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
    from ``eia860_to_project_portfolio_input_csvs``, which also documents
    what the EIA860 data vintage in the raw database means — in
    particular that the latest available vintage (the convert step's
    default) is PUDL's EIA860M-derived reconstruction of the in-progress
    report year, not an as-filed annual survey.

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
    * footprint
    * include_retired
    * planned_inclusion
    * inactive_inclusion
    * include_planned_retirements
    * exclude_commercial_industrial_sectors
    * include_net_metered
    * ba_source
    * load_zone_level
    * project_aggregation
    * aggregation_dimensions
    * aggregation_level
    * project_fixed_cost_scenario_id
    * project_fixed_cost_scenario_name

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from open_data_toolkit.project.fleet.step_common import (
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    warn_on_fleet_data_gaps,
    add_shared_project_step_arguments,
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
    add_shared_project_step_arguments(parser=parser)
    parser.add_argument(
        "-o",
        "--output_directory",
        default="../../csvs_open_data/project/fixed_cost",
    )
    parser.add_argument("-fcost_id", "--project_fixed_cost_scenario_id", default=1)
    parser.add_argument(
        "-fcost_name", "--project_fixed_cost_scenario_name", default="base"
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_project_fixed_cost(
    conn,
    project_name_str,
    fleet_relation_sql,
    study_year,
    output_directory,
    subscenario_id,
    subscenario_name,
    aggregate_projects=False,
):
    # The two modes share the fleet relation but differ in the SELECT
    # list. NOTE the pre-existing drift in the storage-cost CASE: the
    # aggregated branch tests energy_storage_capacity_mwh IS NULL while
    # the disaggregated branch tests the storage prime-mover codes —
    # preserved as-is here (flagged for review, not silently changed)
    if aggregate_projects:
        sql = f"""
        SELECT {project_name_str} AS project,
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
        {fleet_relation_sql}
         GROUP BY project
        ;
        """
    else:
        sql = f"""
    SELECT {project_name_str} AS project,
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
    {fleet_relation_sql}
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

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    get_project_fixed_cost(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        study_year=parsed_args.study_year,
        output_directory=parsed_args.output_directory,
        subscenario_id=parsed_args.project_fixed_cost_scenario_id,
        subscenario_name=parsed_args.project_fixed_cost_scenario_name,
        aggregate_projects=parsed_args.project_aggregation != "none",
    )

    conn.close()


if __name__ == "__main__":
    main()
