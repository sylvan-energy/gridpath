# Copyright 2016-2025 Blue Marble Analytics LLC.
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

import ast
import csv
import logging
import multiprocessing
import os
import pandas as pd
import platform
import sqlite3
import unittest

from gridpath import run_end_to_end, run_scenario, validate_inputs
from db import create_database
from db.common_functions import connect_to_database
from db.utilities import port_csvs_to_db, scenario

# Change directory to 'gridpath' directory, as that's what run_scenario.py
# expects; the rest of the global variables are relative paths from there
os.chdir(os.path.join(os.path.dirname(__file__), "..", "gridpath"))
EXAMPLES_DIRECTORY = os.path.join("..", "examples")
DB_NAME = "unittest_examples"
DB_PATH = f"../db/{DB_NAME}.db"
DB_SCHEMA = f"../db/db_schema.sql"
DATA_DIRECTORY = "../db/data"
CSV_PATH = "../db//csvs_test_examples"
SCENARIOS_CSV = os.path.join(CSV_PATH, "scenarios.csv")
TEST_SCENARIOS_CSV = "../tests/test_data/test_scenario_objective_function_values.csv"

# Platform check
LINUX = True if platform.system() == "Linux" else False
MACOS = True if platform.system() == "Darwin" else False
WINDOWS = True if platform.system() == "Windows" else False

# Python version
PYTHON_VERSION = platform.python_version()


