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
from ra_toolkit.project.availability.outages.create_availability_iteration_input_csvs import (
    main as create_availability_iteration_input_csvs_main,
)


class TestCreateAvailabilityIterationInputCsvs(unittest.TestCase):
    """
    Test create_availability_iteration_input_csvs script
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

    def test_create_availability_iteration_input_csvs(self):
        """Test create_availability_iteration_input_csvs with hardcoded arguments"""
        args = [
            "--database",
            self.db_path,
            "--input_csv",
            "./csvs_test_examples/raw_data_ra_toolkit/project/availability/user_defined_unit_availability_params.csv",
            "--n_iterations",
            "4",
            "--project_availability_scenario_id",
            "3",
            "--project_availability_scenario_name",
            "ra_toolkit_module_tests",
            "--output_directory",
            "./csvs_test_examples/project/availability/exogenous_independent",
            "--quiet",
            "--overwrite",
            "--user_provided_seeding",
            "--starting_project_iteration_seed",
            "1",
        ]
        create_availability_iteration_input_csvs_main(args)

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
