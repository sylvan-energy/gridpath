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
Tests for input CSVs based on a default subscenario ID (file name ending with
a dash and the default subscenario ID, e.g. 2_change-1.csv): rows are added,
changed and -- via the ``remove_row`` column -- removed relative to the
default subscenario ID when the CSV is loaded into the database.
"""

import numpy as np
import os
import sqlite3
import tempfile
import unittest

from db.utilities.common_functions import (
    get_subscenario_data_and_insert_into_db,
)

SUBSCENARIO = "test_scenario_id"

# project and period are the keys; project is text, period an integer
CAPACITY_TABLE = "test_capacity"
CAPACITY_SCHEMA = f"""
CREATE TABLE inputs_{CAPACITY_TABLE} (
{SUBSCENARIO} INTEGER,
project VARCHAR(64),
period INTEGER,
capacity_mw FLOAT,
note VARCHAR(64),
PRIMARY KEY ({SUBSCENARIO}, project, period)
);
"""
CAPACITY_HEADER = "project,period,capacity_mw,note"
CAPACITY_DEFAULT_ROWS = [
    "Coal,2020,100,a",
    "Coal,2030,90,b",
    "Gas,2020,50,c",
    "Gas,2030,60,d",
    "Wind,2030,10,e",
]

# A table with a nullable primary-key column
COMPONENT_TABLE = "test_component"
COMPONENT_SCHEMA = f"""
CREATE TABLE inputs_{COMPONENT_TABLE} (
{SUBSCENARIO} INTEGER,
zone VARCHAR(64),
component VARCHAR(64),
percent FLOAT,
PRIMARY KEY ({SUBSCENARIO}, zone, component)
);
"""

# A table whose columns are all primary-key columns
MAP_TABLE = "test_map"
MAP_SCHEMA = f"""
CREATE TABLE inputs_{MAP_TABLE} (
{SUBSCENARIO} INTEGER,
project VARCHAR(64),
zone VARCHAR(64),
PRIMARY KEY ({SUBSCENARIO}, project, zone)
);
"""


class TestDefaultSubscenarioRows(unittest.TestCase):
    def setUp(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.inputs_dir = tmp_dir.name

        # The adapters gridpath_load_csvs registers (port_csvs_to_db.main)
        sqlite3.register_adapter(np.int64, lambda val: int(val))
        sqlite3.register_adapter(np.float64, lambda val: float(val))

        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        for schema in [CAPACITY_SCHEMA, COMPONENT_SCHEMA, MAP_SCHEMA]:
            self.conn.execute(schema)

    def load_csv(self, table, filename, header, rows):
        with open(os.path.join(self.inputs_dir, filename), "w") as f:
            f.write("\n".join([header] + rows) + "\n")

        get_subscenario_data_and_insert_into_db(
            conn=self.conn,
            quiet=True,
            subscenario=SUBSCENARIO,
            table=table,
            dir_subsc=False,
            inputs_dir=self.inputs_dir,
            csv_file=filename,
            use_project_method=False,
            sub_input_column=None,
            skip_subscenario_info=True,
            skip_subscenario_data=False,
            cols_to_exclude_str="nan",
            custom_method="nan",
        )

    def load_capacity_default(self):
        self.load_csv(
            CAPACITY_TABLE, "1_default.csv", CAPACITY_HEADER, CAPACITY_DEFAULT_ROWS
        )

    def load_capacity_change(self, rows, header=CAPACITY_HEADER + ",remove_row"):
        self.load_csv(CAPACITY_TABLE, "2_change-1.csv", header, rows)

    def get_rows(self, table, subscenario_id):
        columns = [
            r[1]
            for r in self.conn.execute(f"PRAGMA table_info(inputs_{table});")
            if r[1] != SUBSCENARIO
        ]
        return sorted(
            self.conn.execute(
                f"""SELECT {", ".join(columns)} FROM inputs_{table}
                WHERE {SUBSCENARIO} = ?;""",
                (subscenario_id,),
            ).fetchall(),
            key=lambda row: tuple(str(v) for v in row),
        )

    def test_add_and_change_rows(self):
        """
        Without the remove_row column: the subscenario's own rows win, the
        other rows of the default subscenario ID are copied.
        """
        self.load_capacity_default()
        self.load_capacity_change(
            rows=["Coal,2030,95,changed", "Solar,2030,5,added"],
            header=CAPACITY_HEADER,
        )

        self.assertListEqual(
            self.get_rows(CAPACITY_TABLE, 2),
            [
                ("Coal", 2020, 100.0, "a"),
                ("Coal", 2030, 95.0, "changed"),
                ("Gas", 2020, 50.0, "c"),
                ("Gas", 2030, 60.0, "d"),
                ("Solar", 2030, 5.0, "added"),
                ("Wind", 2030, 10.0, "e"),
            ],
        )
        # The default subscenario ID is untouched
        self.assertEqual(len(self.get_rows(CAPACITY_TABLE, 1)), 5)

    def test_remove_row_by_full_key(self):
        self.load_capacity_default()
        self.load_capacity_change(
            rows=["Coal,2030,,,1", "Gas,2030,65,changed,"],
        )

        self.assertListEqual(
            self.get_rows(CAPACITY_TABLE, 2),
            [
                ("Coal", 2020, 100.0, "a"),
                ("Gas", 2020, 50.0, "c"),
                ("Gas", 2030, 65.0, "changed"),
                ("Wind", 2030, 10.0, "e"),
            ],
        )
        self.assertEqual(len(self.get_rows(CAPACITY_TABLE, 1)), 5)

    def test_remove_rows_with_blank_key_as_wildcard(self):
        """
        A blank primary-key cell matches any value: all of Coal, and every
        project's 2020 row.
        """
        self.load_capacity_default()
        self.load_capacity_change(rows=["Coal,,,,1"])
        self.assertListEqual(
            self.get_rows(CAPACITY_TABLE, 2),
            [
                ("Gas", 2020, 50.0, "c"),
                ("Gas", 2030, 60.0, "d"),
                ("Wind", 2030, 10.0, "e"),
            ],
        )

        self.load_csv(
            CAPACITY_TABLE,
            "3_change-1.csv",
            CAPACITY_HEADER + ",remove_row",
            [",2020,,,1"],
        )
        self.assertListEqual(
            self.get_rows(CAPACITY_TABLE, 3),
            [
                ("Coal", 2030, 90.0, "b"),
                ("Gas", 2030, 60.0, "d"),
                ("Wind", 2030, 10.0, "e"),
            ],
        )

    def test_remove_then_add_replaces_a_block(self):
        """
        Removal filters only what is inherited: the subscenario's own rows
        are loaded even when a wildcard removal covers their keys.
        """
        self.load_capacity_default()
        self.load_capacity_change(rows=["Coal,,,,1", "Coal,2040,80,new,"])

        self.assertListEqual(
            self.get_rows(CAPACITY_TABLE, 2),
            [
                ("Coal", 2040, 80.0, "new"),
                ("Gas", 2020, 50.0, "c"),
                ("Gas", 2030, 60.0, "d"),
                ("Wind", 2030, 10.0, "e"),
            ],
        )

    def test_flagged_rows_do_not_change_data_types(self):
        """
        The blank cells of a flagged row must not change how the data rows
        are read: integers in a text column (the note) would otherwise
        become floats and be stored as '7.0'.
        """
        self.load_capacity_default()
        self.load_capacity_change(rows=["Coal,,,,1", "Solar,2030,5,7,"])

        self.assertListEqual(
            self.conn.execute(f"""SELECT period, note FROM inputs_{CAPACITY_TABLE}
                WHERE {SUBSCENARIO} = 2 AND project = 'Solar';""").fetchall(),
            [(2030, "7")],
        )

    def test_chained_default_subscenarios(self):
        """
        A subscenario ID based on one that was itself based on another one
        starts from the latter's loaded rows (removals included).
        """
        self.load_capacity_default()
        self.load_capacity_change(rows=["Coal,,,,1"])
        self.load_csv(
            CAPACITY_TABLE,
            "3_change-2.csv",
            CAPACITY_HEADER + ",remove_row",
            ["Wind,2030,,,1"],
        )

        self.assertListEqual(
            self.get_rows(CAPACITY_TABLE, 3),
            [("Gas", 2020, 50.0, "c"), ("Gas", 2030, 60.0, "d")],
        )

    def test_removal_matching_no_default_row_raises(self):
        self.load_capacity_default()
        with self.assertRaisesRegex(ValueError, "match no row"):
            self.load_capacity_change(rows=["Cole,2030,,,1"])

    def test_removal_with_data_values_raises(self):
        self.load_capacity_default()
        with self.assertRaisesRegex(ValueError, "has values in"):
            self.load_capacity_change(rows=["Coal,2030,95,,1"])

    def test_entirely_blank_removal_raises(self):
        self.load_capacity_default()
        with self.assertRaisesRegex(ValueError, "entirely blank"):
            self.load_capacity_change(rows=[",,,,1"])

    def test_unknown_flag_value_raises(self):
        self.load_capacity_default()
        with self.assertRaisesRegex(ValueError, "must be 1"):
            self.load_capacity_change(rows=["Coal,2030,,,yes"])

    def test_removal_without_default_subscenario_raises(self):
        with self.assertRaisesRegex(ValueError, "not based on a default"):
            self.load_csv(
                CAPACITY_TABLE,
                "1_default.csv",
                CAPACITY_HEADER + ",remove_row",
                ["Coal,2020,100,a,", "Coal,2030,,,1"],
            )

    def test_remove_row_column_without_flags(self):
        """
        An unflagged remove_row column is just dropped, with or without a
        default subscenario ID.
        """
        self.load_csv(
            CAPACITY_TABLE,
            "1_default.csv",
            CAPACITY_HEADER + ",remove_row",
            [row + "," for row in CAPACITY_DEFAULT_ROWS],
        )
        self.assertEqual(len(self.get_rows(CAPACITY_TABLE, 1)), 5)

    def test_null_primary_key_values(self):
        """
        Default rows with a NULL in a primary-key column are copied unless
        the subscenario has the very same key (NULL included).
        """
        header = "zone,component,percent"
        self.load_csv(
            COMPONENT_TABLE,
            "1_default.csv",
            header,
            ["Zone1,,0.1", "Zone1,a,0.2", "Zone2,,0.3", "Zone3,,0.4"],
        )
        self.load_csv(
            COMPONENT_TABLE,
            "2_change-1.csv",
            header,
            ["Zone1,b,0.5", "Zone2,,0.6"],
        )

        self.assertListEqual(
            self.get_rows(COMPONENT_TABLE, 2),
            [
                ("Zone1", None, 0.1),
                ("Zone1", "a", 0.2),
                ("Zone1", "b", 0.5),
                ("Zone2", None, 0.6),
                ("Zone3", None, 0.4),
            ],
        )

    def test_wildcard_removal_includes_null_keyed_rows(self):
        """
        A blank key cell is a wildcard, so a NULL-keyed default row goes
        with its siblings; it cannot be removed on its own.
        """
        header = "zone,component,percent"
        self.load_csv(
            COMPONENT_TABLE,
            "1_default.csv",
            header,
            ["Zone1,,0.1", "Zone1,a,0.2", "Zone2,,0.3"],
        )
        self.load_csv(
            COMPONENT_TABLE,
            "2_change-1.csv",
            header + ",remove_row",
            ["Zone1,,,1"],
        )

        self.assertListEqual(self.get_rows(COMPONENT_TABLE, 2), [("Zone2", None, 0.3)])

    def test_table_with_only_primary_key_columns(self):
        header = "project,zone"
        self.load_csv(
            MAP_TABLE, "1_default.csv", header, ["Coal,Zone1", "Gas,Zone1", "Gas,Zone2"]
        )
        self.load_csv(
            MAP_TABLE,
            "2_change-1.csv",
            header + ",remove_row",
            ["Gas,Zone2,1", "Wind,Zone2,"],
        )

        self.assertListEqual(
            self.get_rows(MAP_TABLE, 2),
            [("Coal", "Zone1"), ("Gas", "Zone1"), ("Wind", "Zone2")],
        )


if __name__ == "__main__":
    unittest.main()
