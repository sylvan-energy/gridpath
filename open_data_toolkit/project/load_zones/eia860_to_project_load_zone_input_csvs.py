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
Form EIA 860 Project Load Zones
*******************************

This module creates project load zone input CSVs for a EIA860-based project
portfolio based on the user-defined mapping in the
user_defined_eia_gridpath_key table.

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``, which also documents
    what the EIA860 data vintage in the raw database means — in
    particular that the latest available vintage (the convert step's
    default) is PUDL's EIA860M-derived reconstruction of the in-progress
    report year, not an as-filed annual survey.

Per-unit ``load_zone`` overrides from ``user_defined_unit_overrides``
(see ``open_data_toolkit.project.fleet.unit_overrides``) apply here, and the
step verifies that every project resolves to exactly ONE load zone
before writing the CSV — a violation (e.g. an aggregation carve-out
whose units' zones disagree) fails loudly rather than riding into the
inputs as duplicate rows.

After writing the CSV, the step cross-checks the assigned zones against the
system load zones that ``eia930_load_zone_input_csvs`` derives for the same
footprint and load-zone level, and warns (even with ``quiet``) about any
project zone missing there — such projects would reference a load zone with
no load balance and only fail later, at model load (e.g. islanded BAs like
HECO that are in the BA map but never appear in the interchange data, with
``--footprint all --load_zone_level baa``). The check is skipped if no
EIA930 interchange data is loaded.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_load_zone_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

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
    * project_load_zone_scenario_id
    * project_load_zone_scenario_name

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from open_data_toolkit.geographic_scope import (
    warn_on_project_load_zones_missing_from_system,
)
from open_data_toolkit.project.fleet.unit_overrides import (
    check_one_zone_per_project,
    get_project_load_zone_str,
)
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
        default="../../csvs_open_data/project/load_zones",
    )
    parser.add_argument("-lz_id", "--project_load_zone_scenario_id", default=1)
    parser.add_argument(
        "-lz_name", "--project_load_zone_scenario_name", default="wecc_baas"
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_project_load_zones(
    conn,
    project_name_str,
    fleet_relation_sql,
    load_zone_str,
    output_directory,
    subscenario_id,
    subscenario_name,
    aggregate_projects=False,
):
    # Grouping by (project, load_zone) rather than project alone keeps a
    # project spanning zones visible as multiple rows, so the one-zone
    # check below can catch it (bare GROUP BY project would collapse it
    # to one arbitrary zone); for a healthy fleet the output is identical
    group_by_sql = "GROUP BY project, load_zone" if aggregate_projects else ""
    sql = f"""
    SELECT {project_name_str} AS project,
        {load_zone_str} AS load_zone
    {fleet_relation_sql}
    {group_by_sql}
    ;
    """

    df = pd.read_sql(sql, conn)
    check_one_zone_per_project(project_load_zones_df=df)
    df.to_csv(
        os.path.join(output_directory, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )

    return df


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project load zone inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    project_load_zones_df = get_project_load_zones(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        load_zone_str=get_project_load_zone_str(
            load_zone_level=parsed_args.load_zone_level, footprint=parsed_args.footprint
        ),
        output_directory=parsed_args.output_directory,
        subscenario_id=parsed_args.project_load_zone_scenario_id,
        subscenario_name=parsed_args.project_load_zone_scenario_name,
        aggregate_projects=parsed_args.project_aggregation != "none",
    )

    # Cross-check against the system load zones the eia930_load_zone step
    # derives: a project zone missing there would only fail at model load
    warn_on_project_load_zones_missing_from_system(
        conn=conn,
        footprint=parsed_args.footprint,
        load_zone_level=parsed_args.load_zone_level,
        project_load_zones=project_load_zones_df["load_zone"].unique(),
        quiet=parsed_args.quiet,
    )

    conn.close()


if __name__ == "__main__":
    main()
