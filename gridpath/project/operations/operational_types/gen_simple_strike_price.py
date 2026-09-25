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
This operational type describes generators that are dispatched all-or-nothing
against the price in a market, i.e. on a *strike price* basis. In each
timepoint, the project's marginal cost of generating is compared to the price
in the market the project is assigned to. If generating is cheaper than the
market price, the project produces power equal to its available capacity; if
the market price is lower, the project produces nothing.

The marginal cost is the project's fuel cost (constant heat rate times the
fuel price in the timepoint's period and month), plus its variable O&M cost,
plus its carbon tax cost if the *carbon_tax* feature is enabled and the
project is in a carbon tax zone with a tax in the timepoint's period. Both the
marginal cost and the market price are model inputs, so the dispatch decision
is made when the model is built rather than by the optimization: this
operational type adds no variables and no constraints, and the project's power
output is a constant in every timepoint. It is a price-taker heuristic
embedded in the model, not an optimized dispatch.

The available capacity can either be a set input (e.g. for the gen_spec
capacity_type) or a decision variable by period (e.g. for the gen_new_lin
capacity_type). Note, however, that the dispatch decision does not depend on
the capacity, so a project of this operational type that is also a
capacity-expansion candidate will be built only if the value of its (fixed)
dispatch outweighs its capacity cost.

The heat rate must be constant, i.e. the project's heat rate curve must have a
single load point, and the project may be assigned at most one fuel. This
operational type cannot provide reserves (since there is no operable range,
i.e. no headroom or footroom).

Costs for this operational type include fuel costs and variable O&M costs.
Note that market revenues are not credited to the project: as for every other
operational type, the project's power flows into the load balance of its load
zone, and any market transactions are decided by the market modules.

.. note:: This operational type requires the *markets* feature, as it needs
    the market price in each timepoint. The market assigned to the project
    must be one of the markets included in the scenario.

.. note:: The carbon tax inputs are read here from the same files the carbon
    tax modules read, because those modules are loaded after the operational
    types and so their parameters are not yet available when this operational
    type's dispatch decision is made.

.. warning:: The carbon tax cost in the strike price does not account for
    carbon credits. With both the *carbon_tax* and *carbon_credits* features
    enabled, the number of credits purchased is a decision variable, so the
    tax reduction it buys cannot be known when the dispatch decision is made;
    the strike price will then overstate the project's carbon tax cost and the
    project will run less than it otherwise would.

