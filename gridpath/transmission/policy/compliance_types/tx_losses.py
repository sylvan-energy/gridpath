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
Transmission losses count against the policy requirement, analogous to how
storage round-trip losses count against it via the *stor_losses* compliance
type on the project side.
"""

from pyomo.environ import Set


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
    """ """
    # Not actually initialized or used for now
    m.TX_LOSSES_TX_POLICY_ZONES = Set(dimen=3, within=m.TX_POLICY_ZONES)


# Compliance type methods
def contribution_in_timepoint(mod, tx, policy, zone, tmp):
    """
    Losses on the line reduce the total contributions toward the policy
    requirement, so the contribution is the negative of the losses (in
    either flow direction).
    """
    return -(mod.Tx_Losses_LZ_From_MW[tx, tmp] + mod.Tx_Losses_LZ_To_MW[tx, tmp])
