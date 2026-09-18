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

from db.create_database import main as create_database_main
from ra_toolkit.temporal.create_temporal_scenarios import (
    main as create_temporal_scenarios_main,
)

os.chdir(os.path.join(os.path.dirname(__file__), "..", "..", "..", "db"))


class TestCreateTemporalScenarios(unittest.TestCase):
    """
    Test create_temporal_scenarios script
    """

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
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

    def test_create_temporal_scenarios(self):
        """Test create_temporal_scenarios with hardcoded arguments"""
        args = [
            "--database",
            self.db_path,
            "--csv_path",
            "./csvs_test_examples/raw_data_ra_toolkit/temporal/temporal_scenarios.csv",
            "--quiet",
        ]
        create_temporal_scenarios_main(args)

    @classmethod
    def tearDownClass(cls):
        """Clean up test database"""
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
