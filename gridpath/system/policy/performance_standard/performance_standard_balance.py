# Copyright 2022 (c) Crown Copyright, GC.
# Modifications Copyright 2016-2023 Blue Marble Analytics.
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
Constrain total carbon emissions to be less than performance standard
"""

from pyomo.environ import Var, Constraint, Expression, NonNegativeReals, value

from gridpath.auxiliary.dynamic_components import (
    performance_standard_balance_emission_components,
    performance_standard_balance_credit_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.performance_standard import PERFORMANCE_STANDARD_Z_PRD_DF

Infinity = float("inf")


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

    # Performance standard per energy unit
    m.Performance_Standard_Energy_Unit_Overage = Var(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        within=NonNegativeReals,
    )

    def violation_expression_energy_rule(mod, z, p):
        if mod.performance_standard_energy_allow_violation[z]:
            return mod.Performance_Standard_Energy_Unit_Overage[z, p]
        else:
            return 0

    m.Performance_Standard_Energy_Unit_Overage_Expression = Expression(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=violation_expression_energy_rule,
    )

    m.Total_Performance_Standard_Emissions_from_All_Sources_Expression = Expression(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=lambda mod, z, p: sum(
            getattr(mod, component)[z, p]
            for component in getattr(
                d, performance_standard_balance_emission_components
            )
        ),
    )

    m.Total_Performance_Standard_Credits_from_All_Sources_Expression = Expression(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=lambda mod, z, p: sum(
            getattr(mod, component)[z, p]
            for component in getattr(d, performance_standard_balance_credit_components)
        ),
    )

    def performance_standard_energy_rule(mod, z, p):
        """
        Total carbon emitted must be less than performance standard
        :param mod:
        :param z:
        :param p:
        :return:
        """
        var = mod.performance_standard_tco2_per_mwh[z, p]
        if var == Infinity:
            return Constraint.Skip
        else:
            return (
                mod.Total_Performance_Standard_Emissions_from_All_Sources_Expression[
                    z, p
                ]
                - mod.Performance_Standard_Energy_Unit_Overage_Expression[z, p]
                <= (
                    mod.Total_Performance_Standard_Project_Energy[z, p]
                    * mod.performance_standard_tco2_per_mwh[z, p]
                )
                + mod.Total_Performance_Standard_Credits_from_All_Sources_Expression[
                    z, p
                ]
            )

    m.Performance_Standard_Energy_Unit_Constraint = Constraint(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=performance_standard_energy_rule,
    )

    # Performance standard per power unit
    m.Performance_Standard_Power_Unit_Overage = Var(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        within=NonNegativeReals,
    )

    def violation_expression_power_rule(mod, z, p):
        if mod.performance_standard_power_allow_violation[z]:
            return mod.Performance_Standard_Power_Unit_Overage[z, p]
        else:
            return 0

    m.Performance_Standard_Power_Unit_Overage_Expression = Expression(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=violation_expression_power_rule,
    )

    def performance_standard_power_rule(mod, z, p):
        """
        Total carbon emitted must be less than performance standard
        :param mod:
        :param z:
        :param p:
        :return:
        """
        var = mod.performance_standard_tco2_per_mw[z, p]
        if var == Infinity:
            return Constraint.Skip
        else:
            return (
                mod.Total_Performance_Standard_Emissions_from_All_Sources_Expression[
                    z, p
                ]
                - mod.Performance_Standard_Power_Unit_Overage_Expression[z, p]
                <= (
                    mod.Total_Performance_Standard_Project_Capacity[z, p]
                    * mod.performance_standard_tco2_per_mw[z, p]
                )
                + mod.Total_Performance_Standard_Credits_from_All_Sources_Expression[
                    z, p
                ]
            )

    m.Performance_Standard_Power_Unit_Constraint = Constraint(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=performance_standard_power_rule,
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
        "performance_standard_energy_overage_tco2",
        "performance_standard_power_overage_tco2",
    ]
    data = [
        [
            z,
            p,
            value(m.Performance_Standard_Energy_Unit_Overage_Expression[z, p]),
            value(m.Performance_Standard_Power_Unit_Overage_Expression[z, p]),
        ]
        for (z, p) in m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD
    ]
    results_df = create_results_df(
        index_columns=["performance_standard_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PERFORMANCE_STANDARD_Z_PRD_DF), results_df)


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
    instance.constraint_indices["Performance_Standard_Energy_Unit_Constraint"] = [
        "performance_standard_zone",
        "period",
        "dual",
    ]
    instance.constraint_indices["Performance_Standard_Power_Unit_Constraint"] = [
        "performance_standard_zone",
        "period",
        "dual",
    ]
