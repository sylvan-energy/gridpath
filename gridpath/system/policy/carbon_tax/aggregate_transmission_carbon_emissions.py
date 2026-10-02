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
Aggregate the emissions of imports over transmission lines into CARBON TAX zone-period
expressions: :code:`Total_Tx_Carbon_Tax_Import_Emissions_Tons` (gross
imports) and :code:`Total_Tx_Carbon_Tax_Signed_Import_Emissions_Tons`
(imports less export credits, zero in gross-basis zones), which
:code:`system.policy.CARBON_TAX.aggregate_import_carbon_emissions` combines per
the zone's import-emissions basis. See
:code:`gridpath.system.policy.import_emissions`.
"""

from gridpath.system.policy.import_emissions import (
    CARBON_TAX,
    generic_add_source_aggregation_components,
    generic_export_source_aggregation_results,
)
from gridpath.transmission.operations.carbon_emissions_common import TX_SOURCE


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
    generic_add_source_aggregation_components(m, d, CARBON_TAX, TX_SOURCE)


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
    generic_export_source_aggregation_results(m, d, CARBON_TAX, TX_SOURCE)
