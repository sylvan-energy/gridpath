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
Simplest implementation with a MWh target by period.
"""

import csv
import os.path
import pandas as pd

from pyomo.environ import Var, Constraint, NonNegativeReals, Expression, value

from gridpath.auxiliary.dynamic_components import (
    period_energy_target_balance_contribution_components,
)
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.policy.energy_targets import ENERGY_TARGET_ZONE_PRD_DF


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

    m.Period_Energy_Target_Shortage_MWh = Var(
        m.ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET, within=NonNegativeReals
    )

    def violation_expression_rule(mod, z, p):
        if mod.energy_target_allow_violation[z]:
            return mod.Period_Energy_Target_Shortage_MWh[z, p]
        else:
            return 0

    m.Period_Energy_Target_Shortage_MWh_Expression = Expression(
        m.ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET, rule=violation_expression_rule
    )

    m.Total_Period_Energy_Target_Contributions_from_All_Sources_Expression = Expression(
        m.ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET,
        rule=lambda mod, z, p: sum(
            getattr(mod, component)[z, p]
            for component in getattr(
                d, period_energy_target_balance_contribution_components
            )
        ),
    )

    def energy_target_rule(mod, z, p):
        """
        Total delivered energy-target-eligible energy from all sources
        (projects, net of transmission losses counted against the target)
        must exceed the target
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return (
            mod.Total_Period_Energy_Target_Contributions_from_All_Sources_Expression[
                z, p
            ]
            + mod.Period_Energy_Target_Shortage_MWh_Expression[z, p]
            >= mod.Period_Energy_Target[z, p]
        )

    m.Period_Energy_Target_Constraint = Constraint(
        m.ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET, rule=energy_target_rule
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
        "energy_target_mwh",
        "total_energy_target_energy_mwh",
        "fraction_of_energy_target_met",
        "fraction_of_energy_target_energy_curtailed",
        "energy_target_shortage_mwh",
        "dual",
        "energy_target_marginal_cost_per_mwh",
    ]
    data = [
        [
            z,
            p,
            value(m.Period_Energy_Target[z, p]),
            value(m.Total_Delivered_Period_Energy_Target_Energy_MWh[z, p])
            + value(m.Total_Curtailed_Period_Energy_Target_Energy_MWh[z, p]),
            (
                1
                if float(m.period_energy_target_mwh[z, p]) == 0
                else value(m.Total_Delivered_Period_Energy_Target_Energy_MWh[z, p])
                / float(m.period_energy_target_mwh[z, p])
            ),
            (
                0
                if (
                    value(m.Total_Delivered_Period_Energy_Target_Energy_MWh[z, p])
                    + value(m.Total_Curtailed_Period_Energy_Target_Energy_MWh[z, p])
                )
                == 0
                else value(m.Total_Curtailed_Period_Energy_Target_Energy_MWh[z, p])
                / (
                    value(m.Total_Delivered_Period_Energy_Target_Energy_MWh[z, p])
                    + value(m.Total_Curtailed_Period_Energy_Target_Energy_MWh[z, p])
                )
            ),
            value(m.Period_Energy_Target_Shortage_MWh_Expression[z, p]),
            (
                duals_wrapper(m, getattr(m, "Period_Energy_Target_Constraint")[z, p])
                if (z, p)
                in [idx for idx in getattr(m, "Period_Energy_Target_Constraint")]
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(
                        m, getattr(m, "Period_Energy_Target_Constraint")[z, p]
                    ),
                    m.period_objective_coefficient[p],
                )
                if (z, p)
                in [idx for idx in getattr(m, "Period_Energy_Target_Constraint")]
                else None
            ),
        ]
        for (z, p) in m.ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET
    ]
    results_df = create_results_df(
        index_columns=["energy_target_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, ENERGY_TARGET_ZONE_PRD_DF), results_df)


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
    instance.constraint_indices["Period_Energy_Target_Constraint"] = [
        "energy_target_zone",
        "period",
        "dual",
    ]