"""

import os.path
import warnings
from pyomo.environ import (
    Binary,
    Constraint,
    NonNegativeReals,
    Param,
    Reals,
    Set,
    value,
)

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.dynamic_components import headroom_variables, footroom_variables
from gridpath.auxiliary.validations import (
    get_projects_by_reserve,
    validate_idxs,
    validate_single_input,
    write_validation_to_database,
)
from gridpath.common_functions import create_results_df
from gridpath.project.common_functions import (
    check_boundary_type,
    check_if_first_timepoint,
)
from gridpath.project.operations.reserves.reserve_aggregation import (
    footroom_provision_rule,
    headroom_provision_rule,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_optype_model_data,
    validate_opchars,
)


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
    | | :code:`GEN_SIMPLE_STRIKE_PRICE`                                       |
    |                                                                         |
    | The set of generators of the :code:`gen_simple_strike_price`            |
    | operational type.                                                       |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS`                              |
    |                                                                         |
    | Two-dimensional set with generators of the                              |
    | :code:`gen_simple_strike_price` operational type and their operational  |
    | timepoints.                                                             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_simple_strike_price_market`                                |
    | | *Defined over*: :code:`GEN_SIMPLE_STRIKE_PRICE`                       |
    | | *Within*: :code:`m.MARKETS`                                           |
    |                                                                         |
    | The market whose price the project's marginal cost is compared to.      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_simple_strike_price_dispatch_at_equal_cost`                |
    | | *Defined over*: :code:`GEN_SIMPLE_STRIKE_PRICE`                       |
    | | *Within*: :code:`Binary`                                              |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Determines how a tie is broken, i.e. what the project does when its     |
    | marginal cost is exactly equal to the market price. If 1, the project   |
    | generates; if 0 (the default), it does not.                             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Carbon Tax Input Params                                                 |
    +=========================================================================+
    | Declared only when the *carbon_tax* feature is enabled, and read from   |
    | the same input files as the carbon tax modules' own parameters.         |
    +-------------------------------------------------------------------------+
    | | :code:`gen_simple_strike_price_carbon_tax_zone`                       |
    | | *Defined over*: :code:`PROJECTS`                                      |
    | | *Within*: :code:`CARBON_TAX_ZONES`                                    |
    |                                                                         |
    | The carbon tax zone of each project that is in one.                     |
    +-------------------------------------------------------------------------+
    | | :code:`gen_simple_strike_price_carbon_tax_allowance`                  |
    | | *Defined over*: :code:`PROJECTS`, :code:`FUEL_GROUPS`,                |
    |   :code:`PERIODS`                                                       |
    | | *Within*: :code:`Reals`                                               |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The project's carbon tax allowance in tCO2 per MWh.                     |
    +-------------------------------------------------------------------------+
    | | :code:`gen_simple_strike_price_carbon_tax`                            |
    | | *Defined over*:                                                       |
    |   :code:`GEN_SIMPLE_STRIKE_PRICE_CARBON_TAX_ZONE_PRDS`                  |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The carbon tax in each carbon tax zone and period that has one.         |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Params                                                          |
    +=========================================================================+
    | | :code:`GenSimpleStrikePrice_Marginal_Cost_per_MWh`                    |
    | | *Defined over*: :code:`GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS`              |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The project's cost of generating one MWh in the timepoint: the constant |
    | heat rate times the fuel price in the timepoint's period and month      |
    | (zero if the project has no fuel), plus the project's variable O&M      |
    | cost, plus the tax on the project's emissions net of its carbon tax     |
    | allowance (zero unless the project is in a carbon tax zone with a tax   |
    | in this period).                                                        |
    +-------------------------------------------------------------------------+
    | | :code:`GenSimpleStrikePrice_Online`                                   |
    | | *Defined over*: :code:`GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS`              |
    | | *Within*: :code:`Binary`                                              |
    |                                                                         |
    | 1 if the project generates in the timepoint, 0 otherwise. This is 1 if  |
    | the project's marginal cost is lower than the price in its market, 0 if |
    | it is higher, and determined by                                         |
    | :code:`gen_simple_strike_price_dispatch_at_equal_cost` if the two are   |
    | equal.                                                                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`GenSimpleStrikePrice_No_Upward_Reserves_Constraint`            |
    | | *Defined over*: :code:`GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS`              |
    |                                                                         |
    | Strike-price generator projects cannot provide upward reserves.         |
    +-------------------------------------------------------------------------+
    | | :code:`GenSimpleStrikePrice_No_Downward_Reserves_Constraint`          |
    | | *Defined over*: :code:`GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS`              |
    |                                                                         |
    | Strike-price generator projects cannot provide downward reserves.       |
    +-------------------------------------------------------------------------+

    """

    # The market price is the whole point of this operational type, so fail
    # early and clearly rather than with an AttributeError if the markets
    # feature is not on
    if not hasattr(m, "market_price"):
        raise ValueError(
            "The 'gen_simple_strike_price' operational type requires the "
            "'markets' feature, which is not enabled in this scenario. "
            "Enable the 'markets' feature (of_markets) or change the "
            "operational type of the affected projects."
        )

    # Sets
    ###########################################################################

    m.GEN_SIMPLE_STRIKE_PRICE = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_simple_strike_price"
        ),
    )

    m.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.GEN_SIMPLE_STRIKE_PRICE,
        ),
    )

    # Required Params
    ###########################################################################

    m.gen_simple_strike_price_market = Param(
        m.GEN_SIMPLE_STRIKE_PRICE, within=m.MARKETS
    )

    # Optional Params
    ###########################################################################

    m.gen_simple_strike_price_dispatch_at_equal_cost = Param(
        m.GEN_SIMPLE_STRIKE_PRICE, within=Binary, default=0
    )

    # Carbon Tax Input Params
    ###########################################################################
    # The carbon tax modules are loaded after the operational types, so their
    # parameters are not yet constructed when this operational type's dispatch
    # decision is made. Read the same inputs into operational-type-owned
    # parameters instead; these are loaded from the very same files, so the
    # values cannot drift from the ones the carbon tax modules use.
    # geography.carbon_tax_zones is loaded before the operational types, so
    # its set tells us whether the carbon tax feature is on at all.
    if hasattr(m, "CARBON_TAX_ZONES"):
        m.gen_simple_strike_price_carbon_tax_zone = Param(
            m.PROJECTS, within=m.CARBON_TAX_ZONES
        )

        m.gen_simple_strike_price_carbon_tax_allowance = Param(
            m.PROJECTS, m.FUEL_GROUPS, m.PERIODS, within=Reals, default=0
        )

        m.GEN_SIMPLE_STRIKE_PRICE_CARBON_TAX_ZONE_PRDS = Set(
            dimen=2, within=m.CARBON_TAX_ZONES * m.PERIODS
        )

        m.gen_simple_strike_price_carbon_tax = Param(
            m.GEN_SIMPLE_STRIKE_PRICE_CARBON_TAX_ZONE_PRDS, within=NonNegativeReals
        )

    # Derived Params
    ###########################################################################

    m.GenSimpleStrikePrice_Marginal_Cost_per_MWh = Param(
        m.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS,
        within=Reals,
        initialize=marginal_cost_init,
    )

    m.GenSimpleStrikePrice_Online = Param(
        m.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS,
        within=Binary,
        initialize=online_init,
    )

    # Constraints
    ###########################################################################

    # TODO: remove this constraint once input validation is in place that
    #  does not allow specifying a reserve_zone if 'gen_simple_strike_price'
    #  type
    def no_upward_reserve_rule(mod, g, tmp):
        """
        **Constraint Name**: GenSimpleStrikePrice_No_Upward_Reserves_Constraint
        **Enforced Over**: GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS

        Upward reserves should be zero in every operational timepoint.
        """
        if getattr(d, headroom_variables)[g]:
            warnings.warn("""project {} is of the 'gen_simple_strike_price' operational 
                type and should not be assigned any upward reserve BAs since 
                it cannot provide upward reserves. Please replace the upward 
                reserve BA for project {} with '.' (no value) in projects.tab. 
                Model will add constraint to ensure project {} cannot provide 
                upward reserves.
                """.format(g, g, g))
            return headroom_provision_rule(d, mod, g, tmp) == 0
        else:
            return Constraint.Skip

    m.GenSimpleStrikePrice_No_Upward_Reserves_Constraint = Constraint(
        m.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS, rule=no_upward_reserve_rule
    )

    # TODO: remove this constraint once input validation is in place that
    #  does not allow specifying a reserve_zone if 'gen_simple_strike_price'
    #  type
    def no_downward_reserve_rule(mod, g, tmp):
        """
        **Constraint Name**: GenSimpleStrikePrice_No_Downward_Reserves_Constraint
        **Enforced Over**: GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS

        Downward reserves should be zero in every operational timepoint.
        """
        if getattr(d, footroom_variables)[g]:
            warnings.warn("""project {} is of the 'gen_simple_strike_price' operational 
                type and should not be assigned any downward reserve BAs since 
                it cannot provide downward reserves. Please replace the 
                downward reserve BA for project {} with '.' (no value) in 
                projects.tab. Model will add constraint to ensure project {} 
                cannot provide downward reserves.
                """.format(g, g, g))
            return footroom_provision_rule(d, mod, g, tmp) == 0
        else:
            return Constraint.Skip

    m.GenSimpleStrikePrice_No_Downward_Reserves_Constraint = Constraint(
        m.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS, rule=no_downward_reserve_rule
    )


