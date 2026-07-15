# Copyright 2016-2025 Blue Marble Analytics LLC.
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


import os.path
from pyomo.environ import Param, Expression, value

from gridpath.auxiliary.dynamic_components import cost_components
from gridpath.common_functions import create_results_df


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

    def total_release_violation_penalty_cost_rule(mod):
        """
        :param mod:
        :return:
        """
        return sum(
            mod.Target_Release_Violation_VolUnit[r, bt, h]
            * mod.target_release_violation_cost[r]
            * mod.number_years_represented[mod.period[mod.last_hrz_tmp[bt, h]]]
            * mod.discount_factor[mod.period[mod.last_hrz_tmp[bt, h]]]
            for (
                r,
                bt,
                h,
            ) in mod.WATER_NODE_RESERVOIR_BT_HRZS_WITH_TOTAL_RELEASE_REQUIREMENTS
        )

    m.Total_Release_Violation_Penalty_Cost = Expression(
        rule=total_release_violation_penalty_cost_rule
    )

    def total_min_water_storage_violation_penalty_cost_rule(mod):
        """
        :param mod:
        :return:
        """
        return sum(
            mod.Min_Reservoir_Storage_Violation[r, tmp]
            * mod.min_volume_violation_cost[r]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.discount_factor[mod.period[tmp]]
            for r in mod.WATER_NODES_W_RESERVOIRS
            for tmp in mod.TMPS
        )

    m.Total_Min_Water_Storage_Violation_Penalty_Cost = Expression(
        rule=total_min_water_storage_violation_penalty_cost_rule
    )

    def total_max_water_storage_violation_penalty_cost_rule(mod):
        """
        :param mod:
        :return:
        """
        return sum(
            mod.Max_Reservoir_Storage_Violation[r, tmp]
            * mod.max_volume_violation_cost[r]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.discount_factor[mod.period[tmp]]
            for r in mod.WATER_NODES_W_RESERVOIRS
            for tmp in mod.TMPS
        )

    m.Total_Max_Water_Storage_Violation_Penalty_Cost = Expression(
        rule=total_max_water_storage_violation_penalty_cost_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add tuning costs to cost components
    """

    getattr(dynamic_components, cost_components).append(
        "Total_Release_Violation_Penalty_Cost"
    )

    getattr(dynamic_components, cost_components).append(
        "Total_Min_Water_Storage_Violation_Penalty_Cost"
    )

    getattr(dynamic_components, cost_components).append(
        "Total_Max_Water_Storage_Violation_Penalty_Cost"
    )
