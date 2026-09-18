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
This module adds market revenue and costs to the objective function components.
"""

from pyomo.environ import Expression

from gridpath.auxiliary.dynamic_components import cost_components, revenue_components


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
    :param m: the Pyomo abstract model object we are adding components to
    :param d: the DynamicComponents class object we will get components from

    Here, we aggregate total market revenue and costs, and add them as a
    dynamic component to the objective function.

    """

    def total_market_net_cost_init(mod):
        return sum(
            mod.Net_Market_Purchased_Power[lz, market, tmp]
            * mod.market_price[market, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (lz, market, tmp) in mod.LZ_MARKETS * mod.TMPS
            if not mod.no_market_participation_in_stage[lz, market]
        )

    m.Total_Market_Net_Cost = Expression(initialize=total_market_net_cost_init)

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total load balance penalty costs to cost components
    """

    getattr(dynamic_components, cost_components).append("Total_Market_Net_Cost")
