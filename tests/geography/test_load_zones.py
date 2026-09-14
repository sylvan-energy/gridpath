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
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "test_data")

# No prerequisite modules
NAME_OF_MODULE_BEING_TESTED = "geography.load_zones"

try:
    MODULE_BEING_TESTED = import_module(
        "." + NAME_OF_MODULE_BEING_TESTED, package="gridpath"
    )
except ImportError:
    print("ERROR! Couldn't import module " + NAME_OF_MODULE_BEING_TESTED + " to test.")


class TestLoadZones(unittest.TestCase):
    """ """

    def test_add_model_components(self):
        """
        Test that there are no errors when adding model components
        :return:
        """
        create_abstract_model(
            prereq_modules=[],
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
            prereq_modules=[],
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_load_zone_data_loads_correctly(self):
        """
        Create LOAD_ZONES set and load data; check resulting set is as expected
        :return:
        """
        m, data = add_components_and_load_data(
            prereq_modules=[],
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        instance = m.create_instance(data)
        expected = sorted(["Zone1", "Zone2", "Zone3", "Zone4"])
        actual = sorted([z for z in instance.LOAD_ZONES])
        self.assertListEqual(
            expected, actual, msg="LOAD_ZONES set data does not load correctly."
        )

        # Param: allow_overgeneration
        expected_allow_overgen = OrderedDict(
            sorted({"Zone1": 1, "Zone2": 1, "Zone3": 1, "Zone4": 1}.items())
        )
        actual_allow_overgen = OrderedDict(
            sorted(
                {
                    z: instance.allow_overgeneration[z] for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(expected_allow_overgen, actual_allow_overgen)

        # Param: overgeneration_penalty_per_mw
        expected_overgen_penalty = OrderedDict(
            sorted(
                {
                    "Zone1": 99999999,
                    "Zone2": 99999999,
                    "Zone3": 99999999,
                    "Zone4": 99999999,
                }.items()
            )
        )
        actual_overgen_penalty = OrderedDict(
            sorted(
                {
                    z: instance.overgeneration_penalty_per_mw[z]
                    for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(expected_overgen_penalty, actual_overgen_penalty)

        # Param: allow_unserved_energy
        expected_allow_unserved_energy = OrderedDict(
            sorted({"Zone1": 1, "Zone2": 1, "Zone3": 1, "Zone4": 1}.items())
        )
        actual_allow_unserved_energy = OrderedDict(
            sorted(
                {
                    z: instance.allow_overgeneration[z] for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(
            expected_allow_unserved_energy, actual_allow_unserved_energy
        )

        # Param: unserved_energy_penalty_per_mwh
        expected_unserved_energy_penalty = OrderedDict(
            sorted(
                {
                    "Zone1": 99999999,
                    "Zone2": 99999999,
                    "Zone3": 99999999,
                    "Zone4": 99999999,
                }.items()
            )
        )
        actual_unserved_energy_penalty = OrderedDict(
            sorted(
                {
                    z: instance.unserved_energy_penalty_per_mwh[z]
                    for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(
            expected_unserved_energy_penalty, actual_unserved_energy_penalty
        )

        # Param: unserved_energy_limit_mwh
        expected_unserved_energy_limit = OrderedDict(
            sorted(
                {
                    "Zone1": float("inf"),
                    "Zone2": float("inf"),
                    "Zone3": 100000,
                    "Zone4": 100000,
                }.items()
            )
        )
        actual_unserved_energy_limit = OrderedDict(
            sorted(
                {
                    z: instance.unserved_energy_limit_mwh[z]
                    for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(
            expected_unserved_energy_limit, actual_unserved_energy_limit
        )

        # Param: max_unserved_load_penalty_per_mw
        expected_max_unserved_load_penalty_per_mw = OrderedDict(
            sorted({"Zone1": 0, "Zone2": 0, "Zone3": 0, "Zone4": 0}.items())
        )
        actual_max_unserved_load_penalty_per_mw = OrderedDict(
            sorted(
                {
                    z: instance.max_unserved_load_penalty_per_mw[z]
                    for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(
            expected_max_unserved_load_penalty_per_mw,
            actual_max_unserved_load_penalty_per_mw,
        )

        # Param: max_unserved_load_limit_mw
        expected_unserved_load_limit = OrderedDict(
            sorted(
                {
                    "Zone1": 1000,
                    "Zone2": float("inf"),
                    "Zone3": float("inf"),
                    "Zone4": float("inf"),
                }.items()
            )
        )
        actual_unserved_load_limit = OrderedDict(
            sorted(
                {
                    z: instance.max_unserved_load_limit_mw[z]
                    for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(expected_unserved_load_limit, actual_unserved_load_limit)

        # Param: export_penalty_cost_per_mwh
        expected_export_penalty_cost_per_mwh = OrderedDict(
            sorted({"Zone1": 0, "Zone2": 0, "Zone3": 0, "Zone4": 0}.items())
        )
        actual_export_penalty_cost_per_mwh = OrderedDict(
            sorted(
                {
                    z: instance.export_penalty_cost_per_mwh[z]
                    for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(
            expected_export_penalty_cost_per_mwh, actual_export_penalty_cost_per_mwh
        )

        # Param: unserved_energy_stats_threshold_mw
        # Regression: this param was declared with default 0 but never read
        # from load_zones.tab, so database values were silently ignored.
        # Zone2 is unspecified (".") and must fall back to the default.
        expected_unserved_energy_stats_threshold_mw = OrderedDict(
            sorted({"Zone1": 1, "Zone2": 0, "Zone3": 5.5, "Zone4": 0}.items())
        )
        actual_unserved_energy_stats_threshold_mw = OrderedDict(
            sorted(
                {
                    z: instance.unserved_energy_stats_threshold_mw[z]
                    for z in instance.LOAD_ZONES
                }.items()
            )
        )
        self.assertDictEqual(
            expected_unserved_energy_stats_threshold_mw,
            actual_unserved_energy_stats_threshold_mw,
        )


if __name__ == "__main__":
    unittest.main()
