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
Add the carbon tax cost components.
"""

from pyomo.environ import value, NonNegativeReals, Var, Constraint

from gridpath.auxiliary.dynamic_components import carbon_tax_cost_components
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.carbon_tax import CARBON_TAX_ZONE_PRD_DF


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

    # Variables
    ###########################################################################

    m.Carbon_Tax_Cost = Var(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX, within=NonNegativeReals
    )

    # Constraints
    ###########################################################################
    def carbon_tax_cost_constraint_rule(mod, z, p):
        return mod.Carbon_Tax_Cost[z, p] >= sum(
            getattr(mod, component)[z, p]
            for component in getattr(d, carbon_tax_cost_components)
        )

    m.Carbon_Tax_Cost_Constraint = Constraint(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX, rule=carbon_tax_cost_constraint_rule
    )


def export_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    m,
    d,
):
    """

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """
    results_columns = [
        "carbon_tax_per_ton",
        "total_carbon_emissions_tons",
        "total_carbon_tax_allowance_tons",
        "total_carbon_tax_cost",
    ]
    data = [
        [
            z,
            p,
            float(m.carbon_tax[z, p]),
            value(m.Total_Carbon_Tax_Project_Emissions[z, p]),
            value(m.Total_Carbon_Tax_Project_Allowance[z, p]),
            value(m.Carbon_Tax_Cost[z, p]),
        ]
        for (z, p) in m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX
    ]
    results_df = create_results_df(
        index_columns=["carbon_tax_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, CARBON_TAX_ZONE_PRD_DF), results_df)
