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
Tests for the loud non-optimal-solve flagging: the per-cell warning printed
at solve time and the end-of-run summary scanned from the
termination-condition files on disk -- both deliberately printed regardless
of the --quiet setting (results CSVs are not exported/imported when the
solver status is not 'ok', so a non-optimal subproblem is otherwise easy to
miss).
"""

import contextlib
import io
import os
import tempfile
import unittest
from argparse import Namespace

from gridpath.auxiliary.scenario_chars import ScenarioStructure
from gridpath.common_functions import RESULTS_EXPORT_COMPLETE_FILENAME
from gridpath.run_scenario import (
    describe_solve_cell,
    print_solve_status_warning,
    Results,
    save_results,
    warn_on_non_optimal_solves,
)


class TestDescribeSolveCell(unittest.TestCase):
    def test_iteration_directories_and_labeled_subproblem_stage(self):
        self.assertEqual(
            describe_solve_cell(
                weather_iteration="weather_iteration_1",
                hydro_iteration="",
                availability_iteration="availability_iteration_3",
                subproblem="4",
                stage="5",
            ),
            "weather_iteration_1, availability_iteration_3, subproblem 4, stage 5",
        )

    def test_single_subproblem_scenario(self):
        self.assertEqual(
            describe_solve_cell(
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
            ),
            "the scenario's single subproblem",
        )


class TestPrintSolveStatusWarning(unittest.TestCase):
    def get_warning_output(self, solver_status, termination_condition):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            print_solve_status_warning(
                solver_status=solver_status,
                termination_condition=termination_condition,
                weather_iteration="weather_iteration_1",
                hydro_iteration="",
                availability_iteration="",
                subproblem="2",
                stage="",
            )

        return captured.getvalue()

    def test_silent_when_optimal(self):
        self.assertEqual(self.get_warning_output("ok", "optimal"), "")

    def test_ok_but_not_optimal(self):
        output = self.get_warning_output("ok", "maxTimeLimit")
        self.assertIn("WARNING", output)
        self.assertIn("NOT OPTIMAL", output)
        self.assertIn("maxTimeLimit", output)
        self.assertIn("weather_iteration_1, subproblem 2", output)
        # Results ARE exported/imported for ok-status non-optimal solves
        self.assertIn("still be exported and imported", output)

    def test_solver_status_not_ok(self):
        output = self.get_warning_output("warning", "infeasible")
        self.assertIn("WARNING", output)
        self.assertIn("no valid solution", output)
        self.assertIn("infeasible", output)
        self.assertIn("weather_iteration_1, subproblem 2", output)
        self.assertIn("results_scenario", output)


class TestSaveResultsSolverStatusNotOk(unittest.TestCase):
    """
    The solver-status-not-ok path of save_results: no results are exported,
    but the warning must print even under --quiet, and the status files and
    the export-complete sentinel must still be written.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.scenario_directory = self.tmp_dir.name

    def tearDown(self):
        self.tmp_dir.cleanup()

    def call_save_results(self):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            save_results(
                scenario_directory=self.scenario_directory,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
                multi_stage=None,
                instance=None,
                results=Results(
                    solver_status="warning", termination_condition="infeasible"
                ),
                dynamic_components=None,
                parsed_arguments=Namespace(quiet=True),
            )

        return captured.getvalue()

    def test_warning_printed_despite_quiet_and_status_files_written(self):
        output = self.call_save_results()

        self.assertIn("WARNING", output)
        self.assertIn("infeasible", output)

        results_directory = os.path.join(self.scenario_directory, "results")
        with open(os.path.join(results_directory, "solver_status.txt")) as f:
            self.assertEqual(f.read(), "warning")
        with open(os.path.join(results_directory, "termination_condition.txt")) as f:
            self.assertEqual(f.read(), "infeasible")
        # The export-complete sentinel is written for non-ok solves too
        # (the "export" -- nothing, for a not-ok solve -- did complete)
        self.assertTrue(
            os.path.exists(
                os.path.join(results_directory, RESULTS_EXPORT_COMPLETE_FILENAME)
            )
        )
        # No results CSVs
        self.assertEqual(
            sorted(os.listdir(results_directory)),
            sorted(
                [
                    "solver_status.txt",
                    "termination_condition.txt",
                    RESULTS_EXPORT_COMPLETE_FILENAME,
                ]
            ),
        )

    def test_infeasible_linked_subproblems_raise(self):
        with open(
            os.path.join(self.scenario_directory, "linked_subproblems_map.csv"), "w"
        ) as f:
            f.write("")

        with self.assertRaisesRegex(Exception, "linked subproblem"):
            self.call_save_results()


def three_subproblem_structure():
    return ScenarioStructure(
        weather_hydro_avail_subproblem_stage_dict={
            0: {0: {0: {1: [1], 2: [1], 3: [1]}}}
        },
        weather_iteration_flag=False,
        hydro_iteration_flag=False,
        availability_iteration_flag=False,
        subproblem_flag=True,
        stage_flag=False,
    )


class TestWarnOnNonOptimalSolves(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.scenario_directory = self.tmp_dir.name

    def tearDown(self):
        self.tmp_dir.cleanup()

    def write_termination_condition(self, cell_directory, termination_condition):
        results_directory = os.path.join(
            self.scenario_directory, cell_directory, "results"
        )
        os.makedirs(results_directory, exist_ok=True)
        with open(
            os.path.join(results_directory, "termination_condition.txt"), "w"
        ) as f:
            f.write(termination_condition)

    def get_summary(self):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            non_optimal_cells = warn_on_non_optimal_solves(
                scenario_directory=self.scenario_directory,
                scenario_structure=three_subproblem_structure(),
            )

        return non_optimal_cells, captured.getvalue()

    def test_silent_when_all_optimal(self):
        for cell_directory in ["1", "2", "3"]:
            self.write_termination_condition(cell_directory, "optimal")

        non_optimal_cells, output = self.get_summary()

        self.assertEqual(non_optimal_cells, {})
        self.assertEqual(output, "")

    def test_summary_groups_by_condition(self):
        self.write_termination_condition("1", "optimal")
        self.write_termination_condition("2", "infeasible")
        # Subproblem 3 was never solved: no termination condition file

        non_optimal_cells, output = self.get_summary()

        self.assertEqual(
            non_optimal_cells,
            {
                (0, 0, 0, 2, 0): "infeasible",
                (0, 0, 0, 3, 0): "not solved (no termination condition file)",
            },
        )
        self.assertIn("WARNING", output)
        self.assertIn("2 of 3", output)
        self.assertIn("did not solve to optimality", output)
        self.assertIn("infeasible: 1 subproblem/stage(s)", output)
        self.assertIn("(0, 0, 0, 2, 0)", output)
        self.assertIn("not solved (no termination condition file)", output)
        self.assertIn("(0, 0, 0, 3, 0)", output)


if __name__ == "__main__":
    unittest.main()
