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
Tests for post-import scenario-directory cleanup/archiving and for the
cleaned-directory marker that blocks the standalone entry points.
"""

import csv
import filecmp
import os
import sqlite3
import tarfile
import tempfile
import unittest

from gridpath import import_scenario_results, run_scenario
from gridpath.auxiliary.scenario_chars import ScenarioStructure
from gridpath.import_scenario_results import (
    IMPORT_STATUS_IMPORTED,
    IMPORT_STATUS_SKIPPED_NOT_SOLVED,
)
from gridpath.scenario_directory_cleanup import (
    ARCHIVE_DIRECTORY_NAME,
    CLEANUP_MARKER_FILENAME,
    check_scenario_directory_not_cleaned,
    cleanup_scenario_directory,
    clear_cleanup_marker,
    get_cleanup_marker_path,
)

DB_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "db_schema.sql")

RETAINED_FIXTURE_FILES = [
    "scenario_description.csv",
    "features.csv",
    "solver_options.csv",
    "units.csv",
    "multi_stage_flag.txt",
    "linked_subproblems_map.csv",
]


def write_scenario_root_files(scenario_directory):
    for fname in RETAINED_FIXTURE_FILES:
        with open(os.path.join(scenario_directory, fname), "w") as f:
            f.write("retained")
    logs_directory = os.path.join(scenario_directory, "logs")
    os.makedirs(logs_directory, exist_ok=True)
    with open(os.path.join(logs_directory, "e2e_test.log"), "w") as f:
        f.write("log")


def write_subproblem_tree(scenario_directory, cell_directory):
    """
    Write a subproblem/stage directory with inputs, results, and logs files,
    the way a solved subproblem leaves it.
    """
    cell_path = os.path.join(scenario_directory, cell_directory)
    for subdirectory, fname, contents in [
        ("inputs", "load_mw.tab", "load"),
        ("results", "termination_condition.txt", "optimal"),
        ("results", "solver_status.txt", "ok"),
        ("results", "objective_function_value.txt", "42.0"),
        ("results", "system_load_zone_timepoint.csv", "results"),
        ("logs", "opt_test.log", "log"),
    ]:
        os.makedirs(os.path.join(cell_path, subdirectory), exist_ok=True)
        with open(os.path.join(cell_path, subdirectory, fname), "w") as f:
            f.write(contents)


def two_weather_draw_structure():
    """
    Two weather draws with two subproblems each.
    """
    return ScenarioStructure(
        weather_hydro_avail_subproblem_stage_dict={
            1: {0: {0: {1: [1], 2: [1]}}},
            2: {0: {0: {1: [1], 2: [1]}}},
        },
        weather_iteration_flag=True,
        hydro_iteration_flag=False,
        availability_iteration_flag=False,
        subproblem_flag=True,
        stage_flag=False,
    )


def all_imported_statuses_for_two_weather_draws():
    return {
        (w, 0, 0, subproblem, 0): IMPORT_STATUS_IMPORTED
        for w in (1, 2)
        for subproblem in (1, 2)
    }


class TestCleanupScenarioDirectory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.scenario_directory = self.tmp_dir.name
        write_scenario_root_files(self.scenario_directory)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def write_two_weather_draws(self):
        for w in (1, 2):
            for subproblem in (1, 2):
                write_subproblem_tree(
                    self.scenario_directory,
                    os.path.join(f"weather_iteration_{w}", str(subproblem)),
                )

    def assert_root_files_retained(self):
        for fname in RETAINED_FIXTURE_FILES:
            self.assertTrue(
                os.path.exists(os.path.join(self.scenario_directory, fname)),
                msg=f"{fname} should have been retained",
            )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.scenario_directory, "logs", "e2e_test.log")
            )
        )

    def read_marker_rows(self):
        with open(get_cleanup_marker_path(self.scenario_directory), "r") as f:
            return list(csv.DictReader(f))

    def test_cleanup_all_draws_imported(self):
        self.write_two_weather_draws()

        cleaned, retained = cleanup_scenario_directory(
            scenario_directory=self.scenario_directory,
            scenario_structure=two_weather_draw_structure(),
            import_statuses=all_imported_statuses_for_two_weather_draws(),
            quiet=True,
        )

        self.assertEqual(
            sorted(cleaned), ["weather_iteration_1", "weather_iteration_2"]
        )
        self.assertEqual(retained, [])
        for w in (1, 2):
            self.assertFalse(
                os.path.exists(
                    os.path.join(self.scenario_directory, f"weather_iteration_{w}")
                )
            )
        self.assert_root_files_retained()
        marker_rows = self.read_marker_rows()
        self.assertEqual(
            sorted(row["cleaned_unit"] for row in marker_rows),
            ["weather_iteration_1", "weather_iteration_2"],
        )
        self.assertTrue(all(row["action"] == "cleanup" for row in marker_rows))

    def test_draw_with_skipped_subproblem_retained(self):
        self.write_two_weather_draws()
        import_statuses = all_imported_statuses_for_two_weather_draws()
        import_statuses[(2, 0, 0, 2, 0)] = IMPORT_STATUS_SKIPPED_NOT_SOLVED

        cleaned, retained = cleanup_scenario_directory(
            scenario_directory=self.scenario_directory,
            scenario_structure=two_weather_draw_structure(),
            import_statuses=import_statuses,
            quiet=True,
        )

        self.assertEqual(cleaned, ["weather_iteration_1"])
        self.assertEqual(retained, ["weather_iteration_2"])
        self.assertFalse(
            os.path.exists(os.path.join(self.scenario_directory, "weather_iteration_1"))
        )
        # The retained draw keeps ALL its files, including the imported
        # subproblem 1's
        for subproblem in (1, 2):
            self.assertTrue(
                os.path.exists(
                    os.path.join(
                        self.scenario_directory,
                        "weather_iteration_2",
                        str(subproblem),
                        "inputs",
                        "load_mw.tab",
                    )
                )
            )
        self.assertEqual(
            [row["cleaned_unit"] for row in self.read_marker_rows()],
            ["weather_iteration_1"],
        )

    def test_no_statuses_cleans_nothing_and_writes_no_marker(self):
        self.write_two_weather_draws()

        cleaned, retained = cleanup_scenario_directory(
            scenario_directory=self.scenario_directory,
            scenario_structure=two_weather_draw_structure(),
            import_statuses={},
            quiet=True,
        )

        self.assertEqual(cleaned, [])
        self.assertEqual(len(retained), 2)
        self.assertFalse(
            os.path.exists(get_cleanup_marker_path(self.scenario_directory))
        )

    def test_none_statuses_raise(self):
        with self.assertRaises(ValueError):
            cleanup_scenario_directory(
                scenario_directory=self.scenario_directory,
                scenario_structure=two_weather_draw_structure(),
                import_statuses=None,
                quiet=True,
            )

    def test_archive_extracts_to_identical_tree(self):
        self.write_two_weather_draws()
        # Snapshot the pre-cleanup tree for comparison
        snapshot_dir = tempfile.TemporaryDirectory()
        self.addCleanup(snapshot_dir.cleanup)
        for w in (1, 2):
            unit = f"weather_iteration_{w}"
            os.makedirs(os.path.join(snapshot_dir.name, unit))
            os.rmdir(os.path.join(snapshot_dir.name, unit))
            import shutil

            shutil.copytree(
                os.path.join(self.scenario_directory, unit),
                os.path.join(snapshot_dir.name, unit),
            )

        cleaned, retained = cleanup_scenario_directory(
            scenario_directory=self.scenario_directory,
            scenario_structure=two_weather_draw_structure(),
            import_statuses=all_imported_statuses_for_two_weather_draws(),
            archive_format="tar",
            quiet=True,
        )

        self.assertEqual(len(cleaned), 2)
        archive_directory = os.path.join(
            self.scenario_directory, ARCHIVE_DIRECTORY_NAME
        )
        extract_dir = tempfile.TemporaryDirectory()
        self.addCleanup(extract_dir.cleanup)
        for w in (1, 2):
            unit = f"weather_iteration_{w}"
            archive_path = os.path.join(archive_directory, f"{unit}.tar")
            self.assertTrue(os.path.exists(archive_path))
            # No leftover partial archives
            self.assertFalse(os.path.exists(archive_path + ".part"))
            self.assertFalse(
                os.path.exists(os.path.join(self.scenario_directory, unit))
            )
            with tarfile.open(archive_path, "r") as tar:
                tar.extractall(path=extract_dir.name, filter="data")

        # The extracted tree must match the pre-cleanup snapshot exactly
        comparison = filecmp.dircmp(snapshot_dir.name, extract_dir.name)
        self.assert_trees_identical(comparison)
        marker_rows = self.read_marker_rows()
        self.assertTrue(all(row["action"] == "archive" for row in marker_rows))

    def assert_trees_identical(self, comparison):
        self.assertEqual(comparison.left_only, [])
        self.assertEqual(comparison.right_only, [])
        self.assertEqual(comparison.diff_files, [])
        self.assertEqual(comparison.funny_files, [])
        for sub_comparison in comparison.subdirs.values():
            self.assert_trees_identical(sub_comparison)

    def test_root_unit_cleanup_when_no_iteration_levels(self):
        structure = ScenarioStructure(
            weather_hydro_avail_subproblem_stage_dict={0: {0: {0: {1: [1], 2: [1]}}}},
            weather_iteration_flag=False,
            hydro_iteration_flag=False,
            availability_iteration_flag=False,
            subproblem_flag=True,
            stage_flag=False,
        )
        for subproblem in (1, 2):
            write_subproblem_tree(self.scenario_directory, str(subproblem))

        cleaned, retained = cleanup_scenario_directory(
            scenario_directory=self.scenario_directory,
            scenario_structure=structure,
            import_statuses={
                (0, 0, 0, 1, 0): IMPORT_STATUS_IMPORTED,
                (0, 0, 0, 2, 0): IMPORT_STATUS_IMPORTED,
            },
            quiet=True,
        )

        self.assertEqual(cleaned, [""])
        for subproblem in (1, 2):
            self.assertFalse(
                os.path.exists(os.path.join(self.scenario_directory, str(subproblem)))
            )
        self.assert_root_files_retained()
        self.assertEqual(
            [row["cleaned_unit"] for row in self.read_marker_rows()], ["."]
        )

    def test_empty_iteration_parents_pruned(self):
        structure = ScenarioStructure(
            weather_hydro_avail_subproblem_stage_dict={
                1: {1: {0: {1: [1]}}, 2: {0: {1: [1]}}}
            },
            weather_iteration_flag=True,
            hydro_iteration_flag=True,
            availability_iteration_flag=False,
            subproblem_flag=False,
            stage_flag=False,
        )
        for h in (1, 2):
            write_subproblem_tree(
                self.scenario_directory,
                os.path.join("weather_iteration_1", f"hydro_iteration_{h}"),
            )

        # First clean only hydro draw 1: weather_iteration_1 must survive
        # (it still holds hydro_iteration_2)
        import_statuses = {
            (1, 1, 0, 0, 0): IMPORT_STATUS_IMPORTED,
            (1, 2, 0, 0, 0): IMPORT_STATUS_SKIPPED_NOT_SOLVED,
        }
        cleanup_scenario_directory(
            scenario_directory=self.scenario_directory,
            scenario_structure=structure,
            import_statuses=import_statuses,
            quiet=True,
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    self.scenario_directory,
                    "weather_iteration_1",
                    "hydro_iteration_2",
                )
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.scenario_directory,
                    "weather_iteration_1",
                    "hydro_iteration_1",
                )
            )
        )

        # Now clean the remaining draw: the empty weather_iteration_1 parent
        # goes too
        import_statuses[(1, 2, 0, 0, 0)] = IMPORT_STATUS_IMPORTED
        cleanup_scenario_directory(
            scenario_directory=self.scenario_directory,
            scenario_structure=structure,
            import_statuses=import_statuses,
            quiet=True,
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.scenario_directory, "weather_iteration_1"))
        )


class TestCleanedDirectoryMarkerGuards(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        # addCleanup rather than tearDown: cleanups run LIFO, so database
        # connections the tests register afterwards are closed BEFORE the
        # directory is removed (Windows can't delete open files)
        self.addCleanup(self.tmp_dir.cleanup)
        self.scenario_location = self.tmp_dir.name
        self.scenario_name = "guard_test_scenario"
        self.scenario_directory = os.path.join(
            self.scenario_location, self.scenario_name
        )
        os.makedirs(self.scenario_directory)

    def write_marker(self):
        with open(get_cleanup_marker_path(self.scenario_directory), "w") as f:
            f.write("timestamp,action,cleaned_unit\n")

    def test_check_raises_only_when_marker_present(self):
        # No marker: no exception
        check_scenario_directory_not_cleaned(
            scenario_directory=self.scenario_directory, attempted_action="Testing."
        )
        self.write_marker()
        with self.assertRaises(RuntimeError):
            check_scenario_directory_not_cleaned(
                scenario_directory=self.scenario_directory,
                attempted_action="Testing.",
            )
        # Clearing the marker unblocks
        clear_cleanup_marker(scenario_directory=self.scenario_directory)
        check_scenario_directory_not_cleaned(
            scenario_directory=self.scenario_directory, attempted_action="Testing."
        )

    def test_import_refuses_on_cleaned_directory_before_deleting_results(self):
        """
        The destructive-reimport guard: importing from a cleaned directory
        must refuse BEFORE deleting the scenario's database results.
        """
        db_path = os.path.join(self.tmp_dir.name, "guard_test.db")
        conn = sqlite3.connect(db_path)
        self.addCleanup(conn.close)
        with open(DB_SCHEMA_PATH, "r") as schema_f:
            conn.executescript(schema_f.read())
        conn.execute(
            "INSERT INTO scenarios (scenario_id, scenario_name) VALUES (1, ?);",
            (self.scenario_name,),
        )
        conn.execute("""INSERT INTO results_scenario (scenario_id, weather_iteration,
            hydro_iteration, availability_iteration, subproblem_id, stage_id,
            solver_termination_condition) VALUES (1, 0, 0, 0, 1, 1, 'optimal');""")
        conn.commit()

        self.write_marker()

        with self.assertRaises(RuntimeError):
            import_scenario_results.main(
                [
                    "--database",
                    db_path,
                    "--scenario",
                    self.scenario_name,
                    "--scenario_location",
                    self.scenario_location,
                    "--quiet",
                ]
            )

        # The previously imported results must have survived the refusal
        n_results = conn.execute(
            "SELECT COUNT(*) FROM results_scenario WHERE scenario_id = 1;"
        ).fetchone()[0]
        self.assertEqual(n_results, 1)

    def test_run_scenario_refuses_on_cleaned_directory(self):
        self.write_marker()
        with self.assertRaises(RuntimeError):
            run_scenario.main(
                [
                    "--scenario",
                    self.scenario_name,
                    "--scenario_location",
                    self.scenario_location,
                    "--quiet",
                ]
            )


if __name__ == "__main__":
    unittest.main()
