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
The per-unit default-storage-duration fill
(open_data_toolkit.project.fleet.storage_durations), exercised through the two
specified-capacity steps and the fleet audit's energy_mwh_source column.
The central case is an aggregated battery project whose units are partly
rated: the fill must add duration × capacity_mw for the UNRATED units
only, never touching rated ones — a reported zero included.
"""

import contextlib
import io
import os
import sqlite3
import tempfile
import unittest

import pandas as pd

from db.create_database import main as create_database_main
from open_data_toolkit.project.capacity_specified.eia860_to_project_specified_capacity_input_csvs import (
    main as eia860_capacity_main,
)
from open_data_toolkit.project.capacity_specified.eia860m_to_project_specified_capacity_input_csvs import (
    main as eia860m_capacity_main,
)
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

# One aggregated battery project of three units — rated, rated at zero,
# and unrated — plus a fully-unrated battery project in another zone, a
# pumped-storage unit, and a non-storage control unit
# fmt: off
EIA860_GENERATOR_FIXTURE_ROWS = [
    # (plant_id_eia, generator_id, operational_status_code,
    #  balancing_authority_code_eia, capacity_mw,
    #  energy_storage_capacity_mwh, prime_mover_code, energy_source_code_1)
    (20, "B1", "OP", "Zone1", 100, 400, "BA", "MWH"),
    # A reported zero is a rating, not a gap: never filled
    (20, "B2", "OP", "Zone1", 50, 0, "BA", "MWH"),
    (20, "B3", "OP", "Zone1", 200, None, "BA", "MWH"),
    # Fully-unrated project: NULL without the fill, 320 MWh at 4 h
    (21, "B1", "OP", "Zone2", 80, None, "BA", "MWH"),
    # Pumped storage: only filled by its own setting
    (22, "P1", "OP", "Zone1", 60, None, "PS", "WAT"),
    # Non-storage unit: specified_stor_capacity_mwh stays NULL regardless
    (23, "G1", "OP", "Zone1", 90, None, "CT", "NG"),
]
# fmt: on

# The EIA860M changelog mirror of the fill (the step shares the
# expression builder; this pins the wiring): one unrated and one rated
# battery, current through the data's end
# fmt: off
EIA860M_GENERATOR_FIXTURE_ROWS = [
    # (report_date, valid_until_date, plant_id_eia, generator_id,
    #  operational_status_code, balancing_authority_code_eia, capacity_mw,
    #  energy_storage_capacity_mwh, prime_mover_code, energy_source_code_1)
    ("2024-01-01", "2026-08-01", 30, "B1", "OP", "Zone1", 100, None, "BA", "MWH"),
    ("2024-01-01", "2026-08-01", 31, "B2", "OP", "Zone1", 50, 200, "BA", "MWH"),
]
# fmt: on

EIA_GRIDPATH_KEY_FIXTURE_ROWS = [
    ("BA", "MWH", "stor_spec", "stor", "Batteries", "Batteries"),
    ("PS", "WAT", "stor_spec", "stor", "Pumped_Storage", "Pumped_Storage"),
    ("CT", "NG", "gen_spec", "gen_commit_lin", "Gas", None),
]

BAA_KEY_FIXTURE_ROWS = [
    ("Zone1", "Region1", "Interconnect1"),
    ("Zone2", "Region1", "Interconnect1"),
]


class TestDefaultStorageDurations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "storage_durations_test_raw.db")

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
            capacity_mw, energy_storage_capacity_mwh, prime_mover_code,
            energy_source_code_1)
            VALUES ('v-test', '2026-01-01', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            EIA860_GENERATOR_FIXTURE_ROWS,
        )
        conn.executemany(
            """
            INSERT INTO raw_data_eia860m_generators
            (version_num, report_date, valid_until_date, plant_id_eia,
            generator_id, operational_status_code,
            balancing_authority_code_eia, capacity_mw,
            energy_storage_capacity_mwh, prime_mover_code,
            energy_source_code_1)
            VALUES ('v-test', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            EIA860M_GENERATOR_FIXTURE_ROWS,
        )
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
        # One far-future planned retirement date and one inert solar row
        # so the missing-data warnings (empty planned-retirement column,
        # empty net-metering table) stay quiet
        conn.execute("""
            UPDATE raw_data_eia860_generators
            SET planned_generator_retirement_date = '2099-01-01'
            WHERE plant_id_eia = 23
            """)
        conn.execute("""
            UPDATE raw_data_eia860m_generators
            SET planned_generator_retirement_date = '2099-01-01'
            WHERE plant_id_eia = 31
            """)
        conn.execute("""
            INSERT INTO raw_data_eia860_solar
            (version_num, report_date, plant_id_eia, generator_id,
            uses_net_metering_agreement)
            VALUES ('v-test', '2025-01-01', 999999, 'NM0', 0)
            """)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def run_capacity_step_and_read_csv(self, step_main, scenario_name, extra_args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            step_main(
                [
                    "--database",
                    self.db_path,
                    "--study_year",
                    "2026",
                    "--footprint",
                    "Region1",
                    "--output_directory",
                    self.tmp_dir.name,
                    "--project_specified_capacity_scenario_id",
                    "1",
                    "--project_specified_capacity_scenario_name",
                    scenario_name,
                    "--quiet",
                ]
                + extra_args
            )

        df = pd.read_csv(os.path.join(self.tmp_dir.name, f"1_{scenario_name}.csv"))

        return df.set_index("project"), output.getvalue()

    def assert_stor_mwh(self, df, expected):
        """
        *expected* maps project name to (specified_capacity_mw,
        specified_stor_capacity_mwh); None means the value must be missing.
        """
        self.assertEqual(sorted(df.index.tolist()), sorted(expected.keys()))
        for project, (capacity_mw, stor_capacity_mwh) in expected.items():
            self.assertEqual(df.loc[project, "specified_capacity_mw"], capacity_mw)
            if stor_capacity_mwh is None:
                self.assertTrue(pd.isna(df.loc[project, "specified_stor_capacity_mwh"]))
            else:
                self.assertEqual(
                    df.loc[project, "specified_stor_capacity_mwh"], stor_capacity_mwh
                )

    def test_aggregated_no_fill_by_default(self):
        # Today's behavior with the settings unset: the partially-rated
        # project sums only its rated units (understated), the
        # fully-unrated one is NULL
        df, output = self.run_capacity_step_and_read_csv(
            eia860_capacity_main,
            scenario_name="agg_no_fill",
            extra_args=["--project_aggregation", "all"],
        )

        self.assert_stor_mwh(
            df,
            {
                "Batteries_Zone1": (350, 400),  # 400 + 0; 200 MW unrated
                "Batteries_Zone2": (80, None),
                "Pumped_Storage_Zone1": (60, None),
                "Gas_Zone1": (90, None),
            },
        )
        self.assertNotIn("Default storage durations", output)

    def test_aggregated_battery_fill(self):
        # The report's central case: per-unit 4 h fill for the unrated
        # units only — 400 (rated) + 0 (rated at zero) + 4 × 200 = 1,200
        # for the partially-rated project, 4 × 80 = 320 for the
        # fully-unrated one; pumped storage untouched by the battery
        # setting
        df, output = self.run_capacity_step_and_read_csv(
            eia860_capacity_main,
            scenario_name="agg_ba_fill",
            extra_args=[
                "--project_aggregation",
                "all",
                "--default_battery_duration_hours",
                "4",
            ],
        )

        self.assert_stor_mwh(
            df,
            {
                "Batteries_Zone1": (350, 1200),
                "Batteries_Zone2": (80, 320),
                "Pumped_Storage_Zone1": (60, None),
                "Gas_Zone1": (90, None),
            },
        )

        # The fill is reported loudly (the step ran with --quiet), and the
        # mostly-assumption warning names both projects with over half
        # their storage MW unrated (Zone1: 200 of 350; Zone2: all of it)
        self.assertIn(
            "Default storage durations filled 2 unrated units (280 MW) "
            "in 2 projects: 1120 MWh added.",
            output,
        )
        self.assertIn("WARNING", output)
        self.assertIn("Batteries_Zone1 (57%)", output)
        self.assertIn("Batteries_Zone2 (100%)", output)

    def test_aggregated_battery_and_pumped_storage_fill(self):
        df, output = self.run_capacity_step_and_read_csv(
            eia860_capacity_main,
            scenario_name="agg_ba_ps_fill",
            extra_args=[
                "--project_aggregation",
                "all",
                "--default_battery_duration_hours",
                "4",
                "--default_pumped_storage_duration_hours",
                "12",
            ],
        )

        self.assert_stor_mwh(
            df,
            {
                "Batteries_Zone1": (350, 1200),
                "Batteries_Zone2": (80, 320),
                "Pumped_Storage_Zone1": (60, 720),
                "Gas_Zone1": (90, None),
            },
        )
        self.assertIn(
            "Default storage durations filled 3 unrated units (340 MW) "
            "in 3 projects: 1840 MWh added.",
            output,
        )

    def test_disaggregated_fill(self):
        # Per-unit projects: only the unrated units change
        df, output = self.run_capacity_step_and_read_csv(
            eia860_capacity_main,
            scenario_name="disagg_ba_fill",
            extra_args=["--default_battery_duration_hours", "4"],
        )

        self.assert_stor_mwh(
            df,
            {
                "20__B1": (100, 400),
                "20__B2": (50, 0),
                "20__B3": (200, 800),
                "21__B1": (80, 320),
                "22__P1": (60, None),
                "23__G1": (90, None),
            },
        )

    def test_eia860m_step_fill(self):
        df, output = self.run_capacity_step_and_read_csv(
            eia860m_capacity_main,
            scenario_name="eia860m_ba_fill",
            extra_args=["--default_battery_duration_hours", "4"],
        )

        self.assert_stor_mwh(
            df,
            {
                "30__B1": (100, 400),  # unrated, filled at 4 h
                "31__B2": (50, 200),  # rated, untouched
            },
        )
        self.assertIn(
            "Default storage durations filled 1 unrated units (100 MW) "
            "in 1 projects: 400 MWh added.",
            output,
        )

    def test_invalid_duration_raises_before_database_work(self):
        for bad_value in ("0", "-2", "four"):
            with self.subTest(bad_value=bad_value):
                with self.assertRaises(ValueError):
                    eia860_capacity_main(
                        [
                            "--database",
                            os.path.join(self.tmp_dir.name, "nonexistent.db"),
                            "--footprint",
                            "Region1",
                            "--output_directory",
                            self.tmp_dir.name,
                            "--default_battery_duration_hours",
                            bad_value,
                            "--quiet",
                        ]
                    )

    def run_audit_and_read_csv(self, extra_args):
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
                    "--quiet",
                ]
                + extra_args
            )

        audit_df = pd.read_csv(
            os.path.join(self.tmp_dir.name, "fleet_audit.csv"),
            dtype={"generator_id": str},
        ).set_index(["plant_id_eia", "generator_id"])

        # The audit's cross-check against the fleet relation must have
        # passed silently
        self.assertNotIn("WARNING", output.getvalue())

        return audit_df

    def test_fleet_audit_energy_mwh_source(self):
        # Without duration settings, unrated storage units are 'missing';
        # rated ones (a zero included) are 'filed'; non-storage units get
        # no label
        audit_df = self.run_audit_and_read_csv(extra_args=[])
        self.assertEqual(audit_df.loc[(20, "B1"), "energy_mwh_source"], "filed")
        self.assertEqual(audit_df.loc[(20, "B2"), "energy_mwh_source"], "filed")
        self.assertEqual(audit_df.loc[(20, "B3"), "energy_mwh_source"], "missing")
        self.assertEqual(audit_df.loc[(21, "B1"), "energy_mwh_source"], "missing")
        self.assertEqual(audit_df.loc[(22, "P1"), "energy_mwh_source"], "missing")
        self.assertTrue(pd.isna(audit_df.loc[(23, "G1"), "energy_mwh_source"]))
        self.assertEqual(audit_df.loc[(20, "B1"), "energy_storage_capacity_mwh"], 400)

        # With the battery setting, unrated batteries become
        # 'default_duration'; pumped storage stays 'missing' (no PS
        # setting given)
        audit_df = self.run_audit_and_read_csv(
            extra_args=["--default_battery_duration_hours", "4"]
        )
        self.assertEqual(audit_df.loc[(20, "B1"), "energy_mwh_source"], "filed")
        self.assertEqual(
            audit_df.loc[(20, "B3"), "energy_mwh_source"], "default_duration"
        )
        self.assertEqual(
            audit_df.loc[(21, "B1"), "energy_mwh_source"], "default_duration"
        )
        self.assertEqual(audit_df.loc[(22, "P1"), "energy_mwh_source"], "missing")


if __name__ == "__main__":
    unittest.main()
