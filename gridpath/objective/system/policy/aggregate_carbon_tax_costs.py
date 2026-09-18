# Copyright 2021 (c) Crown Copyright, GC.
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
This module aggregates carbon tax costs for use in the objective function.
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
    :param m: the Pyomo abstract model object we are adding components to
    :param d: the DynamicComponents class object we will get components from

    Here, we sum up all carbon tax costs.
    """

    def total_carbon_tax_cost_rule(mod):
        return sum(
            mod.Carbon_Tax_Cost[z, p]
            * mod.number_years_represented[p]
            * mod.probability_weighted_discount_factor[p]
            for (z, p) in mod.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX
        )

    m.Total_Carbon_Tax_Cost = Expression(rule=total_carbon_tax_cost_rule)

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total carbon tax costs to cost components

    """

    getattr(dynamic_components, cost_components).append("Total_Carbon_Tax_Cost")
