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
    "system.markets.market_participation",
    "system.markets.policy_import_emissions",
]
NAME_OF_MODULE_BEING_TESTED = (
    "system.policy.generic_policy.policy_requirement_base_markets"
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


class TestPolicyRequirementBaseMarkets(unittest.TestCase):
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

        # Set: POLICY_ZONE_BASE_LZ_MARKETS
        expected_base_markets = sorted(
            [
                ("Carbon", "CarbonZone1", "Zone1", "Market_Hub_1", "net_purchases"),
                ("Carbon", "CarbonZone1", "Zone1", "Market_Hub_2", "purchases"),
                ("Carbon", "CarbonZone1", "Zone1", "Market_Hub_2", "sales"),
            ]
        )
        self.assertListEqual(
            expected_base_markets, sorted(instance.POLICY_ZONE_BASE_LZ_MARKETS)
        )

        # Param: policy_market_base_multiplier (unspecified defaults to 1)
        expected_multiplier = {
            ("Carbon", "CarbonZone1", "Zone1", "Market_Hub_1", "net_purchases"): 1,
            ("Carbon", "CarbonZone1", "Zone1", "Market_Hub_2", "purchases"): 1,
            ("Carbon", "CarbonZone1", "Zone1", "Market_Hub_2", "sales"): 0.1,
        }
        actual_multiplier = {
            idx: instance.policy_market_base_multiplier[idx]
            for idx in instance.POLICY_ZONE_BASE_LZ_MARKETS
        }
        self.assertDictEqual(expected_multiplier, actual_multiplier)

        # Expression: Total_Market_Policy_Zone_Base is the net purchases of
        # Zone1-Market_Hub_1 plus the gross purchases and 0.1 times the gross
        # sales of Zone1-Market_Hub_2, the gross purchases being the counted
        # import emissions over the import intensity (0.6) and the gross
        # sales those purchases less the net position; the RPS policy has no
        # base markets
        base = instance.Total_Market_Policy_Zone_Base
        net = instance.Final_Net_Market_Purchased_Power
        emissions = instance.Market_Policy_Import_Emissions_Tons
        for h in [2020, 2030]:
            self.assertEqual(
                linear_repn(0), linear_repn(base["RPS", "RPSZone1", "year", h])
            )

            expected = 0
            for tmp in instance.TMPS_BY_BLN_TYPE_HRZ["year", h]:
                purchases = (
                    emissions["Zone1", "Market_Hub_2", "Carbon", "CarbonZone1", tmp]
                    / 0.6
                )
                expected += (
                    net["Zone1", "Market_Hub_1", tmp]
                    + purchases
                    + 0.1 * (purchases - net["Zone1", "Market_Hub_2", tmp])
                ) * (instance.hrs_in_tmp[tmp] * instance.tmp_weight[tmp])
            self.assertTrue(linear_coefficients_by_var(expected))
            self.assertEqual(
                linear_repn(expected),
                linear_repn(base["Carbon", "CarbonZone1", "year", h]),
            )

    def test_inexact_gross_base_refused(self):
        """
        The model refuses to build gross base rows whose import intensity is
        below the base coefficient times the pair's gross multipliers (2020:
        0.6 < 0.5 x (1 + 0.5)), whose pair does not count its import
        emissions toward the zone (Zone2-Market_Hub_1 counts toward
        CarbonZone2 only) or whose zone has 'min' requirements
        """
        bad_rows = {
            "intensity": (
                ("Carbon", "CarbonZone1", "Zone1", "Market_Hub_2", "sales"),
                0.5,
                "at least the base coefficient",
            ),
            "unmapped": (
                ("Carbon", "CarbonZone1", "Zone2", "Market_Hub_1", "purchases"),
                1,
                "count its import emissions",
            ),
            "min_sense": (
                ("RPS", "RPSZone1", "Zone1", "Market_Hub_2", "sales"),
                1,
                "'max' requirements",
            ),
        }
        for case, (idx, multiplier, message) in bad_rows.items():
            with self.subTest(case=case):
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
                rows = data.data()["POLICY_ZONE_BASE_LZ_MARKETS"]
                rows[None] = sorted(set(rows[None]) | {idx})
                data.data()["policy_market_base_multiplier"][idx] = multiplier
                with self.assertRaisesRegex(ValueError, message):
                    m.create_instance(data)


def linear_coefficients_by_var(expr):
    """
    The linear coefficient of each variable in the expression, keyed by the
    variable's name.
    """
    repn = generate_standard_repn(expr)
    return {var.name: coef for var, coef in zip(repn.linear_vars, repn.linear_coefs)}


def linear_repn(expr):
    """
    The constant and the linear coefficients by variable name of the
    expression, for comparing two linear expressions.
    """
    return (
        generate_standard_repn(expr).constant,
        linear_coefficients_by_var(expr),
    )


if __name__ == "__main__":
    unittest.main()
