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
from data_toolkit.project.capacity_specified.eia860m_to_project_specified_capacity_input_csvs import (
    main as eia860m_to_project_specified_capacity_input_csvs_main,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "..",
    "data_toolkit",
    "raw_data_db_schema.sql",
)

# Fixture changelog: one row per generator per change, valid from
# report_date until valid_until_date. Mirroring the real changelog's
# convention, generators still present in EIA's files carry their last
# row's valid_until_date at the data's end (2026-08-01 here, the maximum
# report_date); an earlier valid_until_date means the generator VANISHED
# from EIA's monthly files at that point (see unit 18)
# fmt: off
EIA860M_GENERATOR_FIXTURE_ROWS = [
    # (report_date, valid_until_date, plant_id_eia, generator_id,
    #  operational_status_code, balancing_authority_code_eia, capacity_mw,
    #  energy_storage_capacity_mwh, prime_mover_code, energy_source_code_1,
    #  current_planned_generator_operating_date, generator_retirement_date,
    #  planned_generator_retirement_date)
    # Operating gas unit, uprated 100 -> 120 MW in June 2025: only the
    # latest changelog row at the as-of date should count
    ("2024-01-01", "2025-06-01", 1, "1", "OP", "Zone1", 100, None, "CT", "NG", None, None, None),
    ("2025-06-01", "2026-08-01", 1, "1", "OP", "Zone1", 120, None, "CT", "NG", None, None, None),
    # Retired unit: excluded by status
    ("2020-07-01", "2026-08-01", 2, "1", "RE", "Zone1", 300, None, "CT", "NG", None, "2020-06-01", None),
    # Retires during the study year: excluded by the retirement-date window
    ("2024-01-01", "2026-08-01", 3, "1", "OP", "Zone1", 80, None, "CT", "NG", None, "2026-06-15", None),
    # Under construction, comes online after the study year starts: excluded
    ("2025-08-01", "2026-08-01", 4, "1", "U", "Zone1", 500, None, "CT", "NG", "2026-11-01", None, None),
    # Under construction (860M 'V' status, no 'CO' in 860M), online exactly
    # on Jan 1 of the study year: included (the date window is inclusive)
    ("2025-08-01", "2026-08-01", 5, "1", "V", "Zone1", 200, None, "CT", "NG", "2026-01-01", None, None),
    # Wind units: aggregated to the BA level
    ("2024-01-01", "2026-08-01", 6, "W1", "OP", "Zone1", 30, None, "WT", "WND", None, None, None),
    ("2024-01-01", "2026-08-01", 6, "W2", "OP", "Zone1", 50, None, "WT", "WND", None, None, None),
    ("2024-01-01", "2026-08-01", 7, "W1", "OP", "Zone2", 20, None, "WT", "WND", None, None, None),
    # Battery: storage energy capacity carried through
    ("2024-01-01", "2026-08-01", 8, "B1", "OP", "Zone1", 50, 200, "BA", "MWH", None, None, None),
    # Out-of-region BA: excluded
    ("2024-01-01", "2026-08-01", 9, "1", "OP", "ZoneX", 400, None, "CT", "NG", None, None, None),
    # First reported after the explicit as-of date: excluded from that
    # snapshot, but included when the as-of date defaults to the latest
    # report date in the data
    ("2026-08-01", None, 10, "1", "OP", "Zone1", 70, None, "CT", "NG", None, None, None),
    # In a BA with no interconnect in the map (like generation-only BAs):
    # in scope at the 'baa'/'region' levels, excluded at 'interconnect'
    ("2024-01-01", "2026-08-01", 11, "1", "OP", "ZoneNoIC", 60, None, "CT", "NG", None, None, None),
    # In a BA missing from the map entirely: excluded even with --footprint all
    ("2024-01-01", "2026-08-01", 12, "1", "OP", "ZoneUnmapped", 90, None, "CT", "NG", None, None, None),
    # Planned, construction not started ('P'), online by Jan 1 of the
    # study year: only included with planned_inclusion 'all'
    ("2024-01-01", "2026-08-01", 13, "1", "P", "Zone1", 150, None, "CT", "NG", "2026-01-01", None, None),
    # Existing but not operating: standby ('SB'), short-term
    # out-of-service ('OA'), and long-term out-of-service ('OS') — only
    # included at the matching inactive_inclusion levels
    ("2024-01-01", "2026-08-01", 14, "1", "SB", "Zone1", 25, None, "CT", "NG", None, None, None),
    ("2024-01-01", "2026-08-01", 15, "1", "OA", "Zone1", 35, None, "CT", "NG", None, None, None),
    ("2024-01-01", "2026-08-01", 16, "1", "OS", "Zone1", 45, None, "CT", "NG", None, None, None),
    # Behind-the-meter-type unit (industrial CHP sector, set in the UPDATE
    # below): excluded by default, included with include_btm_plants
    ("2024-01-01", "2026-08-01", 17, "1", "OP", "Zone1", 55, None, "CT", "NG", None, None, None),
    # Zombie: last row says operating, but the generator VANISHED from
    # EIA's monthly files in March 2025 without ever filing a retirement
    # (valid_until_date before the data's end) — excluded from snapshots
    # on or after the vanishing date, included in earlier ones
    ("2024-01-01", "2025-03-01", 18, "1", "OP", "Zone1", 65, None, "CT", "NG", None, None, None),
    # Still operating, but with a filed PLANNED retirement date before the
    # end of the study year: excluded by default, kept with
    # include_planned_retirements
    ("2024-01-01", "2026-08-01", 19, "1", "OP", "Zone1", 85, None, "CT", "NG", None, None, "2026-06-01"),
]
# fmt: on

