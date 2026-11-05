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
    charge), i.e. its losses count against the policy. Net discharge is the
    project's power provision, which the operational type defines, so this
    works for any storage-like operational type (``stor``,
    ``stor_stress_hrz``, ...) without referring to a type's own variables.
    """
    return mod.Project_Power_Provision_MW[prj, tmp]
