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
The import emissions of transmission lines and markets mapped to a generic
policy, aggregated per policy zone and horizon and entering the policy
requirement constraint.
"""

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
    "transmission",
    "transmission.capacity",
    "transmission.capacity.capacity_types",
    "transmission.capacity.capacity",
    "transmission.availability.availability",
    "transmission.operations.operational_types",
    "transmission.operations.operations",
    "system.markets.market_participation",
    "project.policy.policy_contribution",
    "transmission.policy.import_emissions",
    "system.markets.policy_import_emissions",
    "system.policy.generic_policy.aggregate_project_policy_contributions",
    "system.policy.generic_policy.aggregate_transmission_import_emissions",
    "system.policy.generic_policy.aggregate_market_import_emissions",
    "system.policy.generic_policy.aggregate_import_emissions",
]
NAME_OF_MODULE_BEING_TESTED = "system.policy.generic_policy.policy_target_balance"
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


class TestAggregateImportEmissions(unittest.TestCase):
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
        The Carbon policy's CarbonZone1 (gross basis) has the horizon
        requirements; its import emissions are the transmission and market
        gross import emissions, and they enter the policy constraint along
        with the project contributions. CarbonZone2 (net_prd) has no
        requirement, so nothing is built for it at the zone-horizon level.
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

        self.assertListEqual([], list(instance.NET_PRD_POLICY_ZONE_PERIODS))
        for h in [2020, 2030]:
            carbon = ("Carbon", "CarbonZone1", "year", h)
            tx = instance.Total_Tx_Policy_Import_Emissions_Tons[carbon]
            market = instance.Total_Market_Policy_Import_Emissions_Tons[carbon]
            total = instance.Total_Policy_Import_Emissions_Tons[carbon]
            self.assertTrue(linear_coefficients_by_var(tx))
            self.assertTrue(linear_coefficients_by_var(market))
            self.assertEqual(linear_repn(tx + market), linear_repn(total))
            # Gross zone: the signed totals are zero
            self.assertEqual(
                0, instance.Total_Tx_Policy_Signed_Import_Emissions_Tons[carbon].expr
            )

            # The import emissions are a contribution toward the policy
            contributions = instance.Total_Policy_Zone_Tmp_Contributions_from_All_Sources_Expression[
                carbon
            ]
            self.assertEqual(
                linear_repn(
                    instance.Total_Project_Policy_Zone_Tmp_Contributions[carbon] + total
                ),
                linear_repn(contributions),
            )

            # The RPS has no import rows: zero import emissions
            rps = ("RPS", "RPSZone1", "year", h)
            self.assertEqual(
                linear_repn(0),
                linear_repn(instance.Total_Policy_Import_Emissions_Tons[rps]),
            )


def linear_coefficients_by_var(expr):
    repn = generate_standard_repn(expr)
    return {var.name: coef for var, coef in zip(repn.linear_vars, repn.linear_coefs)}


def linear_repn(expr):
    return (generate_standard_repn(expr).constant, linear_coefficients_by_var(expr))


if __name__ == "__main__":
    unittest.main()
