# Copyright 2026 Sylvan Energy Analytics LLC.
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
This module aggregates the cost of curtailment applied to transmission
losses in each timepoint and adds the total to the objective function.
"""

from pyomo.environ import Expression

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

    def total_tx_curtailment_cost_rule(mod):
        """ """
        return sum(
            mod.Tx_Curtailment_Cost[tx, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.discount_factor[mod.period[tmp]]
            for (tx, tmp) in mod.TX_CURTAILMENT_COST_TX_LINE_OPR_TMPS
        )

    m.Total_Tx_Curtailment_Cost = Expression(rule=total_tx_curtailment_cost_rule)

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total transmission curtailment costs to cost components
    """

    getattr(dynamic_components, cost_components).append("Total_Tx_Curtailment_Cost")
