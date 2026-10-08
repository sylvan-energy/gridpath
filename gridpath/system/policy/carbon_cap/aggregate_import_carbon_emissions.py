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
The import emissions that count toward each carbon cap zone and period,
combined from transmission imports and market purchases per the zone's
import-emissions basis, and added to the carbon cap balance. See
:code:`gridpath.system.policy.import_emissions`.
"""

from gridpath.auxiliary.dynamic_components import (
    carbon_cap_balance_emission_components,
)
from gridpath.system.policy.carbon_cap import CARBON_CAP_ZONE_PRD_DF
from gridpath.system.policy.import_emissions import (
    CARBON_CAP,
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
    generic_add_import_emissions_components(m, d, CARBON_CAP)
    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    Add the combined import emissions to the carbon cap balance.
    """
    getattr(dynamic_components, carbon_cap_balance_emission_components).append(
        "Total_Carbon_Cap_Import_Emissions_Tons"
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
    generic_export_import_emissions_results(m, d, CARBON_CAP)

    # Total emissions recomputed from the solved dispatch and flows
    df = getattr(d, CARBON_CAP_ZONE_PRD_DF)
    df["total_emissions_degen"] = (
        df["project_emissions"] + df["total_import_emissions_degen"]
    )
