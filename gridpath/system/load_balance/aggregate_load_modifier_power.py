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

"""
This module, aggregates the power production by all operational projects
tagged as demand side.
"""

from pyomo.environ import Expression, value

from gridpath.auxiliary.dynamic_components import load_balance_production_components
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
    :param m: the Pyomo abstract model object we are adding the components to
    :param d: the DynamicComponents class object we are adding components to
    """

    # Add power generation to load balance constraint
    def total_load_modifier_power_production_rule(mod, z, tmp):
        """
        Note that this is the total demand side power from the perspective of
        the bulk system.
        """
        return sum(
            mod.Bulk_Power_Provision_MW[prj, tmp]
            for prj in mod.OPR_PRJS_IN_TMP[tmp]
            if mod.load_zone[prj] == z and mod.load_modifier_flag[prj] == 1
        )

    m.Load_Modifier_Power_Production_in_Zone_MW = Expression(
        m.LOAD_ZONES, m.TMPS, rule=total_load_modifier_power_production_rule
    )

    def load_modifier_adjusted_load_init(mod, lz, tmp):
        return (
            mod.LZ_Bulk_Static_Load_in_Tmp[lz, tmp]
            - mod.Load_Modifier_Power_Production_in_Zone_MW[lz, tmp]
        )

    m.LZ_Modified_Load_in_Tmp = Expression(
        m.LOAD_ZONES, m.TMPS, initialize=load_modifier_adjusted_load_init
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
        "load_modifier_power_mw",
        "load_modifier_adjusted_load_mw",
    ]
    data = [
        [
            lz,
            tmp,
            value(m.Load_Modifier_Power_Production_in_Zone_MW[lz, tmp]),
            value(m.LZ_Modified_Load_in_Tmp[lz, tmp]),
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
