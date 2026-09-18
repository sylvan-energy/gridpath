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

    def total_capacity_transfer_costs_rule(mod):
        return sum(
            mod.Capacity_Transfer_Costs_Per_Yr_in_Period[prm_z_from, prm_z_to, prd]
            * mod.number_years_represented[prd]
            * mod.probability_weighted_discount_factor[prd]
            for (prm_z_from, prm_z_to) in mod.PRM_ZONES_CAPACITY_TRANSFER_ZONES
            for prd in mod.PERIODS
        )

    m.Total_Capacity_Transfer_Costs = Expression(
        rule=total_capacity_transfer_costs_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total prm shortage penalty costs to cost components
    """

    getattr(dynamic_components, cost_components).append("Total_Capacity_Transfer_Costs")
