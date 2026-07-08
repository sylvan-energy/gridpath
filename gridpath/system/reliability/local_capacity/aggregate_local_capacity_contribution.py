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
Aggregate simple local capacity contribution from the project level to the
local-capacity-zone level for each period.
"""

import csv
import os.path
from pyomo.environ import Expression, value

from gridpath.auxiliary.dynamic_components import (
    local_capacity_balance_provision_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.reliability.local_capacity import LOCAL_CAPACITY_ZONE_PRD_DF


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

    def total_local_capacity_provision_rule(mod, z, p):
        """

        :param mod:
        :param z:
        :param p:
        :return:
        """
        return sum(
            mod.Local_Capacity_Contribution_MW[g, p]
            for g in mod.LOCAL_CAPACITY_PROJECTS_BY_LOCAL_CAPACITY_ZONE[z]
            if (g, p) in mod.LOCAL_CAPACITY_PRJ_OPR_PRDS
        )

    m.Total_Local_Capacity_Contribution_MW = Expression(
        m.LOCAL_CAPACITY_ZONE_PERIODS_WITH_REQUIREMENT,
        rule=total_local_capacity_provision_rule,
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    This method adds contribution to local capacity provision components
    """

    getattr(dynamic_components, local_capacity_balance_provision_components).append(
        "Total_Local_Capacity_Contribution_MW"
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
        "project_contribution_mw",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_Local_Capacity_Contribution_MW[z, p]),
        ]
        for (z, p) in m.LOCAL_CAPACITY_ZONE_PERIODS_WITH_REQUIREMENT
    ]
    results_df = create_results_df(
        index_columns=["local_capacity_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, LOCAL_CAPACITY_ZONE_PRD_DF), results_df)
