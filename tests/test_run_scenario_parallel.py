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

import csv
import os
import shutil
import tempfile
import unittest

from gridpath import run_scenario_parallel

# Change directory to the 'gridpath' directory as that's what
# run_scenario_parallel.py expects; the rest of the variables are relative
# paths from there
os.chdir(os.path.join(os.path.dirname(__file__), "../gridpath"))

EXAMPLES_DIRECTORY = os.path.join("..", "examples")


class TestRunScenarioParallel(unittest.TestCase):
    def test_parallel_scenarios(self):
        scenarios_csv_path = os.path.join(
            os.getcwd(), "../tests/test_data/scenarios_to_run.csv"
        )

        # Run the scenarios in a temporary copy of their example
        # directories, so that this test doesn't write into examples/
        # directories that concurrently running tests may also be using;
        # point the scenario_location row of the scenarios CSV at the copy
        with tempfile.TemporaryDirectory() as tmp_dir:
            with open(scenarios_csv_path, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))

            scenario_names = rows[0][1:]
            for scenario_name in scenario_names:
                shutil.copytree(
                    os.path.join(EXAMPLES_DIRECTORY, scenario_name),
                    os.path.join(tmp_dir, scenario_name),
                )

            for row in rows:
                if row[0] == "scenario_location":
                    row[1:] = [tmp_dir] * len(scenario_names)

            tmp_csv_path = os.path.join(tmp_dir, "scenarios_to_run.csv")
            with open(tmp_csv_path, "w", newline="") as f:
                csv.writer(f).writerows(rows)

            run_scenario_parallel.main(
                ["--scenarios_csv", tmp_csv_path, "--n_parallel_scenarios", "2"]
            )


if __name__ == "__main__":
    unittest.main()
