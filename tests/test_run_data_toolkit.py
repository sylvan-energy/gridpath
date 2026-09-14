# Copyright 2016-2024 Blue Marble Analytics LLC.
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

import os
import pandas as pd
import unittest

from data_toolkit import run_data_toolkit

OPEN_DATA_SETTINGS_CSV = "../tests/test_data/data_toolkit_open_data_settings.csv"


class TestDataToolkit(unittest.TestCase):
    """
    Run the Data Toolkit steps end to end against the open-data test
    fixture (builds the Data Toolkit raw database from
    data_toolkit/raw_data_db_schema.sql, loads it, and runs the steps).
    The RA Toolkit steps that used to share this settings CSV run against
    their own raw database in tests/test_run_ra_toolkit.py
    (ra_toolkit_open_data_settings.csv).
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up the testing database
        :return:
        """
        os.chdir(os.path.join(os.path.dirname(__file__), "..", "db"))
        temp_db_paths = get_temp_db_paths()

        for p in temp_db_paths:
            if os.path.exists(p):
                os.remove(p)

    def test_data_toolkit_open_data(self):
        os.chdir(os.path.join(os.path.dirname(__file__), "..", "db"))
        run_data_toolkit.main(["--settings_csv", OPEN_DATA_SETTINGS_CSV, "--quiet"])

    def test_ra_toolkit_step_in_settings_csv_fails_loudly(self):
        # A settings CSV naming a step from the other toolkit's registry
        # must fail upfront (before any step has run and had side
        # effects), pointing at the right command — not run the steps it
        # does know
        os.chdir(os.path.join(os.path.dirname(__file__), "..", "db"))
        with self.assertRaisesRegex(
            ValueError,
            "Unknown step 'create_temporal_scenarios' in the "
            "'gridpath.data_toolkit_steps' entry-point group",
        ):
            run_data_toolkit.main(
                [
                    "--settings_csv",
                    "../tests/test_data/ra_toolkit_open_data_settings.csv",
                    "--quiet",
                ]
            )

    @classmethod
    def tearDownClass(cls):
        temp_db_paths = get_temp_db_paths()

        for p in temp_db_paths:
            if os.path.exists(p):
                os.remove(p)
            for temp_file_ext in ["-shm", "-wal"]:
                temp_file = "{}{}".format(p, temp_file_ext)
                if os.path.exists(temp_file):
                    os.remove(temp_file)


def get_temp_db_paths():
    open_data_settings_df = pd.read_csv(OPEN_DATA_SETTINGS_CSV)
    open_data_settings_db_path = os.path.join(
        os.getcwd(),
        run_data_toolkit.get_setting(
            open_data_settings_df, "create_database", "database"
        ),
    )

    return [open_data_settings_db_path]


if __name__ == "__main__":
    unittest.main()
