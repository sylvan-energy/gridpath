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
Fleet Audit
***********

Report what the EIA860-based project pipeline decided about EVERY unit in
the raw generator data for a given set of settings — the intermediate
checkpoint between the raw data and the generated input CSVs. For each
unit, the audit CSV (``fleet_audit.csv`` in the output directory) shows:

* the unit's BA per source — EIA-860 as reported, its EIA-930A
  operational BAs, any manual override — and the RESOLVED BA the pipeline
  used (stage 0, see ``open_data_toolkit.project.fleet.ba_assignment``), plus the
  load zone at the chosen level (with any per-unit load_zone override
  applied);
* any per-unit overrides from ``user_defined_unit_overrides``
  (``override_include``/``override_aggregation``/``override_load_zone``;
  see ``open_data_toolkit.project.fleet.unit_overrides``) — the include
  override folds into the ``in_fleet`` verdict exactly as in the fleet
  relation the steps query;
* pass/fail per selection stage: whether the unit's prime mover/fuel has
  a ``user_defined_eia_gridpath_key`` row at all, the geographic
  footprint/zone filter (stage 1, ``open_data_toolkit.geographic_scope``), and
  the characteristic filters — planned-date window, status/retirement,
  behind-the-meter — individually and combined (stage 2,
  ``open_data_toolkit.project.fleet.fleet_filters``);
* the final verdict (``in_fleet``) and, for in-fleet units, the project
  name the unit lands in under the aggregation settings (stage 3,
  ``open_data_toolkit.project.fleet.aggregation``).

A units/MW waterfall per stage is printed, and the audit CROSS-CHECKS its
verdicts against the actual fleet relation the input-CSV steps query
(``get_fleet_relation_sql``) — a mismatch is reported loudly and means
this module has drifted from the pipeline.

Run it with the SAME settings as the project input-CSV steps (footprint,
study year, fleet selection, ba_source, load-zone level, aggregation).
The audit covers the EIA-860 annual table, whose loaded vintage it
inherits — note that the latest vintage is PUDL's EIA860M-derived
reconstruction of the in-progress report year rather than an as-filed
annual survey (see
``eia860_to_project_portfolio_input_csvs``); the ``report_date`` column
in the audit CSV records which vintage each unit came from. The
EIA860M-based capacity step additionally applies an as-of-date snapshot
filter not audited here.

=====
Usage
=====

>>> gridpath_fleet_audit --database PATH/TO/RAW/DB --output_directory PATH/TO/OUTPUT

or via the orchestrator:

>>> gridpath_run_data_toolkit --single_step fleet_audit --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been
populated:

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

