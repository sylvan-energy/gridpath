# Copyright 2016-2025 Blue Marble Analytics LLC.
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
Limits on how much a scenario may transact in the markets it participates in.

A limit applies to a **market group**. A group of one limits a single market,
a group of all the scenario's markets is a system-wide limit, and a group of
some of them, e.g. all the hubs of one region, is a limit on that region's
transactions. Groups may overlap, so a market can be limited on its own and
as part of a wider total at the same time.

A market's position in a timepoint is its net power purchased, summed over
the load zones participating in it: its purchases when positive, its sales
when negative. The *final* position is the same quantity including the
transactions carried over from the previous stages.

**Net and gross limits.** Each limit row has a *basis* saying what it caps:

* ``net`` caps the group's net position, the sum of its markets' positions,
  so a purchase in one market offsets a sale in another.
* ``gross`` caps the group's total sales and total purchases separately,
  each market counted without offsetting: the sales limit caps the sum of
  the sales of the markets that are selling, whatever the others buy.

For a group of one market the two are the same. A group may carry a row of
each basis, each with its own profiles and flat limits, e.g. a gross cap on
hourly sales and a net cap on annual exports. Gross limits split each of the
group's markets' positions into non-negative sales and purchases variables
bounded below by the position; capping their sum is exact and keeps the
problem linear.

Limits come at three temporal resolutions. The timepoint-level limits are in
MW and apply to the position in the timepoint. The horizon- and period-level
limits are in MWh and apply to the position summed over the timepoints of the
horizon or period, each weighted by its number of hours and its timepoint
weight. Horizon-level limits follow a balancing type the user picks, so a
limit can be imposed over any horizon defined in the scenario's temporal
structure (a day, a week, a month, ...).

+------------+------------------------------+------+
| Resolution | Limits                       | Unit |
+============+==============================+======+
| Timepoint  | sales, purchases             | MW   |
+------------+------------------------------+------+
| Timepoint  | final sales, final purchases | MW   |
+------------+------------------------------+------+
| Horizon    | sales, purchases             | MWh  |
+------------+------------------------------+------+
| Period     | sales, purchases             | MWh  |
+------------+------------------------------+------+

A limit that is not specified defaults to infinity, i.e. it is not enforced
and no constraint is built for it.

The horizon- and period-level sales limits can optionally count the energy
the system's storage loses against the limit, i.e. cap sales plus storage
losses rather than sales alone. The losses are those of the projects of the
*stor* operational type, the energy they charge less the energy they
discharge, and are system-wide, not group-specific.

**Every market is a group of its own.** A market is implicitly a group
containing just that market, named after it, so limiting a single market
takes no group definition at all: name the market in the volume subscenario
and it is limited on its own. Only groups of more than one market have to be
listed, and a scenario that needs none can leave its market group
subscenario unset.

A group may therefore not be named after a market unless it contains that
market alone, which would merge the two silently; this is a validation error.

**Groups and the scenario's markets.** A group is narrowed to the markets of
the scenario's market subscenario, so one group definition serves scenarios
with different market sets: a group of every hub in the interconnection
limits whichever of them a given scenario models, and a group left with none
of them contributes no constraints. This is the same scoping that lets one
market volume subscenario serve scenarios with different market sets.

**Flat limits and default rows.** A limit that does not vary need not be
written out per timepoint or period. Two shortcuts exist, and they stack.

The group's row in the market volume subscenario carries flat timepoint- and
period-level limits (the ``default_*`` columns), applied in every timepoint
or period, stage and iteration, so a flat limit needs no profile at all. A
horizon-level limit needs a balancing type and so has no flat form.

Every limit profile also accepts a wildcard row that supplies the default for
the rest of the profile: the row whose temporal index is 0, i.e.
``timepoint = 0``, ``horizon = 0`` (a separate default per balancing type) or
``period = 0``. Unlike the flat limit it is keyed by stage and iteration, so
it can default differently in each.

Resolution is per column and falls through in this order: an explicit row,
then the profile's wildcard row, then the group's flat limit, then infinity.
A cell left NULL at one layer falls through to the next, so a row that
overrides one limit need not repeat the others, and a flat limit combines
naturally with a profile that lists only the exceptions. To leave a single
timepoint unlimited when a finite default is in force, give it an explicitly
large value.

