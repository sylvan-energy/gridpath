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
Tests for the solver-file arguments (--write_solver_files_to_logs_dir,
--keepfiles, --symbolic), which mean different things depending on the
solver's interface: the legacy interfaces (e.g. Cbc) write problem and
solution files and delete them unless *keepfiles* is passed, Pyomo's new
interfaces replaced *keepfiles* with a working directory, and the
persistent ones among them (e.g. HiGHS, GridPath's default solver) pass the
model to the solver in memory and write no files at all.
"""

import contextlib
import io
import os
import tempfile
import unittest
import warnings
from unittest import mock

from pyomo.common.tempfiles import TempfileManager
from pyomo.environ import (
    ConcreteModel,
    NonNegativeReals,
    Objective,
    Var,
)

from gridpath import run_scenario


class SolveSentinel(Exception):
    """Raised in place of an actual solve, to inspect the solve call."""


def build_instance():
    instance = ConcreteModel()
    instance.Power = Var(within=NonNegativeReals, bounds=(0, 10))
    instance.Total_Cost = Objective(expr=instance.Power)

    return instance


def parse_args(solver, additional_args):
    return run_scenario.parse_arguments(
        [
            "--scenario",
            "irrelevant",
            "--scenario_location",
            "irrelevant",
            "--solver",
            solver,
        ]
        + additional_args
    )


class TestSolverFileArgumentWarnings(unittest.TestCase):
    """The warnings must name the arguments the solver cannot honor."""

    def get_warnings(self, solver_name, in_memory_interface, additional_args):
        parsed_arguments = parse_args(solver_name, additional_args)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            run_scenario.warn_on_unsupported_solver_file_arguments(
                solver_name=solver_name,
                new_interface=in_memory_interface,
                in_memory_interface=in_memory_interface,
                parsed_arguments=parsed_arguments,
            )

        return [str(warning.message) for warning in recorded]

    def test_in_memory_interface_warns_naming_every_requested_argument(self):
        messages = self.get_warnings(
            solver_name="highs",
            in_memory_interface=True,
            additional_args=[
                "--write_solver_files_to_logs_dir",
                "--keepfiles",
                "--symbolic",
            ],
        )
        self.assertEqual(len(messages), 1)
        for argument in [
            "--write_solver_files_to_logs_dir",
            "--keepfiles",
            "--symbolic",
        ]:
            self.assertIn(argument, messages[0])
        # The user needs to be pointed at what does work
        self.assertIn("--create_lp_problem_file_only", messages[0])
        self.assertIn("solver_options.csv", messages[0])

    def test_in_memory_interface_warns_only_about_requested_arguments(self):
        messages = self.get_warnings(
            solver_name="highs",
            in_memory_interface=True,
            additional_args=["--symbolic"],
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("--symbolic", messages[0])
        self.assertNotIn("--keepfiles", messages[0])
        self.assertNotIn("--write_solver_files_to_logs_dir", messages[0])

    def test_no_warning_when_no_solver_file_arguments_requested(self):
        self.assertEqual(
            self.get_warnings(
                solver_name="highs", in_memory_interface=True, additional_args=[]
            ),
            [],
        )

    def test_new_file_based_interface_warns_about_keepfiles_only(self):
        parsed_arguments = parse_args(
            "ipopt", ["--keepfiles", "--symbolic", "--write_solver_files_to_logs_dir"]
        )
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            run_scenario.warn_on_unsupported_solver_file_arguments(
                solver_name="ipopt",
                new_interface=True,
                in_memory_interface=False,
                parsed_arguments=parsed_arguments,
            )
        messages = [str(warning.message) for warning in recorded]
        self.assertEqual(len(messages), 1)
        self.assertIn("--keepfiles", messages[0])
        self.assertIn("--write_solver_files_to_logs_dir", messages[0])

    def test_legacy_interface_does_not_warn(self):
        parsed_arguments = parse_args(
            "cbc", ["--keepfiles", "--symbolic", "--write_solver_files_to_logs_dir"]
        )
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            run_scenario.warn_on_unsupported_solver_file_arguments(
                solver_name="cbc",
                new_interface=False,
                in_memory_interface=False,
                parsed_arguments=parsed_arguments,
            )
        self.assertEqual([str(warning.message) for warning in recorded], [])


class TestSolveArgumentsByInterface(unittest.TestCase):
    """
    *keepfiles* must not be passed to the new interfaces (it is deprecated
    there and silently redirects the solver's files to the current working
    directory); they get the working directory
    --write_solver_files_to_logs_dir points at instead.
    """

    def setUp(self):
        self.original_tempdir = TempfileManager.tempdir
        self.addCleanup(setattr, TempfileManager, "tempdir", self.original_tempdir)
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.logs_directory = tmp_dir.name

    def call_solve(self, solver_name, additional_args, tempdir):
        """Return (solve kwargs, optimizer, warnings) from an intercepted
        solve."""
        TempfileManager.tempdir = tempdir
        parsed_arguments = parse_args(solver_name, additional_args)
        recorded = {}

        def record_and_stop(instance, **kwargs):
            recorded["kwargs"] = kwargs
            raise SolveSentinel()

        original_solver_factory = run_scenario.SolverFactory

        def spying_solver_factory(*args, **kwargs):
            optimizer = original_solver_factory(*args, **kwargs)
            recorded["optimizer"] = optimizer
            optimizer.solve = record_and_stop

            return optimizer

        with mock.patch.object(
            run_scenario, "SolverFactory", side_effect=spying_solver_factory
        ):
            # Record the warnings rather than letting them print: their
            # content is checked in TestSolverFileArgumentWarnings, here we
            # only check that solve() warns at all
            with warnings.catch_warnings(record=True) as recorded_warnings:
                warnings.simplefilter("always")
                with self.assertRaises(SolveSentinel):
                    run_scenario.solve(
                        instance=build_instance(), parsed_arguments=parsed_arguments
                    )

        return (
            recorded["kwargs"],
            recorded["optimizer"],
            [str(warning.message) for warning in recorded_warnings],
        )

    def test_new_interface_gets_working_dir_and_no_keepfiles(self):
        kwargs, optimizer, _warnings = self.call_solve(
            solver_name="highs",
            additional_args=["--write_solver_files_to_logs_dir", "--keepfiles"],
            tempdir=self.logs_directory,
        )
        self.assertNotIn("keepfiles", kwargs)
        self.assertEqual(
            os.path.realpath(str(optimizer.config.working_dir)),
            os.path.realpath(self.logs_directory),
        )

    def test_new_interface_working_dir_untouched_without_the_argument(self):
        kwargs, optimizer, _warnings = self.call_solve(
            solver_name="highs", additional_args=[], tempdir=None
        )
        self.assertNotIn("keepfiles", kwargs)
        self.assertIsNone(optimizer.config.working_dir)

    def test_solve_warns_about_unsupported_arguments(self):
        """The warning is useless if solve() doesn't actually emit it."""
        _kwargs, _optimizer, recorded_warnings = self.call_solve(
            solver_name="highs",
            additional_args=["--write_solver_files_to_logs_dir", "--keepfiles"],
            tempdir=self.logs_directory,
        )
        self.assertTrue(
            any("have no effect" in message for message in recorded_warnings),
            msg=f"solve() did not warn; warnings: {recorded_warnings}",
        )

    def test_legacy_interface_still_gets_keepfiles(self):
        kwargs, _optimizer, recorded_warnings = self.call_solve(
            solver_name="cbc",
            additional_args=["--write_solver_files_to_logs_dir", "--keepfiles"],
            tempdir=self.logs_directory,
        )
        self.assertTrue(kwargs["keepfiles"])
        self.assertEqual(recorded_warnings, [])
        # The legacy interfaces write to the temporary file directory, which
        # --write_solver_files_to_logs_dir points at the logs directory
        self.assertEqual(TempfileManager.tempdir, self.logs_directory)


class TestSymbolicProblemFileLabels(unittest.TestCase):
    """
    --create_lp_problem_file_only must honor --symbolic: without symbolic
    labels the LP file is written with generic labels (x1, c_e_x1_), which
    are useless for debugging.
    """

    def setUp(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.tmp_dir_name = tmp_dir.name

    def write_lp(self, symbolic_solver_labels):
        instance = build_instance()
        with contextlib.redirect_stdout(io.StringIO()):
            run_scenario.write_problem_file(
                instance=instance,
                prob_sol_files_directory=self.tmp_dir_name,
                symbolic_solver_labels=symbolic_solver_labels,
            )
        with open(os.path.join(self.tmp_dir_name, "problem_file.lp")) as f:
            return f.read()

    def test_symbolic_labels_name_the_pyomo_components(self):
        lp_file = self.write_lp(symbolic_solver_labels=True)
        self.assertIn("Power", lp_file)
        self.assertIn("Total_Cost", lp_file)

    def test_generic_labels_are_the_default(self):
        lp_file = self.write_lp(symbolic_solver_labels=False)
        self.assertNotIn("Power", lp_file)
        self.assertNotIn("Total_Cost", lp_file)


if __name__ == "__main__":
    unittest.main()
