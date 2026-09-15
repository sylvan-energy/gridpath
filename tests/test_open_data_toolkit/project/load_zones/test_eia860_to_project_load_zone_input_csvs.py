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
from open_data_toolkit.project.load_zones.eia860_to_project_load_zone_input_csvs import (
    main as project_load_zones_main,
)
from open_data_toolkit.project.project_data_filters_common import (
    warn_on_project_load_zones_missing_from_system,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "..",
    "open_data_toolkit",
    "raw_data_db_schema.sql",
)

# Zone1/Zone2 are interchange-observed; Islanded is in the BA map (like
# HECO/GRIS/CEA — region and interconnect NULL) but never in the
# interchange data
BAA_CODES_FIXTURE_ROWS = [
    # (baa, region, interconnect)
    ("Zone1", "Region1", "Interconnect1"),
    ("Zone2", "Region1", "Interconnect1"),
    ("Islanded", None, None),
]

INTERCHANGE_FIXTURE_ROWS = [
    # (from, to, datetime_pst_he)
    ("Zone1", "Zone2", "2024-06-01 10:00:00"),
    ("Zone2", "Zone1", "2024-06-01 10:00:00"),
]

EIA860_GENERATOR_FIXTURE_ROWS = [
    # (version_num, report_date, plant_id_eia, generator_id,
    #  operational_status_code, balancing_authority_code_eia, capacity_mw,
    #  prime_mover_code, energy_source_code_1,
    #  current_planned_generator_operating_date)
    ("v-test", "2024-01-01", 1, "1", "OP", "Zone1", 100, "CT", "NG", None),
    ("v-test", "2024-01-01", 2, "1", "OP", "Islanded", 50, "CT", "NG", None),
    # Under construction (older-vintage 'CO' code, kept in the
    # under-construction tier), online exactly on Jan 1 of the study year:
    # included (the date window is inclusive) at the default
    # planned_inclusion level
    ("v-test", "2024-01-01", 3, "1", "CO", "Zone2", 70, "CT", "NG", "2026-01-01"),
    # Planned, construction not started, online by Jan 1 of the study
    # year: only included with planned_inclusion 'all'
    ("v-test", "2024-01-01", 4, "1", "P", "Zone2", 40, "CT", "NG", "2026-01-01"),
]

EIA_GRIDPATH_KEY_FIXTURE_ROWS = [
    ("CT", "NG", "gen_spec", "gen_commit_lin", "Gas", None),
]


