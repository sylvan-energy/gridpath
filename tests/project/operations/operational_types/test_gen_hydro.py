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
    "project",
    "project.capacity.capacity",
    "project.availability.availability",
    "project.fuels",
    "project.operations",
]
NAME_OF_MODULE_BEING_TESTED = "project.operations.operational_types.gen_hydro"
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


class TestGenHydro(unittest.TestCase):
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

    def test_capacity_data_load_correctly(self):
        """
        Test that are data loaded are as expected
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

        # Sets: GEN_HYDRO
        expected_projects = ["Hydro"]
        actual_projects = [p for p in instance.GEN_HYDRO]
        self.assertListEqual(expected_projects, actual_projects)

        # Sets: GEN_HYDRO_OPR_BT_HRZS
        expected_operational_horizons = sorted(
            [
                ("Hydro", "day", 202001),
                ("Hydro", "day", 202002),
                ("Hydro", "day", 203001),
                ("Hydro", "day", 203002),
            ]
        )
        actual_operational_horizons = sorted(
            [p for p in instance.GEN_HYDRO_OPR_BT_HRZS]
        )
        self.assertListEqual(expected_operational_horizons, actual_operational_horizons)

        # Param: gen_hydro_average_power_fraction
        expected_average_power = OrderedDict(
            sorted(
                {
                    ("Hydro", "day", 202001): 0.5,
                    ("Hydro", "day", 202002): 0.5,
                    ("Hydro", "day", 203001): 0.5,
                    ("Hydro", "day", 203002): 0.5,
                }.items()
            )
        )
        actual_average_power = OrderedDict(
            sorted(
                {
                    (prj, bt, horizon): instance.gen_hydro_average_power_fraction[
                        prj, bt, horizon
                    ]
                    for (prj, bt, horizon) in instance.GEN_HYDRO_OPR_BT_HRZS
                }.items()
            )
        )
        self.assertDictEqual(expected_average_power, actual_average_power)

        # Param: gen_hydro_min_power_fraction
        expected_min_power = OrderedDict(
            sorted(
                {
                    ("Hydro", "day", 202001): 0.15,
                    ("Hydro", "day", 202002): 0.15,
                    ("Hydro", "day", 203001): 0.15,
                    ("Hydro", "day", 203002): 0.15,
                }.items()
            )
        )
        actual_min_power = OrderedDict(
            sorted(
                {
                    (prj, bt, horizon): instance.gen_hydro_min_power_fraction[
                        prj, bt, horizon
                    ]
                    for (prj, bt, horizon) in instance.GEN_HYDRO_OPR_BT_HRZS
                }.items()
            )
        )
        self.assertDictEqual(expected_min_power, actual_min_power)

        # Param: gen_hydro_max_power_fraction
        expected_max_power = OrderedDict(
            sorted(
                {
                    ("Hydro", "day", 202001): 1,
                    ("Hydro", "day", 202002): 1,
                    ("Hydro", "day", 203001): 1,
                    ("Hydro", "day", 203002): 1,
                }.items()
            )
        )
        actual_max_power = OrderedDict(
            sorted(
                {
                    (prj, bt, horizon): instance.gen_hydro_max_power_fraction[
                        prj, bt, horizon
                    ]
                    for (prj, bt, horizon) in instance.GEN_HYDRO_OPR_BT_HRZS
                }.items()
            )
        )
        self.assertDictEqual(expected_max_power, actual_max_power)

        # GEN_HYDRO_OPR_TMPS
        expected_tmps = sorted(get_project_operational_timepoints(expected_projects))
        actual_tmps = sorted([tmp for tmp in instance.GEN_HYDRO_OPR_TMPS])
        self.assertListEqual(expected_tmps, actual_tmps)

        # Param: gen_hydro_ramp_up_when_on_rate
        expected_ramp_up = OrderedDict(sorted({"Hydro": 0.5}.items()))
        actual_ramp_up = OrderedDict(
            sorted(
                {
                    prj: instance.gen_hydro_ramp_up_when_on_rate[prj]
                    for prj in instance.GEN_HYDRO
                }.items()
            )
        )
        self.assertDictEqual(expected_ramp_up, actual_ramp_up)

        # Param: gen_hydro_ramp_down_when_on_rate
        expected_ramp_down = OrderedDict(sorted({"Hydro": 0.5}.items()))
        actual_ramp_down = OrderedDict(
            sorted(
                {
                    prj: instance.gen_hydro_ramp_down_when_on_rate[prj]
                    for prj in instance.GEN_HYDRO
                }.items()
            )
        )
        self.assertDictEqual(expected_ramp_down, actual_ramp_down)

        # Sets: GEN_HYDRO_BUDGET_ALLOC_BT_HRZS (the fixture file has no rows
        # for gen_hydro projects; see test_gen_hydro_must_take for loaded
        # limits)
        self.assertListEqual([], list(instance.GEN_HYDRO_BUDGET_ALLOC_BT_HRZS))


if __name__ == "__main__":
    unittest.main()
