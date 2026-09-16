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
from open_data_toolkit.project.fleet.fleet_audit import main as fleet_audit_main

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "..",
    "open_data_toolkit",
    "raw_data_db_schema.sql",
)

# One unit per selection outcome the audit must flag
# fmt: off
EIA860_GENERATOR_FIXTURE_ROWS = [
    # (plant_id_eia, generator_id, operational_status_code,
    #  balancing_authority_code_eia, capacity_mw, prime_mover_code,
    #  energy_source_code_1, current_planned_generator_operating_date,
    #  generator_retirement_date)
    # In fleet: operating, in footprint, keyed
    (1, "1", "OP", "Zone1", 100, "CT", "NG", None, None),
    # No user_defined_eia_gridpath_key row for this PM/fuel
    (2, "1", "OP", "Zone1", 50, "XX", "NG", None, None),
    # Out-of-footprint BA
    (3, "1", "OP", "ZoneX", 200, "CT", "NG", None, None),
    # Retired
    (4, "1", "RE", "Zone1", 300, "CT", "NG", None, "2020-06-01"),
    # Under construction, online after Jan 1 of the study year
    (5, "1", "U", "Zone1", 400, "CT", "NG", "2026-11-01", None),
    # Behind-the-meter sector (set in the UPDATE below)
    (6, "1", "OP", "Zone1", 25, "CT", "NG", None, None),
    # EIA-860 says out-of-footprint, EIA-930A reassigns into Zone1
    (7, "1", "OP", "ZoneX", 75, "CT", "NG", None, None),
    # EIA-860 says out-of-footprint, manual override pins to Zone1
    (8, "1", "OP", "ZoneX", 60, "CT", "NG", None, None),
]
# fmt: on

EIA_GRIDPATH_KEY_FIXTURE_ROWS = [
    ("CT", "NG", "gen_spec", "gen_commit_lin", "Gas", None),
]

BAA_KEY_FIXTURE_ROWS = [
    ("Zone1", "Region1", "Interconnect1"),
    ("ZoneX", "RegionX", "InterconnectX"),
]