# Derived Param Rules
###############################################################################


def get_fuel_by_prj(mod):
    """
    The single fuel of each fueled project of this operational type, mapped
    once on the first call rather than rescanning FUELS_BY_PRJ for every
    project-timepoint.

    Projects of this operational type may have at most one fuel: with a fuel
    blend, the marginal cost of generating would depend on the blend chosen by
    the optimization and so could not be compared to the market price when the
    model is built.
    """
    if not hasattr(mod, "_gridpath_gen_simple_strike_price_fuel"):
        fuel_by_prj = {}
        for prj in mod.GEN_SIMPLE_STRIKE_PRICE:
            if prj not in mod.FUEL_PRJS:
                continue
            fuels = list(mod.FUELS_BY_PRJ[prj])
            if len(fuels) > 1:
                raise ValueError(
                    "Project {} is of the 'gen_simple_strike_price' "
                    "operational type and is assigned {} fuels ({}), but "
                    "projects of this operational type may have at most one "
                    "fuel.".format(prj, len(fuels), ", ".join(sorted(fuels)))
                )
            fuel_by_prj[prj] = fuels[0]
        mod._gridpath_gen_simple_strike_price_fuel = fuel_by_prj

    return mod._gridpath_gen_simple_strike_price_fuel


def get_fuel_groups_by_prj(mod):
    """
    The fuel groups of each fueled project of this operational type, mapped
    once on the first call rather than rescanning FUEL_PRJ_FUELS_FUEL_GROUP
    for every project-timepoint. A project whose fuel belongs to no fuel group
    has no entry, which is also how the carbon tax modules treat it.
    """
    if not hasattr(mod, "_gridpath_gen_simple_strike_price_fuel_groups"):
        fuel_groups_by_prj = {}
        for prj, fg, f in mod.FUEL_PRJ_FUELS_FUEL_GROUP:
            if prj in mod.GEN_SIMPLE_STRIKE_PRICE:
                fuel_groups_by_prj.setdefault(prj, set()).add(fg)
        mod._gridpath_gen_simple_strike_price_fuel_groups = fuel_groups_by_prj

    return mod._gridpath_gen_simple_strike_price_fuel_groups


