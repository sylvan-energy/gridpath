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
Tests for the check that HiGHS's HiPO algorithm is actually available when a
scenario's solver options request it. Neither HiGHS nor Pyomo report an
unavailable algorithm: setOptionValue() returns an error that the solver
interface swallows and the solve proceeds with the default algorithm, so
without this check a run believed to be using HiPO can silently be simplex.
"""

import sys
import unittest
from unittest import mock

from gridpath.run_scenario import check_hipo_availability

LOADED_STATUS = "Extras: Successfully loaded libhighs_extras.dylib"
NOT_LOADED_STATUS = "Extras: Not loaded (library not found)"

HIPO_OPTIONS = {"solver": "hipo", "parallel": "on", "run_crossover": "on"}


class TestCheckHipoAvailability(unittest.TestCase):
    def test_no_error_when_extras_loaded(self):
        with mock.patch(
            "highspy._core.getExtrasLoadStatus", return_value=LOADED_STATUS
        ):
            check_hipo_availability(solver_name="highs", solver_options=HIPO_OPTIONS)

    def test_error_when_extras_not_loaded(self):
        with mock.patch(
            "highspy._core.getExtrasLoadStatus", return_value=NOT_LOADED_STATUS
        ):
            with self.assertRaises(UserWarning) as e:
                check_hipo_availability(
                    solver_name="highs", solver_options=HIPO_OPTIONS
                )
        self.assertIn("highspy-extras", str(e.exception))
        self.assertIn(NOT_LOADED_STATUS, str(e.exception))

    def test_error_when_extras_not_importable(self):
        # A missing highspy-extras package can also make the status check
        # itself unavailable; that must not pass silently either
        with mock.patch.dict(sys.modules, {"highspy._core": None}):
            with self.assertRaises(UserWarning) as e:
                check_hipo_availability(
                    solver_name="highs", solver_options=HIPO_OPTIONS
                )
        self.assertIn("highspy-extras", str(e.exception))

    def test_appsi_highs_solver_name_also_checked(self):
        with mock.patch(
            "highspy._core.getExtrasLoadStatus", return_value=NOT_LOADED_STATUS
        ):
            with self.assertRaises(UserWarning):
                check_hipo_availability(
                    solver_name="appsi_highs", solver_options=HIPO_OPTIONS
                )

    def test_no_check_when_hipo_not_requested(self):
        # The default HiGHS algorithm needs no extras
        with mock.patch(
            "highspy._core.getExtrasLoadStatus", return_value=NOT_LOADED_STATUS
        ):
            check_hipo_availability(solver_name="highs", solver_options={})
            check_hipo_availability(
                solver_name="highs", solver_options={"presolve": "off"}
            )
            check_hipo_availability(
                solver_name="highs", solver_options={"solver": "ipm"}
            )

    def test_no_check_for_other_solvers(self):
        # "solver" is also a solver option for shell solvers such as GAMS,
        # where it names the solver to use and has nothing to do with HiGHS
        with mock.patch(
            "highspy._core.getExtrasLoadStatus", return_value=NOT_LOADED_STATUS
        ):
            check_hipo_availability(
                solver_name="gams", solver_options={"solver": "hipo"}
            )
            check_hipo_availability(solver_name=None, solver_options=HIPO_OPTIONS)

    def test_solver_option_value_is_case_and_whitespace_tolerant(self):
        with mock.patch(
            "highspy._core.getExtrasLoadStatus", return_value=NOT_LOADED_STATUS
        ):
            with self.assertRaises(UserWarning):
                check_hipo_availability(
                    solver_name="HiGHS", solver_options={"solver": " HiPO "}
                )


if __name__ == "__main__":
    unittest.main()
