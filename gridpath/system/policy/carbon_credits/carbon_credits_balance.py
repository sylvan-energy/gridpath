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

from pyomo.environ import Var, NonNegativeReals, Constraint, Expression, value

from gridpath.auxiliary.dynamic_components import (
    carbon_credits_balance_generation_components,
    carbon_credits_balance_purchase_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.carbon_credits import CARBON_CREDITS_ZONE_PRD_DF


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

    def total_credits_generated_rule(mod, z, p):
        return sum(
            getattr(mod, c)[z, p]
            for c in getattr(d, carbon_credits_balance_generation_components)
        )

    m.Total_Carbon_Credits_Generated = Expression(
        m.CARBON_CREDITS_ZONES, m.PERIODS, rule=total_credits_generated_rule
    )

    # Aggregate all costs
    def total_credits_purchased_rule(mod, z, p):
        return sum(
            getattr(mod, c)[z, p]
            for c in getattr(d, carbon_credits_balance_purchase_components)
        )

    m.Total_Carbon_Credits_Purchased = Expression(
        m.CARBON_CREDITS_ZONES, m.PERIODS, rule=total_credits_purchased_rule
    )

    def track_available_credits(mod, z, prd):
        return (
            mod.Total_Carbon_Credits_Purchased[z, prd]
            <= mod.Total_Carbon_Credits_Generated[z, prd]
        )

    m.Track_Carbon_Credits_Constraint = Constraint(
        m.CARBON_CREDITS_ZONES, m.PERIODS, rule=track_available_credits
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
        "total_generated_carbon_credits",
        "total_purchased_carbon_credits",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_Carbon_Credits_Generated[z, p]),
            value(m.Total_Carbon_Credits_Purchased[z, p]),
        ]
        for z in m.CARBON_CREDITS_ZONES
        for p in m.PERIODS
    ]
    results_df = create_results_df(
        index_columns=["carbon_credits_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, CARBON_CREDITS_ZONE_PRD_DF), results_df)