def carbon_tax_cost_per_mwh(mod, prj, tmp):
    """
    The project's carbon tax cost per MWh generated, replicating
    Total_Project_Carbon_Tax_Cost in
    system.policy.carbon_tax.aggregate_project_carbon_emissions: the project's
    emissions net of its carbon tax allowance, times the tax in its zone.

    Emissions per MWh are the constant heat rate times the fuel's carbon
    intensity. The allowance per MWh is the project's
    carbon_tax_allowance, because the allowance rule divides the fuel burn by
    the project's average heat rate, and for this operational type the
    average heat rate and the constant heat rate are the same number (the
    single load point is enforced in marginal_cost_init).

    Returns 0 when the carbon tax feature is off, when the project is not in a
    carbon tax zone, or when its zone has no tax in this period, each of which
    is also when the carbon tax modules charge the project nothing.
    """
    if not hasattr(mod, "gen_simple_strike_price_carbon_tax_zone"):
        return 0

    if prj not in mod.gen_simple_strike_price_carbon_tax_zone:
        return 0

    prd = mod.period[tmp]
    carbon_tax_zone = mod.gen_simple_strike_price_carbon_tax_zone[prj]
    if (
        carbon_tax_zone,
        prd,
    ) not in mod.GEN_SIMPLE_STRIKE_PRICE_CARBON_TAX_ZONE_PRDS:
        return 0

    emissions_per_mwh = 0
    allowance_per_mwh = 0
    if prj in mod.FUEL_PRJS:
        fuel = get_fuel_by_prj(mod)[prj]
        emissions_per_mwh = (
            mod.fuel_burn_slope_mmbtu_per_mwh[prj, prd, 0]
            * mod.co2_intensity_tons_per_mmbtu[fuel]
        )
        allowance_per_mwh = sum(
            mod.gen_simple_strike_price_carbon_tax_allowance[prj, fg, prd]
            for fg in get_fuel_groups_by_prj(mod).get(prj, [])
        )

    return mod.gen_simple_strike_price_carbon_tax[carbon_tax_zone, prd] * (
        emissions_per_mwh - allowance_per_mwh
    )


