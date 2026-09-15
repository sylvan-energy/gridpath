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
Form EIA 860 Project Availability
*********************************

Create availability type CSV for a EIA860-based project portfolio. Availability
types are set to 'exogenous' for all projects with no exogenous profiles
specified (i.e., always available).

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``, which also documents
    what the EIA860 data vintage in the raw database means — in
    particular that the latest available vintage (the convert step's
    default) is PUDL's EIA860M-derived reconstruction of the in-progress
    report year, not an as-filed annual survey.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_availability_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

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
    * include_btm_plants
    * include_net_metered
    * ba_source
    * load_zone_level
    * project_aggregation
    * aggregation_dimensions
    * aggregation_level
    * project_availability_scenario_id
    * project_availability_scenario_name

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
        "-avl_csv",
        "--output_directory",
        default="../../csvs_open_data/project/availability",
    )
    parser.add_argument("-avl_id", "--project_availability_scenario_id", default=1)
    parser.add_argument(
        "-avl_name", "--project_availability_scenario_name", default="no_derates"
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_project_availability(
    conn,
    project_name_str,
    fleet_relation_sql,
    csv_location,
    subscenario_id,
    subscenario_name,
    aggregate_projects=False,
):
    # NOTE: the aggregated branch used to omit the
    # exogenous_availability_monthly_scenario_id column (drift between the
    # two branches), which would have failed the exact-column-match CSV
    # port; both modes now write the full column set
    group_by_sql = "GROUP BY project" if aggregate_projects else ""
    sql = f"""
    SELECT {project_name_str} AS project,
    'exogenous' AS availability_type,
    NULL AS exogenous_availability_independent_scenario_id,
    NULL AS exogenous_availability_weather_scenario_id,
    NULL AS exogenous_availability_independent_bt_hrz_scenario_id,
    NULL AS exogenous_availability_weather_bt_hrz_scenario_id,
    NULL AS exogenous_availability_monthly_scenario_id,
    NULL AS endogenous_availability_scenario_id
    {fleet_relation_sql}
    {group_by_sql}
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
        print("Creating project availability inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    get_project_availability(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_availability_scenario_id,
        subscenario_name=parsed_args.project_availability_scenario_name,
        aggregate_projects=parsed_args.project_aggregation != "none",
    )

    conn.close()


if __name__ == "__main__":
    main()
