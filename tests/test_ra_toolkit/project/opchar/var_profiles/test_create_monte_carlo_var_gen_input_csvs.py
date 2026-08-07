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
import unittest

import pandas as pd

from db.create_database import main as create_database_main
from ra_toolkit.temporal.create_monte_carlo_weather_draws import (
    main as create_monte_carlo_weather_draws_main,
)
from ra_toolkit.temporal.create_monte_carlo_weather_draw_profiles import (
    main as create_monte_carlo_weather_draw_profiles_main,
)
from ra_toolkit.project.opchar.var_profiles.create_monte_carlo_var_gen_input_csvs import (
    main as create_monte_carlo_var_gen_input_csvs_main,
)


class TestCreateMonteCarloVarGenInputCsvs(unittest.TestCase):
    """
    Test create_monte_carlo_var_gen_input_csvs script
    """

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        os.chdir(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "db")
        )
        cls.db_path = "ra_toolkit_test_steps_temp.db"

        # Clean up temp database if it exists
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

        # Create database first
        create_db_args = [
            "--database",
            cls.db_path,
            "--db_schema",
            "../data_toolkit/raw_data_db_schema.sql",
            "--quiet",
        ]
        create_database_main(create_db_args)

        # Create monte carlo weather draws (prerequisite)
        weather_draws_args = [
            "--database",
            cls.db_path,
            "--input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/monte_carlo_weather"
            "/user_defined_monte_carlo_weather_bins.csv",
            "--weather_draws_seed",
            "0",
            "--n_iterations",
            "2",
            "--study_year",
            "2026",
            "--quiet",
        ]
        create_monte_carlo_weather_draws_main(weather_draws_args)

        # Create monte carlo weather draw profiles (prerequisite)
        weather_profiles_args = [
            "--database",
            cls.db_path,
            "--timeseries_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/opchar/"
            "/user_defined_monte_carlo_timeseries_var_only.csv",
            "--timeseries_type",
            "var_profiles",
            "--raw_data_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/opchar"
            "/var_profiles/pudl_ra_toolkit_var_profiles.csv",
            "--units_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/opchar/"
            "/user_defined_var_project_units.csv",
            "--study_year",
            "2026",
            "--quiet",
        ]
        create_monte_carlo_weather_draw_profiles_main(weather_profiles_args)

    def test_parallel_matches_serial(self):
        """n_parallel_projects=4 produces byte-identical CSVs to n_parallel_projects=1.
        Catches any row-ordering or data-loss bugs in the spawn pool implementation."""
        serial_dir = (
            "./csvs_test_examples/project/opchar/variable_generator_profiles_serial"
        )
        parallel_dir = (
            "./csvs_test_examples/project/opchar/variable_generator_profiles_parallel"
        )
        os.makedirs(serial_dir, exist_ok=True)
        os.makedirs(parallel_dir, exist_ok=True)

        common_args = [
            "--database",
            self.db_path,
            "--variable_generator_profile_scenario_id",
            "8",
            "--variable_generator_profile_scenario_name",
            "ra_toolkit_parallel_consistency_test",
            "--stage_id",
            "1",
            "--overwrite",
            "--quiet",
        ]

        create_monte_carlo_var_gen_input_csvs_main(
            common_args
            + ["--output_directory", serial_dir, "--n_parallel_projects", "1"]
        )
        create_monte_carlo_var_gen_input_csvs_main(
            common_args
            + ["--output_directory", parallel_dir, "--n_parallel_projects", "4"]
        )

        serial_files = sorted(f for f in os.listdir(serial_dir) if f.endswith(".csv"))
        parallel_files = sorted(
            f for f in os.listdir(parallel_dir) if f.endswith(".csv")
        )
        self.assertEqual(
            serial_files,
            parallel_files,
            "Different set of output files between serial and parallel runs",
        )

        sort_cols = ["weather_iteration", "timepoint"]
        for fname in serial_files:
            s = pd.read_csv(os.path.join(serial_dir, fname))
            p = pd.read_csv(os.path.join(parallel_dir, fname))
            s = s.sort_values(sort_cols).reset_index(drop=True)
            p = p.sort_values(sort_cols).reset_index(drop=True)
            pd.testing.assert_frame_equal(
                s,
                p,
                check_like=False,
                obj=f"{fname}: serial vs parallel",
            )

    def test_create_monte_carlo_var_gen_input_csvs(self):
        """Test create_monte_carlo_var_gen_input_csvs with hardcoded arguments"""
        args = [
            "--database",
            self.db_path,
            "--output_directory",
            "./csvs_test_examples/project/opchar/variable_generator_profiles",
            "--variable_generator_profile_scenario_id",
            "7",
            "--variable_generator_profile_scenario_name",
            "ra_toolkit_module_tests_mc",
            "--stage_id",
            "1",
            "--overwrite",
            "--n_parallel_projects",
            "4",
            "--quiet",
        ]
        create_monte_carlo_var_gen_input_csvs_main(args)

    @classmethod
    def tearDownClass(cls):
        """Clean up test database"""
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        for temp_file_ext in ["-shm", "-wal"]:
            temp_file = f"{cls.db_path}{temp_file_ext}"
            if os.path.exists(temp_file):
                os.remove(temp_file)


if __name__ == "__main__":
    unittest.main()
