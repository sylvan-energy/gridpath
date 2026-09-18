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
This module aggregates all project capacity costs and adds them to the
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

    Here, we sum up all capacity-related costs and add them to the
    objective-function dynamic components.

    :math:`Total\_Capacity\_Costs =
    \sum_{(r, p)\in {RP}}{Capacity\_Cost\_in\_Period_{r, p} \\times
    probability\_weighted\_discount\_factor_p \\times number\_years\_represented_p}`

    """

    # Add costs to objective function
    def total_capacity_cost_rule(mod):
        return sum(
            mod.Capacity_Cost_in_Period[g, p]
            * mod.probability_weighted_discount_factor[p]
            * mod.number_years_represented[p]
            for (g, p) in mod.PRJ_FIN_PRDS
        )

    m.Total_Capacity_Costs = Expression(rule=total_capacity_cost_rule)

    def total_energy_cost_rule(mod):
        return sum(
            mod.Energy_Cost_in_Period[g, p]
            * mod.probability_weighted_discount_factor[p]
            * mod.number_years_represented[p]
            for (g, p) in mod.PRJ_FIN_PRDS
        )

    m.Total_Energy_Costs = Expression(rule=total_energy_cost_rule)

    def total_fixed_cost_rule(mod):
        return sum(
            mod.Fixed_Cost_in_Period[g, p]
            * mod.probability_weighted_discount_factor[p]
            * mod.number_years_represented[p]
            for (g, p) in mod.PRJ_OPR_PRDS
        )

    m.Total_Fixed_Costs = Expression(rule=total_fixed_cost_rule)

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total capacity costs to cost components
    """

    getattr(dynamic_components, cost_components).append("Total_Capacity_Costs")
    getattr(dynamic_components, cost_components).append("Total_Energy_Costs")
    getattr(dynamic_components, cost_components).append("Total_Fixed_Costs")
