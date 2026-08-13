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
A scenario can use any combination of the three iteration levels -- e.g.
weather and availability iterations but no hydro iterations. These tests pin
that all three scenario-structure sources (disk inference, the database, and
the temporal-structure CSV) handle such a "sparse middle" level: the unused
level gets a single 0 key and a False flag, in the right position.
"""

import os
import sqlite3
import tempfile
import unittest

from gridpath.auxiliary.scenario_chars import (
    get_scenario_structure_from_csv,
    get_scenario_structure_from_db,
    get_scenario_structure_from_disk,
)

DB_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "db_schema.sql")


def assert_sparse_middle_structure(test_case, structure):
    test_case.assertTrue(structure.WEATHER_ITERATION_FLAG)
    test_case.assertFalse(structure.HYDRO_ITERATION_FLAG)
    test_case.assertTrue(structure.AVAILABILITY_ITERATION_FLAG)
    for w in structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT:
        # The unused hydro level is a single 0 key in the middle position
        test_case.assertEqual(
            list(structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[w].keys()),
            [0],
        )
        test_case.assertEqual(
            sorted(structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[w][0].keys()),
            [10, 11],
        )


class TestSparseIterationLevels(unittest.TestCase):
    def test_structure_from_disk(self):
        with tempfile.TemporaryDirectory() as scenario_directory:
            for w in (1, 2):
                for a in (10, 11):
                    for subproblem in ("1", "2"):
                        for subdirectory in ("inputs", "results"):
                            os.makedirs(
                                os.path.join(
                                    scenario_directory,
                                    f"weather_iteration_{w}",
                                    f"availability_iteration_{a}",
                                    subproblem,
                                    subdirectory,
                                )
                            )

            structure = get_scenario_structure_from_disk(scenario_directory)

        assert_sparse_middle_structure(self, structure)
        self.assertTrue(structure.SUBPROBLEM_FLAG)
        self.assertFalse(structure.STAGE_FLAG)

    def test_structure_from_db(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with open(DB_SCHEMA_PATH, "r") as schema_f:
            conn.executescript(schema_f.read())
        conn.execute(
            "INSERT INTO scenarios (scenario_id, scenario_name, "
            "temporal_scenario_id) VALUES (1, 'sparse_test', 1);"
        )
        # The unused hydro level is stored as 0 in inputs_temporal_iterations
        for w in (1, 2):
            for a in (10, 11):
                conn.execute(
                    """INSERT INTO inputs_temporal_iterations
                    (temporal_scenario_id, weather_iteration, hydro_iteration,
                    availability_iteration) VALUES (1, ?, 0, ?);""",
                    (w, a),
                )
        for subproblem in (1, 2):
            conn.execute(
                "INSERT INTO inputs_temporal_subproblems (temporal_scenario_id, "
                "subproblem_id) VALUES (1, ?);",
                (subproblem,),
            )
            conn.execute(
                "INSERT INTO inputs_temporal_subproblems_stages "
                "(temporal_scenario_id, subproblem_id, stage_id) VALUES (1, ?, 1);",
                (subproblem,),
            )
        conn.commit()

        structure = get_scenario_structure_from_db(conn=conn, scenario_id=1)

        assert_sparse_middle_structure(self, structure)
        self.assertTrue(structure.SUBPROBLEM_FLAG)
        self.assertFalse(structure.STAGE_FLAG)

    def test_structure_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = os.path.join(tmp_dir, "structure.csv")
            with open(csv_path, "w", newline="") as f:
                f.write(
                    "weather_iteration,hydro_iteration,availability_iteration,"
                    "subproblem,stage\n"
                )
                for w in (1, 2):
                    for a in (10, 11):
                        for subproblem in (1, 2):
                            f.write(f"{w},0,{a},{subproblem},1\n")

            structure = get_scenario_structure_from_csv(csv_path)

        assert_sparse_middle_structure(self, structure)
        self.assertTrue(structure.SUBPROBLEM_FLAG)
        self.assertFalse(structure.STAGE_FLAG)


if __name__ == "__main__":
    unittest.main()