def marginal_cost_init(mod, prj, tmp):
    """
    **Param Name**: GenSimpleStrikePrice_Marginal_Cost_per_MWh
    **Defined Over**: GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS

    The cost of generating one MWh: fuel cost, plus variable O&M cost, plus
    carbon tax cost. All components are model inputs, so this resolves to a
    number when the model is built.
    """
    prd = mod.period[tmp]
    marginal_cost = 0

    # Fuel cost
    if prj in mod.FUEL_PRJS:
        if prj not in mod.HR_CURVE_PRJS:
            raise ValueError(
                "Project {} is of the 'gen_simple_strike_price' operational "
                "type and is assigned a fuel, but has no heat rate curve. "
                "Specify a heat_rate_curves_scenario_id for this project or "
                "remove its project_fuel_scenario_id.".format(prj)
            )
        # A project of this operational type is either fully on or fully off,
        # so only a constant heat rate is meaningful; this is also what makes
        # the carbon tax allowance per MWh the allowance parameter itself
        if (prj, prd, 1) in mod.HR_CURVE_PRJS_PRDS_SGMS:
            raise ValueError(
                "Project {} is of the 'gen_simple_strike_price' operational "
                "type and has a heat rate curve with more than one load "
                "point. Projects of this operational type are either fully on "
                "or fully off, so specify a single load point (a constant "
                "heat rate) for this project.".format(prj)
            )
        fuel = get_fuel_by_prj(mod)[prj]
        marginal_cost += (
            mod.fuel_burn_slope_mmbtu_per_mwh[prj, prd, 0]
            * mod.fuel_price_per_mmbtu[fuel, prd, mod.month[tmp]]
        )

    # Variable O&M cost; a project may have any combination of the three
    # simple variable O&M inputs, which are additive
    if prj in mod.VAR_OM_COST_CURVE_PRJS:
        raise ValueError(
            "Project {} is of the 'gen_simple_strike_price' operational type "
            "and is assigned a variable O&M curve. Projects of this "
            "operational type are either fully on or fully off, so a variable "
            "O&M curve by loading level has no meaning for them; specify a "
            "simple variable O&M cost instead.".format(prj)
        )
    if prj in mod.VAR_OM_COST_SIMPLE_PRJS:
        marginal_cost += mod.variable_om_cost_per_mwh[prj]
    if (prj, prd) in mod.VAR_OM_COST_BY_PRD_PRJ_PRDS:
        marginal_cost += mod.variable_om_cost_per_mwh_by_period[prj, prd]
    if (prj, tmp) in mod.VAR_OM_COST_BY_TMP_PRJ_TMPS:
        marginal_cost += mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]

    # Carbon tax cost
    marginal_cost += carbon_tax_cost_per_mwh(mod, prj, tmp)

    return marginal_cost


