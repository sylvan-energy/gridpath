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


from collections import OrderedDict
from importlib import import_module
import os.path
import sys
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data
from tests.project.operations.common_functions import (
    get_project_operational_timepoints,
    get_project_operational_periods,
)

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.markets",
    "system.markets.prices",
    "geography.carbon_credits_zones",
    "geography.water_network",
    "system.water.water_system_params",
    "system.water.water_nodes",
    "system.water.water_flows",
    "system.water.water_node_inflows_outflows",
    "system.water.reservoirs",
    "system.water.water_node_balance",
    "system.water.powerhouses",
    "project",
    "project.capacity.capacity",
    "project.availability.availability",
    "project.fuels",
    "project.operations",
    "system.load_balance.static_load_requirement",
    "project.capacity.potential",
    "project.operations.operational_types",
    "project.operations.power",
    "project.operations.fuel_burn",
    "project.operations.carbon_emissions",
]
NAME_OF_MODULE_BEING_TESTED = "project.operations.carbon_credits"
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


Infinity = float("inf")


class TestCarbonCredits(unittest.TestCase):
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

        # Set: CARBON_CREDITS_GENERATION_PRJS
        expected_projects = sorted(
            [
                "Nuclear",
                "Gas_CCGT",
                "Coal",
                "DAC",
            ]
        )
        actual_projects = sorted([p for p in instance.CARBON_CREDITS_GENERATION_PRJS])
        self.assertListEqual(expected_projects, actual_projects)

        # Set: CARBON_CREDITS_GENERATION_PRJ_OPR_TMPS
        expected_carb_prj_op_tmp = sorted(
            get_project_operational_timepoints(expected_projects)
        )

        actual_carb_prj_op_tmp = sorted(
            [
                (prj, tmp)
                for (prj, tmp) in instance.CARBON_CREDITS_GENERATION_PRJ_OPR_TMPS
            ]
        )
        self.assertListEqual(expected_carb_prj_op_tmp, actual_carb_prj_op_tmp)

        # CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS
        expected_carb_prj_op_prd = sorted(
            get_project_operational_periods(expected_projects)
        )
        actual_carb_prj_op_prd = sorted(
            [
                (prj, prd)
                for (prj, prd) in instance.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS
            ]
        )
        self.assertListEqual(expected_carb_prj_op_prd, actual_carb_prj_op_prd)

        # Set: CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES
        expected_prj_zones = sorted(
            [
                ("Coal", "Carbon_Credits_Zone1"),
                ("Gas_CCGT", "Carbon_Credits_Zone1"),
                ("Gas_CT", "Carbon_Credits_Zone2"),
            ]
        )

        actual_prj_zones = sorted(
            [
                (prj, z)
                for (
                    prj,
                    z,
                ) in instance.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES
            ]
        )

        self.assertListEqual(expected_prj_zones, actual_prj_zones)

        # Param: intensity_threshold_emissions_toCO2_per_MWh
        expected_intensity_threshold = {
            ("Nuclear", 2020): 100,
            ("Gas_CCGT", 2020): Infinity,
            ("Coal", 2020): 200,
            ("DAC", 2020): Infinity,
            ("Nuclear", 2030): Infinity,
            ("Gas_CCGT", 2030): Infinity,
            ("Coal", 2030): Infinity,
            ("DAC", 2030): Infinity,
        }
        actual_intensity_threshold = {
            (prj, prd): instance.intensity_threshold_emissions_toCO2_per_MWh[prj, prd]
            for (prj, prd) in instance.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS
        }
        self.assertDictEqual(expected_intensity_threshold, actual_intensity_threshold)

        # Param: absolute_threshold_emissions_toCO2_per_MWh
        expected_absolute_threshold = {
            ("Nuclear", 2020): Infinity,
            ("Gas_CCGT", 2020): 100,
            ("Coal", 2020): Infinity,
            ("DAC", 2020): Infinity,
            ("Nuclear", 2030): Infinity,
            ("Gas_CCGT", 2030): Infinity,
            ("Coal", 2030): Infinity,
            ("DAC", 2030): 100,
        }
        actual_absolute_threshold = {
            (prj, prd): instance.absolute_threshold_emissions_toCO2[prj, prd]
            for (prj, prd) in instance.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS
        }
        self.assertDictEqual(expected_absolute_threshold, actual_absolute_threshold)


if __name__ == "__main__":
    unittest.main()
