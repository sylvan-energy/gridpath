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
Aggregate simple PRM contribution from the project level to the PRM zone level
for each period.
"""

import csv
import os.path
from pyomo.environ import Expression, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.dynamic_components import prm_balance_provision_components
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.reliability.prm import PRM_ZONE_PRD_DF


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

    def total_prm_provision_rule(mod, z, p):
        """

        :param mod:
        :param z:
        :param p:
        :return:
        """
        return sum(
            mod.PRM_Simple_Contribution_MW[g, p]
            for g in mod.PRM_PROJECTS_BY_PRM_ZONE[z]
            if (g, p) in mod.PRM_PRJ_OPR_PRDS
        )

    m.Total_PRM_Simple_Contribution_MW = Expression(
        m.PRM_ZONE_PERIODS_WITH_REQUIREMENT, rule=total_prm_provision_rule
    )

    # Add to balance constraint
    getattr(d, prm_balance_provision_components).append(
        "Total_PRM_Simple_Contribution_MW"
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
        "elcc_simple_mw",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_PRM_Simple_Contribution_MW[z, p]),
        ]
        for (z, p) in m.PRM_ZONE_PERIODS_WITH_REQUIREMENT
    ]
    results_df = create_results_df(
        index_columns=["prm_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PRM_ZONE_PRD_DF), results_df)
