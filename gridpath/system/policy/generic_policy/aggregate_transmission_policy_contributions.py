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
Aggregate transmission-line contributions (e.g. losses via the *tx_losses*
compliance type) toward the policy requirements and add them to the policy
requirement constraint.
"""

from pyomo.environ import Expression

from gridpath.auxiliary.dynamic_components import (
    policy_balance_contribution_components,
)


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

    def policy_target_total_tx_tmp_contributions_rule(mod, policy, zone, bt, h):
        """
        :param mod:
        :param policy:
        :param zone:
        :param bt:
        :param h:
        :return:
        """
        return sum(
            (mod.Tx_Policy_Contribution_in_Timepoint[tx, policy, zone, tmp])
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (tx, _policy, _zone, tmp) in mod.TX_POLICY_ZONE_OPR_TMPS
            if policy == _policy
            and zone == _zone
            and tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
        )

    m.Total_Tx_Policy_Zone_Tmp_Contributions = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        rule=policy_target_total_tx_tmp_contributions_rule,
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add the transmission contributions to the policy requirement constraint.
    """

    getattr(dynamic_components, policy_balance_contribution_components).append(
        "Total_Tx_Policy_Zone_Tmp_Contributions"
    )
