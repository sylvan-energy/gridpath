# Copyright 2022 (c) Crown Copyright, GC.
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
This module adds performance standard overage penalty costs to the objective function.
"""

import os.path
from pyomo.environ import Param, Expression, NonNegativeReals

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

    Here, we aggregate total penalty costs for not meeting the performance standard
    constraint.
    """

    def total_penalty_costs_energy_rule(mod):
        return sum(
            mod.Performance_Standard_Energy_Unit_Overage_Expression[z, p]
            * mod.performance_standard_energy_violation_penalty_per_emission[z]
            * mod.number_years_represented[p]
            * mod.probability_weighted_discount_factor[p]
            for (
                z,
                p,
            ) in mod.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD
        )

    m.Total_Performance_Standard_Energy_Balance_Penalty_Costs = Expression(
        rule=total_penalty_costs_energy_rule
    )

    def total_penalty_costs_power_rule(mod):
        return sum(
            mod.Performance_Standard_Power_Unit_Overage_Expression[z, p]
            * mod.performance_standard_power_violation_penalty_per_emission[z]
            * mod.number_years_represented[p]
            * mod.probability_weighted_discount_factor[p]
            for (
                z,
                p,
            ) in mod.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD
        )

    m.Total_Performance_Standard_Power_Balance_Penalty_Costs = Expression(
        rule=total_penalty_costs_power_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total carbon cap penalty costs to cost components

    """

    getattr(dynamic_components, cost_components).append(
        "Total_Performance_Standard_Energy_Balance_Penalty_Costs"
    )
    getattr(dynamic_components, cost_components).append(
        "Total_Performance_Standard_Power_Balance_Penalty_Costs"
    )
