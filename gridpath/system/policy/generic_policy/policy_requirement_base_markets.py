# Copyright 2026 Sylvan Energy Analytics LLC
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
Market transactions in the *base* of a generic policy requirement: the energy
a (load zone, market) pair buys or sells over the requirement's horizon,
added to the base projects' output or capacity (see
:code:`gridpath.system.policy.generic_policy.policy_requirement_base`), e.g.
so that an emissions intensity standard applies to own generation plus
purchases. Each row has a *base type*:

* ``net_purchases``: the pair's final net purchases (negative when selling);
* ``purchases``: its gross purchases;
* ``sales``: its gross sales.

``net_purchases`` is linear in the market position and can be used in any
requirement. The gross types are not: the model only has the net position,
and a gross quantity can only be bounded from below by its positive part.
Where a larger base relaxes the requirement, as in an emissions intensity
cap, the solver could inflate such a quantity for free. The gross types
therefore reuse the variable that counts the pair's purchases toward the
same policy zone's import emissions
(:code:`gridpath.system.markets.policy_import_emissions`): gross purchases
are the pair's counted import emissions divided by its import intensity, and
gross sales are those purchases less the net position. Inflating the
variable then adds emissions at the import intensity :math:`I` while it
raises the requirement by the base coefficient :math:`c` times the sum
:math:`M` of the pair's ``purchases`` and ``sales`` multipliers, so it
never pays off as long as :math:`I \\geq c \\cdot M` in every timepoint of
every requirement horizon. Gross types hence require:

* that the pair counts its import emissions toward the same policy zone
  (the ``import_emissions`` compliance type in the market policy zones),
  which in turn requires the zone's requirements to be ``max``
  requirements;
* that the zone has the ``gross`` import-emissions basis: under ``net_prd``,
  the zone's net import emissions are floored at zero, and below the floor
  the emissions variable costs nothing;
* a positive import intensity, at least the base coefficient times
  :math:`M`, in every timepoint.