def online_init(mod, prj, tmp):
    """
    **Param Name**: GenSimpleStrikePrice_Online
    **Defined Over**: GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS

    Generate if the marginal cost is below the market price, don't if it is
    above, and break a tie based on the project's
    gen_simple_strike_price_dispatch_at_equal_cost input.
    """
    marginal_cost = mod.GenSimpleStrikePrice_Marginal_Cost_per_MWh[prj, tmp]
    price = mod.market_price[mod.gen_simple_strike_price_market[prj], tmp]

    if marginal_cost < price:
        return 1
    elif marginal_cost > price:
        return 0
    else:
        return mod.gen_simple_strike_price_dispatch_at_equal_cost[prj]


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp):
    """
    Power provision from strike-price generators is their available capacity
    if the project generates in this timepoint and zero if it does not.
    """
    if mod.GenSimpleStrikePrice_Online[g, tmp]:
        return mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
    else:
        return 0


def fuel_burn_rule(mod, g, tmp):
    """
    Fuel burn is the constant heat rate times power output, which is the
    available capacity when the project generates and zero when it does not.
    """
    if mod.GenSimpleStrikePrice_Online[g, tmp]:
        return (
            mod.fuel_burn_slope_mmbtu_per_mwh[g, mod.period[tmp], 0]
            * mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
        )
    else:
        return 0


def power_delta_rule(mod, g, tmp):
    """
    Exogenously defined ramp for strike-price generators.

    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint.
    """
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[g]
    ) and (
        check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linear",
        )
        or check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        )
    ):
        pass
    else:
        prev_tmp = mod.prev_tmp[tmp, mod.balancing_type_project[g]]
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * mod.GenSimpleStrikePrice_Online[g, tmp]
        ) - (
            mod.Capacity_MW[g, mod.period[prev_tmp]]
            * mod.Availability_Derate[g, prev_tmp]
            * mod.GenSimpleStrikePrice_Online[g, prev_tmp]
        )


def capacity_providing_inertia_rule(mod, g, tmp):
    """
    Capacity providing inertia for a GEN_SIMPLE_STRIKE_PRICE project is its
    available capacity if it is generating and zero otherwise.
    """
    if mod.GenSimpleStrikePrice_Online[g, tmp]:
        return mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
    else:
        return 0


# Input-Output
###############################################################################


