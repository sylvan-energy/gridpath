# Copyright 2016-2024 Blue Marble Analytics LLC.
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


from collections import OrderedDict
from importlib import import_module
import os.path
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "test_data")

# No prerequisite modules
NAME_OF_MODULE_BEING_TESTED = "geography.generic_policy"

try:
    MODULE_BEING_TESTED = import_module(
        "." + NAME_OF_MODULE_BEING_TESTED, package="gridpath"
    )
except ImportError:
    print("ERROR! Couldn't import module " + NAME_OF_MODULE_BEING_TESTED + " to test.")


class TestGeographyGenericPolicy(unittest.TestCase):
    """ """

    def test_add_model_components(self):
        """
        Test that there are no errors when adding model components
        :return:
        """
        create_abstract_model(
            prereq_modules=[],
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
        :return:
        """
        add_components_and_load_data(
            prereq_modules=[],
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_load_zone_data_loads_correctly(self):
        """
        Create LOAD_ZONES set and load data; check resulting set is as expected
        :return:
        """
        m, data = add_components_and_load_data(
            prereq_modules=[],
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        instance = m.create_instance(data)
        expected = sorted(
            [
                ("RPS", "RPSZone1"),
                ("Carbon", "CarbonZone1"),
                ("Carbon", "CarbonZone2"),
                ("SLICE_OF_DAY", "SODZone1"),
            ]
        )
        actual = sorted([(p, z) for (p, z) in instance.POLICIES_ZONES])
        self.assertListEqual(
            expected, actual, msg="LOAD_ZONES set data does not load correctly."
        )

        # Param: policy_zone_allow_violation
        expected_allow_viol = OrderedDict(
            sorted(
                {
                    ("RPS", "RPSZone1"): 0,
                    ("Carbon", "CarbonZone1"): 1,
                    ("Carbon", "CarbonZone2"): 0,
                    ("SLICE_OF_DAY", "SODZone1"): 0,
                }.items()
            )
        )
        actual_allow_viol = OrderedDict(
            sorted(
                {
                    (p, z): instance.policy_zone_allow_violation[(p, z)]
                    for (p, z) in instance.POLICIES_ZONES
                }.items()
            )
        )
        self.assertDictEqual(expected_allow_viol, actual_allow_viol)

        # Param: policy_zone_violation_penalty_per_unit
        expected_overgen_penalty = OrderedDict(
            sorted(
                {
                    ("RPS", "RPSZone1"): 0,
                    ("Carbon", "CarbonZone1"): 100,
                    ("Carbon", "CarbonZone2"): 0,
                    ("SLICE_OF_DAY", "SODZone1"): 0,
                }.items()
            )
        )
        actual_overgen_penalty = OrderedDict(
            sorted(
                {
                    (p, z): instance.policy_zone_violation_penalty_per_unit[(p, z)]
                    for (p, z) in instance.POLICIES_ZONES
                }.items()
            )
        )
        self.assertDictEqual(expected_overgen_penalty, actual_overgen_penalty)

        # Param: policy_import_emissions_basis (unspecified defaults to gross)
        self.assertDictEqual(
            {
                ("RPS", "RPSZone1"): "gross",
                ("Carbon", "CarbonZone1"): "gross",
                ("Carbon", "CarbonZone2"): "net_prd",
                ("SLICE_OF_DAY", "SODZone1"): "gross",
            },
            {
                (p, z): instance.policy_import_emissions_basis[p, z]
                for (p, z) in instance.POLICIES_ZONES
            },
        )


if __name__ == "__main__":
    unittest.main()
