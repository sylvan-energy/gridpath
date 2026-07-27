# Copyright 2016-2023 Blue Marble Analytics LLC.
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

import logging
import os
import shutil
import tempfile
import unittest

from gridpath import run_end_to_end
from tests.test_examples import set_up_test_database
from viz import (
    capacity_factor_plot,
    capacity_new_plot,
    capacity_retired_plot,
    capacity_total_loadzone_comparison_plot,
    capacity_total_plot,
    capacity_total_scenario_comparison_plot,
    carbon_plot,
    cost_plot,
    curtailment_hydro_heatmap_plot,
    curtailment_variable_heatmap_plot,
    dispatch_plot,
    energy_plot,
    energy_target_plot,
    project_operations_plot,
)

# Change directory to 'gridpath' directory, as that's what run_scenario.py
# expects; the rest of the global variables are relative paths from there
os.chdir(os.path.join(os.path.dirname(__file__), "..", "gridpath"))
EXAMPLES_DIRECTORY = os.path.join("..", "examples")
# When running in parallel via pytest-xdist, give each worker process its
# own database (PYTEST_XDIST_WORKER is e.g. "gw0"; unset in serial runs)
XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
DB_NAME = f"unittest_examples{XDIST_WORKER}"
DB_PATH = f"../db/{DB_NAME}.db"

# The example scenarios solved to populate results for the plot tests
SCENARIOS_TO_RUN = [
    "test",
    "test_new_solar_carbon_cap",
    "2periods_new_build_rps_percent_target",
    "2periods_gen_lin_econ_retirement",
    "2periods_new_build_2zones",
    "2horizons_w_hydro",
]


class TestViz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Set up the testing database
        :return:
        """

        set_up_test_database(DB_PATH)

        # Solve the scenarios in a temporary copy of their example
        # directories, so that these runs don't write into examples/
        # directories that concurrently running tests may also be using
        cls.scenarios_dir = tempfile.TemporaryDirectory()
        for scenario_name in SCENARIOS_TO_RUN:
            shutil.copytree(
                os.path.join(EXAMPLES_DIRECTORY, scenario_name),
                os.path.join(cls.scenarios_dir.name, scenario_name),
            )

        try:
            # Run a few scenarios to populate results
            for scenario_name in SCENARIOS_TO_RUN:
                run_end_to_end.main(
                    [
                        "--database",
                        DB_PATH,
                        "--scenario",
                        scenario_name,
                        "--scenario_location",
                        cls.scenarios_dir.name,
                        "--quiet",
                        "--mute_solver_output",
                    ]
                )
        except Exception as e:
            print(
                "Error encountered during population of testing database "
                "{}.db. Deleting database ...".format(DB_NAME)
            )
            logging.exception(e)
            os.remove(DB_PATH)

    def test_capacity_factor_plot(self):
        capacity_factor_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "test",
                "--load_zone",
                "Zone1",
                # "--show",
            ]
        )

    def test_capacity_new_plot(self):
        capacity_new_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "test_new_solar_carbon_cap",
                "--load_zone",
                "Zone1",
                # "--show",
            ]
        )

    def test_capacity_retired_plot(self):
        capacity_retired_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "2periods_gen_lin_econ_retirement",
                "--load_zone",
                "Zone1",
                # "--show",
            ]
        )

    def test_capacity_total_loadzone_comparison_plot(self):
        capacity_total_loadzone_comparison_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "2periods_new_build_2zones",
                "--period",
                "2020",
                # "--show",
            ]
        )

    def test_capacity_total_plot(self):
        capacity_total_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "test_new_solar_carbon_cap",
                "--load_zone",
                "Zone1",
                # "--show",
            ]
        )

    # def test_capacity_total_scenario_comparison_plot(self):
    #     """This plot does not work"""
    #     capacity_total_scenario_comparison_plot.main(
    #         [
    #             "--database",
    #             DB_PATH,
    #             "--period",
    #             "2020",
    #             "--load_zone",
    #             "Zone1",
    #             "--show",
    #         ]
    #     )

    def test_carbon_plot(self):
        carbon_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "test_new_solar_carbon_cap",
                "--carbon_cap_zone",
                "Zone1",
                # "--show",
            ]
        )

    def test_cost_plot(self):
        cost_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "test_new_solar_carbon_cap",
                "--load_zone",
                "Zone1",
                # "--show",
            ]
        )

    def test_curtailment_hydro_heatmap_plot(self):
        curtailment_hydro_heatmap_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "2horizons_w_hydro",
                "--load_zone",
                "Zone1",
                "--period",
                "2020",
                # "--show",
            ]
        )

    def test_curtailment_variable_heatmap_plot(self):
        curtailment_variable_heatmap_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "2horizons_w_hydro",
                "--load_zone",
                "Zone1",
                "--period",
                "2020",
                # "--show",
            ]
        )

    def test_dispatch_plot(self):
        dispatch_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "test",
                "--load_zone",
                "Zone1",
                "--starting_tmp",
                "20200101",
                "--ending_tmp",
                "20200102",
                # "--show",
            ]
        )

    def test_energy_plot(self):
        energy_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "2periods_gen_lin_econ_retirement",
                "--load_zone",
                "Zone1",
                # "--show",
            ]
        )

    def test_energy_target_plot(self):
        energy_target_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "2periods_new_build_rps_percent_target",
                "--energy_target_zone",
                "RPSZone1",
                # "--show",
            ]
        )

    def test_project_operations_plot(self):
        project_operations_plot.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "2periods_new_build_rps_percent_target",
                "--period",
                "2030",
                "--project",
                "Gas_CCGT",
                # "--show",
            ]
        )

    @classmethod
    def tearDownClass(cls):
        cls.scenarios_dir.cleanup()
        os.remove(DB_PATH)
        for temp_file_ext in ["-shm", "-wal"]:
            temp_file = "{}{}".format(DB_PATH, temp_file_ext)
            if os.path.exists(temp_file):
                os.remove(temp_file)
