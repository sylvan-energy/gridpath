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


from pyomo.environ import Expression

from gridpath.auxiliary.dynamic_components import cost_components


def generic_record_dynamic_components(
    dynamic_components, objective_function_reserve_penalty_cost_component
):
    """
    Add total reserve penalty to cost components dynamic components

    :param dynamic_components:
    :param objective_function_reserve_penalty_cost_component:
    :return:
    """
    getattr(dynamic_components, cost_components).append(
        objective_function_reserve_penalty_cost_component
    )


def generic_add_model_components(
    m,
    d,
    scenario_directory,
    subproblem,
    stage,
    reserve_zone_set,
    reserve_violation_expression,
    reserve_violation_penalty_param,
    objective_function_reserve_penalty_cost_component,
):
    """
    Aggregate reserve violation penalty costs
    :param m:
    :param d:
    :param reserve_zone_set:
    :param reserve_violation_expression:
    :param reserve_violation_penalty_param:
    :param objective_function_reserve_penalty_cost_component:
    :return:
    """

    # Add violation penalty costs incurred to objective function
    def penalty_costs_rule(mod):
        return sum(
            getattr(mod, reserve_violation_expression)[ba, tmp]
            * getattr(mod, reserve_violation_penalty_param)[ba]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (ba, tmp) in getattr(mod, reserve_zone_set) * mod.TMPS
        )

    setattr(
        m,
        objective_function_reserve_penalty_cost_component,
        Expression(rule=penalty_costs_rule),
    )