def load_model_data(
    mod,
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
    :param mod:
    :param d:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """

    load_optype_model_data(
        mod=mod,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="gen_simple_strike_price",
    )

    # Carbon tax inputs, read from the same files as the carbon tax modules
    # (see the note in this module's docstring)
    if hasattr(mod, "gen_simple_strike_price_carbon_tax_zone"):
        inputs_directory = os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
        )

        data_portal.load(
            filename=os.path.join(inputs_directory, "projects.tab"),
            select=("project", "carbon_tax_zone"),
            param=(mod.gen_simple_strike_price_carbon_tax_zone,),
        )

        # No project with an allowance means no file is written, in which case
        # the allowance stays at its default of zero
        allowance_file = os.path.join(
            inputs_directory, "project_carbon_tax_allowance.tab"
        )
        if os.path.exists(allowance_file):
            data_portal.load(
                filename=allowance_file,
                select=(
                    "project",
                    "fuel_group",
                    "period",
                    "carbon_tax_allowance_tco2_per_mwh",
                ),
                param=mod.gen_simple_strike_price_carbon_tax_allowance,
            )

        data_portal.load(
            filename=os.path.join(inputs_directory, "carbon_tax.tab"),
            index=mod.GEN_SIMPLE_STRIKE_PRICE_CARBON_TAX_ZONE_PRDS,
            param=mod.gen_simple_strike_price_carbon_tax,
            select=("carbon_tax_zone", "period", "carbon_tax"),
        )


def add_to_prj_tmp_results(mod):
    """
    Export the inputs of the dispatch decision alongside its outcome so that
    the dispatch can be checked without recomputing it.
    """
    results_columns = [
        "strike_price_marginal_cost_per_mwh",
        "strike_price_market_price_per_mwh",
        "strike_price_online",
    ]
    data = [
        [
            prj,
            tmp,
            value(mod.GenSimpleStrikePrice_Marginal_Cost_per_MWh[prj, tmp]),
            value(mod.market_price[mod.gen_simple_strike_price_market[prj], tmp]),
            value(mod.GenSimpleStrikePrice_Online[prj, tmp]),
        ]
        for (prj, tmp) in mod.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS
    ]

    optype_dispatch_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    return results_columns, optype_dispatch_df


# Validation
###############################################################################


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
    Get inputs from database and validate the inputs
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    # Validate operational chars table inputs
    opchar_df = validate_opchars(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "gen_simple_strike_price",
    )

    # Other module specific validations

    c = conn.cursor()

    # Check that the project's market is one of the scenario's markets
    prj_markets = c.execute(
        """
        SELECT project, market
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, market
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {}
        AND operational_type = '{}') AS op_char
        USING(project)
        WHERE project_portfolio_scenario_id = {}
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            "gen_simple_strike_price",
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    ).fetchall()

    scenario_markets = [m[0] for m in c.execute("""
            SELECT market
            FROM inputs_geography_markets
            WHERE market_scenario_id = {}
            """.format(subscenarios.MARKET_SCENARIO_ID)).fetchall()]

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_operational_chars",
        severity="High",
        errors=validate_idxs(
            # The scenario's markets must cover every market named by a
            # gen_simple_strike_price project, so the projects' markets are
            # the required indexes and the scenario's markets the actual ones
            actual_idxs=scenario_markets,
            req_idxs=[market for (prj, market) in prj_markets if market is not None],
            idx_label="market",
            msg="Markets of gen_simple_strike_price projects must be included "
            "in the scenario's markets.",
        ),
    )

    # Check that the project has at most one fuel
    prj_fuels = c.execute(
        """
        SELECT project, COUNT(fuel) AS n_fuels
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, project_fuel_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {}
        AND operational_type = '{}') AS op_char
        USING(project)
        INNER JOIN
        inputs_project_fuels
        USING(project, project_fuel_scenario_id)
        WHERE project_portfolio_scenario_id = {}
        GROUP BY project
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            "gen_simple_strike_price",
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    ).fetchall()

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_fuels",
        severity="High",
        errors=[
            "Project(s) '{}': gen_simple_strike_price projects can have at "
            "most one fuel.".format(prj)
            for (prj, n_fuels) in prj_fuels
            if n_fuels > 1
        ],
    )

    # Check that the heat rate curve has a single load point, i.e. that the
    # heat rate is constant
    heat_rates = c.execute(
        """
        SELECT project, period, load_point_fraction
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, operational_type, heat_rate_curves_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {}
        AND operational_type = '{}') AS op_char
        USING(project)
        INNER JOIN
        (SELECT project, period, heat_rate_curves_scenario_id, load_point_fraction
        FROM inputs_project_heat_rate_curves) as heat_rates
        USING(project, heat_rate_curves_scenario_id)
        WHERE project_portfolio_scenario_id = {}
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            "gen_simple_strike_price",
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    # Convert inputs to data frame
    hr_df = cursor_to_df(heat_rates)

    # Check that there is only one load point (constant heat rate)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_heat_rate_curves",
        severity="Mid",
        errors=validate_single_input(
            df=hr_df,
            msg="gen_simple_strike_price can only have one load point (constant "
            "heat rate).",
        ),
    )

    # Check that the project does not have any reserve BAs assigned to it
    projects_by_reserve = get_projects_by_reserve(scenario_id, subscenarios, conn)
    for reserve, projects_w_ba in projects_by_reserve.items():
        table = "inputs_project_" + reserve + "_bas"
        reserve_errors = validate_idxs(
            actual_idxs=opchar_df["project"],
            invalid_idxs=projects_w_ba,
            msg="gen_simple_strike_price cannot provide {}.".format(reserve),
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
            db_table=table,
            severity="Mid",
            errors=reserve_errors,
        )
