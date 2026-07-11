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
Constraint total PRM contribution to be more than or equal to the requirement.
"""

import csv
import os.path

from pyomo.environ import Var, Constraint, Expression, NonNegativeReals, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.dynamic_components import prm_balance_provision_components
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.reliability.prm import PRM_ZONE_PRD_DF


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

    m.Total_PRM_from_All_Sources_Expression = Expression(
        m.PRM_ZONE_PERIODS_WITH_REQUIREMENT,
        rule=lambda mod, z, p: sum(
            getattr(mod, component)[z, p]
            for component in getattr(d, prm_balance_provision_components)
        ),
    )

    m.PRM_Shortage_MW = Var(
        m.PRM_ZONE_PERIODS_WITH_REQUIREMENT, within=NonNegativeReals
    )

    def violation_expression_rule(mod, z, p):
        if mod.prm_allow_violation[z]:
            return mod.PRM_Shortage_MW[z, p]
        else:
            return 0

    m.PRM_Shortage_MW_Expression = Expression(
        m.PRM_ZONE_PERIODS_WITH_REQUIREMENT, rule=violation_expression_rule
    )

    def prm_requirement_rule(mod, z, p):
        """
        Total PRM provision must be greater than or equal to the requirement
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return (
            mod.Total_PRM_from_All_Sources_Expression[z, p]
            + mod.PRM_Shortage_MW_Expression[z, p]
            >= mod.prm_requirement_mw[z, p]
        )

    m.PRM_Constraint = Constraint(
        m.PRM_ZONE_PERIODS_WITH_REQUIREMENT, rule=prm_requirement_rule
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
        "elcc_total_mw",
        "prm_shortage_mw",
        "dual",
        "prm_marginal_cost_per_mw",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_PRM_from_All_Sources_Expression[z, p]),
            value(m.PRM_Shortage_MW_Expression[z, p]),
            (
                duals_wrapper(m, getattr(m, "PRM_Constraint")[z, p])
                if (z, p) in [idx for idx in getattr(m, "PRM_Constraint")]
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(m, getattr(m, "PRM_Constraint")[z, p]),
                    m.period_objective_coefficient[p],
                )
                if (z, p) in [idx for idx in getattr(m, "PRM_Constraint")]
                else None
            ),
        ]
        for (z, p) in m.PRM_ZONE_PERIODS_WITH_REQUIREMENT
    ]
    results_df = create_results_df(
        index_columns=["prm_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PRM_ZONE_PRD_DF), results_df)


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
    instance.constraint_indices["PRM_Constraint"] = ["prm_zone", "period", "dual"]