class TestExamples(unittest.TestCase):
    """ """

    df = pd.read_csv(TEST_SCENARIOS_CSV, delimiter=",")
    df.set_index("test_scenario", inplace=True)

    def assertDictAlmostEqual(self, d1, d2, msg=None, places=7):
        # check if both inputs are dicts
        self.assertIsInstance(d1, dict, "First argument is not a dictionary")
        self.assertIsInstance(d2, dict, "Second argument is not a dictionary")

        # check if both inputs have the same keys
        self.assertEqual(d1.keys(), d2.keys())

        # check each key
        for key, value in d1.items():
            if isinstance(value, dict):
                self.assertDictAlmostEqual(d1[key], d2[key], places=places, msg=msg)
            else:
                self.assertAlmostEqual(d1[key], d2[key], places=places, msg=msg)

    def check_validation(self, test):
        """
        Check that validate inputs runs without errors, and that there
        are no validation issues recorded in the status_validation table
        :return:
        """

        # Check that test validation runs without errors
        validate_inputs.main(["--database", DB_PATH, "--scenario", test, "--quiet"])

        # Check that no validation issues are recorded in the db for the test
        expected_validations = []

        conn = connect_to_database(
            db_path=DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES
        )
        c = conn.cursor()
        validations = c.execute("""
            SELECT scenario_name FROM status_validation
            INNER JOIN
            (SELECT scenario_id, scenario_name FROM scenarios)
            USING (scenario_id)
            WHERE scenario_name = '{}'
            """.format(test))
        actual_validations = validations.fetchall()
        conn.close()

        self.assertListEqual(expected_validations, actual_validations)

    def run_and_check_objective(
        self,
        scenario_name,
        expected_objective,
        additional_args=[],
        solver=None,
        parallel=1,
    ):
        """

        :param scenario_name: str, name of the test example
        :param expected_objective: float or dict, expected objective
        :param parallel: int, set to a number > 1 to test
            parallelization functionality
        :return:
        """

        args_to_pass = [
            "--database",
            DB_PATH,
            "--scenario",
            scenario_name,
            "--scenario_location",
            EXAMPLES_DIRECTORY,
            # "--log",
            # "--write_solver_files_to_logs_dir",
            # "--keepfiles",
            # "--symbolic",
            "--n_parallel_get_inputs",
            str(parallel),
            "--n_parallel_solve",
            str(parallel),
            "--quiet",
            "--mute_solver_output",
            "--testing",
        ] + additional_args

        if solver is not None:
            args_to_pass.append("--solver")
            args_to_pass.append(solver)

        actual_objective = run_end_to_end.main(args_to_pass)

        expected_objective = objective_function_overwrite(
            scenario_name=scenario_name, starting_objective=expected_objective
        )

        # Check if we have a multiprocessing manager
        # If so, convert the manager proxy dictionary to a simple dictionary
        # to avoid errors
        # Done via copies to avoid broken pipe error
        if hasattr(multiprocessing, "managers"):
            if isinstance(actual_objective, multiprocessing.managers.DictProxy):
                # Make a dictionary from a copy of the objective
                actual_objective_copy = dict(actual_objective.copy())
                for subproblem in actual_objective.keys():
                    # If we have stages, make a dictionary form a copy of the
                    # stage dictionary for each subproblem
                    if isinstance(
                        actual_objective[subproblem], multiprocessing.managers.DictProxy
                    ):
                        stage_dict_copy = dict(actual_objective_copy[subproblem].copy())
                        # Reset the stage dictionary to the new simple
                        # dictionary object
                        actual_objective_copy[subproblem] = stage_dict_copy
                # Reset the objective to the new dictionary object
                actual_objective = actual_objective_copy

        # Convert any numpy floats to plain Python floats, so that the
        # values written to the CSV can be read back with ast.literal_eval
        # (numpy floats are written as, e.g., 'np.float64(42.0)')
        actual_objective = objective_values_to_float(actual_objective)

        # Uncomment this to save new objective function values
        df = pd.read_csv(TEST_SCENARIOS_CSV, delimiter=",")
        df.set_index("test_scenario", inplace=True)
        # Set dtype to 'object' so that we can have floats and dictionaries
        # in the column
        df["actual_objective"] = df["actual_objective"].astype("object")
        df.at[scenario_name, "actual_objective"] = actual_objective
        df.to_csv(TEST_SCENARIOS_CSV, index=True)

        if scenario_name == "test_new_solar_carbon_cap_dac":
            # This test is particularly sensitive to platform and
            # Python version, so we relax the precision of the test a bit
            # more
            places = -1
        else:
            places = 1

        self.assertDictAlmostEqual(expected_objective, actual_objective, places=places)

    @classmethod
    def setUpClass(cls):
        """
        Set up the testing database
        :return:
        """

        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

        create_database.main(
            [
                "--database",
                DB_PATH,
                "--db_schema",
                DB_SCHEMA,
                "--data_directory",
                DATA_DIRECTORY,
            ]
        )

        try:
            port_csvs_to_db.main(
                ["--database", DB_PATH, "--csv_location", CSV_PATH, "--quiet"]
            )
        except Exception as e:
            print(
                "Error encountered during population of testing database "
                "{}.db. Deleting database ...".format(DB_NAME)
            )
            logging.exception(e)
            os.remove(DB_PATH)

        try:
            scenario.main(
                ["--database", DB_PATH, "--csv_path", SCENARIOS_CSV, "--quiet"]
            )
        except Exception as e:
            print(
                "Error encountered during population of testing database "
                "{}.db. Deleting database ...".format(DB_NAME)
            )
            logging.exception(e)
            os.remove(DB_PATH)

    def validate_and_test_example_generic(
        self, scenario_name, solver=None, skip_validation=False, additional_args=[]
    ):
        # Use the expected objective column by default
        # Since most development happens on MacOS, the generic expected
        # objective column is set to the MacOS value
        column_to_use = "expected_objective"
        if MACOS and not pd.isnull(
            self.df.loc[scenario_name]["expected_objective_darwin"]
        ):
            column_to_use = "expected_objective_darwin"
        if WINDOWS and not pd.isnull(
            self.df.loc[scenario_name]["expected_objective_windows"]
        ):
            column_to_use = "expected_objective_windows"
        if LINUX and not pd.isnull(
            self.df.loc[scenario_name]["expected_objective_linux"]
        ):
            column_to_use = "expected_objective_linux"

        # Evaluate the objective function as a literal (as it is in
        # dictionary format stored as string in the CSV)
        # This is now done for all scenarios, even if they have no iterations
        # or multiple subproblem/stages
        objective = ast.literal_eval(self.df.loc[scenario_name][column_to_use])

        if not skip_validation:
            self.check_validation(scenario_name)
        self.run_and_check_objective(
            scenario_name=scenario_name,
            solver=solver,
            expected_objective=objective,
            additional_args=additional_args,
        )

    def test_example_test(self):
        """
        Check validation and objective function value of "test" example
        :return:
        """
        scenario_name = "test"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_no_overgen_allowed(self):
        """
        Check validation and objective function value of
        "test_no_overgen_allowed" example
        :return:
        """

        scenario_name = "test_no_overgen_allowed"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_build_storage(self):
        """
        Check validation and objective function value of
        "test_new_build_storage" example
        :return:
        """

        scenario_name = "test_new_build_storage"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_binary_build_storage(self):
        """
        Check validation and objective function value of
        "test_new_binary_build_storage" example
        :return:
        """
        scenario_name = "test_new_binary_build_storage"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_build_storage_cumulative_min_max(self):
        """
        Check validation and objective function value of
        "test_new_build_storage_cumulative_min_max" example
        :return:
        """
        scenario_name = "test_new_build_storage_cumulative_min_max"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_no_reserves(self):
        """
        Check validation and objective function value of
        "test_no_reserves" example
        :return:
        """
        scenario_name = "test_no_reserves"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_hydro(self):
        """
        Check validation and objective function value of "test_w_hydro" example
        :return:
        """
        scenario_name = "test_w_hydro"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_storage(self):
        """
        Check validation and objective function value of "test_w_storage" example
        :return:
        """
        scenario_name = "test_w_storage"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2horizons(self):
        """
        Check validation and objective function value of "2horizons" example
        :return:
        """
        scenario_name = "2horizons"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2horizons_w_hydro(self):
        """
        Check validation and objective function value of
        "2horizons_w_hydro" example
        :return:
        """
        scenario_name = "2horizons_w_hydro"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2horizons_w_hydro_and_nuclear_binary_availability(self):
        """
        Check validation and objective function value of
        "2horizons_w_hydro_and_nuclear_binary_availability" example

        NOTE: the objective function for this example is lower than that for
        the '2horizons_w_hydro' example because of the unrealistically high
        relative heat rate of the 'Nuclear' project relative to the gas
        projects; allowing binary availability for a must-run project
        actually allows lower-cost power when the nuclear plant is
        unavailable. We should probably re-think this example as part of a
        future more general revamp of the examples.

        :return:
        """
        scenario_name = "2horizons_w_hydro_and_nuclear_binary_availability"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2horizons_w_hydro_w_balancing_types(self):
        """
        Check validation and objective function value of
        "2horizons_w_hydro_w_balancing_types" example. The objective
        function of this example should be lower than that of the
        '2horizons_w_hydro' example, as the average hydro budget is the
        same across all timepoints, but the hydro balancing horizon is now
        longer.
        :return:
        """
        scenario_name = "2horizons_w_hydro_w_balancing_types"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2horizons_w_stor_stress_hrz(self):
        """
        Check validation and objective function value of
        "2horizons_w_stor_stress_hrz" example. A stor_stress_hrz storage
        project builds up its state of charge over the first
        (average-condition) horizon and enters the second (stress) horizon,
        which has higher load, with the accumulated energy.
        :return:
        """
        scenario_name = "2horizons_w_stor_stress_hrz"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods(self):
        """
        Check validation and objective function value of "2periods" example
        :return:
        """
        scenario_name = "2periods"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build(self):
        """
        Check validation and objective function value of "2periods_new_build" example
        """
        scenario_name = "2periods_new_build"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_new_build_transmission(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_new_build_transmission" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_new_build_transmission"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_singleBA(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_singleBA"
        example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_singleBA"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_transmission"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission_w_losses(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission_w_losses" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_transmission_w_losses"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission_w_losses_curtailment_cost(
        self,
    ):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission_w_losses_curtailment_cost"
        example, in which a curtailment cost is applied to transmission
        losses

        Note: the objective function should differ from that of
        2periods_new_build_2zones_transmission_w_losses by exactly the total
        transmission curtailment cost
        :return:
        """
        scenario_name = (
            "2periods_new_build_2zones_transmission_w_losses_curtailment_cost"
        )
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission_w_losses_opp_dir(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission_w_losses_opp_dir" example

        Note: this should be the same as the objective function for
        2periods_new_build_2zones_transmission_w_losses
        :return:
        """
        scenario_name = "2periods_new_build_2zones_transmission_w_losses_opp_dir"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_rps(self):
        """
        Check validation and objective function value of
        "2periods_new_build_rps" example
        :return:
        """
        scenario_name = "2periods_new_build_rps"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_rps_w_tx_losses(self):
        """
        Check validation and objective function value of
        "2periods_new_build_rps_w_tx_losses" example, in which transmission
        losses count against the period energy target
        :return:
        """
        scenario_name = "2periods_new_build_rps_w_tx_losses"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_rps_percent_target(self):
        """
        Check objective function value of
        "2periods_new_build_rps_percent_target" example
        This example should have the same objective function as
        test_example_2periods_new_build_rps, as its target is the same,
        but specified as percentage of load.
        :return:
        """
        scenario_name = "2periods_new_build_rps_percent_target"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_cumulative_min_max(self):
        """
        Check validation and objective function value of
        "2periods_new_build_cumulative_min_max" example
        :return:
        """
        scenario_name = "2periods_new_build_cumulative_min_max"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_single_stage_prod_cost(self):
        """
        Check validation and objective function values of
        "single_stage_prod_cost" example
        :return:
        """
        scenario_name = "single_stage_prod_cost"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_single_stage_prod_cost_linked_subproblems(self):
        """
        Check objective function values of
        "single_stage_prod_cost_linked_subproblems" example
        :return:
        """
        scenario_name = "single_stage_prod_cost_linked_subproblems"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_single_stage_prod_cost_linked_subproblems_w_hydro(self):
        """
        Check objective function values of
        "single_stage_prod_cost_linked_subproblems" example
        :return:
        """
        scenario_name = "single_stage_prod_cost_linked_subproblems_w_hydro"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_multi_stage_prod_cost(self):
        """
        Check validation and objective function values of
        "multi_stage_prod_cost" example
        :return:
        """
        scenario_name = "multi_stage_prod_cost"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_single_stage_prod_cost_cycle_select(self):
        """
        Check validation and objective function values of
        "single_stage_prod_cost_cycle_select" example. This example is the same as
        single_stage_prod_cost but the Coal and Gas_CCGT plants have mutually
        exclusive commitment in this example.
        """
        scenario_name = "single_stage_prod_cost_cycle_select"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_multi_stage_prod_cost_parallel(self):
        """
        Check "multi_stage_prod_cost" example running subproblems in parallel
        (getting inputs and optimization)
        :return:
        """
        run_end_to_end.main(
            [
                "--database",
                DB_PATH,
                "--scenario",
                "multi_stage_prod_cost",
                "--scenario_location",
                EXAMPLES_DIRECTORY,
                # "--log",
                # "--write_solver_files_to_logs_dir",
                # "--keepfiles",
                # "--symbolic",
                "--n_parallel_get_inputs",
                "3",
                "--n_parallel_solve",
                "3",
                "--quiet",
                "--mute_solver_output",
                "--testing",
            ]
        )

    def test_example_multi_stage_prod_cost_w_hydro(self):
        """
        Check validation and objective function values of
        "multi_stage_prod_cost_w_hydro"
        example
        :return:
        """
        scenario_name = "multi_stage_prod_cost_w_hydro"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_multi_stage_prod_cost_linked_subproblems(self):
        """
        Check validation and objective function values of
        "multi_stage_prod_cost_linked_subproblems" example
        :return:
        """
        scenario_name = "multi_stage_prod_cost_linked_subproblems"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_gen_lin_econ_retirement(self):
        """
        Check validation and objective function value of
        "2periods_gen_lin_econ_retirement"
        example
        :return:
        """
        scenario_name = "2periods_gen_lin_econ_retirement"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_gen_bin_econ_retirement(self):
        """
        Check validation and objective function value of
        "2periods_gen_bin_econ_retirement"
        example
        :return:
        """
        scenario_name = "2periods_gen_bin_econ_retirement"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_variable_gen_reserves(self):
        """
        Check validation and objective function value of
        "variable_gen_reserves"
        example; this example requires a non-linear solver
        :return:
        """
        scenario_name = "test_variable_gen_reserves"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_rps_variable_reserves(self):
        """
        Check validation and objective function value of
        "2periods_new_build_rps_variable_reserves" example
        :return:
        """
        scenario_name = "2periods_new_build_rps_variable_reserves"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_rps_variable_reserves_subhourly_adj(self):
        """
        Check validation and objective function value of
        "2periods_new_build_rps_variable_reserves_subhourly_adj" example
        :return:
        """
        scenario_name = "2periods_new_build_rps_variable_reserves_subhourly_adj"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_ramp_up_constraints(self):
        """
        Check validation and objective function value of
        "test_ramp_up_constraints" example
        :return:
        """
        scenario_name = "test_ramp_up_constraints"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_ramp_up_and_down_constraints(self):
        """
        Check validation and objective function value of
        "test_ramp_up_and_down_constraints"
        example;
        :return:
        """
        scenario_name = "test_ramp_up_and_down_constraints"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_rps_w_rps_ineligible_storage(self):
        """
        Check validation and objective function value of
        "2periods_new_build_rps_w_rps_ineligible_storage" example
        :return:
        """
        scenario_name = "2periods_new_build_rps_w_rps_ineligible_storage"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_rps_w_rps_eligible_storage(self):
        """
        Check validation and objective function value of
        "2periods_new_build_rps_w_rps_eligible_storage" example
        :return:
        """
        scenario_name = "2periods_new_build_rps_w_rps_eligible_storage"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar(self):
        """
        Check validation and objective function value of
        "test_new_solar" example
        :return:
        """
        scenario_name = "test_new_solar"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_binary_solar(self):
        """
        Check validation and objective function value of
        "test_new_binary_solar" example
        :return:
        """
        scenario_name = "test_new_binary_solar"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_cap(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_cap" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_cap"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_cap_2zones_tx(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_cap_2zones_tx" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_cap_2zones_tx"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_cap_2zones_dont_count_tx(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_cap_2zones_dont_count_tx" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_cap_2zones_dont_count_tx"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_tax(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_tax" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_tax"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_simple_prm(self):
        """
        Check validation and objective function value of
        "2periods_new_build_simple_prm"
        example
        :return:
        """
        scenario_name = "2periods_new_build_simple_prm"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_simple_prm_w_energy_only(self):
        """
        Check validation and objective function value of
        "2periods_new_build_simple_prm"
        example
        :return:
        """
        scenario_name = "2periods_new_build_simple_prm_w_energy_only"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_simple_prm_w_energy_only_deliv_cap_limit(self):
        """
        Check validation and objective function value of
        "2periods_new_build_simple_prm"
        example
        :return:
        """
        scenario_name = "2periods_new_build_simple_prm_w_energy_only_deliv_cap_limit"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_local_capacity(self):
        """
        Check validation and objective function value of
        "2periods_new_build_local_capacity"
        example
        :return:
        """
        scenario_name = "2periods_new_build_local_capacity"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_tx_dcopf(self):
        """
        Check validation and objective function value of
        "test_tx_dcopf" example
        :return:
        """
        scenario_name = "test_tx_dcopf"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_tx_simple(self):
        """
        Check validation and objective function value of
        "test_tx_simple" example
        :return:
        """
        scenario_name = "test_tx_simple"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_tx_simple_tmp_emissions(self):
        """
        Check validation and objective function value of
        "test_tx_simple_tmp_emissions" example
        :return:
        """
        scenario_name = "test_tx_simple_tmp_emissions"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_tx_simple_additive(self):
        """
        Check validation and objective function value of
        "test_tx_simple_additive" example
        :return:
        """
        scenario_name = "test_tx_simple_additive"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_startup_shutdown_rates(self):
        """
        Check validation and objective function value of
        "test_startup_shutdown_rates"
        example
        :return:
        """
        scenario_name = "test_startup_shutdown_rates"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_no_fuels(self):
        """
        Check validation and objective function value of "test_no_fuels"
        example
        :return:
        """
        scenario_name = "test_no_fuels"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_variable_om_curves(self):
        """
        Check validation and objective function value of
        "test_variable_om_curves"
        example
        :return:
        """
        scenario_name = "test_variable_om_curves"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_aux_cons(self):
        """
        Check validation and objective function value of
        "test_aux_cons" example

        Note: the objective function value is lower than that for the "test"
        example because the auxiliary consumption results in less
        overgeneration and therefore lower overgeneration penalty.
        """
        scenario_name = "test_aux_cons"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_lf_down_percent_req(self):
        """
        Check validation and objective function value of
        "test_w_lf_down_percent_req" example
        :return:
        """
        scenario_name = "test_w_lf_down_percent_req"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_capgroups(self):
        """
        Check validation and objective function value of
        "test_example_2periods_new_build_capgroups" example
        """
        scenario_name = "2periods_new_build_capgroups"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_markets(self):
        """
        Check validation and objective function value of "test" example
        :return:
        """
        scenario_name = "test_markets"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_horizon_energy_target(self):
        """
        Check validation and objective function value of
        "test_example_2periods_new_build_horizon_energy_target" example
        :return:
        """
        scenario_name = "2periods_new_build_horizon_energy_target"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_horizon_energy_target_halfyear(self):
        """
        Check validation and objective function value of
        "2periods_new_build_horizon_energy_target_halfyear" example
        :return:
        """
        scenario_name = "2periods_new_build_horizon_energy_target_halfyear"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_build_gen_var_stor_hyb(self):
        """
        Check validation and objective function value of
        "test_new_build_gen_var_stor_hyb" example
        :return:
        """
        scenario_name = "test_new_build_gen_var_stor_hyb"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_carbon_tax_allowance(self):
        """
        Check validation and objective function value of
        "test_carbon_tax_allowance" example
        :return:
        """
        scenario_name = "test_carbon_tax_allowance"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_min_max_build_trans(self):
        """
        Check validation and objective function value of
        "test_min_max_build_trans" example
        :return:
        """
        scenario_name = "test_min_max_build_trans"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission_Tx1halfavail(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission_Tx1halfavail" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_transmission_Tx1halfavail"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission_Tx1halfavailmonthly(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission_Tx1halfavail" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_transmission_Tx1halfavailmonthly"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_cheap_fuel_blend(self):
        """
        Check validation and objective function value of "test_cheap_fuel_blend" example
        :return:
        """
        scenario_name = "test_cheap_fuel_blend"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_cap_2zones_tx_low_carbon_fuel_blend(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_cap_2zones_tx_low_carbon_fuel_blend" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_cap_2zones_tx_low_carbon_fuel_blend"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_cheap_fuel_blend_w_limit(self):
        """
        Check validation and objective function value of
        "test_cheap_fuel_blend_w_limit" example
        :return:
        """
        scenario_name = "test_cheap_fuel_blend_w_limit"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_fuel_burn_limit(self):
        """
        Check validation and objective function value of
        "test_new_solar_fuel_burn_limit" example. Inputs set up so that this should
        be the same as the "test_new_solar_carbon_cap" example.
        :return:
        """
        scenario_name = "test_new_solar_fuel_burn_limit"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_fuel_burn_limit_relative(self):
        """
        Check validation and objective function value of
        "test_new_solar_fuel_burn_limit_relative" example. Inputs set up so that this
        should be the same as the "test_new_solar_fuel_burn_limit" example.
        :return:
        """
        scenario_name = "test_new_solar_fuel_burn_limit_relative"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_w_solver_options(self):
        """
        Check validation and objective function value of "test_w_solver_options" example
        :return:
        """
        scenario_name = "test_w_solver_options"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_carbon_tax_allowance_with_different_fuel_groups(self):
        """
        Check validation and objective function value of
        "test_carbon_tax_allowance_with_different_fuel_groups" example
        :return:
        """
        scenario_name = "test_carbon_tax_allowance_with_different_fuel_groups"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_performance_standard(self):
        """
        Check validation and objective function value of "test_performance_standard" example
        :return:
        """
        scenario_name = "test_performance_standard"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_tx_flow(self):
        """
        Check validation and objective function value of
        "test_tx_flow" example
        :return:
        """
        scenario_name = "test_tx_flow"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_reserve_prj_contribution(self):
        """
        Check validation and objective function value of
        "test_reserve_prj_contribution" example.
        This example is based on "test_new_solar" with the only difference, the LF UP
        requirement ID
        :return:
        """
        scenario_name = "test_new_solar_reserve_prj_contribution"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_new_solar_carbon_cap_2zones_tx_hydrogen_prod(self):
        """
        Check validation and objective function value of
        "test_reserve_prj_contribution" example.
        This example is based on "test_new_solar" with the only difference, the LF UP
        requirement ID
        :return:
        """
        scenario_name = "test_new_solar_carbon_cap_2zones_tx_hydrogen_prod"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_new_solar_carbon_cap_2zones_tx_hydrogen_prod_new(self):
        """
        Check validation and objective function value of
        "test_reserve_prj_contribution" example.
        This example is based on "test_new_solar" with the only difference, the LF UP
        requirement ID
        :return:
        """
        scenario_name = "test_new_solar_carbon_cap_2zones_tx_hydrogen_prod_new"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_cap_dac(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_cap_dac" example.

        Note that the same version of Cbc (v2.10.12) produces a slightly
        different objective function for this problem on Windows/Linux than on
        Mac as of Python v3.12.
        :return:
        """
        scenario_name = "test_new_solar_carbon_cap_dac"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_cap_factor_limits(self):
        """
        Check validation and objective function value of "test" example
        :return:
        """
        scenario_name = "test_cap_factor_limits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_multi_stage_prod_cost_w_markets(self):
        """
        Check validation and objective function values of
        "multi_stage_prod_cost_w_markets" example
        :return:
        """
        scenario_name = "multi_stage_prod_cost_w_markets"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_supplemental_firing(self):
        """
        Check validation and objective function value of "test_supplemental_firing" example
        :return:
        """
        scenario_name = "test_supplemental_firing"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_tx_capacity_groups(self):
        """
        Check validation and objective function value of
        "test_tx_capacity_groups" example
        :return:
        """
        scenario_name = "test_tx_capacity_groups"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_fin_lifetime(self):
        """
        Check validation and objective function value of
        "2periods_new_build_fin_lifetime" example. Same as "2periods_new_build" but
        with shorter financial lifetimes and some fixed costs. Cost is lower because
        the same payment is made fewer times.
        """
        scenario_name = "2periods_new_build_fin_lifetime"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_cumulative_and_vintage_min_max(self):
        """
        Check validation and objective function value of
        "2periods_new_build_cumulative_and_vintage_min_max" example. It is the same
        as 2periods_new_build_cumulative_and_min_max but with a max in 2020 for the
        CCGT to force early build and a min on the CT in 2030 to force more build.

        :return:
        """
        scenario_name = "2periods_new_build_cumulative_and_vintage_min_max"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_storage_w_soc_penalty(self):
        """
        Check validation and objective function value of "test_w_storage_w_soc_penalty"
        example
        :return:
        """
        scenario_name = "test_w_storage_w_soc_penalty"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_storage_w_soc_last_tmp_penalty(self):
        """
        Check validation and objective function value of "test_w_storage_w_soc_penalty"
        example
        :return:
        """
        scenario_name = "test_w_storage_w_soc_last_tmp_penalty"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_itc(self):
        """
        Check validation and objective function value of
        "test_new_solar_itc" example
        :return:
        """
        scenario_name = "test_new_solar_itc"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_build_storage_itc(self):
        """
        Check validation and objective function value of
        "test_new_build_storage" example
        :return:
        """
        scenario_name = "test_new_build_storage_itc"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_simple_prm_2loadzones(self):
        """
        Check validation and objective function value of
        "2periods_new_build_simple_prm_2loadzones"
        example
        :return:
        """
        scenario_name = "2periods_new_build_simple_prm_2loadzones"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_simple_prm_2loadzones_newtx_w_transfers(self):
        """
        Check validation and objective function value of
        "2periods_new_build_simple_prm_w_transfers"
        example
        :return:
        """
        scenario_name = "2periods_new_build_simple_prm_2loadzones_newtx_w_transfers"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_simple_prm_2loadzones_newtx_w_transfers_w_costs(
        self,
    ):
        """
        Check validation and objective function value of
        "2periods_new_build_simple_prm_2loadzones_newtx_w_transfers_w_costs"
        example
        :return:
        """
        scenario_name = (
            "2periods_new_build_simple_prm_2loadzones_newtx_w_transfers_w_costs"
        )
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_flex_load(self):
        """
        Check validation and objective function value of "test_w_storage" example
        :return:
        """
        scenario_name = "test_w_flex_load"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_w_relative_capacity_instead_of_potential(self):
        """
        Check validation and objective function value of
        "test_new_solar" example
        :return:
        """
        scenario_name = "test_new_solar_w_relative_capacity_instead_of_potential"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission_w_hurdle_rates(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission_w_hurdle_rates" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_transmission_w_hurdle_rates"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission_w_hurdle_rates_by_timepoint(
        self,
    ):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission_w_hurdle_rates_by_timepoint" example
        :return:
        """
        scenario_name = (
            "2periods_new_build_2zones_transmission_w_hurdle_rates_by_timepoint"
        )
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_transmission_w_hurdle_rates_by_timepoint_and_period(
        self,
    ):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_transmission_w_hurdle_rates_by_timepoint_and_period" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_transmission_w_hurdle_rates_by_timepoint_and_period"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_simple_prm_2loadzones_newtx_w_transfers_w_subsidies(
        self,
    ):
        """
        Check validation and objective function value of
        "test_new_solar" example
        :return:
        """
        scenario_name = (
            "2periods_new_build_simple_prm_2loadzones_newtx_w_transfers_w_subsidies"
        )
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_build_storage_itc_single_superperiod(self):
        """
        Check validation and objective function value of
        "test_new_build_storage_itc_single_superperiodself" example
        :return:
        """
        scenario_name = "test_new_build_storage_itc_single_superperiod"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_incomplete_only(self):
        """
        Check that the "incomplete only" functionality works with no errors.
        :return:
        """
        actual_objective = run_scenario.main(
            [
                "--scenario",
                "test",
                "--scenario_location",
                EXAMPLES_DIRECTORY,
                "--quiet",
                "--mute_solver_output",
                "--incomplete_only",
            ]
        )

    def test_example_test_w_storage_starting_soc(self):
        """
        Check validation and objective function value of
        "test_w_storage_starting_soc" example
        :return:
        """
        scenario_name = "test_w_storage_starting_soc"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_nonfuel_emissions(self):
        """
        Check validation and objective function value of "test" example
        :return:
        """
        scenario_name = "test_w_nonfuel_emissions"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_credits(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_credits" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_credits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_performance_standard_carbon_credits(self):
        """
        Check validation and objective function value of "test_performance_standard" example
        :return:
        """
        scenario_name = "test_performance_standard_carbon_credits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_tax_w_carbon_credits(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_tax_w_carbon_credits" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_tax_w_carbon_credits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_solar_carbon_credits_w_sell(self):
        """
        Check validation and objective function value of
        "test_new_solar_carbon_credits_w_sell" example
        The carbon credit price must be set higher than the cost of USE in this
        example to incentivize the project to not run and generate credits.
        :return:
        """
        scenario_name = "test_new_solar_carbon_credits_w_sell"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_performance_standard_carbon_credits_w_cap_no_credits_mapping(self):
        """
        Check validation and objective function value of
        "test_performance_standard_carbon_credits_w_cap_no_credits_mapping" example
        :return:
        """
        scenario_name = (
            "test_performance_standard_carbon_credits_w_cap_no_credits_mapping"
        )
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_new_solar_carbon_credits_w_buy(self):
        """
        Check validation and objective function value of "test_new_solar_carbon_credits_w_buy" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_credits_w_buy"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_new_solar_carbon_credits_w_buy_and_sell(self):
        """
        Check validation and objective function value of "test_new_solar_carbon_credits_w_buy_and_sell" example
        :return:
        """
        scenario_name = "test_new_solar_carbon_credits_w_buy_and_sell"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_single_stage_prod_cost_w_spinup_lookahead(self):
        """
        Check validation and objective function values of
        "single_stage_prod_cost_w_spinup_lookahead" example
        :return:
        """
        scenario_name = "single_stage_prod_cost_w_spinup_lookahead"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_tx_targets_max(self):
        """
        Check validation and objective function value of
        "test_example_test_tx_targets_max"
        example
        :return:
        """
        scenario_name = "test_tx_targets_max"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_ra_toolkit_monte_carlo(self):
        """
        Check validation and objective function values of
        "ra_toolkit_monte_carlo" example
        :return:
        """
        scenario_name = "ra_toolkit_monte_carlo"
        self.validate_and_test_example_generic(
            scenario_name=scenario_name, skip_validation=True
        )

    def test_example_ra_toolkit_sync(self):
        """
        Check validation and objective function values of
        "ra_toolkit_sync" example
        :return:
        """
        scenario_name = "ra_toolkit_sync"
        self.validate_and_test_example_generic(
            scenario_name=scenario_name, skip_validation=True
        )

    def test_example_2periods_nuclear_var_cost_by_period_same(self):
        """
        Check validation and objective function value of "2periods_nuclear_var_cost_by_period_same" example
        :return:
        """
        scenario_name = "2periods_nuclear_var_cost_by_period_same"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_nuclear_var_cost_by_period_diff(self):
        """
        Check validation and objective function value of
        "2periods_nuclear_var_cost_by_period_diff" example
        :return:
        """
        scenario_name = "2periods_nuclear_var_cost_by_period_diff"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_ra_toolkit_sync_single_year(self):
        """
        Check validation and objective function values of
        "ra_toolkit_sync_single_year" example
        :return:
        """
        scenario_name = "ra_toolkit_sync_single_year"
        self.validate_and_test_example_generic(
            scenario_name=scenario_name, skip_validation=True
        )

    def test_test_performance_standard_power(self):
        """
        Check validation and objective function values of "test_performance_standard_power" example
        :return:
        """
        scenario_name = "test_performance_standard_power"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_performance_standard_both(self):
        """
        Check validation and objective function values of "test_performance_standard_both" example
        :return:
        """
        scenario_name = "test_performance_standard_both"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_new_instantaneous_penetration(self):
        """
        Check validation and objective function value of "test_new_instantaneous_penetration" example
        :return:
        """

        scenario_name = "test_new_instantaneous_penetration"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_exog_elev(self):
        """
        Check validation and objective function value of "hydro_system" example
        :return:
        """

        scenario_name = "hydro_system_exog_elev"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_exog_elev_w_travel_time(self):
        """
        Check validation and objective function value of "hydro_system" example
        :return:
        """

        scenario_name = "hydro_system_exog_elev_w_travel_time"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_tx_flow_w_simflow(self):
        """
        Check validation and objective function value of "test_tx_flow_w_simflow" example
        :return:
        """

        scenario_name = "test_tx_flow_w_simflow"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_ra_toolkit_sync_single_year_w_hydro_instead_of_weather_profile(
        self,
    ):
        """
        Check validation and objective function values of
        "ra_toolkit_sync_single_year_w_hydro_instead_of_weather_profile" example
        :return:
        """
        scenario_name = "ra_toolkit_sync_single_year_w_hydro_instead_of_weather_profile"
        self.validate_and_test_example_generic(
            scenario_name=scenario_name, skip_validation=True
        )

    def test_example_2periods_new_build_2zones_loadcomponents(self):
        """
        Check validation and objective function value of
        "2periods_new_build_2zones_loadcomponents" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_loadcomponents"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_nuclear_var_cost_by_timepoint_same(self):
        """
        Check validation and objective function value of
        "2periods_nuclear_var_cost_by_timepoint_same" example
        :return:
        """
        scenario_name = "2periods_nuclear_var_cost_by_timepoint_same"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_nuclear_var_cost_by_timepoint_diff(self):
        """
        Check validation and objective function value of
        "2periods_nuclear_var_cost_by_timepoint_diff" example
        :return:
        """
        scenario_name = "2periods_nuclear_var_cost_by_timepoint_diff"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_storage_wind_as_energy(self):
        """
        Check validation and objective function value of
        "test_w_storage_wind_as_energy" example
        :return:
        """
        scenario_name = "test_w_storage_wind_as_energy"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_hydro_no_reserves(self):
        """
        Check validation and objective function value of
        "test_w_hydro_no_reserves"
        example
        :return:
        """
        scenario_name = "test_w_hydro_no_reserves"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_hydro_as_energy_no_reserves(self):
        """
        Check validation and objective function value of
        "test_w_hydro_as_energy_no_reserves"
        example
        :return:
        """
        scenario_name = "test_w_hydro_as_energy_no_reserves"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_lf(self):
        """
        Check validation and objective function value of
        "test_w_lf" example
        :return:
        """
        scenario_name = "test_w_lf"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_lf_w_demand_charges(self):
        """
        Check validation and objective function value of
        "test_w_lf_w_demand_charges" example
        :return:
        """
        scenario_name = "test_w_lf_w_demand_charges"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_lf_only(self):
        """
        Check validation and objective function value of
        "test_w_lf_only" example
        :return:
        """
        scenario_name = "test_w_lf_only"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_lf_only_and_prices(self):
        """
        Check validation and objective function value of
        "test_w_lf_only_and_prices" example
        :return:
        """
        scenario_name = "test_w_lf_only_and_prices"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_lf_only_energy_potential_limit(self):
        """
        Check validation and objective function value of
        "test_w_lf_only_energy_potential_limit" example
        :return:
        """
        scenario_name = "test_w_lf_only_energy_potential_limit"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_hydro_as_slice_candidate(self):
        """
        Check validation and objective function value of
        "test_w_hydro_as_slice_candidate"
        example
        :return:
        """
        scenario_name = "test_w_hydro_as_slice_candidate"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_energy_products(self):
        """
        Check validation and objective function value of
        "test_w_energy_products" example
        :return:
        """
        scenario_name = "test_w_energy_products"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_energy_products_group_limits(self):
        """
        Check validation and objective function value of
        "test_w_lf_only_and_prices" example
        :return:
        """
        scenario_name = "test_w_energy_products_group_limits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_generic_policy(self):
        """
        Check validation and objective function value of
        "2periods_new_build_generic_policy" example
        :return:
        """
        scenario_name = "2periods_new_build_generic_policy"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_generic_policy_w_tx_losses(self):
        """
        Check validation and objective function value of
        "2periods_new_build_generic_policy_w_tx_losses" example, in which
        transmission losses count against the policy requirement via the
        tx_losses compliance type
        :return:
        """
        scenario_name = "2periods_new_build_generic_policy_w_tx_losses"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_open_data(self):
        """
        Check validation and objective function value of "open_data" example
        :return:
        """

        scenario_name = "open_data"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_exog_elev_w_travel_time_and_max_halfday_flows(self):
        """
        :return:
        """

        scenario_name = "hydro_system_exog_elev_w_travel_time_and_max_halfday_flows"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_w_ramp_limits(self):
        """
        :return:
        """

        scenario_name = "hydro_system_w_ramp_limits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_w_bt_hrz_avl(self):
        """
        :return:
        """

        scenario_name = "test_w_bt_hrz_avl"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_exog_elev_w_gen_ramp_limits(self):
        """ """
        scenario_name = "hydro_system_exog_elev_w_gen_ramp_limits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_exog_elev_w_binding_tmp_flow_max(self):
        """
        Check that per-timepoint max water flow bounds are enforced: peak-hour
        flow caps on the water links limit hydro power output below the load
        level, resulting in unserved energy.
        :return:
        """
        scenario_name = "hydro_system_exog_elev_w_binding_tmp_flow_max"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_exog_elev_w_flow_and_volume_violations(self):
        """
        Check water system violation penalties: a horizon min flow
        requirement, a reservoir target release, and a reservoir minimum
        volume are all set above achievable levels with violations allowed,
        so their respective penalty costs must show up in the objective.
        :return:
        """
        scenario_name = "hydro_system_exog_elev_w_flow_and_volume_violations"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_exog_elev_w_bt_hrz_inflows(self):
        """
        Check horizon-level average exogenous water inflows: same as
        hydro_system_exog_elev, but with part of each node's inflow moved
        from the timepoint-level inputs to horizon-level average inputs
        (spread across the horizon's timepoints, additive with the
        timepoint-level inflows). The totals are unchanged, so this
        scenario must reproduce the hydro_system_exog_elev objective.
        :return:
        """
        scenario_name = "hydro_system_exog_elev_w_bt_hrz_inflows"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_hydro_system_exog_elev_w_hrz_only_inflows(self):
        """
        Check that the timepoint-level inflow inputs can be skipped
        entirely: same as hydro_system_exog_elev, but with all inflows
        specified as horizon-level averages (no water_inflows.tab is
        written for this scenario). The base inflows are constant within
        the day, so the totals are unchanged and this scenario must
        reproduce the hydro_system_exog_elev objective.
        :return:
        """
        scenario_name = "hydro_system_exog_elev_w_hrz_only_inflows"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_dsm_examples(self):
        scenario_name = "dsm_examples"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_hydro_ramp_limits(self):
        """
        Check validation and objective function value of
        "test_w_hydro_ramp_limits" example
        :return:
        """
        scenario_name = "test_w_hydro_ramp_limits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_generic_policy_recs(self):
        """
        Check validation and objective function value of
        "2periods_new_build_rps_recs" example
        :return:
        """
        scenario_name = "2periods_new_build_generic_policy_recs"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_generic_policy_sod_test(self):
        """
        Check validation and objective function value of
        "generic_policy_sod_test" example
        :return:
        """
        scenario_name = "generic_policy_sod_test"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_generic_policy_sod_test_w_annual_rps(self):
        """
        Check validation and objective function value of
        "generic_policy_sod_test_w_annual_rps" example
        :return:
        """
        scenario_name = "generic_policy_sod_test_w_annual_rps"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_markets_w_tmp_total_limits(self):
        """
        Check validation and objective function value of "test" example
        :return:
        """
        scenario_name = "test_markets_w_tmp_total_limits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_markets_w_prd_total_limits(self):
        """
        Check validation and objective function value of "test" example
        :return:
        """
        scenario_name = "test_markets_w_prd_total_limits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_build_storage_losses_limit(self):
        """
        Check validation and objective function value of
        "test_new_build_storage_losses_limit" example
        :return:
        """

        scenario_name = "test_new_build_storage_losses_limit"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_carbon_credits_purchase_limits(self):
        """
        Check validation and objective function value of
        "test_carbon_credits_purchase_limits" example
        :return:
        """

        scenario_name = "test_carbon_credits_purchase_limits"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_inertia_reserves(self):
        """
        Check validation and objective function value of
        "test_new_build_storage_losses_limit" example
        :return:
        """

        scenario_name = "test_inertia_reserves"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_test_w_no_prj_av_sid_specified(self):
        """
        Check validation and objective function value of
        "test_w_no_prj_av_sid_specified" example
        :return:
        """

        scenario_name = "test_w_no_prj_av_sid_specified"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_subproblem_builtin_horizons(self):
        """
        Check validation and objective function value of "test_subproblem_builtin_horizons" example
        :return:
        """
        scenario_name = "test_subproblem_builtin_horizons"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_subproblem_period_builtin_horizons(self):
        """
        Check validation and objective function value of "2periods_subproblem_period_builtin_horizons" example
        :return:
        """
        scenario_name = "2periods_subproblem_period_builtin_horizons"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_single_stage_prod_cost_w_startup_limit(self):
        """
        Check validation and objective function values of
        "single_stage_prod_cost_w_startup_limit" example
        :return:
        """
        scenario_name = "single_stage_prod_cost_w_startup_limit"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_2periods_new_build_2zones_new_build_transmission_stochastic(self):
        """
        Check validation and objective function values of
        "single_stage_prod_cost_w_startup_limit" example
        :return:
        """
        scenario_name = "2periods_new_build_2zones_new_build_transmission_stochastic"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_new_build_gen_var_stor_hyb_as_pwr_grp(self):
        """
        Check validation and objective function value of
        "test_new_build_gen_var_stor_hyb_as_pwr_grp" example
        :return:
        """
        scenario_name = "test_new_build_gen_var_stor_hyb_as_pwr_grp"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_test_w_monthly_prj_derates(self):
        """
        Check validation and objective function value of "test_w_monthly_prj_derates" example
        :return:
        """
        scenario_name = "test_w_monthly_prj_derates"
        self.validate_and_test_example_generic(scenario_name=scenario_name)

    def test_example_ra_toolkit_sync_temporal_structure_overwrite(self):
        """
        Check validation and objective function values of
        "ra_toolkit_sync_temporal_structure_overwrite" example
        :return:
        """
        scenario_name = "ra_toolkit_sync_temporal_structure_overwrite"
        self.validate_and_test_example_generic(
            scenario_name=scenario_name,
            skip_validation=True,
            additional_args=[
                "--temporal_structure_csv_overwrite",
                "--temporal_structure_csv_path",
                f""
                f"{os.path.join(EXAMPLES_DIRECTORY, 'ra_toolkit_sync_temporal_structure_overwrite', 'temporal_structure_overwrite.csv')}",
            ],
        )

    @classmethod
    def tearDownClass(cls):
        os.remove(DB_PATH)
        for temp_file_ext in ["-shm", "-wal"]:
            temp_file = "{}{}".format(DB_PATH, temp_file_ext)
            if os.path.exists(temp_file):
                os.remove(temp_file)


def objective_values_to_float(objective):
    """
    Recursively convert the values of a (possibly nested) objective-value
    dictionary to plain Python floats.
    """
    if isinstance(objective, dict):
        return {k: objective_values_to_float(v) for k, v in objective.items()}
    return float(objective)


def objective_function_overwrite(scenario_name, starting_objective):
    # No overwrites are currently needed; with Cbc as the default solver,
    # this was used for a Python-version-dependent objective function value
    # for one of the examples. Keeping the hook in case it is needed again.
    objective = starting_objective

    return objective


if __name__ == "__main__":
    unittest.main()
