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

""" """

from pyomo.environ import Expression, value

from gridpath.auxiliary.dynamic_components import (
    policy_balance_contribution_components,
)
from gridpath.common_functions import create_results_df
from gridpath.system.policy.energy_targets import ENERGY_TARGET_ZONE_HRZ_DF


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

    def policy_target_total_tmp_contributions_rule(mod, policy, zone, bt, h):
        """
        :param mod:
        :param zone:
        :param bt:
        :param h:
        :return:
        """
        return sum(
            (mod.Policy_Contribution_in_Timepoint[prj, policy, zone, tmp])
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (prj, _policy, _zone, tmp) in mod.PRJ_POLICY_ZONE_OPR_TMPS
            if policy == _policy
            and zone == _zone
            and tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
        )

    m.Total_Project_Policy_Zone_Tmp_Contributions = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        rule=policy_target_total_tmp_contributions_rule,
    )

    def policy_target_total_month_hour_contributions_rule(
        mod, policy, zone, prd, mn, hr
    ):
        return sum(
            mod.Policy_Contribution_in_Month_Hour[prj, policy, zone, prd, mn, hr]
            for (
                prj,
                _policy,
                _zone,
                _prd,
                _mn,
                _hr,
            ) in mod.PRJ_POLICY_ZONE_PRDS_MONTH_HOURS
            if _policy == policy
            and _zone == zone
            and _prd == prd
            and _mn == mn
            and _hr == hr
        )

    m.Total_Project_Policy_Zone_Month_Hour_Contributions = Expression(
        m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ,
        rule=policy_target_total_month_hour_contributions_rule,
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add the project contributions to the policy requirement constraint.
    """

    getattr(dynamic_components, policy_balance_contribution_components).append(
        "Total_Project_Policy_Zone_Tmp_Contributions"
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
    #
    # results_columns = [
    #     "delivered_energy_target_energy_mwh",
    #     "curtailed_energy_target_energy_mwh",
    # ]
    # data = [
    #     [
    #         z,
    #         bt,
    #         h,
    #         value(m.Total_Project_Policy_Zone_Tmp_Contributions[z, bt, h]),
    #         value(m.Total_Curtailed_Horizon_Energy_Target_Energy_MWh[z, bt, h]),
    #     ]
    #     for (z, bt, h) in m.ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET
    # ]
    # results_df = create_results_df(
    #     index_columns=["energy_target_zone", "balancing_type", "horizon"],
    #     results_columns=results_columns,
    #     data=data,
    # )
    #
    # for c in results_columns:
    #     getattr(d, ENERGY_TARGET_ZONE_HRZ_DF)[c] = None
    # getattr(d, ENERGY_TARGET_ZONE_HRZ_DF).update(results_df)

    pass
