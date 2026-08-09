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
Tests for the per-subproblem/stage import statuses returned by
import_scenario_results, including the warning on none/partial imports and
the handling of missing solver status files with --ignore_incomplete.
"""

import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
import warnings

from gridpath.auxiliary.import_export_rules import import_export_rules
from gridpath.auxiliary.scenario_chars import ScenarioStructure
from gridpath.import_scenario_results import (
    IMPORT_STATUS_IMPORTED,
    IMPORT_STATUS_SKIPPED_NOT_SOLVED,
    IMPORT_STATUS_SKIPPED_SOLVER_STATUS_NOT_OK,
    IMPORT_STATUS_SKIPPED_BY_IMPORT_RULE,
    import_scenario_results_into_database,
    warn_on_import_gaps,
)

DB_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "db_schema.sql")


def write_cell_results_files(
    scenario_directory,
    cell_directory,
    termination_condition="optimal",
    solver_status="ok",
    objective_function_value="42.0",
):
    """
    Write a cell's results directory; pass None for a file to omit it.
    """
    results_directory = os.path.join(scenario_directory, cell_directory, "results")
    os.makedirs(results_directory, exist_ok=True)
    for fname, contents in [
        ("termination_condition.txt", termination_condition),
        ("solver_status.txt", solver_status),
        ("objective_function_value.txt", objective_function_value),
    ]:
        if contents is not None:
            with open(os.path.join(results_directory, fname), "w") as f:
                f.write(contents)


def two_subproblem_structure():
    return ScenarioStructure(
        weather_hydro_avail_subproblem_stage_dict={0: {0: {0: {1: [1], 2: [1]}}}},
        weather_iteration_flag=False,
        hydro_iteration_flag=False,
        availability_iteration_flag=False,
        subproblem_flag=True,
        stage_flag=False,
    )


class TestImportScenarioResultsStatuses(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.scenario_directory = self.tmp_dir.name
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_PATH, "r") as schema_f:
            self.conn.executescript(schema_f.read())

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def write_cell_results(self, cell_directory, **kwargs):
        write_cell_results_files(self.scenario_directory, cell_directory, **kwargs)

    def import_results(
        self, scenario_structure, import_rule=None, ignore_incomplete=False
    ):
        return import_scenario_results_into_database(
            import_rule=import_rule,
            loaded_modules=[],
            scenario_id=1,
            scenario_structure=scenario_structure,
            db=self.conn,
            scenario_directory=self.scenario_directory,
            ignore_incomplete=ignore_incomplete,
            quiet=True,
        )

    def get_results_scenario_rows(self):
        return self.conn.execute("""SELECT subproblem_id, solver_termination_condition,
            objective_function_value
            FROM results_scenario ORDER BY subproblem_id;""").fetchall()

    def test_all_cells_imported(self):
        self.write_cell_results("1")
        self.write_cell_results("2")

        import_statuses = self.import_results(two_subproblem_structure())

        self.assertEqual(
            import_statuses,
            {
                (0, 0, 0, 1, 0): IMPORT_STATUS_IMPORTED,
                (0, 0, 0, 2, 0): IMPORT_STATUS_IMPORTED,
            },
        )
        self.assertEqual(
            self.get_results_scenario_rows(),
            [(1, "optimal", 42.0), (2, "optimal", 42.0)],
        )

    def test_solver_status_not_ok_skipped(self):
        self.write_cell_results("1")
        self.write_cell_results(
            "2",
            termination_condition="infeasible",
            solver_status="warning",
            objective_function_value=None,
        )

        import_statuses = self.import_results(two_subproblem_structure())

        self.assertEqual(
            import_statuses,
            {
                (0, 0, 0, 1, 0): IMPORT_STATUS_IMPORTED,
                (0, 0, 0, 2, 0): IMPORT_STATUS_SKIPPED_SOLVER_STATUS_NOT_OK,
            },
        )
        # Termination condition recorded, but no objective for subproblem 2
        self.assertEqual(
            self.get_results_scenario_rows(),
            [(1, "optimal", 42.0), (2, "infeasible", None)],
        )

    def test_missing_files_raise_without_ignore_incomplete(self):
        self.write_cell_results("1")
        # Subproblem 2 was never solved: no results directory at all

        with self.assertRaises(FileNotFoundError):
            self.import_results(two_subproblem_structure())

    def test_first_cell_not_solved_with_ignore_incomplete(self):
        # Subproblem 1 was never solved; subproblem 2 solved fine
        self.write_cell_results("2")

        # Not assertWarns, which touches __warningregistry__ on all loaded
        # modules and trips Pyomo's lazy-import proxies
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import_statuses = self.import_results(
                two_subproblem_structure(), ignore_incomplete=True
            )
        self.assertTrue(any("not found" in str(w.message) for w in caught))

        self.assertEqual(
            import_statuses,
            {
                (0, 0, 0, 1, 0): IMPORT_STATUS_SKIPPED_NOT_SOLVED,
                (0, 0, 0, 2, 0): IMPORT_STATUS_IMPORTED,
            },
        )
        self.assertEqual(
            self.get_results_scenario_rows(),
            [
                (1, "termination condition file not found", None),
                (2, "optimal", 42.0),
            ],
        )

    def test_stale_solver_status_not_reused_across_cells(self):
        # Subproblem 1 solved "ok"; subproblem 2 has a termination condition
        # file but no solver status file. The import must not reuse
        # subproblem 1's "ok" status for subproblem 2 (and must not attempt
        # to read subproblem 2's nonexistent objective function file).
        self.write_cell_results("1")
        self.write_cell_results(
            "2",
            termination_condition="unknown",
            solver_status=None,
            objective_function_value=None,
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import_statuses = self.import_results(
                two_subproblem_structure(), ignore_incomplete=True
            )
        self.assertTrue(any("not found" in str(w.message) for w in caught))

        self.assertEqual(
            import_statuses,
            {
                (0, 0, 0, 1, 0): IMPORT_STATUS_IMPORTED,
                (0, 0, 0, 2, 0): IMPORT_STATUS_SKIPPED_NOT_SOLVED,
            },
        )
        self.assertEqual(
            self.get_results_scenario_rows(),
            [(1, "optimal", 42.0), (2, "unknown", None)],
        )

    def test_skipped_by_import_rule(self):
        self.write_cell_results("1")
        self.write_cell_results("2")

        import_export_rules["always_false_test_rule"] = {
            "import": lambda results_directory, quiet: False
        }
        self.addCleanup(import_export_rules.pop, "always_false_test_rule")

        import_statuses = self.import_results(
            two_subproblem_structure(), import_rule="always_false_test_rule"
        )

        self.assertEqual(
            import_statuses,
            {
                (0, 0, 0, 1, 0): IMPORT_STATUS_SKIPPED_BY_IMPORT_RULE,
                (0, 0, 0, 2, 0): IMPORT_STATUS_SKIPPED_BY_IMPORT_RULE,
            },
        )
        # The import rule gates module results only; the termination
        # condition and objective function value are still recorded
        self.assertEqual(
            self.get_results_scenario_rows(),
            [(1, "optimal", 42.0), (2, "optimal", 42.0)],
        )

    def test_directory_level_combinations(self):
        # Any combination of the five directory levels must work. The
        # expected directory paths are written out by hand here to pin the
        # on-disk layout convention: iteration levels appear as
        # weather_iteration_N/hydro_iteration_N/availability_iteration_N
        # directories when the corresponding flag is set, the subproblem
        # directory appears if there are multiple subproblems or any stages,
        # and the stage directory only when there are stages. Absent levels
        # are 0 in the status keys.
        cases = [
            (
                "single_subproblem_no_levels",
                {0: {0: {0: {1: [1]}}}},
                (False, False, False, False, False),
                {"": (0, 0, 0, 0, 0)},
            ),
            (
                "subproblems_only",
                {0: {0: {0: {1: [1], 2: [1]}}}},
                (False, False, False, True, False),
                {"1": (0, 0, 0, 1, 0), "2": (0, 0, 0, 2, 0)},
            ),
            (
                "stages_with_single_subproblem",
                {0: {0: {0: {1: [1, 2]}}}},
                (False, False, False, False, True),
                {
                    os.path.join("1", "1"): (0, 0, 0, 1, 1),
                    os.path.join("1", "2"): (0, 0, 0, 1, 2),
                },
            ),
            (
                "subproblems_and_stages",
                {0: {0: {0: {1: [1, 2], 2: [1]}}}},
                (False, False, False, True, True),
                {
                    os.path.join("1", "1"): (0, 0, 0, 1, 1),
                    os.path.join("1", "2"): (0, 0, 0, 1, 2),
                    os.path.join("2", "1"): (0, 0, 0, 2, 1),
                },
            ),
            (
                "hydro_iterations_only",
                {0: {5: {0: {1: [1]}}, 7: {0: {1: [1]}}}},
                (False, True, False, False, False),
                {
                    "hydro_iteration_5": (0, 5, 0, 0, 0),
                    "hydro_iteration_7": (0, 7, 0, 0, 0),
                },
            ),
            (
                "availability_iterations_and_subproblems",
                {0: {0: {9: {1: [1], 2: [1]}}}},
                (False, False, True, True, False),
                {
                    os.path.join("availability_iteration_9", "1"): (0, 0, 9, 1, 0),
                    os.path.join("availability_iteration_9", "2"): (0, 0, 9, 2, 0),
                },
            ),
            (
                "all_five_levels",
                {1: {2: {3: {4: [5, 6]}}}},
                (True, True, True, True, True),
                {
                    os.path.join(
                        "weather_iteration_1",
                        "hydro_iteration_2",
                        "availability_iteration_3",
                        "4",
                        "5",
                    ): (1, 2, 3, 4, 5),
                    os.path.join(
                        "weather_iteration_1",
                        "hydro_iteration_2",
                        "availability_iteration_3",
                        "4",
                        "6",
                    ): (1, 2, 3, 4, 6),
                },
            ),
        ]

        for name, structure_dict, flags, expected_cells_by_dir in cases:
            weather_flag, hydro_flag, availability_flag, subproblem_flag, stage_flag = (
                flags
            )
            structure = ScenarioStructure(
                weather_hydro_avail_subproblem_stage_dict=structure_dict,
                weather_iteration_flag=weather_flag,
                hydro_iteration_flag=hydro_flag,
                availability_iteration_flag=availability_flag,
                subproblem_flag=subproblem_flag,
                stage_flag=stage_flag,
            )
            with self.subTest(case=name):
                with tempfile.TemporaryDirectory() as scenario_directory:
                    conn = sqlite3.connect(":memory:")
                    try:
                        with open(DB_SCHEMA_PATH, "r") as schema_f:
                            conn.executescript(schema_f.read())
                        for cell_directory in expected_cells_by_dir:
                            write_cell_results_files(scenario_directory, cell_directory)

                        import_statuses = import_scenario_results_into_database(
                            import_rule=None,
                            loaded_modules=[],
                            scenario_id=1,
                            scenario_structure=structure,
                            db=conn,
                            scenario_directory=scenario_directory,
                            ignore_incomplete=False,
                            quiet=True,
                        )

                        self.assertEqual(
                            import_statuses,
                            {
                                cell: IMPORT_STATUS_IMPORTED
                                for cell in expected_cells_by_dir.values()
                            },
                        )
                        # The status keys must match the results_scenario rows
                        db_cells = conn.execute(
                            """SELECT weather_iteration, hydro_iteration,
                            availability_iteration, subproblem_id, stage_id
                            FROM results_scenario;"""
                        ).fetchall()
                        self.assertEqual(
                            set(db_cells), set(expected_cells_by_dir.values())
                        )
                    finally:
                        conn.close()


class TestWarnOnImportGaps(unittest.TestCase):
    def get_warning_output(self, import_statuses):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            warn_on_import_gaps(import_statuses)

        return captured.getvalue()

    def test_no_warning_when_all_imported(self):
        output = self.get_warning_output(
            {
                (0, 0, 0, 1, 0): IMPORT_STATUS_IMPORTED,
                (0, 0, 0, 2, 0): IMPORT_STATUS_IMPORTED,
            }
        )
        self.assertEqual(output, "")

    def test_warning_on_partial_import(self):
        output = self.get_warning_output(
            {
                (0, 0, 0, 1, 0): IMPORT_STATUS_IMPORTED,
                (0, 0, 0, 2, 0): IMPORT_STATUS_SKIPPED_SOLVER_STATUS_NOT_OK,
            }
        )
        self.assertIn("WARNING", output)
        self.assertIn("only 1 of 2", output)
        self.assertIn(IMPORT_STATUS_SKIPPED_SOLVER_STATUS_NOT_OK, output)
        self.assertIn("(0, 0, 0, 2, 0)", output)

    def test_warning_on_no_imports(self):
        output = self.get_warning_output(
            {
                (0, 0, 0, 1, 0): IMPORT_STATUS_SKIPPED_NOT_SOLVED,
                (0, 0, 0, 2, 0): IMPORT_STATUS_SKIPPED_NOT_SOLVED,
            }
        )
        self.assertIn("WARNING", output)
        self.assertIn("NONE", output)
        self.assertIn("no results for this scenario", output)

    def test_example_cells_capped(self):
        import_statuses = {
            (0, 0, 0, subproblem, 0): IMPORT_STATUS_SKIPPED_NOT_SOLVED
            for subproblem in range(1, 21)
        }
        output = self.get_warning_output(import_statuses)
        self.assertIn("and 10 more", output)


if __name__ == "__main__":
    unittest.main()
