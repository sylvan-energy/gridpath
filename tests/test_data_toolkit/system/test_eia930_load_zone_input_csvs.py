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
from data_toolkit.project.project_data_filters_common import report_footprint_type
from data_toolkit.system.eia930_load_zone_input_csvs import (
    main as eia930_load_zone_input_csvs_main,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "data_toolkit",
    "raw_data_db_schema.sql",
)

# Interchange between two in-region BAs, plus links to an out-of-region BA
# and to a BA missing from the BA map entirely
INTERCHANGE_FIXTURE_ROWS = [
    # (balancing_authority_code_eia, balancing_authority_code_adjacent_eia,
    #  datetime_pst_he)
    ("Zone1", "Zone2", "2024-06-01 10:00:00"),
    ("Zone2", "Zone1", "2024-06-01 10:00:00"),
    ("Zone1", "ZoneX", "2024-06-01 10:00:00"),
    ("Zone1", "ZoneUnmapped", "2024-06-01 10:00:00"),
]

BAA_CODES_FIXTURE_ROWS = [
    # (baa, region, interconnect)
    ("Zone1", "Region1", "Interconnect1"),
    ("Zone2", "Region1", "Interconnect1"),
    ("ZoneX", "RegionX", "InterconnectX"),
]


class TestEIA930LoadZoneInputCsvs(unittest.TestCase):
    """
    Test load-zone and load-balance CSV creation at both load-zone levels.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "eia930_lz_test_raw.db")

        create_database_main(
            [
                "--database",
                cls.db_path,
                "--db_schema",
                RAW_DATA_DB_SCHEMA,
                "--quiet",
            ]
        )

        conn = sqlite3.connect(cls.db_path)
        conn.executemany(
            """
            INSERT INTO raw_data_eia930_hourly_interchange
            (balancing_authority_code_eia,
            balancing_authority_code_adjacent_eia, datetime_pst_he)
            VALUES (?, ?, ?)
            """,
            INTERCHANGE_FIXTURE_ROWS,
        )
        conn.executemany(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES (?, ?, ?)",
            BAA_CODES_FIXTURE_ROWS,
        )
        conn.commit()
        conn.close()

    def run_step_and_read_csvs(self, load_zone_level, footprint="Region1"):
        lz_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        lb_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        eia930_load_zone_input_csvs_main(
            [
                "--database",
                self.db_path,
                "--footprint",
                footprint,
                "--load_zone_level",
                load_zone_level,
                "--lz_output_directory",
                lz_directory,
                "--load_zone_scenario_id",
                "1",
                "--load_zone_scenario_name",
                "test",
                "--lb_output_directory",
                lb_directory,
                "--load_balance_scenario_id",
                "1",
                "--load_balance_scenario_name",
                "test",
                "--quiet",
            ]
        )

        load_zones = pd.read_csv(os.path.join(lz_directory, "1_test.csv"))
        load_balance = pd.read_csv(os.path.join(lb_directory, "1_test.csv"))

        return load_zones, load_balance

    def test_baa_level(self):
        # One load zone per in-region BA observed in the interchange data;
        # the out-of-region BA is excluded
        load_zones, load_balance = self.run_step_and_read_csvs(load_zone_level="baa")

        self.assertEqual(sorted(load_zones["load_zone"].tolist()), ["Zone1", "Zone2"])
        # The load-balance CSV has one row per zone
        self.assertEqual(sorted(load_balance["load_zone"].tolist()), ["Zone1", "Zone2"])
        self.assertTrue(
            (load_balance["unserved_energy_penalty_per_mwh"] == 20000).all()
        )

    def test_region_level(self):
        # One load zone per EIA930 region: the two in-region BAs collapse
        # into a single zone
        load_zones, load_balance = self.run_step_and_read_csvs(load_zone_level="region")

        self.assertEqual(load_zones["load_zone"].tolist(), ["Region1"])
        self.assertEqual(load_balance["load_zone"].tolist(), ["Region1"])

    def test_interconnect_level(self):
        # One load zone per interconnect: the two in-region BAs collapse
        # into their shared interconnect
        load_zones, load_balance = self.run_step_and_read_csvs(
            load_zone_level="interconnect"
        )

        self.assertEqual(load_zones["load_zone"].tolist(), ["Interconnect1"])
        self.assertEqual(load_balance["load_zone"].tolist(), ["Interconnect1"])

    def test_all_level(self):
        # One zone spanning the whole footprint, named after the --footprint
        # value: with an interconnect footprint this matches, for that
        # interconnect, what the 'interconnect' level produces on the
        # unfiltered data
        load_zones, load_balance = self.run_step_and_read_csvs(
            load_zone_level="all", footprint="Interconnect1"
        )

        self.assertEqual(load_zones["load_zone"].tolist(), ["Interconnect1"])
        self.assertEqual(load_balance["load_zone"].tolist(), ["Interconnect1"])

    def test_all_scope_baa_level(self):
        # 'all' includes every mapped BA observed in the interchange data;
        # the unmapped BA is still excluded
        load_zones, load_balance = self.run_step_and_read_csvs(
            load_zone_level="baa", footprint="all"
        )

        self.assertEqual(
            sorted(load_zones["load_zone"].tolist()), ["Zone1", "Zone2", "ZoneX"]
        )

    def test_all_scope_interconnect_level(self):
        load_zones, load_balance = self.run_step_and_read_csvs(
            load_zone_level="interconnect", footprint="all"
        )

        self.assertEqual(
            sorted(load_zones["load_zone"].tolist()),
            ["Interconnect1", "InterconnectX"],
        )

    def report_footprint_output(self, footprint, quiet=False):
        conn = sqlite3.connect(self.db_path)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report_footprint_type(conn=conn, footprint=footprint, quiet=quiet)
        conn.close()

        return out.getvalue()

    def test_report_footprint_type(self):
        # The message says which map column the footprint value matched
        self.assertEqual(
            self.report_footprint_output("Region1"),
            "Footprint 'Region1' is an EIA930 region (2 BAs in the BA map).\n",
        )
        self.assertEqual(
            self.report_footprint_output("Interconnect1"),
            "Footprint 'Interconnect1' is an interconnect " "(2 BAs in the BA map).\n",
        )
        self.assertEqual(
            self.report_footprint_output("all"),
            "Footprint 'all': no footprint filter (all mapped BAs).\n",
        )
        # Informational messages respect quiet
        self.assertEqual(self.report_footprint_output("Region1", quiet=True), "")
        # A footprint matching nothing warns even when quiet
        no_match_output = self.report_footprint_output("Nowhere", quiet=True)
        self.assertIn("WARNING", no_match_output)
        self.assertIn("all outputs will be empty", no_match_output)

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