class TestFleetAudit(unittest.TestCase):
    """
    Test the fleet audit's per-unit flags, BA-resolution columns,
    waterfall, and its cross-check against the fleet relation, on a
    fixture with one unit per selection outcome.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "fleet_audit_test_raw.db")

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
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            operational_status_code, balancing_authority_code_eia,
            capacity_mw, prime_mover_code, energy_source_code_1,
            current_planned_generator_operating_date,
            generator_retirement_date)
            VALUES ('v-test', '2026-01-01', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            EIA860_GENERATOR_FIXTURE_ROWS,
        )
        # Give one unit a far-future planned retirement date so the
        # default planned-retirement exclusion neither drops units nor
        # warns about an entirely-empty column
        conn.execute("""UPDATE raw_data_eia860_generators
            SET planned_generator_retirement_date = '2099-01-01'
            WHERE plant_id_eia = 1""")
        conn.executemany(
            """
            INSERT INTO user_defined_eia_gridpath_key
            (prime_mover_code, energy_source_code, gridpath_capacity_type,
            gridpath_operational_type, gridpath_technology, agg_project)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            EIA_GRIDPATH_KEY_FIXTURE_ROWS,
        )
        conn.executemany(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES (?, ?, ?)",
            BAA_KEY_FIXTURE_ROWS,
        )
        conn.execute("""
            INSERT INTO raw_data_eia930a_generators
            (data_year, ba, schedule, plant_id_eia, generator_id)
            VALUES (2024, 'Zone1', 2, 7, '1')
            """)
        conn.execute("""
            INSERT INTO user_defined_baa_overrides
            (plant_id_eia, generator_id, balancing_authority_code_eia, reason)
            VALUES (8, '1', 'Zone1', 'test override')
            """)
        # One inert solar row (flag 0) so the empty-solar-table warning
        # (net-metered exclusion silently doing nothing) stays quiet
        conn.execute("""
            INSERT INTO raw_data_eia860_solar
            (version_num, report_date, plant_id_eia, generator_id,
            uses_net_metering_agreement)
            VALUES ('v-test', '2025-01-01', 999999, 'NM0', 0)
            """)
        # Sectors: unit 6 is behind-the-meter, the rest utility
        conn.execute("""
            UPDATE raw_data_eia860_generators
            SET sector_name_eia = CASE plant_id_eia
                    WHEN 6 THEN 'Industrial CHP'
                    ELSE 'Electric Utility'
                END
            """)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def run_audit(self, extra_args=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            fleet_audit_main(
                [
                    "--database",
                    self.db_path,
                    "--study_year",
                    "2026",
                    "--footprint",
                    "Region1",
                    "--output_directory",
                    self.tmp_dir.name,
                ]
                + (extra_args if extra_args else [])
            )

        audit_df = pd.read_csv(
            os.path.join(self.tmp_dir.name, "fleet_audit.csv"),
            dtype={"generator_id": str},
        ).set_index("plant_id_eia")

        return audit_df, output.getvalue()

    def test_fleet_audit(self):
        audit_df, output = self.run_audit()

        # Every raw unit appears, in fleet or not
        self.assertEqual(len(audit_df), 8)

        # Per-stage flags: (has_key, in_footprint, date, status, btm, in_fleet)
        expected_flags = {
            1: (1, 1, 1, 1, 1, 1),
            2: (0, 1, 1, 1, 1, 0),  # no gridpath key row
            3: (1, 0, 1, 1, 1, 0),  # out of footprint
            4: (1, 1, 1, 0, 1, 0),  # retired
            5: (1, 1, 0, 1, 1, 0),  # online after Jan 1 of study year
            6: (1, 1, 1, 1, 1, 1),  # BTM sector — kept by default
            7: (1, 1, 1, 1, 1, 1),  # in footprint via the EIA-930A BA
            8: (1, 1, 1, 1, 1, 1),  # in footprint via the manual override
        }
        flag_columns = [
            "has_gridpath_key",
            "in_footprint",
            "passes_date_window",
            "passes_status_retirement",
            "passes_commercial_industrial_exclusion",
            "in_fleet",
        ]
        for plant, expected in expected_flags.items():
            self.assertEqual(
                tuple(audit_df.loc[plant, flag_columns]),
                expected,
                msg=f"plant {plant}",
            )

        # BA resolution columns show each source and the resolved value
        self.assertEqual(audit_df.loc[7, "eia860_ba"], "ZoneX")
        self.assertEqual(audit_df.loc[7, "eia930a_bas"], "Zone1")
        self.assertEqual(audit_df.loc[7, "resolved_ba"], "Zone1")
        self.assertEqual(audit_df.loc[8, "eia860_ba"], "ZoneX")
        self.assertEqual(audit_df.loc[8, "override_ba"], "Zone1")
        self.assertEqual(audit_df.loc[8, "resolved_ba"], "Zone1")
        self.assertEqual(audit_df.loc[1, "load_zone"], "Zone1")
        # Out-of-footprint unit has no load zone
        self.assertTrue(pd.isna(audit_df.loc[3, "load_zone"]))

        # Project names only for in-fleet units
        self.assertEqual(audit_df.loc[1, "project"], "1__1")
        self.assertTrue(pd.isna(audit_df.loc[4, "project"]))

        # Waterfall counts (units passing this AND previous stages)
        self.assertIn("EIA-860 units in the raw data", output)
        self.assertIn("8 units", output)  # raw
        self.assertIn("IN FLEET", output)
        self.assertIn("4 units", output)  # in fleet
        self.assertIn("4 projects", output)

        # The cross-check against the real fleet relation passed silently
        self.assertNotIn("WARNING", output)

    def test_fleet_audit_eia860_ba_source(self):
        # With ba_source eia860, the 930A reassignment does not apply
        # (unit 7 stays out of footprint) but the override still does
        audit_df, output = self.run_audit(extra_args=["--ba_source", "eia860"])

        self.assertEqual(audit_df.loc[7, "resolved_ba"], "ZoneX")
        self.assertEqual(audit_df.loc[7, "in_fleet"], 0)
        self.assertEqual(audit_df.loc[8, "resolved_ba"], "Zone1")
        self.assertEqual(audit_df.loc[8, "in_fleet"], 1)
        self.assertNotIn("WARNING", output)

    def test_fleet_audit_exclude_commercial_industrial_and_include_retired(self):
        audit_df, output = self.run_audit(
            extra_args=["--exclude_commercial_industrial_sectors", "--include_retired"]
        )

        self.assertEqual(audit_df.loc[6, "passes_commercial_industrial_exclusion"], 0)
        self.assertEqual(audit_df.loc[6, "in_fleet"], 0)
        self.assertEqual(audit_df.loc[4, "passes_status_retirement"], 1)
        self.assertEqual(audit_df.loc[4, "in_fleet"], 1)
        self.assertNotIn("WARNING", output)

    def test_fleet_audit_aggregated_project_names(self):
        audit_df, output = self.run_audit(extra_args=["--project_aggregation", "all"])

        self.assertEqual(audit_df.loc[1, "project"], "Gas_Zone1")
        self.assertEqual(audit_df.loc[7, "project"], "Gas_Zone1")
        self.assertIn("1 projects", output)
        self.assertNotIn("WARNING", output)


if __name__ == "__main__":
    unittest.main()
