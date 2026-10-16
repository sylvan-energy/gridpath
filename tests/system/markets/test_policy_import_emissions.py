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

from pyomo.environ import value

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.markets",
    "geography.generic_policy",
    "system.markets.market_participation",
]
NAME_OF_MODULE_BEING_TESTED = "system.markets.policy_import_emissions"
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

# The test data assign (Zone1, Market_Hub_1) and (Zone1, Market_Hub_2) to the
# Carbon policy's CarbonZone1 (gross basis) and (Zone2, Market_Hub_1) to its
# CarbonZone2 (net_prd basis), with an export intensity
ZONE1 = ("Carbon", "CarbonZone1")
ZONE2 = ("Carbon", "CarbonZone2")
LZ_MARKET_ZONES = [
    ("Zone1", "Market_Hub_1", *ZONE1),
    ("Zone2", "Market_Hub_1", *ZONE2),
    ("Zone1", "Market_Hub_2", *ZONE1),
]


class TestMarketPolicyImportEmissions(unittest.TestCase):
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

        # Set: POLICY_LZ_MARKET_ZONES (load zone, market, policy, zone)
        self.assertListEqual(
            sorted(LZ_MARKET_ZONES), sorted(instance.POLICY_LZ_MARKET_ZONES)
        )

        # Set: POLICY_MARKETS
        self.assertListEqual(
            ["Market_Hub_1", "Market_Hub_2"], sorted(instance.POLICY_MARKETS)
        )

        # Params: flat intensities (export defaults to 0 where unspecified)
        self.assertDictEqual(
            {LZ_MARKET_ZONES[0]: 0.4, LZ_MARKET_ZONES[1]: 0.4, LZ_MARKET_ZONES[2]: 0.6},
            {
                idx: instance.market_policy_co2_intensity_tons_per_mwh[idx]
                for idx in LZ_MARKET_ZONES
            },
        )
        self.assertDictEqual(
            {LZ_MARKET_ZONES[0]: 0, LZ_MARKET_ZONES[1]: 0.3, LZ_MARKET_ZONES[2]: 0},
            {
                idx: instance.market_policy_export_co2_intensity_tons_per_mwh[idx]
                for idx in LZ_MARKET_ZONES
            },
        )

        # Hourly adders (Market_Hub_1 only)
        for mrkt, tmp in instance.POLICY_MARKET_TMPS:
            self.assertEqual(
                0.1 if mrkt == "Market_Hub_1" else 0,
                instance.market_policy_co2_intensity_tons_per_mwh_hourly[mrkt, tmp],
            )

        # Sets: pair-zone-timepoints, split by the zone's basis
        expected = sorted(
            (lz, mrkt, *z, tmp)
            for (lz, mrkt, *z) in LZ_MARKET_ZONES
            for tmp in instance.TMPS
        )
        self.assertEqual(5, len(expected[0]))
        self.assertListEqual(expected, sorted(instance.POLICY_LZ_MARKET_ZONE_TMPS))
        self.assertListEqual(
            [idx for idx in expected if idx[2:4] == ZONE1],
            sorted(instance.GROSS_POLICY_LZ_MARKET_ZONE_TMPS),
        )
        self.assertListEqual(
            [idx for idx in expected if idx[2:4] == ZONE2],
            sorted(instance.NET_POLICY_LZ_MARKET_ZONE_TMPS),
        )

        # The variables and constraints follow the split
        n_tmps = len(instance.TMPS)
        self.assertEqual(
            2 * n_tmps, len(instance.Market_Policy_Import_Emissions_Constraint)
        )
        self.assertEqual(n_tmps, len(instance.Market_Policy_Import_MW_Constraint))

    def test_signed_import_emissions(self):
        """
        In a net zone the signed emissions are (I_imp - I_exp) * Import_MW +
        I_exp * final net purchased power, as for the carbon cap.
        """
        from gridpath.system.policy.import_emissions import POLICY
        from gridpath.system.markets.carbon_emissions_common import (
            signed_import_emissions_tons,
        )

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

        tmp = 20200101
        idx = ("Zone2", "Market_Hub_1", *ZONE2, tmp)
        # Intensities are 0.4 + 0.1 (import) and 0.3 + 0.05 (export)
        instance.Net_Market_Purchased_Power["Zone2", "Market_Hub_1", tmp].value = 10
        instance.Market_Policy_Import_MW[idx].value = 10
        self.assertAlmostEqual(
            5.0, value(signed_import_emissions_tons(instance, POLICY, idx))
        )
        instance.Net_Market_Purchased_Power["Zone2", "Market_Hub_1", tmp].value = -10
        instance.Market_Policy_Import_MW[idx].value = 0
        self.assertAlmostEqual(
            -3.5, value(signed_import_emissions_tons(instance, POLICY, idx))
        )


if __name__ == "__main__":
    unittest.main()
