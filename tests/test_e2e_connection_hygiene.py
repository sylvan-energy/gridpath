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
The E2E step mains must close their database connection when they raise: a
connection left open by an error keeps the database file locked on Windows
(and, held alive via the exception traceback, is never garbage-collected
under unittest's assertRaises).
"""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from gridpath import get_scenario_inputs, import_scenario_results, process_results

DB_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "db_schema.sql")


class TestConnectionClosedOnError(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.db_path = os.path.join(self.tmp_dir.name, "hygiene_test.db")
        conn = sqlite3.connect(self.db_path)
        try:
            with open(DB_SCHEMA_PATH, "r") as schema_f:
                conn.executescript(schema_f.read())
            conn.commit()
        finally:
            conn.close()

    def assert_connection_closed_on_error(self, module):
        """
        Run the module's main() against a scenario that doesn't exist (which
        raises after the connection is opened) and assert the connection it
        opened was closed on the way out.
        """
        created_connections = []
        real_connect = module.connect_to_database

        def spy_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            created_connections.append(conn)
            return conn

        with mock.patch.object(module, "connect_to_database", side_effect=spy_connect):
            with self.assertRaises(ValueError):
                module.main(
                    [
                        "--database",
                        self.db_path,
                        "--scenario",
                        "no_such_scenario",
                        "--quiet",
                    ]
                )

        self.assertEqual(len(created_connections), 1)
        # Executing on a closed connection raises ProgrammingError
        with self.assertRaises(sqlite3.ProgrammingError):
            created_connections[0].execute("SELECT 1;")

    def test_get_scenario_inputs_closes_connection_on_error(self):
        self.assert_connection_closed_on_error(get_scenario_inputs)

    def test_import_scenario_results_closes_connection_on_error(self):
        self.assert_connection_closed_on_error(import_scenario_results)

    def test_process_results_closes_connection_on_error(self):
        self.assert_connection_closed_on_error(process_results)


if __name__ == "__main__":
    unittest.main()
