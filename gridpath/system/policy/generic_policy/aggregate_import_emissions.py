# Copyright 2026 Sylvan Energy Analytics LLC.
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
The import emissions that count toward each policy zone and horizon,
combined from transmission imports and market purchases per the zone's
import-emissions basis (``gross`` or ``net_prd``), and added to the policy
requirement constraint as a contribution. Since the imported-power variables
are only bounded from below, the accounting is exact only where the policy
pushes them down, i.e. for ``max`` policies; the inputs validation of the
mappings enforces this. See :code:`gridpath.system.policy.import_emissions`.
"""

from gridpath.auxiliary.dynamic_components import (
    policy_balance_contribution_components,
)
from gridpath.system.policy.import_emissions import (
    POLICY,
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
    generic_add_import_emissions_components(m, d, POLICY)

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    Add the combined import emissions to the policy requirement constraint.
    """
    getattr(dynamic_components, policy_balance_contribution_components).append(
        "Total_Policy_Import_Emissions_Tons"
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
    generic_export_import_emissions_results(m, d, POLICY)
