# Copyright 2016-2023 Blue Marble Analytics.
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


import os.path

from gridpath.system.policy.performance_standard import PERFORMANCE_STANDARD_Z_PRD_DF
from gridpath.system.policy.performance_standard import PERFORMANCE_STANDARD_Z_PRJ_PRD_DF


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
    Export all results from the CARBON_CAP_ZONE_PRD_DF that various modules
    have added to
    """

    getattr(d, PERFORMANCE_STANDARD_Z_PRD_DF).to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_performance_standard.csv",
        ),
        sep=",",
        index=True,
    )
    
    getattr(d, PERFORMANCE_STANDARD_Z_PRJ_PRD_DF).to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_performance_standard_project.csv",
        ),
        sep=",",
        index=True,
    )
