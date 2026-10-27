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
Differential test for percent reserve requirements mapped by load zone and
load component. In ``2periods_new_build_2zones_loadcomponents`` each load
zone's load is split into two load components and there are no load
modifiers, so a requirement of 15% of each of a zone's load components
(``..._w_lf_up_percent_req_by_load_component_twin``) must match a requirement
of 15% of the zone's whole load (``..._w_lf_up_percent_req``): identical
objective function values and identical requirement, provision and violation
in every timepoint. ``..._w_lf_up_percent_req_one_load_component`` includes
only load component ``half1``, so its requirement is 15% of that component's
load inputs.

The requirement binds in every timepoint of all three scenarios (non-zero
duals), so dropping or double counting a load component would change the
objective.

The scenarios are solved into a temporary directory so that the committed
example directories are not touched.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

import pandas as pd

from db import create_database
from db.utilities import port_csvs_to_db, scenario
from gridpath import run_end_to_end

REPO_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_TEMPLATE_ENV_VAR = "GRIDPATH_TEST_EXAMPLES_DB_TEMPLATE"

WHOLE_LOAD_ZONES = "2periods_new_build_2zones_loadcomponents_w_lf_up_percent_req"
BY_LOAD_COMPONENT = f"{WHOLE_LOAD_ZONES}_by_load_component_twin"
ONE_LOAD_COMPONENT = f"{WHOLE_LOAD_ZONES}_one_load_component"

PERCENT_REQUIREMENT = 0.15


class TestReservePercentRequirementLoadComponentExamples(unittest.TestCase):
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
                    "--quiet",
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

        cls.objectives = {}
        for scenario_name in [WHOLE_LOAD_ZONES, BY_LOAD_COMPONENT, ONE_LOAD_COMPONENT]:
            cls.objectives[scenario_name] = run_end_to_end.main(
                [
                    "--database",
                    cls.db_path,
                    "--scenario",
                    scenario_name,
                    "--scenario_location",
                    cls.scenario_location,
                    "--quiet",
                    "--mute_solver_output",
                    "--testing",
                ]
            )

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        try:
            return pd.read_sql(sql, conn, params=params)
        finally:
            conn.close()

    def lf_reserves_up_results(self, scenario_name):
        return (
            self.query(
                """
                SELECT r.*
                FROM results_system_lf_reserves_up AS r
                JOIN scenarios USING (scenario_id)
                WHERE scenario_name = ?
                """,
                params=(scenario_name,),
            )
            .set_index(["lf_reserves_up_ba", "timepoint"])
            .sort_index()
        )

    def test_objectives_match_twin(self):
        whole = self.objectives[WHOLE_LOAD_ZONES][("", "", "", 1)][1]
        by_component = self.objectives[BY_LOAD_COMPONENT][("", "", "", 1)][1]
        one_component = self.objectives[ONE_LOAD_COMPONENT][("", "", "", 1)][1]
        self.assertAlmostEqual(whole, by_component, delta=1e-9 * abs(whole))
        # Fewer reserves to hold: lower costs, i.e. a higher objective
        self.assertGreater(one_component, whole)

    def test_reserve_results_match_twin(self):
        whole = self.lf_reserves_up_results(WHOLE_LOAD_ZONES)
        by_component = self.lf_reserves_up_results(BY_LOAD_COMPONENT)
        self.assertEqual(len(whole), 8)
        self.assertListEqual(list(whole.index), list(by_component.index))
        for column in [
            "reserve_requirement_mw",
            "reserve_provision_mw",
            "reserve_violation_mw",
        ]:
            pd.testing.assert_series_equal(
                whole[column], by_component[column], rtol=1e-9, atol=1e-6
            )

    def test_one_load_component_requirement(self):
        results = self.lf_reserves_up_results(ONE_LOAD_COMPONENT)
        half1_load = (
            self.query(
                """
                SELECT load_zone AS lf_reserves_up_ba, timepoint, load_mw
                FROM inputs_system_load_levels
                WHERE load_component = 'half1'
                AND weather_iteration = 0
                AND stage_id = 1
                AND load_levels_scenario_id = (
                    SELECT load_levels_scenario_id
                    FROM inputs_system_load
                    WHERE load_scenario_id = (
                        SELECT load_scenario_id FROM scenarios
                        WHERE scenario_name = ?
                        )
                    )
                """,
                params=(ONE_LOAD_COMPONENT,),
            )
            .set_index(["lf_reserves_up_ba", "timepoint"])
            .reindex(results.index)["load_mw"]
        )
        pd.testing.assert_series_equal(
            results["reserve_requirement_mw"],
            PERCENT_REQUIREMENT * half1_load,
            check_names=False,
            rtol=1e-9,
        )

    def test_requirement_binds(self):
        for scenario_name in [WHOLE_LOAD_ZONES, BY_LOAD_COMPONENT, ONE_LOAD_COMPONENT]:
            with self.subTest(scenario_name=scenario_name):
                results = self.lf_reserves_up_results(scenario_name)
                self.assertTrue((results["dual"].abs() > 1e-9).all())
                self.assertTrue((results["reserve_violation_mw"] == 0).all())


if __name__ == "__main__":
    unittest.main()
