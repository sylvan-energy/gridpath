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


from collections import OrderedDict
from importlib import import_module
import os.path
import sys
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.carbon_cap_zones",
    "system.policy.carbon_cap.carbon_cap",
    "transmission",
    "transmission.capacity",
    "transmission.capacity.capacity_types",
    "transmission.capacity.capacity",
    "transmission.availability.availability",
    "transmission.operations.operational_types",
    "transmission.operations.operations",
    "system.load_balance.aggregate_transmission_power",
]
NAME_OF_MODULE_BEING_TESTED = "transmission.operations.tx_curtailment_costs"
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


class TestTxCurtailmentCosts(unittest.TestCase):
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

        # Set: TX_CURTAILMENT_COST_TX_LINE_PRDS
        expected_tx_prds = sorted(
            [
                ("Tx_New", 2020),
                ("Tx_New", 2030),
                ("Tx_binary_1", 2020),
                ("Tx_binary_1", 2030),
            ]
        )
        actual_tx_prds = sorted(
            [(tx, prd) for (tx, prd) in instance.TX_CURTAILMENT_COST_TX_LINE_PRDS]
        )
        self.assertListEqual(expected_tx_prds, actual_tx_prds)

        # Set: TX_CURTAILMENT_COST_TX_LINES
        expected_tx_lines = sorted(["Tx_New", "Tx_binary_1"])
        actual_tx_lines = sorted([tx for tx in instance.TX_CURTAILMENT_COST_TX_LINES])
        self.assertListEqual(expected_tx_lines, actual_tx_lines)

        # Param: tx_curtailment_cost_per_powerunithour
        expected_cost = OrderedDict(
            sorted(
                {
                    ("Tx_New", 2020): 10,
                    ("Tx_New", 2030): 10,
                    ("Tx_binary_1", 2020): 5,
                    ("Tx_binary_1", 2030): 0,
                }.items()
            )
        )
        actual_cost = OrderedDict(
            sorted(
                {
                    (tx, prd): instance.tx_curtailment_cost_per_powerunithour[tx, prd]
                    for (tx, prd) in instance.TX_CURTAILMENT_COST_TX_LINE_PRDS
                }.items()
            )
        )
        self.assertDictEqual(expected_cost, actual_cost)

        # Param: tx_losses_factor_curtailment
        expected_factor = OrderedDict(
            sorted(
                {
                    "Tx1": 1,
                    "Tx_New": 0.5,
                    "Tx2": 1,
                    "Tx3": 1,
                    "Tx_binary_1": 1,
                }.items()
            )
        )
        actual_factor = OrderedDict(
            sorted(
                {
                    tx: instance.tx_losses_factor_curtailment[tx]
                    for tx in instance.TX_LINES
                }.items()
            )
        )
        self.assertDictEqual(expected_factor, actual_factor)
