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
Emissions of market purchases, shared by the carbon cap and carbon tax
modules (:code:`system.markets.carbon_emissions` and
:code:`system.markets.carbon_tax_emissions`). See
:code:`gridpath.system.policy.import_emissions` for the accounting.

A (load zone, market) pair is assigned to a zone with an import intensity for
its purchases and an export intensity for its sales, each a flat value per
zone row plus an optional timepoint-varying adder per market. The same market
may count toward different zones depending on which load zone trades at it,
and a pair may count toward several zones. Positions are the *final*
positions, including the transactions carried over from previous stages, as
in the load balance.
"""

import csv
import os.path
from types import SimpleNamespace

from pyomo.environ import Constraint, NonNegativeReals, Param, Set, Var, value

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.auxiliary.validations import write_validation_to_database
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)
from gridpath.system.policy.import_emissions import (
    ImportEmissionsSource,
    is_net_zone,
    validate_export_intensities,
    validate_single_profile_per_entity,
)

_NAMES = {}


def names(policy):
    """
    The component names for a policy's market import emissions (built once
    per policy; the per-index expression helpers call this).
    """
    if policy.name in _NAMES:
        return _NAMES[policy.name]
    P, p, Pc = policy.set_prefix, policy.name, policy.component_prefix
    _NAMES[policy.name] = SimpleNamespace(
        lz_market_zones=f"{P}_LZ_MARKET_ZONES",
        markets=f"{P}_MARKETS",
        market_tmps=f"{P}_MARKET_TMPS",
        lz_market_zone_tmps=f"{P}_LZ_MARKET_ZONE_TMPS",
        gross_lz_market_zone_tmps=f"GROSS_{P}_LZ_MARKET_ZONE_TMPS",
        net_lz_market_zone_tmps=f"NET_{P}_LZ_MARKET_ZONE_TMPS",
        import_intensity=f"market_{p}_co2_intensity_tons_per_mwh",
        export_intensity=f"market_{p}_export_co2_intensity_tons_per_mwh",
        import_intensity_hourly=f"market_{p}_co2_intensity_tons_per_mwh_hourly",
        export_intensity_hourly=f"market_{p}_export_co2_intensity_tons_per_mwh_hourly",
        import_emissions_var=f"Market_{Pc}_Import_Emissions_Tons",
        import_emissions_constraint=f"Market_{Pc}_Import_Emissions_Constraint",
        import_mw_var=f"Market_{Pc}_Import_MW",
        import_mw_constraint=f"Market_{Pc}_Import_MW_Constraint",
        zones_file=f"market_{p}_zones.tab",
        timepoint_emissions_file=f"market_{p}_timepoint_emissions.tab",
        results=f"system_market_{p}_imports",
        zones_table=f"inputs_market_{p}_zones",
        timepoint_emissions_table=f"inputs_market_{p}_timepoint_emissions",
        subscenario_attr=f"MARKET_{P}_ZONE_SCENARIO_ID",
    )
    return _NAMES[policy.name]


def generic_add_model_components(m, d, policy):
    """
    The following Pyomo model components are defined in this function, with
    ``<P>`` the policy (``CARBON_CAP`` / ``CARBON_TAX``), ``<p>`` its lower
    case (``carbon_cap`` / ``carbon_tax``) and ``<Pc>`` its capitalized form
    (``Carbon_Cap`` / ``Carbon_Tax``):

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`<P>_LZ_MARKET_ZONES`                                           |
    |                                                                         |
    | Three-dimensional set of the (load zone, market) pairs whose purchases  |
    | or sales count toward a zone and that zone.                             |
    +-------------------------------------------------------------------------+
    | | :code:`<P>_MARKETS`                                                   |
    |                                                                         |
    | The markets of any assigned pair.                                       |
    +-------------------------------------------------------------------------+
    | | :code:`<P>_MARKET_TMPS`                                               |
    |                                                                         |
    | Those markets by timepoint, the index of the timepoint-varying          |
    | intensity adders.                                                       |
    +-------------------------------------------------------------------------+
    | | :code:`<P>_LZ_MARKET_ZONE_TMPS`                                       |
    |                                                                         |
    | Four-dimensional set of load zone, market, zone and timepoint; split    |
    | into :code:`GROSS_<P>_LZ_MARKET_ZONE_TMPS` and                          |
    | :code:`NET_<P>_LZ_MARKET_ZONE_TMPS` by the zone's import-emissions      |
    | basis.                                                                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`market_<p>_co2_intensity_tons_per_mwh`                         |
    | | *Defined over*: :code:`<P>_LZ_MARKET_ZONES`                           |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The emissions intensity of purchases in metric tonnes per MWh.          |
    +-------------------------------------------------------------------------+
    | | :code:`market_<p>_export_co2_intensity_tons_per_mwh`                  |
    | | *Defined over*: :code:`<P>_LZ_MARKET_ZONES`                           |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The credit per MWh sold, in metric tonnes; applies only in zones with   |
    | the ``net_prd`` basis and may not exceed the import intensity.          |
    +-------------------------------------------------------------------------+
    | | :code:`market_<p>_co2_intensity_tons_per_mwh_hourly`                  |
    | | :code:`market_<p>_export_co2_intensity_tons_per_mwh_hourly`           |
    | | *Defined over*: :code:`<P>_MARKET_TMPS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Timepoint-varying adders to the market's flat intensities in every      |
    | zone row of the market.                                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Market_<Pc>_Import_Emissions_Tons`                             |
    | | *Defined over*: :code:`GROSS_<P>_LZ_MARKET_ZONE_TMPS`                 |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The emissions of the pair's purchases counted toward a gross-basis      |
    | zone.                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`Market_<Pc>_Import_MW`                                         |
    | | *Defined over*: :code:`NET_<P>_LZ_MARKET_ZONE_TMPS`                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The pair's purchases counted toward a net-basis zone.                   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Market_<Pc>_Import_Emissions_Constraint`                       |
    | | *Enforced over*: :code:`GROSS_<P>_LZ_MARKET_ZONE_TMPS`                |
    |                                                                         |
    | Import emissions are at least the final net purchased power times the   |
    | import intensity.                                                       |
    +-------------------------------------------------------------------------+
    | | :code:`Market_<Pc>_Import_MW_Constraint`                              |
    | | *Enforced over*: :code:`NET_<P>_LZ_MARKET_ZONE_TMPS`                  |
    |                                                                         |
    | Imported power is at least the final net purchased power.               |
    +-------------------------------------------------------------------------+

    Both variables can exceed the actual purchases where nothing pushes them
    down (a non-binding cap, a zero tax); the results also report the values
    recomputed from the solved positions.
    """
    n = names(policy)
    zones = getattr(m, policy.zones_set)

    # Sets
    ###########################################################################

    setattr(m, n.lz_market_zones, Set(dimen=3, within=m.LZ_MARKETS * zones))

    setattr(
        m,
        n.markets,
        Set(
            within=m.MARKETS,
            initialize=lambda mod: sorted(
                set(mrkt for (lz, mrkt, z) in getattr(mod, n.lz_market_zones))
            ),
        ),
    )

    setattr(
        m,
        n.market_tmps,
        Set(
            dimen=2,
            initialize=lambda mod: [
                (mrkt, tmp) for mrkt in getattr(mod, n.markets) for tmp in mod.TMPS
            ],
        ),
    )

    setattr(
        m,
        n.lz_market_zone_tmps,
        Set(
            dimen=4,
            initialize=lambda mod: [
                (lz, mrkt, z, tmp)
                for (lz, mrkt, z) in getattr(mod, n.lz_market_zones)
                for tmp in mod.TMPS
            ],
        ),
    )

    setattr(
        m,
        n.gross_lz_market_zone_tmps,
        Set(
            dimen=4,
            initialize=lambda mod: [
                (lz, mrkt, z, tmp)
                for (lz, mrkt, z, tmp) in getattr(mod, n.lz_market_zone_tmps)
                if not is_net_zone(mod, policy, z)
            ],
        ),
    )

    setattr(
        m,
        n.net_lz_market_zone_tmps,
        Set(
            dimen=4,
            initialize=lambda mod: [
                (lz, mrkt, z, tmp)
                for (lz, mrkt, z, tmp) in getattr(mod, n.lz_market_zone_tmps)
                if is_net_zone(mod, policy, z)
            ],
        ),
    )

    # Params
    ###########################################################################

    for param in [n.import_intensity, n.export_intensity]:
        setattr(
            m,
            param,
            Param(getattr(m, n.lz_market_zones), within=NonNegativeReals, default=0),
        )

    for param in [n.import_intensity_hourly, n.export_intensity_hourly]:
        setattr(
            m,
            param,
            Param(getattr(m, n.market_tmps), within=NonNegativeReals, default=0),
        )

    # Variables and constraints
    ###########################################################################

    setattr(
        m,
        n.import_emissions_var,
        Var(getattr(m, n.gross_lz_market_zone_tmps), within=NonNegativeReals),
    )

    def import_emissions_rule(mod, lz, mrkt, z, tmp):
        return getattr(mod, n.import_emissions_var)[
            lz, mrkt, z, tmp
        ] >= purchased_power(mod, lz, mrkt, tmp) * import_intensity(
            mod, policy, lz, mrkt, z, tmp
        )

    setattr(
        m,
        n.import_emissions_constraint,
        Constraint(getattr(m, n.gross_lz_market_zone_tmps), rule=import_emissions_rule),
    )

    setattr(
        m,
        n.import_mw_var,
        Var(getattr(m, n.net_lz_market_zone_tmps), within=NonNegativeReals),
    )

    def import_mw_rule(mod, lz, mrkt, z, tmp):
        return getattr(mod, n.import_mw_var)[lz, mrkt, z, tmp] >= purchased_power(
            mod, lz, mrkt, tmp
        )

    setattr(
        m,
        n.import_mw_constraint,
        Constraint(getattr(m, n.net_lz_market_zone_tmps), rule=import_mw_rule),
    )


# Per-index expressions
###############################################################################


def purchased_power(mod, lz, mrkt, tmp):
    """
    The pair's final net purchased power (negative when selling).
    """
    return mod.Final_Net_Market_Purchased_Power[lz, mrkt, tmp]


def import_intensity(mod, policy, lz, mrkt, z, tmp):
    n = names(policy)
    return (
        getattr(mod, n.import_intensity)[lz, mrkt, z]
        + getattr(mod, n.import_intensity_hourly)[mrkt, tmp]
    )


def export_intensity(mod, policy, lz, mrkt, z, tmp):
    n = names(policy)
    return (
        getattr(mod, n.export_intensity)[lz, mrkt, z]
        + getattr(mod, n.export_intensity_hourly)[mrkt, tmp]
    )


def import_emissions_tons(mod, policy, idx):
    """
    The emissions of the pair's purchases in the timepoint as the model
    counts them: the emissions variable in a gross zone, imported MW times
    the import intensity in a net zone.
    """
    lz, mrkt, z, tmp = idx
    n = names(policy)
    if is_net_zone(mod, policy, z):
        return getattr(mod, n.import_mw_var)[lz, mrkt, z, tmp] * import_intensity(
            mod, policy, lz, mrkt, z, tmp
        )
    else:
        return getattr(mod, n.import_emissions_var)[lz, mrkt, z, tmp]


def signed_import_emissions_tons(mod, policy, idx):
    """
    Purchases at the import intensity less sales at the export intensity,
    for a net zone; see :code:`gridpath.system.policy.import_emissions`.
    """
    lz, mrkt, z, tmp = idx
    i_exp = export_intensity(mod, policy, lz, mrkt, z, tmp)
    return (import_intensity(mod, policy, lz, mrkt, z, tmp) - i_exp) * getattr(
        mod, names(policy).import_mw_var
    )[lz, mrkt, z, tmp] + i_exp * purchased_power(mod, lz, mrkt, tmp)


def realized_purchase_mw(mod, policy, idx):
    lz, mrkt, z, tmp = idx
    return max(value(purchased_power(mod, lz, mrkt, tmp)), 0)


def realized_sale_mw(mod, policy, idx):
    lz, mrkt, z, tmp = idx
    return max(-value(purchased_power(mod, lz, mrkt, tmp)), 0)


def realized_import_emissions_tons(mod, policy, idx):
    return realized_purchase_mw(mod, policy, idx) * import_intensity(mod, policy, *idx)


def realized_export_credits_tons(mod, policy, idx):
    """
    Sales earn credits only in net zones.
    """
    if is_net_zone(mod, policy, idx[2]):
        return realized_sale_mw(mod, policy, idx) * export_intensity(mod, policy, *idx)
    else:
        return 0


MARKET_SOURCE = ImportEmissionsSource(
    label="Market",
    results_prefix="market_import",
    zone_tmps_set=lambda policy: names(policy).lz_market_zone_tmps,
    zone_position=2,
    import_emissions_tons=import_emissions_tons,
    signed_import_emissions_tons=signed_import_emissions_tons,
    realized_import_emissions_tons=realized_import_emissions_tons,
    realized_export_credits_tons=realized_export_credits_tons,
)


# Input-Output
###############################################################################


def generic_load_model_data(
    m,
    d,
    data_portal,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    policy,
):
    """
    Both files are optional: with neither, no pair is assigned to a zone.
    """
    n = names(policy)
    inputs_directory = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
    )

    zones_file = os.path.join(inputs_directory, n.zones_file)
    if os.path.exists(zones_file):
        data_portal.load(
            filename=zones_file,
            index=getattr(m, n.lz_market_zones),
            param=(
                getattr(m, n.import_intensity),
                getattr(m, n.export_intensity),
            ),
        )

    timepoint_emissions_file = os.path.join(
        inputs_directory, n.timepoint_emissions_file
    )
    if os.path.exists(timepoint_emissions_file):
        data_portal.load(
            filename=timepoint_emissions_file,
            param=(
                getattr(m, n.import_intensity_hourly),
                getattr(m, n.export_intensity_hourly),
            ),
        )


def generic_export_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    m,
    d,
    policy,
):
    """
    Per load zone, market, zone and timepoint: the final position split into
    purchases and sales, the intensities, the import emissions as the model
    counted them and as recomputed from the position, and the export
    credits. Written only when pairs are assigned to zones.
    """
    n = names(policy)
    idxs = sorted(getattr(m, n.lz_market_zone_tmps))
    if not idxs:
        return

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            f"{n.results}.csv",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "load_zone",
                "market",
                policy.zone_column,
                "timepoint",
                "period",
                "timepoint_weight",
                "number_of_hours_in_timepoint",
                "import_co2_intensity_tons_per_mwh",
                "export_co2_intensity_tons_per_mwh",
                "purchase_mw",
                "sale_mw",
                "import_emissions_tons",
                "import_emissions_tons_degen",
                "export_credits_tons",
            ]
        )
        for lz, mrkt, z, tmp in idxs:
            idx = (lz, mrkt, z, tmp)
            writer.writerow(
                [
                    lz,
                    mrkt,
                    z,
                    tmp,
                    m.period[tmp],
                    m.tmp_weight[tmp],
                    m.hrs_in_tmp[tmp],
                    import_intensity(m, policy, *idx),
                    export_intensity(m, policy, *idx),
                    realized_purchase_mw(m, policy, idx),
                    realized_sale_mw(m, policy, idx),
                    value(import_emissions_tons(m, policy, idx)),
                    realized_import_emissions_tons(m, policy, idx),
                    realized_export_credits_tons(m, policy, idx),
                ]
            )


# Database
###############################################################################


def lz_market_zones_sql(subscenarios, policy, scope_zones=True):
    """
    The zone assignments of the scenario's (load zone, market) pairs; with
    *scope_zones*, only those to zones in the scenario's zone subscenario.
    """
    n = names(policy)
    zone_filter = (
        f"""
        AND {policy.zone_column} IN (
            SELECT {policy.zone_column}
            FROM inputs_geography_{policy.name}_zones
            WHERE {policy.name}_zone_scenario_id =
                {getattr(subscenarios, policy.zone_subscenario_attr)}
        )
        """
        if scope_zones
        else ""
    )
    return f"""
        SELECT load_zone, market, {policy.zone_column},
            tmp_import_emissions_scenario_id,
            co2_intensity_tons_per_mwh, export_co2_intensity_tons_per_mwh
        FROM {n.zones_table}
        WHERE {n.subscenario_attr.lower()} = {getattr(subscenarios, n.subscenario_attr)}
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
        {zone_filter}
    """


def generic_get_inputs_from_database(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    policy,
):
    """
    :return: the zone assignments (load zone, market, zone, intensities) and
        the timepoint intensity adders of the markets
    """
    n = names(policy)
    c = conn.cursor()
    lz_market_zones = c.execute(f"""
        SELECT load_zone, market, {policy.zone_column},
            co2_intensity_tons_per_mwh, export_co2_intensity_tons_per_mwh
        FROM ({lz_market_zones_sql(subscenarios, policy)})
        """)

    c2 = conn.cursor()
    timepoint_emissions = c2.execute(f"""
        SELECT market, timepoint,
            co2_intensity_tons_per_mwh_hourly,
            export_co2_intensity_tons_per_mwh_hourly
        FROM {n.timepoint_emissions_table}
        WHERE (market, tmp_import_emissions_scenario_id) IN (
            SELECT DISTINCT market, tmp_import_emissions_scenario_id
            FROM ({lz_market_zones_sql(subscenarios, policy)})
        )
        AND timepoint IN (
            SELECT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
        )
        """)

    return lz_market_zones, timepoint_emissions


def generic_write_model_inputs(
    scenario_directory,
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    policy,
):
    """
    Write the zone assignments and the timepoint intensity adders; each
    file is written only if it has data.
    """
    n = names(policy)
    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )

    lz_market_zones, timepoint_emissions = generic_get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
        policy,
    )

    for fname, data in [
        (n.zones_file, lz_market_zones),
        (n.timepoint_emissions_file, timepoint_emissions),
    ]:
        write_tab_file_model_inputs(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            fname=fname,
            data=data,
            replace_nulls=True,
        )


def generic_import_results_into_database(
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
    policy,
):
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
        which_results=names(policy).results,
    )


# Validation
###############################################################################


def generic_validate_inputs(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    policy,
    module_name,
):
    """
    Check zone assignments against the scenario's zones, the intensities'
    signs, the export-vs-import intensities in net zones and that a market
    references a single timepoint profile.
    """
    n = names(policy)
    c = conn.cursor()
    df = cursor_to_df(
        c.execute(lz_market_zones_sql(subscenarios, policy, scope_zones=False))
    )
    if df.empty:
        return

    zones_and_bases = c.execute(f"""
        SELECT {policy.zone_column}, COALESCE(import_emissions_basis, 'gross')
        FROM inputs_geography_{policy.name}_zones
        WHERE {policy.name}_zone_scenario_id =
            {getattr(subscenarios, policy.zone_subscenario_attr)}
        """).fetchall()
    basis_by_zone = dict(zones_and_bases)

    tmp_df = cursor_to_df(c.execute(f"""
            SELECT market, tmp_import_emissions_scenario_id, timepoint,
                COALESCE(co2_intensity_tons_per_mwh_hourly, 0)
                    AS import_intensity_hourly,
                COALESCE(export_co2_intensity_tons_per_mwh_hourly, 0)
                    AS export_intensity_hourly
            FROM {n.timepoint_emissions_table}
            WHERE timepoint IN (
                SELECT timepoint
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
            )
            """))

    df["import_intensity"] = df["co2_intensity_tons_per_mwh"].fillna(0)
    df["export_intensity"] = df["export_co2_intensity_tons_per_mwh"].fillna(0)
    pair_cols = ["load_zone", "market"]

    def labels(rows):
        return ", ".join(
            "-".join(str(row[c]) for c in pair_cols + [policy.zone_column])
            for _, row in rows.iterrows()
        )

    errors = []
    unknown_zones = df[~df[policy.zone_column].isin(basis_by_zone.keys())]
    if not unknown_zones.empty:
        errors.append(
            f"load_zone-market-{policy.zone_column}(s) '{labels(unknown_zones)}': "
            f"{policy.zone_column} not in the scenario's zones "
            f"{sorted(basis_by_zone.keys())}."
        )
    negative = df[(df["import_intensity"] < 0) | (df["export_intensity"] < 0)]
    if not negative.empty:
        errors.append(
            f"load_zone-market-{policy.zone_column}(s) '{labels(negative)}': "
            "intensities must be non-negative."
        )
    errors += validate_export_intensities(
        df, basis_by_zone, tmp_df, ["market"], policy.zone_column
    )
    errors += validate_single_profile_per_entity(df, ["market"])

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=module_name,
        db_table=n.zones_table,
        severity="High",
        errors=errors,
    )
