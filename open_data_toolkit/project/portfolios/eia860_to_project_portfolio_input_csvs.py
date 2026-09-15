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

All projects are disaggregated (one project per plant/generator) unless the
``project_aggregation`` setting is used: ``all`` aggregates ALL projects to
the technology-load-zone level (see the ``load_zone_level`` setting), while
``agg_project_keyed`` aggregates only the technologies whose
user_defined_eia_gridpath_key row has ``agg_project`` set (e.g. aggregate
wind/solar/hydro, keep thermal units disaggregated) and keeps everything
else as individual units. Aggregate names can be split finer with the
``aggregation_dimensions`` setting — a comma-separated list of named
dimensions inserted between the technology and the load zone (e.g.
``technology_description,vintage_decade`` yields
``Gas_Natural_Gas_Fired_Combined_Cycle_1990s_CISO``); dimensions with no
value for a unit contribute nothing (e.g. with the ``duration`` dimension,
storage aggregates become ``Batteries_4h_<zone>`` while non-storage names
are unchanged). See AGGREGATION_DIMENSIONS in
``open_data_toolkit.project.fleet.aggregation`` for the menu: technology_description,
vintage_decade, duration, status.

By default aggregation happens at the load-zone level itself; the
``aggregation_level`` setting decouples the two, naming (and thereby
aggregating) the aggregate projects at a FINER geographic level than the
zones they are assigned to — e.g. ``load_zone_level custom`` with
``aggregation_level baa`` yields per-BA projects like ``Gas_CT_BPAT``,
each assigned its BA's custom zone. The aggregation level must refine the
load-zone level over the in-footprint BAs (every aggregated project must
belong to exactly one load zone); the steps verify this against the BA
map before querying and fail loudly otherwise.

All these settings must be set consistently across the project-level
steps.

Individual units can additionally be pinned past the automated selection
and aggregation with the OPTIONAL ``user_defined_unit_overrides`` table
(empty by default — a no-op): force a unit into or out of the fleet,
carve a plant into its own aggregate project (e.g. ``Hydro_Hoover``), or
override its load zone. See
``open_data_toolkit.project.fleet.unit_overrides`` for the semantics.

.. note:: Hybrid projects are currently not treated separately by this
    module: their generation and storage components show up as individual
    units.

Project portfolios are created from whichever EIA860 data vintage was
loaded into the raw database — the ``eia860_report_date`` chosen at
convert time (``gridpath_pudl_to_gridpath_raw_data``), recorded in the
``report_date`` column of raw_data_eia860_generators. Know which KIND of
vintage that is, because the convert step defaults to the LATEST one and
the latest is normally not an annual filing at all:

* completed report years are as-filed annual survey data (PUDL
  ``data_maturity`` ``final``, or ``provisional`` for a recent year whose
  form has been released but not yet finalized);
* the latest vintage is PUDL's RECONSTRUCTION of the in-progress report
  year from EIA860M (``data_maturity = 'monthly_update'``): the fleet as
  EIA's current monthly publication has it, relabeled to Jan 1 of that
  year. The Jan-1 label is a year marker, NOT an information cutoff — the
  data is as fresh as the last EIA860M month the PUDL release ingested
  (verified Aug 2026: it matched EIA's then-current EIA860M publication
  unit for unit).

The reconstruction is a good default for the project steps: every column
they read — status codes, capacities, operating/retirement dates, the
sector name behind the ``include_btm_plants`` exclusion, and all the
``aggregation_dimensions`` columns — is populated there. What it lacks
are the annual-form-only columns (minimum load, multi-fuel and
carbon-capture flags, second energy source, ownership, cogen status),
which no project step reads. If some other consumer needs those, prefer
the convert step's ``eia860_annual_detail_report_date`` setting, which
backfills them from a pinned as-filed vintage while keeping this fresh
fleet, over pinning an older vintage wholesale (which would model a
staler fleet — measured Aug 2026: an as-filed portfolio one report year
back differed from the current fleet by several hundred units in the
western interconnect alone).

