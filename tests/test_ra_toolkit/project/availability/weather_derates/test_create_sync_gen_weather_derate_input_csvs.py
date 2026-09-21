# Copyright 2016-2024 Blue Marble Analytics LLC.
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
import tempfile
import unittest

import pandas as pd

from db.create_database import main as create_database_main
from ra_toolkit.project.availability.weather_derates.create_sync_gen_weather_derate_input_csvs import (
    main as create_sync_gen_weather_derate_input_csvs_main,
)


class TestCreateSyncGenWeatherDerateInputCsvs(unittest.TestCase):
    """
    Test create_sync_gen_weather_derate_input_csvs script
    """

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        os.chdir(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "db")
        )
        # The scratch DB lives in a per-class temp dir: a shared
        # CWD-relative DB file caused flaky lock/disk-I/O errors and stale
        # WAL state across test modules
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "step_test_temp.db")

        # Create database first
        create_db_args = [
            "--database",
            cls.db_path,
            "--db_schema",
            "../ra_toolkit/raw_data_db_schema.sql",
            "--quiet",
        ]
        create_database_main(create_db_args)

    def test_create_sync_gen_weather_derate_input_csvs(self):
        """Test create_sync_gen_weather_derate_input_csvs with hardcoded arguments"""
        args = [
            "--database",
            self.db_path,
            "--availability_profile_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/availability/user_defined_weather_derates.csv",
            "--units_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/availability/user_defined_unit_availability_params.csv",
            "--output_directory",
            "./csvs_test_examples/project/availability/exogenous_weather",
            "--exogenous_availability_weather_scenario_id",
            "6",
            "--exogenous_availability_weather_scenario_name",
            "ra_toolkit_module_tests_sync",
            "--n_parallel_projects",
            "4",
            "--quiet",
            "--overwrite",
        ]
        create_sync_gen_weather_derate_input_csvs_main(args)

    def test_study_year_offsets_timepoints(self):
        """With --study_year, timepoint IDs are offset by YYYY0000 instead
        of running 1 through 8760."""
        out_dir = tempfile.TemporaryDirectory()
        self.addCleanup(out_dir.cleanup)
        # Own scratch DB: the raw CSVs are loaded again here and the raw
        # tables have UNIQUE constraints
        db_path = os.path.join(out_dir.name, "study_year_test.db")
        create_database_main(
            [
                "--database",
                db_path,
                "--db_schema",
                "../ra_toolkit/raw_data_db_schema.sql",
                "--quiet",
            ]
        )
        args = [
            "--database",
            db_path,
            "--availability_profile_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/availability/user_defined_weather_derates.csv",
            "--units_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/availability/user_defined_unit_availability_params.csv",
            "--output_directory",
            out_dir.name,
            "--exogenous_availability_weather_scenario_id",
            "6",
            "--exogenous_availability_weather_scenario_name",
            "study_year_test",
            "--study_year",
            "2026",
            "--print_ones",
            "--n_parallel_projects",
            "2",
            "--quiet",
            "--overwrite",
        ]
        create_sync_gen_weather_derate_input_csvs_main(args)

        profile_files = [
            f for f in os.listdir(out_dir.name) if f.endswith("-6-study_year_test.csv")
        ]
        self.assertTrue(profile_files)
        # Only some fixture projects have derate profile rows; the others
        # get header-only CSVs
        n_populated = 0
        for f in profile_files:
            df = pd.read_csv(os.path.join(out_dir.name, f))
            if df.empty:
                continue
            n_populated += 1
            hour_of_year = df["timepoint"] - 2026 * 10000
            self.assertTrue((hour_of_year >= 1).all(), f)
            self.assertTrue((hour_of_year <= 8784).all(), f)
            # --print_ones keeps every hour, so each iteration starts at hour 1
            self.assertTrue(
                (
                    df.groupby("weather_iteration")["timepoint"].min()
                    == 2026 * 10000 + 1
                ).all(),
                f,
            )
        self.assertGreater(n_populated, 0)

    @classmethod
    def tearDownClass(cls):
        """Clean up test database"""
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
