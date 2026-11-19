# Copyright 2016-2025 Blue Marble Analytics LLC.
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


from pyomo.environ import Set

# Operational types that can be assigned this compliance type
STOR_LOSSES_OPERATIONAL_TYPES = ["stor"]


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
    m.STOR_LOSSES_PROJECT_POLICY_ZONES = Set(dimen=3, within=m.PROJECT_POLICY_ZONES)


# Compliance type methods
def contribution_in_timepoint(mod, prj, policy, zone, tmp):
    """
    A storage project's contribution is its net discharge (discharge minus
    charge), i.e. its losses count against the policy. This keeps
    simultaneous charging and discharging from acting as artificial load.

    Only the operational types in STOR_LOSSES_OPERATIONAL_TYPES are
    supported.
    """
    if mod.operational_type[prj] not in STOR_LOSSES_OPERATIONAL_TYPES:
        raise ValueError(get_unsupported_operational_type_message(mod, prj))

    return mod.Stor_Discharge_MW[prj, tmp] - mod.Stor_Charge_MW[prj, tmp]


def get_unsupported_operational_type_message(mod, prj):
    return (
        f"Project {prj} of the {mod.operational_type[prj]} operational type "
        f"is assigned the stor_losses policy compliance type, which supports "
        f"only the following operational types: "
        f"{', '.join(STOR_LOSSES_OPERATIONAL_TYPES)}."
    )
