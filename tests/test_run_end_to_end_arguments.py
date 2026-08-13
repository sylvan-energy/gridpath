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
Tests for run_end_to_end's argument validation: the per-draw mode and
cleanup/archive flag combinations that must be rejected at parse time.
"""

import contextlib
import io
import unittest

from gridpath import run_end_to_end

BASE_ARGS = ["--database", "irrelevant.db", "--scenario", "irrelevant"]


class TestRunEndToEndArgumentValidation(unittest.TestCase):
    def assert_rejected(self, additional_args):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                run_end_to_end.parse_arguments(BASE_ARGS + additional_args)

    def test_valid_combinations_accepted(self):
        for additional_args in [
            [],
            ["--per_draw_lifecycle"],
            ["--per_draw_lifecycle", "--single_draw", "812", "0", "1"],
            ["--per_draw_lifecycle", "--cleanup_after_import"],
            [
                "--per_draw_lifecycle",
                "--archive_after_import",
                "--cleanup_granularity",
                "subproblem",
            ],
            ["--per_draw_lifecycle", "--skip_process_results"],
            [
                "--per_draw_lifecycle",
                "--n_draws_per_solve_batch",
                "10",
                "--n_parallel_solve",
                "10",
            ],
            ["--cleanup_after_import"],
            ["--archive_after_import", "tar.gz"],
        ]:
            with self.subTest(args=additional_args):
                parsed = run_end_to_end.parse_arguments(BASE_ARGS + additional_args)
                self.assertIsNotNone(parsed)

    def test_single_draw_requires_per_draw_lifecycle(self):
        # --single_draw is a selector for per-draw mode, not a mode switch
        self.assert_rejected(["--single_draw", "812", "0", "1"])

    def test_batch_size_must_be_positive(self):
        self.assert_rejected(["--per_draw_lifecycle", "--n_draws_per_solve_batch", "0"])

    def test_per_draw_incompatible_with_step_skipping(self):
        for skip_arg in [
            "--skip_get_inputs",
            "--skip_run_scenario",
            "--skip_import_results",
        ]:
            with self.subTest(skip_arg=skip_arg):
                self.assert_rejected(["--per_draw_lifecycle", skip_arg])
        self.assert_rejected(
            ["--per_draw_lifecycle", "--single_e2e_step_only", "get_inputs"]
        )

    def test_ignore_cleanup_marker_is_not_an_e2e_argument(self):
        """
        --ignore_cleanup_marker belongs to run_scenario only (for
        deliberately solving a re-materialized subset standalone). The E2E
        flows never need it -- a full run's get_inputs step removes the
        marker, and the per-draw machinery re-materializes what it
        processes -- so the E2E parser rejects it rather than offering a
        marker override with no use.
        """
        self.assert_rejected(["--ignore_cleanup_marker"])

    def test_cleanup_flag_combinations_rejected(self):
        self.assert_rejected(["--cleanup_after_import", "--archive_after_import"])
        self.assert_rejected(["--cleanup_after_import", "--skip_import_results"])
        self.assert_rejected(
            ["--archive_after_import", "--single_e2e_step_only", "import_results"]
        )


if __name__ == "__main__":
    unittest.main()
