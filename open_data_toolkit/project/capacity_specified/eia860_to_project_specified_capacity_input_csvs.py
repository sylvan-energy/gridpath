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
Form EIA 860 Project Capacity
*****************************

Create specified capacity CSV for a EIA860-based project portfolio.

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``, which also documents
    what the EIA860 data vintage in the raw database means — in
    particular that the latest available vintage (the convert step's
    default) is PUDL's EIA860M-derived reconstruction of the in-progress
    report year, not an as-filed annual survey.

Storage units with no EIA-reported energy capacity — common among
planned and under-construction batteries — contribute no
``specified_stor_capacity_mwh``, which silently understates an
aggregated project whenever some (but not all) of its units are unrated.
The ``default_battery_duration_hours`` and
``default_pumped_storage_duration_hours`` settings fill such units PER
UNIT as duration × capacity_mw before aggregation (see
``open_data_toolkit.project.fleet.storage_durations``); the run prints what was
filled, and the fleet audit's ``energy_mwh_source`` column shows the
assumption per unit under the same settings.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_specified_capacity_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

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
    * require_plant_in_eia860_vintage
    * ba_source
    * load_zone_level
    * project_aggregation
    * aggregation_dimensions
    * aggregation_level
    * hybrid_treatment
    * default_battery_duration_hours
    * default_pumped_storage_duration_hours
    * project_specified_capacity_scenario_id
    * project_specified_capacity_scenario_name

"""

import csv
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from open_data_toolkit.project.fleet.step_common import (
    EIA860_GENERATORS_TABLE,
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    warn_on_fleet_data_gaps,
    add_shared_project_step_arguments,
)
from open_data_toolkit.project.fleet.storage_durations import (
    add_default_storage_duration_arguments,
    get_default_durations_from_args,
    get_specified_stor_capacity_mwh_expr,
    report_default_storage_duration_fill,
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
        "-cap_csv",
        "--output_directory",
        default="../../csvs_open_data/project/capacity_specified",
    )
    parser.add_argument(
        "-cap_id", "--project_specified_capacity_scenario_id", default=1
    )
    parser.add_argument(
        "-cap_name", "--project_specified_capacity_scenario_name", default="base"
    )
    add_default_storage_duration_arguments(parser=parser)

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_project_capacity(
    conn,
    project_name_str,
    fleet_relation_sql,
    study_year,
    csv_location,
    subscenario_id,
    subscenario_name,
    default_durations,
    aggregate_projects=False,
):
    # The per-unit storage energy capacity, with any requested
    # default-duration fill for unrated units
    stor_capacity_mwh_expr = get_specified_stor_capacity_mwh_expr(
        generators_table=EIA860_GENERATORS_TABLE,
        default_durations=default_durations,
    )

    # The two modes share the fleet relation but differ in the SELECT
    # list: aggregated groups SUM their units' capacities
    if aggregate_projects:
        sql = f"""
        SELECT {project_name_str} AS project,
            {study_year} as period,
            SUM(capacity_mw) AS specified_capacity_mw,
            NULL AS specified_energy_mwh,
            NULL AS shaping_capacity_mw,
            NULL AS hyb_gen_specified_capacity_mw,
            NULL AS hyb_stor_specified_capacity_mw,
            SUM({stor_capacity_mwh_expr})
                AS specified_stor_capacity_mwh,
            NULL AS fuel_production_capacity_fuelunitperhour,
            NULL AS fuel_release_capacity_fuelunitperhour,
            NULL AS fuel_storage_capacity_fuelunit
        {fleet_relation_sql}
         GROUP BY project
        ;
        """
    else:
        sql = f"""
    SELECT {project_name_str} AS project,
        {study_year} as period,
        capacity_mw AS specified_capacity_mw,
        NULL AS specified_energy_mwh,
        NULL AS shaping_capacity_mw,
        NULL AS hyb_gen_specified_capacity_mw,
        NULL AS hyb_stor_specified_capacity_mw,
        {stor_capacity_mwh_expr}
            AS specified_stor_capacity_mwh,
        NULL AS fuel_production_capacity_fuelunitperhour,
        NULL AS fuel_release_capacity_fuelunitperhour,
        NULL AS fuel_storage_capacity_fuelunit
    {fleet_relation_sql}
    ;
    """

    df = pd.read_sql(sql, conn)
    df.to_csv(
        os.path.join(csv_location, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project specified capacity input CSVs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)
    default_durations = get_default_durations_from_args(parsed_args)

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    get_project_capacity(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        study_year=parsed_args.study_year,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_specified_capacity_scenario_id,
        subscenario_name=parsed_args.project_specified_capacity_scenario_name,
        default_durations=default_durations,
        aggregate_projects=parsed_args.project_aggregation != "none",
    )

    report_default_storage_duration_fill(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        default_durations=default_durations,
        generators_table=EIA860_GENERATORS_TABLE,
    )

    conn.close()


if __name__ == "__main__":
    main()
