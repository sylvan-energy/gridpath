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
This module aggregates the net power flow in/out of a load zone on all
transmission lines connected to the load zone to create a load-balance
production component, and adds it to the load-balance constraint.
"""

from pyomo.environ import Expression, value

from gridpath.auxiliary.dynamic_components import (
    load_balance_production_components,
    load_balance_consumption_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.load_balance import LOAD_ZONE_TMP_DF


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
    Add net transmitted power to load balance
    :param m:
    :param d:
    :return:
    """

    def total_transmission_to_rule(mod, z, tmp):
        """
        For each load zone, iterate over the transmission lines with the
        load zone as destination to determine net imports into the load zone
        minus any losses incurred. Tx_Losses_LZ_To_MW is positive when
        Transmit_Power_MW is positive (losses are accounted for when the
        transmission flow is to the destination load zone) and 0 otherwise.
        """
        return sum(
            (mod.Transmit_Power_MW[tx, tmp] - mod.Tx_Losses_LZ_To_MW[tx, tmp])
            for tx in mod.TX_LINES_OPR_IN_TMP[tmp]
            if mod.load_zone_to[tx] == z
        )

    m.Transmission_to_Zone_MW = Expression(
        m.LOAD_ZONES, m.TMPS, rule=total_transmission_to_rule
    )

    def total_transmission_from_rule(mod, z, tmp):
        """
        For each load zone, iterate over the transmission lines with the
        load zone as origin to determine net exports from the load zone
        minus any losses incurred. Tx_Losses_LZ_From_MW is positive when
        Transmit_Power_MW is negative (losses are accounted for when the
        transmission flow is to the origin load zone) and 0 otherwise.
        """
        return sum(
            (mod.Transmit_Power_MW[tx, tmp] + mod.Tx_Losses_LZ_From_MW[tx, tmp])
            for tx in mod.TX_LINES_OPR_IN_TMP[tmp]
            if mod.load_zone_from[tx] == z
        )

    m.Transmission_from_Zone_MW = Expression(
        m.LOAD_ZONES, m.TMPS, rule=total_transmission_from_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:
    :return:

    This method adds the transmission to/from to the load balance dynamic
    components.
    """

    getattr(dynamic_components, load_balance_production_components).append(
        "Transmission_to_Zone_MW"
    )

    getattr(dynamic_components, load_balance_consumption_components).append(
        "Transmission_from_Zone_MW"
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
    :param stage:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    results_columns = [
        "net_imports_mw",
    ]
    data = [
        [
            lz,
            tmp,
            (
                value(m.Transmission_to_Zone_MW[lz, tmp])
                - value(m.Transmission_from_Zone_MW[lz, tmp])
            ),
        ]
        for lz in getattr(m, "LOAD_ZONES")
        for tmp in getattr(m, "TMPS")
    ]
    results_df = create_results_df(
        index_columns=["load_zone", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, LOAD_ZONE_TMP_DF), results_df)