Validation checks all three, and the model refuses to build without them.
"""

import csv
import os.path

from pyomo.environ import Expression, Param, Reals, Set, value

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.auxiliary.dynamic_components import policy_balance_base_components
from gridpath.auxiliary.validations import write_validation_to_database
from gridpath.common_functions import create_results_df
from gridpath.system.markets.carbon_emissions_common import (
    import_intensity,
    lz_market_zones_sql,
    names,
)
from gridpath.system.policy.generic_policy.generic_policy_requirements import MAX
from gridpath.system.policy.import_emissions import POLICY, get_basis_by_zone, GROSS

NET_PURCHASES_BASE = "net_purchases"
PURCHASES_BASE = "purchases"
SALES_BASE = "sales"
GROSS_BASE_TYPES = [PURCHASES_BASE, SALES_BASE]
BASE_TYPES = [NET_PURCHASES_BASE] + GROSS_BASE_TYPES


def add_model_components(
    m,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    The following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`POLICY_ZONE_BASE_LZ_MARKETS`                                   |
    |                                                                         |
    | Five-dimensional set of the (load zone, market) pairs whose             |
    | transactions a policy zone's requirements scale with, and the base type |
    | (``net_purchases``, ``purchases`` or ``sales``) of each: (policy, zone, |
    | load zone, market, base type).                                          |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`policy_market_base_multiplier`                                 |
    | | *Defined over*: :code:`POLICY_ZONE_BASE_LZ_MARKETS`                   |
    | | *Within*: :code:`Reals`                                               |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The weight of the pair's base quantity in the policy zone's base.       |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Total_Market_Policy_Zone_Base`                                 |
    | | *Defined over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`          |
    |                                                                         |
    | The weighted energy the base pairs buy, sell or buy net over the        |
    | horizon. Added to the policy requirement's base components.             |
    +-------------------------------------------------------------------------+
    """

    m.POLICY_ZONE_BASE_LZ_MARKETS = Set(dimen=5)

    m.policy_market_base_multiplier = Param(
        m.POLICY_ZONE_BASE_LZ_MARKETS, within=Reals, default=1
    )

    def total_base_rule(mod, policy, zone, bt, h):
        """
        The base pairs' weighted energy over the horizon
        """
        rows = base_rows_by_policy_zone(mod).get((policy, zone), [])
        if not rows:
            return 0
        check_gross_rows_exact(mod, policy, zone, bt, h)
        return sum(
            mod.policy_market_base_multiplier[policy, zone, lz, mrkt, base_type]
            * base_mw(mod, policy, zone, lz, mrkt, base_type, tmp)
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (lz, mrkt, base_type) in rows
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
        )

    m.Total_Market_Policy_Zone_Base = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, rule=total_base_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add the market transactions to the policy requirement's base.
    """
    getattr(dynamic_components, policy_balance_base_components).append(
        "Total_Market_Policy_Zone_Base"
    )


# Per-index helpers
###############################################################################


def base_rows_by_policy_zone(mod):
    """
    The (load zone, market, base type) rows of each policy zone, built in one
    pass and cached on the model instance.
    """
    cache = getattr(mod, "_gridpath_policy_market_base_rows", None)
    if cache is None:
        cache = {}
        for policy, zone, lz, mrkt, base_type in mod.POLICY_ZONE_BASE_LZ_MARKETS:
            cache.setdefault((policy, zone), []).append((lz, mrkt, base_type))
        mod._gridpath_policy_market_base_rows = cache
    return cache


def gross_purchases_mw(mod, policy, zone, lz, mrkt, tmp):
    """
    The pair's purchases as counted toward the zone's import emissions: the
    emissions variable divided by the import intensity.
    """
    z = (policy, zone)
    return getattr(mod, names(POLICY).import_emissions_var)[
        lz, mrkt, policy, zone, tmp
    ] / import_intensity(mod, POLICY, lz, mrkt, z, tmp)


def base_mw(mod, policy, zone, lz, mrkt, base_type, tmp):
    """
    The pair's base quantity in the timepoint, in MW.
    """
    net = mod.Final_Net_Market_Purchased_Power[lz, mrkt, tmp]
    if base_type == NET_PURCHASES_BASE:
        return net
    purchases = gross_purchases_mw(mod, policy, zone, lz, mrkt, tmp)
    if base_type == PURCHASES_BASE:
        return purchases
    return purchases - net


def realized_base_mw(mod, lz, mrkt, base_type, tmp):
    """
    The pair's base quantity in the timepoint recomputed from the solved net
    position.
    """
    net = value(mod.Final_Net_Market_Purchased_Power[lz, mrkt, tmp])
    if base_type == NET_PURCHASES_BASE:
        return net
    if base_type == PURCHASES_BASE:
        return max(net, 0)
    return max(-net, 0)


def check_gross_rows_exact(mod, policy, zone, bt, h):
    """
    Raise if a gross-type row of the policy zone could be inflated to relax
    the requirement (bt, h); see the module docstring.
    """
    gross_multipliers = {}
    for lz, mrkt, base_type in base_rows_by_policy_zone(mod)[policy, zone]:
        if base_type in GROSS_BASE_TYPES:
            gross_multipliers[lz, mrkt] = (
                gross_multipliers.get((lz, mrkt), 0)
                + mod.policy_market_base_multiplier[policy, zone, lz, mrkt, base_type]
            )
    if not gross_multipliers:
        return

    if mod.policy_requirement_sense[policy, zone, bt, h] != MAX:
        raise ValueError(
            f"Policy {policy} zone {zone}: market purchases and sales can only "
            f"be in the base of 'max' requirements; horizon {bt} {h} is not."
        )
    gross_set = getattr(mod, names(POLICY).gross_lz_market_zone_tmps)
    coeff = mod.policy_requirement_f_base_coeff[policy, zone, bt, h]
    for (lz, mrkt), multiplier in gross_multipliers.items():
        for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]:
            if (lz, mrkt, policy, zone, tmp) not in gross_set:
                raise ValueError(
                    f"Policy {policy} zone {zone}: market purchases and sales of "
                    f"{lz}-{mrkt} in the base require the pair to count its "
                    f"import emissions toward the zone, with the 'gross' basis."
                )
            intensity = import_intensity(mod, POLICY, lz, mrkt, (policy, zone), tmp)
            if intensity <= 0 or intensity < coeff * multiplier:
                raise ValueError(
                    f"Policy {policy} zone {zone}: the import intensity of "
                    f"{lz}-{mrkt} in timepoint {tmp} ({intensity}) must be "
                    f"positive and at least the base coefficient times the "
                    f"pair's purchases and sales multipliers ({coeff} x "
                    f"{multiplier}) for the base to be exact."
                )


# Input-Output
###############################################################################


def load_model_data(
    m,
    d,
    data_portal,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    The base markets file is only written when there are any; without it,
    the base set is empty.
    """
    base_markets_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "policy_requirement_base_markets.tab",
    )
    if os.path.exists(base_markets_file):
        data_portal.load(
            filename=base_markets_file,
            index=m.POLICY_ZONE_BASE_LZ_MARKETS,
            param=m.policy_market_base_multiplier,
        )
    else:
        data_portal.data()["POLICY_ZONE_BASE_LZ_MARKETS"] = {None: []}


