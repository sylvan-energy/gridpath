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

from ra_toolkit import run_ra_toolkit

RA_SETTINGS_CSV = "../tests/test_data/data_toolkit_ra_settings.csv"
RA_SETTINGS_STEPS_CSV = "../tests/test_data/data_toolkit_ra_settings_steps.csv"
RA_OPEN_DATA_SETTINGS_CSV = "../tests/test_data/ra_toolkit_open_data_settings.csv"


class TestRAToolkit(unittest.TestCase):
    """
    Run the RA Toolkit steps end to end against the test fixtures (each
    settings CSV builds its own RA raw database from
    ra_toolkit/raw_data_db_schema.sql, loads it, and runs the steps).
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

    def test_ra_toolkit_single_steps(self):
        os.chdir(os.path.join(os.path.dirname(__file__), "..", "db"))
        for step in [
            "create_database",
            "load_raw_data",
            "create_sync_load_input_csvs",
            "create_sync_var_gen_input_csvs",
            "create_monte_carlo_weather_draws",
            "create_monte_carlo_weather_draw_profiles",
            "create_monte_carlo_load_input_csvs",
            "create_monte_carlo_var_gen_input_csvs",
            "create_hydro_iteration_input_csvs",
            "create_availability_iteration_input_csvs",
            "create_sync_gen_weather_derate_input_csvs",
            "create_monte_carlo_gen_weather_derate_input_csvs",
            "create_temporal_scenarios",
        ]:
            run_ra_toolkit.main(
                [
                    "--settings_csv",
                    RA_SETTINGS_STEPS_CSV,
                    "--quiet",
                    "--single_step_only",
                    step,
                ]
            )

    def test_ra_toolkit(self):
        os.chdir(os.path.join(os.path.dirname(__file__), "..", "db"))
        run_ra_toolkit.main(["--settings_csv", RA_SETTINGS_CSV, "--quiet"])

    def test_ra_toolkit_open_data(self):
        # The RA companion to the Data Toolkit's open-data integration run
        # (tests/test_run_data_toolkit.py): regenerates the RA-generated
        # open-data fixture CSVs (load levels, variable generation
        # profiles, hydro operational characteristics) from its own RA raw
        # database
        os.chdir(os.path.join(os.path.dirname(__file__), "..", "db"))
        run_ra_toolkit.main(["--settings_csv", RA_OPEN_DATA_SETTINGS_CSV, "--quiet"])

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
    temp_db_paths = []
    for settings_csv in [
        RA_SETTINGS_CSV,
        RA_SETTINGS_STEPS_CSV,
        RA_OPEN_DATA_SETTINGS_CSV,
    ]:
        settings_df = pd.read_csv(settings_csv)
        temp_db_paths.append(
            os.path.join(
                os.getcwd(),
                run_ra_toolkit.get_setting(settings_df, "create_database", "database"),
            )
        )

    return temp_db_paths


if __name__ == "__main__":
    unittest.main()
