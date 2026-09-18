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
This module adds horizon energy-target shortage penalty costs to the objective
function.
"""

from pyomo.environ import Expression, NonNegativeReals

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
    :param m: the Pyomo abstract model object we are adding components to
    :param d: the DynamicComponents class object we will get components from

    Here, we aggregate total penalty costs for not meeting the energy-target constraint.
    """

    def total_penalty_costs_rule(mod):
        return sum(
            mod.Horizon_Energy_Target_Shortage_MWh_Expression[z, bt, h]
            * mod.energy_target_violation_penalty_per_mwh[z]
            * mod.number_years_represented[mod.period[mod.last_hrz_tmp[bt, h]]]
            * mod.probability_weighted_discount_factor[
                mod.period[mod.last_hrz_tmp[bt, h]]
            ]
            for (z, bt, h) in mod.ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET
        )

    m.Total_Horizon_Energy_Target_Balance_Penalty_Costs = Expression(
        rule=total_penalty_costs_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total energy_target balance penalty costs to cost components
    """

    getattr(dynamic_components, cost_components).append(
        "Total_Horizon_Energy_Target_Balance_Penalty_Costs"
    )
