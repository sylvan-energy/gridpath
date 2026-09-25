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

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.markets",
    "system.markets.prices",
    "geography.fuel_burn_limit_balancing_areas",
    "system.policy.fuel_burn_limits.fuel_burn_limits",
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
]
NAME_OF_MODULE_BEING_TESTED = (
    "system.policy.fuel_burn_limits.aggregate_project_fuel_burn"
)
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


class TestAggregateProjectFuelBurn(unittest.TestCase):
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

        # Set: PRJ_FUEL_BURN_LIMIT_BAS
        expected_prj_fuel_ba = sorted(
            [
                ("Gas_CCGT", "Zone1"),
                ("Coal", "Zone1"),
                ("Gas_CT", "Zone1"),
                ("Gas_CCGT_New", "Zone1"),
                ("Gas_CCGT_New_Binary", "Zone1"),
                ("Gas_CT_New", "Zone1"),
                ("Coal_z2", "Zone2"),
            ]
        )
        actual_prj_fuel_ba = sorted(
            [(prj, ba) for (prj, ba) in instance.PRJ_FUEL_BURN_LIMIT_BAS]
        )
        self.assertListEqual(expected_prj_fuel_ba, actual_prj_fuel_ba)

        # Set: FUEL_FUEL_BURN_LIMIT_BAS
        expected_fuel_fuel_ba = sorted(
            [
                ("Gas", "Zone1"),
                ("Coal", "Zone1"),
                ("Coal", "Zone2"),
            ]
        )
        actual_fuel_fuel_ba = sorted(
            [(f, ba) for (f, ba) in instance.FUEL_FUEL_BURN_LIMIT_BAS]
        )
        self.assertListEqual(expected_fuel_fuel_ba, actual_fuel_fuel_ba)

        # Set: PRJ_FUELS_WITH_LIMITS
        expected_prj_fuel_w_limits = sorted(
            [
                ("Gas_CCGT", "Gas"),
                ("Coal", "Coal"),
                ("Gas_CT", "Gas"),
                ("Gas_CCGT_New", "Gas"),
                ("Gas_CCGT_New_Binary", "Gas"),
                ("Gas_CT_New", "Gas"),
                ("Coal_z2", "Coal"),
            ]
        )
        actual_prj_fuel_w_limits = sorted(
            [(prj, f) for (prj, f) in instance.PRJ_FUELS_WITH_LIMITS]
        )
        self.assertListEqual(expected_prj_fuel_w_limits, actual_prj_fuel_w_limits)

        # Set: PRJS_BY_FUEL_BA
        expected_prj_by_fuel_ba = {
            "Zone1": sorted(
                [
                    "Gas_CCGT",
                    "Gas_CT",
                    "Gas_CCGT_New",
                    "Gas_CCGT_New_Binary",
                    "Gas_CT_New",
                    "Coal",
                ]
            ),
            "Zone2": sorted(["Coal_z2"]),
        }
        actual_prj_by_fuel_ba = {
            ba: sorted([prj for prj in instance.PRJS_BY_FUEL_BA[ba]])
            for ba in instance.PRJS_BY_FUEL_BA
        }

        self.assertDictEqual(expected_prj_by_fuel_ba, actual_prj_by_fuel_ba)


if __name__ == "__main__":
    unittest.main()
