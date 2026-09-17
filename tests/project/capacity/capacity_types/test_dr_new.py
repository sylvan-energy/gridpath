# Copyright 2016-2023 Blue Marble Analytics LLC.
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
from types import SimpleNamespace

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
    "project",
]
NAME_OF_MODULE_BEING_TESTED = "project.capacity.capacity_types.dr_new"
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


class TestDRNew(unittest.TestCase):
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

        # Set: DR_NEW
        expected_projects = ["Shift_DR"]
        actual_projects = sorted([prj for prj in instance.DR_NEW])
        self.assertListEqual(expected_projects, actual_projects)

        # Set: DR_NEW_OPR_PRDS
        expected_opr_periods = [("Shift_DR", 2020), ("Shift_DR", 2030)]
        actual_opr_periods = [(dr, prd) for (dr, prd) in instance.DR_NEW_OPR_PRDS]
        self.assertListEqual(expected_opr_periods, actual_opr_periods)

        # Set: DR_NEW_FIN_PRDS
        expected_fin_periods = [("Shift_DR", 2020), ("Shift_DR", 2030)]
        actual_fin_periods = [(dr, prd) for (dr, prd) in instance.DR_NEW_FIN_PRDS]
        self.assertListEqual(expected_fin_periods, actual_fin_periods)

        # Param: dr_new_min_duration
        expected_duration = OrderedDict(sorted({"Shift_DR": 6}.items()))
        actual_duration = OrderedDict(
            sorted(
                {
                    prj: instance.dr_new_min_duration[prj] for prj in instance.DR_NEW
                }.items()
            )
        )
        self.assertDictEqual(expected_duration, actual_duration)

        # Param: dr_new_min_cumulative_new_build_mwh
        expected_min_build = OrderedDict(
            sorted({("Shift_DR", 2020): 1, ("Shift_DR", 2030): 2}.items())
        )
        actual_min_build = OrderedDict(
            sorted(
                {
                    (prj, p): instance.dr_new_min_cumulative_new_build_mwh[prj, p]
                    for prj in instance.DR_NEW
                    for p in instance.PERIODS
                }.items()
            )
        )
        self.assertDictEqual(expected_min_build, actual_min_build)

        # Param: dr_new_max_cumulative_new_build_mwh
        expected_potential = OrderedDict(
            sorted({("Shift_DR", 2020): 10, ("Shift_DR", 2030): 20}.items())
        )
        actual_potential = OrderedDict(
            sorted(
                {
                    (prj, p): instance.dr_new_max_cumulative_new_build_mwh[prj, p]
                    for prj in instance.DR_NEW
                    for p in instance.PERIODS
                }.items()
            )
        )
        self.assertDictEqual(expected_potential, actual_potential)

        # Set: DR_NEW_PTS
        expected_proj_points = [("Shift_DR", 1), ("Shift_DR", 2), ("Shift_DR", 3)]
        actual_proj_points = sorted([(prj, pnt) for (prj, pnt) in instance.DR_NEW_PTS])
        self.assertListEqual(expected_proj_points, actual_proj_points)

        # Param: dr_new_supply_curve_slope
        expected_slopes = {
            ("Shift_DR", 1): 25000,
            ("Shift_DR", 2): 50000,
            ("Shift_DR", 3): 75000,
        }
        actual_slopes = {
            (prj, pnt): instance.dr_new_supply_curve_slope[prj, pnt]
            for (prj, pnt) in instance.DR_NEW_PTS
        }
        self.assertDictEqual(expected_slopes, actual_slopes)

        # Param: dr_new_supply_curve_intercept
        expected_intercepts = {
            ("Shift_DR", 1): 0,
            ("Shift_DR", 2): -256987769,
            ("Shift_DR", 3): -616885503,
        }
        actual_intercepts = {
            (prj, pnt): instance.dr_new_supply_curve_intercept[prj, pnt]
            for (prj, pnt) in instance.DR_NEW_PTS
        }
        self.assertDictEqual(expected_intercepts, actual_intercepts)

        # Set: DR_NEW_OPR_PRDS
        expected_op_per = sorted([("Shift_DR", 2020), ("Shift_DR", 2030)])
        actual_op_per = sorted([(prj, per) for (prj, per) in instance.DR_NEW_OPR_PRDS])
        self.assertListEqual(expected_op_per, actual_op_per)

    def test_energy_stor_capacity_follows_period_tree(self):
        """
        Cumulative DR build in a period must sum the build in that period and
        its ancestors only. On a stochastic scenario tree (2020 -> 20301 and
        2020 -> 20302), build in the sibling branch 20301 must not count
        toward capacity in 20302 even though 20301 < 20302 numerically.
        """
        build = {
            ("Shift_DR", 2020): 1.0,
            ("Shift_DR", 20301): 10.0,
            ("Shift_DR", 20302): 100.0,
        }
        trajectory_prev_periods = {
            2020: [2020],
            20301: [20301, 2020],
            20302: [20302, 2020],
        }
        mock_mod = SimpleNamespace(
            PERIODS=[2020, 20301, 20302],
            DRNew_Build_MWh=build,
            FUTURE_TRAJECTORY_PREV_PERIODS_BY_PERIOD=trajectory_prev_periods,
        )

        expected = {2020: 1.0, 20301: 11.0, 20302: 101.0}
        actual = {
            p: MODULE_BEING_TESTED.dr_new_energy_stor_capacity_rule(
                mock_mod, "Shift_DR", p
            )
            for p in mock_mod.PERIODS
        }
        self.assertDictEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
