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
Tuning costs to prevent undesirable behavior when problem is degenerate.
E.g. since the cost incurred by hydro over the course of a horizon is the same
regardless of exact dispatch, cases may arise when the project is ramped
unnecessarily unless there's a cost on the ramp. This aggregates the tuning
costs imposed on hydro to prevent this behavior.
"""

from pyomo.environ import Param, Expression

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

    :param m:
    :param d:
    :return:
    """

    def total_ramp_tuning_cost_rule(mod):
        """
        Ramp tuning costs for all projects
        :param mod:
        :return:
        """
        return sum(
            (mod.Ramp_Up_Tuning_Cost[g, tmp] + mod.Ramp_Down_Tuning_Cost[g, tmp])
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.discount_factor[mod.period[tmp]]
            for (g, tmp) in mod.TUNING_COST_PRJ_OPR_TMPS
        )

    m.Total_Ramp_Tuning_Cost = Expression(rule=total_ramp_tuning_cost_rule)

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add tuning costs to cost components
    """

    getattr(dynamic_components, cost_components).append("Total_Ramp_Tuning_Cost")