.. warning:: Do not mix vintages ACROSS steps — e.g. an old as-filed
    portfolio with capacities from a fresh
    ``eia860m_to_project_specified_capacity_input_csvs`` run. The
    portfolio defines the project universe, so newer generators are
    silently dropped rather than added, while portfolio projects the
    fresh snapshot no longer carries end up with no capacity at all
    (caught by ``gridpath_validate`` as a High-severity error). Loading
    two EIA860 vintages into one raw database is worse still: no step
    filters on ``report_date``, so every generator appears twice and
    aggregated capacities silently double.

The user selects the footprint (determines the subset of generators
to use) and the study year (determines which generators are in the fleet).
By default the fleet consists of the units expected to be operational in
the study year: operating units that don't retire before the end of the
study year, plus units already under construction (or with construction
complete) whose planned operating date is on or before Jan 1 of the study
year, minus units EIA expects to be gone by then: a unit still
operating but with a filed PLANNED retirement date before the end of
the study year is excluded by default (``include_planned_retirements``
keeps such units instead — planned retirement dates are softer
commitments than filed retirements, they slip and get withdrawn, so a
study may choose not to trust them; units with no planned retirement
date are always kept, and if the raw data predates the
planned-retirement column entirely, a loud warning flags that the
exclusion is doing nothing). Three more settings adjust this window.
``include_retired`` also keeps
retired units (and drops the retirement-date window).
``planned_inclusion`` selects which not-yet-operational units count,
always subject to the planned-operating-date window: the default
``under_construction``; ``all``, which additionally includes planned
units on which construction has not started (a more speculative fleet —
such units are more likely to slip or be cancelled); or ``none``, which
keeps only currently operating units. ``inactive_inclusion`` selects
which existing-but-not-operating units count, cumulatively in order of
how available they are: ``standby`` adds standby/backup units (available
for service but not normally used); ``out_of_service_short_term`` also
adds out-of-service units expected back in service within the next
calendar year; ``all`` also adds long-term out-of-service units; the
default ``none`` adds none of them. Behind-the-meter-type units — the
commercial/industrial EIA sectors (Commercial/Industrial CHP and
Non-CHP) — are excluded by default: their output typically serves onsite
load, so it is netted out of the metered demand that EIA-930-derived
load is built from and absent from BA generation telemetry, and modeling
them as supply resources alongside that load would double-count their
energy. ``include_btm_plants`` opts them back in; units with no sector
in the raw data cannot be classified and are always kept (with a loud
warning). The same window (and the same settings) applies in all the
EIA860(M)-based project steps and should be set consistently across
them.

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
    * include_btm_plants
    * ba_source
    * load_zone_level
    * project_aggregation
    * aggregation_dimensions
    * aggregation_level
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
        default="../../csvs_open_data/project/portfolios",
    )
    parser.add_argument("-p_id", "--project_portfolio_scenario_id", default=1)
    parser.add_argument(
        "-p_name", "--project_portfolio_scenario_name", default="wecc_plants_units"
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_project_portfolio_for_region(
    conn,
    project_name_str,
    fleet_relation_sql,
    csv_location,
    subscenario_id,
    subscenario_name,
    aggregate_projects=False,
):
    # In aggregated modes the name expression maps units to their
    # aggregate and GROUP BY collapses them (per-unit names ride through
    # as singleton groups in the keyed mode); disaggregated names are
    # unique per row, so no GROUP BY is needed there
    group_by_sql = "GROUP BY project" if aggregate_projects else ""
    sql = f"""
    SELECT {project_name_str} AS project,
    NULL as specified,
    NULL as new_build,
    gridpath_capacity_type AS capacity_type
    {fleet_relation_sql}
    {group_by_sql}
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

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    get_project_portfolio_for_region(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_portfolio_scenario_id,
        subscenario_name=parsed_args.project_portfolio_scenario_name,
        aggregate_projects=parsed_args.project_aggregation != "none",
    )

    conn.close()


if __name__ == "__main__":
    main()
