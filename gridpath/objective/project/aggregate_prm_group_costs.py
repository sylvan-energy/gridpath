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
Aggregate capacity threshold costs.
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
    Sum up all PRM group costs and add to the objective function.
    :param m:
    :param d:
    :return:
    """

    # Add costs to objective function
    def total_deliverability_cost_rule(mod):
        return sum(
            mod.Deliverability_Group_Deliverable_Capacity_Cost[g, p]
            * mod.probability_weighted_discount_factor[p]
            * mod.number_years_represented[p]
            for g in mod.DELIVERABILITY_GROUPS
            for p in mod.PERIODS
        )

    m.Total_PRM_Deliverability_Group_Costs = Expression(
        rule=total_deliverability_cost_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total prm group costs to cost components
    """

    getattr(dynamic_components, cost_components).append(
        "Total_PRM_Deliverability_Group_Costs"
    )
