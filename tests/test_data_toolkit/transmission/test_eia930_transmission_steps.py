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
from data_toolkit.transmission.load_zones.eia930_to_transmission_load_zone_input_csvs import (
    main as tx_load_zones_main,
)
from data_toolkit.transmission.capacity_specified.eia930_to_transmission_specified_capacity_input_csvs import (
    main as tx_capacity_main,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "data_toolkit",
    "raw_data_db_schema.sql",
)

# Zone1 and Zone2 are in Region1, Zone3 in Region2, all in Interconnect1;
# Zone4 is in Region2 but a different interconnect (so Region2 spans two
# interconnects); ZoneOut is outside all of them; ZoneNoIC has no
# interconnect in the map (like generation-only and foreign BAs)
BAA_CODES_FIXTURE_ROWS = [
    # (baa, region, interconnect)
    ("Zone1", "Region1", "Interconnect1"),
    ("Zone2", "Region1", "Interconnect1"),
    ("Zone3", "Region2", "Interconnect1"),
    ("Zone4", "Region2", "Interconnect2"),
    ("ZoneOut", "RegionX", "InterconnectX"),
    ("ZoneNoIC", "RegionX", None),
]

# Two hours of two-sided interchange reports. Region1->Region2 hourly sums
# are 150 and 130, while the individual pairs peak at 120 and 50 — so the
# region-level capacity (max of hourly sums = 150) differs from the sum of
# the BA-pair capacities (170)
INTERCHANGE_FIXTURE_ROWS = [
    # (from, to, datetime_pst_he, mwh)
    ("Zone1", "Zone3", "2024-06-01 10:00:00", 100),
    ("Zone3", "Zone1", "2024-06-01 10:00:00", -100),
    ("Zone1", "Zone3", "2024-06-01 11:00:00", 120),
    ("Zone3", "Zone1", "2024-06-01 11:00:00", -120),
    ("Zone2", "Zone3", "2024-06-01 10:00:00", 50),
    ("Zone3", "Zone2", "2024-06-01 10:00:00", -50),
    ("Zone2", "Zone3", "2024-06-01 11:00:00", 10),
    ("Zone3", "Zone2", "2024-06-01 11:00:00", -10),
    ("Zone1", "Zone2", "2024-06-01 10:00:00", 30),
    ("Zone2", "Zone1", "2024-06-01 10:00:00", -30),
    ("Zone1", "Zone2", "2024-06-01 11:00:00", 30),
    ("Zone2", "Zone1", "2024-06-01 11:00:00", -30),
    # Interconnect-spanning link within Region2 (out of scope for the
    # Interconnect1 tests, since Zone4 is in Interconnect2)
    ("Zone3", "Zone4", "2024-06-01 10:00:00", 80),
    ("Zone4", "Zone3", "2024-06-01 10:00:00", -80),
    ("Zone3", "Zone4", "2024-06-01 11:00:00", 60),
    ("Zone4", "Zone3", "2024-06-01 11:00:00", -60),
    # Out of scope for the Interconnect1/Region1/Region2 tests; in scope
    # with --footprint all
    ("Zone1", "ZoneOut", "2024-06-01 10:00:00", 999),
    ("ZoneOut", "Zone1", "2024-06-01 10:00:00", -999),
    # Links involving the no-interconnect BA: in scope only for RegionX
    # or 'all', and never at the interconnect level (no zone there)
    ("Zone1", "ZoneNoIC", "2024-06-01 10:00:00", 70),
    ("ZoneNoIC", "Zone1", "2024-06-01 10:00:00", -70),
    ("ZoneOut", "ZoneNoIC", "2024-06-01 10:00:00", 55),
    ("ZoneNoIC", "ZoneOut", "2024-06-01 10:00:00", -55),
]


