# Copyright 2026 Sylvan Energy Analytics LLC.
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
Form EIA 860M Project Capacity
******************************

Create specified capacity CSV for a project portfolio based on EIA860M
(monthly) data. This module mirrors
``eia860_to_project_specified_capacity_input_csvs`` but draws on the EIA860M
generator changelog, which is updated monthly and is therefore several months
fresher than the annual EIA860 data.

The changelog holds one row per generator per change, valid from
*report_date* until *valid_until_date*. This module first reduces it to a
snapshot of the fleet as of the ``eia860m_as_of_date`` setting: each
generator's latest changelog row on or before that date, provided the
row was still valid then — generators that VANISHED from EIA's monthly
files without ever filing a retirement (their last row says operating
forever, but EIA's current publication no longer carries them) are
excluded via *valid_until_date*. Note the as-of date is a FILING
(report) date, not an event date: the snapshot is the fleet as EIA had
PUBLISHED it by that month, and units come online one to a few months
before the filing that first reports them, so an as-of snapshot slightly
lags the fleet physically operating on that date (the event date is the
``generator_operating_date`` column, which the study-year window tests).
The as-of date defaults to the latest report date in the changelog, so
default settings yield the latest available snapshot — to approximately
align with the typically older EIA860 vintage instead, set the as-of
date to the report_date in raw_data_eia860_generators (approximately,
because that vintage's label is a year marker, not a filing cutoff — see
the PUDL convert step's docstring). The snapshot then gets the same
study-year, region, and status filters as the EIA860 module — including
the ``planned_inclusion`` setting's status-code tiers: 'U'/'V' (under
construction) and 'TS' (construction complete, not yet in commercial
operation) at the default ``under_construction`` level, plus
'P'/'L'/'T'/'OT' (planned, construction not started) at ``all``.

The ``project_aggregation`` and ``aggregation_dimensions`` settings also
work as in the EIA860 modules (see the portfolio module description); the
EIA860M changelog carries the columns every current aggregation dimension
needs (a dimension needing a column it lacks would fail with a clear
error).

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860m_to_project_specified_capacity_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_eia860m_generators
    * user_defined_eia_gridpath_key
    * raw_data_eia_baa_codes

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
    * eia860m_as_of_date
    * project_specified_capacity_scenario_id
    * project_specified_capacity_scenario_name

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from open_data_toolkit.project.fleet.fleet_filters import (
    get_eia860m_as_of_date_filter_string,
)
from open_data_toolkit.project.fleet.step_common import (
    EIA860M_GENERATORS_TABLE,
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    requests_hybrid_dimension,
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
        "-asof",
        "--eia860m_as_of_date",
        default=None,
        help="Reconstruct the fleet as of this FILING date (YYYY-MM-DD) "
        "from the EIA860M changelog: the fleet as EIA had published it by "
        "that month (publication lags physical commissioning by one to a "
        "few months; generators that vanished from EIA's files by this "
        "date are excluded). Defaults to the latest report date in the "
        "raw_data_eia860m_generators table, i.e., the latest available "
        "snapshot. To approximately align with EIA860-based inputs "
        "instead, set this to the EIA860 vintage (the report_date in "
        "raw_data_eia860_generators).",
    )
    parser.add_argument(
        "-cap_csv",
        "--output_directory",
        default="../../csvs_open_data/project/capacity_specified",
    )
    parser.add_argument(
        "-cap_id", "--project_specified_capacity_scenario_id", default=2
    )
    parser.add_argument(
        "-cap_name",
        "--project_specified_capacity_scenario_name",
        default="base_eia860m",
    )

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
    aggregate_projects=False,
):
    # The two modes share the fleet relation (which carries the as-of-date
    # snapshot filter) but differ in the SELECT list: aggregated groups
    # SUM their units' capacities
    if aggregate_projects:
        sql = f"""
        SELECT {project_name_str} AS project,
            {study_year} as period,
            SUM(capacity_mw) AS specified_capacity_mw,
            NULL AS specified_energy_mwh,
            NULL AS shaping_capacity_mw,
            NULL AS hyb_gen_specified_capacity_mw,
            NULL AS hyb_stor_specified_capacity_mw,
            SUM(CASE
                WHEN raw_data_eia860m_generators.prime_mover_code NOT IN ('BA',
                'ES', 'FW', 'PS') THEN NULL
                ELSE energy_storage_capacity_mwh
            END)
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
        CASE
            WHEN raw_data_eia860m_generators.prime_mover_code NOT IN ('BA',
            'ES', 'FW', 'PS') THEN NULL
            ELSE energy_storage_capacity_mwh
        END
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


def determine_as_of_date(conn, eia860m_as_of_date):
    """
    If no as-of date was specified, default to the latest report date in
    the EIA860M changelog, so that default settings yield the latest
    available fleet snapshot (this also composes correctly with raw data
    generated with the latest-only convert setting). To align EIA860M-based
    inputs with the (typically older) EIA860 vintage instead, set the as-of
    date explicitly — the vintage is in raw_data_eia860_generators'
    report_date column.
    """
    if eia860m_as_of_date is None:
        eia860m_as_of_date = conn.execute(
            "SELECT MAX(report_date) FROM raw_data_eia860m_generators"
        ).fetchone()[0]

    return eia860m_as_of_date


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project specified capacity input CSVs from EIA860M")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    # This early call validates the aggregation settings before any
    # database work; the fleet relation itself is built after connecting,
    # since the as-of-date default is read from the changelog — and when
    # the 'hybrid' dimension is requested, the project name embeds that
    # relation (pairing is against IN-FLEET partners), so the name is
    # rebuilt below with the as-of filter
    project_name_str = get_project_name_str_from_args(
        parsed_args, generators_table=EIA860M_GENERATORS_TABLE
    )

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(
        conn=conn, parsed_args=parsed_args, generators_table=EIA860M_GENERATORS_TABLE
    )

    as_of_date = determine_as_of_date(
        conn=conn, eia860m_as_of_date=parsed_args.eia860m_as_of_date
    )
    as_of_filter_string = get_eia860m_as_of_date_filter_string(as_of_date=as_of_date)

    if requests_hybrid_dimension(parsed_args):
        project_name_str = get_project_name_str_from_args(
            parsed_args,
            generators_table=EIA860M_GENERATORS_TABLE,
            extra_where=as_of_filter_string,
        )

    fleet_relation_sql = get_fleet_relation_sql_from_args(
        parsed_args,
        generators_table=EIA860M_GENERATORS_TABLE,
        extra_where=as_of_filter_string,
    )

    get_project_capacity(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        study_year=parsed_args.study_year,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_specified_capacity_scenario_id,
        subscenario_name=parsed_args.project_specified_capacity_scenario_name,
        aggregate_projects=parsed_args.project_aggregation != "none",
    )

    conn.close()


if __name__ == "__main__":
    main()