EIA_GRIDPATH_KEY_FIXTURE_ROWS = [
    # (prime_mover_code, energy_source_code, gridpath_capacity_type,
    #  gridpath_operational_type, gridpath_technology, agg_project)
    ("CT", "NG", "gen_spec", "gen_commit_lin", "Gas", None),
    ("WT", "WND", "gen_spec", "gen_var_must_take", "Wind", "Wind"),
    ("BA", "MWH", "stor_spec", "stor", "Batteries", None),
]

BAA_KEY_FIXTURE_ROWS = [
    # (baa, region, interconnect)
    ("Zone1", "Region1", "Interconnect1"),
    ("Zone2", "Region1", "Interconnect1"),
    ("ZoneX", "RegionX", "InterconnectX"),
    ("ZoneNoIC", "RegionX", None),
]


class TestEIA860MToProjectSpecifiedCapacityInputCsvs(unittest.TestCase):
    """
    Test eia860m_to_project_specified_capacity_input_csvs against a small
    fixture changelog.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "eia860m_test_raw.db")

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
            INSERT INTO raw_data_eia860m_generators
            (version_num, report_date, valid_until_date, plant_id_eia,
            generator_id, operational_status_code,
            balancing_authority_code_eia, capacity_mw,
            energy_storage_capacity_mwh, prime_mover_code,
            energy_source_code_1, current_planned_generator_operating_date,
            generator_retirement_date, planned_generator_retirement_date)
            VALUES ('v-test', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        # Generator-type columns (aggregation dimensions), derived from the
        # prime mover to keep the row fixtures compact
        conn.execute("""
            UPDATE raw_data_eia860m_generators
            SET technology_description = CASE prime_mover_code
                    WHEN 'CT' THEN 'Natural Gas Fired Combustion Turbine'
                    WHEN 'WT' THEN 'Onshore Wind Turbine'
                    WHEN 'BA' THEN 'Batteries'
                END,
                fuel_type_code_pudl = CASE prime_mover_code
                    WHEN 'CT' THEN 'gas'
                    WHEN 'WT' THEN 'wind'
                    ELSE 'other'
                END,
                sector_id_eia = CASE plant_id_eia
                    WHEN 17 THEN 7
                    ELSE 1
                END
            """)
        conn.commit()
        conn.close()

    def run_step_and_read_csv(self, scenario_name, extra_args):
        eia860m_to_project_specified_capacity_input_csvs_main(
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
                "2",
                "--project_specified_capacity_scenario_name",
                scenario_name,
                "--quiet",
            ]
            + extra_args
        )

        df = pd.read_csv(os.path.join(self.tmp_dir.name, f"2_{scenario_name}.csv"))

        return df.sort_values("project").set_index("project")

    def assert_capacity(self, df, expected):
        """
        *expected* maps project name to (specified_capacity_mw,
        specified_stor_capacity_mwh); None means the value must be missing.
        """
        self.assertEqual(sorted(df.index.tolist()), sorted(expected.keys()))
        self.assertTrue((df["period"] == 2026).all())
        for project, (capacity_mw, stor_capacity_mwh) in expected.items():
            self.assertEqual(df.loc[project, "specified_capacity_mw"], capacity_mw)
            if stor_capacity_mwh is None:
                self.assertTrue(pd.isna(df.loc[project, "specified_stor_capacity_mwh"]))
            else:
                self.assertEqual(
                    df.loc[project, "specified_stor_capacity_mwh"], stor_capacity_mwh
                )

    def test_disaggregated_with_explicit_as_of_date(self):
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may",
            extra_args=["--eia860m_as_of_date", "2026-05-01"],
        )

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),  # latest changelog row wins (not 100)
                "5__1": (200, None),  # under construction ('V') included
                "8__B1": (50, 200),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
            },
        )

    def test_vanished_generator_excluded_after_vanishing_date(self):
        # Plant 18's last changelog row says operating, but the generator
        # vanished from EIA's monthly files in March 2025 without a
        # retirement record (valid_until_date 2025-03-01): it must appear
        # in snapshots BEFORE the vanishing date (which also picks up
        # plant 1's earlier 100 MW row) and drop from later ones — the
        # explicit-May and default-as-of tests assert its absence there
        df = self.run_step_and_read_csv(
            scenario_name="as_of_jan_2025",
            extra_args=["--eia860m_as_of_date", "2025-01-01"],
        )

        self.assert_capacity(
            df,
            {
                "1__1": (100, None),  # pre-uprate row at this as-of date
                "8__B1": (50, 200),
                "18__1": (65, None),  # still in EIA's files at this date
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
            },
        )

    def test_disaggregated_with_default_as_of_date(self):
        # Without --eia860m_as_of_date, the snapshot is taken at the latest
        # report date in the changelog (2026-08-01) — default settings
        # yield the latest available snapshot, which picks up plant 10
        df = self.run_step_and_read_csv(scenario_name="as_of_latest", extra_args=[])

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),
                "5__1": (200, None),
                "8__B1": (50, 200),
                "10__1": (70, None),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
            },
        )

    def test_default_as_of_date_not_affected_by_eia860_data(self):
        # The default as-of date is the latest CHANGELOG report date even
        # when (older-vintage) EIA860 data is present in the raw database —
        # default settings must yield the latest available snapshot, so
        # plant 10 (first reported 2026-08-01) is included despite the
        # EIA860 vintage being 2026-05-01
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id)
            VALUES ('v-test', '2026-05-01', 1, '1')
            """)
        conn.commit()
        conn.close()

        try:
            df = self.run_step_and_read_csv(
                scenario_name="as_of_latest_with_eia860_data", extra_args=[]
            )
        finally:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM raw_data_eia860_generators")
            conn.commit()
            conn.close()

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),
                "5__1": (200, None),
                "8__B1": (50, 200),
                "10__1": (70, None),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
            },
        )

    def test_disaggregated_include_retired(self):
        # With --include_retired, the 'RE' status is allowed and the
        # retirement-date window is dropped: the long-retired plant 2 and
        # the mid-study-year retiree plant 3 join the portfolio; the
        # not-yet-online plant 4 stays excluded (operating-date window)
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_incl_retired",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--include_retired",
            ],
        )

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),
                "2__1": (300, None),  # retired 2020, allowed by the flag
                "3__1": (80, None),  # retires mid-study, window dropped
                "5__1": (200, None),
                "8__B1": (50, 200),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
            },
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

    def test_planned_retirements_excluded_by_default(self):
        # Unit 19 is operating with a filed planned retirement date before
        # the end of the study year: excluded by default...
        df = self.run_step_and_read_csv(
            scenario_name="default_no_planned_ret", extra_args=[]
        )
        self.assertNotIn("19__1", df.index)

        # ...and kept with include_planned_retirements (everything else
        # unchanged)
        df_incl = self.run_step_and_read_csv(
            scenario_name="incl_planned_ret",
            extra_args=["--include_planned_retirements"],
        )
        self.assertEqual(df_incl.loc["19__1", "specified_capacity_mw"], 85)
        self.assertEqual(
            sorted(df_incl.index.tolist()), sorted(df.index.tolist() + ["19__1"])
        )

    def test_aggregated_custom_load_zone_level(self):
        # Zone1 and Zone2 grouped into one custom zone: the wind
        # aggregate spans both BAs and is named after the custom zone
        self.set_custom_zones({"Zone1": "CustomA", "Zone2": "CustomA"})

        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_custom_agg",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--load_zone_level",
                "custom",
                "--project_aggregation",
                "all",
            ],
        )

        self.assertIn("Wind_CustomA", df.index)
        self.assertEqual(df.loc["Wind_CustomA", "specified_capacity_mw"], 100)

    def test_custom_level_excludes_unmapped_bas_with_warning(self):
        # Zone2 left unmapped: its unit drops out at the custom level,
        # and the ready-check warns about the in-footprint exclusion
        self.set_custom_zones({"Zone1": "CustomA"})

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            df = self.run_step_and_read_csv(
                scenario_name="as_of_may_custom_unmapped",
                extra_args=[
                    "--eia860m_as_of_date",
                    "2026-05-01",
                    "--load_zone_level",
                    "custom",
                ],
            )

        self.assertNotIn("7__W1", df.index)  # Zone2 unit excluded
        self.assertIn("1__1", df.index)
        self.assertIn("WARNING", out.getvalue())
        self.assertIn("Zone2", out.getvalue())

    def test_custom_level_without_custom_zones_raises(self):
        self.set_custom_zones({})
        with self.assertRaises(ValueError):
            self.run_step_and_read_csv(
                scenario_name="as_of_may_custom_unready",
                extra_args=["--load_zone_level", "custom"],
            )

    def test_disaggregated_btm_excluded_by_default(self):
        # Plant 17 (industrial CHP, sector_id_eia 7) is behind-the-meter
        # type: excluded with no extra flags (its output would be netted
        # into EIA-930-derived load, so including it double-counts)
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_btm_default",
            extra_args=["--eia860m_as_of_date", "2026-05-01"],
        )

        self.assertNotIn("17__1", df.index)

    def test_disaggregated_include_btm_plants(self):
        # --include_btm_plants opts the commercial/industrial sectors back
        # in; everything else matches the default fleet
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_incl_btm",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--include_btm_plants",
            ],
        )

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),
                "5__1": (200, None),
                "8__B1": (50, 200),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
                "17__1": (55, None),  # BTM unit allowed by the flag
            },
        )

    def test_disaggregated_planned_inclusion_none(self):
        # With planned_inclusion 'none', only currently operating ('OP')
        # units are kept: the under-construction plant 5 ('V', online by
        # Jan 1 of the study year, included by default) drops out
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_planned_none",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--planned_inclusion",
                "none",
            ],
        )

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),
                "8__B1": (50, 200),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
            },
        )

    def test_disaggregated_planned_inclusion_all(self):
        # With planned_inclusion 'all', the planned-but-not-under-
        # construction plant 13 ('P', excluded by default) joins the
        # fleet alongside the under-construction plant 5
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_planned_all",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--planned_inclusion",
                "all",
            ],
        )

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),
                "5__1": (200, None),
                "13__1": (150, None),
                "8__B1": (50, 200),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
            },
        )

    def test_disaggregated_inactive_inclusion_levels(self):
        # The inactive_inclusion levels are cumulative: 'standby' adds the
        # standby plant 14, 'out_of_service_short_term' also adds the
        # short-term out-of-service plant 15, and 'all' also adds the
        # long-term out-of-service plant 16 (all excluded by default —
        # see the other tests)
        baseline = {
            "1__1": (120, None),
            "5__1": (200, None),
            "8__B1": (50, 200),
            "6__W1": (30, None),
            "6__W2": (50, None),
            "7__W1": (20, None),
        }
        additions_by_level = {
            "standby": {"14__1": (25, None)},
            "out_of_service_short_term": {"14__1": (25, None), "15__1": (35, None)},
            "all": {
                "14__1": (25, None),
                "15__1": (35, None),
                "16__1": (45, None),
            },
        }
        for level, additions in additions_by_level.items():
            df = self.run_step_and_read_csv(
                scenario_name=f"as_of_may_inactive_{level}",
                extra_args=[
                    "--eia860m_as_of_date",
                    "2026-05-01",
                    "--inactive_inclusion",
                    level,
                ],
            )
            self.assert_capacity(df, {**baseline, **additions})

    def test_disaggregated_region_load_zone_level(self):
        # Without aggregation there are no aggregated projects, so
        # load_zone_level does not affect this step's output: identical to
        # the baa-level disaggregated run
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_region_lz",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--load_zone_level",
                "region",
            ],
        )

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),
                "5__1": (200, None),
                "8__B1": (50, 200),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
            },
        )

    def test_aggregated_region_load_zone_level(self):
        # project_aggregation all at region level: everything aggregates to
        # technology_region
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_agg_region_lz",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--project_aggregation",
                "all",
                "--load_zone_level",
                "region",
            ],
        )

        self.assert_capacity(
            df,
            {
                "Gas_Region1": (320, None),  # 120 + 200
                "Batteries_Region1": (50, 200),
                "Wind_Region1": (100, None),
            },
        )

    def test_aggregated_interconnect_load_zone_level(self):
        # project_aggregation all at interconnect level: everything aggregates
        # to technology_interconnect
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_agg_interconnect_lz",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--project_aggregation",
                "all",
                "--load_zone_level",
                "interconnect",
            ],
        )

        self.assert_capacity(
            df,
            {
                "Gas_Interconnect1": (320, None),  # 120 + 200
                "Batteries_Interconnect1": (50, 200),
                "Wind_Interconnect1": (100, None),
            },
        )

    def test_aggregated_all_load_zone_level(self):
        # 'all' + an interconnect footprint filter: everything aggregates
        # into a single zone named after the --footprint value — identical
        # output to what the 'interconnect' level yields for that
        # interconnect (see test_aggregated_interconnect_load_zone_level)
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_agg_all_lz",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--footprint",
                "Interconnect1",
                "--project_aggregation",
                "all",
                "--load_zone_level",
                "all",
            ],
        )

        self.assert_capacity(
            df,
            {
                "Gas_Interconnect1": (320, None),  # 120 + 200
                "Batteries_Interconnect1": (50, 200),
                "Wind_Interconnect1": (100, None),
            },
        )

    def test_all_region_scope(self):
        # 'all' includes every mapped BA's units — the RegionX and
        # no-interconnect BAs join the Region1 fleet — but units in BAs
        # missing from the map (plant 12) are still excluded
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_all_regions",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--footprint",
                "all",
            ],
        )

        self.assert_capacity(
            df,
            {
                "1__1": (120, None),
                "5__1": (200, None),
                "8__B1": (50, 200),
                "6__W1": (30, None),
                "6__W2": (50, None),
                "7__W1": (20, None),
                "9__1": (400, None),
                "11__1": (60, None),
            },
        )

    def test_named_scope_excludes_null_zone_column_bas(self):
        # RegionX at the interconnect level: the no-interconnect BA's unit
        # (plant 11) is excluded — it has no load zone at that level —
        # rather than aggregated into a NULL-named project
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_regionx_interconnect_lz",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--footprint",
                "RegionX",
                "--project_aggregation",
                "all",
                "--load_zone_level",
                "interconnect",
            ],
        )

        self.assert_capacity(df, {"Gas_InterconnectX": (400, None)})

    def test_ba_source_eia930a_vs_eia860(self):
        # Seed an EIA-930A assignment that moves plant 1's generator to the
        # out-of-region ZoneX: under the default (eia930a-preferred)
        # assignment, 1__1 drops out of the Region1 portfolio; with
        # --ba_source eia860, the EIA-860 assignment (Zone1) is used and
        # 1__1 stays. All other units are untouched (not in the 930A
        # table -> EIA-860 fallback).
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO raw_data_eia930a_generators
            (data_year, ba, schedule, plant_id_eia, generator_id)
            VALUES (2024, 'ZoneX', 2, 1, '1')
            """)
        conn.commit()
        conn.close()

        try:
            df_default = self.run_step_and_read_csv(
                scenario_name="as_of_may_930a",
                extra_args=["--eia860m_as_of_date", "2026-05-01"],
            )
            df_860 = self.run_step_and_read_csv(
                scenario_name="as_of_may_860",
                extra_args=[
                    "--eia860m_as_of_date",
                    "2026-05-01",
                    "--ba_source",
                    "eia860",
                ],
            )
        finally:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM raw_data_eia930a_generators")
            conn.commit()
            conn.close()

        expected_without_1__1 = {
            "5__1": (200, None),
            "8__B1": (50, 200),
            "6__W1": (30, None),
            "6__W2": (50, None),
            "7__W1": (20, None),
        }
        self.assert_capacity(df_default, expected_without_1__1)
        self.assert_capacity(df_860, {**expected_without_1__1, "1__1": (120, None)})

    def test_aggregated(self):
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_agg",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--project_aggregation",
                "all",
            ],
        )

        self.assert_capacity(
            df,
            {
                "Gas_Zone1": (320, None),  # 120 + 200
                "Batteries_Zone1": (50, 200),
                "Wind_Zone1": (80, None),
                "Wind_Zone2": (20, None),
            },
        )

    def test_aggregated_agg_project_keyed(self):
        # 'agg_project_keyed' aggregates only the technologies whose key
        # row has agg_project set (Wind); Gas and Batteries units stay
        # disaggregated with their per-unit names and values
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_agg_keyed",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--project_aggregation",
                "agg_project_keyed",
            ],
        )

        self.assert_capacity(
            df,
            {
                "Wind_Zone1": (80, None),  # 30 + 50, aggregated
                "Wind_Zone2": (20, None),
                "1__1": (120, None),  # per-unit, not aggregated
                "5__1": (200, None),
                "8__B1": (50, 200),
            },
        )

    def test_aggregated_with_aggregation_dimensions(self):
        # Dimensions refine the aggregate names in the requested order,
        # between the technology and the load zone. 'duration' only has a
        # value for the battery (4h = 200 MWh / 50 MW) — units without a
        # value get no token, no separator. 'status' splits the operating
        # ('OP') from the under-construction ('V') gas aggregate.
        df = self.run_step_and_read_csv(
            scenario_name="as_of_may_agg_dims",
            extra_args=[
                "--eia860m_as_of_date",
                "2026-05-01",
                "--project_aggregation",
                "all",
                "--aggregation_dimensions",
                "technology_description,duration,status",
            ],
        )

        self.assert_capacity(
            df,
            {
                "Gas_Natural_Gas_Fired_Combustion_Turbine_OP_Zone1": (120, None),
                "Gas_Natural_Gas_Fired_Combustion_Turbine_V_Zone1": (200, None),
                "Batteries_Batteries_4h_OP_Zone1": (50, 200),
                "Wind_Onshore_Wind_Turbine_OP_Zone1": (80, None),
                "Wind_Onshore_Wind_Turbine_OP_Zone2": (20, None),
            },
        )

    def test_dimension_unsupported_by_eia860m_raises(self):
        # The 860M changelog doesn't carry sector_name_eia — asking this
        # step for a dimension needing it must fail loudly, not produce
        # broken names. Every current catalog dimension is carried by both
        # generator tables, so exercise the guard with a synthetic
        # dimension
        from unittest.mock import patch

        from data_toolkit.project.fleet.aggregation import AGGREGATION_DIMENSIONS

        with patch.dict(
            AGGREGATION_DIMENSIONS,
            {"synthetic": {"expr": "sector_name_eia", "columns": ["sector_name_eia"]}},
        ):
            with self.assertRaisesRegex(ValueError, "does not carry"):
                eia860m_to_project_specified_capacity_input_csvs_main(
                    [
                        "--database",
                        self.db_path,
                        "--footprint",
                        "Region1",
                        "--output_directory",
                        self.tmp_dir.name,
                        "--project_aggregation",
                        "all",
                        "--aggregation_dimensions",
                        "synthetic",
                        "--quiet",
                    ]
                )

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