class TestEIA930TransmissionSteps(unittest.TestCase):
    """
    Test the transmission load-zone and specified-capacity steps at both
    load-zone levels, including the interconnect-based scoping.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "tx_test_raw.db")

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
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES (?, ?, ?)",
            BAA_CODES_FIXTURE_ROWS,
        )
        conn.executemany(
            """
            INSERT INTO raw_data_eia930_hourly_interchange
            (balancing_authority_code_eia,
            balancing_authority_code_adjacent_eia, datetime_pst_he,
            interchange_reported_mwh)
            VALUES (?, ?, ?, ?)
            """,
            INTERCHANGE_FIXTURE_ROWS,
        )
        conn.commit()
        conn.close()

    def run_load_zones(self, footprint, load_zone_level):
        output_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        tx_load_zones_main(
            [
                "--database",
                self.db_path,
                "--footprint",
                footprint,
                "--load_zone_level",
                load_zone_level,
                "--output_directory",
                output_directory,
                "--transmission_load_zone_scenario_id",
                "1",
                "--transmission_load_zone_scenario_name",
                "test",
                "--quiet",
            ]
        )

        return pd.read_csv(os.path.join(output_directory, "1_test.csv"))

    def run_capacity(self, footprint, load_zone_level):
        output_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        tx_capacity_main(
            [
                "--database",
                self.db_path,
                "--study_year",
                "2026",
                "--footprint",
                footprint,
                "--load_zone_level",
                load_zone_level,
                "--output_directory",
                output_directory,
                "--transmission_specified_capacity_scenario_id",
                "1",
                "--transmission_specified_capacity_scenario_name",
                "test",
                "--quiet",
            ]
        )

        return pd.read_csv(os.path.join(output_directory, "1_test.csv")).set_index(
            "transmission_line"
        )

    def set_custom_zones(self, zones_by_ba):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE raw_data_eia_baa_codes SET custom_zone = NULL")
        conn.executemany(
            "UPDATE raw_data_eia_baa_codes SET custom_zone = ? WHERE baa = ?",
            [(zone, ba) for ba, zone in zones_by_ba.items()],
        )
        conn.commit()
        conn.close()

    def test_custom_level(self):
        # Custom zones grouping Zone1+Zone2: the intra-zone link drops,
        # parallel BA pairs collapse into one custom-zone-pair line, and
        # the capacity is the max of the hourly sums (like the other
        # aggregated levels)
        self.set_custom_zones({"Zone1": "CustA", "Zone2": "CustA", "Zone3": "CustB"})

        load_zones = self.run_load_zones(
            footprint="Interconnect1", load_zone_level="custom"
        )
        self.assertEqual(
            load_zones.values.tolist(),
            [["CustA_CustB", "CustA", "CustB"]],
        )

        capacity = self.run_capacity(
            footprint="Interconnect1", load_zone_level="custom"
        )
        self.assertEqual(capacity.loc["CustA_CustB", "max_mw"], 150)
        self.assertEqual(capacity.loc["CustA_CustB", "min_mw"], -150)

    def test_custom_level_unmapped_ba_links_drop_with_warning(self):
        # Zone3 has no custom zone: every link touching it drops (NULL
        # endpoint guard) and the ready-check warns about the exclusion
        self.set_custom_zones({"Zone1": "CustA", "Zone2": "CustB"})

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            load_zones = self.run_load_zones(
                footprint="Interconnect1", load_zone_level="custom"
            )

        self.assertEqual(
            load_zones.values.tolist(),
            [["CustA_CustB", "CustA", "CustB"]],
        )
        self.assertIn("WARNING", out.getvalue())
        self.assertIn("Zone3", out.getvalue())

    def test_baa_level_interconnect_scope(self):
        # Lines between all in-interconnect BA pairs; the out-of-scope link
        # is excluded
        load_zones = self.run_load_zones(
            footprint="Interconnect1", load_zone_level="baa"
        )
        self.assertEqual(
            load_zones.values.tolist(),
            [
                ["Zone1_Zone2", "Zone1", "Zone2"],
                ["Zone1_Zone3", "Zone1", "Zone3"],
                ["Zone2_Zone3", "Zone2", "Zone3"],
            ],
        )

        capacity = self.run_capacity(footprint="Interconnect1", load_zone_level="baa")
        self.assertEqual(capacity.loc["Zone1_Zone2", "max_mw"], 30)
        self.assertEqual(capacity.loc["Zone1_Zone3", "max_mw"], 120)
        self.assertEqual(capacity.loc["Zone2_Zone3", "max_mw"], 50)
        self.assertEqual(capacity.loc["Zone1_Zone3", "min_mw"], -120)

    def test_baa_level_region_scope(self):
        # Region-value scoping still works: only the intra-Region1 pair
        load_zones = self.run_load_zones(footprint="Region1", load_zone_level="baa")
        self.assertEqual(
            load_zones.values.tolist(), [["Zone1_Zone2", "Zone1", "Zone2"]]
        )

    def test_region_level(self):
        # Parallel BA pairs collapse into one region-pair line, intra-region
        # links are dropped, and the capacity is the max of the HOURLY SUMS
        # (100+50=150), not the sum of the per-pair maxima (120+50=170)
        load_zones = self.run_load_zones(
            footprint="Interconnect1", load_zone_level="region"
        )
        self.assertEqual(
            load_zones.values.tolist(),
            [["Region1_Region2", "Region1", "Region2"]],
        )

        capacity = self.run_capacity(
            footprint="Interconnect1", load_zone_level="region"
        )
        self.assertEqual(capacity.loc["Region1_Region2", "max_mw"], 150)
        self.assertEqual(capacity.loc["Region1_Region2", "min_mw"], -150)

    def test_interconnect_level(self):
        # Region2 spans two interconnects, so scoping by it yields one
        # interconnect-pair line from the Zone3-Zone4 interchange
        load_zones = self.run_load_zones(
            footprint="Region2", load_zone_level="interconnect"
        )
        self.assertEqual(
            load_zones.values.tolist(),
            [["Interconnect1_Interconnect2", "Interconnect1", "Interconnect2"]],
        )

        capacity = self.run_capacity(
            footprint="Region2", load_zone_level="interconnect"
        )
        self.assertEqual(capacity.loc["Interconnect1_Interconnect2", "max_mw"], 80)
        self.assertEqual(capacity.loc["Interconnect1_Interconnect2", "min_mw"], -80)

    def test_interconnect_level_intra_zone_links_dropped(self):
        # All of Interconnect1's internal links are intra-zone at the
        # interconnect level, so no lines result
        load_zones = self.run_load_zones(
            footprint="Interconnect1", load_zone_level="interconnect"
        )
        self.assertTrue(load_zones.empty)

    def test_all_scope_baa_level(self):
        # 'all' includes every mapped BA pair
        load_zones = self.run_load_zones(footprint="all", load_zone_level="baa")
        self.assertEqual(
            load_zones.values.tolist(),
            [
                ["Zone1_Zone2", "Zone1", "Zone2"],
                ["Zone1_Zone3", "Zone1", "Zone3"],
                ["Zone1_ZoneNoIC", "Zone1", "ZoneNoIC"],
                ["Zone1_ZoneOut", "Zone1", "ZoneOut"],
                ["Zone2_Zone3", "Zone2", "Zone3"],
                ["Zone3_Zone4", "Zone3", "Zone4"],
                ["ZoneNoIC_ZoneOut", "ZoneNoIC", "ZoneOut"],
            ],
        )

    def test_all_scope_interconnect_level(self):
        # 'all' with interconnect zones: interconnect-spanning links
        # survive; the no-interconnect BA's links are excluded entirely
        # rather than emitted with a NULL zone
        load_zones = self.run_load_zones(
            footprint="all", load_zone_level="interconnect"
        )
        self.assertEqual(
            load_zones.values.tolist(),
            [
                ["Interconnect1_Interconnect2", "Interconnect1", "Interconnect2"],
                ["Interconnect1_InterconnectX", "Interconnect1", "InterconnectX"],
            ],
        )

        capacity = self.run_capacity(footprint="all", load_zone_level="interconnect")
        self.assertEqual(capacity.loc["Interconnect1_Interconnect2", "max_mw"], 80)
        self.assertEqual(capacity.loc["Interconnect1_Interconnect2", "min_mw"], -80)
        # From Zone1-ZoneOut only: the ZoneNoIC-ZoneOut flows must not be
        # summed into the interconnect pair
        self.assertEqual(capacity.loc["Interconnect1_InterconnectX", "max_mw"], 999)
        self.assertEqual(capacity.loc["Interconnect1_InterconnectX", "min_mw"], -999)

    def test_all_level(self):
        # A single footprint zone has no transmission: at the 'all' level
        # every link is intra-zone, so both steps produce empty CSVs
        load_zones = self.run_load_zones(
            footprint="Interconnect1", load_zone_level="all"
        )
        self.assertTrue(load_zones.empty)

        capacity = self.run_capacity(footprint="Interconnect1", load_zone_level="all")
        self.assertTrue(capacity.empty)

    def test_named_scope_null_zone_column_guard(self):
        # RegionX contains ZoneOut (InterconnectX) and ZoneNoIC (no
        # interconnect): at the interconnect level the no-interconnect BA
        # is dropped rather than producing a NULL zone, leaving no links
        load_zones = self.run_load_zones(
            footprint="RegionX", load_zone_level="interconnect"
        )
        self.assertTrue(load_zones.empty)

        # At the baa level the same scope does yield the BA-pair link
        load_zones = self.run_load_zones(footprint="RegionX", load_zone_level="baa")
        self.assertEqual(
            load_zones.values.tolist(),
            [["ZoneNoIC_ZoneOut", "ZoneNoIC", "ZoneOut"]],
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
