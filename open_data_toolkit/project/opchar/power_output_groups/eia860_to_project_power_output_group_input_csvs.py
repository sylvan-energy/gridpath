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
Create the power-output-group input CSVs coupling each hybrid plant's
components under a shared interconnection (POI) limit — the
``power_output_group`` hybrid treatment (see the ``hybrid_treatment``
setting). Hybrid components stay separate projects (the solar/wind unit
and the battery, or their ``hybrid``-dimension aggregates); this step
generates the two subscenario CSVs GridPath's core
``project.operations.power_output_groups`` module consumes:

* ``projects/`` — group membership (``inputs_project_power_output_groups``,
  selected by ``project_power_output_group_scenario_id``);
* ``requirements/`` — the per-period min/max on the group's combined
  output (``inputs_project_power_output_group_requirements``, selected by
  ``project_power_output_group_requirement_scenario_id``).

Hybrid components are paired exactly as in the ``hybrid`` aggregation
dimension (direct-support links from the EIA860 energy-storage
supplement, falling back to plant co-location; in-fleet partners only —
see the portfolio step's documentation), then clustered: units connected
by co-location or by support links form one hybrid installation. In the
disaggregated mode each cluster becomes its own group, named
``hybrid_<smallest plant id>``; in an aggregated mode (which requires the
``hybrid`` aggregation dimension) the clusters in each geographic name
token merge into one group per token, named ``hybrid_<token>``, whose
members are the hybrid aggregate projects and whose limit is the SUM of
the member clusters' POI limits — a documented relaxation (headroom can
be reallocated across the token's plants; per-plant groups are impossible
once components are aggregated).

**The POI limit is an assumption, not data**: EIA-860 collects no
point-of-interconnection capacity. The default rule (``max_component``)
takes each cluster's limit as max(total variable-component AC nameplate,
total battery MW): the AC nameplate is each component's inverter/turbine
limit, and a shared POI cannot be smaller than the largest component that
ever uses it alone. The ``sum`` rule instead writes the (non-binding) sum
of both sides — pure plumbing until real limits replace it. Correct known
limits by editing the generated requirements CSV.

**The battery side's MW basis** is the ``hybrid_battery_mw_basis``
setting. The default, ``nameplate``, uses the battery's ``capacity_mw``
from the fleet (generators) table — the same number the capacity step
writes as the member's ``specified_capacity_mw``, so the group limit and
the member capacity agree by construction. ``discharge_rating`` instead
uses the EIA-860 energy-storage supplement's ``max_discharge_rate_mw``
where a row is filed (nameplate otherwise). The supplement is an
annual-form-only table pinned to one (by default the latest annual)
vintage by the convert step, typically a year behind the fleet table's
860M-derived reconstruction of the in-progress year; its ratings can
describe an earlier build stage of a battery that has since expanded, or
carry filing errors, so ``discharge_rating`` mixes EIA-860 vintages within
one scenario and can put a group's cap BELOW its battery member's own
modeled capacity. Under either basis the step warns — regardless of
``quiet`` — for every hybrid battery whose filed discharge rating differs
from its nameplate by more than 10 %, listing both values: those rows are
the ones that need a human look.

.. note:: The group couples net output within ``[0, POI]``. GridPath's
    group minimum parameter is non-negative (default 0), so a grouped
    hybrid can never be a net load: the battery only charges from
    concurrent co-located generation — the ITC-era operating mode of most
    existing hybrids, and conservative for adequacy. POI-limited GRID
    charging is not expressible with the current model-side parameter
    domain.

Run this step only with ``hybrid_treatment power_output_group`` (it
refuses otherwise): the same setting makes the opchar step flip paired
variable components from ``gen_var_must_take`` to the curtailable
``gen_var``, without which a plant whose variable component alone can
exceed the POI makes the group constraint infeasible. Run it with the
SAME shared settings as the other project-level steps — the member
project names must match the portfolio's exactly.

=====
Usage
=====

>>> gridpath_eia860_to_project_power_output_group_input_csvs --database PATH/TO/RAW/DB --output_directory PATH/TO/CSV/DIR

or via the orchestrator:

>>> gridpath_run_data_toolkit --single_step eia860_to_project_power_output_group_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been
populated:

