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
Differential test for the project-period summary export: the per-project-
period sums over the project's own timepoints in the period must equal a
brute-force filter of the full PRJ_OPR_TMPS set at the solution of a solved
example. The example is solved into a temporary directory so that the
committed example directory is not touched.
"""

import math
import os
import shutil
import tempfile
import unittest

import pandas as pd
from pyomo.environ import value

from db import create_database
from db.utilities import port_csvs_to_db, scenario
from gridpath import get_scenario_inputs, run_scenario
from gridpath.project import summary_results

REPO_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_TEMPLATE_ENV_VAR = "GRIDPATH_TEST_EXAMPLES_DB_TEMPLATE"
EXAMPLE = "2periods_new_build"


class TestProjectSummaryResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "examples.db")
        cls.scenario_location = os.path.join(cls.tmp_dir.name, "scenarios")
        os.makedirs(cls.scenario_location)

        template_path = os.environ.get(DB_TEMPLATE_ENV_VAR)
        if template_path and os.path.exists(template_path):
            shutil.copyfile(template_path, cls.db_path)
        else:
            csv_path = os.path.join(REPO_DIRECTORY, "db", "csvs_test_examples")
            create_database.main(
                [
                    "--database",
                    cls.db_path,
                    "--db_schema",
                    os.path.join(REPO_DIRECTORY, "db", "db_schema.sql"),
                    "--data_directory",
                    os.path.join(REPO_DIRECTORY, "db", "data"),
                ]
            )
            port_csvs_to_db.main(
                ["--database", cls.db_path, "--csv_location", csv_path, "--quiet"]
            )
            scenario.main(
                [
                    "--database",
                    cls.db_path,
                    "--csv_path",
                    os.path.join(csv_path, "scenarios.csv"),
                    "--quiet",
                ]
            )

        get_scenario_inputs.main(
            [
                "--database",
                cls.db_path,
                "--scenario",
                EXAMPLE,
                "--scenario_location",
                cls.scenario_location,
                "--quiet",
            ]
        )

        cls.scenario_directory = os.path.join(cls.scenario_location, EXAMPLE)
        parsed_arguments = run_scenario.parse_arguments(
            [
                "--scenario",
                EXAMPLE,
                "--scenario_location",
                cls.scenario_location,
                "--quiet",
                "--mute_solver_output",
            ]
        )
        cls.dynamic_components, cls.instance = run_scenario.create_problem(
            scenario_directory=cls.scenario_directory,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
            multi_stage=False,
            parsed_arguments=parsed_arguments,
        )
        run_scenario.solve(cls.instance, parsed_arguments)

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def test_summary_matches_brute_force_over_prj_opr_tmps(self):
        m = self.instance
        os.makedirs(os.path.join(self.scenario_directory, "results"), exist_ok=True)
        summary_results.export_summary_results(
            self.scenario_directory, "", "", "", "", "", m, self.dynamic_components
        )
        summary = pd.read_csv(
            os.path.join(
                self.scenario_directory, "results", "project_period_summary.csv"
            )
        ).set_index(["project", "period"])

        self.assertEqual(
            set(summary.index), {(prj, prd) for prj, prd in m.PRJ_OPR_PRDS}
        )
        for prj, prd in m.PRJ_OPR_PRDS:
            # The brute-force filter of the full project-timepoint set
            expected_mwh = sum(
                value(m.Bulk_Power_Provision_MW[_prj, tmp])
                * m.hrs_in_tmp[tmp]
                * m.tmp_weight[tmp]
                for (_prj, tmp) in m.PRJ_OPR_TMPS
                if _prj == prj and m.period[tmp] == prd
            )
            row = summary.loc[(prj, prd)]
            self.assertAlmostEqual(
                row["total_delivered_bulk_power_mwh"], expected_mwh, places=6
            )
            capacity_mw = value(m.Capacity_MW[prj, prd])
            self.assertAlmostEqual(row["capacity_mw"], capacity_mw, places=6)
            if capacity_mw > 0:
                hrs_in_prd = sum(
                    m.hrs_in_tmp[tmp] * m.tmp_weight[tmp] for tmp in m.TMPS_IN_PRD[prd]
                )
                self.assertAlmostEqual(
                    row["cap_factor_equivalent"],
                    expected_mwh / (capacity_mw * hrs_in_prd),
                    places=9,
                )
            else:
                self.assertTrue(math.isnan(row["cap_factor_equivalent"]))


if __name__ == "__main__":
    unittest.main()
