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
Emissions imported into a policy zone over transmission lines and through
market purchases.

Each *source* (transmission lines, markets) assigns its entities to zones with
an import intensity and an export intensity, builds the per-timepoint import
variables, and reports per-timepoint results. The source aggregation modules
in :code:`system.policy.<policy>` sum each source into expressions, over the
indices the policy is enforced on (a zone and a period for the carbon cap and
carbon tax), of its *gross* import emissions and of its *signed* emissions
(imports less export credits). The policy's import-emissions module combines
the sources per the zone's *import-emissions basis*:

* ``gross``: every imported MWh counts at its import intensity and exports
  earn nothing; the sources' gross totals enter the policy directly.
* ``net_prd``: exports earn a credit at their export intensity and the zone's
  net import emissions are floored at zero over each enforcement index.

Under ``net_prd`` the signed emissions of an entity in a timepoint are
:math:`(I_{imp} - I_{exp}) \\cdot F^{+} + I_{exp} \\cdot f`, with :math:`f`
the flow into the zone (negative for exports) and :math:`F^{+} \\geq f`,
:math:`F^{+} \\geq 0` the imported MW variable; this is linear and exact as
long as :math:`I_{imp} \\geq I_{exp}`, which the inputs validation enforces.
With a zero export intensity, ``net_prd`` reproduces ``gross`` exactly.

