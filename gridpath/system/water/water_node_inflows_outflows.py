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

""" """

import csv
import os.path
from pyomo.environ import (
    Boolean,
    NonNegativeIntegers,
    Constraint,
    Expression,
    Any,
    value,
)

from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.common_functions import (
    create_results_df,
)
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_boundary_type,
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

    # ### Expressions ### #
    def endogenous_node_inflow_rate_init(mod, wn, tmp):
        """
        Exogenous inflow to node + sum of flow on all links to note in the
        timepoint of arrival
        """
        endogenous_flows = 0
        for wl in mod.WATER_LINKS_TO_BY_WATER_NODE[wn]:
            dep_tmp = mod.departure_timepoint[wl, tmp]
            if dep_tmp != "tmp_outside_horizon":
                endogenous_flows += mod.Water_Link_Flow_Rate_Vol_per_Sec[
                    wl, dep_tmp, tmp
                ]

        return endogenous_flows

    m.Endogenous_Water_Node_Inflow_Rate_Vol_Per_Sec = Expression(
        m.WATER_NODES,
        m.TMPS,
        initialize=endogenous_node_inflow_rate_init,
    )

    def gross_node_inflow_rate_init(mod, wn, tmp):
        """
        Exogenous inflow to node + sum of flow on all links to note in the
        timepoint of arrival
        """

        return (
            mod.exogenous_water_inflow_rate_vol_per_sec[wn, tmp]
            + mod.Endogenous_Water_Node_Inflow_Rate_Vol_Per_Sec[wn, tmp]
        )

    m.Gross_Water_Node_Inflow_Rate_Vol_Per_Sec = Expression(
        m.WATER_NODES,
        m.TMPS,
        initialize=gross_node_inflow_rate_init,
    )

    def node_outflow_rate_init(mod, wn, tmp):
        return sum(
            mod.Water_Link_Flow_Rate_Vol_per_Sec[
                wl, tmp, mod.arrival_timepoint[wl, tmp]
            ]
            for wl in mod.WATER_LINKS_FROM_BY_WATER_NODE[wn]
        )

    m.Gross_Water_Node_Outflow_Rate_Vol_per_Sec = Expression(
        m.WATER_NODES,
        m.TMPS,
        initialize=node_outflow_rate_init,
    )
