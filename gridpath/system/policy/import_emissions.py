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
Emissions imported into a carbon cap or carbon tax zone over transmission
lines and through market purchases.

Each *source* (transmission lines, markets) assigns its entities to zones with
an import intensity and an export intensity, builds the per-timepoint import
variables, and reports per-timepoint results. The source aggregation modules
in :code:`system.policy.<policy>` sum each source into zone-period expressions
of its *gross* import emissions and of its *signed* emissions (imports less
export credits). The policy's import-emissions module combines the sources per
the zone's *import-emissions basis*:

* ``gross``: every imported MWh counts at its import intensity and exports
  earn nothing; the sources' gross totals enter the policy directly.
* ``net_prd``: exports earn a credit at their export intensity and the zone's
  net import emissions are floored at zero over each period.

Under ``net_prd`` the signed emissions of an entity in a timepoint are
:math:`(I_{imp} - I_{exp}) \\cdot F^{+} + I_{exp} \\cdot f`, with :math:`f`
the flow into the zone (negative for exports) and :math:`F^{+} \\geq f`,
:math:`F^{+} \\geq 0` the imported MW variable; this is linear and exact as
long as :math:`I_{imp} \\geq I_{exp}`, which the inputs validation enforces.
With a zero export intensity, ``net_prd`` reproduces ``gross`` exactly.

