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
import pandas as pd
from pyomo.environ import value
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
    "geography.markets",
    "geography.carbon_tax_zones",
    "system.markets.prices",
    "project",
    "project.capacity.capacity",
    "project.availability.availability",
    "project.fuels",
    "project.operations",
]
NAME_OF_MODULE_BEING_TESTED = (
    "project.operations.operational_types.gen_simple_strike_price"
)
# Most scenarios do not have the carbon tax feature, in which case none of the
# carbon tax modules are loaded at all; TestGenSimpleStrikePriceNoCarbonTax
# checks that the operational type works in that (more common) configuration
PREREQUISITE_MODULE_NAMES_NO_CARBON_TAX = [
    mdl for mdl in PREREQUISITE_MODULE_NAMES if mdl != "geography.carbon_tax_zones"
]

IMPORTED_PREREQ_MODULES = list()
for mdl in PREREQUISITE_MODULE_NAMES:
    try:
        imported_module = import_module("." + str(mdl), package="gridpath")
        IMPORTED_PREREQ_MODULES.append(imported_module)
    except ImportError:
        print("ERROR! Module " + str(mdl) + " not found.")
        sys.exit(1)

IMPORTED_PREREQ_MODULES_NO_CARBON_TAX = [
    m
    for mdl, m in zip(PREREQUISITE_MODULE_NAMES, IMPORTED_PREREQ_MODULES)
    if mdl in PREREQUISITE_MODULE_NAMES_NO_CARBON_TAX
]
# Import the module we'll test
try:
    MODULE_BEING_TESTED = import_module(
        "." + NAME_OF_MODULE_BEING_TESTED, package="gridpath"
    )
except ImportError:
    print("ERROR! Couldn't import module " + NAME_OF_MODULE_BEING_TESTED + " to test.")


# The fixture projects, with every number below traceable to a file in
# tests/test_data/inputs:
#
# 'Gen_Strike_Price' burns Gas at a constant heat rate of 1.1 MMBtu/MWh
# (heat_rate_curves.tab) with a fuel price of 5/MMBtu (fuel_prices.tab) and a
# variable O&M cost of 2/MWh (projects.tab). It is in Carbon_Tax_Zone1
# (projects.tab), which taxes carbon at 30/tCO2 in 2020 and 50/tCO2 in 2030
# (carbon_tax.tab); Gas emits 0.05306 tCO2/MMBtu (fuels.tab) and the project
# is allowed 0.01 tCO2/MWh in 2020 and 0.005 in 2030
# (project_carbon_tax_allowance.tab). Its marginal cost is therefore
# 8.95098/MWh in 2020 and 10.1683/MWh in 2030: the carbon tax alone puts it
# above the high market price of 10 in 2030 but not in 2020.
#
# 'Gen_Strike_Price_Tie' has no fuel and a variable O&M cost of 10/MWh, which
# is exactly the high market price, and breaks the tie toward generating. It
# is in no carbon tax zone, so the carbon tax never touches its marginal cost.
HEAT_RATE = 1.1
FUEL_PRICE = 5
CO2_INTENSITY = 0.05306
EXPECTED_MARGINAL_COST = {
    ("Gen_Strike_Price", 2020): (
        HEAT_RATE * FUEL_PRICE + 2 + 30 * (HEAT_RATE * CO2_INTENSITY - 0.01)
    ),
    ("Gen_Strike_Price", 2030): (
        HEAT_RATE * FUEL_PRICE + 2 + 50 * (HEAT_RATE * CO2_INTENSITY - 0.005)
    ),
    ("Gen_Strike_Price_Tie", 2020): 10,
    ("Gen_Strike_Price_Tie", 2030): 10,
}
EXPECTED_MARKET = {
    "Gen_Strike_Price": "Market_Hub_1",
    "Gen_Strike_Price_Tie": "Market_Hub_2",
}
EXPECTED_TIE_BREAK = {"Gen_Strike_Price": 0, "Gen_Strike_Price_Tie": 1}


