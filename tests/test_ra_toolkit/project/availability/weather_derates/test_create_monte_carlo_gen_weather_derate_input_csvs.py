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

from db.create_database import main as create_database_main
from ra_toolkit.temporal.create_monte_carlo_weather_draws import (
    main as create_monte_carlo_weather_draws_main,
)
from ra_toolkit.temporal.create_monte_carlo_weather_draw_profiles import (
    main as create_monte_carlo_weather_draw_profiles_main,
)
from ra_toolkit.project.availability.weather_derates.create_monte_carlo_gen_weather_derate_input_csvs import (
    main as create_monte_carlo_gen_weather_derate_input_csvs_main,
)


class TestCreateMonteCarloGenWeatherDerateInputCsvs(unittest.TestCase):
    """
    Test create_monte_carlo_gen_weather_derate_input_csvs script
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
            "../ra_toolkit/raw_data_db_schema.sql",
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
            "./csvs_test_examples/raw_data_ra_toolkit/project/availability/"
            "/user_defined_monte_carlo_timeseries_thermal_only.csv",
            "--timeseries_type",
            "availability",
            "--raw_data_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/availability"
            "/user_defined_weather_derates.csv",
            "--units_input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/availability/"
            "/user_defined_unit_availability_params.csv",
            "--study_year",
            "2026",
            "--quiet",
        ]
        create_monte_carlo_weather_draw_profiles_main(weather_profiles_args)

    def test_create_monte_carlo_gen_weather_derate_input_csvs(self):
        """Test create_monte_carlo_gen_weather_derate_input_csvs with hardcoded arguments"""
        args = [
            "--database",
            self.db_path,
            "--output_directory",
            "./csvs_test_examples/project/availability/exogenous_weather",
            "--exogenous_availability_weather_scenario_id",
            "5",
            "--exogenous_availability_weather_scenario_name",
            "ra_toolkit_module_tests_mc",
            "--stage_id",
            "1",
            "--overwrite",
            "--n_parallel_projects",
            "4",
            "--quiet",
        ]
        create_monte_carlo_gen_weather_derate_input_csvs_main(args)

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
