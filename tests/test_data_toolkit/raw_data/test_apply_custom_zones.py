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

import contextlib
import io
import os
import sqlite3
import tempfile
import unittest

import pandas as pd

from db.create_database import main as create_database_main
from data_toolkit.raw_data.apply_custom_zones import (
    main as apply_custom_zones_main,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "data_toolkit",
    "raw_data_db_schema.sql",
)

BAA_FIXTURE_ROWS = [
    # (baa, region, interconnect)
    ("Zone1", "Region1", "Interconnect1"),
    ("Zone2", "Region1", "Interconnect1"),
    ("Zone3", "Region2", "Interconnect1"),
    ("ZoneX", "RegionX", "InterconnectX"),
]


class TestApplyCustomZones(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.db_path = os.path.join(self.tmp_dir.name, "custom_zones_test_raw.db")
        create_database_main(
            [
                "--database",
                self.db_path,
                "--db_schema",
                RAW_DATA_DB_SCHEMA,
                "--quiet",
            ]
        )
        conn = sqlite3.connect(self.db_path)
        conn.executemany(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES (?, ?, ?)",
            BAA_FIXTURE_ROWS,
        )
        conn.commit()
        conn.close()

    def write_csv(self, df, name="zones.csv"):
        path = os.path.join(self.tmp_dir.name, name)
        df.to_csv(path, index=False)
        return path

    def run_step(self, csv_path, quiet=False):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            apply_custom_zones_main(
                ["--database", self.db_path, "--custom_zone_csv", csv_path]
                + (["--quiet"] if quiet else [])
            )
        return out.getvalue()

    def custom_zones(self):
        conn = sqlite3.connect(self.db_path)
        rows = dict(conn.execute("SELECT baa, custom_zone FROM raw_data_eia_baa_codes"))
        conn.close()
        return rows

    def test_basic_apply_and_report(self):
        csv_path = self.write_csv(
            pd.DataFrame({"baa": ["Zone1", "Zone2", "Zone3"], "zone": ["A", "A", "B"]})
        )
        output = self.run_step(csv_path)

        self.assertEqual(
            self.custom_zones(),
            {"Zone1": "A", "Zone2": "A", "Zone3": "B", "ZoneX": None},
        )
        self.assertIn("3 BAs mapped to 2 zones (A, B)", output)
        self.assertIn("1 map BAs left unmapped", output)

    def test_ba_column_subregion_rows_and_external_bas(self):
        # The wecc6-style CSV shape: a 'ba' column, extra columns, sub-BA
        # rows (skipped), and external-zone BAs not in the map (reported)
        csv_path = self.write_csv(
            pd.DataFrame(
                {
                    "ba": ["Zone1", "Zone1", "Zone2", "External1"],
                    "eia930_subregion": ["", "SUBR", "", ""],
                    "zone": ["A", "B", "A", "Canada"],
                    "notes": ["", "sub-BA row", "", "external"],
                }
            )
        )
        output = self.run_step(csv_path)

        # the subregion row's conflicting zone was skipped, not applied
        self.assertEqual(
            self.custom_zones(),
            {"Zone1": "A", "Zone2": "A", "Zone3": None, "ZoneX": None},
        )
        self.assertIn("skipped 1 rows with a non-empty eia930_subregion", output)
        self.assertIn("External1", output)

    def test_rerun_resets_previous_mapping(self):
        self.run_step(
            self.write_csv(
                pd.DataFrame({"baa": ["Zone1", "Zone2"], "zone": ["A", "A"]}),
                name="first.csv",
            )
        )
        self.run_step(
            self.write_csv(
                pd.DataFrame({"baa": ["Zone3"], "zone": ["C"]}), name="second.csv"
            )
        )

        # Zone1/Zone2 reset to NULL — the CSV is the complete mapping
        self.assertEqual(
            self.custom_zones(),
            {"Zone1": None, "Zone2": None, "Zone3": "C", "ZoneX": None},
        )

    def test_adds_column_to_pre_custom_zone_database(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("ALTER TABLE raw_data_eia_baa_codes DROP COLUMN custom_zone")
        conn.commit()
        conn.close()

        output = self.run_step(
            self.write_csv(pd.DataFrame({"baa": ["Zone1"], "zone": ["A"]}))
        )

        self.assertIn("Added the custom_zone column", output)
        self.assertEqual(self.custom_zones()["Zone1"], "A")

    def test_conflicting_duplicate_raises_identical_duplicate_tolerated(self):
        with self.assertRaises(ValueError):
            self.run_step(
                self.write_csv(
                    pd.DataFrame({"baa": ["Zone1", "Zone1"], "zone": ["A", "B"]})
                )
            )
        self.run_step(
            self.write_csv(
                pd.DataFrame({"baa": ["Zone1", "Zone1"], "zone": ["A", "A"]}),
                name="dup_same.csv",
            )
        )
        self.assertEqual(self.custom_zones()["Zone1"], "A")

    def test_missing_columns_and_empty_zone_raise(self):
        with self.assertRaises(ValueError):
            self.run_step(
                self.write_csv(pd.DataFrame({"balancing_authority": ["Zone1"]}))
            )
        with self.assertRaises(ValueError):
            self.run_step(
                self.write_csv(pd.DataFrame({"baa": ["Zone1"], "zone": [""]}))
            )


if __name__ == "__main__":
    unittest.main()
