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
Aggregate the losses of transmission lines mapped to an energy target zone
and count them against the zone's horizon energy target.
"""

from pyomo.environ import Expression

from gridpath.auxiliary.dynamic_components import (
    horizon_energy_target_balance_contribution_components,
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

    def total_tx_losses_rule(mod, z, bt, h):
        """
        Losses on transmission lines mapped to the energy target zone reduce
        the total delivered energy counted toward the target.
        :param mod:
        :param z:
        :param bt:
        :param h:
        :return:
        """
        return -sum(
            mod.Tx_Losses_MW[tx, tmp] * mod.hrs_in_tmp[tmp] * mod.tmp_weight[tmp]
            for (tx, tmp) in mod.ENERGY_TARGET_TX_OPR_TMPS
            if tx in mod.ENERGY_TARGET_TX_LINES_BY_ENERGY_TARGET_ZONE[z]
            and tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
        )

    m.Total_Horizon_Energy_Target_Tx_Losses_MWh = Expression(
        m.ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET,
        rule=total_tx_losses_rule,
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Count transmission losses against the horizon energy target constraint.
    """

    getattr(
        dynamic_components, horizon_energy_target_balance_contribution_components
    ).append("Total_Horizon_Energy_Target_Tx_Losses_MWh")
