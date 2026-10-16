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
    "geography.generic_policy",
    "transmission",
    "transmission.capacity",
    "transmission.capacity.capacity_types",
    "transmission.capacity.capacity",
    "transmission.availability.availability",
    "transmission.operations.operational_types",
    "transmission.operations.operations",
]
NAME_OF_MODULE_BEING_TESTED = "transmission.policy.import_emissions"
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

# The test data assign Tx1 and Tx_New to the Carbon policy's CarbonZone1
# (gross basis) and Tx_New also to its CarbonZone2 (net_prd basis), with an
# export intensity; the zone key is the (policy, zone) pair
ZONE1 = ("Carbon", "CarbonZone1")
ZONE2 = ("Carbon", "CarbonZone2")
LINE_ZONES = [("Tx1", *ZONE1), ("Tx_New", *ZONE1), ("Tx_New", *ZONE2)]


class TestTxPolicyImportEmissions(unittest.TestCase):
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

        # Param: policy_import_emissions_basis (from the geography)
        self.assertEqual("gross", instance.policy_import_emissions_basis[ZONE1])
        self.assertEqual("net_prd", instance.policy_import_emissions_basis[ZONE2])
        self.assertEqual(
            "gross", instance.policy_import_emissions_basis["RPS", "RPSZone1"]
        )

        # Set: POLICY_TX_LINE_ZONES (line, policy, zone)
        self.assertListEqual(sorted(LINE_ZONES), sorted(instance.POLICY_TX_LINE_ZONES))

        # Set: POLICY_TX_LINES
        self.assertListEqual(["Tx1", "Tx_New"], sorted(instance.POLICY_TX_LINES))

        # Set: POLICY_TX_LINES_BY_ZONE, indexed by the (policy, zone) pairs
        self.assertDictEqual(
            {ZONE1: ["Tx1", "Tx_New"], ZONE2: ["Tx_New"]},
            {z: sorted(instance.POLICY_TX_LINES_BY_ZONE[z]) for z in [ZONE1, ZONE2]},
        )
        self.assertListEqual(
            [], list(instance.POLICY_TX_LINES_BY_ZONE["RPS", "RPSZone1"])
        )

        # Params: direction and flat intensities
        self.assertDictEqual(
            {
                ("Tx1", *ZONE1): "negative",
                ("Tx_New", *ZONE1): "negative",
                ("Tx_New", *ZONE2): "positive",
            },
            dict(instance.tx_policy_import_direction.items()),
        )
        self.assertDictEqual(
            {("Tx1", *ZONE1): 0.6, ("Tx_New", *ZONE1): 0.8, ("Tx_New", *ZONE2): 0.5},
            {
                idx: instance.tx_policy_co2_intensity_tons_per_mwh[idx]
                for idx in LINE_ZONES
            },
        )
        self.assertDictEqual(
            {("Tx1", *ZONE1): 0, ("Tx_New", *ZONE1): 0, ("Tx_New", *ZONE2): 0.2},
            {
                idx: instance.tx_policy_export_co2_intensity_tons_per_mwh[idx]
                for idx in LINE_ZONES
            },
        )

        # Hourly adders
        for tx, tmp in instance.POLICY_TX_OPR_TMPS:
            self.assertEqual(
                0.1 if tx == "Tx1" else 0.2,
                instance.tx_policy_co2_intensity_tons_per_mwh_hourly[tx, tmp],
            )

        # Sets: line-zone-timepoints, split by the zone's basis
        expected_line_zone_tmps = sorted(
            (tx, *z, tmp)
            for (tx, *z) in LINE_ZONES
            for (l, tmp) in instance.POLICY_TX_OPR_TMPS
            if l == tx
        )
        self.assertEqual(4, len(expected_line_zone_tmps[0]))
        self.assertListEqual(
            expected_line_zone_tmps, sorted(instance.POLICY_TX_LINE_ZONE_OPR_TMPS)
        )
        self.assertListEqual(
            [idx for idx in expected_line_zone_tmps if idx[1:3] == ZONE1],
            sorted(instance.GROSS_POLICY_TX_LINE_ZONE_OPR_TMPS),
        )
        self.assertListEqual(
            [idx for idx in expected_line_zone_tmps if idx[1:3] == ZONE2],
            sorted(instance.NET_POLICY_TX_LINE_ZONE_OPR_TMPS),
        )

        # The variables and constraints follow the split
        self.assertEqual(192, len(instance.Tx_Policy_Import_Emissions_Constraint))
        self.assertEqual(96, len(instance.Tx_Policy_Import_MW_Constraint))

    def test_signed_import_emissions(self):
        """
        In a net zone the signed emissions are (I_imp - I_exp) * Import_MW +
        I_exp * flow into the zone, as for the carbon cap.
        """
        from gridpath.system.policy.import_emissions import POLICY
        from gridpath.transmission.operations.carbon_emissions_common import (
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
        idx = ("Tx_New", *ZONE2, tmp)
        # Intensities are 0.5 + 0.2 (import) and 0.2 + 0.05 (export)
        instance.TxSimple_Transmit_Power_MW["Tx_New", tmp].value = 10
        instance.Tx_Policy_Import_MW[idx].value = 10
        self.assertAlmostEqual(
            7.0, value(signed_import_emissions_tons(instance, POLICY, idx))
        )
        instance.TxSimple_Transmit_Power_MW["Tx_New", tmp].value = -10
        instance.Tx_Policy_Import_MW[idx].value = 0
        self.assertAlmostEqual(
            -2.5, value(signed_import_emissions_tons(instance, POLICY, idx))
        )


if __name__ == "__main__":
    unittest.main()