This module holds the policy descriptors and the generic model and results
code the policy-specific modules call.
"""

from pyomo.environ import Constraint, Expression, NonNegativeReals, Set, Var, value

from gridpath.auxiliary.dynamic_components import (
    carbon_cap_import_emission_components,
    carbon_cap_signed_import_emission_components,
    carbon_tax_import_emission_components,
    carbon_tax_signed_import_emission_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.carbon_cap import CARBON_CAP_ZONE_PRD_DF
from gridpath.system.policy.carbon_tax import CARBON_TAX_ZONE_PRD_DF

GROSS = "gross"
NET_PRD = "net_prd"
IMPORT_EMISSIONS_BASES = [GROSS, NET_PRD]

IMPORT_DIRECTIONS = ["positive", "negative"]


class ImportEmissionsPolicy(object):
    """
    The names a policy's import-emissions components are built from, so the
    carbon cap and the carbon tax share one implementation.
    """

    def __init__(
        self,
        name,
        zones_set,
        zone_periods_set,
        zone_subscenario_attr,
        zone_prd_df,
        import_emission_components,
        signed_import_emission_components,
    ):
        # 'carbon_cap' / 'carbon_tax'
        self.name = name
        # 'Carbon_Cap' / 'Carbon_Tax', for Var/Expression/Constraint names
        self.component_prefix = name.title()
        # 'CARBON_CAP' / 'CARBON_TAX', for Set names
        self.set_prefix = name.upper()
        # the zone column in the inputs tables and .tab files
        self.zone_column = f"{name}_zone"
        self.zones_set = zones_set
        self.zone_periods_set = zone_periods_set
        self.basis_param = f"{name}_import_emissions_basis"
        self.zone_subscenario_attr = zone_subscenario_attr
        self.zone_prd_df = zone_prd_df
        self.import_emission_components = import_emission_components
        self.signed_import_emission_components = signed_import_emission_components


CARBON_CAP = ImportEmissionsPolicy(
    name="carbon_cap",
    zones_set="CARBON_CAP_ZONES",
    zone_periods_set="CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP",
    zone_subscenario_attr="CARBON_CAP_ZONE_SCENARIO_ID",
    zone_prd_df=CARBON_CAP_ZONE_PRD_DF,
    import_emission_components=carbon_cap_import_emission_components,
    signed_import_emission_components=carbon_cap_signed_import_emission_components,
)

CARBON_TAX = ImportEmissionsPolicy(
    name="carbon_tax",
    zones_set="CARBON_TAX_ZONES",
    zone_periods_set="CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX",
    zone_subscenario_attr="CARBON_TAX_ZONE_SCENARIO_ID",
    zone_prd_df=CARBON_TAX_ZONE_PRD_DF,
    import_emission_components=carbon_tax_import_emission_components,
    signed_import_emission_components=carbon_tax_signed_import_emission_components,
)


class ImportEmissionsSource(object):
    """
    What the aggregation code needs to know about a source of imports
    (transmission lines or markets). The per-index functions take
    :code:`(mod, policy, index_tuple)` where the tuple is an element of the
    source's (entity..., zone, timepoint) set.
    """

    def __init__(
        self,
        label,
        results_prefix,
        zone_tmps_set,
        zone_position,
        import_emissions_tons,
        signed_import_emissions_tons,
        realized_import_emissions_tons,
        realized_export_credits_tons,
    ):
        # 'Tx' / 'Market', for component names
        self.label = label
        # 'import' / 'market_import', for the zone-period results columns
        self.results_prefix = results_prefix
        # function of policy returning the (entity..., zone, timepoint) set name
        self.zone_tmps_set = zone_tmps_set
        # position of the zone in that set's tuples
        self.zone_position = zone_position
        self.import_emissions_tons = import_emissions_tons
        self.signed_import_emissions_tons = signed_import_emissions_tons
        self.realized_import_emissions_tons = realized_import_emissions_tons
        self.realized_export_credits_tons = realized_export_credits_tons


# Index helpers
###############################################################################


def zone_basis(mod, policy, zone):
    return getattr(mod, policy.basis_param)[zone]


def is_net_zone(mod, policy, zone):
    return zone_basis(mod, policy, zone) == NET_PRD


def indices_by_zone_period(mod, policy, source):
    """
    The source's (entity..., zone, timepoint) tuples grouped by (zone,
    period), built in one pass over the set the first time it is asked for
    and cached on the model instance.
    """
    cache_attr = f"_gridpath_{policy.name}_{source.label.lower()}_idxs_by_zone_prd"
    cache = getattr(mod, cache_attr, None)
    if cache is None:
        cache = {}
        for idx in getattr(mod, source.zone_tmps_set(policy)):
            key = (idx[source.zone_position], mod.period[idx[-1]])
            cache.setdefault(key, []).append(idx)
        setattr(mod, cache_attr, cache)
    return cache


def tmp_energy_weight(mod, tmp):
    return mod.hrs_in_tmp[tmp] * mod.tmp_weight[tmp]


# Source aggregation (one module per policy and source)
###############################################################################


def generic_add_source_aggregation_components(m, d, policy, source):
    """
    Zone-period expressions of the source's gross import emissions and of
    its signed emissions (imports less export credits; zero in gross zones),
    registered with the policy's import-emissions lists.
    """

    def total_import_emissions_rule(mod, z, p):
        return sum(
            source.import_emissions_tons(mod, policy, idx)
            * tmp_energy_weight(mod, idx[-1])
            for idx in indices_by_zone_period(mod, policy, source).get((z, p), [])
        )

    gross_name = f"Total_{source.label}_{policy.component_prefix}_Import_Emissions_Tons"
    setattr(
        m,
        gross_name,
        Expression(
            getattr(m, policy.zone_periods_set), rule=total_import_emissions_rule
        ),
    )

    def total_signed_import_emissions_rule(mod, z, p):
        if not is_net_zone(mod, policy, z):
            return 0
        return sum(
            source.signed_import_emissions_tons(mod, policy, idx)
            * tmp_energy_weight(mod, idx[-1])
            for idx in indices_by_zone_period(mod, policy, source).get((z, p), [])
        )

    signed_name = (
        f"Total_{source.label}_{policy.component_prefix}"
        f"_Signed_Import_Emissions_Tons"
    )
    setattr(
        m,
        signed_name,
        Expression(
            getattr(m, policy.zone_periods_set),
            rule=total_signed_import_emissions_rule,
        ),
    )

    getattr(d, policy.import_emission_components).append(gross_name)
    getattr(d, policy.signed_import_emission_components).append(signed_name)


def generic_export_source_aggregation_results(m, d, policy, source):
    """
    Add the source's zone-period import emissions (the model value and the
    value recomputed from the solved flows) and realized export credits to
    the policy's zone-period results dataframe.
    """
    gross_name = f"Total_{source.label}_{policy.component_prefix}_Import_Emissions_Tons"
    prefix = source.results_prefix
    results_columns = [
        f"{prefix}_emissions",
        f"{prefix}_emissions_degen",
        f"{prefix.replace('import', 'export')}_credits",
    ]
    data = []
    for z, p in getattr(m, policy.zone_periods_set):
        idxs = indices_by_zone_period(m, policy, source).get((z, p), [])
        data.append(
            [
                z,
                p,
                value(getattr(m, gross_name)[z, p]),
                sum(
                    source.realized_import_emissions_tons(m, policy, idx)
                    * tmp_energy_weight(m, idx[-1])
                    for idx in idxs
                ),
                sum(
                    source.realized_export_credits_tons(m, policy, idx)
                    * tmp_energy_weight(m, idx[-1])
                    for idx in idxs
                ),
            ]
        )
    results_df = create_results_df(
        index_columns=[policy.zone_column, "period"],
        results_columns=results_columns,
        data=data,
    )
    update_results_df(getattr(d, policy.zone_prd_df), results_df)


# Combination per zone basis (one module per policy)
###############################################################################


def generic_add_import_emissions_components(m, d, policy):
    """
    The zone-period import emissions that enter the policy:
    :code:`Total_<Policy>_Import_Emissions_Tons` is the sum of the sources'
    gross emissions in gross zones and the non-negative variable
    :code:`Net_<Policy>_Import_Emissions_Tons`, bounded below by the sum of
    the sources' signed emissions, in net zones.
    """
    net_zone_periods = f"NET_PRD_{policy.set_prefix}_ZONE_PERIODS"
    setattr(
        m,
        net_zone_periods,
        Set(
            dimen=2,
            initialize=lambda mod: [
                (z, p)
                for (z, p) in getattr(mod, policy.zone_periods_set)
                if is_net_zone(mod, policy, z)
            ],
        ),
    )

    net_var = f"Net_{policy.component_prefix}_Import_Emissions_Tons"
    setattr(m, net_var, Var(getattr(m, net_zone_periods), within=NonNegativeReals))

    def net_import_emissions_rule(mod, z, p):
        return getattr(mod, net_var)[z, p] >= sum(
            getattr(mod, component)[z, p]
            for component in getattr(d, policy.signed_import_emission_components)
        )

    setattr(
        m,
        f"Net_{policy.component_prefix}_Import_Emissions_Constraint",
        Constraint(getattr(m, net_zone_periods), rule=net_import_emissions_rule),
    )

    def total_import_emissions_rule(mod, z, p):
        if is_net_zone(mod, policy, z):
            return getattr(mod, net_var)[z, p]
        else:
            return sum(
                getattr(mod, component)[z, p]
                for component in getattr(d, policy.import_emission_components)
            )

    setattr(
        m,
        f"Total_{policy.component_prefix}_Import_Emissions_Tons",
        Expression(
            getattr(m, policy.zone_periods_set), rule=total_import_emissions_rule
        ),
    )


def generic_export_import_emissions_results(m, d, policy):
    """
    Add the zone's basis and its total import emissions, as the model
    counted them and as recomputed from the solved flows, to the policy's
    zone-period results dataframe. Runs after the source aggregation modules
    have written their columns; a source that is not in the model
    contributes nothing.
    """
    df = getattr(d, policy.zone_prd_df)
    results_columns = [
        "import_emissions_basis",
        "total_import_emissions",
        "total_import_emissions_degen",
    ]
    data = []
    for z, p in getattr(m, policy.zone_periods_set):
        realized_imports = 0
        realized_credits = 0
        for prefix in ["import", "market_import"]:
            degen_col = f"{prefix}_emissions_degen"
            credits_col = f"{prefix.replace('import', 'export')}_credits"
            if degen_col in df.columns:
                realized_imports += df.loc[(z, p), degen_col]
                realized_credits += df.loc[(z, p), credits_col]
        if is_net_zone(m, policy, z):
            realized_total = max(realized_imports - realized_credits, 0)
        else:
            realized_total = realized_imports
        data.append(
            [
                z,
                p,
                zone_basis(m, policy, z),
                value(
                    getattr(
                        m, f"Total_{policy.component_prefix}_Import_Emissions_Tons"
                    )[z, p]
                ),
                realized_total,
            ]
        )
    results_df = create_results_df(
        index_columns=[policy.zone_column, "period"],
        results_columns=results_columns,
        data=data,
    )
    update_results_df(df, results_df)


# Validation helpers shared by the sources
###############################################################################


def validate_export_intensities(zones_df, basis_by_zone, tmp_df, idx_cols, zone_col):
    """
    Error messages for rows of a net-basis zone whose export intensity
    exceeds the import intensity, flat or in any timepoint.

    :param zones_df: the zone assignments with ``import_intensity``,
        ``export_intensity`` and ``tmp_import_emissions_scenario_id``
    :param basis_by_zone: dict zone -> basis
    :param tmp_df: the timepoint adders with ``import_intensity_hourly`` and
        ``export_intensity_hourly``, keyed by the entity column(s) and
        ``tmp_import_emissions_scenario_id``
    :param idx_cols: the entity column(s), e.g. ``["transmission_line"]``
    :param zone_col: the zone column
    """
    errors = []
    net_rows = zones_df[zones_df[zone_col].map(basis_by_zone) == "net_prd"]
    if net_rows.empty:
        return errors

    def label(row):
        return "-".join(str(row[c]) for c in idx_cols + [zone_col])

    flat_bad = net_rows[net_rows["export_intensity"] > net_rows["import_intensity"]]
    for _, row in flat_bad.iterrows():
        errors.append(
            f"{label(row)}: export intensity exceeds import intensity; "
            "exports may not be credited at more than imports are charged."
        )

    # Only rows with a profile have hourly adders; the id is read as object
    # dtype when some rows have none
    with_profile = net_rows.dropna(subset=["tmp_import_emissions_scenario_id"])
    if tmp_df.empty or with_profile.empty:
        return errors
    with_profile = with_profile.astype({"tmp_import_emissions_scenario_id": int})
    merged = with_profile.merge(
        tmp_df.astype({"tmp_import_emissions_scenario_id": int}),
        on=idx_cols + ["tmp_import_emissions_scenario_id"],
        how="inner",
    )
    hourly_bad = merged[
        merged["export_intensity"] + merged["export_intensity_hourly"]
        > merged["import_intensity"] + merged["import_intensity_hourly"]
    ]
    for key, group in hourly_bad.groupby(idx_cols + [zone_col]):
        errors.append(
            f"{'-'.join(str(k) for k in key)}: export intensity exceeds import "
            f"intensity in timepoint(s) {sorted(group['timepoint'].unique())}."
        )
    return errors


def validate_single_profile_per_entity(zones_df, idx_cols):
    """
    Error messages for entities whose zone rows reference different timepoint
    intensity profiles; the profile is a property of the entity.
    """
    counts = zones_df.groupby(idx_cols)["tmp_import_emissions_scenario_id"].nunique(
        dropna=False
    )
    return [
        f"{'-'.join(str(k) for k in (key if isinstance(key, tuple) else (key,)))}: "
        "all zone rows of an entity must reference the same "
        "tmp_import_emissions_scenario_id."
        for key, count in counts.items()
        if count > 1
    ]
