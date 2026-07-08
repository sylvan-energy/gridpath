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
Constraint total carbon emissions to be less than cap
"""

from pyomo.environ import Var, Constraint, Expression, NonNegativeReals, value

from gridpath.auxiliary.dynamic_components import (
    carbon_cap_balance_emission_components,
    carbon_cap_balance_credit_components,
)
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.policy.carbon_cap import CARBON_CAP_ZONE_PRD_DF


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

    m.Carbon_Cap_Overage = Var(
        m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP, within=NonNegativeReals
    )

    def violation_expression_rule(mod, z, p):
        if mod.carbon_cap_allow_violation[z]:
            return mod.Carbon_Cap_Overage[z, p]
        else:
            return 0

    m.Carbon_Cap_Overage_Expression = Expression(
        m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP, rule=violation_expression_rule
    )

    m.Total_Carbon_Emissions_from_All_Sources_Expression = Expression(
        m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP,
        rule=lambda mod, z, p: sum(
            getattr(mod, component)[z, p]
            for component in getattr(d, carbon_cap_balance_emission_components)
        ),
    )

    m.Total_Carbon_Credits_from_All_Sources_Expression = Expression(
        m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP,
        rule=lambda mod, z, p: sum(
            getattr(mod, component)[z, p]
            for component in getattr(d, carbon_cap_balance_credit_components)
        ),
    )

    def carbon_cap_target_rule(mod, z, p):
        """
        Total carbon emitted must be less than target
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return (
            mod.Total_Carbon_Emissions_from_All_Sources_Expression[z, p]
            - mod.Carbon_Cap_Overage_Expression[z, p]
            <= mod.carbon_cap_target[z, p]
            + mod.Total_Carbon_Credits_from_All_Sources_Expression[z, p]
        )

    m.Carbon_Cap_Constraint = Constraint(
        m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP, rule=carbon_cap_target_rule
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
        "total_emissions",
        "total_credits",
        "dual",
        "carbon_cap_marginal_cost_per_emission",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_Carbon_Emissions_from_All_Sources_Expression[z, p]),
            value(m.Total_Carbon_Credits_from_All_Sources_Expression[z, p]),
            (
                duals_wrapper(m, getattr(m, "Carbon_Cap_Constraint")[z, p])
                if (z, p) in [idx for idx in getattr(m, "Carbon_Cap_Constraint")]
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(m, getattr(m, "Carbon_Cap_Constraint")[z, p]),
                    m.period_objective_coefficient[p],
                )
                if (z, p) in [idx for idx in getattr(m, "Carbon_Cap_Constraint")]
                else None
            ),
        ]
        for (z, p) in m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP
    ]
    results_df = create_results_df(
        index_columns=["carbon_cap_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, CARBON_CAP_ZONE_PRD_DF), results_df)


def save_duals(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    instance,
    dynamic_components,
):
    instance.constraint_indices["Carbon_Cap_Constraint"] = [
        "carbon_cap_zone",
        "period",
        "dual",
    ]
