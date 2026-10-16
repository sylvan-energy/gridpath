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
The *import_emissions* compliance type: the emissions of the power the line
imports into the policy zone count toward the policy requirement, at the
line's import intensity and, in a ``net_prd`` zone, less a credit for exports
at its export intensity. The per-line parameters (import direction and
intensities) are columns of the same mapping table; the accounting is shared
with the carbon cap and carbon tax
(:code:`gridpath.system.policy.import_emissions`) and enters the policy
requirement at the zone-horizon level through
:code:`system.policy.generic_policy.aggregate_import_emissions`, not through
the per-timepoint contribution below, which is therefore zero.
"""


# Compliance type methods
def contribution_in_timepoint(mod, tx, policy, zone, tmp):
    """
    Zero: the import emissions are aggregated per zone and horizon by the
    import-emissions modules.
    """
    return 0