class TestGenSimpleStrikePrice(unittest.TestCase):
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
        Test that the data loaded are as expected
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

        # Set: GEN_SIMPLE_STRIKE_PRICE
        expected_gen_set = sorted(["Gen_Strike_Price", "Gen_Strike_Price_Tie"])
        actual_gen_set = sorted([prj for prj in instance.GEN_SIMPLE_STRIKE_PRICE])
        self.assertListEqual(expected_gen_set, actual_gen_set)

        # Set: GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS
        expected_operational_timepoints_by_project = sorted(
            get_project_operational_timepoints(expected_gen_set)
        )
        actual_operational_timepoints_by_project = sorted(
            [(g, tmp) for (g, tmp) in instance.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS]
        )
        self.assertListEqual(
            expected_operational_timepoints_by_project,
            actual_operational_timepoints_by_project,
        )

        # Param: gen_simple_strike_price_market
        actual_market = {
            prj: instance.gen_simple_strike_price_market[prj]
            for prj in instance.GEN_SIMPLE_STRIKE_PRICE
        }
        self.assertDictEqual(EXPECTED_MARKET, actual_market)

        # Param: gen_simple_strike_price_dispatch_at_equal_cost
        actual_tie_break = {
            prj: instance.gen_simple_strike_price_dispatch_at_equal_cost[prj]
            for prj in instance.GEN_SIMPLE_STRIKE_PRICE
        }
        self.assertDictEqual(EXPECTED_TIE_BREAK, actual_tie_break)

        # Param: GenSimpleStrikePrice_Marginal_Cost_per_MWh
        for g, tmp in instance.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS:
            self.assertAlmostEqual(
                EXPECTED_MARGINAL_COST[g, instance.period[tmp]],
                instance.GenSimpleStrikePrice_Marginal_Cost_per_MWh[g, tmp],
                places=9,
                msg="marginal cost of {} in timepoint {}".format(g, tmp),
            )

        # Param: GenSimpleStrikePrice_Online
        # Compute the expected dispatch from the market prices on file rather
        # than from the model, so that the test is an independent check
        prices_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "market_prices.tab"), sep="\t"
        )
        prices = prices_df.set_index(["market", "timepoint"]).to_dict()["price"]

        expected_online = {}
        for g, tmp in instance.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS:
            marginal_cost = EXPECTED_MARGINAL_COST[g, instance.period[tmp]]
            price = prices[EXPECTED_MARKET[g], tmp]
            if marginal_cost < price:
                expected_online[g, tmp] = 1
            elif marginal_cost > price:
                expected_online[g, tmp] = 0
            else:
                expected_online[g, tmp] = EXPECTED_TIE_BREAK[g]

        actual_online = {
            (g, tmp): instance.GenSimpleStrikePrice_Online[g, tmp]
            for (g, tmp) in instance.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS
        }
        self.assertDictEqual(expected_online, actual_online)

        # The fixture is only a meaningful test of the dispatch logic if both
        # outcomes actually occur, including the tie
        self.assertEqual(
            {0, 1}, set(expected_online.values()), "fixture exercises both outcomes"
        )
        tie_tmps = [
            tmp
            for (g, tmp) in expected_online
            if g == "Gen_Strike_Price_Tie"
            and prices["Market_Hub_2", tmp]
            == EXPECTED_MARGINAL_COST[g, instance.period[tmp]]
        ]
        self.assertTrue(tie_tmps, "fixture exercises the tie-break")

        # The carbon tax must change a dispatch decision, or this fixture
        # would pass just as well with the carbon tax term missing entirely:
        # without it 'Gen_Strike_Price' would cost 7.5/MWh in every period and
        # so would generate whenever the price is 10, including in 2030
        cost_without_carbon_tax = HEAT_RATE * FUEL_PRICE + 2
        flipped = [
            (g, tmp)
            for (g, tmp) in expected_online
            if g == "Gen_Strike_Price"
            and expected_online[g, tmp] == 0
            and cost_without_carbon_tax < prices[EXPECTED_MARKET[g], tmp]
        ]
        self.assertTrue(
            flipped, "fixture exercises the carbon tax changing the dispatch"
        )

    def test_dispatch_rules(self):
        """
        Test that power provision and fuel burn are the available capacity
        (times the heat rate, for fuel burn) when the project generates and
        zero when it does not.
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

        for g, tmp in instance.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS:
            online = instance.GenSimpleStrikePrice_Online[g, tmp]
            available_capacity = value(
                instance.Capacity_MW[g, instance.period[tmp]]
                * instance.Availability_Derate[g, tmp]
            )

            expected_power = available_capacity if online else 0
            self.assertEqual(
                expected_power,
                value(MODULE_BEING_TESTED.power_provision_rule(instance, g, tmp)),
            )

            if g == "Gen_Strike_Price":
                expected_fuel_burn = HEAT_RATE * available_capacity if online else 0
                self.assertAlmostEqual(
                    expected_fuel_burn,
                    value(MODULE_BEING_TESTED.fuel_burn_rule(instance, g, tmp)),
                    places=9,
                )


class TestGenSimpleStrikePriceNoCarbonTax(unittest.TestCase):
    """
    The carbon tax feature is optional, and a scenario without it does not
    load any of the carbon tax modules, so none of their inputs or parameters
    exist. Check that the operational type builds, loads and dispatches on
    fuel and variable O&M cost alone in that case.
    """

    def build(self):
        m, data = add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES_NO_CARBON_TAX,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        return m.create_instance(data)

    def test_add_model_components(self):
        """
        Test that there are no errors when adding model components
        :return:
        """
        create_abstract_model(
            prereq_modules=IMPORTED_PREREQ_MODULES_NO_CARBON_TAX,
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
            prereq_modules=IMPORTED_PREREQ_MODULES_NO_CARBON_TAX,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_no_carbon_tax_components(self):
        """
        Test that none of the carbon tax parameters are declared
        :return:
        """
        instance = self.build()

        for component in [
            "gen_simple_strike_price_carbon_tax_zone",
            "gen_simple_strike_price_carbon_tax_allowance",
            "gen_simple_strike_price_carbon_tax",
            "GEN_SIMPLE_STRIKE_PRICE_CARBON_TAX_ZONE_PRDS",
        ]:
            self.assertFalse(
                hasattr(instance, component),
                "{} should not be declared without the carbon tax "
                "feature".format(component),
            )

    def test_marginal_cost_without_carbon_tax(self):
        """
        Test that the marginal cost is the fuel cost plus the variable O&M
        cost, with no carbon tax component, and that the dispatch follows
        :return:
        """
        instance = self.build()

        # 'Gen_Strike_Price' burns 1.1 MMBtu/MWh of Gas at 5/MMBtu and has a
        # variable O&M cost of 2/MWh; 'Gen_Strike_Price_Tie' has no fuel and a
        # variable O&M cost of 10/MWh
        expected_marginal_cost = {
            "Gen_Strike_Price": HEAT_RATE * FUEL_PRICE + 2,
            "Gen_Strike_Price_Tie": 10,
        }

        prices_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "market_prices.tab"), sep="\t"
        )
        prices = prices_df.set_index(["market", "timepoint"]).to_dict()["price"]

        for g, tmp in instance.GEN_SIMPLE_STRIKE_PRICE_OPR_TMPS:
            marginal_cost = expected_marginal_cost[g]
            self.assertAlmostEqual(
                marginal_cost,
                instance.GenSimpleStrikePrice_Marginal_Cost_per_MWh[g, tmp],
                places=9,
                msg="marginal cost of {} in timepoint {}".format(g, tmp),
            )

            price = prices[EXPECTED_MARKET[g], tmp]
            if marginal_cost < price:
                expected_online = 1
            elif marginal_cost > price:
                expected_online = 0
            else:
                expected_online = EXPECTED_TIE_BREAK[g]
            self.assertEqual(
                expected_online,
                instance.GenSimpleStrikePrice_Online[g, tmp],
                "dispatch of {} in timepoint {}".format(g, tmp),
            )

        # 'Gen_Strike_Price' is taxed for carbon in the fixture, so without the
        # carbon tax modules it must cost less than it does with them, or this
        # test would pass even if the carbon tax leaked in
        self.assertLess(
            expected_marginal_cost["Gen_Strike_Price"],
            EXPECTED_MARGINAL_COST["Gen_Strike_Price", 2020],
        )


if __name__ == "__main__":
    unittest.main()
