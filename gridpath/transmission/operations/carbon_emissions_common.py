# Copyright 2016-2023 Blue Marble Analytics LLC.
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
Emissions imported over transmission lines, shared by the carbon cap and
carbon tax modules (:code:`transmission.operations.carbon_emissions` and
:code:`transmission.operations.carbon_tax_emissions`). See
:code:`gridpath.system.policy.import_emissions` for the accounting.

A line is assigned to a zone with an *import direction* (whether positive or
negative line flow is an import into the zone), an import intensity and an
export intensity, each a flat value per zone row plus an optional
timepoint-varying adder per line. A line may be assigned to several zones,
e.g. importing into the zone at one end and exporting from the zone at the
other end.
"""

import csv
import os.path
from types import SimpleNamespace

from pyomo.environ import Constraint, NonNegativeReals, Param, Set, Var, value

from gridpath.auxiliary.auxiliary import cursor_to_df, subset_init_by_set_membership
from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.auxiliary.validations import (
    validate_columns,
    validate_values,
    write_validation_to_database,
)
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)
from gridpath.system.policy.import_emissions import (
    IMPORT_DIRECTIONS,
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
    The component names for a policy's transmission import emissions (built
    once per policy; the per-index expression helpers call this).
    """
    if policy.name in _NAMES:
        return _NAMES[policy.name]
    P, p, Pc = policy.set_prefix, policy.name, policy.component_prefix
    _NAMES[policy.name] = SimpleNamespace(
        line_zones=f"{P}_TX_LINE_ZONES",
        lines=f"{P}_TX_LINES",
        lines_by_zone=f"{P}_TX_LINES_BY_ZONE",
        opr_tmps=f"{P}_TX_OPR_TMPS",
        line_zone_opr_tmps=f"{P}_TX_LINE_ZONE_OPR_TMPS",
        gross_line_zone_opr_tmps=f"GROSS_{P}_TX_LINE_ZONE_OPR_TMPS",
        net_line_zone_opr_tmps=f"NET_{P}_TX_LINE_ZONE_OPR_TMPS",
        import_direction=f"tx_{p}_import_direction",
        import_intensity=f"tx_{p}_co2_intensity_tons_per_mwh",
        export_intensity=f"tx_{p}_export_co2_intensity_tons_per_mwh",
        import_intensity_hourly=f"tx_{p}_co2_intensity_tons_per_mwh_hourly",
        export_intensity_hourly=f"tx_{p}_export_co2_intensity_tons_per_mwh_hourly",
        import_emissions_var=f"Tx_{Pc}_Import_Emissions_Tons",
        import_emissions_constraint=f"Tx_{Pc}_Import_Emissions_Constraint",
        import_mw_var=f"Tx_{Pc}_Import_MW",
        import_mw_constraint=f"Tx_{Pc}_Import_MW_Constraint",
        zones_file=f"transmission_{p}_{policy.zones_file_tag}.tab",
        timepoint_emissions_file=f"transmission_{p}_timepoint_emissions.tab",
        results=f"transmission_{p}_imports",
        zones_table=f"inputs_transmission_{p}_zones",
        timepoint_emissions_table=f"inputs_transmission_{p}_timepoint_emissions",
        subscenario_attr=f"TRANSMISSION_{P}_ZONE_SCENARIO_ID",
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
    | | :code:`<P>_TX_LINE_ZONES`                                             |
    |                                                                         |
    | The transmission lines whose imports or exports count toward a zone and |
    | that zone (one or more elements, per the policy's zone columns).        |
    +-------------------------------------------------------------------------+
    | | :code:`<P>_TX_LINES`                                                  |
    |                                                                         |
    | The lines assigned to any zone.                                         |
    +-------------------------------------------------------------------------+
    | | :code:`<P>_TX_LINES_BY_ZONE`                                          |
    | | *Defined over*: the policy's zones                                    |
    |                                                                         |
    | Indexed set of the lines assigned to each zone.                         |
    +-------------------------------------------------------------------------+
    | | :code:`<P>_TX_OPR_TMPS`                                               |
    |                                                                         |
    | The assigned lines' operational timepoints.                             |
    +-------------------------------------------------------------------------+
    | | :code:`<P>_TX_LINE_ZONE_OPR_TMPS`                                     |
    |                                                                         |
    | Line, zone and operational timepoint; split                             |
    | into :code:`GROSS_<P>_TX_LINE_ZONE_OPR_TMPS` and                        |
    | :code:`NET_<P>_TX_LINE_ZONE_OPR_TMPS` by the zone's import-emissions    |
    | basis.                                                                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`tx_<p>_import_direction`                                       |
    | | *Defined over*: :code:`<P>_TX_LINE_ZONES`                             |
    | | *Within*: :code:`["positive", "negative"]`                            |
    |                                                                         |
    | Which line flow direction is an import into the zone: "positive"        |
    | ("negative") means positive (negative) flows are imports and negative   |
    | (positive) flows are exports.                                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`tx_<p>_co2_intensity_tons_per_mwh`                             |
    | | *Defined over*: :code:`<P>_TX_LINE_ZONES`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The emissions intensity of imports in metric tonnes per MWh.            |
    +-------------------------------------------------------------------------+
    | | :code:`tx_<p>_export_co2_intensity_tons_per_mwh`                      |
    | | *Defined over*: :code:`<P>_TX_LINE_ZONES`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The credit per MWh exported, in metric tonnes; applies only in zones    |
    | with the ``net_prd`` basis and may not exceed the import intensity.     |
    +-------------------------------------------------------------------------+
    | | :code:`tx_<p>_co2_intensity_tons_per_mwh_hourly`                      |
    | | :code:`tx_<p>_export_co2_intensity_tons_per_mwh_hourly`               |
    | | *Defined over*: :code:`<P>_TX_OPR_TMPS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Timepoint-varying adders to the line's flat intensities in every zone   |
    | it is assigned to.                                                      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Tx_<Pc>_Import_Emissions_Tons`                                 |
    | | *Defined over*: :code:`GROSS_<P>_TX_LINE_ZONE_OPR_TMPS`               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The emissions imported over the line into a gross-basis zone.           |
    +-------------------------------------------------------------------------+
    | | :code:`Tx_<Pc>_Import_MW`                                             |
    | | *Defined over*: :code:`NET_<P>_TX_LINE_ZONE_OPR_TMPS`                 |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The power imported over the line into a net-basis zone.                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Tx_<Pc>_Import_Emissions_Constraint`                           |
    | | *Enforced over*: :code:`GROSS_<P>_TX_LINE_ZONE_OPR_TMPS`              |
    |                                                                         |
    | Imported emissions are at least the flow into the zone times the        |
    | import intensity.                                                       |
    +-------------------------------------------------------------------------+
    | | :code:`Tx_<Pc>_Import_MW_Constraint`                                  |
    | | *Enforced over*: :code:`NET_<P>_TX_LINE_ZONE_OPR_TMPS`                |
    |                                                                         |
    | Imported power is at least the flow into the zone.                      |
    +-------------------------------------------------------------------------+

    Both variables can exceed the actual imports where nothing pushes them
    down (a non-binding cap, a zero tax); the results also report the values
    recomputed from the solved flows.
    """
    n = names(policy)
    zones = getattr(m, policy.zones_set)
    # The zone is one or more elements of the index tuples (one for the
    # carbon cap and carbon tax); the helpers below take tuples apart
    zone_dimen = policy.zone_dimen

    # Sets
    ###########################################################################

    setattr(m, n.line_zones, Set(dimen=1 + zone_dimen, within=m.TX_LINES * zones))

    setattr(
        m,
        n.lines,
        Set(
            within=m.TX_LINES,
            initialize=lambda mod: sorted(
                set(idx[0] for idx in getattr(mod, n.line_zones))
            ),
        ),
    )

    setattr(
        m,
        n.lines_by_zone,
        Set(
            zones,
            within=m.TX_LINES,
            initialize=lambda mod, *z: [
                idx[0] for idx in getattr(mod, n.line_zones) if idx[1:] == z
            ],
        ),
    )

    setattr(
        m,
        n.opr_tmps,
        Set(
            dimen=2,
            initialize=lambda mod: subset_init_by_set_membership(
                mod=mod,
                superset="TX_OPR_TMPS",
                index=0,
                membership_set=getattr(mod, n.lines),
            ),
        ),
    )

    def line_zone_opr_tmps_init(mod):
        tmps_by_line = {}
        for tx, tmp in getattr(mod, n.opr_tmps):
            tmps_by_line.setdefault(tx, []).append(tmp)
        return [
            (*line_zone, tmp)
            for line_zone in getattr(mod, n.line_zones)
            for tmp in tmps_by_line.get(line_zone[0], [])
        ]

    setattr(
        m,
        n.line_zone_opr_tmps,
        Set(dimen=2 + zone_dimen, initialize=line_zone_opr_tmps_init),
    )

    setattr(
        m,
        n.gross_line_zone_opr_tmps,
        Set(
            dimen=2 + zone_dimen,
            initialize=lambda mod: [
                idx
                for idx in getattr(mod, n.line_zone_opr_tmps)
                if not is_net_zone(mod, policy, idx[1:-1])
            ],
        ),
    )

    setattr(
        m,
        n.net_line_zone_opr_tmps,
        Set(
            dimen=2 + zone_dimen,
            initialize=lambda mod: [
                idx
                for idx in getattr(mod, n.line_zone_opr_tmps)
                if is_net_zone(mod, policy, idx[1:-1])
            ],
        ),
    )

    # Params
    ###########################################################################

    setattr(
        m,
        n.import_direction,
        Param(getattr(m, n.line_zones), within=IMPORT_DIRECTIONS),
    )

    for param in [n.import_intensity, n.export_intensity]:
        setattr(
            m,
            param,
            Param(getattr(m, n.line_zones), within=NonNegativeReals, default=0),
        )

    for param in [n.import_intensity_hourly, n.export_intensity_hourly]:
        setattr(
            m,
            param,
            Param(getattr(m, n.opr_tmps), within=NonNegativeReals, default=0),
        )

    # Variables and constraints
    ###########################################################################

    setattr(
        m,
        n.import_emissions_var,
        Var(getattr(m, n.gross_line_zone_opr_tmps), within=NonNegativeReals),
    )

    def import_emissions_rule(mod, *idx):
        (tx,), z, tmp = split_index(TX_SOURCE, idx)
        return getattr(mod, n.import_emissions_var)[idx] >= import_flow(
            mod, policy, tx, z, tmp
        ) * import_intensity(mod, policy, tx, z, tmp)

    setattr(
        m,
        n.import_emissions_constraint,
        Constraint(getattr(m, n.gross_line_zone_opr_tmps), rule=import_emissions_rule),
    )

    setattr(
        m,
        n.import_mw_var,
        Var(getattr(m, n.net_line_zone_opr_tmps), within=NonNegativeReals),
    )

    def import_mw_rule(mod, *idx):
        (tx,), z, tmp = split_index(TX_SOURCE, idx)
        return getattr(mod, n.import_mw_var)[idx] >= import_flow(
            mod, policy, tx, z, tmp
        )

    setattr(
        m,
        n.import_mw_constraint,
        Constraint(getattr(m, n.net_line_zone_opr_tmps), rule=import_mw_rule),
    )


# Per-index expressions
###############################################################################


def import_flow(mod, policy, tx, z, tmp):
    """
    The line flow into the zone (an expression; negative when exporting).
    The zone ``z`` is a tuple (as everywhere below).
    """
    if getattr(mod, names(policy).import_direction)[tx, z] == "positive":
        return mod.Transmit_Power_MW[tx, tmp]
    else:
        return -mod.Transmit_Power_MW[tx, tmp]


def import_intensity(mod, policy, tx, z, tmp):
    n = names(policy)
    return (
        getattr(mod, n.import_intensity)[tx, z]
        + getattr(mod, n.import_intensity_hourly)[tx, tmp]
    )


def export_intensity(mod, policy, tx, z, tmp):
    n = names(policy)
    return (
        getattr(mod, n.export_intensity)[tx, z]
        + getattr(mod, n.export_intensity_hourly)[tx, tmp]
    )


def import_emissions_tons(mod, policy, idx):
    """
    The emissions imported over the line in the timepoint as the model counts
    them: the emissions variable in a gross zone, imported MW times the
    import intensity in a net zone.
    """
    (tx,), z, tmp = split_index(TX_SOURCE, idx)
    n = names(policy)
    if is_net_zone(mod, policy, z):
        return getattr(mod, n.import_mw_var)[idx] * import_intensity(
            mod, policy, tx, z, tmp
        )
    else:
        return getattr(mod, n.import_emissions_var)[idx]


def signed_import_emissions_tons(mod, policy, idx):
    """
    Imports at the import intensity less exports at the export intensity, for
    a net zone; see :code:`gridpath.system.policy.import_emissions`.
    """
    (tx,), z, tmp = split_index(TX_SOURCE, idx)
    i_exp = export_intensity(mod, policy, tx, z, tmp)
    return (import_intensity(mod, policy, tx, z, tmp) - i_exp) * getattr(
        mod, names(policy).import_mw_var
    )[idx] + i_exp * import_flow(mod, policy, tx, z, tmp)


def realized_import_mw(mod, policy, idx):
    (tx,), z, tmp = split_index(TX_SOURCE, idx)
    return max(value(import_flow(mod, policy, tx, z, tmp)), 0)


def realized_export_mw(mod, policy, idx):
    (tx,), z, tmp = split_index(TX_SOURCE, idx)
    return max(-value(import_flow(mod, policy, tx, z, tmp)), 0)


def realized_import_emissions_tons(mod, policy, idx):
    (tx,), z, tmp = split_index(TX_SOURCE, idx)
    return realized_import_mw(mod, policy, idx) * import_intensity(
        mod, policy, tx, z, tmp
    )


def realized_export_credits_tons(mod, policy, idx):
    """
    Exports earn credits only in net zones.
    """
    (tx,), z, tmp = split_index(TX_SOURCE, idx)
    if is_net_zone(mod, policy, z):
        return realized_export_mw(mod, policy, idx) * export_intensity(
            mod, policy, tx, z, tmp
        )
    else:
        return 0


TX_SOURCE = ImportEmissionsSource(
    label="Tx",
    results_prefix="import",
    zone_tmps_set=lambda policy: names(policy).line_zone_opr_tmps,
    entity_dimen=1,
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
    Both files are optional: with neither, no line is assigned to a zone.
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
            index=getattr(m, n.line_zones),
            param=(
                getattr(m, n.import_direction),
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
    Per line, zone and timepoint: the flows split into imports and exports,
    the intensities, the import emissions as the model counted them and as
    recomputed from the flows, and the export credits. Written only when
    lines are assigned to zones.
    """
    n = names(policy)
    idxs = sorted(getattr(m, n.line_zone_opr_tmps))
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
                "transmission_line",
                *policy.zone_columns,
                "timepoint",
                "period",
                "timepoint_weight",
                "number_of_hours_in_timepoint",
                "import_direction",
                "import_co2_intensity_tons_per_mwh",
                "export_co2_intensity_tons_per_mwh",
                "import_mw",
                "export_mw",
                "import_emissions_tons",
                "import_emissions_tons_degen",
                "export_credits_tons",
            ]
        )
        for idx in idxs:
            (tx,), z, tmp = split_index(TX_SOURCE, idx)
            writer.writerow(
                [
                    tx,
                    *z,
                    tmp,
                    m.period[tmp],
                    m.tmp_weight[tmp],
                    m.hrs_in_tmp[tmp],
                    getattr(m, n.import_direction)[tx, z],
                    import_intensity(m, policy, tx, z, tmp),
                    export_intensity(m, policy, tx, z, tmp),
                    realized_import_mw(m, policy, idx),
                    realized_export_mw(m, policy, idx),
                    value(import_emissions_tons(m, policy, idx)),
                    realized_import_emissions_tons(m, policy, idx),
                    realized_export_credits_tons(m, policy, idx),
                ]
            )


# Database
###############################################################################


def line_zones_sql(subscenarios, policy, scope_zones=True):
    """
    The zone assignments of the scenario's transmission portfolio; with
    *scope_zones*, only those to zones in the scenario's zone subscenario.
    """
    n = names(policy)
    zone_filter = zone_scope_sql(subscenarios, policy) if scope_zones else ""
    return f"""
        SELECT transmission_line, {", ".join(policy.zone_columns)}, import_direction,
            tmp_import_emissions_scenario_id,
            tx_co2_intensity_tons_per_mwh, tx_export_co2_intensity_tons_per_mwh
        FROM {n.zones_table}
        WHERE {n.subscenario_attr.lower()} = {getattr(subscenarios, n.subscenario_attr)}
        AND transmission_line IN (
            SELECT transmission_line
            FROM inputs_transmission_portfolios
            WHERE transmission_portfolio_scenario_id =
                {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}
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
    :return: the zone assignments (line, zone, direction, intensities) and
        the timepoint intensity adders of the lines
    """
    n = names(policy)
    c = conn.cursor()
    line_zones = c.execute(f"""
        SELECT transmission_line, {", ".join(policy.zone_columns)}, import_direction,
            tx_co2_intensity_tons_per_mwh, tx_export_co2_intensity_tons_per_mwh
        FROM ({line_zones_sql(subscenarios, policy)})
        """)

    c2 = conn.cursor()
    timepoint_emissions = c2.execute(f"""
        SELECT transmission_line, timepoint,
            tx_co2_intensity_tons_per_mwh_hourly,
            tx_export_co2_intensity_tons_per_mwh_hourly
        FROM {n.timepoint_emissions_table}
        WHERE (transmission_line, tmp_import_emissions_scenario_id) IN (
            SELECT DISTINCT transmission_line, tmp_import_emissions_scenario_id
            FROM ({line_zones_sql(subscenarios, policy)})
        )
        AND timepoint IN (
            SELECT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
        )
        """)

    return line_zones, timepoint_emissions


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

    line_zones, timepoint_emissions = generic_get_inputs_from_database(
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
        (n.zones_file, line_zones),
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
    Check zone assignments against the scenario's zones, the import
    directions, the intensities' signs, the export-vs-import intensities in
    net zones and that a line references a single timepoint profile.
    """
    n = names(policy)
    c = conn.cursor()
    df = cursor_to_df(
        c.execute(line_zones_sql(subscenarios, policy, scope_zones=False))
    )
    if df.empty:
        return

    basis_by_zone = get_basis_by_zone(c, subscenarios, policy)

    tmp_df = cursor_to_df(c.execute(f"""
            SELECT transmission_line, tmp_import_emissions_scenario_id, timepoint,
                COALESCE(tx_co2_intensity_tons_per_mwh_hourly, 0)
                    AS import_intensity_hourly,
                COALESCE(tx_export_co2_intensity_tons_per_mwh_hourly, 0)
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

    df["import_intensity"] = df["tx_co2_intensity_tons_per_mwh"].fillna(0)
    df["export_intensity"] = df["tx_export_co2_intensity_tons_per_mwh"].fillna(0)

    errors = (
        validate_zones(df, basis_by_zone, ["transmission_line"], policy)
        + validate_columns(df, "import_direction", valids=IMPORT_DIRECTIONS)
        + validate_values(
            df,
            ["import_intensity", "export_intensity"],
            idx_col=["transmission_line", *policy.zone_columns],
            min=0,
        )
        + validate_export_intensities(
            df, basis_by_zone, tmp_df, ["transmission_line"], policy
        )
        + validate_single_profile_per_entity(df, ["transmission_line"])
    )
    if policy.validate_rows is not None:
        errors += policy.validate_rows(
            c, subscenarios, df, ["transmission_line"], policy
        )

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