"""

import os.path
import sys
from argparse import ArgumentParser

import pandas as pd

from gridpath.common_functions import get_version_parser

from open_data_toolkit.geographic_scope import get_footprint_scope_sql
from open_data_toolkit.project.fleet.unit_overrides import (
    get_project_load_zone_str,
    get_unit_override_sql,
)
from open_data_toolkit.project.fleet.ba_assignment import (
    GENERATORS_TABLE_COLUMNS,
    MANUAL_BAA_OVERRIDE_SQL,
    EIA930A_ASSIGNMENT_JOIN_SQL,
    EIA930A_RESOLVED_BA_CASE_SQL,
)
from open_data_toolkit.project.fleet.fleet_filters import (
    get_allowed_status_codes,
    get_geographic_filter_string,
    get_planned_date_window_string,
    get_retired_filter_string,
    get_btm_filter_string,
    get_characteristics_filter_string,
)
from open_data_toolkit.project.fleet.step_common import (
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    warn_on_fleet_data_gaps,
    add_shared_project_step_arguments,
)

AUDIT_FILE_NAME = "fleet_audit.csv"


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
        default="../../csvs_open_data/project/fleet_audit",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_fleet_audit_sql(
    ba_source,
    study_year,
    footprint,
    load_zone_level,
    include_retired,
    planned_inclusion,
    inactive_inclusion,
    include_planned_retirements,
    include_btm_plants,
    project_name_str,
):
    """
    The per-unit audit query: every raw_data_eia860_generators unit with
    its per-source and resolved BA (mirroring get_generators_table_str —
    the audit's cross-check against the real fleet relation guards this
    mirror), its load zone, a 0/1 flag per selection stage built from the
    SAME filter-string builders the input-CSV steps use, the combined
    in_fleet verdict, and the stage-3 project name for in-fleet units.
    """
    # The audit joins EIA-930A unconditionally (to SHOW each unit's 930A
    # BAs under either ba_source); the resolution mirrors
    # get_generators_table_str for the chosen source
    if ba_source == "eia860":
        resolved_ba_sql = f"""COALESCE(
            {MANUAL_BAA_OVERRIDE_SQL},
            g.balancing_authority_code_eia
            )"""
    else:
        resolved_ba_sql = f"""COALESCE(
            {MANUAL_BAA_OVERRIDE_SQL},
            {EIA930A_RESOLVED_BA_CASE_SQL}
            )"""

    columns_str = ",\n            ".join(
        f"g.{c}" for c in GENERATORS_TABLE_COLUMNS["raw_data_eia860_generators"]
    )

    # The filter predicates below reference balancing_authority_code_eia
    # (and the unit's characteristic columns) unqualified, exactly as in
    # the input-CSV steps' queries — the inner relation re-exposes the
    # RESOLVED BA under that name (the per-source values ride alongside
    # under their own names), so the same filter strings apply unchanged
    geographic_filter = get_geographic_filter_string(
        footprint=footprint, load_zone_level=load_zone_level
    )
    characteristics_filter = get_characteristics_filter_string(
        study_year=study_year,
        include_retired=include_retired,
        planned_inclusion=planned_inclusion,
        inactive_inclusion=inactive_inclusion,
        include_planned_retirements=include_planned_retirements,
        include_btm_plants=include_btm_plants,
    )
    # Sub-flags: the individual pieces the characteristics filter is
    # composed of; the AND-prefixed builders become bare predicates by
    # prepending the same '1 = 1' the step queries use
    date_window_predicate = get_planned_date_window_string(study_year=study_year)
    status_retirement_predicate = "1 = 1 " + get_retired_filter_string(
        study_year=study_year,
        allowed_status_codes=get_allowed_status_codes(
            planned_inclusion=planned_inclusion,
            inactive_inclusion=inactive_inclusion,
        ),
        include_retired=include_retired,
        include_planned_retirements=include_planned_retirements,
    )
    btm_predicate = "1 = 1 " + get_btm_filter_string(
        include_btm_plants=include_btm_plants
    )

    load_zone_str = get_project_load_zone_str(
        load_zone_level=load_zone_level, footprint=footprint
    )
    footprint_scope_sql = get_footprint_scope_sql(
        footprint=footprint, load_zone_level=load_zone_level
    )

    # Per-unit overrides (user_defined_unit_overrides): shown per column,
    # and the include override folds into the in_fleet verdict exactly as
    # in get_fleet_relation_sql (bypassing/failing the characteristics
    # stage only)
    include_override_sql = get_unit_override_sql(column="include")
    aggregation_override_sql = get_unit_override_sql(column="aggregation")
    load_zone_override_sql = get_unit_override_sql(column="load_zone")
    in_fleet_predicate = f"""gridpath_technology IS NOT NULL
            AND {geographic_filter}
            AND COALESCE(({include_override_sql}) = 1, ({characteristics_filter}
            ))"""

    return f"""
    SELECT
        plant_id_eia,
        generator_id,
        report_date,
        capacity_mw,
        operational_status_code,
        technology_description,
        sector_name_eia,
        raw_data_eia860_generators.prime_mover_code,
        energy_source_code_1,
        eia860_ba,
        eia930a_bas,
        override_ba,
        balancing_authority_code_eia AS resolved_ba,
        CASE WHEN {footprint_scope_sql} THEN {load_zone_str} END AS load_zone,
        CASE WHEN gridpath_technology IS NOT NULL THEN 1 ELSE 0 END
            AS has_gridpath_key,
        CASE WHEN {geographic_filter} THEN 1 ELSE 0 END AS in_footprint,
        CASE WHEN {date_window_predicate} THEN 1 ELSE 0 END
            AS passes_date_window,
        CASE WHEN {status_retirement_predicate} THEN 1 ELSE 0 END
            AS passes_status_retirement,
        CASE WHEN {btm_predicate} THEN 1 ELSE 0 END AS passes_btm,
        {include_override_sql} AS override_include,
        {aggregation_override_sql} AS override_aggregation,
        {load_zone_override_sql} AS override_load_zone,
        CASE WHEN {in_fleet_predicate}
            THEN 1 ELSE 0 END AS in_fleet,
        CASE WHEN {in_fleet_predicate}
            THEN {project_name_str} END AS project
    FROM (
        SELECT
            {columns_str},
            g.balancing_authority_code_eia AS eia860_ba,
            eia930a.bas AS eia930a_bas,
            {MANUAL_BAA_OVERRIDE_SQL} AS override_ba,
            {resolved_ba_sql} AS balancing_authority_code_eia
        FROM raw_data_eia860_generators g{EIA930A_ASSIGNMENT_JOIN_SQL}
    ) AS raw_data_eia860_generators
    LEFT JOIN user_defined_eia_gridpath_key ON
            raw_data_eia860_generators.prime_mover_code =
            user_defined_eia_gridpath_key.prime_mover_code
            AND energy_source_code_1 = energy_source_code
    LEFT JOIN raw_data_eia_baa_codes ON
            balancing_authority_code_eia = raw_data_eia_baa_codes.baa
    ;
    """


def print_fleet_waterfall(audit_df):
    """
    Print the units/MW selection waterfall from the audit dataframe: each
    line counts units passing that stage AND all previous ones, so the
    numbers only ever shrink; the stage-2 sub-lines show the individual
    characteristic filters within the stage-1 survivors.
    """

    def line(label, mask):
        n = int(mask.sum())
        mw = audit_df.loc[mask, "capacity_mw"].sum()
        print(f"    {label:<58}{n:>7} units {round(mw):>9} MW")

    all_units = pd.Series(True, index=audit_df.index)
    keyed = audit_df["has_gridpath_key"] == 1
    in_footprint = keyed & (audit_df["in_footprint"] == 1)
    date_ok = in_footprint & (audit_df["passes_date_window"] == 1)
    status_ok = in_footprint & (audit_df["passes_status_retirement"] == 1)
    btm_ok = in_footprint & (audit_df["passes_btm"] == 1)
    in_fleet = audit_df["in_fleet"] == 1

    print("Fleet selection waterfall (units passing this AND previous stages):")
    line("EIA-860 units in the raw data", all_units)
    line("with a user_defined_eia_gridpath_key row", keyed)
    line("stage 1: in footprint, with a load zone at the level", in_footprint)
    line("stage 2:   pass planned-date window", date_ok)
    line("stage 2:   pass status/retirement selection", status_ok)
    line("stage 2:   pass behind-the-meter exclusion", btm_ok)
    force_included = in_fleet & in_footprint & (audit_df["override_include"] == 1)
    force_excluded = in_footprint & keyed & (audit_df["override_include"] == 0)
    if force_included.any():
        line("    force-included by unit override", force_included)
    if force_excluded.any():
        line("    force-excluded by unit override", force_excluded)
    line("IN FLEET (all stages)", in_fleet)
    n_projects = audit_df.loc[in_fleet, "project"].nunique()
    print(f"    {'stage 3: aggregated into projects':<58}{n_projects:>7} projects")


def check_against_fleet_relation(conn, audit_df, fleet_relation_sql):
    """
    Cross-check the audit's in_fleet verdicts against the ACTUAL fleet
    relation the input-CSV steps query. A mismatch is reported loudly —
    regardless of any quiet setting — and means the audit has drifted
    from the pipeline; trust the pipeline, fix the audit. Returns True
    when the two agree.
    """
    fleet_units = {
        (plant, gen)
        for plant, gen in conn.cursor().execute(
            f"SELECT plant_id_eia, generator_id {fleet_relation_sql}"
        )
    }
    audit_units = {
        (row.plant_id_eia, row.generator_id)
        for row in audit_df[audit_df["in_fleet"] == 1].itertuples()
    }

    if fleet_units != audit_units:
        audit_only = audit_units - fleet_units
        fleet_only = fleet_units - audit_units
        print(
            f"WARNING: the fleet audit's in_fleet verdicts do not match "
            f"the fleet relation the input-CSV steps query "
            f"({len(audit_only)} units audit-only, {len(fleet_only)} "
            f"fleet-only) — the audit has drifted from the pipeline and "
            f"its flags cannot be trusted until fleet_audit.py is fixed."
        )
        return False

    return True


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Auditing the project fleet selection")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)
    audit_sql = get_fleet_audit_sql(
        ba_source=parsed_args.ba_source,
        study_year=parsed_args.study_year,
        footprint=parsed_args.footprint,
        load_zone_level=parsed_args.load_zone_level,
        include_retired=parsed_args.include_retired,
        planned_inclusion=parsed_args.planned_inclusion,
        inactive_inclusion=parsed_args.inactive_inclusion,
        include_planned_retirements=parsed_args.include_planned_retirements,
        include_btm_plants=parsed_args.include_btm_plants,
        project_name_str=project_name_str,
    )

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    audit_df = pd.read_sql(audit_sql, conn)
    audit_df.to_csv(
        os.path.join(parsed_args.output_directory, AUDIT_FILE_NAME), index=False
    )

    check_against_fleet_relation(
        conn=conn, audit_df=audit_df, fleet_relation_sql=fleet_relation_sql
    )

    if not parsed_args.quiet:
        print_fleet_waterfall(audit_df=audit_df)

    conn.close()


if __name__ == "__main__":
    main()
