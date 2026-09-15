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

Each project's fuel is named <generic_fuel>_<fuel_region>, with the fuel
region taken from the user_defined_project_fuel_region_key table — an
explicit per-project mapping the user provides (fuel regions in the EIA
AEO can be more disaggregated than BAs, e.g. the CA South and North AEO
regions vs the CISO BA, so a per-BA assignment is not always possible).
Projects without a mapping are skipped (no fuel CSV is written for them);
the fuel-region vocabulary must match user_defined_eiaaeo_region_key's,
which defines the fuels' prices and characteristics.

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``, which also documents
    what the EIA860 data vintage in the raw database means — in
    particular that the latest available vintage (the convert step's
    default) is PUDL's EIA860M-derived reconstruction of the in-progress
    report year, not an as-filed annual survey.

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
    * raw_data_eia_baa_codes
    * user_defined_project_fuel_region_key

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
    * project_fuel_scenario_id
    * project_fuel_scenario_name

"""

import csv
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import sys

from open_data_toolkit.project.fleet.aggregation import DISAGG_PROJECT_NAME_STR
from open_data_toolkit.project.fleet.fleet_filters import FUEL_FILTER_STR
from open_data_toolkit.project.fleet.step_common import (
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
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
    add_shared_project_step_arguments(
        parser=parser, zone_aware=False, aggregation=False
    )
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
    fleet_relation_sql,
    disagg_project_name_str,
    csv_location,
    subscenario_id,
    subscenario_name,
):

    # Only coal, gas, and fuel oil for now (with aeo prices)
    # The fuel region comes from the user's explicit per-project mapping;
    # the LEFT JOIN (in the fleet relation's extra_joins) plus the
    # fuel-is-None guard below skip unmapped projects
    sql = f"""
        SELECT {disagg_project_name_str} AS project,
            gridpath_generic_fuel || '_' || fuel_region as fuel
        {fleet_relation_sql}
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
                newline="",
            ) as filepath:
                writer = csv.writer(filepath, delimiter=",", lineterminator="\n")
                writer.writerow(header)
                writer.writerow([fuel, None, None])


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project fuel inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    # Zone-agnostic step: no BA-map join and the default 'baa' load-zone
    # level (a superset of the portfolio's projects is harmless); the
    # fuel-region key rides in as an extra join, the operational-type
    # filter as an extra WHERE term
    fleet_relation_sql = get_fleet_relation_sql_from_args(
        parsed_args,
        join_ba_map=False,
        extra_joins=f"""
        LEFT JOIN user_defined_project_fuel_region_key ON
            user_defined_project_fuel_region_key.project =
            {DISAGG_PROJECT_NAME_STR}""",
        extra_where=FUEL_FILTER_STR,
    )

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    get_project_fuels(
        conn=conn,
        fleet_relation_sql=fleet_relation_sql,
        disagg_project_name_str=DISAGG_PROJECT_NAME_STR,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_fuel_scenario_id,
        subscenario_name=parsed_args.project_fuel_scenario_name,
    )

    conn.close()


if __name__ == "__main__":
    main()
