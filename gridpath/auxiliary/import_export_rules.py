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

import os.path
from pyomo.environ import value

# Import-export rules


# Export & import if USE is found only
def export_rule_use(instance, quiet):
    unserved_energy_found = any(
        [
            value(instance.Unserved_Energy_MW_Expression[z, tmp])
            for z in getattr(instance, "LOAD_ZONES")
            for tmp in getattr(instance, "TMPS")
        ]
    )

    if unserved_energy_found:
        if not quiet:
            print("unserved energy found; exporting results")
    else:
        if not quiet:
            print("no unserved energy found; skipping results export")

    return unserved_energy_found


def sys_lz_tmp_csv_based_rule(results_directory, quiet):
    """
    Returns True if the results directory contains a system_load_zone_timepoint.csv file.
    """
    if os.path.exists(
        os.path.join(results_directory, "system_load_zone_timepoint.csv")
    ):
        import_results = True
        if not quiet:
            print("'system_load_zone_timepoint' found -- processing")
    else:
        import_results = False
        if not quiet:
            print("'system_load_zone_timepoint' not found -- skipping")

    return import_results


def sys_lz_tmp_csv_based_rule_w_dir_args(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    quiet,
):
    results_directory = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "results",
    )

    flag = sys_lz_tmp_csv_based_rule(results_directory, quiet)
    return flag


# These are high-level rules for whether or not to run each results-side step of
# GridPath_E2E
import_export_rules = {
    # Only export results if USE is found; export summaries; summarize
    # results and import results only if system_load_zone_timepoint.csv is found
    "USE": {
        "export": export_rule_use,
        "export_summary": lambda instance, quiet: True,
        "import": sys_lz_tmp_csv_based_rule,
    },
    "USE_import_only": {
        "export": lambda instance, quiet: True,
        "export_summary": lambda instance, quiet: True,
        "import": sys_lz_tmp_csv_based_rule,
    },
    "summary_only": {
        "export": lambda instance, quiet: False,
        "export_summary": lambda instance, quiet: True,
        "import": lambda results_directory, quiet: True,
    },
}
