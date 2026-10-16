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
import sys
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.generic_policy",
    "system.load_balance.static_load_requirement",
]
NAME_OF_MODULE_BEING_TESTED = "system.policy.generic_policy.generic_policy_requirements"
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


class TestHorizonEnergyTarget(unittest.TestCase):
    """ """

    def test_add_model_components(self):
        """
        Test that there are no errors when adding model components
        :return:
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
        :return:
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

    def test_data_loaded_correctly(self):
        """
        Test components initialized with data as expected
        :return:
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

        # Set: POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
        expected_p_zone_bt_horizons = sorted(
            [
                ("RPS", "RPSZone1", "year", 2020),
                ("RPS", "RPSZone1", "year", 2030),
                ("Carbon", "CarbonZone1", "year", 2020),
                ("Carbon", "CarbonZone1", "year", 2030),
            ]
        )
        actual_p_zone_bt_horizons = sorted(
            [
                (p, z, bt, h)
                for (
                    p,
                    z,
                    bt,
                    h,
                ) in instance.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
            ]
        )
        self.assertListEqual(expected_p_zone_bt_horizons, actual_p_zone_bt_horizons)

        # Param: policy_requirement
        expected_req = OrderedDict(
            sorted(
                {
                    ("RPS", "RPSZone1", "year", 2020): 250000,
                    ("RPS", "RPSZone1", "year", 2030): 0,
                    ("Carbon", "CarbonZone1", "year", 2020): 0,
                    ("Carbon", "CarbonZone1", "year", 2030): 200000,
                }.items()
            )
        )
        actual_req = OrderedDict(
            sorted(
                {
                    (p, z, bt, h): instance.policy_requirement[p, z, bt, h]
                    for (
                        p,
                        z,
                        bt,
                        h,
                    ) in instance.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
                }.items()
            )
        )
        self.assertDictEqual(expected_req, actual_req)

        # Param: policy_requirement_f_load_coeff
        expected_req_fl = OrderedDict(
            sorted(
                {
                    ("RPS", "RPSZone1", "year", 2020): 0,
                    ("RPS", "RPSZone1", "year", 2030): 0.8,
                    ("Carbon", "CarbonZone1", "year", 2020): 0.9,
                    ("Carbon", "CarbonZone1", "year", 2030): 0,
                }.items()
            )
        )
        actual_req_fl = OrderedDict(
            sorted(
                {
                    (p, z, bt, h): instance.policy_requirement_f_load_coeff[p, z, bt, h]
                    for (
                        p,
                        z,
                        bt,
                        h,
                    ) in instance.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
                }.items()
            )
        )
        self.assertDictEqual(expected_req_fl, actual_req_fl)

        # Param: policy_requirement_sense (unspecified defaults to "min")
        expected_sense = OrderedDict(
            sorted(
                {
                    ("RPS", "RPSZone1", "year", 2020): "min",
                    ("RPS", "RPSZone1", "year", 2030): "min",
                    ("Carbon", "CarbonZone1", "year", 2020): "max",
                    ("Carbon", "CarbonZone1", "year", 2030): "max",
                }.items()
            )
        )
        actual_sense = OrderedDict(
            sorted(
                {
                    (p, z, bt, h): instance.policy_requirement_sense[p, z, bt, h]
                    for (
                        p,
                        z,
                        bt,
                        h,
                    ) in instance.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
                }.items()
            )
        )
        self.assertDictEqual(expected_sense, actual_sense)

        # Param: policy_requirement_f_base_coeff (defaults to 0)
        expected_base_coeff = OrderedDict(
            sorted(
                {
                    ("RPS", "RPSZone1", "year", 2020): 0,
                    ("RPS", "RPSZone1", "year", 2030): 0,
                    ("Carbon", "CarbonZone1", "year", 2020): 0.5,
                    ("Carbon", "CarbonZone1", "year", 2030): 0,
                }.items()
            )
        )
        actual_base_coeff = OrderedDict(
            sorted(
                {
                    (p, z, bt, h): instance.policy_requirement_f_base_coeff[p, z, bt, h]
                    for (
                        p,
                        z,
                        bt,
                        h,
                    ) in instance.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
                }.items()
            )
        )
        self.assertDictEqual(expected_base_coeff, actual_base_coeff)

        # Set: POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ
        expected_p_zone_prd_mh = sorted(
            [
                ("SLICE_OF_DAY", "SODZone1", 2020, 1, 7),
                ("SLICE_OF_DAY", "SODZone1", 2020, 1, 8),
                ("SLICE_OF_DAY", "SODZone1", 2030, 1, 7),
                ("SLICE_OF_DAY", "SODZone1", 2030, 1, 8),
            ]
        )
        actual_p_zone_prd_mh = sorted(
            [
                (p, z, prd, mn, hr)
                for (
                    p,
                    z,
                    prd,
                    mn,
                    hr,
                ) in instance.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ
            ]
        )
        self.assertListEqual(expected_p_zone_prd_mh, actual_p_zone_prd_mh)

        # Param: policy_month_hour_requirement
        expected_mh_req = OrderedDict(
            sorted(
                {
                    ("SLICE_OF_DAY", "SODZone1", 2020, 1, 7): 100,
                    ("SLICE_OF_DAY", "SODZone1", 2020, 1, 8): 100,
                    ("SLICE_OF_DAY", "SODZone1", 2030, 1, 7): 100,
                    ("SLICE_OF_DAY", "SODZone1", 2030, 1, 8): 100,
                }.items()
            )
        )
        actual_mh_req = OrderedDict(
            sorted(
                {
                    (p, z, prd, mn, hr): instance.policy_month_hour_requirement[
                        p, z, prd, mn, hr
                    ]
                    for (
                        p,
                        z,
                        prd,
                        mn,
                        hr,
                    ) in instance.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ
                }.items()
            )
        )
        self.assertDictEqual(expected_mh_req, actual_mh_req)


if __name__ == "__main__":
    unittest.main()
