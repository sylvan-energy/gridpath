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
The iteration-keyed opchar input tables (variable generator profiles, hydro
operating characteristics, energy profiles, ...) are read with equality
filters on weather_iteration, hydro_iteration, and stage_id (e.g.
weather_iteration = 0 for inputs that do not vary by weather iteration).
NULL never satisfies an equality filter, so a blank key cell would silently
drop the row and the project would end up with no data. The schema must
therefore declare these columns NOT NULL, so blank cells fail at CSV import
instead.
"""

import os.path
import sqlite3
import unittest

DB_SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "db", "db_schema.sql")

ITERATION_KEY_COLUMNS = ["weather_iteration", "hydro_iteration", "stage_id"]

# The tables read via get_prj_temporal_index_opr_inputs_from_db as of this
# writing; the discovery below must find at least these
KNOWN_ITERATION_KEYED_TABLES = {
    "inputs_project_energy_hrz_shaping",
    "inputs_project_energy_profiles",
    "inputs_project_energy_slice_hrz_shaping",
    "inputs_project_hydro_operational_chars",
    "inputs_project_load_component_shift_bounds",
    "inputs_project_load_modifier_profiles",
    "inputs_project_stor_exog_state_of_charge",
    "inputs_project_variable_generator_profiles",
    "inputs_project_variable_om_cost_by_timepoint",
}


def get_iteration_keyed_opchar_input_tables(conn):
    """
    Every inputs_project_* table with a companion <table>_iterations table
    whose subscenario ID column is a column of
    inputs_project_operational_chars -- the tables read via
    get_prj_temporal_index_opr_inputs_from_db.
    """
    c = conn.cursor()
    opchar_columns = {
        row[1]
        for row in c.execute("PRAGMA table_info(inputs_project_operational_chars)")
    }
    iterations_tables = [row[0] for row in c.execute("""SELECT name FROM sqlite_master
            WHERE type = 'table' AND name LIKE 'inputs_project_%_iterations'""")]

    tables = []
    for iterations_table in iterations_tables:
        subscenario_id_columns = [
            row[1]
            for row in c.execute(f"PRAGMA table_info({iterations_table})")
            if row[1].endswith("_scenario_id") and row[1] in opchar_columns
        ]
        if subscenario_id_columns:
            tables.append(iterations_table[: -len("_iterations")])

    return sorted(tables)


class TestIterationKeyColumnsNotNull(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        self.addCleanup(self.conn.close)

    def test_discovery_covers_known_tables(self):
        tables = set(get_iteration_keyed_opchar_input_tables(self.conn))
        self.assertTrue(
            KNOWN_ITERATION_KEYED_TABLES <= tables,
            f"Missing: {sorted(KNOWN_ITERATION_KEYED_TABLES - tables)}",
        )

    def test_iteration_key_columns_are_not_null(self):
        """
        Every iteration key column present in each iteration-keyed table
        carries a NOT NULL constraint (PRAGMA table_info 'notnull' flag).
        """
        c = self.conn.cursor()
        for table in get_iteration_keyed_opchar_input_tables(self.conn):
            notnull_by_column = {
                row[1]: bool(row[3]) for row in c.execute(f"PRAGMA table_info({table})")
            }
            for column in ITERATION_KEY_COLUMNS:
                if column not in notnull_by_column:
                    continue
                with self.subTest(table=table, column=column):
                    self.assertTrue(
                        notnull_by_column[column],
                        f"{table}.{column} must be NOT NULL: the input query "
                        f"filters on it by equality, so a NULL would silently "
                        f"drop the row.",
                    )

    def test_blank_csv_cell_is_rejected_at_insert(self):
        """
        The CSV-import path turns a blank cell into NULL; the constraint must
        reject it with a message naming the table and column.
        """
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            self.conn.execute("""INSERT INTO inputs_project_variable_generator_profiles
                (project, variable_generator_profile_scenario_id,
                weather_iteration, hydro_iteration, stage_id, timepoint,
                cap_factor)
                VALUES ('Wind', 1, NULL, 0, 1, 2020010101, 0.5)""")
        self.assertIn(
            "NOT NULL constraint failed: "
            "inputs_project_variable_generator_profiles.weather_iteration",
            str(cm.exception),
        )


if __name__ == "__main__":
    unittest.main()
