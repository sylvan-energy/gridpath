# Copyright 2016-2023 Blue Marble Analytics LLC.
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
This module aggregates all project operational costs and adds them to the
objective function.
"""

from pyomo.environ import Expression

from gridpath.auxiliary.dynamic_components import cost_components


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
    r"""
    :param m: the Pyomo abstract model object we are adding the components to
    :param d: the DynamicComponents class object we are adding components to

    Here, we sum up all operational costs. Operational costs include
    variable O&M costs, fuel costs, startup costs, and shutdown costs.

    :math:`Total\_Variable\_OM\_Cost =
    \sum_{(r, tmp)\in {RT}}{Variable\_OM\_Cost_{r, tmp}
    \\times number\_of\_hours\_in\_timepoint_{tmp}
    \\times horizon\_weight_{h^{tmp}}
    \\times number\_years\_represented_{p^{tmp}}
    \\times probability\_weighted\_discount\_factor_{p^{tmp}}}`

    :math:`Total\_Fuel\_Cost =
    \sum_{(r, tmp)\in {RT}}{Fuel\_Cost_{r, tmp}
    \\times number\_of\_hours\_in\_timepoint_{tmp}
    \\times horizon\_weight_{h^{tmp}}
    \\times number\_years\_represented_{p^{tmp}}
    \\times probability\_weighted\_discount\_factor_{p^{tmp}}}`

    """

    # Power production variable costs
    def total_variable_om_cost_rule(mod):
        """
        Power production cost for all generators across all timepoints
        :param mod:
        :return:
        """
        return sum(
            mod.Variable_OM_Cost[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.VAR_OM_COST_ALL_PRJS_OPR_TMPS
        )

    m.Total_Variable_OM_Cost = Expression(rule=total_variable_om_cost_rule)

    # Fuel cost
    def total_fuel_cost_rule(mod):
        """
        Fuel costs for all generators across all timepoints
        :param mod:
        :return:
        """
        return sum(
            mod.Fuel_Cost[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.FUEL_PRJ_OPR_TMPS
        )

    m.Total_Fuel_Cost = Expression(rule=total_fuel_cost_rule)

    # Startup and shutdown costs
    def total_startup_cost_rule(mod):
        """
        Sum startup costs for the objective function term.
        :param mod:
        :return:
        """
        return sum(
            mod.Startup_Cost[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.STARTUP_COST_PRJ_OPR_TMPS
        )

    m.Total_Startup_Cost = Expression(rule=total_startup_cost_rule)

    def total_shutdown_cost_rule(mod):
        """
        Sum shutdown costs for the objective function term.
        :param mod:
        :return:
        """
        return sum(
            mod.Shutdown_Cost[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.SHUTDOWN_COST_PRJ_OPR_TMPS
        )

    m.Total_Shutdown_Cost = Expression(rule=total_shutdown_cost_rule)

    def total_operational_violation_cost_rule(mod):
        """
        Sum operational constraint violation costs for the objective function
        term.
        """
        return sum(
            mod.Operational_Violation_Cost[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.VIOL_ALL_PRJ_OPR_TMPS
        )

    m.Total_Operational_Violation_Cost = Expression(
        rule=total_operational_violation_cost_rule
    )

    def total_curtailment_cost_rule(mod):
        """
        Sum curtailment costs for the objective function term.
        :param mod:
        :return:
        """
        return sum(
            mod.Curtailment_Cost[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.CURTAILMENT_COST_PRJ_OPR_TMPS
        )

    m.Total_Curtailment_Cost = Expression(rule=total_curtailment_cost_rule)

    def total_soc_penalty_cost_rule(mod):
        """
        Sum curtailment costs for the objective function term.
        :param mod:
        :return:
        """
        return sum(
            mod.SOC_Penalty_Cost[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.SOC_PENALTY_COST_PRJ_OPR_TMPS
        )

    m.Total_SOC_Penalty_Cost = Expression(rule=total_soc_penalty_cost_rule)

    def total_soc_last_tmp_penalty_cost_rule(mod):
        """
        Sum last tmp penalty costs for the objective function term.
        :param mod:
        :return:
        """
        return sum(
            mod.SOC_Penalty_Last_Tmp_Cost[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.SOC_LAST_TMP_PENALTY_COST_PRJ_OPR_TMPS
        )

    m.Total_SOC_Penalty_Last_Tmp_Cost = Expression(
        rule=total_soc_last_tmp_penalty_cost_rule
    )

    def total_peak_deviation_monthly_demand_charge_cost_rule(mod):
        """
        Sum demand charges for each pr, prd, month.
        :param mod:
        :return:
        """
        return sum(
            mod.Peak_Deviation_Demand_Charge_Cost[g, prd, mnth]
            * mod.number_years_represented[prd]
            * mod.probability_weighted_discount_factor[prd]
            for (g, prd) in mod.PRJ_OPR_PRDS
            for mnth in mod.MONTHS
        )

    m.Total_Peak_Deviation_Monthly_Demand_Charge_Cost = Expression(
        rule=total_peak_deviation_monthly_demand_charge_cost_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add operational costs to the objective-function dynamic components.
    """

    getattr(dynamic_components, cost_components).append("Total_Variable_OM_Cost")
    getattr(dynamic_components, cost_components).append("Total_Fuel_Cost")
    getattr(dynamic_components, cost_components).append("Total_Startup_Cost")
    getattr(dynamic_components, cost_components).append("Total_Shutdown_Cost")
    getattr(dynamic_components, cost_components).append(
        "Total_Operational_Violation_Cost"
    )
    getattr(dynamic_components, cost_components).append("Total_Curtailment_Cost")
    getattr(dynamic_components, cost_components).append("Total_SOC_Penalty_Cost")
    getattr(dynamic_components, cost_components).append(
        "Total_SOC_Penalty_Last_Tmp_Cost"
    )
    getattr(dynamic_components, cost_components).append(
        "Total_Peak_Deviation_Monthly_Demand_Charge_Cost"
    )
