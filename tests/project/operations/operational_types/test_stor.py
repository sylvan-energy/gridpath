# Copyright 2016-2023 Blue Marble Analytics LLC.
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
import sys
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data
from tests.project.operations.common_functions import get_project_operational_timepoints

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "project",
    "project.capacity.capacity",
    "project.availability.availability",
    "project.fuels",
    "project.operations",
]
NAME_OF_MODULE_BEING_TESTED = "project.operations.operational_types.stor"
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


class TestStor(unittest.TestCase):
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

    def test_capacity_data_load_correctly(self):
        """
        Test that are data loaded are as expected
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

        # Sets: STOR
        expected_projects = ["Battery", "Battery_Binary", "Battery_Specified"]
        actual_projects = sorted([p for p in instance.STOR])
        self.assertListEqual(expected_projects, actual_projects)

        # STOR_OPR_TMPS
        expected_tmps = sorted(get_project_operational_timepoints(expected_projects))
        actual_tmps = sorted([tmp for tmp in instance.STOR_OPR_TMPS])
        self.assertListEqual(expected_tmps, actual_tmps)

        # Param: stor_charging_efficiency
        expected_charging_efficiency = {
            "Battery": 0.8,
            "Battery_Binary": 0.8,
            "Battery_Specified": 0.8,
        }
        actual_charging_efficiency = {
            prj: instance.stor_charging_efficiency[prj] for prj in instance.STOR
        }
        self.assertDictEqual(expected_charging_efficiency, actual_charging_efficiency)

        # Param: stor_discharging_efficiency
        expected_discharging_efficiency = {
            "Battery": 0.8,
            "Battery_Binary": 0.8,
            "Battery_Specified": 0.8,
        }
        actual_discharging_efficiency = {
            prj: instance.stor_discharging_efficiency[prj] for prj in instance.STOR
        }
        self.assertDictEqual(
            expected_discharging_efficiency, actual_discharging_efficiency
        )

        # Param: stor_storage_efficiency
        expected_storage_efficiency = {
            "Battery": 0.9,
            "Battery_Binary": 1.0,
            "Battery_Specified": 0.5,
        }
        actual_storage_efficiency = {
            prj: instance.stor_storage_efficiency[prj] for prj in instance.STOR
        }
        self.assertDictEqual(expected_storage_efficiency, actual_storage_efficiency)

        # Param: stor_exogenous_starting_state_of_charge
        expected_exog_soc = {
            ("Battery", 20300101): 1,
        }
        actual_exog_soc = {
            (prj, tmp): instance.stor_exogenous_starting_state_of_charge[prj, tmp]
            for (prj, tmp) in instance.STOR_EXOG_SOC_TMPS
        }
        self.assertDictEqual(expected_exog_soc, actual_exog_soc)

        # Param: stor_reserves_setpoint_duration_hours (sparse: no default, so
        # only projects with a specified value are "in" the param)
        expected_reserves_setpoint_duration = {"Battery": 0.5}
        actual_reserves_setpoint_duration = {
            prj: instance.stor_reserves_setpoint_duration_hours[prj]
            for prj in instance.STOR
            if prj in instance.stor_reserves_setpoint_duration_hours
        }
        self.assertDictEqual(
            expected_reserves_setpoint_duration, actual_reserves_setpoint_duration
        )


if __name__ == "__main__":
    unittest.main()