def export_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    m,
    d,
):
    """
    Each base pair's base quantity in each of the policy zone's requirement
    horizons in MWh, as the model counted it and recomputed from the solved
    net position, before and after the pair's multiplier.
    """
    if not m.POLICY_ZONE_BASE_LZ_MARKETS:
        return

    data = []
    for policy, zone, bt, h in m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ:
        for lz, mrkt, base_type in base_rows_by_policy_zone(m).get((policy, zone), []):
            base = 0
            realized_base = 0
            for tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, h]:
                energy_weight = m.hrs_in_tmp[tmp] * m.tmp_weight[tmp]
                base += (
                    value(base_mw(m, policy, zone, lz, mrkt, base_type, tmp))
                    * energy_weight
                )
                realized_base += (
                    realized_base_mw(m, lz, mrkt, base_type, tmp) * energy_weight
                )
            multiplier = m.policy_market_base_multiplier[
                policy, zone, lz, mrkt, base_type
            ]
            data.append(
                [policy, zone, bt, h, lz, mrkt, base_type]
                + [multiplier, base, realized_base, multiplier * base]
            )

    results_df = create_results_df(
        index_columns=[
            "policy_name",
            "policy_zone",
            "balancing_type_horizon",
            "horizon",
            "load_zone",
            "market",
            "base_type",
        ],
        results_columns=[
            "base_multiplier",
            "base_in_hrz",
            "base_in_hrz_degen",
            "weighted_base_in_hrz",
        ],
        data=data,
    )
    results_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "market_policy_requirement_base.csv",
        ),
        sep=",",
        index=True,
    )


# Database
###############################################################################


def base_markets_sql(subscenarios):
    """
    The base markets of the requirement subscenario, for the scenario's
    (load zone, market) pairs and the policy zones in the policy zone
    subscenario.
    """
    return f"""
        SELECT policy_name, policy_zone, load_zone, market, base_type,
            base_multiplier
        FROM inputs_system_policy_requirements_base_markets
        WHERE policy_requirement_scenario_id =
            {subscenarios.POLICY_REQUIREMENT_SCENARIO_ID}
        AND (load_zone, market) IN (
            SELECT load_zone, market
            FROM inputs_load_zone_markets
            WHERE load_zone_market_scenario_id =
                {subscenarios.LOAD_ZONE_MARKET_SCENARIO_ID}
            AND load_zone IN (
                SELECT load_zone
                FROM inputs_geography_load_zones
                WHERE load_zone_scenario_id = {subscenarios.LOAD_ZONE_SCENARIO_ID}
            )
            AND market IN (
                SELECT market
                FROM inputs_geography_markets
                WHERE market_scenario_id = {subscenarios.MARKET_SCENARIO_ID}
            )
        )
        AND (policy_name, policy_zone) IN (
            SELECT policy_name, policy_zone
            FROM inputs_geography_policy_zones
            WHERE policy_zone_scenario_id = {subscenarios.POLICY_ZONE_SCENARIO_ID}
        )
        """


def get_inputs_from_database(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
):
    """
    The base markets of the requirement subscenario.
    """
    c = conn.cursor()
    return c.execute(base_markets_sql(subscenarios))


def validate_inputs(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
):
    """
    The base type must be one of the supported types, and the gross types
    must be exact (see the module docstring).
    """
    c = conn.cursor()
    df = cursor_to_df(c.execute(base_markets_sql(subscenarios)))
    if df.empty:
        return

    invalid = df[~df["base_type"].isin(BASE_TYPES)]
    errors = [
        f"{row['policy_name']}-{row['policy_zone']}-{row['load_zone']}-"
        f"{row['market']}: invalid base_type '{row['base_type']}'; valid types "
        f"are {BASE_TYPES}."
        for _, row in invalid.iterrows()
    ]
    errors += validate_gross_rows(c, subscenarios, subproblem, stage, df)

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_system_policy_requirements_base_markets",
        severity="High",
        errors=errors,
    )