class TestEIA860ToProjectLoadZoneInputCsvs(unittest.TestCase):
    """
    Test the project load-zone step and its cross-check warning for
    project zones missing from the interchange-derived system zones.
    """

    @classmethod
    def make_db(cls, db_path, with_interchange):
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        conn = sqlite3.connect(db_path)
        conn.executemany(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES (?, ?, ?)",
            BAA_CODES_FIXTURE_ROWS,
        )
        if with_interchange:
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
            """
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            operational_status_code, balancing_authority_code_eia,
            capacity_mw, prime_mover_code, energy_source_code_1,
            current_planned_generator_operating_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            EIA860_GENERATOR_FIXTURE_ROWS,
        )
        # Give one unit a far-future planned retirement date so the
        # default planned-retirement exclusion neither drops units nor
        # warns about an entirely-empty column
        conn.execute("""UPDATE raw_data_eia860_generators
            SET planned_generator_retirement_date = '2099-01-01'
            WHERE plant_id_eia = 1""")
        # Give every fixture unit a (non-behind-the-meter) sector so the
        # default BTM exclusion neither drops units nor warns about
        # unclassifiable NULL-sector rows
        conn.execute(
            "UPDATE raw_data_eia860_generators "
            "SET sector_name_eia = 'Electric Utility'"
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
        conn.commit()
        conn.close()

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "lz_test_raw.db")
        cls.make_db(cls.db_path, with_interchange=True)
        cls.no_interchange_db_path = os.path.join(
            cls.tmp_dir.name, "lz_test_raw_no_interchange.db"
        )
        cls.make_db(cls.no_interchange_db_path, with_interchange=False)

    def run_step(self, footprint, db_path=None, extra_args=None):
        output_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            project_load_zones_main(
                [
                    "--database",
                    db_path if db_path is not None else self.db_path,
                    "--study_year",
                    "2026",
                    "--footprint",
                    footprint,
                    "--output_directory",
                    output_directory,
                    "--project_load_zone_scenario_id",
                    "1",
                    "--project_load_zone_scenario_name",
                    "test",
                    "--quiet",
                ]
                + (extra_args if extra_args is not None else [])
            )

        df = pd.read_csv(os.path.join(output_directory, "1_test.csv"))

        return df.sort_values("project"), out.getvalue()

    def test_named_footprint_no_warning(self):
        df, output = self.run_step(footprint="Region1")

        self.assertEqual(df["project"].tolist(), ["1__1", "3__1"])
        self.assertEqual(df["load_zone"].tolist(), ["Zone1", "Zone2"])
        self.assertNotIn("WARNING", output)

    def test_planned_inclusion_none(self):
        # With planned_inclusion 'none', the under-construction unit
        # (plant 3, 'CO' status, online before the study year and included
        # by default) drops out
        df, output = self.run_step(
            footprint="Region1", extra_args=["--planned_inclusion", "none"]
        )

        self.assertEqual(df["project"].tolist(), ["1__1"])
        self.assertEqual(df["load_zone"].tolist(), ["Zone1"])
        self.assertNotIn("WARNING", output)

    def test_planned_inclusion_all(self):
        # With planned_inclusion 'all', the planned-but-not-under-
        # construction unit (plant 4, 'P' status, excluded by default)
        # joins the under-construction plant 3
        df, output = self.run_step(
            footprint="Region1", extra_args=["--planned_inclusion", "all"]
        )

        self.assertEqual(df["project"].tolist(), ["1__1", "3__1", "4__1"])
        self.assertEqual(df["load_zone"].tolist(), ["Zone1", "Zone2", "Zone2"])
        self.assertNotIn("WARNING", output)

    def test_all_footprint_warns_on_islanded_zone(self):
        # With --footprint all at the baa level, the islanded BA's project
        # gets a zone the system load-zone step would never create — the
        # step must warn (despite --quiet)
        df, output = self.run_step(footprint="all")

        self.assertEqual(df["project"].tolist(), ["1__1", "2__1", "3__1"])
        self.assertEqual(df["load_zone"].tolist(), ["Zone1", "Islanded", "Zone2"])
        self.assertIn("WARNING", output)
        self.assertIn("Islanded", output)
        self.assertNotIn("Zone1,", output)

    def test_check_skipped_without_interchange_data(self):
        df, output = self.run_step(footprint="all", db_path=self.no_interchange_db_path)

        self.assertEqual(df["load_zone"].tolist(), ["Zone1", "Islanded", "Zone2"])
        self.assertNotIn("WARNING", output)

    def test_warn_helper_directly(self):
        conn = sqlite3.connect(self.db_path)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            missing = warn_on_project_load_zones_missing_from_system(
                conn=conn,
                footprint="all",
                load_zone_level="baa",
                project_load_zones=["Zone1", "Islanded"],
                quiet=True,
            )
        self.assertEqual(missing, ["Islanded"])
        self.assertIn("WARNING", out.getvalue())

        # All zones covered: no warning
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            missing = warn_on_project_load_zones_missing_from_system(
                conn=conn,
                footprint="Region1",
                load_zone_level="baa",
                project_load_zones=["Zone1"],
                quiet=True,
            )
        self.assertEqual(missing, [])
        self.assertEqual(out.getvalue(), "")

        # At the 'all' level the single footprint zone always exists as
        # long as any in-scope BA is interchange-observed
        missing = warn_on_project_load_zones_missing_from_system(
            conn=conn,
            footprint="Interconnect1",
            load_zone_level="all",
            project_load_zones=["Interconnect1"],
            quiet=True,
        )
        self.assertEqual(missing, [])

        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
