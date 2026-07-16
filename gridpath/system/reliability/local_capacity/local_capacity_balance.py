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
Constraint total local capacity contribution to be more than or equal to the
requirement.
"""

import csv
import os.path

from pyomo.environ import Var, Constraint, Expression, NonNegativeReals, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.dynamic_components import (
    local_capacity_balance_provision_components,
)
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.reliability.local_capacity import LOCAL_CAPACITY_ZONE_PRD_DF


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

    m.Total_Local_Capacity_from_All_Sources_Expression_MW = Expression(
        m.LOCAL_CAPACITY_ZONE_PERIODS_WITH_REQUIREMENT,
        rule=lambda mod, z, p: sum(
            getattr(mod, component)[z, p]
            for component in getattr(d, local_capacity_balance_provision_components)
        ),
    )

    m.Local_Capacity_Shortage_MW = Var(
        m.LOCAL_CAPACITY_ZONE_PERIODS_WITH_REQUIREMENT, within=NonNegativeReals
    )

    def violation_expression_rule(mod, z, p):
        if mod.local_capacity_allow_violation[z]:
            return mod.Local_Capacity_Shortage_MW[z, p]
        else:
            return 0

    m.Local_Capacity_Shortage_MW_Expression = Expression(
        m.LOCAL_CAPACITY_ZONE_PERIODS_WITH_REQUIREMENT, rule=violation_expression_rule
    )

    def local_capacity_requirement_rule(mod, z, p):
        """
        Total local capacity provision must be greater than or equal to the
        requirement
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return (
            mod.Total_Local_Capacity_from_All_Sources_Expression_MW[z, p]
            + mod.Local_Capacity_Shortage_MW_Expression[z, p]
            >= mod.local_capacity_requirement_mw[z, p]
        )

    m.Local_Capacity_Constraint = Constraint(
        m.LOCAL_CAPACITY_ZONE_PERIODS_WITH_REQUIREMENT,
        rule=local_capacity_requirement_rule,
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
        "local_capacity_provision_mw",
        "local_capacity_shortage_mw",
        "dual",
        "local_capacity_marginal_cost_per_mw",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_Local_Capacity_from_All_Sources_Expression_MW[z, p]),
            value(m.Local_Capacity_Shortage_MW_Expression[z, p]),
            (
                duals_wrapper(m, getattr(m, "Local_Capacity_Constraint")[z, p])
                if (z, p) in [idx for idx in getattr(m, "Local_Capacity_Constraint")]
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(m, getattr(m, "Local_Capacity_Constraint")[z, p]),
                    m.period_objective_coefficient[p],
                )
                if (z, p) in [idx for idx in getattr(m, "Local_Capacity_Constraint")]
                else None
            ),
        ]
        for (z, p) in m.LOCAL_CAPACITY_ZONE_PERIODS_WITH_REQUIREMENT
    ]
    results_df = create_results_df(
        index_columns=["local_capacity_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, LOCAL_CAPACITY_ZONE_PRD_DF), results_df)


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
    instance.constraint_indices["Local_Capacity_Constraint"] = [
        "local_capacity_zone",
        "period",
        "dual",
    ]
