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
Aggregate delivered energy-target-eligible power from the project-timepoint
level to the energy-target zone - balancing type - horizon level.
"""

from pyomo.environ import Expression, value

from gridpath.auxiliary.dynamic_components import (
    horizon_energy_target_balance_contribution_components,
)
from gridpath.common_functions import create_results_df, update_results_df
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

    def energy_target_contribution_rule(mod, z, bt, h):
        """
        Calculate the delivered energy for each zone and balancing type -
        horizon.
        Scheduled power provision (available energy minus reserves minus
        scheduled curtailment) + subhourly delivered energy (from
        providing upward reserves) - subhourly curtailment (from providing
        downward reserves)
        :param mod:
        :param z:
        :param bt:
        :param h:
        :return:
        """
        return sum(
            (
                mod.Scheduled_Energy_Target_Energy_MW[g, tmp]
                - mod.Subhourly_Curtailment_MW[g, tmp]
                + mod.Subhourly_Energy_Target_Energy_MW[g, tmp]
            )
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (g, tmp) in mod.ENERGY_TARGET_PRJ_OPR_TMPS
            if g in mod.ENERGY_TARGET_PRJS_BY_ENERGY_TARGET_ZONE[z]
            and tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
        )

    m.Total_Delivered_Horizon_Energy_Target_Energy_MWh = Expression(
        m.ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET,
        rule=energy_target_contribution_rule,
    )

    def total_curtailed_energy_target_energy_rule(mod, z, bt, h):
        """
        Calculate how much RPS-eligible energy was curtailed in each RPS zone
        in each balancing type - horizon
        :param mod:
        :param z:
        :param bt:
        :param h:
        :return:
        """
        return sum(
            (
                mod.Scheduled_Curtailment_MW[g, tmp]
                + mod.Subhourly_Curtailment_MW[g, tmp]
                - mod.Subhourly_Energy_Target_Energy_MW[g, tmp]
            )
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (g, tmp) in mod.ENERGY_TARGET_PRJ_OPR_TMPS
            if g in mod.ENERGY_TARGET_PRJS_BY_ENERGY_TARGET_ZONE[z]
            and tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
        )

    m.Total_Curtailed_Horizon_Energy_Target_Energy_MWh = Expression(
        m.ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET,
        rule=total_curtailed_energy_target_energy_rule,
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add the delivered project energy to the horizon energy target constraint.
    """

    getattr(
        dynamic_components, horizon_energy_target_balance_contribution_components
    ).append("Total_Delivered_Horizon_Energy_Target_Energy_MWh")


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
        "delivered_energy_target_energy_mwh",
        "curtailed_energy_target_energy_mwh",
    ]
    data = [
        [
            z,
            bt,
            h,
            value(m.Total_Delivered_Horizon_Energy_Target_Energy_MWh[z, bt, h]),
            value(m.Total_Curtailed_Horizon_Energy_Target_Energy_MWh[z, bt, h]),
        ]
        for (z, bt, h) in m.ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET
    ]
    results_df = create_results_df(
        index_columns=["energy_target_zone", "balancing_type_horizon", "horizon"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, ENERGY_TARGET_ZONE_HRZ_DF), results_df)
