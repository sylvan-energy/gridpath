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
    get_basis_by_zone,
    is_net_zone,
    split_index,
    validate_export_intensities,
    validate_single_profile_per_entity,
    validate_zones,
    zone_scope_sql,
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
        zones_file=f"market_{p}_{policy.zones_file_tag}.tab",
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
    | The (load zone, market) pairs whose purchases or sales count toward a   |
    | zone and that zone (one or more elements, per the policy's zone         |
    | columns).                                                               |
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
    | Load zone, market, zone and timepoint; split                            |
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
    # The zone is one or more elements of the index tuples (one for the
    # carbon cap and carbon tax); the helpers below take tuples apart
    zone_dimen = policy.zone_dimen

    # Sets
    ###########################################################################

    setattr(
        m, n.lz_market_zones, Set(dimen=2 + zone_dimen, within=m.LZ_MARKETS * zones)
    )

    setattr(
        m,
        n.markets,
        Set(
            within=m.MARKETS,
            initialize=lambda mod: sorted(
                set(idx[1] for idx in getattr(mod, n.lz_market_zones))
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
            dimen=3 + zone_dimen,
            initialize=lambda mod: [
                (*lz_market_zone, tmp)
                for lz_market_zone in getattr(mod, n.lz_market_zones)
                for tmp in mod.TMPS
            ],
        ),
    )

    setattr(
        m,
        n.gross_lz_market_zone_tmps,
        Set(
            dimen=3 + zone_dimen,
            initialize=lambda mod: [
                idx
                for idx in getattr(mod, n.lz_market_zone_tmps)
                if not is_net_zone(mod, policy, idx[2:-1])
            ],
        ),
    )

    setattr(
        m,
        n.net_lz_market_zone_tmps,
        Set(
            dimen=3 + zone_dimen,
            initialize=lambda mod: [
                idx
                for idx in getattr(mod, n.lz_market_zone_tmps)
                if is_net_zone(mod, policy, idx[2:-1])
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

    def import_emissions_rule(mod, *idx):
        (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
        return getattr(mod, n.import_emissions_var)[idx] >= purchased_power(
            mod, lz, mrkt, tmp
        ) * import_intensity(mod, policy, lz, mrkt, z, tmp)

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

    def import_mw_rule(mod, *idx):
        (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
        return getattr(mod, n.import_mw_var)[idx] >= purchased_power(mod, lz, mrkt, tmp)

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
    (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
    n = names(policy)
    if is_net_zone(mod, policy, z):
        return getattr(mod, n.import_mw_var)[idx] * import_intensity(
            mod, policy, lz, mrkt, z, tmp
        )
    else:
        return getattr(mod, n.import_emissions_var)[idx]


def signed_import_emissions_tons(mod, policy, idx):
    """
    Purchases at the import intensity less sales at the export intensity,
    for a net zone; see :code:`gridpath.system.policy.import_emissions`.
    """
    (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
    i_exp = export_intensity(mod, policy, lz, mrkt, z, tmp)
    return (import_intensity(mod, policy, lz, mrkt, z, tmp) - i_exp) * getattr(
        mod, names(policy).import_mw_var
    )[idx] + i_exp * purchased_power(mod, lz, mrkt, tmp)


def realized_purchase_mw(mod, policy, idx):
    (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
    return max(value(purchased_power(mod, lz, mrkt, tmp)), 0)


def realized_sale_mw(mod, policy, idx):
    (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
    return max(-value(purchased_power(mod, lz, mrkt, tmp)), 0)


def realized_import_emissions_tons(mod, policy, idx):
    (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
    return realized_purchase_mw(mod, policy, idx) * import_intensity(
        mod, policy, lz, mrkt, z, tmp
    )


def realized_export_credits_tons(mod, policy, idx):
    """
    Sales earn credits only in net zones.
    """
    (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
    if is_net_zone(mod, policy, z):
        return realized_sale_mw(mod, policy, idx) * export_intensity(
            mod, policy, lz, mrkt, z, tmp
        )
    else:
        return 0


MARKET_SOURCE = ImportEmissionsSource(
    label="Market",
    results_prefix="market_import",
    zone_tmps_set=lambda policy: names(policy).lz_market_zone_tmps,
    entity_dimen=2,
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
                *policy.zone_columns,
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
        for idx in idxs:
            (lz, mrkt), z, tmp = split_index(MARKET_SOURCE, idx)
            writer.writerow(
                [
                    lz,
                    mrkt,
                    *z,
                    tmp,
                    m.period[tmp],
                    m.tmp_weight[tmp],
                    m.hrs_in_tmp[tmp],
                    import_intensity(m, policy, lz, mrkt, z, tmp),
                    export_intensity(m, policy, lz, mrkt, z, tmp),
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
    zone_filter = zone_scope_sql(subscenarios, policy) if scope_zones else ""
    return f"""
        SELECT load_zone, market, {", ".join(policy.zone_columns)},
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
        {policy.rows_filter_sql}
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
        SELECT load_zone, market, {", ".join(policy.zone_columns)},
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

    basis_by_zone = get_basis_by_zone(c, subscenarios, policy)

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
    label_cols = pair_cols + policy.zone_columns

    def labels(rows):
        return ", ".join(
            "-".join(str(row[c]) for c in label_cols) for _, row in rows.iterrows()
        )

    errors = validate_zones(df, basis_by_zone, pair_cols, policy)
    negative = df[(df["import_intensity"] < 0) | (df["export_intensity"] < 0)]
    if not negative.empty:
        errors.append(
            f"{'-'.join(label_cols)}(s) '{labels(negative)}': "
            "intensities must be non-negative."
        )
    errors += validate_export_intensities(df, basis_by_zone, tmp_df, ["market"], policy)
    errors += validate_single_profile_per_entity(df, ["market"])
    if policy.validate_rows is not None:
        errors += policy.validate_rows(c, subscenarios, df, pair_cols, policy)

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
