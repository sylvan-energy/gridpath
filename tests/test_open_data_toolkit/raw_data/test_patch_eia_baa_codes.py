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

import os
import sqlite3
import tempfile
import unittest

from db.create_database import main as create_database_main
from open_data_toolkit.raw_data.patch_eia_baa_codes import (
    apply_baa_map_patches,
    main as patch_eia_baa_codes_main,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "open_data_toolkit",
    "raw_data_db_schema.sql",
)

# The source-data gaps as PUDL v2026.7.2 has them, plus a fully populated
# control row; no SIKE row
BAA_CODES_FIXTURE_ROWS = [
    # (baa, region, interconnect)
    ("GRID", None, "western"),
    ("AVRN", "NW", None),
    ("GLHB", "MIDW", None),
    ("CISO", "CAL", "western"),
]


class TestPatchEIABaaCodes(unittest.TestCase):
    """
    Test the BA-map patch step: NULL-filling, the SIKE insert, idempotence,
    and that source-populated values are never overwritten.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.db_path = os.path.join(self.tmp_dir.name, "patch_test_raw.db")
        create_database_main(
            ["--database", self.db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        conn = sqlite3.connect(self.db_path)
        conn.executemany(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES (?, ?, ?)",
            BAA_CODES_FIXTURE_ROWS,
        )
        conn.commit()
        conn.close()

    def read_map(self):
        conn = sqlite3.connect(self.db_path)
        rows = {
            baa: (region, interconnect)
            for baa, region, interconnect in conn.cursor().execute(
                "SELECT baa, region, interconnect FROM raw_data_eia_baa_codes"
            )
        }
        conn.close()

        return rows

    def test_patches_applied_and_idempotent(self):
        patch_eia_baa_codes_main(["--database", self.db_path, "--quiet"])

        rows = self.read_map()
        self.assertEqual(rows["GRID"], ("NW", "western"))
        self.assertEqual(rows["AVRN"], ("NW", "western"))
        self.assertEqual(rows["GLHB"], ("MIDW", "eastern"))
        self.assertEqual(rows["SIKE"], ("MIDW", "eastern"))
        # The control row is untouched
        self.assertEqual(rows["CISO"], ("CAL", "western"))

        # Rerun: everything already in place, nothing changes
        conn = sqlite3.connect(self.db_path)
        n_changed = apply_baa_map_patches(conn=conn, quiet=True)
        conn.close()
        self.assertEqual(n_changed, 0)
        self.assertEqual(self.read_map(), rows)

    def test_source_values_take_precedence(self):
        # Simulate a future PUDL release that fixes the source data with
        # different values: the patch must not overwrite them
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE raw_data_eia_baa_codes SET region = 'SRC' WHERE baa = 'GRID'"
        )
        conn.execute(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES ('SIKE', 'SRC', 'SRC')"
        )
        conn.commit()

        apply_baa_map_patches(conn=conn, quiet=True)
        conn.close()

        rows = self.read_map()
        self.assertEqual(rows["GRID"], ("SRC", "western"))
        self.assertEqual(rows["SIKE"], ("SRC", "SRC"))


if __name__ == "__main__":
    unittest.main()
