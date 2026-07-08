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
Aggregate carbon emissions and energy from the project-timepoint level to
the performance zone - period level.
"""

from pyomo.environ import Expression, value

from gridpath.auxiliary.dynamic_components import (
    performance_standard_balance_emission_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.performance_standard import PERFORMANCE_STANDARD_Z_PRD_DF


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

    def total_performance_standard_emissions_rule(mod, z, p):
        """
        Calculate total emissions from all performance standard projects in performance
        standard zone
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return sum(
            mod.Project_Carbon_Emissions[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (g, tmp) in mod.PERFORMANCE_STANDARD_OPR_TMPS
            if g in mod.PERFORMANCE_STANDARD_PRJS_BY_PERFORMANCE_STANDARD_ZONE[z]
            and tmp in mod.TMPS_IN_PRD[p]
        )

    m.Total_Performance_Standard_Project_Emissions = Expression(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=total_performance_standard_emissions_rule,
    )

    def total_performance_standard_energy_rule(mod, z, p):
        """
        Calculate total energy from all performance standard projects in performance
        standard zone
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return sum(
            mod.Bulk_Power_Provision_MW[g, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (g, tmp) in mod.PERFORMANCE_STANDARD_OPR_TMPS
            if g in mod.PERFORMANCE_STANDARD_PRJS_BY_PERFORMANCE_STANDARD_ZONE[z]
            and tmp in mod.TMPS_IN_PRD[p]
        )

    # We'll multiply this by the standard in the balance constraint
    # Note this is NOT added to the dynamic components
    m.Total_Performance_Standard_Project_Energy = Expression(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=total_performance_standard_energy_rule,
    )

    def total_performance_standard_capacity_rule(mod, z, p):
        """
        Calculate total capacity from all performance standard projects in performance
        standard zone
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return sum(
            mod.Capacity_MW[prj, prd]
            for (prj, prd) in mod.PERFORMANCE_STANDARD_OPR_PRDS
            if prj in mod.PERFORMANCE_STANDARD_PRJS_BY_PERFORMANCE_STANDARD_ZONE[z]
            and prd == p
        )

    # We'll multiply this by the standard in the balance constraint
    # Note this is NOT added to the dynamic components
    m.Total_Performance_Standard_Project_Capacity = Expression(
        m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD,
        rule=total_performance_standard_capacity_rule,
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    This method adds project emissions to carbon balance
    """

    getattr(
        dynamic_components, performance_standard_balance_emission_components
    ).append("Total_Performance_Standard_Project_Emissions")


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
        "performance_standard_project_emissions_tco2",
        "performance_standard_project_energy_mwh",
        "performance_standard_project_capacity_mw",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_Performance_Standard_Project_Emissions[z, p]),
            value(m.Total_Performance_Standard_Project_Energy[z, p]),
            value(m.Total_Performance_Standard_Project_Capacity[z, p]),
        ]
        for (z, p) in m.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD
    ]
    results_df = create_results_df(
        index_columns=["performance_standard_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PERFORMANCE_STANDARD_Z_PRD_DF), results_df)
