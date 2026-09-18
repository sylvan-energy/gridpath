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
This module aggregates transmission-line-period-level capacity costs
for use in the objective function.
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
    """

    :param m:
    :param d:
    :return:
    """

    def total_tx_capacity_cost_rule(mod):
        """
        **Expression Name**: Total_Tx_Capacity_Costs

        The total transmission capacity cost is equal to the transmission
        capacity cost times the period's probability-weighted discount factor
        times the number of
        years represented in the period, summed up for each of the periods.
        """
        return sum(
            mod.Tx_Capacity_Cost_in_Period[g, p]
            * mod.probability_weighted_discount_factor[p]
            * mod.number_years_represented[p]
            for (g, p) in mod.TX_FIN_PRDS
        )

    m.Total_Tx_Capacity_Costs = Expression(rule=total_tx_capacity_cost_rule)

    def total_tx_fixed_cost_rule(mod):
        return sum(
            mod.Tx_Fixed_Cost_in_Period[g, p]
            * mod.probability_weighted_discount_factor[p]
            * mod.number_years_represented[p]
            for (g, p) in mod.TX_OPR_PRDS
        )

    m.Total_Tx_Fixed_Costs = Expression(rule=total_tx_fixed_cost_rule)

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total transmission capacity costs to cost components
    """

    getattr(dynamic_components, cost_components).append("Total_Tx_Capacity_Costs")
    getattr(dynamic_components, cost_components).append("Total_Tx_Fixed_Costs")
