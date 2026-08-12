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
Tests for the per-draw E2E building blocks: draw slicing, per-draw results
deletion, the importer worker's failure handling, resume helpers, and the
WAL journal-mode lifecycle.
"""

import os
import queue
import sqlite3
import tempfile
import unittest

from db.utilities.scenario import delete_scenario_results_for_draw
from gridpath.auxiliary.scenario_chars import (
    build_single_draw_structure,
    iterate_directory_structure,
    iterate_draws,
    ScenarioDirectoryStructure,
    ScenarioStructure,
)
from gridpath.import_scenario_results import IMPORT_STATUS_IMPORTED
from gridpath.run_end_to_end_per_draw import (
    _ImportState,
    get_completed_draw_units,
    get_draw_unit,
    import_draws_worker,
    restore_journal_mode,
    set_wal_journal_mode,
)
from gridpath.scenario_directory_cleanup import get_cleanup_marker_path
from tests.test_scenario_directory_cleanup import (
    write_scenario_root_files,
    write_subproblem_tree,
)

DB_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "db_schema.sql")


def two_by_two_iteration_structure():
    """
    Two weather x two hydro draws, two subproblems each.
    """
    return ScenarioStructure(
        weather_hydro_avail_subproblem_stage_dict={
            1: {1: {0: {1: [1], 2: [1]}}, 2: {0: {1: [1], 2: [1]}}},
            2: {1: {0: {1: [1], 2: [1]}}, 2: {0: {1: [1], 2: [1]}}},
        },
        weather_iteration_flag=True,
        hydro_iteration_flag=True,
        availability_iteration_flag=False,
        subproblem_flag=True,
        stage_flag=False,
    )


def get_all_cells(scenario_structure):
    directory_structure = ScenarioDirectoryStructure(
        scenario_structure
    ).SCENARIO_DIRECTORY_STRUCTURE
    return {
        (
            cell.weather_iteration,
            cell.hydro_iteration,
            cell.availability_iteration,
            cell.subproblem,
            cell.stage,
        )
        for cell in iterate_directory_structure(directory_structure)
    }


class TestDrawSlicing(unittest.TestCase):
    def test_slices_partition_the_full_structure(self):
        """
        The union of the single-draw slices' cells must equal the full
        structure's cells, with no overlap between slices.
        """
        structure = two_by_two_iteration_structure()
        draws = list(iterate_draws(structure))
        self.assertEqual(draws, [(1, 1, 0), (1, 2, 0), (2, 1, 0), (2, 2, 0)])

        all_slice_cells = []
        for draw in draws:
            draw_structure = build_single_draw_structure(structure, *draw)
            slice_cells = get_all_cells(draw_structure)
            # Each slice's cells carry its own draw key
            for cell in slice_cells:
                self.assertEqual(cell[:3], draw)
            all_slice_cells.extend(slice_cells)

        # Partition: no overlap, full coverage
        self.assertEqual(len(all_slice_cells), len(set(all_slice_cells)))
        self.assertEqual(set(all_slice_cells), get_all_cells(structure))

    def test_slice_preserves_flags(self):
        structure = two_by_two_iteration_structure()
        draw_structure = build_single_draw_structure(structure, 1, 2, 0)
        self.assertTrue(draw_structure.WEATHER_ITERATION_FLAG)
        self.assertTrue(draw_structure.HYDRO_ITERATION_FLAG)
        self.assertFalse(draw_structure.AVAILABILITY_ITERATION_FLAG)
        self.assertTrue(draw_structure.SUBPROBLEM_FLAG)
        self.assertFalse(draw_structure.STAGE_FLAG)
        self.assertEqual(draw_structure.N_SUBPROBLEMS, 2)

    def test_get_draw_unit_paths(self):
        structure = two_by_two_iteration_structure()
        unit, cells = get_draw_unit(structure, (1, 2, 0))
        self.assertEqual(unit, os.path.join("weather_iteration_1", "hydro_iteration_2"))
        self.assertEqual(sorted(cells), [(1, 2, 0, 1, 0), (1, 2, 0, 2, 0)])

    def test_get_draw_unit_no_iteration_levels(self):
        structure = ScenarioStructure(
            weather_hydro_avail_subproblem_stage_dict={0: {0: {0: {1: [1]}}}},
            weather_iteration_flag=False,
            hydro_iteration_flag=False,
            availability_iteration_flag=False,
            subproblem_flag=False,
            stage_flag=False,
        )
        unit, cells = get_draw_unit(structure, (0, 0, 0))
        self.assertEqual(unit, "")
        self.assertEqual(cells, [(0, 0, 0, 0, 0)])


class TestDeleteScenarioResultsForDraw(unittest.TestCase):
    def test_deletes_only_the_draw_and_skips_summary_tables(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with open(DB_SCHEMA_PATH, "r") as schema_f:
            conn.executescript(schema_f.read())

        for w in (1, 2):
            # results_scenario keys iterations as integers...
            conn.execute(
                """INSERT INTO results_scenario (scenario_id,
                weather_iteration, hydro_iteration, availability_iteration,
                subproblem_id, stage_id, solver_termination_condition)
                VALUES (1, ?, 0, 0, 1, 1, 'optimal');""",
                (w,),
            )
            # ...while the module results tables key them as the
            # directory-name strings, with NULL for absent levels
            conn.execute(
                """INSERT INTO results_system_costs (scenario_id,
                weather_iteration, hydro_iteration, availability_iteration,
                subproblem_id, stage_id)
                VALUES (1, ?, NULL, NULL, 1, '');""",
                (f"weather_iteration_{w}",),
            )
        # A cross-iteration summary table without the iteration columns
        conn.execute("""INSERT INTO results_system_loss_of_load_metrics_summary
            (scenario_id, LOLH_hrs_per_year) VALUES (1, 0.5);""")
        conn.commit()

        delete_scenario_results_for_draw(
            conn=conn,
            scenario_id=1,
            weather_iteration=1,
            hydro_iteration=0,
            availability_iteration=0,
            weather_iteration_str="weather_iteration_1",
            hydro_iteration_str="",
            availability_iteration_str="",
        )

        remaining = conn.execute(
            "SELECT weather_iteration FROM results_scenario;"
        ).fetchall()
        self.assertEqual(remaining, [(2,)])
        # The string-keyed table's draw-1 row is gone too, draw 2 retained
        remaining_costs = conn.execute(
            "SELECT weather_iteration FROM results_system_costs;"
        ).fetchall()
        self.assertEqual(remaining_costs, [("weather_iteration_2",)])
        n_summary = conn.execute(
            "SELECT COUNT(*) FROM results_system_loss_of_load_metrics_summary;"
        ).fetchone()[0]
        self.assertEqual(n_summary, 1)


class TestImportDrawsWorker(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.scenario_directory = os.path.join(self.tmp_dir.name, "scenario")
        os.makedirs(self.scenario_directory)
        write_scenario_root_files(self.scenario_directory)
        self.db_path = os.path.join(self.tmp_dir.name, "per_draw_test.db")
        conn = sqlite3.connect(self.db_path)
        try:
            with open(DB_SCHEMA_PATH, "r") as schema_f:
                conn.executescript(schema_f.read())
            # The worker's connection enforces foreign keys
            conn.execute(
                "INSERT INTO scenarios (scenario_id, scenario_name) "
                "VALUES (1, 'per_draw_test');"
            )
            conn.commit()
        finally:
            conn.close()

        self.structure = ScenarioStructure(
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

    def run_worker(self, draws, cleanup_after_import=True):
        draw_queue = queue.Queue()
        for draw in draws:
            draw_queue.put((draw, build_single_draw_structure(self.structure, *draw)))
        draw_queue.put(None)
        import_state = _ImportState()
        import_draws_worker(
            draw_queue=draw_queue,
            import_state=import_state,
            db_path=self.db_path,
            scenario_id=1,
            scenario_directory=self.scenario_directory,
            loaded_modules=[],
            import_rule=None,
            cleanup_after_import=cleanup_after_import,
            archive_format=None,
            quiet=True,
        )
        return import_state

    def get_imported_weather_iterations(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return sorted(
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT weather_iteration FROM results_scenario;"
                )
            )
        finally:
            conn.close()

    def test_imports_and_cleans_per_draw(self):
        for w in (1, 2):
            for subproblem in (1, 2):
                write_subproblem_tree(
                    self.scenario_directory,
                    os.path.join(f"weather_iteration_{w}", str(subproblem)),
                )

        import_state = self.run_worker([(1, 0, 0), (2, 0, 0)])

        self.assertIsNone(import_state.error)
        self.assertEqual(
            import_state.statuses,
            {
                (w, 0, 0, subproblem, 0): IMPORT_STATUS_IMPORTED
                for w in (1, 2)
                for subproblem in (1, 2)
            },
        )
        self.assertEqual(self.get_imported_weather_iterations(), [1, 2])
        for w in (1, 2):
            self.assertFalse(
                os.path.exists(
                    os.path.join(self.scenario_directory, f"weather_iteration_{w}")
                )
            )
        completed = get_completed_draw_units(self.scenario_directory)
        self.assertEqual(completed, {"weather_iteration_1", "weather_iteration_2"})

    def test_error_stops_import_and_retains_remaining_draws(self):
        # Draw 1 solved; draw 2 has no results at all -> its import raises
        # and the worker stops, leaving draw 2's directory untouched
        for subproblem in (1, 2):
            write_subproblem_tree(
                self.scenario_directory,
                os.path.join("weather_iteration_1", str(subproblem)),
            )
        os.makedirs(os.path.join(self.scenario_directory, "weather_iteration_2", "1"))

        import_state = self.run_worker([(1, 0, 0), (2, 0, 0)])

        self.assertIsInstance(import_state.error, FileNotFoundError)
        # Draw 1 imported and cleaned; draw 2 not imported, dir retained
        self.assertEqual(self.get_imported_weather_iterations(), [1])
        self.assertFalse(
            os.path.exists(os.path.join(self.scenario_directory, "weather_iteration_1"))
        )
        self.assertTrue(
            os.path.exists(os.path.join(self.scenario_directory, "weather_iteration_2"))
        )
        self.assertEqual(
            get_completed_draw_units(self.scenario_directory),
            {"weather_iteration_1"},
        )

    def test_reimport_is_idempotent(self):
        for subproblem in (1, 2):
            write_subproblem_tree(
                self.scenario_directory,
                os.path.join("weather_iteration_1", str(subproblem)),
            )
        # Simulate a crashed prior import that left partial rows for draw 1
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""INSERT INTO results_scenario (scenario_id,
                weather_iteration, hydro_iteration, availability_iteration,
                subproblem_id, stage_id, solver_termination_condition)
                VALUES (1, 1, 0, 0, 1, 0, 'partial-from-crashed-run');""")
            conn.commit()
        finally:
            conn.close()

        import_state = self.run_worker([(1, 0, 0)], cleanup_after_import=False)

        self.assertIsNone(import_state.error)
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("""SELECT subproblem_id, solver_termination_condition
                FROM results_scenario WHERE weather_iteration = 1
                ORDER BY subproblem_id;""").fetchall()
        finally:
            conn.close()
        # The partial row was replaced, not duplicated
        self.assertEqual(rows, [(1, "optimal"), (2, "optimal")])


class TestResumeHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.scenario_directory = self.tmp_dir.name

    def test_get_completed_draw_units_maps_root_name(self):
        with open(get_cleanup_marker_path(self.scenario_directory), "w") as f:
            f.write(
                "timestamp,action,cleaned_unit\n"
                "t,cleanup,weather_iteration_1\n"
                "t,cleanup,.\n"
            )
        self.assertEqual(
            get_completed_draw_units(self.scenario_directory),
            {"weather_iteration_1", ""},
        )

    def test_get_completed_draw_units_no_marker(self):
        self.assertEqual(get_completed_draw_units(self.scenario_directory), set())


class TestJournalModeLifecycle(unittest.TestCase):
    def test_wal_set_and_restore(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        db_path = os.path.join(tmp_dir.name, "wal_test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (x);")
        conn.commit()
        conn.close()

        prior_mode = set_wal_journal_mode(db_path)
        self.assertEqual(prior_mode.lower(), "delete")
        conn = sqlite3.connect(db_path)
        self.assertEqual(
            conn.execute("PRAGMA journal_mode;").fetchone()[0].lower(), "wal"
        )
        conn.close()

        restore_journal_mode(db_path, prior_mode)
        conn = sqlite3.connect(db_path)
        self.assertEqual(
            conn.execute("PRAGMA journal_mode;").fetchone()[0].lower(), "delete"
        )
        conn.close()
        # No hot sidecars left behind
        self.assertFalse(os.path.exists(db_path + "-wal"))


if __name__ == "__main__":
    unittest.main()