This module holds the policy descriptors and the generic model and results
code the policy-specific modules call. A policy is described by the columns
that identify one of its zones (one column for the carbon cap and carbon tax)
and by the temporal index it is enforced over (the period for both), so the
same code serves policies with composite zone keys or horizon-level
enforcement.
"""

from pyomo.environ import Constraint, Expression, NonNegativeReals, Set, Var, value

from gridpath.auxiliary.dynamic_components import (
    carbon_cap_import_emission_components,
    carbon_cap_signed_import_emission_components,
    carbon_tax_import_emission_components,
    carbon_tax_signed_import_emission_components,
    policy_import_emission_components,
    policy_signed_import_emission_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.carbon_cap import CARBON_CAP_ZONE_PRD_DF
from gridpath.system.policy.carbon_tax import CARBON_TAX_ZONE_PRD_DF
from gridpath.system.policy.generic_policy import POLICY_ZONE_PRD_DF

GROSS = "gross"
NET_PRD = "net_prd"
IMPORT_EMISSIONS_BASES = [GROSS, NET_PRD]

IMPORT_DIRECTIONS = ["positive", "negative"]

# The generic policy's compliance type whose rows carry import emissions
IMPORT_EMISSIONS_COMPLIANCE_TYPE = "import_emissions"


def period_keys(mod, tmp):
    """
    The temporal keys of a period-enforced policy: the timepoint's period.
    """
    return [(mod.period[tmp],)]


def horizon_keys(mod, tmp):
    """
    The temporal keys of a horizon-enforced policy: the timepoint's horizon
    under each balancing type.
    """
    return [(bt, mod.horizon[tmp, bt]) for bt in mod.BLN_TYPES]


class ImportEmissionsPolicy(object):
    """
    The names a policy's import-emissions components are built from, so the
    carbon cap and the carbon tax share one implementation.

    A policy's *zone* is identified by ``zone_columns`` (one or more columns
    in the inputs tables and .tab files; zone keys are tuples of that length
    throughout this code). The policy is enforced over the elements of
    ``requirement_set``: a zone key followed by a temporal key, whose columns
    are ``requirement_columns`` and which ``requirement_keys(mod, tmp)`` maps
    a timepoint to (one or more keys, e.g. the timepoint's horizon under each
    balancing type).
    """

    def __init__(
        self,
        name,
        zone_columns,
        zones_set,
        requirement_set,
        requirement_columns,
        requirement_keys,
        zone_subscenario_attr,
        results_df,
        import_emission_components,
        signed_import_emission_components,
        rows_filter_sql="",
        zones_file_tag="zones",
        validate_rows=None,
    ):
        # 'carbon_cap' / 'carbon_tax' / 'policy'
        self.name = name
        # 'Carbon_Cap' / 'Carbon_Tax', for Var/Expression/Constraint names
        self.component_prefix = name.title()
        # 'CARBON_CAP' / 'CARBON_TAX', for Set names
        self.set_prefix = name.upper()
        # the zone column(s) in the inputs tables and .tab files
        self.zone_columns = list(zone_columns)
        self.zone_dimen = len(self.zone_columns)
        self.zones_set = zones_set
        # the set the policy is enforced over: (zone..., temporal...) tuples
        self.requirement_set = requirement_set
        self.requirement_columns = list(requirement_columns)
        self.requirement_keys = requirement_keys
        self.basis_param = f"{name}_import_emissions_basis"
        self.zone_subscenario_attr = zone_subscenario_attr
        # the results dataframe indexed by the requirement set's columns
        self.results_df = results_df
        self.import_emission_components = import_emission_components
        self.signed_import_emission_components = signed_import_emission_components
        # an extra SQL filter on the sources' mapping tables, e.g. to keep
        # only the rows of one compliance type
        self.rows_filter_sql = rows_filter_sql
        # the tag in the sources' .tab file names (<source>_<name>_<tag>.tab),
        # so the import mappings do not collide with another .tab of the
        # policy's source mappings
        self.zones_file_tag = zones_file_tag
        # optional extra validation of the mapping rows:
        # (cursor, subscenarios, df, entity_columns, policy) -> error messages
        self.validate_rows = validate_rows

    @property
    def index_columns(self):
        """
        The columns of the requirement set's elements.
        """
        return self.zone_columns + self.requirement_columns

    def zone_of(self, requirement_idx):
        """
        The zone key of a requirement set element.
        """
        return tuple(requirement_idx[: self.zone_dimen])


CARBON_CAP = ImportEmissionsPolicy(
    name="carbon_cap",
    zone_columns=["carbon_cap_zone"],
    zones_set="CARBON_CAP_ZONES",
    requirement_set="CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP",
    requirement_columns=["period"],
    requirement_keys=period_keys,
    zone_subscenario_attr="CARBON_CAP_ZONE_SCENARIO_ID",
    results_df=CARBON_CAP_ZONE_PRD_DF,
    import_emission_components=carbon_cap_import_emission_components,
    signed_import_emission_components=carbon_cap_signed_import_emission_components,
)

CARBON_TAX = ImportEmissionsPolicy(
    name="carbon_tax",
    zone_columns=["carbon_tax_zone"],
    zones_set="CARBON_TAX_ZONES",
    requirement_set="CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX",
    requirement_columns=["period"],
    requirement_keys=period_keys,
    zone_subscenario_attr="CARBON_TAX_ZONE_SCENARIO_ID",
    results_df=CARBON_TAX_ZONE_PRD_DF,
    import_emission_components=carbon_tax_import_emission_components,
    signed_import_emission_components=carbon_tax_signed_import_emission_components,
)


def validate_import_rows_in_max_policies(c, subscenarios, df, idx_cols, policy):
    """
    Error messages for import-emissions mapping rows of a policy zone with a
    ``min`` horizon requirement or a month-hour requirement: the imported
    power variables are bounded from below only, so import emissions can be
    counted exactly only where the policy pushes them down, i.e. toward a
    ``max`` requirement.
    """
    min_zones = set(c.execute(f"""
            SELECT DISTINCT policy_name, policy_zone
            FROM inputs_system_policy_requirements
            WHERE policy_requirement_scenario_id =
                {subscenarios.POLICY_REQUIREMENT_SCENARIO_ID}
            AND COALESCE(policy_requirement_sense, 'min') = 'min'
            UNION
            SELECT DISTINCT policy_name, policy_zone
            FROM inputs_system_policy_month_hour_requirements
            WHERE policy_requirement_scenario_id =
                {subscenarios.POLICY_REQUIREMENT_SCENARIO_ID}
            """).fetchall())
    bad = df[zone_tuples(df, policy).isin(min_zones)]
    if bad.empty:
        return []
    label_cols = idx_cols + policy.zone_columns
    labels = ", ".join(
        "-".join(str(row[col]) for col in label_cols) for _, row in bad.iterrows()
    )
    return [
        f"{'-'.join(label_cols)}(s) '{labels}': import emissions can only count "
        "toward policies with 'max' horizon requirements (the imported power "
        "variables are exact only where the policy pushes them down)."
    ]


POLICY = ImportEmissionsPolicy(
    name="policy",
    zone_columns=["policy_name", "policy_zone"],
    zones_set="POLICIES_ZONES",
    requirement_set="POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ",
    requirement_columns=["balancing_type_horizon", "horizon"],
    requirement_keys=horizon_keys,
    zone_subscenario_attr="POLICY_ZONE_SCENARIO_ID",
    results_df=POLICY_ZONE_PRD_DF,
    import_emission_components=policy_import_emission_components,
    signed_import_emission_components=policy_signed_import_emission_components,
    rows_filter_sql=f"AND compliance_type = '{IMPORT_EMISSIONS_COMPLIANCE_TYPE}'",
    zones_file_tag=IMPORT_EMISSIONS_COMPLIANCE_TYPE,
    validate_rows=validate_import_rows_in_max_policies,
)


class ImportEmissionsSource(object):
    """
    What the aggregation code needs to know about a source of imports
    (transmission lines or markets). The per-index functions take
    :code:`(mod, policy, index_tuple)` where the tuple is an element of the
    source's (entity..., zone..., timepoint) set; :code:`split_index` takes
    such a tuple apart.
    """

    def __init__(
        self,
        label,
        results_prefix,
        zone_tmps_set,
        entity_dimen,
        import_emissions_tons,
        signed_import_emissions_tons,
        realized_import_emissions_tons,
        realized_export_credits_tons,
    ):
        # 'Tx' / 'Market', for component names
        self.label = label
        # 'import' / 'market_import', for the aggregated results columns
        self.results_prefix = results_prefix
        # function of policy returning the (entity..., zone..., timepoint)
        # set name
        self.zone_tmps_set = zone_tmps_set
        # number of entity elements at the front of that set's tuples
        self.entity_dimen = entity_dimen
        self.import_emissions_tons = import_emissions_tons
        self.signed_import_emissions_tons = signed_import_emissions_tons
        self.realized_import_emissions_tons = realized_import_emissions_tons
        self.realized_export_credits_tons = realized_export_credits_tons


# Index helpers
###############################################################################


def split_index(source, idx):
    """
    An (entity..., zone..., timepoint) tuple of the source as its entity
    tuple, its zone tuple and its timepoint.
    """
    n = source.entity_dimen
    return tuple(idx[:n]), tuple(idx[n:-1]), idx[-1]


def zone_basis(mod, policy, zone):
    return getattr(mod, policy.basis_param)[zone]


def is_net_zone(mod, policy, zone):
    return zone_basis(mod, policy, zone) == NET_PRD


def indices_by_requirement(mod, policy, source):
    """
    The source's (entity..., zone..., timepoint) tuples grouped by the
    policy's requirement index (zone..., temporal...), built in one pass over
    the set the first time it is asked for and cached on the model instance.
    """
    cache_attr = f"_gridpath_{policy.name}_{source.label.lower()}_idxs_by_req"
    cache = getattr(mod, cache_attr, None)
    if cache is None:
        cache = {}
        for idx in getattr(mod, source.zone_tmps_set(policy)):
            _entity, zone, tmp = split_index(source, idx)
            for temporal_key in policy.requirement_keys(mod, tmp):
                cache.setdefault(zone + tuple(temporal_key), []).append(idx)
        setattr(mod, cache_attr, cache)
    return cache


def tmp_energy_weight(mod, tmp):
    return mod.hrs_in_tmp[tmp] * mod.tmp_weight[tmp]


# Source aggregation (one module per policy and source)
###############################################################################


def generic_add_source_aggregation_components(m, d, policy, source):
    """
    Expressions, over the policy's requirement set, of the source's gross
    import emissions and of its signed emissions (imports less export
    credits; zero in gross zones), registered with the policy's
    import-emissions lists.
    """

    def total_import_emissions_rule(mod, *idx):
        return sum(
            source.import_emissions_tons(mod, policy, source_idx)
            * tmp_energy_weight(mod, source_idx[-1])
            for source_idx in indices_by_requirement(mod, policy, source).get(idx, [])
        )

    gross_name = f"Total_{source.label}_{policy.component_prefix}_Import_Emissions_Tons"
    setattr(
        m,
        gross_name,
        Expression(
            getattr(m, policy.requirement_set), rule=total_import_emissions_rule
        ),
    )

    def total_signed_import_emissions_rule(mod, *idx):
        if not is_net_zone(mod, policy, policy.zone_of(idx)):
            return 0
        return sum(
            source.signed_import_emissions_tons(mod, policy, source_idx)
            * tmp_energy_weight(mod, source_idx[-1])
            for source_idx in indices_by_requirement(mod, policy, source).get(idx, [])
        )

    signed_name = (
        f"Total_{source.label}_{policy.component_prefix}"
        f"_Signed_Import_Emissions_Tons"
    )
    setattr(
        m,
        signed_name,
        Expression(
            getattr(m, policy.requirement_set),
            rule=total_signed_import_emissions_rule,
        ),
    )

    getattr(d, policy.import_emission_components).append(gross_name)
    getattr(d, policy.signed_import_emission_components).append(signed_name)


def generic_export_source_aggregation_results(m, d, policy, source):
    """
    Add the source's import emissions per requirement index (the model value
    and the value recomputed from the solved flows) and realized export
    credits to the policy's results dataframe.
    """
    gross_name = f"Total_{source.label}_{policy.component_prefix}_Import_Emissions_Tons"
    prefix = source.results_prefix
    results_columns = [
        f"{prefix}_emissions",
        f"{prefix}_emissions_degen",
        f"{prefix.replace('import', 'export')}_credits",
    ]
    data = []
    for idx in getattr(m, policy.requirement_set):
        idx = tuple(idx)
        source_idxs = indices_by_requirement(m, policy, source).get(idx, [])
        data.append(
            [
                *idx,
                value(getattr(m, gross_name)[idx]),
                sum(
                    source.realized_import_emissions_tons(m, policy, source_idx)
                    * tmp_energy_weight(m, source_idx[-1])
                    for source_idx in source_idxs
                ),
                sum(
                    source.realized_export_credits_tons(m, policy, source_idx)
                    * tmp_energy_weight(m, source_idx[-1])
                    for source_idx in source_idxs
                ),
            ]
        )
    results_df = create_results_df(
        index_columns=policy.index_columns,
        results_columns=results_columns,
        data=data,
    )
    update_results_df(getattr(d, policy.results_df), results_df)


# Combination per zone basis (one module per policy)
###############################################################################


def generic_add_import_emissions_components(m, d, policy):
    """
    The import emissions that enter the policy at each requirement index:
    :code:`Total_<Policy>_Import_Emissions_Tons` is the sum of the sources'
    gross emissions in gross zones and the non-negative variable
    :code:`Net_<Policy>_Import_Emissions_Tons`, bounded below by the sum of
    the sources' signed emissions, in net zones.
    """
    requirement_set = getattr(m, policy.requirement_set)
    net_requirement_idxs = f"NET_PRD_{policy.set_prefix}_ZONE_PERIODS"
    setattr(
        m,
        net_requirement_idxs,
        Set(
            dimen=requirement_set.dimen,
            initialize=lambda mod: [
                idx
                for idx in getattr(mod, policy.requirement_set)
                if is_net_zone(mod, policy, policy.zone_of(idx))
            ],
        ),
    )

    net_var = f"Net_{policy.component_prefix}_Import_Emissions_Tons"
    setattr(m, net_var, Var(getattr(m, net_requirement_idxs), within=NonNegativeReals))

    def net_import_emissions_rule(mod, *idx):
        return getattr(mod, net_var)[idx] >= sum(
            getattr(mod, component)[idx]
            for component in getattr(d, policy.signed_import_emission_components)
        )

    setattr(
        m,
        f"Net_{policy.component_prefix}_Import_Emissions_Constraint",
        Constraint(getattr(m, net_requirement_idxs), rule=net_import_emissions_rule),
    )

    def total_import_emissions_rule(mod, *idx):
        if is_net_zone(mod, policy, policy.zone_of(idx)):
            return getattr(mod, net_var)[idx]
        else:
            return sum(
                getattr(mod, component)[idx]
                for component in getattr(d, policy.import_emission_components)
            )

    setattr(
        m,
        f"Total_{policy.component_prefix}_Import_Emissions_Tons",
        Expression(requirement_set, rule=total_import_emissions_rule),
    )


def generic_export_import_emissions_results(m, d, policy):
    """
    Add the zone's basis and its total import emissions, as the model
    counted them and as recomputed from the solved flows, to the policy's
    results dataframe. Runs after the source aggregation modules have written
    their columns; a source that is not in the model contributes nothing.
    """
    df = getattr(d, policy.results_df)
    results_columns = [
        "import_emissions_basis",
        "total_import_emissions",
        "total_import_emissions_degen",
    ]
    data = []
    for idx in getattr(m, policy.requirement_set):
        idx = tuple(idx)
        zone = policy.zone_of(idx)
        realized_imports = 0
        realized_credits = 0
        for prefix in ["import", "market_import"]:
            degen_col = f"{prefix}_emissions_degen"
            credits_col = f"{prefix.replace('import', 'export')}_credits"
            if degen_col in df.columns:
                realized_imports += df.loc[idx, degen_col]
                realized_credits += df.loc[idx, credits_col]
        if is_net_zone(m, policy, zone):
            realized_total = max(realized_imports - realized_credits, 0)
        else:
            realized_total = realized_imports
        data.append(
            [
                *idx,
                zone_basis(m, policy, zone),
                value(
                    getattr(
                        m, f"Total_{policy.component_prefix}_Import_Emissions_Tons"
                    )[idx]
                ),
                realized_total,
            ]
        )
    results_df = create_results_df(
        index_columns=policy.index_columns,
        results_columns=results_columns,
        data=data,
    )
    update_results_df(df, results_df)


# Database and validation helpers shared by the sources
###############################################################################


def zone_scope_sql(subscenarios, policy):
    """
    A SQL filter clause keeping rows whose zone is in the scenario's zone
    subscenario.
    """
    zone_cols = ", ".join(policy.zone_columns)
    return f"""
        AND ({zone_cols}) IN (
            SELECT {zone_cols}
            FROM inputs_geography_{policy.name}_zones
            WHERE {policy.name}_zone_scenario_id =
                {getattr(subscenarios, policy.zone_subscenario_attr)}
        )
        """


def get_basis_by_zone(c, subscenarios, policy):
    """
    The import-emissions basis of each of the scenario's zones, keyed by the
    zone tuple.
    """
    zone_cols = ", ".join(policy.zone_columns)
    rows = c.execute(f"""
        SELECT {zone_cols}, COALESCE(import_emissions_basis, '{GROSS}')
        FROM inputs_geography_{policy.name}_zones
        WHERE {policy.name}_zone_scenario_id =
            {getattr(subscenarios, policy.zone_subscenario_attr)}
        """).fetchall()
    return {tuple(row[:-1]): row[-1] for row in rows}


def zone_tuples(df, policy):
    """
    The zone key of each row of a dataframe with the policy's zone columns.
    """
    return df[policy.zone_columns].apply(tuple, axis=1)


def validate_zones(df, basis_by_zone, idx_cols, policy):
    """
    Error messages for rows assigned to a zone that is not among the
    scenario's zones.
    """
    unknown = df[~zone_tuples(df, policy).isin(basis_by_zone.keys())]
    if unknown.empty:
        return []
    label_cols = idx_cols + policy.zone_columns
    labels = ", ".join(
        "-".join(str(row[c]) for c in label_cols) for _, row in unknown.iterrows()
    )
    return [
        f"{'-'.join(label_cols)}(s) '{labels}': zone not in the scenario's "
        f"zones {sorted(basis_by_zone.keys())}."
    ]


def validate_export_intensities(zones_df, basis_by_zone, tmp_df, idx_cols, policy):
    """
    Error messages for rows of a net-basis zone whose export intensity
    exceeds the import intensity, flat or in any timepoint.

    :param zones_df: the zone assignments with ``import_intensity``,
        ``export_intensity`` and ``tmp_import_emissions_scenario_id``
    :param basis_by_zone: dict zone tuple -> basis
    :param tmp_df: the timepoint adders with ``import_intensity_hourly`` and
        ``export_intensity_hourly``, keyed by the entity column(s) and
        ``tmp_import_emissions_scenario_id``
    :param idx_cols: the entity column(s), e.g. ``["transmission_line"]``
    :param policy: the policy, for its zone columns
    """
    errors = []
    zone_cols = policy.zone_columns
    net_rows = zones_df[zone_tuples(zones_df, policy).map(basis_by_zone) == NET_PRD]
    if net_rows.empty:
        return errors

    def label(row):
        return "-".join(str(row[c]) for c in idx_cols + zone_cols)

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
    for key, group in hourly_bad.groupby(idx_cols + zone_cols):
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