* raw_data_eia860_generators
* raw_data_eia860_energy_storage
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
    * hybrid_poi_rule
    * hybrid_battery_mw_basis
    * project_power_output_group_scenario_id
    * project_power_output_group_scenario_name
    * project_power_output_group_requirement_scenario_id
    * project_power_output_group_requirement_scenario_name

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from open_data_toolkit.project.fleet.aggregation import get_geographic_token_str
from open_data_toolkit.project.fleet.fleet_filters import (
    HYBRID_STORAGE_PRIME_MOVERS,
    get_hybrid_pairing_expr,
    get_support_links_sql,
)
from open_data_toolkit.project.fleet.step_common import (
    EIA860_GENERATORS_TABLE,
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    warn_on_fleet_data_gaps,
    add_shared_project_step_arguments,
)

POI_RULE_CHOICES = ("max_component", "sum")
BATTERY_MW_BASIS_CHOICES = ("nameplate", "discharge_rating")
# Relative difference between a hybrid battery's filed discharge rating
# and its nameplate above which the step warns (see the module docstring)
BATTERY_RATING_MISMATCH_TOLERANCE = 0.1

# The exact inputs_project_power_output_group(_requirement)s column sets,
# in order — the CSV-to-DB loader enforces both
PROJECTS_CSV_COLUMNS = ["power_output_group", "project"]
REQUIREMENTS_CSV_COLUMNS = [
    "power_output_group",
    "period",
    "power_output_group_total_power_min",
    "power_output_group_total_power_max",
]


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
        default="../../csvs_open_data/project/opchar/power_output_groups",
        help="The group CSVs are written to the 'projects' and "
        "'requirements' subdirectories of this directory.",
    )
    parser.add_argument(
        "-poi",
        "--hybrid_poi_rule",
        default="max_component",
        choices=list(POI_RULE_CHOICES),
        help="How each hybrid cluster's shared interconnection (POI) limit "
        "is derived — EIA-860 collects no POI capacity, so this is an "
        "assumption: 'max_component' (the default) = max(total variable "
        "AC nameplate, total battery MW); 'sum' = their non-binding sum "
        "(plumbing only, until real limits are edited in). The battery "
        "MW basis is hybrid_battery_mw_basis.",
    )
    parser.add_argument(
        "-batt_mw",
        "--hybrid_battery_mw_basis",
        default="nameplate",
        choices=list(BATTERY_MW_BASIS_CHOICES),
        help="The MW basis of each hybrid battery in the POI rule: "
        "'nameplate' (the default) = the fleet table's capacity_mw, the "
        "same basis as the capacity step's specified_capacity_mw, so the "
        "group limit and the member capacity agree by construction; "
        "'discharge_rating' = the EIA-860 energy-storage supplement's "
        "max_discharge_rate_mw where filed (nameplate otherwise) — an "
        "annual-only table pinned to an older vintage than the fleet "
        "table, whose ratings can lag a battery's build-out. Either way "
        "the step warns for batteries whose filed rating and nameplate "
        "differ by more than 10%%.",
    )
    parser.add_argument(
        "-grp_id", "--project_power_output_group_scenario_id", default=1
    )
    parser.add_argument(
        "-grp_name",
        "--project_power_output_group_scenario_name",
        default="hybrids",
    )
    parser.add_argument(
        "-req_id",
        "--project_power_output_group_requirement_scenario_id",
        default=1,
    )
    parser.add_argument(
        "-req_name",
        "--project_power_output_group_requirement_scenario_name",
        default="hybrid_poi_limits",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_hybrid_component_units(
    conn, project_name_str, fleet_relation_sql, geographic_token_str
):
    """
    The in-fleet hybrid components, one row per unit: plant, generator,
    prime mover, capacity, the battery's supplement discharge rating
    (NULL for variable units and unfiled batteries), the project the unit
    maps to under the aggregation settings, and its geographic name
    token.
    """
    pairing_expr = get_hybrid_pairing_expr(
        generators_table=EIA860_GENERATORS_TABLE,
        fleet_relation_sql=fleet_relation_sql,
    )
    sql = f"""
    SELECT plant_id_eia,
        generator_id,
        {EIA860_GENERATORS_TABLE}.prime_mover_code AS prime_mover_code,
        capacity_mw,
        (SELECT es.max_discharge_rate_mw
         FROM raw_data_eia860_energy_storage es
         WHERE es.plant_id_eia = {EIA860_GENERATORS_TABLE}.plant_id_eia
         AND es.generator_id = {EIA860_GENERATORS_TABLE}.generator_id
         LIMIT 1) AS max_discharge_rate_mw,
        {project_name_str} AS project,
        {geographic_token_str} AS geographic_token
    {fleet_relation_sql}
    AND ({pairing_expr}) IS NOT NULL
    ;
    """

    return pd.read_sql(sql, conn)


def get_support_link_edges(conn):
    """
    The batteries' direct-support links as (batt_plant, batt_gen,
    supported_plant, supported_gen) rows — the cross-plant clustering
    edges; callers restrict both ends to the hybrid components.
    """
    return pd.read_sql(f"SELECT * FROM ({get_support_links_sql()})", conn)


def cluster_hybrid_units(units_df, links_df):
    """
    Group the hybrid-component units into installations: units connected
    by plant co-location or by direct-support links (between in-fleet
    hybrid components) form one cluster — one shared interconnection.
    Returns the units dataframe with a ``cluster`` column holding each
    cluster's smallest plant id (ties broken by generator id).
    """
    unit_keys = list(zip(units_df["plant_id_eia"], units_df["generator_id"]))
    unit_set = set(unit_keys)
    parent = {key: key for key in unit_keys}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(key_1, key_2):
        root_1, root_2 = find(key_1), find(key_2)
        if root_1 != root_2:
            parent[max(root_1, root_2)] = min(root_1, root_2)

    # Co-location edges: all hybrid units at one plant share its POI
    for _plant, plant_units in units_df.groupby("plant_id_eia"):
        keys = list(zip(plant_units["plant_id_eia"], plant_units["generator_id"]))
        for key in keys[1:]:
            union(keys[0], key)

    # Direct-support edges (may cross plant ids)
    for row in links_df.itertuples():
        battery_key = (row.batt_plant, row.batt_gen)
        supported_key = (row.supported_plant, row.supported_gen)
        if battery_key in unit_set and supported_key in unit_set:
            union(battery_key, supported_key)

    units_df = units_df.copy()
    units_df["cluster"] = [find(key)[0] for key in unit_keys]

    return units_df


def get_battery_mw(units_df, hybrid_battery_mw_basis):
    """
    Each unit's battery-side MW under *hybrid_battery_mw_basis*:
    ``nameplate`` = the fleet table's ``capacity_mw``;
    ``discharge_rating`` = the supplement's ``max_discharge_rate_mw``
    where filed, nameplate otherwise. Returns a Series aligned with
    *units_df* (variable units included; callers mask them).
    """
    if hybrid_battery_mw_basis == "nameplate":
        return units_df["capacity_mw"]
    elif hybrid_battery_mw_basis == "discharge_rating":
        return units_df["max_discharge_rate_mw"].fillna(units_df["capacity_mw"])
    else:
        raise ValueError(
            f"Unknown hybrid_battery_mw_basis '{hybrid_battery_mw_basis}'; "
            f"choose from {BATTERY_MW_BASIS_CHOICES}."
        )


def warn_on_battery_rating_nameplate_mismatch(
    units_df, tolerance=BATTERY_RATING_MISMATCH_TOLERANCE
):
    """
    Warn — loudly, regardless of any quiet setting — for every hybrid
    battery whose filed supplement discharge rating differs from its
    fleet-table nameplate by more than *tolerance* (relative to
    nameplate), listing plant, generator, both values and the ratio.
    The two come from different EIA-860 vintages (see the module
    docstring): a large gap means a stale supplement row (partial build
    stage), a filing error, or a genuinely derated battery — under the
    ``nameplate`` basis the limit ignores the rating, under
    ``discharge_rating`` it uses it, and either way the row deserves a
    look. Returns the offending rows (empty when none).
    """
    is_battery = units_df["prime_mover_code"].isin(HYBRID_STORAGE_PRIME_MOVERS)
    filed = units_df["max_discharge_rate_mw"].notna()
    nameplate = units_df["capacity_mw"]
    relative_gap = (units_df["max_discharge_rate_mw"] - nameplate).abs() / nameplate
    mismatched = units_df.loc[
        is_battery & filed & (nameplate > 0) & (relative_gap > tolerance),
        ["plant_id_eia", "generator_id", "capacity_mw", "max_discharge_rate_mw"],
    ].copy()

    if not mismatched.empty:
        mismatched["nameplate_to_rating_ratio"] = (
            mismatched["capacity_mw"] / mismatched["max_discharge_rate_mw"]
        )
        mismatched = mismatched.sort_values(
            "nameplate_to_rating_ratio", ascending=False
        ).reset_index(drop=True)
        print(
            f"WARNING: {len(mismatched)} hybrid batter"
            f"{'y has' if len(mismatched) == 1 else 'ies have'} a filed EIA-860 "
            f"energy-storage-supplement discharge rating "
            f"(max_discharge_rate_mw) differing from the fleet table's "
            f"nameplate (capacity_mw) by more than {tolerance:.0%}. The two "
            f"come from different EIA-860 vintages (the supplement is "
            f"annual-only and typically older); a large gap usually means "
            f"the supplement describes an earlier build stage or a filing "
            f"error. The hybrid_battery_mw_basis setting decides which "
            f"number the POI limit uses ('nameplate', the default, matches "
            f"the capacity step). Review these units:\n"
            + mismatched.to_string(index=False)
        )

    return mismatched


def get_cluster_poi_limits(units_df, hybrid_poi_rule, hybrid_battery_mw_basis):
    """
    Each cluster's POI limit under *hybrid_poi_rule* (see the module
    docstring): per cluster, the variable side sums AC nameplate and the
    storage side sums each battery's MW under *hybrid_battery_mw_basis*
    (``nameplate``, or the supplement's ``discharge_rating`` with a
    nameplate fallback where unfiled). Returns a dataframe indexed by
    cluster with ``poi_limit_mw``.
    """
    units_df = units_df.copy()
    is_battery = units_df["prime_mover_code"].isin(HYBRID_STORAGE_PRIME_MOVERS)
    units_df["variable_mw"] = units_df["capacity_mw"].where(~is_battery, 0)
    units_df["battery_mw"] = get_battery_mw(
        units_df=units_df, hybrid_battery_mw_basis=hybrid_battery_mw_basis
    ).where(is_battery, 0)

    sides = units_df.groupby("cluster")[["variable_mw", "battery_mw"]].sum()
    if hybrid_poi_rule == "max_component":
        sides["poi_limit_mw"] = sides.max(axis=1)
    else:
        sides["poi_limit_mw"] = sides.sum(axis=1)

    return sides[["poi_limit_mw"]]


def build_group_dfs(
    units_df,
    links_df,
    hybrid_poi_rule,
    hybrid_battery_mw_basis,
    aggregate_projects,
    period,
):
    """
    The two output dataframes (group membership; group-period
    requirements) from the hybrid-component units. Disaggregated mode:
    one group per cluster (``hybrid_<smallest plant id>``); aggregated
    modes: the clusters in each geographic name token merge into
    ``hybrid_<token>`` with the SUM of their POI limits. The minimum is
    written as an explicit 0 — with GridPath's non-negative minimum
    domain, the group can never be a net load either way.
    """
    units_df = cluster_hybrid_units(units_df=units_df, links_df=links_df)
    poi_limits = get_cluster_poi_limits(
        units_df=units_df,
        hybrid_poi_rule=hybrid_poi_rule,
        hybrid_battery_mw_basis=hybrid_battery_mw_basis,
    )

    if aggregate_projects:
        # A cluster's units can in principle straddle geographic tokens
        # (a cross-plant support link across BAs); its POI then counts
        # toward each unit's own token — the relaxation is already
        # per-token, so no warning is needed, but keep sums per unit-token
        units_df["cluster_poi_mw"] = units_df["cluster"].map(poi_limits["poi_limit_mw"])
        cluster_tokens = units_df.groupby(["cluster", "geographic_token"]).agg(
            cluster_poi_mw=("cluster_poi_mw", "first")
        )
        n_straddling = cluster_tokens.groupby("cluster").size().gt(1).sum()
        if n_straddling:
            print(
                f"WARNING: {n_straddling} hybrid cluster(s) straddle "
                f"geographic name tokens (cross-plant support links across "
                f"zones); each such cluster's POI limit is counted toward "
                f"EVERY token it touches — correct the generated "
                f"requirements CSV if this matters."
            )
        units_df["power_output_group"] = "hybrid_" + units_df[
            "geographic_token"
        ].astype(str)
        requirements = (
            cluster_tokens.reset_index()
            .groupby("geographic_token")["cluster_poi_mw"]
            .sum()
            .reset_index()
        )
        requirements["power_output_group"] = "hybrid_" + requirements[
            "geographic_token"
        ].astype(str)
        requirements = requirements.rename(
            columns={"cluster_poi_mw": "power_output_group_total_power_max"}
        )
    else:
        units_df["power_output_group"] = "hybrid_" + units_df["cluster"].astype(str)
        requirements = poi_limits.reset_index()
        requirements["power_output_group"] = "hybrid_" + requirements["cluster"].astype(
            str
        )
        requirements = requirements.rename(
            columns={"poi_limit_mw": "power_output_group_total_power_max"}
        )

    projects_df = (
        units_df[["power_output_group", "project"]]
        .drop_duplicates()
        .sort_values(["power_output_group", "project"])
        .reset_index(drop=True)
    )

    requirements["period"] = period
    requirements["power_output_group_total_power_min"] = 0
    requirements_df = (
        requirements[REQUIREMENTS_CSV_COLUMNS]
        .sort_values("power_output_group")
        .reset_index(drop=True)
    )

    return projects_df, requirements_df


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if parsed_args.hybrid_treatment != "power_output_group":
        raise ValueError(
            f"This step implements the 'power_output_group' hybrid "
            f"treatment, but hybrid_treatment is "
            f"'{parsed_args.hybrid_treatment}' — set hybrid_treatment "
            f"power_output_group (consistently across the project-level "
            f"steps: the opchar step must flip paired must-take variable "
            f"components to gen_var, or the group limits can be "
            f"infeasible), or drop this step from the run."
        )

    if not parsed_args.quiet:
        print("Creating hybrid power output group inputs")

    projects_directory = os.path.join(parsed_args.output_directory, "projects")
    requirements_directory = os.path.join(parsed_args.output_directory, "requirements")
    os.makedirs(projects_directory, exist_ok=True)
    os.makedirs(requirements_directory, exist_ok=True)

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)
    geographic_token_str = get_geographic_token_str(
        load_zone_level=parsed_args.load_zone_level,
        footprint=parsed_args.footprint,
        aggregation_level=parsed_args.aggregation_level,
    )

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    units_df = get_hybrid_component_units(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        geographic_token_str=geographic_token_str,
    )
    links_df = get_support_link_edges(conn=conn)
    conn.close()

    if units_df.empty:
        # No paired hybrid components in this fleet: write header-only
        # CSVs so downstream porting still finds the expected files
        print(
            "WARNING: no paired hybrid components in this fleet — writing "
            "header-only power output group CSVs."
        )
        projects_df = pd.DataFrame(columns=PROJECTS_CSV_COLUMNS)
        requirements_df = pd.DataFrame(columns=REQUIREMENTS_CSV_COLUMNS)
    else:
        warn_on_battery_rating_nameplate_mismatch(units_df=units_df)
        projects_df, requirements_df = build_group_dfs(
            units_df=units_df,
            links_df=links_df,
            hybrid_poi_rule=parsed_args.hybrid_poi_rule,
            hybrid_battery_mw_basis=parsed_args.hybrid_battery_mw_basis,
            aggregate_projects=parsed_args.project_aggregation != "none",
            period=parsed_args.study_year,
        )

    projects_df.to_csv(
        os.path.join(
            projects_directory,
            f"{parsed_args.project_power_output_group_scenario_id}_"
            f"{parsed_args.project_power_output_group_scenario_name}.csv",
        ),
        index=False,
    )
    requirements_df.to_csv(
        os.path.join(
            requirements_directory,
            f"{parsed_args.project_power_output_group_requirement_scenario_id}_"
            f"{parsed_args.project_power_output_group_requirement_scenario_name}"
            f".csv",
        ),
        index=False,
    )


if __name__ == "__main__":
    main()
