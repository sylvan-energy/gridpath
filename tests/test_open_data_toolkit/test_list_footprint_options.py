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

import duckdb
import pandas as pd

from db.create_database import main as create_database_main
from open_data_toolkit.list_footprint_options import main as list_footprint_options_main
from open_data_toolkit.project.project_data_filters_common import get_footprint_options

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "open_data_toolkit",
    "raw_data_db_schema.sql",
)

BAA_CODES_FIXTURE_ROWS = [
    # (baa, region, interconnect)
    ("Zone1", "Region1", "Interconnect1"),
    ("Zone2", "Region1", "Interconnect1"),
    ("ZoneX", "RegionX", "InterconnectX"),
]

EXPECTED_OPTIONS_OUTPUT = (
    "  interconnect: Interconnect1 (2 BAs)\n"
    "  interconnect: InterconnectX (1 BAs)\n"
    "  region: Region1 (2 BAs)\n"
    "  region: RegionX (1 BAs)\n"
    "  all: no footprint filter (3 mapped BAs)\n"
)


class TestListFootprintOptions(unittest.TestCase):
    """
    Test the footprint-options listing against each of its three BA-map
    sources (raw database, converted raw CSV, downloaded parquet) and its
    source-resolution order.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        # Paths inside an empty directory: nothing available by default
        self.db_path = os.path.join(self.tmp_dir.name, "test_raw.db")
        self.raw_data_directory = os.path.join(self.tmp_dir.name, "raw_data")
        self.pudl_download_directory = os.path.join(self.tmp_dir.name, "pudl_download")
        os.makedirs(self.raw_data_directory)
        os.makedirs(self.pudl_download_directory)

    def make_raw_db(self):
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

    def make_raw_csv(self):
        pd.DataFrame(
            BAA_CODES_FIXTURE_ROWS, columns=["baa", "region", "interconnect"]
        ).to_csv(
            os.path.join(self.raw_data_directory, "pudl_eia_baa_codes.csv"),
            index=False,
        )

    def make_parquet(self):
        parquet_path = os.path.join(
            self.pudl_download_directory,
            "core_eia__codes_balancing_authorities.parquet",
        )
        baa_map_df = pd.DataFrame(
            BAA_CODES_FIXTURE_ROWS,
            columns=[
                "code",
                "balancing_authority_region_code_eia",
                "interconnect_code_eia",
            ],
        )
        duckdb.sql(
            f"COPY (SELECT * FROM baa_map_df) TO '{parquet_path}' (FORMAT PARQUET)"
        )

    def run_main(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            list_footprint_options_main(
                [
                    "--database",
                    self.db_path,
                    "--raw_data_directory",
                    self.raw_data_directory,
                    "--pudl_download_directory",
                    self.pudl_download_directory,
                ]
            )

        return out.getvalue()

    def test_get_footprint_options(self):
        # One entry per distinct region and interconnect, with type and
        # BA count, ordered by type then value
        self.make_raw_db()
        conn = sqlite3.connect(self.db_path)
        footprint_options = get_footprint_options(conn=conn)
        conn.close()

        self.assertEqual(
            footprint_options,
            [
                ("interconnect", "Interconnect1", 2),
                ("interconnect", "InterconnectX", 1),
                ("region", "Region1", 2),
                ("region", "RegionX", 1),
            ],
        )

    def test_raw_db_source(self):
        self.make_raw_db()
        output = self.run_main()

        self.assertEqual(
            output,
            f"Available --footprint values (from raw database {self.db_path}):\n"
            + EXPECTED_OPTIONS_OUTPUT,
        )

    def test_raw_csv_source(self):
        # No raw DB: fall back to the converted raw CSV
        self.make_raw_csv()
        output = self.run_main()

        self.assertIn("raw-data CSV", output.splitlines()[0])
        self.assertTrue(output.endswith(EXPECTED_OPTIONS_OUTPUT))

    def test_parquet_source(self):
        # Neither raw DB nor raw CSV: fall back to the downloaded parquet
        self.make_parquet()
        output = self.run_main()

        self.assertIn("PUDL download", output.splitlines()[0])
        self.assertTrue(output.endswith(EXPECTED_OPTIONS_OUTPUT))

    def test_most_processed_source_wins(self):
        # With all three present, the raw database is used
        self.make_raw_db()
        self.make_raw_csv()
        self.make_parquet()
        output = self.run_main()

        self.assertIn("raw database", output.splitlines()[0])

    def test_empty_db_falls_through(self):
        # A raw DB whose BA-map table is empty is not a usable source
        create_database_main(
            ["--database", self.db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.make_raw_csv()
        output = self.run_main()

        self.assertIn("raw-data CSV", output.splitlines()[0])

    def test_no_source_available(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as raised:
                list_footprint_options_main(
                    [
                        "--database",
                        self.db_path,
                        "--raw_data_directory",
                        self.raw_data_directory,
                        "--pudl_download_directory",
                        self.pudl_download_directory,
                    ]
                )

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("No BA map found", out.getvalue())
        self.assertIn("gridpath_get_pudl_data", out.getvalue())


if __name__ == "__main__":
    unittest.main()
