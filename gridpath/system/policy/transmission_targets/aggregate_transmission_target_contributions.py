# Copyright 2022 (c) Crown Copyright, GC.
# Modifications Copyright Blue Marble Analytics LLC 2023.
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
Aggregate delivered transmission-target-eligible transmission flow from the
tx_line-timepoint level to the transmission-target zone - balancing_type -
horizon level.
"""

from pyomo.environ import Expression, value

from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.transmission_targets import TX_TARGETS_DF


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

    def transmission_target_pos_dir_contribution_rule(mod, z, bt, hz):
        """
        Calculate the delivered energy in the positive direction for each transmission-target zone and period
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return sum(
            (
                mod.Transmission_Target_Energy_MW_Pos_Dir[tx, tmp]
                if float(mod.contributes_net_flow_to_tx_target[tx]) == 0
                else mod.Transmission_Target_Net_Energy_MW_Pos_Dir[tx, tmp]
            )
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (tx, tmp) in mod.TRANSMISSION_TARGET_TX_OPR_TMPS
            if tx in mod.TRANSMISSION_TARGET_TX_LINES_BY_TRANSMISSION_TARGET_ZONE[z]
            and tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hz]
        )

    m.Total_Transmission_Target_Energy_Pos_Dir_MWh = Expression(
        m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET,
        rule=transmission_target_pos_dir_contribution_rule,
    )

    def transmission_target_neg_dir_contribution_rule(mod, z, bt, hz):
        """
        Calculate the delivered energy in the negative direction for each transmission-target zone and period
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return sum(
            (
                mod.Transmission_Target_Energy_MW_Neg_Dir[tx, tmp]
                if float(mod.contributes_net_flow_to_tx_target[tx]) == 0
                else mod.Transmission_Target_Net_Energy_MW_Neg_Dir[tx, tmp]
            )
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (tx, tmp) in mod.TRANSMISSION_TARGET_TX_OPR_TMPS
            if tx in mod.TRANSMISSION_TARGET_TX_LINES_BY_TRANSMISSION_TARGET_ZONE[z]
            and tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hz]
        )

    m.Total_Transmission_Target_Energy_Neg_Dir_MWh = Expression(
        m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET,
        rule=transmission_target_neg_dir_contribution_rule,
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
        "total_transmission_target_energy_pos_dir_mwh",
        "total_transmission_target_energy_neg_dir_mwh",
    ]
    data = [
        [
            z,
            bt,
            hz,
            value(m.Total_Transmission_Target_Energy_Pos_Dir_MWh[z, bt, hz]),
            value(m.Total_Transmission_Target_Energy_Neg_Dir_MWh[z, bt, hz]),
        ]
        for (
            z,
            bt,
            hz,
        ) in m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET
    ]
    results_df = create_results_df(
        index_columns=["transmission_target_zone", "balancing_type", "horizon"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, TX_TARGETS_DF), results_df)
