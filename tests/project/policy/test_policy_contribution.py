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
from tests.project.operations.common_functions import get_project_operational_timepoints

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "system.load_balance.static_load_requirement",
    "geography.generic_policy",
    "system.policy.generic_policy.generic_policy_requirements",
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
    "project.capacity.potential",
    "project.operations.operational_types",
    "project.operations.power",
]
NAME_OF_MODULE_BEING_TESTED = "project.policy.policy_contribution"
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


class TestRECs(unittest.TestCase):
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

        # Set: PROJECT_POLICY_ZONES
        expected_prj_policy_zones = sorted(
            [
                ("Wind", "RPS", "RPSZone1"),
                ("Wind_z2", "RPS", "RPSZone1"),
                ("Gas_CCGT", "Carbon", "CarbonZone1"),
                ("Coal", "Carbon", "CarbonZone1"),
                ("Battery", "RPS", "RPSZone1"),
                ("Wind", "SLICE_OF_DAY", "SODZone1"),
                ("Gas_CCGT", "SLICE_OF_DAY", "SODZone1"),
                ("Battery", "SLICE_OF_DAY", "SODZone1"),
                ("Nuclear_Flexible", "SLICE_OF_DAY", "SODZone1"),
            ]
        )
        actual_prj_policy_zones = sorted(
            [
                (prj, policy, zone)
                for (prj, policy, zone) in instance.PROJECT_POLICY_ZONES
            ]
        )
        self.assertListEqual(expected_prj_policy_zones, actual_prj_policy_zones)

        # Param: compliance_type
        expected_compliance_type = OrderedDict(
            sorted(
                {
                    ("Wind", "RPS", "RPSZone1"): "f_output",
                    ("Wind_z2", "RPS", "RPSZone1"): "f_output",
                    ("Gas_CCGT", "Carbon", "CarbonZone1"): "f_output",
                    ("Coal", "Carbon", "CarbonZone1"): "f_output",
                    ("Battery", "RPS", "RPSZone1"): "stor_losses",
                    ("Wind", "SLICE_OF_DAY", "SODZone1"): "sod_exceedance",
                    ("Gas_CCGT", "SLICE_OF_DAY", "SODZone1"): "sod_flat_block",
                    ("Battery", "SLICE_OF_DAY", "SODZone1"): "sod_stor",
                    ("Nuclear_Flexible", "SLICE_OF_DAY", "SODZone1"): "sod_flat_block",
                }.items()
            )
        )
        actual_compliance_type = OrderedDict(
            sorted(
                {
                    (prj, policy, zone): instance.compliance_type[prj, policy, zone]
                    for (prj, policy, zone) in instance.PROJECT_POLICY_ZONES
                }.items()
            )
        )
        self.assertDictEqual(expected_compliance_type, actual_compliance_type)

        # Set: PRJ_POLICY_ZONE_PRDS_MONTH_HOURS
        # Every mapped project gets the month-hour requirement indices of its
        # policy-zone, but only for the periods in which it is operational:
        # Nuclear_Flexible has specified capacity in 2030 only, so its 2020
        # slices must be excluded (its Capacity_MW is undefined there).
        month_hours_with_req = sorted(
            (p, z, prd, mn, hr)
            for (p, z, prd, mn, hr) in instance.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ
        )
        self.assertListEqual(
            [
                ("SLICE_OF_DAY", "SODZone1", 2020, 1, 7),
                ("SLICE_OF_DAY", "SODZone1", 2020, 1, 8),
                ("SLICE_OF_DAY", "SODZone1", 2030, 1, 7),
                ("SLICE_OF_DAY", "SODZone1", 2030, 1, 8),
            ],
            month_hours_with_req,
        )
        expected_prj_month_hours = sorted(
            [
                (prj, "SLICE_OF_DAY", "SODZone1", prd, 1, hr)
                for prj in ["Wind", "Gas_CCGT", "Battery"]
                for prd in [2020, 2030]
                for hr in [7, 8]
            ]
            + [
                ("Nuclear_Flexible", "SLICE_OF_DAY", "SODZone1", 2030, 1, hr)
                for hr in [7, 8]
            ]
        )
        actual_prj_month_hours = sorted(
            (prj, policy, zone, prd, mn, hr)
            for (
                prj,
                policy,
                zone,
                prd,
                mn,
                hr,
            ) in instance.PRJ_POLICY_ZONE_PRDS_MONTH_HOURS
        )
        self.assertListEqual(expected_prj_month_hours, actual_prj_month_hours)
        self.assertIn(("Nuclear_Flexible", 2030), instance.PRJ_OPR_PRDS)
        self.assertNotIn(("Nuclear_Flexible", 2020), instance.PRJ_OPR_PRDS)


if __name__ == "__main__":
    unittest.main()
