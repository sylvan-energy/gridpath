# Copyright 2016-2023 Blue Marble Analytics LLC.
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
import shutil
import sys
import tempfile
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "geography.load_zones",
    "transmission",
]
NAME_OF_MODULE_BEING_TESTED = "transmission.capacity.capacity_types.tx_spec"
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


class TestSpecifiedTransmission(unittest.TestCase):
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

        # Set: TX_SPEC_OPR_PRDS
        expected_periods = [
            ("Tx1", 2020),
            ("Tx1", 2030),
            ("Tx2", 2020),
            ("Tx2", 2030),
            ("Tx3", 2020),
            ("Tx3", 2030),
            ("Tx_binary_1", 2020),
            ("Tx_binary_1", 2030),
        ]
        actual_periods = sorted([(tx, p) for (tx, p) in instance.TX_SPEC_OPR_PRDS])
        self.assertListEqual(expected_periods, actual_periods)

        # Param: tx_spec_min_cap_mw
        expected_min = OrderedDict(
            sorted(
                {
                    ("Tx1", 2020): -10,
                    ("Tx1", 2030): -10,
                    ("Tx2", 2020): -10,
                    ("Tx2", 2030): -10,
                    ("Tx3", 2020): -10,
                    ("Tx3", 2030): -10,
                    ("Tx_binary_1", 2020): -10,
                    ("Tx_binary_1", 2030): -10,
                }.items()
            )
        )
        actual_min = OrderedDict(
            sorted(
                {
                    (tx, p): instance.tx_spec_min_cap_mw[tx, p]
                    for (tx, p) in instance.TX_SPEC_OPR_PRDS
                }.items()
            )
        )
        self.assertDictEqual(expected_min, actual_min)

        # Param: specified_tx_max_mw
        expected_max = OrderedDict(
            sorted(
                {
                    ("Tx1", 2020): 10,
                    ("Tx1", 2030): 10,
                    ("Tx2", 2020): 10,
                    ("Tx2", 2030): 10,
                    ("Tx3", 2020): 10,
                    ("Tx3", 2030): 10,
                    ("Tx_binary_1", 2020): 10,
                    ("Tx_binary_1", 2030): 10,
                }.items()
            )
        )
        actual_max = OrderedDict(
            sorted(
                {
                    (tx, p): instance.tx_spec_max_cap_mw[tx, p]
                    for (tx, p) in instance.TX_SPEC_OPR_PRDS
                }.items()
            )
        )
        self.assertDictEqual(expected_max, actual_max)

        # Param: tx_spec_fixed_cost_per_mw_yr
        expected_fixed_cost = OrderedDict(
            sorted(
                {
                    ("Tx1", 2020): 0,
                    ("Tx1", 2030): 5,
                    ("Tx2", 2020): 0,
                    ("Tx2", 2030): 5,
                    ("Tx3", 2020): 0,
                    ("Tx3", 2030): 5,
                    ("Tx_binary_1", 2020): 0,
                    ("Tx_binary_1", 2030): 5,
                }.items()
            )
        )
        actual_fixed_cost = OrderedDict(
            sorted(
                {
                    (tx, p): instance.tx_spec_fixed_cost_per_mw_yr[tx, p]
                    for (tx, p) in instance.TX_SPEC_OPR_PRDS
                }.items()
            )
        )
        self.assertDictEqual(expected_fixed_cost, actual_fixed_cost)

    def test_blank_caps_are_unconstrained(self):
        """A blank min/max leaves the line-period in TX_SPEC_OPR_PRDS but sets
        the capacity param to its +/-inf default (i.e. no flow limit)."""
        tmp_dir = tempfile.mkdtemp()
        try:
            staged = os.path.join(tmp_dir, "test_data")
            shutil.copytree(TEST_DATA_DIRECTORY, staged)
            cap_file = os.path.join(
                staged, "inputs", "specified_transmission_line_capacities.tab"
            )
            # Blank Tx1's max (2020) and Tx2's min (2020); leave the rows in place.
            rows = open(cap_file).read().split("\n")
            out = []
            for r in rows:
                f = r.split("\t")
                if f[0] == "Tx1" and f[1] == "2020":
                    f[3] = "."  # specified_tx_max_mw -> no upper limit
                    r = "\t".join(f)
                elif f[0] == "Tx2" and f[1] == "2020":
                    f[2] = "."  # specified_tx_min_mw -> no lower limit
                    r = "\t".join(f)
                out.append(r)
            open(cap_file, "w").write("\n".join(out))

            m, data = add_components_and_load_data(
                prereq_modules=IMPORTED_PREREQ_MODULES,
                module_to_test=MODULE_BEING_TESTED,
                test_data_dir=staged,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
            )
            instance = m.create_instance(data)

            # Row still present (so the line stays operational / in TX_OPR_PRDS).
            self.assertIn(("Tx1", 2020), list(instance.TX_SPEC_OPR_PRDS))
            self.assertIn(("Tx2", 2020), list(instance.TX_SPEC_OPR_PRDS))

            # Blank cells fall back to the +/-inf defaults.
            self.assertEqual(
                instance.tx_spec_max_cap_mw["Tx1", 2020], float("inf")
            )
            self.assertEqual(
                instance.tx_spec_min_cap_mw["Tx2", 2020], float("-inf")
            )
            # The non-blank direction on each line is unaffected.
            self.assertEqual(instance.tx_spec_min_cap_mw["Tx1", 2020], -10)
            self.assertEqual(instance.tx_spec_max_cap_mw["Tx2", 2020], 10)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
