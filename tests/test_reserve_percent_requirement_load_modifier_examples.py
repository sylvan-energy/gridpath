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
Differential test for percent reserve requirements on load components with
load modifiers linked to them. In ``dsm_load_component_linked_w_lf_up_percent_req``
the load-following up requirement is 30% of the zone's whole load, net of
its load modifiers: a ``load_component_modifier`` project linked to load
component ``half1`` and a ``load_component_shift`` project linked to
``half2`` (both with a distribution loss adjustment factor of 0.05). In
``..._by_load_component_twin`` it is 30% of each load component, each net of
the load modifier linked to it. The zone has no other load modifiers, so the
two must agree: identical objective function values and identical
requirement, provision and violation in every timepoint, and the requirement
must equal 30% of the components' load less the linked projects' bulk power
production.

Both load modifiers are built and modify the load in every timepoint, and
the requirement binds in the peak timepoint, where it drives the investment
in the load_component_shift project, so not netting either project out of
its load component would change the twin's objective.

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

WHOLE_LOAD_ZONE = "dsm_load_component_linked_w_lf_up_percent_req"
BY_LOAD_COMPONENT = f"{WHOLE_LOAD_ZONE}_by_load_component_twin"

PERCENT_REQUIREMENT = 0.3
LINKED_PRJS = ["DSM_Load_Component_Modifier", "DSM_Load_Component_Shift"]


class TestReservePercentRequirementLoadModifierExamples(unittest.TestCase):
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
        for scenario_name in [WHOLE_LOAD_ZONE, BY_LOAD_COMPONENT]:
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
            .set_index("timepoint")
            .sort_index()
        )

    def linked_prjs_bulk_power(self, scenario_name):
        """
        :return: DataFrame of the linked projects' bulk power production by
            timepoint (columns) and project (rows)
        """
        return self.query(
            f"""
            SELECT project, timepoint, power_mw
            FROM results_project_timepoint
            JOIN scenarios USING (scenario_id)
            WHERE scenario_name = ?
            AND project IN ({", ".join("?" for _ in LINKED_PRJS)})
            """,
            params=(scenario_name, *LINKED_PRJS),
        ).pivot(index="project", columns="timepoint", values="power_mw")

    def test_objectives_match_twin(self):
        whole = self.objectives[WHOLE_LOAD_ZONE][("", "hydro_iteration_1", "", 1)][1]
        by_component = self.objectives[BY_LOAD_COMPONENT][
            ("", "hydro_iteration_1", "", 1)
        ][1]
        self.assertAlmostEqual(whole, by_component, delta=1e-9 * abs(whole))

    def test_reserve_results_match_twin(self):
        whole = self.lf_reserves_up_results(WHOLE_LOAD_ZONE)
        by_component = self.lf_reserves_up_results(BY_LOAD_COMPONENT)
        self.assertEqual(len(whole), 24)
        self.assertListEqual(list(whole.index), list(by_component.index))
        for column in [
            "reserve_requirement_mw",
            "reserve_provision_mw",
            "reserve_violation_mw",
        ]:
            pd.testing.assert_series_equal(
                whole[column], by_component[column], rtol=1e-9, atol=1e-6
            )

    def test_requirement_nets_linked_load_modifiers(self):
        results = self.lf_reserves_up_results(BY_LOAD_COMPONENT)
        static_load = (
            self.query(
                """
                SELECT timepoint, SUM(load_mw) AS load_mw
                FROM inputs_system_load_levels
                WHERE weather_iteration = 0
                AND stage_id = 1
                AND load_zone = 'Zone1'
                AND load_levels_scenario_id = (
                    SELECT load_levels_scenario_id
                    FROM inputs_system_load
                    WHERE load_scenario_id = (
                        SELECT load_scenario_id FROM scenarios
                        WHERE scenario_name = ?
                        )
                    )
                GROUP BY timepoint
                """,
                params=(BY_LOAD_COMPONENT,),
            )
            .set_index("timepoint")
            .reindex(results.index)["load_mw"]
        )
        bulk_power = self.linked_prjs_bulk_power(BY_LOAD_COMPONENT)
        # Both linked projects modify the load in every timepoint
        self.assertTrue((bulk_power.abs() > 1e-6).all().all())
        pd.testing.assert_series_equal(
            results["reserve_requirement_mw"],
            PERCENT_REQUIREMENT * (static_load - bulk_power.sum()),
            check_names=False,
            rtol=1e-9,
        )

    def test_requirement_binds(self):
        for scenario_name in [WHOLE_LOAD_ZONE, BY_LOAD_COMPONENT]:
            with self.subTest(scenario_name=scenario_name):
                results = self.lf_reserves_up_results(scenario_name)
                self.assertGreater((results["dual"].abs() > 1e-9).sum(), 0)
                self.assertTrue((results["reserve_violation_mw"] == 0).all())


if __name__ == "__main__":
    unittest.main()
