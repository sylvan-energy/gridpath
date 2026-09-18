# Copyright 2016-2023 Blue Marble Analytics LLC.
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


from importlib import import_module
import os.path
import pandas as pd
import sys
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
]
NAME_OF_MODULE_BEING_TESTED = "temporal.investment.superperiods"
IMPORTED_PREREQ_MODULES = list()
for mdl in PREREQUISITE_MODULE_NAMES:
    try:
        imported_module = import_module("." + str(mdl), package="gridpath")
        IMPORTED_PREREQ_MODULES.append(imported_module)
    except ImportError:
        print("ERROR! Module " + str(mdl) + " not found.")
        sys.exit(1)
# Import the module we'll test
try:
    MODULE_BEING_TESTED = import_module(
        "." + NAME_OF_MODULE_BEING_TESTED, package="gridpath"
    )
except ImportError:
    print("ERROR! Couldn't import module " + NAME_OF_MODULE_BEING_TESTED + " to test.")


class TestSuperPeriods(unittest.TestCase):
    """
    Unit tests for gridpath.temporal.investment.periods
    """

    def test_add_model_components(self):
        """
        Test that there are no errors when adding model components
        """
        create_abstract_model(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_load_model_data(self):
        """
        Test that data are loaded with no errors
        """
        add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_initialized_components(self):
        """
        Create components; check they are initialized with data as expected
        """
        m, data = add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        instance = m.create_instance(data)

        # SUPERPERIOD_PERIODS set
        expected_superperiod_periods = sorted([(1, 2020), (2, 2020), (2, 2030)])
        actual_superperiod_periods = [
            (s_p, p) for (s_p, p) in instance.SUPERPERIOD_PERIODS
        ]
        self.assertListEqual(
            expected_superperiod_periods,
            actual_superperiod_periods,
        )

        # SUPERPERIODS set
        expected_superperiod_periods = sorted([1, 2])
        actual_superperiod_periods = [s_p for s_p in instance.SUPERPERIODS]
        self.assertListEqual(
            expected_superperiod_periods,
            actual_superperiod_periods,
        )

    def test_validate_superperiods_on_single_trajectory(self):
        """
        A superperiod may not span sibling branches of the period tree.
        Tree: 2020 -> {20301, 20302}; 20301 -> {20401, 20402};
        20302 -> {20403}.
        """
        validate = MODULE_BEING_TESTED.validate_superperiods_on_single_trajectory
        prev_period = {
            20301: 2020,
            20302: 2020,
            20401: 20301,
            20402: 20301,
            20403: 20302,
        }

        # Deterministic problem (no prev_period specified): nothing to check
        self.assertListEqual([], validate([(1, 2020), (1, 2030)], {}))

        # Superperiods along one trajectory are fine
        self.assertListEqual(
            [], validate([(1, 2020), (1, 20301), (1, 20401), (2, 20302)], prev_period)
        )

        # Siblings, and cousins on different branches, are not
        errors = validate(
            [(1, 20301), (1, 20302), (2, 20401), (2, 20403), (3, 2020), (3, 20402)],
            prev_period,
        )
        self.assertEqual(2, len(errors))
        self.assertIn("Superperiod 1 includes periods 20301 and 20302", errors[0])
        self.assertIn("Superperiod 2 includes periods 20401 and 20403", errors[1])


if __name__ == "__main__":
    unittest.main()
