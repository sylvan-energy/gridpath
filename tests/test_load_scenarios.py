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

"""
Tests for the gridpath_load_scenarios entry point (db/utilities/scenario.py),
in particular the --yes flag that skips the interactive delete/re-load
confirmation prompts for non-interactive use.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from db import create_database
from db.utilities import scenario


class TestLoadScenariosYesFlag(unittest.TestCase):
    def setUp(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.db_path = os.path.join(tmp_dir.name, "test.db")
        # Schema plus the model-defaults data (the status-type lookup tables
        # the scenarios table's defaults reference); a scenario row with no
        # subscenario IDs set needs no other input data
        create_database.main(
            [
                "--database",
                self.db_path,
                "--data_directory",
                os.path.join(os.path.dirname(create_database.__file__), "data"),
            ]
        )
        self.csv_path = os.path.join(tmp_dir.name, "scenarios.csv")
        with open(self.csv_path, "w", newline="") as f:
            f.write(
                "optional_feature_or_subscenarios,s1\n"
                "of_transmission,0\n"
                "of_policy,1\n"
            )

    def _scenario_ids(self):
        conn = sqlite3.connect(self.db_path)
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT scenario_id FROM scenarios WHERE scenario_name = 's1'"
            )
        ]
        conn.close()
        return ids

    def _main(self, *extra_args):
        scenario.main(
            [
                "--database",
                self.db_path,
                "--csv_path",
                self.csv_path,
                "--scenario",
                "s1",
                "--quiet",
                *extra_args,
            ]
        )

    def test_yes_skips_reload_and_delete_prompts(self):
        # Any call to input() would hang a headless run; make it fail loudly
        with mock.patch("builtins.input", side_effect=AssertionError("prompted")):
            self._main()
            first_ids = self._scenario_ids()
            self.assertEqual(1, len(first_ids))

            # Re-loading an existing scenario deletes and re-creates it
            self._main("--yes")
            second_ids = self._scenario_ids()
            self.assertEqual(1, len(second_ids))
            self.assertNotEqual(first_ids, second_ids)

            self._main("--yes", "--delete")
            self.assertEqual([], self._scenario_ids())

    def test_prompts_without_yes(self):
        self._main()

        with mock.patch("builtins.input", return_value="n") as prompt:
            self._main("--delete")
        prompt.assert_called_once()
        self.assertEqual(1, len(self._scenario_ids()))

        with mock.patch("builtins.input", return_value="n") as prompt:
            self._main()
        prompt.assert_called_once()
        self.assertEqual(1, len(self._scenario_ids()))

        with mock.patch("builtins.input", return_value="y"):
            self._main("--delete")
        self.assertEqual([], self._scenario_ids())


if __name__ == "__main__":
    unittest.main()
