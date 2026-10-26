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
Differential test for by-timepoint reserve requirements keyed by weather
iteration. In ``ra_toolkit_monte_carlo_w_weather_dependent_reserves`` the
RSG1 spinning reserve requirement (subscenario 4) is a by-timepoint MW
profile flagged to vary by weather iteration, with one slice per Monte Carlo
draw (weather iterations 1 and 2), each equal to 80% of that draw's load. Its
twin ``..._percent_twin`` (subscenario 3) specifies the same requirement as
80% of load, which already varies by weather iteration because each draw
reads its own load. The two must agree draw by draw:

* identical objective function values;
* identical requirement, provision and violation in every timepoint.

The requirement binds in every subproblem of both draws (non-zero duals),
and the draws' requirements differ, so a draw reading the other draw's slice
or the weather iteration 0 rows would break the equality.

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

WEATHER_DEPENDENT = "ra_toolkit_monte_carlo_w_weather_dependent_reserves"
PERCENT_TWIN = "ra_toolkit_monte_carlo_w_weather_dependent_reserves_percent_twin"

DRAW_COLUMNS = [
    "weather_iteration",
    "hydro_iteration",
    "availability_iteration",
    "subproblem_id",
    "stage_id",
]


class TestReserveRequirementWeatherIterationExamples(unittest.TestCase):
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
        for scenario_name in [WEATHER_DEPENDENT, PERCENT_TWIN]:
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

    def spinning_reserve_results(self, scenario_name):
        conn = sqlite3.connect(self.db_path)
        try:
            df = pd.read_sql(
                """
                SELECT r.*
                FROM results_system_spinning_reserves AS r
                JOIN scenarios USING (scenario_id)
                WHERE scenario_name = ?
                """,
                conn,
                params=(scenario_name,),
            )
        finally:
            conn.close()
        return df.set_index(
            DRAW_COLUMNS + ["spinning_reserves_ba", "timepoint"]
        ).sort_index()

    def test_objectives_match_twin(self):
        weather_dependent = self.objectives[WEATHER_DEPENDENT]
        twin = self.objectives[PERCENT_TWIN]
        self.assertEqual(len(weather_dependent), 4)
        self.assertSetEqual(set(weather_dependent), set(twin))
        for draw in weather_dependent:
            self.assertNotAlmostEqual(weather_dependent[draw][1], 0, places=2)
            self.assertAlmostEqual(
                weather_dependent[draw][1],
                twin[draw][1],
                delta=1e-9 * abs(twin[draw][1]),
                msg=draw,
            )
        # The draws' objectives differ, so matching per draw is a real check
        self.assertEqual(
            len(set(round(o[1], 6) for o in weather_dependent.values())), 4
        )

    def test_reserve_results_match_twin(self):
        weather_dependent = self.spinning_reserve_results(WEATHER_DEPENDENT)
        twin = self.spinning_reserve_results(PERCENT_TWIN)
        self.assertEqual(len(weather_dependent), 672)
        self.assertListEqual(list(weather_dependent.index), list(twin.index))
        for column in [
            "reserve_requirement_mw",
            "reserve_provision_mw",
            "reserve_violation_mw",
        ]:
            pd.testing.assert_series_equal(
                weather_dependent[column], twin[column], rtol=1e-9, atol=1e-6
            )

    def test_requirement_binds_and_differs_by_draw(self):
        df = self.spinning_reserve_results(WEATHER_DEPENDENT).reset_index()
        binding = df[df["dual"].abs() > 1e-9].groupby(DRAW_COLUMNS).size()
        self.assertEqual(len(binding), 4)

        requirement = df.pivot_table(
            index=["subproblem_id", "timepoint"],
            columns="weather_iteration",
            values="reserve_requirement_mw",
        )
        self.assertGreater((requirement[1] - requirement[2]).abs().max(), 1)


if __name__ == "__main__":
    unittest.main()
