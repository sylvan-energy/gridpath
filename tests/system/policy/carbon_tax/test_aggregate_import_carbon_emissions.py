# Copyright 2026 Sylvan Energy Analytics LLC
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
    "geography.carbon_tax_zones",
    "system.policy.carbon_tax.carbon_tax",
    "transmission",
    "transmission.capacity",
    "transmission.capacity.capacity_types",
    "transmission.capacity.capacity",
    "transmission.availability.availability",
    "transmission.operations.operational_types",
    "transmission.operations.operations",
    "transmission.operations.carbon_tax_emissions",
    "geography.markets",
    "system.markets.market_participation",
    "system.markets.carbon_tax_emissions",
    "system.policy.carbon_tax.aggregate_transmission_carbon_emissions",
    "system.policy.carbon_tax.aggregate_market_carbon_emissions",
]
NAME_OF_MODULE_BEING_TESTED = (
    "system.policy.carbon_tax.aggregate_import_carbon_emissions"
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


class TestAggregateImportCarbonEmissions(unittest.TestCase):
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

        # Net-basis zone-periods get the floored variable, gross ones the sum
        # of the sources' gross emissions
        net_zone_periods = sorted(
            (z, p)
            for (z, p) in instance.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX
            if z == "Carbon_Tax_Zone2"
        )
        self.assertTrue(net_zone_periods)
        self.assertListEqual(
            net_zone_periods, sorted(instance.NET_PRD_CARBON_TAX_ZONE_PERIODS)
        )
        self.assertListEqual(
            net_zone_periods, sorted(instance.Net_Carbon_Tax_Import_Emissions_Tons)
        )
        self.assertListEqual(
            net_zone_periods,
            sorted(instance.Net_Carbon_Tax_Import_Emissions_Constraint),
        )
        self.assertListEqual(
            sorted(instance.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX),
            sorted(instance.Total_Carbon_Tax_Import_Emissions_Tons),
        )
        net_total = instance.Total_Carbon_Tax_Import_Emissions_Tons[
            "Carbon_Tax_Zone2", 2020
        ].expr
        self.assertIs(
            net_total,
            instance.Net_Carbon_Tax_Import_Emissions_Tons["Carbon_Tax_Zone2", 2020],
        )
        gross_total = instance.Total_Carbon_Tax_Import_Emissions_Tons[
            "Carbon_Tax_Zone1", 2020
        ].expr
        self.assertIn("Tx_Carbon_Tax_Import_Emissions_Tons[", str(gross_total))
        self.assertIn("Market_Carbon_Tax_Import_Emissions_Tons[", str(gross_total))

    def test_dynamic_components(self):
        """
        The combined total is what enters the policy
        """
        m, d = create_abstract_model(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        self.assertIn("Total_Carbon_Tax_Import_Cost", d.carbon_tax_cost_components)


if __name__ == "__main__":
    unittest.main()
