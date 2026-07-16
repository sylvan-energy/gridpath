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
import pandas as pd
import shutil
import sys
import tempfile
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
    "geography.energy_target_zones",
    "transmission",
    "transmission.capacity",
    "transmission.capacity.capacity_types",
    "transmission.capacity.capacity",
    "transmission.availability.availability",
    "transmission.operations.operational_types",
    "transmission.operations.operations",
    "system.load_balance.aggregate_transmission_power",
]
NAME_OF_MODULE_BEING_TESTED = "transmission.operations.energy_target_contributions"
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


class TestTxEnergyTargetContributions(unittest.TestCase):
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

        # Set: ENERGY_TARGET_TX_LINES
        expected_tx_lines = sorted(["Tx_New", "Tx_binary_1"])
        actual_tx_lines = sorted([tx for tx in instance.ENERGY_TARGET_TX_LINES])
        self.assertListEqual(expected_tx_lines, actual_tx_lines)

        # Param: tx_energy_target_zone
        expected_zone = OrderedDict(
            sorted({"Tx_New": "RPS_Zone_1", "Tx_binary_1": "RPS_Zone_1"}.items())
        )
        actual_zone = OrderedDict(
            sorted(
                {
                    tx: instance.tx_energy_target_zone[tx]
                    for tx in instance.ENERGY_TARGET_TX_LINES
                }.items()
            )
        )
        self.assertDictEqual(expected_zone, actual_zone)

        # Set: ENERGY_TARGET_TX_LINES_BY_ENERGY_TARGET_ZONE
        expected_lines_by_zone = OrderedDict(
            sorted(
                {
                    "RPS_Zone_1": sorted(["Tx_New", "Tx_binary_1"]),
                    "RPS_Zone_2": [],
                }.items()
            )
        )
        actual_lines_by_zone = OrderedDict(
            sorted(
                {
                    z: sorted(
                        [
                            tx
                            for tx in instance.ENERGY_TARGET_TX_LINES_BY_ENERGY_TARGET_ZONE[
                                z
                            ]
                        ]
                    )
                    for z in instance.ENERGY_TARGET_ZONES
                }.items()
            )
        )
        self.assertDictEqual(expected_lines_by_zone, actual_lines_by_zone)

    def test_no_transmission_energy_target_inputs(self):
        """
        Transmission energy-target contributions are optional: if the user
        has not specified any transmission energy target inputs (no
        energy_target_zone column in transmission_lines.tab), the model
        should still build, with the transmission energy target components
        empty.
        :return:
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_data_dir = os.path.join(tmp_dir, "test_data")
            shutil.copytree(TEST_DATA_DIRECTORY, test_data_dir)
            tx_lines_file = os.path.join(
                test_data_dir, "inputs", "transmission_lines.tab"
            )
            df = pd.read_csv(tx_lines_file, sep="\t")
            df = df.drop(columns=["energy_target_zone"])
            df.to_csv(tx_lines_file, sep="\t", index=False)

            m, data = add_components_and_load_data(
                prereq_modules=IMPORTED_PREREQ_MODULES,
                module_to_test=MODULE_BEING_TESTED,
                test_data_dir=test_data_dir,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
            )
            instance = m.create_instance(data)

            self.assertListEqual([], [tx for tx in instance.ENERGY_TARGET_TX_LINES])
            self.assertListEqual(
                [], [idx for idx in instance.ENERGY_TARGET_TX_OPR_TMPS]
            )


if __name__ == "__main__":
    unittest.main()
