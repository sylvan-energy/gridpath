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
Aggregate carbon emissions from the transmission-line-timepoint level to
the carbon cap zone - period level.
"""

import csv
import os.path
from pyomo.environ import (
    Param,
    Set,
    Var,
    Constraint,
    Expression,
    NonNegativeReals,
    value,
)

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.dynamic_components import carbon_cap_balance_emission_components
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.carbon_cap import CARBON_CAP_ZONE_PRD_DF
from gridpath.transmission.operations.carbon_emissions import (
    calculate_carbon_emissions_imports,
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
    Aggregate total imports of emissions and add to carbon balance constraint
    :param m:
    :param d:
    :return:
    """

    def total_carbon_emissions_imports_rule(mod, z, p):
        """
        Calculate total emissions from all carbonaceous transmission lines
        imported into the carbon cap zone
        :param mod:
        :param z:
        :param p:
        :return:
        """
        return sum(
            mod.Import_Carbon_Emissions_Tons[tx, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (tx, tmp) in mod.CRB_TX_OPR_TMPS
            if tx in mod.CRB_TX_LINES_BY_CARBON_CAP_ZONE[z]
            and tmp in mod.TMPS_IN_PRD[p]
        )

    m.Total_Carbon_Emission_Imports_Tons = Expression(
        m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP,
        rule=total_carbon_emissions_imports_rule,
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    This method adds emission imports to carbon balance
    """

    getattr(dynamic_components, carbon_cap_balance_emission_components).append(
        "Total_Carbon_Emission_Imports_Tons"
    )


def total_carbon_emissions_imports_degen_expr_rule(mod, z, p):
    """
    In case of degeneracy where the Import_Carbon_Emissions_Tons variable
    can take a value larger than the actual import emissions (when the
    carbon cap is non-binding), we can upost-process to figure out what the
    actual imported emissions are (e.g. instead of applying a tuning cost)
    :param mod:
    :param z:
    :param p:
    :return:
    """
    return sum(
        calculate_carbon_emissions_imports(mod, tx, tmp)
        * mod.hrs_in_tmp[tmp]
        * mod.tmp_weight[tmp]
        for (tx, tmp) in mod.CRB_TX_OPR_TMPS
        if tx in mod.CRB_TX_LINES_BY_CARBON_CAP_ZONE[z] and tmp in mod.TMPS_IN_PRD[p]
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
        "import_emissions",
        "import_emissions_degen",
        "total_emissions_degen",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_Carbon_Emission_Imports_Tons[z, p]),
            total_carbon_emissions_imports_degen_expr_rule(m, z, p),
            None,
        ]
        for (z, p) in m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP
    ]
    results_df = create_results_df(
        index_columns=["carbon_cap_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, CARBON_CAP_ZONE_PRD_DF), results_df)

    # Update the total_emissions_degen column
    getattr(d, CARBON_CAP_ZONE_PRD_DF)["total_emissions_degen"] = (
        getattr(d, CARBON_CAP_ZONE_PRD_DF)["project_emissions"]
        + getattr(d, CARBON_CAP_ZONE_PRD_DF)["import_emissions_degen"]
    )
