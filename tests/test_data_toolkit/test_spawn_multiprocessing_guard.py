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
Tests for the Windows spawn-guard mechanism used in data toolkit pool functions.

Background
----------
On Windows (and with spawn start method on Linux/macOS), multiprocessing Pool
workers re-import __main__ before running their target function. Without a guard
this causes:
  - Recursive pool creation → RuntimeError bootstrapping phase
  - Open SQLite handles inherited into workers → PermissionError WinError 32
  - Module-level side effects (e.g. database deletion) running in every worker

The guard used across the pool functions is:

    if current_process().name != "MainProcess":
        return

parent_process() was insufficient: it is set inside BaseProcess._bootstrap(),
which runs *after* prepare() has already re-imported __main__, so it is still
None at the point the guard is evaluated. current_process().name is set earlier,
during prepare(), before __main__ is re-imported, making it a reliable guard.
"""

import tempfile
import unittest
from multiprocessing import current_process, get_context
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# Module-level worker functions — spawn Process targets must be picklable,
# which requires them to be importable by name (i.e. module-level, not local).
# ---------------------------------------------------------------------------


def _report_name(queue):
    """Report current_process().name from inside a spawn worker."""
    from multiprocessing import current_process

    queue.put(current_process().name)


def _run_pool_fn_in_worker(queue):
    """Call the pool function from inside a spawn worker and report whether
    get_context() was invoked.  Uses mocks so no database is required."""
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from multiprocessing import get_context

    dummy_units = pd.DataFrame(
        {
            "timeseries_name": ["ts1"],
            "project": ["proj1"],
            "unit": ["unit1"],
            "unit_weight": [1.0],
        }
    )

    context_calls = []

    def tracking_get_context(method):
        context_calls.append(method)
        # Return a real context so the test doesn't hang if the guard fails.
        return get_context(method)

    mock_conn = MagicMock()
    mock_conn.close = MagicMock()

    with (
        patch(
            "data_toolkit.project.create_monte_carlo_gen_input_csvs_common"
            ".connect_to_database",
            return_value=mock_conn,
        ),
        patch(
            "data_toolkit.project.create_monte_carlo_gen_input_csvs_common"
            ".pd.read_sql",
            return_value=dummy_units,
        ),
        patch(
            "data_toolkit.project.create_monte_carlo_gen_input_csvs_common"
            ".get_context",
            side_effect=tracking_get_context,
        ),
    ):
        from data_toolkit.project.create_monte_carlo_gen_input_csvs_common import (
            get_monte_carlo_timeseries_project_pool_and_make_profile_csvs,
        )
        import tempfile

        get_monte_carlo_timeseries_project_pool_and_make_profile_csvs(
            db_path="unused.db",
            weather_bins_id=1,
            weather_draws_id=1,
            output_directory=tempfile.mkdtemp(),
            profile_scenario_id=1,
            profile_scenario_name="guard_test",
            stage_id=1,
            overwrite=False,
            n_parallel_projects=4,
            units_table="raw_data_var_project_units",
            param_name="cap_factor",
            raw_data_table="raw_data_var_profiles",
            study_year=2026,
            print_default_values=True,
            default_value=None,
        )

    queue.put(context_calls)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestSpawnGuard(unittest.TestCase):
    """
    Unit tests for the spawn re-entry guard in data toolkit pool functions.
    These tests require no database and run quickly.
    """

    # ------------------------------------------------------------------
    # Guard mechanism tests
    # ------------------------------------------------------------------

    def test_main_process_name_is_mainprocess(self):
        """current_process().name == 'MainProcess' in the test runner.
        The guard must NOT fire here, so normal pool creation proceeds."""
        self.assertEqual(current_process().name, "MainProcess")

    def test_spawn_worker_name_is_not_mainprocess(self):
        """Spawn workers receive a name other than 'MainProcess' before
        __main__ is re-imported, so the guard fires before any pool is
        created."""
        ctx = get_context("spawn")
        q = ctx.Queue()

        p = ctx.Process(target=_report_name, args=(q,))
        p.start()
        p.join(timeout=30)

        self.assertEqual(p.exitcode, 0, "Spawn worker process exited with error")
        self.assertFalse(q.empty(), "Worker did not report its process name")
        name = q.get_nowait()
        self.assertNotEqual(
            name,
            "MainProcess",
            f"Spawn worker name was {name!r} — expected anything other than "
            "'MainProcess' so the current_process().name guard fires when "
            "__main__ is re-imported during worker bootstrapping.",
        )

    # ------------------------------------------------------------------
    # Functional guard test: pool function skips pool creation in worker
    # ------------------------------------------------------------------

    def test_pool_function_guard_skips_pool_creation_in_worker(self):
        """get_monte_carlo_timeseries_project_pool_and_make_profile_csvs
        returns before calling get_context() when executed inside a spawn
        worker (the guard fires on current_process().name != 'MainProcess')."""
        ctx = get_context("spawn")
        q = ctx.Queue()

        p = ctx.Process(target=_run_pool_fn_in_worker, args=(q,))
        p.start()
        p.join(timeout=60)

        self.assertEqual(
            p.exitcode, 0, "Worker process crashed — check stderr for traceback"
        )
        self.assertFalse(q.empty(), "Worker did not report context_calls")
        context_calls = q.get_nowait()
        self.assertEqual(
            context_calls,
            [],
            "get_context() was called inside a spawn worker — the "
            "current_process().name guard did not fire. Pool would have been "
            "created during worker bootstrapping, causing RuntimeError.",
        )


if __name__ == "__main__":
    unittest.main()
