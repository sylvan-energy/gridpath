# Copyright 2026 Sylvan Energy Analytics LLC
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
The import emissions that count toward each carbon tax zone and period,
combined from transmission imports and market purchases per the zone's
import-emissions basis, and their cost at the zone's carbon tax, added to the
carbon tax cost. See :code:`gridpath.system.policy.import_emissions`.
"""

from pyomo.environ import Expression, value

from gridpath.auxiliary.dynamic_components import carbon_tax_cost_components
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.carbon_tax import CARBON_TAX_ZONE_PRD_DF
from gridpath.system.policy.import_emissions import (
    CARBON_TAX,
    generic_add_import_emissions_components,
    generic_export_import_emissions_results,
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
    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Total_Carbon_Tax_Import_Cost`                                  |
    | | *Defined over*: :code:`CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX`       |
    |                                                                         |
    | The zone's import emissions times its carbon tax.                       |
    +-------------------------------------------------------------------------+
    """
    generic_add_import_emissions_components(m, d, CARBON_TAX)

    def total_import_cost_rule(mod, z, p):
        return mod.Total_Carbon_Tax_Import_Emissions_Tons[z, p] * mod.carbon_tax[z, p]

    m.Total_Carbon_Tax_Import_Cost = Expression(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX, rule=total_import_cost_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    Add the import emissions cost to the carbon tax cost.
    """
    getattr(dynamic_components, carbon_tax_cost_components).append(
        "Total_Carbon_Tax_Import_Cost"
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
    generic_export_import_emissions_results(m, d, CARBON_TAX)

    results_df = create_results_df(
        index_columns=["carbon_tax_zone", "period"],
        results_columns=["total_import_carbon_tax_cost"],
        data=[
            [z, p, value(m.Total_Carbon_Tax_Import_Cost[z, p])]
            for (z, p) in m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX
        ],
    )
    update_results_df(getattr(d, CARBON_TAX_ZONE_PRD_DF), results_df)
