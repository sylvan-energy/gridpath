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
from open_data_toolkit.project.availability.eia860_to_project_availability_input_csvs import (
    main as availability_main,
    parse_month_list,
    get_seasonal_months,
    get_seasonal_derate_op_type_filter_string,
    write_monthly_derate_csvs,
    warn_on_missing_seasonal_rating_data,
    DEFAULT_SEASONAL_DERATE_EXCLUDED_OP_TYPES,
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

# One unit per seasonal-derate outcome
# fmt: off
EIA860_GENERATOR_FIXTURE_ROWS = [
    # (plant_id_eia, generator_id, operational_status_code,
    #  balancing_authority_code_eia, capacity_mw, summer_capacity_mw,
    #  winter_capacity_mw, prime_mover_code, energy_source_code_1)
    # Thermal with both seasonal ratings; winter ABOVE nameplate (kept)
    (1, "1", "OP", "Zone1", 100, 90, 105, "CT", "NG"),
    # Thermal with no seasonal ratings: falls back to nameplate (no file
    # on its own, contributes at nameplate to the aggregated derate)
    (1, "2", "OP", "Zone1", 100, None, None, "CT", "NG"),
    # Thermal whose seasonal ratings equal nameplate: no file
    (2, "1", "OP", "Zone1", 50, 50, 50, "CT", "NG"),
    # Variable generator: excluded operational type, no derate despite
    # a summer rating below nameplate
    (3, "W1", "OP", "Zone1", 30, 20, 25, "WT", "WND"),
    # Storage: excluded operational type
    (4, "B1", "OP", "Zone1", 60, 55, 58, "BA", "MWH"),
    # Hyphenated generator id: the disaggregated project-name expression
    # sanitizes it (5__1_1); summer rating only, winter falls back to
    # nameplate so only summer months get rows
    (5, "1-1", "OP", "Zone1", 40, 30, None, "CT", "NG"),
]
# fmt: on

EIA_GRIDPATH_KEY_FIXTURE_ROWS = [
    # (prime_mover_code, energy_source_code, gridpath_capacity_type,
    #  gridpath_operational_type, gridpath_technology, agg_project)
    ("CT", "NG", "gen_spec", "gen_commit_lin", "Gas", "Gas"),
    ("WT", "WND", "gen_spec", "gen_var", "Wind", "Wind"),
    ("BA", "MWH", "stor_spec", "stor", "Batteries", "Batteries"),
]


def read_availability_csv(output_dir):
    return pd.read_csv(
        os.path.join(output_dir, "1_no_derates.csv"),
        dtype=str,
        keep_default_na=False,
    )


def read_monthly_csv(output_dir, filename):
    return pd.read_csv(os.path.join(output_dir, "exogenous_monthly", filename))


class TestSeasonalCapacityDerates(unittest.TestCase):
    """
    Test the availability step's seasonal-capacity-derate mode on a
    fixture with one unit per outcome: both/one/no seasonal ratings,
    ratings equal to nameplate, excluded operational types, a hyphenated
    generator id, and the capacity-weighted aggregated derate.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "availability_test_raw.db")

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
            capacity_mw, summer_capacity_mw, winter_capacity_mw,
            prime_mover_code, energy_source_code_1)
            VALUES ('v-test', '2026-01-01', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            EIA860_GENERATOR_FIXTURE_ROWS,
        )
        # Keep the fleet data-gap warnings quiet: a far-future planned
        # retirement date, utility sectors, and an inert solar row
        conn.execute("""UPDATE raw_data_eia860_generators
            SET planned_generator_retirement_date = '2099-01-01'
            WHERE plant_id_eia = 1 AND generator_id = '1'""")
        conn.execute("""UPDATE raw_data_eia860_generators
            SET sector_name_eia = 'Electric Utility'""")
        conn.execute("""
            INSERT INTO raw_data_eia860_solar
            (version_num, report_date, plant_id_eia, generator_id,
            uses_net_metering_agreement)
            VALUES ('v-test', '2026-01-01', 999999, 'NM0', 0)
            """)
        conn.executemany(
            """
            INSERT INTO user_defined_eia_gridpath_key
            (prime_mover_code, energy_source_code, gridpath_capacity_type,
            gridpath_operational_type, gridpath_technology, agg_project)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            EIA_GRIDPATH_KEY_FIXTURE_ROWS,
        )
        conn.execute(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES ('Zone1', 'Region1', 'Interconnect1')"
        )
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def run_step(self, extra_args=None):
        output_dir = tempfile.TemporaryDirectory()
        self.addCleanup(output_dir.cleanup)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            availability_main(
                [
                    "--database",
                    self.db_path,
                    "--study_year",
                    "2026",
                    "--footprint",
                    "Region1",
                    "--output_directory",
                    output_dir.name,
                    "--quiet",
                ]
                + (extra_args if extra_args else [])
            )
        return output_dir.name, stdout.getvalue()

    def test_off_by_default(self):
        output_dir, stdout = self.run_step()
        self.assertNotIn("WARNING", stdout)
        # No monthly derate directory, and the monthly scenario id column
        # is entirely empty — current behavior untouched
        self.assertFalse(os.path.exists(os.path.join(output_dir, "exogenous_monthly")))
        df = read_availability_csv(output_dir)
        self.assertTrue((df["exogenous_availability_monthly_scenario_id"] == "").all())

    def test_seasonal_derates_disaggregated(self):
        output_dir, stdout = self.run_step(["--seasonal_capacity_derates"])
        self.assertNotIn("WARNING", stdout)

        # Only the two units with a seasonal rating different from
        # nameplate get a file; the hyphenated generator id is sanitized
        self.assertEqual(
            sorted(os.listdir(os.path.join(output_dir, "exogenous_monthly"))),
            [
                "1__1-1-summer_winter_ratings.csv",
                "5__1_1-1-summer_winter_ratings.csv",
            ],
        )

        both_seasons = read_monthly_csv(output_dir, "1__1-1-summer_winter_ratings.csv")
        self.assertEqual(
            list(
                zip(both_seasons["month"], both_seasons["availability_derate_monthly"])
            ),
            [
                (1, 1.05),
                (2, 1.05),
                (6, 0.9),
                (7, 0.9),
                (8, 0.9),
                (9, 0.9),
                (12, 1.05),
            ],
        )

        # Winter rating missing -> nameplate -> only summer months listed
        summer_only = read_monthly_csv(output_dir, "5__1_1-1-summer_winter_ratings.csv")
        self.assertEqual(
            list(zip(summer_only["month"], summer_only["availability_derate_monthly"])),
            [(6, 0.75), (7, 0.75), (8, 0.75), (9, 0.75)],
        )

        # The monthly scenario id is filled for exactly the projects with
        # a file, as an integer (the CSV port and the FK need the exact
        # (project, id) pairs to match)
        df = read_availability_csv(output_dir)
        id_by_project = dict(
            zip(df["project"], df["exogenous_availability_monthly_scenario_id"])
        )
        self.assertEqual(id_by_project["1__1"], "1")
        self.assertEqual(id_by_project["5__1_1"], "1")
        for project in ["1__2", "2__1", "3__W1", "4__B1"]:
            self.assertEqual(id_by_project[project], "")

    def test_seasonal_derates_aggregated(self):
        output_dir, stdout = self.run_step(
            [
                "--seasonal_capacity_derates",
                "--project_aggregation",
                "agg_project_keyed",
            ]
        )
        self.assertNotIn("WARNING", stdout)

        # Only the thermal aggregate gets a file (Wind and Batteries are
        # excluded operational types); the derate is capacity-weighted
        # with the no-rating unit contributing at nameplate:
        # summer (90 + 100 + 50 + 30) / 290, winter (105 + 100 + 50 + 40) / 290
        self.assertEqual(
            os.listdir(os.path.join(output_dir, "exogenous_monthly")),
            ["Gas_Zone1-1-summer_winter_ratings.csv"],
        )
        gas = read_monthly_csv(output_dir, "Gas_Zone1-1-summer_winter_ratings.csv")
        self.assertEqual(
            list(zip(gas["month"], gas["availability_derate_monthly"])),
            [
                (1, 1.017241),
                (2, 1.017241),
                (6, 0.931034),
                (7, 0.931034),
                (8, 0.931034),
                (9, 0.931034),
                (12, 1.017241),
            ],
        )

        df = read_availability_csv(output_dir)
        id_by_project = dict(
            zip(df["project"], df["exogenous_availability_monthly_scenario_id"])
        )
        self.assertEqual(id_by_project["Gas_Zone1"], "1")
        self.assertEqual(id_by_project["Wind_Zone1"], "")
        self.assertEqual(id_by_project["Batteries_Zone1"], "")

    def test_custom_months_and_subscenario(self):
        output_dir, _ = self.run_step(
            [
                "--seasonal_capacity_derates",
                "--summer_months",
                "7",
                "--winter_months",
                "1",
                "--exogenous_availability_monthly_scenario_id",
                "3",
                "--exogenous_availability_monthly_scenario_name",
                "test_name",
            ]
        )
        both_seasons = read_monthly_csv(output_dir, "1__1-3-test_name.csv")
        self.assertEqual(
            list(
                zip(both_seasons["month"], both_seasons["availability_derate_monthly"])
            ),
            [(1, 1.05), (7, 0.9)],
        )
        df = read_availability_csv(output_dir)
        id_by_project = dict(
            zip(df["project"], df["exogenous_availability_monthly_scenario_id"])
        )
        self.assertEqual(id_by_project["1__1"], "3")

    def test_op_type_exclusion_override(self):
        # Excluding only storage brings the wind unit into the derates
        output_dir, _ = self.run_step(
            [
                "--seasonal_capacity_derates",
                "--seasonal_derate_excluded_operational_types",
                "stor",
            ]
        )
        self.assertIn(
            "3__W1-1-summer_winter_ratings.csv",
            os.listdir(os.path.join(output_dir, "exogenous_monthly")),
        )
        self.assertNotIn(
            "4__B1-1-summer_winter_ratings.csv",
            os.listdir(os.path.join(output_dir, "exogenous_monthly")),
        )
        wind = read_monthly_csv(output_dir, "3__W1-1-summer_winter_ratings.csv")
        self.assertEqual(
            list(zip(wind["month"], wind["availability_derate_monthly"])),
            [
                (1, 0.833333),
                (2, 0.833333),
                (6, 0.666667),
                (7, 0.666667),
                (8, 0.666667),
                (9, 0.666667),
                (12, 0.833333),
            ],
        )
        df = read_availability_csv(output_dir)
        id_by_project = dict(
            zip(df["project"], df["exogenous_availability_monthly_scenario_id"])
        )
        self.assertEqual(id_by_project["3__W1"], "1")
        self.assertEqual(id_by_project["4__B1"], "")

    def test_op_type_exclusion_empty_derates_every_type(self):
        output_dir, _ = self.run_step(
            [
                "--seasonal_capacity_derates",
                "--seasonal_derate_excluded_operational_types",
                "",
            ]
        )
        self.assertEqual(
            sorted(os.listdir(os.path.join(output_dir, "exogenous_monthly"))),
            [
                "1__1-1-summer_winter_ratings.csv",
                "3__W1-1-summer_winter_ratings.csv",
                "4__B1-1-summer_winter_ratings.csv",
                "5__1_1-1-summer_winter_ratings.csv",
            ],
        )
        battery = read_monthly_csv(output_dir, "4__B1-1-summer_winter_ratings.csv")
        self.assertEqual(
            list(zip(battery["month"], battery["availability_derate_monthly"]))[:3],
            [(1, 0.966667), (2, 0.966667), (6, 0.916667)],
        )