def validate_gross_rows(c, subscenarios, subproblem, stage, df):
    """
    Error messages for gross-type rows whose pair does not count its import
    emissions toward the zone, whose zone does not have the gross basis, or
    whose import intensity is not positive or is below the base coefficient
    times the pair's gross multipliers in a timepoint of a requirement
    horizon.
    """
    pair_zone_cols = ["policy_name", "policy_zone", "load_zone", "market"]
    gross = df[df["base_type"].isin(GROSS_BASE_TYPES)].copy()
    if gross.empty:
        return []
    gross["base_multiplier"] = gross["base_multiplier"].fillna(1).astype(float)
    gross = gross.groupby(pair_zone_cols, as_index=False)["base_multiplier"].sum()

    def label(row):
        return "-".join(str(row[col]) for col in pair_zone_cols)

    errors = []
    basis_by_zone = get_basis_by_zone(c, subscenarios, POLICY)
    net_zone = gross.apply(
        lambda row: basis_by_zone.get((row["policy_name"], row["policy_zone"]))
        != GROSS,
        axis=1,
    )
    for _, row in gross[net_zone].iterrows():
        errors.append(
            f"{label(row)}: market purchases and sales can only be in the base "
            f"of a zone with the 'gross' import-emissions basis."
        )

    mapping_sql = lz_market_zones_sql(subscenarios, POLICY)
    mappings = cursor_to_df(c.execute(f"""
            SELECT DISTINCT policy_name, policy_zone, load_zone, market
            FROM ({mapping_sql})
            """))
    merged = gross.merge(mappings, on=pair_zone_cols, how="left", indicator=True)
    for _, row in merged[merged["_merge"] == "left_only"].iterrows():
        errors.append(
            f"{label(row)}: market purchases and sales in the base require the "
            f"pair to count its import emissions toward the policy zone (the "
            f"'import_emissions' compliance type in the market policy zones)."
        )

    # The pairs' import intensities (flat plus timepoint adder) and the base
    # coefficient in every timepoint of every requirement horizon
    intensities = cursor_to_df(c.execute(f"""
            SELECT mappings.policy_name, mappings.policy_zone,
                mappings.load_zone, mappings.market, req_tmps.timepoint,
                req_tmps.base_coeff,
                COALESCE(mappings.co2_intensity_tons_per_mwh, 0)
                + COALESCE(adders.co2_intensity_tons_per_mwh_hourly, 0)
                    AS intensity
            FROM ({mapping_sql}) AS mappings
            JOIN (
                SELECT policy_name, policy_zone, timepoint,
                    COALESCE(policy_requirement_f_base_coeff, 0) AS base_coeff
                FROM inputs_system_policy_requirements
                JOIN inputs_temporal_horizon_timepoints
                USING (balancing_type_horizon, horizon, subproblem_id, stage_id)
                WHERE policy_requirement_scenario_id =
                    {subscenarios.POLICY_REQUIREMENT_SCENARIO_ID}
                AND temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
            ) AS req_tmps
            USING (policy_name, policy_zone)
            LEFT JOIN {names(POLICY).timepoint_emissions_table} AS adders
            ON adders.market = mappings.market
            AND adders.tmp_import_emissions_scenario_id =
                mappings.tmp_import_emissions_scenario_id
            AND adders.timepoint = req_tmps.timepoint
            """))
    if intensities.empty:
        return errors
    checks = gross.merge(intensities, on=pair_zone_cols)
    bad = checks[
        (checks["intensity"] <= 0)
        | (checks["intensity"] < checks["base_coeff"] * checks["base_multiplier"])
    ]
    for key, group in bad.groupby(pair_zone_cols):
        errors.append(
            f"{'-'.join(str(k) for k in key)}: the import intensity must be "
            f"positive and at least the base coefficient times the pair's "
            f"purchases and sales multipliers in every timepoint of the "
            f"requirement horizons for the base to be exact; it is not in "
            f"timepoint(s) {sorted(group['timepoint'].unique().tolist())}."
        )

    return errors


def write_model_inputs(
    scenario_directory,
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
):
    """
    Write the base markets to policy_requirement_base_markets.tab, only if
    there are any.
    """
    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )
    base_markets = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    ).fetchall()

    if not base_markets:
        return

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "policy_requirement_base_markets.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "policy_name",
                "policy_zone",
                "load_zone",
                "market",
                "base_type",
                "base_multiplier",
            ]
        )
        for row in base_markets:
            writer.writerow(["." if i is None else i for i in row])


def import_results_into_database(
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    c,
    db,
    results_directory,
    quiet,
):
    """
    Import the base markets' results, if any.
    """
    if not os.path.exists(
        os.path.join(results_directory, "market_policy_requirement_base.csv")
    ):
        return

    import_csv(
        conn=db,
        cursor=c,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        quiet=quiet,
        results_directory=results_directory,
        which_results="market_policy_requirement_base",
    )
