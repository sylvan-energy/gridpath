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
This module aggregates the net market participation by load zone to create a
load-balance production component, and adds it to the load-balance constraint.
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

    # Sum up final positions in all markets for use in the load-balance constraints
    def total_lz_net_purchased_power_init(mod, z, tmp):
        if z in mod.MARKET_LZS:
            return sum(
                mod.Final_Net_Market_Purchased_Power[z, hub, tmp]
                for hub in mod.MARKETS_BY_LZ[z]
            )
        else:
            return 0

    m.Total_Final_LZ_Net_Purchased_Power = Expression(
        m.LOAD_ZONES, m.TMPS, initialize=total_lz_net_purchased_power_init
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:
    :return:

    """
    getattr(dynamic_components, load_balance_production_components).append(
        "Total_Final_LZ_Net_Purchased_Power"
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
        "net_market_purchases_mw",
    ]
    data = [
        [
            lz,
            tmp,
            value(m.Total_Final_LZ_Net_Purchased_Power[lz, tmp]),
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
