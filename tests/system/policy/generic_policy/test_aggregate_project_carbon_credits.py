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
import sys
import unittest

from pyomo.repn import generate_standard_repn

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
    "system.load_balance.static_load_requirement",
    "geography.generic_policy",
    "geography.carbon_credits_zones",
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
    "project.operations.fuel_burn",
    "project.operations.carbon_emissions",
    "project.operations.carbon_credits",
    "project.policy.policy_contribution",
]
NAME_OF_MODULE_BEING_TESTED = (
    "system.policy.generic_policy.aggregate_project_carbon_credits"
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


class TestAggregateProjectCarbonCredits(unittest.TestCase):
    """ """

    def test_add_model_components(self):
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
        The Carbon policy's CarbonZone1 maps to both credits zones and its
        CarbonZone2 to Carbon_Credits_Zone1 only; the credits that count
        toward CarbonZone1's requirements are the purchases, in the horizon's
        period, of the projects mapped to it from either credits zone, and
        they enter the policy as a negative contribution.
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

        # Set: POLICIES_ZONES_CARBON_CREDITS_ZONES
        self.assertListEqual(
            [
                ("Carbon", "CarbonZone1", "Carbon_Credits_Zone1"),
                ("Carbon", "CarbonZone1", "Carbon_Credits_Zone2"),
                ("Carbon", "CarbonZone2", "Carbon_Credits_Zone1"),
            ],
            sorted(instance.POLICIES_ZONES_CARBON_CREDITS_ZONES),
        )

        mapped_prjs = sorted(
            prj
            for (prj, policy, zone) in instance.PROJECT_POLICY_ZONES
            if (policy, zone) == ("Carbon", "CarbonZone1")
        )
        self.assertListEqual(["Coal", "Gas_CCGT", "Gas_CT"], mapped_prjs)

        for h in [2020, 2030]:
            carbon = ("Carbon", "CarbonZone1", "year", h)
            expected_purchases = sorted(
                (prj, z, prd)
                for (
                    prj,
                    z,
                    prd,
                ) in instance.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS
                if prj in mapped_prjs and prd == h
            )
            self.assertTrue(expected_purchases)
            self.assertListEqual(
                expected_purchases,
                sorted(
                    instance.CARBON_CREDITS_PURCHASES_BY_POLICY_ZONE_BLN_TYPE_HRZ[
                        carbon
                    ]
                ),
            )
            expected = sum(
                instance.Project_Purchase_Carbon_Credits[idx]
                for idx in expected_purchases
            )
            self.assertEqual(
                linear_repn(expected),
                linear_repn(instance.Total_Policy_Carbon_Credits[carbon]),
            )
            self.assertEqual(
                linear_repn(-expected),
                linear_repn(instance.Total_Policy_Carbon_Credits_Contribution[carbon]),
            )

            # No credits for the RPS (no mapping)
            rps = ("RPS", "RPSZone1", "year", h)
            self.assertListEqual(
                [],
                list(
                    instance.CARBON_CREDITS_PURCHASES_BY_POLICY_ZONE_BLN_TYPE_HRZ[rps]
                ),
            )


def linear_repn(expr):
    repn = generate_standard_repn(expr)
    return (
        repn.constant,
        {var.name: coef for var, coef in zip(repn.linear_vars, repn.linear_coefs)},
    )


if __name__ == "__main__":
    unittest.main()