The layers are resolved when the model inputs are written, so the scenario's
input files carry the resolved limits and the model itself never sees a
default.
"""

import csv
import os.path

from pyomo.environ import (
    Boolean,
    Constraint,
    Expression,
    NonNegativeReals,
    Param,
    Set,
    Var,
    value,
)

from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.auxiliary.validations import write_validation_to_database
from gridpath.common_functions import constraint_dual, none_dual_type_error_wrapper
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)

Infinity = float("inf")

# The operational type whose losses may be added to the sales limits (see the
# include_storage_losses inputs)
STORAGE_LOSS_OPERATIONAL_TYPE = "stor"

# Cached on the model instance by lz_markets_in_group()
LZ_MARKETS_BY_GROUP_CACHE = "_gridpath_lz_markets_by_market_group"
LZ_MARKETS_BY_MARKET_CACHE = "_gridpath_lz_markets_by_market"

# What a limit row applies to: the group's net position, or its total sales
# and total purchases counted separately
NET = "net"
GROSS = "gross"
LIMIT_BASES = [NET, GROSS]


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
    """ """
    # Market groups: the markets each group contains, already narrowed to the
    # markets of this scenario
    m.MARKET_GROUP_MARKETS = Set(dimen=2)

    m.MARKET_GROUPS = Set(
        initialize=lambda mod: sorted(
            set(grp for (grp, mrkt) in mod.MARKET_GROUP_MARKETS)
        )
    )

    m.MARKETS_BY_MARKET_GROUP = Set(
        m.MARKET_GROUPS,
        within=m.MARKETS,
        initialize=lambda mod, group: [
            mrkt for (grp, mrkt) in mod.MARKET_GROUP_MARKETS if grp == group
        ],
    )

    m.MARKET_VOLUME_LIMIT_BASES = Set(initialize=LIMIT_BASES)

    # Limits by temporal resolution; each set holds only the group-basis-
    # index combinations a limit was specified for. The basis is 'net' (the
    # group's net position) or 'gross' (its total sales and total purchases,
    # counted separately)
    m.MARKET_GROUP_TMPS_W_LIMIT = Set(
        dimen=3, within=m.MARKET_GROUPS * m.MARKET_VOLUME_LIMIT_BASES * m.TMPS
    )
    m.max_market_sales = Param(
        m.MARKET_GROUP_TMPS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_market_purchases = Param(
        m.MARKET_GROUP_TMPS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_final_market_sales = Param(
        m.MARKET_GROUP_TMPS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_final_market_purchases = Param(
        m.MARKET_GROUP_TMPS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )

    m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT = Set(
        dimen=4, within=m.MARKET_GROUPS * m.MARKET_VOLUME_LIMIT_BASES * m.BLN_TYPE_HRZS
    )
    m.max_market_sales_in_hrz = Param(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_market_purchases_in_hrz = Param(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    # Based on 'stor' operational type
    m.max_market_sales_in_hrz_include_storage_losses = Param(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, within=Boolean, default=0
    )

    m.MARKET_GROUP_PRDS_W_LIMIT = Set(
        dimen=3, within=m.MARKET_GROUPS * m.MARKET_VOLUME_LIMIT_BASES * m.PERIODS
    )
    m.max_market_sales_in_prd = Param(
        m.MARKET_GROUP_PRDS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_market_purchases_in_prd = Param(
        m.MARKET_GROUP_PRDS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    # Based on 'stor' operational type
    m.max_market_sales_in_prd_include_storage_losses = Param(
        m.MARKET_GROUP_PRDS_W_LIMIT, within=Boolean, default=0
    )

    # The groups a limit was specified for at any resolution and basis; the
    # net position expressions are built for these only, so a scenario that
    # defines groups but limits none of them builds nothing
    m.MARKET_GROUPS_W_LIMITS = Set(
        within=m.MARKET_GROUPS,
        initialize=lambda mod: sorted(
            set(grp for (grp, basis, tmp) in mod.MARKET_GROUP_TMPS_W_LIMIT)
            | set(
                grp for (grp, basis, bt, hrz) in mod.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT
            )
            | set(grp for (grp, basis, prd) in mod.MARKET_GROUP_PRDS_W_LIMIT)
        ),
    )

    # The group-timepoints a timepoint-level limit of either basis applies
    # to; the final position is needed there only
    m.MARKET_GROUP_TMPS_W_ANY_LIMIT = Set(
        dimen=2,
        within=m.MARKET_GROUPS * m.TMPS,
        initialize=lambda mod: sorted(
            set((grp, tmp) for (grp, basis, tmp) in mod.MARKET_GROUP_TMPS_W_LIMIT)
        ),
    )

    # Gross limits need each market's position split into its sales and its
    # purchases. Build the split only for the market-timepoints a gross limit
    # covers, in one pass over the gross limit rows
    def gross_market_tmps_init(mod):
        market_tmps = set()
        for grp, basis, tmp in mod.MARKET_GROUP_TMPS_W_LIMIT:
            if basis == GROSS:
                market_tmps |= set(
                    (mrkt, tmp) for mrkt in mod.MARKETS_BY_MARKET_GROUP[grp]
                )
        for grp, basis, bt, hrz in mod.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT:
            if basis == GROSS:
                market_tmps |= set(
                    (mrkt, tmp)
                    for mrkt in mod.MARKETS_BY_MARKET_GROUP[grp]
                    for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
                )
        for grp, basis, prd in mod.MARKET_GROUP_PRDS_W_LIMIT:
            if basis == GROSS:
                market_tmps |= set(
                    (mrkt, tmp)
                    for mrkt in mod.MARKETS_BY_MARKET_GROUP[grp]
                    for tmp in mod.TMPS_IN_PRD[prd]
                )
        return sorted(market_tmps)

    m.GROSS_LIMIT_MARKET_TMPS = Set(dimen=2, initialize=gross_market_tmps_init)

    # Only the timepoint-level limits apply to the final position
    m.GROSS_FINAL_LIMIT_MARKET_TMPS = Set(
        dimen=2,
        initialize=lambda mod: sorted(
            set(
                (mrkt, tmp)
                for (grp, basis, tmp) in mod.MARKET_GROUP_TMPS_W_LIMIT
                if basis == GROSS
                for mrkt in mod.MARKETS_BY_MARKET_GROUP[grp]
            )
        ),
    )

    # The projects whose losses the include_storage_losses limits are based
    # on; collected once here rather than by rescanning PRJ_OPR_TMPS in every
    # horizon's and period's constraint
    m.MARKET_VOLUME_LIMIT_STOR_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: [
            prj
            for prj in mod.PROJECTS
            if mod.operational_type[prj] == STORAGE_LOSS_OPERATIONAL_TYPE
        ],
    )

    # A group's net position in the current stage, and the final position
    # given the previous stages' transactions
    def group_net_market_purchases_init(mod, group, tmp):
        return sum(
            mod.Net_Market_Purchased_Power[lz, mrkt, tmp]
            for (lz, mrkt) in lz_markets_in_group(mod, group)
        )

    m.Group_Net_Market_Purchased_Power = Expression(
        m.MARKET_GROUPS_W_LIMITS, m.TMPS, initialize=group_net_market_purchases_init
    )

    def group_final_net_market_purchases_init(mod, group, tmp):
        return sum(
            mod.Final_Net_Market_Purchased_Power[lz, mrkt, tmp]
            for (lz, mrkt) in lz_markets_in_group(mod, group)
        )

    m.Group_Final_Net_Market_Purchased_Power = Expression(
        m.MARKET_GROUP_TMPS_W_ANY_LIMIT,
        initialize=group_final_net_market_purchases_init,
    )

    # A market's sales and purchases, each at least the market's net sales
    # or net purchases and at least zero. A gross limit caps their sum over
    # the group's markets; since that cap is convex, the variables can always
    # sit at the positive parts of the net position, so the gross limit is
    # exact and the problem stays linear. The variables themselves are not
    # unique where no gross limit binds, so results report the positive parts
    # of the net position rather than the variables.
    m.Gross_Market_Sales = Var(m.GROSS_LIMIT_MARKET_TMPS, within=NonNegativeReals)
    m.Gross_Market_Purchases = Var(m.GROSS_LIMIT_MARKET_TMPS, within=NonNegativeReals)

    m.Gross_Market_Sales_Constraint = Constraint(
        m.GROSS_LIMIT_MARKET_TMPS,
        rule=lambda mod, mrkt, tmp: mod.Gross_Market_Sales[mrkt, tmp]
        >= -market_net_position(mod, mrkt, tmp, final=False),
    )
    m.Gross_Market_Purchases_Constraint = Constraint(
        m.GROSS_LIMIT_MARKET_TMPS,
        rule=lambda mod, mrkt, tmp: mod.Gross_Market_Purchases[mrkt, tmp]
        >= market_net_position(mod, mrkt, tmp, final=False),
    )

    m.Gross_Final_Market_Sales = Var(
        m.GROSS_FINAL_LIMIT_MARKET_TMPS, within=NonNegativeReals
    )
    m.Gross_Final_Market_Purchases = Var(
        m.GROSS_FINAL_LIMIT_MARKET_TMPS, within=NonNegativeReals
    )

    m.Gross_Final_Market_Sales_Constraint = Constraint(
        m.GROSS_FINAL_LIMIT_MARKET_TMPS,
        rule=lambda mod, mrkt, tmp: mod.Gross_Final_Market_Sales[mrkt, tmp]
        >= -market_net_position(mod, mrkt, tmp, final=True),
    )
    m.Gross_Final_Market_Purchases_Constraint = Constraint(
        m.GROSS_FINAL_LIMIT_MARKET_TMPS,
        rule=lambda mod, mrkt, tmp: mod.Gross_Final_Market_Purchases[mrkt, tmp]
        >= market_net_position(mod, mrkt, tmp, final=True),
    )

    # Timepoint-level limits. Each sales limit is written as "position >=
    # -limit" and each purchases limit as "position <= limit", where the
    # position is the net position on a net row and the negated total sales
    # or the total purchases on a gross row; net rows keep exactly the
    # constraints they had before gross limits existed.
    def max_market_sales_rule(mod, group, basis, tmp):
        if mod.max_market_sales[group, basis, tmp] == Infinity:
            return Constraint.Skip
        return (
            sales_position(mod, group, basis, tmp, final=False)
            >= -mod.max_market_sales[group, basis, tmp]
        )

    m.Max_Market_Group_Sales_Constraint = Constraint(
        m.MARKET_GROUP_TMPS_W_LIMIT, rule=max_market_sales_rule
    )

    def max_market_purchases_rule(mod, group, basis, tmp):
        if mod.max_market_purchases[group, basis, tmp] == Infinity:
            return Constraint.Skip
        return (
            purchases_position(mod, group, basis, tmp, final=False)
            <= mod.max_market_purchases[group, basis, tmp]
        )

    m.Max_Market_Group_Purchases_Constraint = Constraint(
        m.MARKET_GROUP_TMPS_W_LIMIT, rule=max_market_purchases_rule
    )

    def max_final_market_sales_rule(mod, group, basis, tmp):
        if mod.max_final_market_sales[group, basis, tmp] == Infinity:
            return Constraint.Skip
        return (
            sales_position(mod, group, basis, tmp, final=True)
            >= -mod.max_final_market_sales[group, basis, tmp]
        )

    m.Max_Market_Group_Final_Sales_Constraint = Constraint(
        m.MARKET_GROUP_TMPS_W_LIMIT, rule=max_final_market_sales_rule
    )

    def max_final_market_purchases_rule(mod, group, basis, tmp):
        if mod.max_final_market_purchases[group, basis, tmp] == Infinity:
            return Constraint.Skip
        return (
            purchases_position(mod, group, basis, tmp, final=True)
            <= mod.max_final_market_purchases[group, basis, tmp]
        )

    m.Max_Market_Group_Final_Purchases_Constraint = Constraint(
        m.MARKET_GROUP_TMPS_W_LIMIT, rule=max_final_market_purchases_rule
    )

    # Horizon-level limits
    def max_market_sales_in_hrz_rule(mod, group, basis, bt, hrz):
        if mod.max_market_sales_in_hrz[group, basis, bt, hrz] == Infinity:
            return Constraint.Skip
        tmps = mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        return sales_position_in_tmps(
            mod, group, basis, tmps
        ) >= -mod.max_market_sales_in_hrz[
            group, basis, bt, hrz
        ] + mod.max_market_sales_in_hrz_include_storage_losses[
            group, basis, bt, hrz
        ] * storage_losses_in_tmps(
            mod, tmps
        )

    m.Max_Market_Group_Sales_in_Hrz_Constraint = Constraint(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, rule=max_market_sales_in_hrz_rule
    )

    def max_market_purchases_in_hrz_rule(mod, group, basis, bt, hrz):
        if mod.max_market_purchases_in_hrz[group, basis, bt, hrz] == Infinity:
            return Constraint.Skip
        return (
            purchases_position_in_tmps(
                mod, group, basis, mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            <= mod.max_market_purchases_in_hrz[group, basis, bt, hrz]
        )

    m.Max_Market_Group_Purchases_in_Hrz_Constraint = Constraint(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, rule=max_market_purchases_in_hrz_rule
    )

    # Period-level limits
    def max_market_sales_in_prd_rule(mod, group, basis, prd):
        if mod.max_market_sales_in_prd[group, basis, prd] == Infinity:
            return Constraint.Skip
        tmps = mod.TMPS_IN_PRD[prd]
        return sales_position_in_tmps(
            mod, group, basis, tmps
        ) >= -mod.max_market_sales_in_prd[
            group, basis, prd
        ] + mod.max_market_sales_in_prd_include_storage_losses[
            group, basis, prd
        ] * storage_losses_in_tmps(
            mod, tmps
        )

    m.Max_Market_Group_Sales_in_Prd_Constraint = Constraint(
        m.MARKET_GROUP_PRDS_W_LIMIT, rule=max_market_sales_in_prd_rule
    )

    def max_market_purchases_in_prd_rule(mod, group, basis, prd):
        if mod.max_market_purchases_in_prd[group, basis, prd] == Infinity:
            return Constraint.Skip
        return (
            purchases_position_in_tmps(mod, group, basis, mod.TMPS_IN_PRD[prd])
            <= mod.max_market_purchases_in_prd[group, basis, prd]
        )

    m.Max_Market_Group_Purchases_in_Prd_Constraint = Constraint(
        m.MARKET_GROUP_PRDS_W_LIMIT, rule=max_market_purchases_in_prd_rule
    )


def sales_position(mod, group, basis, tmp, final):
    """
    The quantity a timepoint-level sales limit bounds from below by minus
    the limit: the group's net position on a net row, and its total sales,
    negated, on a gross row.
    """
    if basis == NET:
        return (
            mod.Group_Final_Net_Market_Purchased_Power[group, tmp]
            if final
            else mod.Group_Net_Market_Purchased_Power[group, tmp]
        )
    sales = mod.Gross_Final_Market_Sales if final else mod.Gross_Market_Sales
    return -sum(sales[mrkt, tmp] for mrkt in mod.MARKETS_BY_MARKET_GROUP[group])


def purchases_position(mod, group, basis, tmp, final):
    """
    The quantity a timepoint-level purchases limit bounds from above: the
    group's net position on a net row, and its total purchases on a gross
    row.
    """
    if basis == NET:
        return (
            mod.Group_Final_Net_Market_Purchased_Power[group, tmp]
            if final
            else mod.Group_Net_Market_Purchased_Power[group, tmp]
        )
    purchases = (
        mod.Gross_Final_Market_Purchases if final else mod.Gross_Market_Purchases
    )
    return sum(purchases[mrkt, tmp] for mrkt in mod.MARKETS_BY_MARKET_GROUP[group])


def sales_position_in_tmps(mod, group, basis, tmps):
    """
    :func:`sales_position` as energy in MWh over the timepoints *tmps*.
    """
    return sum(
        sales_position(mod, group, basis, tmp, final=False)
        * mod.hrs_in_tmp[tmp]
        * mod.tmp_weight[tmp]
        for tmp in tmps
    )


def purchases_position_in_tmps(mod, group, basis, tmps):
    """
    :func:`purchases_position` as energy in MWh over the timepoints *tmps*.
    """
    return sum(
        purchases_position(mod, group, basis, tmp, final=False)
        * mod.hrs_in_tmp[tmp]
        * mod.tmp_weight[tmp]
        for tmp in tmps
    )


def market_net_position(mod, market, tmp, final):
    """
    A single market's net purchased power in the timepoint, summed over the
    load zones participating in it; the final position if *final*.
    """
    power = (
        mod.Final_Net_Market_Purchased_Power
        if final
        else mod.Net_Market_Purchased_Power
    )
    return sum(power[lz, mrkt, tmp] for (lz, mrkt) in lz_markets_in_market(mod, market))


def lz_markets_in_market(mod, market):
    """
    The (load zone, market) pairs of *market*, built in one pass over
    LZ_MARKETS the first time it is asked for.
    """
    cache = getattr(mod, LZ_MARKETS_BY_MARKET_CACHE, None)
    if cache is None:
        cache = {}
        for lz, mrkt in mod.LZ_MARKETS:
            cache.setdefault(mrkt, []).append((lz, mrkt))
        setattr(mod, LZ_MARKETS_BY_MARKET_CACHE, cache)
    return cache.get(market, [])


def lz_markets_in_group(mod, group):
    """
    The (load zone, market) pairs that make up *group*'s position, built in
    one pass over LZ_MARKETS the first time it is asked for rather than
    rescanned in every index of every position expression.
    """
    cache = getattr(mod, LZ_MARKETS_BY_GROUP_CACHE, None)
    if cache is None:
        cache = {}
        for grp in mod.MARKET_GROUPS:
            markets = set(mod.MARKETS_BY_MARKET_GROUP[grp])
            cache[grp] = [
                (lz, mrkt) for (lz, mrkt) in mod.LZ_MARKETS if mrkt in markets
            ]
        setattr(mod, LZ_MARKETS_BY_GROUP_CACHE, cache)

    return cache[group]


def storage_losses_in_tmps(mod, tmps):
    """
    Net storage losses in MWh over the timepoints *tmps*, i.e. the energy
    charged less the energy discharged by the projects of the 'stor'
    operational type. System-wide, not specific to a market group.
    """
    return sum(
        (mod.Stor_Charge_MW[prj, tmp] - mod.Stor_Discharge_MW[prj, tmp])
        * mod.hrs_in_tmp[tmp]
        * mod.tmp_weight[tmp]
        for prj in mod.MARKET_VOLUME_LIMIT_STOR_PRJS
        for tmp in tmps
        if (prj, tmp) in mod.PRJ_OPR_TMPS
    )


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
    def input_file(fname):
        return os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            fname,
        )

    groups_filename = input_file("market_groups.tab")
    if os.path.exists(groups_filename):
        data_portal.load(filename=groups_filename, set=m.MARKET_GROUP_MARKETS)

    tmp_limits_filename = input_file("market_volume_tmp.tab")
    if os.path.exists(tmp_limits_filename):
        data_portal.load(
            filename=tmp_limits_filename,
            index=m.MARKET_GROUP_TMPS_W_LIMIT,
            param=(
                m.max_market_sales,
                m.max_market_purchases,
                m.max_final_market_sales,
                m.max_final_market_purchases,
            ),
        )

    hrz_limits_filename = input_file("market_volume_hrz.tab")
    if os.path.exists(hrz_limits_filename):
        data_portal.load(
            filename=hrz_limits_filename,
            index=m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT,
            param=(
                m.max_market_sales_in_hrz,
                m.max_market_purchases_in_hrz,
                m.max_market_sales_in_hrz_include_storage_losses,
            ),
        )

    prd_limits_filename = input_file("market_volume_prd.tab")
    if os.path.exists(prd_limits_filename):
        data_portal.load(
            filename=prd_limits_filename,
            index=m.MARKET_GROUP_PRDS_W_LIMIT,
            param=(
                m.max_market_sales_in_prd,
                m.max_market_purchases_in_prd,
                m.max_market_sales_in_prd_include_storage_losses,
            ),
        )


def limits_with_defaults_sql(
    index_subquery,
    data_subquery,
    value_columns,
    index_columns,
    match_columns,
    default_match_columns,
    wildcard_column,
    extra_select="",
    flat_values=None,
):
    """
    Build the SQL that resolves a limits table against a scenario's temporal
    index, applying the table's wildcard (default) rows and the group's flat
    limits.

    :param index_subquery: SQL selecting the scenario's temporal index (e.g.
        its timepoints), i.e. the rows the limits are resolved for
    :param data_subquery: SQL selecting the limits rows, carrying a
        ``{wildcard_filter}`` placeholder that this function fills in to
        select either the explicit rows or the single wildcard row; it must
        select *wildcard_column* along with *value_columns*
    :param value_columns: the limit columns, each emitted as
        COALESCE(explicit, wildcard)
    :param index_columns: the index columns to emit
    :param match_columns: the columns joining the index to the explicit rows
    :param default_match_columns: the columns joining the index to the
        wildcard row; empty for a table with a single table-wide wildcard
    :param wildcard_column: the temporal column whose value of 0 marks the
        wildcard row
    :param extra_select: literal columns to emit before the index columns
    :param flat_values: the group's flat limits, a value (or None) per entry
        of *value_columns*; the lowest layer of the fall-through, applied to
        every index entry
    :return: the SQL string

    An explicit row wins over the wildcard row, the wildcard row wins over
    the flat limit, and the flat limit wins over the model default of
    infinity. The COALESCE is per column, so a NULL cell in an explicit row
    falls through to the wildcard row and a NULL there to the flat limit.

    Index entries with neither an explicit nor a wildcard row are dropped,
    unless the group has a flat limit, in which case every entry gets one; so
    a group with no limits at this resolution contributes no rows and a
    scenario with no limits at all writes no file.
    """
    if flat_values is None:
        flat_values = {}
    select_index = ", ".join(f"idx.{c} AS {c}" for c in index_columns)
    select_values = ", ".join(
        f"COALESCE(explicit.{c}, wildcard.{c}, {sql_literal(flat_values.get(c))})"
        f" AS {c}"
        for c in value_columns
    )
    has_flat_limit = any(v is not None for v in flat_values.values())
    gate = (
        "1 = 1"
        if has_flat_limit
        else f"explicit.{wildcard_column} IS NOT NULL "
        f"OR wildcard.{wildcard_column} IS NOT NULL"
    )
    explicit_join = " AND ".join(f"idx.{c} = explicit.{c}" for c in match_columns)
    wildcard_join = (
        " AND ".join(f"idx.{c} = wildcard.{c}" for c in default_match_columns)
        if default_match_columns
        else "1 = 1"
    )

    return f"""
        SELECT {extra_select}{select_index}, {select_values}
        FROM ({index_subquery}) AS idx
        LEFT OUTER JOIN (
            {data_subquery.format(wildcard_filter=f"{wildcard_column} != 0")}
        ) AS explicit
            ON {explicit_join}
        LEFT OUTER JOIN (
            {data_subquery.format(wildcard_filter=f"{wildcard_column} = 0")}
        ) AS wildcard
            ON {wildcard_join}
        WHERE {gate}
        """


def sql_literal(value):
    """
    *value* as a SQL literal: NULL for None, else the number itself.
    """
    return "NULL" if value is None else repr(value)


def no_rows_sql(columns):
    """
    A query that returns no rows but names *columns*, so a caller that reads
    the cursor's description gets the right header.
    """
    return "SELECT " + ", ".join(f"NULL AS {c}" for c in columns) + " WHERE 0"


def get_scenario_markets_sql(subscenarios):
    """
    The markets of the scenario's market subscenario.
    """
    return f"""
        SELECT market
        FROM inputs_geography_markets
        WHERE market_scenario_id = {subscenarios.MARKET_SCENARIO_ID}
        """


def get_market_groups_sql(subscenarios):
    """
    The scenario's market groups and their members: every market as a group
    of its own, plus the user-defined groups narrowed to the scenario's
    markets. An unset market group subscenario leaves just the implicit
    singletons.
    """
    scenario_markets = get_scenario_markets_sql(subscenarios)
    return f"""
        SELECT market AS market_group, market
        FROM ({scenario_markets})
        UNION
        SELECT market_group, market
        FROM inputs_market_groups
        WHERE market_group_scenario_id =
        {subscenarios.MARKET_GROUP_SCENARIO_ID}
        AND market IN ({scenario_markets})
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
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """
    groups_c = conn.cursor()
    market_groups = groups_c.execute(f"""
        SELECT market_group, market
        FROM ({get_market_groups_sql(subscenarios)})
        ORDER BY market_group, market
        """)

    c = conn.cursor()
    group_list = c.execute(f"""
        SELECT market_group,
        basis,
        market_volume_tmp_profile_scenario_id,
        market_volume_hrz_profile_scenario_id,
        market_volume_prd_profile_scenario_id,
        varies_by_weather_iteration,
        varies_by_hydro_iteration,
        default_max_market_sales,
        default_max_market_purchases,
        default_max_final_market_sales,
        default_max_final_market_purchases,
        default_max_market_sales_in_prd,
        default_max_market_purchases_in_prd,
        default_max_market_sales_in_prd_include_storage_losses
        FROM inputs_market_volume
        WHERE market_volume_scenario_id = {subscenarios.MARKET_VOLUME_SCENARIO_ID}
        -- Limit groups that have at least one of the scenario's markets
        AND market_group IN (
            SELECT DISTINCT market_group
            FROM ({get_market_groups_sql(subscenarios)})
        )
        """).fetchall()

    # The three limit resolutions: the temporal index each is resolved
    # against, the table it comes from, and how its wildcard row matches
    resolutions = [
        {
            "table": "inputs_market_volume_tmp_profiles",
            "profile_id_column": "market_volume_tmp_profile_scenario_id",
            "index_subquery": f"""
                SELECT stage_id, timepoint
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                """,
            "value_columns": [
                "max_market_sales",
                "max_market_purchases",
                "max_final_market_sales",
                "max_final_market_purchases",
            ],
            "index_columns": ["timepoint"],
            "match_columns": ["stage_id", "timepoint"],
            "default_match_columns": ["stage_id"],
            "wildcard_column": "timepoint",
            "data_index_columns": ["stage_id", "timepoint"],
        },
        {
            "table": "inputs_market_volume_hrz_profiles",
            "profile_id_column": "market_volume_hrz_profile_scenario_id",
            "index_subquery": f"""
                SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                """,
            "value_columns": [
                "max_market_sales_in_hrz",
                "max_market_purchases_in_hrz",
                "max_market_sales_in_hrz_include_storage_losses",
            ],
            "index_columns": ["balancing_type_horizon", "horizon"],
            "match_columns": ["balancing_type_horizon", "horizon"],
            "default_match_columns": ["balancing_type_horizon"],
            "wildcard_column": "horizon",
            "data_index_columns": ["balancing_type_horizon", "horizon"],
        },
        {
            "table": "inputs_market_volume_prd_profiles",
            "profile_id_column": "market_volume_prd_profile_scenario_id",
            "index_subquery": f"""
                SELECT DISTINCT period
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                """,
            "value_columns": [
                "max_market_sales_in_prd",
                "max_market_purchases_in_prd",
                "max_market_sales_in_prd_include_storage_losses",
            ],
            "index_columns": ["period"],
            "match_columns": ["period"],
            "default_match_columns": [],
            "wildcard_column": "period",
            "data_index_columns": ["period"],
        },
    ]

    # Loop over the group-basis rows for each resolution's query, since
    # their limits don't all vary by the same iteration types; a group's net
    # and gross rows are resolved independently, each with its own profiles
    # and flat limits
    n_groups = len(group_list)
    queries = ["" for _ in resolutions]
    n = 1
    for (
        market_group,
        basis,
        tmp_profile_id,
        hrz_profile_id,
        prd_profile_id,
        varies_by_weather_iteration,
        varies_by_hydro_iteration,
        *flat_limits,
    ) in group_list:
        union_str = "UNION" if n < n_groups else ""

        # The group's flat limits, keyed by the profile column they default;
        # the horizon level has none, as a horizon limit needs a balancing
        # type
        flat_values = dict(
            zip(
                [
                    "max_market_sales",
                    "max_market_purchases",
                    "max_final_market_sales",
                    "max_final_market_purchases",
                    "max_market_sales_in_prd",
                    "max_market_purchases_in_prd",
                    "max_market_sales_in_prd_include_storage_losses",
                ],
                flat_limits,
            )
        )

        weather_iteration_to_use = (
            weather_iteration if varies_by_weather_iteration else 0
        )
        hydro_iteration_to_use = hydro_iteration if varies_by_hydro_iteration else 0

        # A profile the group does not have comes back as None; "NULL" makes
        # the filter a valid query that matches no row, so the resolution is
        # simply skipped for this group
        profile_ids = {
            "market_volume_tmp_profile_scenario_id": tmp_profile_id,
            "market_volume_hrz_profile_scenario_id": hrz_profile_id,
            "market_volume_prd_profile_scenario_id": prd_profile_id,
        }

        for i, resolution in enumerate(resolutions):
            profile_id = profile_ids[resolution["profile_id_column"]]
            profile_filter = f"""
                market_group = '{market_group}'
                AND {resolution["profile_id_column"]} =
                {"NULL" if profile_id is None else profile_id}
                AND hydro_iteration = {hydro_iteration_to_use}
                AND weather_iteration = {weather_iteration_to_use}
                AND stage_id = {stage}
                """
            data_columns = ", ".join(
                resolution["data_index_columns"] + resolution["value_columns"]
            )
            queries[i] += (
                limits_with_defaults_sql(
                    index_subquery=resolution["index_subquery"],
                    data_subquery=f"""
                    SELECT {data_columns}
                    FROM {resolution["table"]}
                    WHERE {profile_filter}
                    AND {{wildcard_filter}}
                    """,
                    value_columns=resolution["value_columns"],
                    index_columns=resolution["index_columns"],
                    match_columns=resolution["match_columns"],
                    default_match_columns=resolution["default_match_columns"],
                    wildcard_column=resolution["wildcard_column"],
                    extra_select=(
                        f"'{market_group}' AS market_group, '{basis}' AS basis, "
                    ),
                    flat_values={
                        c: flat_values.get(c) for c in resolution["value_columns"]
                    },
                )
                + union_str
            )

        n += 1

    limits = []
    for i, resolution in enumerate(resolutions):
        columns = (
            ["market_group", "basis"]
            + resolution["index_columns"]
            + resolution["value_columns"]
        )
        # With no groups in the volume subscenario there is nothing to
        # resolve; run a query that returns no rows but still names the
        # columns
        query = queries[i] if group_list else no_rows_sql(columns)
        order_by = ", ".join(
            str(j + 1) for j in range(len(columns) - len(resolution["value_columns"]))
        )
        cursor = conn.cursor()
        limits.append(cursor.execute(f"{query} ORDER BY {order_by}"))

    return (market_groups,) + tuple(limits)


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
    Get inputs from database and validate the inputs.

    Every market is implicitly a group of its own, so a user-defined group
    named after a market would merge with it; flag that. Limit rows are
    resolved against the scenario's temporal structure with an inner join,
    so
    a row naming a balancing type or horizon the scenario does not have is
    dropped silently; flag those rather than let a typo quietly remove a
    limit. Also flag negative limits, which would otherwise fail only at
    model load.

    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """
    c = conn.cursor()
    errors = []

    # A market is implicitly a group of its own, so a group named after one
    # merges with it; that silently widens a limit meant for the single
    # market, and there is no reason to define the singleton by hand
    colliding_groups = c.execute(f"""
        SELECT DISTINCT market_group
        FROM inputs_market_groups
        WHERE market_group_scenario_id =
        {subscenarios.MARKET_GROUP_SCENARIO_ID}
        AND market_group IN ({get_scenario_markets_sql(subscenarios)})
        AND market != market_group
        """).fetchall()
    for (group,) in colliding_groups:
        errors.append(
            f"inputs_market_groups: market group '{group}' is named after a "
            f"market but contains another one; every market is already a "
            f"group of its own, so the two would be merged. Rename the group."
        )

    # A group that narrows to none of the scenario's markets is not an
    # error: group and volume subscenarios are shared across scenarios with
    # different market sets, and such a group simply contributes no
    # constraints. A name that is neither a market nor a defined group is a
    # different matter, and is almost always a typo.
    undefined_groups = c.execute(f"""
        SELECT DISTINCT market_group
        FROM inputs_market_volume
        WHERE market_volume_scenario_id = {subscenarios.MARKET_VOLUME_SCENARIO_ID}
        AND market_group NOT IN (
            SELECT DISTINCT market_group
            FROM inputs_market_groups
            WHERE market_group_scenario_id =
            {subscenarios.MARKET_GROUP_SCENARIO_ID}
        )
        -- Any known market names an implicit group of its own; check
        -- against every market, not only this scenario's, since one volume
        -- subscenario serves scenarios with different market sets
        AND market_group NOT IN (
            SELECT DISTINCT market FROM inputs_geography_markets
        )
        """).fetchall()
    for (group,) in undefined_groups:
        errors.append(
            f"inputs_market_volume: '{group}' is neither a market nor a "
            f"market group defined by the scenario's market group "
            f"subscenario, so its limits are ignored."
        )

    # Each profile table has its own subscenario column, which the
    # scenario's market volume subscenario maps each group to
    def profile_filter_for(column):
        return f"""
            (market_group, {column}) IN (
                SELECT market_group, {column}
                FROM inputs_market_volume
                WHERE market_volume_scenario_id =
                {subscenarios.MARKET_VOLUME_SCENARIO_ID}
            )
            """

    profile_filter = profile_filter_for("market_volume_hrz_profile_scenario_id")

    # Balancing types and horizons the temporal structure does not define (a
    # horizon of 0 is the wildcard row and has no horizon to match)
    unknown_bts = c.execute(f"""
        SELECT DISTINCT balancing_type_horizon
        FROM inputs_market_volume_hrz_profiles
        WHERE {profile_filter}
        AND balancing_type_horizon NOT IN (
            SELECT DISTINCT balancing_type_horizon
            FROM inputs_temporal_horizons
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        )
        """).fetchall()
    for (bt,) in unknown_bts:
        errors.append(
            f"inputs_market_volume_hrz_profiles: balancing type '{bt}' is "
            f"not in the scenario's temporal structure, so its limits are "
            f"ignored."
        )

    unknown_hrzs = c.execute(f"""
        SELECT DISTINCT balancing_type_horizon, horizon
        FROM inputs_market_volume_hrz_profiles
        WHERE {profile_filter}
        AND horizon != 0
        AND balancing_type_horizon IN (
            SELECT DISTINCT balancing_type_horizon
            FROM inputs_temporal_horizons
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        )
        AND (balancing_type_horizon, horizon) NOT IN (
            SELECT balancing_type_horizon, horizon
            FROM inputs_temporal_horizons
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        )
        """).fetchall()
    for bt, hrz in unknown_hrzs:
        errors.append(
            f"inputs_market_volume_hrz_profiles: horizon {hrz} of balancing "
            f"type '{bt}' is not in the scenario's temporal structure, so "
            f"its limits are ignored."
        )

    # Negative limits; the model params are non-negative, so these would
    # otherwise fail only at model load
    negative_limit_checks = [
        (
            "inputs_market_volume_tmp_profiles",
            "market_volume_tmp_profile_scenario_id",
            [
                "max_market_sales",
                "max_market_purchases",
                "max_final_market_sales",
                "max_final_market_purchases",
            ],
        ),
        (
            "inputs_market_volume_hrz_profiles",
            "market_volume_hrz_profile_scenario_id",
            ["max_market_sales_in_hrz", "max_market_purchases_in_hrz"],
        ),
        (
            "inputs_market_volume_prd_profiles",
            "market_volume_prd_profile_scenario_id",
            ["max_market_sales_in_prd", "max_market_purchases_in_prd"],
        ),
    ]
    for table, profile_id_column, columns in negative_limit_checks:
        for column in columns:
            (n_negative,) = c.execute(f"""
                SELECT COUNT(*)
                FROM {table}
                WHERE {profile_filter_for(profile_id_column)}
                AND {column} < 0
                """).fetchone()
            if n_negative:
                errors.append(
                    f"{table}: {n_negative} row(s) have a negative "
                    f"{column}; market volume limits must be non-negative."
                )
    for column in [
        "default_max_market_sales",
        "default_max_market_purchases",
        "default_max_final_market_sales",
        "default_max_final_market_purchases",
        "default_max_market_sales_in_prd",
        "default_max_market_purchases_in_prd",
    ]:
        (n_negative,) = c.execute(f"""
            SELECT COUNT(*)
            FROM inputs_market_volume
            WHERE market_volume_scenario_id =
            {subscenarios.MARKET_VOLUME_SCENARIO_ID}
            AND {column} < 0
            """).fetchone()
        if n_negative:
            errors.append(
                f"inputs_market_volume: {n_negative} row(s) have a negative "
                f"{column}; market volume limits must be non-negative."
            )

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_market_volume",
        severity="High",
        errors=errors,
    )


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
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection

    Get inputs from database and write out the market group and market
    volume limit files.
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

    (
        market_groups,
        tmp_limits,
        hrz_limits,
        prd_limits,
    ) = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    for fname, data in [
        ("market_groups.tab", market_groups),
        ("market_volume_tmp.tab", tmp_limits),
        ("market_volume_hrz.tab", hrz_limits),
        ("market_volume_prd.tab", prd_limits),
    ]:
        write_tab_file_model_inputs(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            fname=fname,
            data=data,
            replace_nulls=True,
        )


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
    Export each market group's limits, the position they constrain, and the
    duals of the constraints enforcing them (a limit left at its default of
    infinity is not enforced and so has no dual).

    The duals are in the objective's NPV terms; normalize each by its index's
    objective coefficient to get a marginal cost per MW or MWh, as the load
    balance marginal costs do.

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    def results_writer(fname, header):
        """
        Open the results file and write its header; most scenarios define no
        limits at a given resolution, and writing nothing rather than a
        header-only file keeps them out of every results directory (a Monte
        Carlo run has one per draw per subproblem).
        """
        f = open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "results",
                fname,
            ),
            "w",
            newline="",
        )
        writer = csv.writer(f)
        writer.writerow(header)
        return f, writer

    if len(m.MARKET_GROUP_TMPS_W_LIMIT) > 0:
        f, writer = results_writer(
            "system_market_volume_tmp.csv",
            [
                "market_group",
                "basis",
                "timepoint",
                "period",
                "net_market_purchased_power_mw",
                "final_net_market_purchased_power_mw",
                "gross_market_sales_mw",
                "gross_market_purchases_mw",
                "final_gross_market_sales_mw",
                "final_gross_market_purchases_mw",
                "max_market_purchases",
                "max_market_sales",
                "max_final_market_purchases",
                "max_final_market_sales",
                "max_market_purchases_dual",
                "max_market_sales_dual",
                "max_final_market_purchases_dual",
                "max_final_market_sales_dual",
                "max_market_purchases_marginal_cost",
                "max_market_sales_marginal_cost",
                "max_final_market_purchases_marginal_cost",
                "max_final_market_sales_marginal_cost",
            ],
        )
        with f:
            for group, basis, tmp in sorted(m.MARKET_GROUP_TMPS_W_LIMIT):
                idx = (group, basis, tmp)
                duals = [
                    constraint_dual(m, constraint, idx)
                    for constraint in [
                        m.Max_Market_Group_Purchases_Constraint,
                        m.Max_Market_Group_Sales_Constraint,
                        m.Max_Market_Group_Final_Purchases_Constraint,
                        m.Max_Market_Group_Final_Sales_Constraint,
                    ]
                ]
                coefficient = m.tmp_objective_coefficient[tmp]
                sales, purchases = realized_gross_position(m, group, tmp, final=False)
                final_sales, final_purchases = realized_gross_position(
                    m, group, tmp, final=True
                )
                writer.writerow(
                    [
                        group,
                        basis,
                        tmp,
                        m.period[tmp],
                        value(m.Group_Net_Market_Purchased_Power[group, tmp]),
                        value(m.Group_Final_Net_Market_Purchased_Power[group, tmp]),
                        sales,
                        purchases,
                        final_sales,
                        final_purchases,
                        m.max_market_purchases[idx],
                        m.max_market_sales[idx],
                        m.max_final_market_purchases[idx],
                        m.max_final_market_sales[idx],
                    ]
                    + duals
                    + [
                        none_dual_type_error_wrapper(dual, coefficient)
                        for dual in duals
                    ]
                )

    if len(m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT) > 0:
        f, writer = results_writer(
            "system_market_volume_hrz.csv",
            [
                "market_group",
                "basis",
                "balancing_type_horizon",
                "horizon",
                "net_market_purchased_power_mwh",
                "gross_market_sales_mwh",
                "gross_market_purchases_mwh",
                "max_market_purchases_in_hrz",
                "max_market_sales_in_hrz",
                "max_market_purchases_in_hrz_dual",
                "max_market_sales_in_hrz_dual",
                "max_market_purchases_in_hrz_marginal_cost",
                "max_market_sales_in_hrz_marginal_cost",
            ],
        )
        with f:
            for group, basis, bt, hrz in sorted(m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT):
                idx = (group, basis, bt, hrz)
                duals = [
                    constraint_dual(m, constraint, idx)
                    for constraint in [
                        m.Max_Market_Group_Purchases_in_Hrz_Constraint,
                        m.Max_Market_Group_Sales_in_Hrz_Constraint,
                    ]
                ]
                coefficient = m.hrz_objective_coefficient[bt, hrz]
                writer.writerow(
                    [group, basis, bt, hrz]
                    + realized_energy(m, group, m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz])
                    + [
                        m.max_market_purchases_in_hrz[idx],
                        m.max_market_sales_in_hrz[idx],
                    ]
                    + duals
                    + [
                        none_dual_type_error_wrapper(dual, coefficient)
                        for dual in duals
                    ]
                )

    if len(m.MARKET_GROUP_PRDS_W_LIMIT) > 0:
        f, writer = results_writer(
            "system_market_volume_prd.csv",
            [
                "market_group",
                "basis",
                "period",
                "net_market_purchased_power_mwh",
                "gross_market_sales_mwh",
                "gross_market_purchases_mwh",
                "max_market_purchases_in_prd",
                "max_market_sales_in_prd",
                "max_market_purchases_in_prd_dual",
                "max_market_sales_in_prd_dual",
                "max_market_purchases_in_prd_marginal_cost",
                "max_market_sales_in_prd_marginal_cost",
            ],
        )
        with f:
            for group, basis, prd in sorted(m.MARKET_GROUP_PRDS_W_LIMIT):
                idx = (group, basis, prd)
                duals = [
                    constraint_dual(m, constraint, idx)
                    for constraint in [
                        m.Max_Market_Group_Purchases_in_Prd_Constraint,
                        m.Max_Market_Group_Sales_in_Prd_Constraint,
                    ]
                ]
                coefficient = m.period_objective_coefficient[prd]
                writer.writerow(
                    [group, basis, prd]
                    + realized_energy(m, group, m.TMPS_IN_PRD[prd])
                    + [
                        m.max_market_purchases_in_prd[idx],
                        m.max_market_sales_in_prd[idx],
                    ]
                    + duals
                    + [
                        none_dual_type_error_wrapper(dual, coefficient)
                        for dual in duals
                    ]
                )


