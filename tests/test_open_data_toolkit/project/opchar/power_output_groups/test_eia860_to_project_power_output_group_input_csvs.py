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
The hybrid power-output-group step: clustering (co-location and
cross-plant direct-support links), the POI-limit rules, the battery MW
basis (nameplate default vs the supplement's discharge rating) and the
rating-vs-nameplate mismatch warning, per-cluster groups in the
disaggregated mode vs per-token groups in aggregated modes, the exact
output column sets, the empty-fleet header-only CSVs, and the treatment
guards.
"""

import contextlib
import io
import os
import pandas as pd
import sqlite3
import tempfile
import unittest

from db.create_database import main as create_database_main
from open_data_toolkit.project.opchar.power_output_groups import (
    eia860_to_project_power_output_group_input_csvs as step,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "..",
    "..",
    "open_data_toolkit",
    "raw_data_db_schema.sql",
)


class TestPowerOutputGroupStep(unittest.TestCase):
    """
    Fixture fleet (all operating, one BA): plant 1 — co-located solar
    (100 MW) + battery (50 MW nameplate, 46 MW filed discharge rating —
    within the mismatch-warning tolerance);
    plant 2 — standalone solar; plant 4 — battery (30 MW, no supplement
    rating) direct-supporting plant 5's solar (90 MW); plant 3 — solar +
    is_independent battery (never grouped).
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.db_path = os.path.join(self.tmp_dir.name, "pog_step_test_raw.db")
        create_database_main(
            ["--database", self.db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        conn = sqlite3.connect(self.db_path)

        conn.execute(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES ('BA1', 'Region1', 'Interconnect1')"
        )
        conn.executemany(
            """
            INSERT INTO user_defined_eia_gridpath_key
            (prime_mover_code, energy_source_code, gridpath_capacity_type,
            gridpath_operational_type, gridpath_technology, agg_project)
            VALUES (?, ?, 'cap', ?, ?, ?)
            """,
            [
                ("PV", "SUN", "gen_var_must_take", "Solar", "Solar"),
                ("BA", "MWH", "stor", "Batteries", "Batteries"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            balancing_authority_code_eia, prime_mover_code,
            energy_source_code_1, operational_status_code,
            sector_name_eia, planned_generator_retirement_date, capacity_mw)
            VALUES ('v-test', '2026-01-01', ?, ?, 'BA1', ?, ?, 'OP',
            'Electric Utility', '2099-01-01', ?)
            """,
            [
                (1, "S1", "PV", "SUN", 100),
                (1, "B1", "BA", "MWH", 50),
                (2, "S1", "PV", "SUN", 80),
                (3, "S1", "PV", "SUN", 60),
                (3, "B1", "BA", "MWH", 20),
                (4, "B1", "BA", "MWH", 30),
                (5, "S1", "PV", "SUN", 90),
            ],
        )
        conn.executemany(
            """
            INSERT INTO raw_data_eia860_energy_storage
            (version_num, report_date, plant_id_eia, generator_id,
            max_discharge_rate_mw, is_independent, is_direct_support,
            plant_id_eia_direct_support_1, generator_id_direct_support_1)
            VALUES ('v-test', '2025-01-01', ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "B1", 46.0, 0, 0, None, None),
                (3, "B1", None, 1, 0, None, None),
                (4, "B1", None, 0, 1, 5, "S1"),
            ],
        )
        conn.commit()
        conn.close()

    def run_step(self, extra_args=()):
        output_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        self.stdout = io.StringIO()
        with contextlib.redirect_stdout(self.stdout):
            step.main(
                [
                    "--database",
                    self.db_path,
                    "--output_directory",
                    output_directory,
                    "--study_year",
                    "2030",
                    "--footprint",
                    "Interconnect1",
                    "--hybrid_treatment",
                    "power_output_group",
                    # No net-metering data in the fixture: silence that
                    # loud warning so stdout assertions see only this
                    # step's own
                    "--include_net_metered",
                    "--quiet",
                ]
                + list(extra_args)
            )
        projects_df = pd.read_csv(
            os.path.join(output_directory, "projects", "1_hybrids.csv")
        )
        requirements_df = pd.read_csv(
            os.path.join(output_directory, "requirements", "1_hybrid_poi_limits.csv")
        )

        return projects_df, requirements_df

    def test_disaggregated_groups(self):
        projects_df, requirements_df = self.run_step()

        # Plant 1 co-location and the cross-plant 4->5 link each form a
        # group; plant 2 (standalone) and plant 3 (independent battery)
        # do not
        self.assertEqual(
            list(projects_df.itertuples(index=False, name=None)),
            [
                ("hybrid_1", "1__B1"),
                ("hybrid_1", "1__S1"),
                ("hybrid_4", "4__B1"),
                ("hybrid_4", "5__S1"),
            ],
        )
        # POI = max(var, battery MW); the solar side dominates both
        self.assertEqual(
            list(requirements_df.itertuples(index=False, name=None)),
            [
                ("hybrid_1", 2030, 0, 100.0),
                ("hybrid_4", 2030, 0, 90.0),
            ],
        )
        self.assertEqual(list(projects_df.columns), step.PROJECTS_CSV_COLUMNS)
        self.assertEqual(list(requirements_df.columns), step.REQUIREMENTS_CSV_COLUMNS)
        # Fixture ratings are within tolerance: no mismatch warning
        self.assertNotIn("discharge rating", self.stdout.getvalue())

    def get_limits(self, requirements_df):
        return dict(
            zip(
                requirements_df["power_output_group"],
                requirements_df["power_output_group_total_power_max"],
            )
        )

    def test_sum_poi_rule(self):
        _projects_df, requirements_df = self.run_step(
            extra_args=["--hybrid_poi_rule", "sum"]
        )
        # var + battery NAMEPLATE (the default basis): plant 1's filed
        # 46 MW rating is ignored
        self.assertEqual(
            self.get_limits(requirements_df), {"hybrid_1": 150.0, "hybrid_4": 120.0}
        )

    def test_sum_poi_rule_discharge_rating_basis(self):
        _projects_df, requirements_df = self.run_step(
            extra_args=[
                "--hybrid_poi_rule",
                "sum",
                "--hybrid_battery_mw_basis",
                "discharge_rating",
            ]
        )
        # var + filed rating (plant 1), nameplate fallback where unfiled
        # (plant 4)
        self.assertEqual(
            self.get_limits(requirements_df), {"hybrid_1": 146.0, "hybrid_4": 120.0}
        )

    def set_plant_1_battery(self, nameplate_mw, discharge_rating_mw):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE raw_data_eia860_generators SET capacity_mw = ? "
            "WHERE plant_id_eia = 1 AND generator_id = 'B1'",
            (nameplate_mw,),
        )
        conn.execute(
            "UPDATE raw_data_eia860_energy_storage SET max_discharge_rate_mw = ? "
            "WHERE plant_id_eia = 1 AND generator_id = 'B1'",
            (discharge_rating_mw,),
        )
        conn.commit()
        conn.close()

    def test_battery_mw_basis_and_mismatch_warning(self):
        # Plant 1's battery: 120 MW nameplate (larger than the 100 MW
        # solar) but a stale 12 MW filed rating, 10% of nameplate
        self.set_plant_1_battery(nameplate_mw=120, discharge_rating_mw=12)

        # Default basis: the group cap is the battery's NAMEPLATE, the
        # same number the capacity step writes for the member
        _projects_df, requirements_df = self.run_step()
        self.assertEqual(self.get_limits(requirements_df)["hybrid_1"], 120.0)
        nameplate_output = self.stdout.getvalue()

        # discharge_rating basis: the rating caps the battery side and the
        # solar side wins the max
        _projects_df, requirements_df = self.run_step(
            extra_args=["--hybrid_battery_mw_basis", "discharge_rating"]
        )
        self.assertEqual(self.get_limits(requirements_df)["hybrid_1"], 100.0)
        rating_output = self.stdout.getvalue()

        # The mismatch warning fires under BOTH bases despite --quiet,
        # naming the unit, both values and the ratio
        for output in (nameplate_output, rating_output):
            self.assertIn("WARNING: 1 hybrid battery", output)
            self.assertIn("more than 10%", output)
            self.assertRegex(output, r"\b1\s+B1\s+120\.0\s+12\.0\s+10\.0")

    def test_mismatch_warning_lists_only_offenders(self):
        # A 9% gap is within the 10% tolerance: silent
        self.set_plant_1_battery(nameplate_mw=50, discharge_rating_mw=45.5)
        self.run_step()
        self.assertNotIn("WARNING", self.stdout.getvalue())

        # A 12% gap below nameplate warns
        self.set_plant_1_battery(nameplate_mw=50, discharge_rating_mw=44)
        self.run_step()
        self.assertIn("WARNING: 1 hybrid battery has", self.stdout.getvalue())

        # ... and so does a rating ABOVE nameplate
        self.set_plant_1_battery(nameplate_mw=50, discharge_rating_mw=60)
        self.run_step()
        self.assertIn("WARNING: 1 hybrid battery has", self.stdout.getvalue())
        # Plant 4's unfiled battery is never reported
        self.assertNotRegex(self.stdout.getvalue(), r"\b4\s+B1\b")

    def test_unknown_battery_mw_basis_raises(self):
        with self.assertRaisesRegex(ValueError, "hybrid_battery_mw_basis"):
            step.get_battery_mw(
                units_df=pd.DataFrame(
                    {"capacity_mw": [1.0], "max_discharge_rate_mw": [1.0]}
                ),
                hybrid_battery_mw_basis="bogus",
            )

    def test_aggregated_groups_merge_per_token(self):
        projects_df, requirements_df = self.run_step(
            extra_args=[
                "--project_aggregation",
                "all",
                "--aggregation_dimensions",
                "hybrid",
            ]
        )
        self.assertEqual(
            list(projects_df.itertuples(index=False, name=None)),
            [
                ("hybrid_BA1", "Batteries_Hybrid_BA1"),
                ("hybrid_BA1", "Solar_Hybrid_BA1"),
            ],
        )
        # The zone group's limit is the SUM of its clusters' POIs
        self.assertEqual(
            list(requirements_df.itertuples(index=False, name=None)),
            [("hybrid_BA1", 2030, 0, 190.0)],
        )

    def test_no_hybrids_writes_header_only_csvs(self):
        # Exclude the batteries (planned retirement before the study
        # year) so nothing pairs
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE raw_data_eia860_generators "
            "SET planned_generator_retirement_date = '2028-01-01' "
            "WHERE prime_mover_code = 'BA'"
        )
        conn.commit()
        conn.close()

        projects_df, requirements_df = self.run_step()
        self.assertTrue(projects_df.empty)
        self.assertTrue(requirements_df.empty)
        self.assertEqual(list(projects_df.columns), step.PROJECTS_CSV_COLUMNS)
        self.assertEqual(list(requirements_df.columns), step.REQUIREMENTS_CSV_COLUMNS)

    def test_refuses_independent_treatment(self):
        with self.assertRaisesRegex(ValueError, "power_output_group"):
            step.main(
                ["--database", self.db_path, "--output_directory", ".", "--quiet"]
            )

    def test_aggregated_mode_requires_hybrid_dimension(self):
        with self.assertRaisesRegex(ValueError, "hybrid.*dimension"):
            self.run_step(extra_args=["--project_aggregation", "all"])


if __name__ == "__main__":
    unittest.main()
