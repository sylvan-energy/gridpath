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
End-to-end equivalence test for numerical scaling, built on the example suite.

``TestScaledExamples`` subclasses ``tests.test_examples.TestExamples`` and
re-runs every example scenario with the power/energy and dollar scale factors
turned on, checking that the objective still matches the same stored expected
value (to a relative tolerance). Because it only overrides the comparison hook
(``run_and_check_objective``), it automatically inherits the parent's test
database setup and *every* ``test_*`` method -- including any example test added
later. A new scenario that happens to break under scaling therefore fails here
without anyone having to remember to add it.

Rationale for the relative tolerance: the unscaled suite asserts an *absolute*
objective match (``places=1``), which only holds because GridPath is
bit-deterministic per platform. Scaling deliberately changes the floating-point
numbers the solver sees, so identical answers can differ in the last few digits
(and, for degenerate LPs, the solver may settle on a different equally-optimal
vertex, differing by ~1e-7 relative). A relative tolerance passes those while
still catching real breakage, which shows up as a large relative difference (or
an outright error, as an unhandled missing-dual once did for ``test_markets``).

This complements the fast, DB-free unit tests in ``test_scaling.py`` (classifier,
factor assignment, exact round-trip, argument guards), which pinpoint *why*
something breaks; this suite is the broad integration net.
"""

import multiprocessing

# Import the module (not the TestExamples class by name): pytest collects any
# TestCase subclass bound at module scope, so importing the class directly would
# make the unscaled TestExamples suite run a second time in this file. Referencing
# it through the module keeps only TestScaledExamples collected here.
from tests import test_examples
from tests.test_examples import (
    objective_function_overwrite,
    DB_PATH,
    EXAMPLES_DIRECTORY,
)
from gridpath import run_end_to_end


class TestScaledExamples(test_examples.TestExamples):
    """Run the full example suite with numerical scaling on."""

    # MW -> GW, MWh -> GWh; $ -> $M.
    POWER_SCALE_FACTOR = 1000.0
    DOLLAR_SCALE_FACTOR = 1000000.0

    # Relative tolerance on the objective: |actual - expected| <= tol * |expected|.
    # Comfortably covers machine-precision matches (~1e-13) and degenerate-LP
    # alternate optima (~1e-7); real breakage fails loudly.
    RELATIVE_TOLERANCE = 1e-6
    # Absolute floor for the (not expected in practice) zero-objective case.
    ABSOLUTE_FLOOR = 1e-6

    def check_validation(self, test):
        """Skip input validation in the scaled suite.

        Validation runs against the same inputs regardless of solve-time
        scaling, so it is already covered by ``TestExamples``; re-running it here
        would only double the work.
        """
        pass

    def _assert_objective_close(self, expected, actual, msg=None):
        """Recursively compare (possibly nested per-subproblem/stage) objectives
        by relative tolerance."""
        if isinstance(expected, dict):
            self.assertIsInstance(actual, dict, msg)
            self.assertEqual(expected.keys(), actual.keys(), msg)
            for key in expected:
                self._assert_objective_close(expected[key], actual[key], msg=msg)
        else:
            bound = (
                self.RELATIVE_TOLERANCE * max(abs(expected), abs(actual))
                + self.ABSOLUTE_FLOOR
            )
            self.assertLessEqual(
                abs(expected - actual),
                bound,
                msg=(
                    f"{msg or ''} expected={expected} actual={actual} "
                    f"rel_diff={abs(expected - actual) / (abs(expected) or 1):.3e} "
                    f"(tol={self.RELATIVE_TOLERANCE})"
                ),
            )

    def run_and_check_objective(
        self,
        scenario_name,
        expected_objective,
        additional_args=[],
        solver=None,
        parallel=1,
    ):
        """Run a scenario with scaling on and check the objective by relative
        tolerance.

        Mirrors ``TestExamples.run_and_check_objective`` but (a) appends the
        scale-factor arguments, (b) compares with a relative tolerance, and (c)
        does not write the ``actual_objective`` column back to the tracked
        expected-values CSV (that column is for the unscaled baseline).
        """
        args_to_pass = [
            "--database",
            DB_PATH,
            "--scenario",
            scenario_name,
            "--scenario_location",
            EXAMPLES_DIRECTORY,
            "--n_parallel_get_inputs",
            str(parallel),
            "--n_parallel_solve",
            str(parallel),
            "--quiet",
            "--mute_solver_output",
            "--testing",
            "--power_scale_factor",
            str(self.POWER_SCALE_FACTOR),
            "--dollar_scale_factor",
            str(self.DOLLAR_SCALE_FACTOR),
        ] + additional_args

        if solver is not None:
            args_to_pass.append("--solver")
            args_to_pass.append(solver)

        actual_objective = run_end_to_end.main(args_to_pass)

        expected_objective = objective_function_overwrite(
            scenario_name=scenario_name, starting_objective=expected_objective
        )

        # Flatten a multiprocessing manager proxy dict to a plain dict (only
        # relevant when parallel > 1); mirrors the parent.
        if hasattr(multiprocessing, "managers"):
            if isinstance(actual_objective, multiprocessing.managers.DictProxy):
                actual_objective_copy = dict(actual_objective.copy())
                for subproblem in actual_objective.keys():
                    if isinstance(
                        actual_objective[subproblem],
                        multiprocessing.managers.DictProxy,
                    ):
                        actual_objective_copy[subproblem] = dict(
                            actual_objective_copy[subproblem].copy()
                        )
                actual_objective = actual_objective_copy

        self._assert_objective_close(
            expected_objective, actual_objective, msg=scenario_name
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