def realized_gross_position(m, group, tmp, final):
    """
    A group's solved total sales and total purchases in the timepoint, in
    MW: the positive parts of each of its markets' net positions, summed.
    Computed from the net positions rather than read from the gross split
    variables, which are exact where a gross limit binds but not unique
    elsewhere, and which do not exist for a net-only group.
    """
    sales = 0.0
    purchases = 0.0
    for mrkt in m.MARKETS_BY_MARKET_GROUP[group]:
        position = value(market_net_position(m, mrkt, tmp, final=final))
        sales += max(0.0, -position)
        purchases += max(0.0, position)
    return sales, purchases


def realized_energy(m, group, tmps):
    """
    A group's solved net purchases, total sales and total purchases over the
    timepoints *tmps*, in MWh.
    """
    net = 0.0
    sales = 0.0
    purchases = 0.0
    for tmp in tmps:
        weight = m.hrs_in_tmp[tmp] * m.tmp_weight[tmp]
        net += value(m.Group_Net_Market_Purchased_Power[group, tmp]) * weight
        tmp_sales, tmp_purchases = realized_gross_position(m, group, tmp, final=False)
        sales += tmp_sales * weight
        purchases += tmp_purchases * weight
    return [net, sales, purchases]


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
    :param scenario_id:
    :param c:
    :param db:
    :param results_directory:
    :param quiet:
    :return:
    """
    for which_results in [
        "system_market_volume_tmp",
        "system_market_volume_hrz",
        "system_market_volume_prd",
    ]:
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
            which_results=which_results,
        )
