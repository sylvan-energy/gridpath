# Copyright 2016-2024 Blue Marble Analytics LLC.
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

    def total_min_flow_violation_penalty_cost_rule(mod):
        """
        :param mod:
        :return:
        """
        return sum(
            mod.Water_Link_Min_Flow_Violation_Vol_per_Sec_Expression[
                wl, dep_tmp, arr_tmp
            ]
            * mod.min_flow_violation_penalty_cost[wl]
            * mod.hrs_in_tmp[dep_tmp]
            * mod.tmp_weight[dep_tmp]
            * mod.number_years_represented[mod.period[dep_tmp]]
            * mod.discount_factor[mod.period[dep_tmp]]
            for (wl, dep_tmp, arr_tmp) in mod.WATER_LINK_DEPARTURE_ARRIVAL_TMPS
        )

    m.Total_Min_Flow_Violation_Penalty_Cost = Expression(
        rule=total_min_flow_violation_penalty_cost_rule
    )

    def total_max_flow_violation_penalty_cost_rule(mod):
        """
        :param mod:
        :return:
        """
        return sum(
            mod.Water_Link_Max_Flow_Violation_Vol_per_Sec_Expression[
                wl, dep_tmp, arr_tmp
            ]
            * mod.max_flow_violation_penalty_cost[wl]
            * mod.hrs_in_tmp[dep_tmp]
            * mod.tmp_weight[dep_tmp]
            * mod.number_years_represented[mod.period[dep_tmp]]
            * mod.discount_factor[mod.period[dep_tmp]]
            for (wl, dep_tmp, arr_tmp) in mod.WATER_LINK_DEPARTURE_ARRIVAL_TMPS
        )

    m.Total_Max_Flow_Violation_Penalty_Cost = Expression(
        rule=total_max_flow_violation_penalty_cost_rule
    )

    def total_hrz_min_flow_violation_penalty_cost_rule(mod):
        """
        :param mod:
        :return:
        """
        return sum(
            mod.Water_Link_Hrz_Min_Flow_Violation_Avg_Vol_per_Sec_Expression[wl, bt, h]
            * mod.hrz_min_flow_violation_penalty_cost_per_hour[wl]
            * sum(mod.hrs_in_tmp[tmp] for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h])
            * mod.number_years_represented[mod.period[mod.last_hrz_tmp[bt, h]]]
            * mod.discount_factor[mod.period[mod.last_hrz_tmp[bt, h]]]
            for (
                wl,
                bt,
                h,
            ) in mod.WATER_LINKS_W_BT_HRZ_MIN_FLOW_CONSTRAINT
        )

    m.Total_Hrz_Min_Flow_Violation_Penalty_Cost = Expression(
        rule=total_hrz_min_flow_violation_penalty_cost_rule
    )

    def total_hrz_max_flow_violation_penalty_cost_rule(mod):
        """
        :param mod:
        :return:
        """
        return sum(
            mod.Water_Link_Hrz_Max_Flow_Violation_Avg_Vol_per_Sec_Expression[r, bt, h]
            * mod.hrz_max_flow_violation_penalty_cost_per_hour[r]
            * sum(mod.hrs_in_tmp[tmp] for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h])
            * mod.number_years_represented[mod.period[mod.last_hrz_tmp[bt, h]]]
            * mod.discount_factor[mod.period[mod.last_hrz_tmp[bt, h]]]
            for (
                r,
                bt,
                h,
            ) in mod.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT
        )

    m.Total_Hrz_Max_Flow_Violation_Penalty_Cost = Expression(
        rule=total_hrz_max_flow_violation_penalty_cost_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add tuning costs to cost components
    """

    getattr(dynamic_components, cost_components).append(
        "Total_Min_Flow_Violation_Penalty_Cost"
    )

    getattr(dynamic_components, cost_components).append(
        "Total_Max_Flow_Violation_Penalty_Cost"
    )

    getattr(dynamic_components, cost_components).append(
        "Total_Hrz_Min_Flow_Violation_Penalty_Cost"
    )

    getattr(dynamic_components, cost_components).append(
        "Total_Hrz_Max_Flow_Violation_Penalty_Cost"
    )