class TestOpTypeExclusionSetting(unittest.TestCase):
    def test_default_builds_not_in_clause(self):
        clause = get_seasonal_derate_op_type_filter_string(
            DEFAULT_SEASONAL_DERATE_EXCLUDED_OP_TYPES
        )
        self.assertIn("NOT IN", clause)
        for op_type in [
            "gen_var",
            "gen_var_must_take",
            "gen_hydro",
            "gen_hydro_must_take",
            "stor",
        ]:
            self.assertIn(f"'{op_type}'", clause)

    def test_empty_value_builds_no_clause(self):
        self.assertEqual(get_seasonal_derate_op_type_filter_string(""), "")
        self.assertEqual(get_seasonal_derate_op_type_filter_string(" , "), "")

    def test_non_identifier_token_raises(self):
        # tokens are interpolated into SQL, so anything beyond
        # operational-type-name characters must be refused
        with self.assertRaisesRegex(ValueError, "operational-type names"):
            get_seasonal_derate_op_type_filter_string("stor,gen_var') OR ('1'='1")


class TestMonthSettings(unittest.TestCase):
    def test_defaults_parse(self):
        self.assertEqual(
            get_seasonal_months("6,7,8,9", "12,1,2"), ([6, 7, 8, 9], [12, 1, 2])
        )

    def test_overlap_raises(self):
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            get_seasonal_months("6,7,8,9", "9,12")

    def test_out_of_range_raises(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 12"):
            parse_month_list("6,13", "summer_months")

    def test_non_integer_raises(self):
        with self.assertRaisesRegex(ValueError, "comma-separated month numbers"):
            parse_month_list("June", "summer_months")

    def test_duplicate_raises(self):
        with self.assertRaisesRegex(ValueError, "must not repeat"):
            parse_month_list("6,6", "summer_months")


class TestHyphenatedProjectNameRefused(unittest.TestCase):
    def test_hyphenated_project_name_raises(self):
        # A hyphen can only come from a user-supplied custom-zone or
        # agg_project name (the disaggregated name expression sanitizes
        # generator ids); the per-project CSV filename convention cannot
        # carry it, so the step must refuse rather than write a file the
        # CSV port would misattribute
        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaisesRegex(ValueError, "contains a hyphen"):
                write_monthly_derate_csvs(
                    derates_df=pd.DataFrame(
                        {
                            "project": ["Gas_CISO-N"],
                            "summer_derate": [0.9],
                            "winter_derate": [1.0],
                        }
                    ),
                    summer_months=[6, 7, 8, 9],
                    winter_months=[12, 1, 2],
                    csv_location=output_dir,
                    subscenario_id=1,
                    subscenario_name="summer_winter_ratings",
                )


class TestWarnOnMissingSeasonalRatingData(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "seasonal_warn_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)

    def insert_units(self, rows):
        self.conn.executemany(
            "INSERT INTO raw_data_eia860_generators (plant_id_eia, "
            "generator_id, summer_capacity_mw, winter_capacity_mw) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = warn_on_missing_seasonal_rating_data(conn=self.conn)
        return result, out.getvalue()

    def test_no_warning_when_any_row_has_a_rating(self):
        self.insert_units([(1, "1", 90, None), (2, "1", None, None)])
        (n_populated, n_rows), output = self.check()
        self.assertEqual((n_populated, n_rows), (1, 2))
        self.assertEqual(output, "")

    def test_warns_when_columns_entirely_null(self):
        self.insert_units([(1, "1", None, None), (2, "1", None, None)])
        (n_populated, n_rows), output = self.check()
        self.assertEqual((n_populated, n_rows), (0, 2))
        self.assertIn("WARNING", output)
        self.assertIn("gridpath_pudl_to_gridpath_raw", output)

    def test_no_warning_on_empty_table(self):
        # an empty generators table is some other problem, not this one
        (n_populated, n_rows), output = self.check()
        self.assertEqual((n_populated, n_rows), (0, 0))
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
