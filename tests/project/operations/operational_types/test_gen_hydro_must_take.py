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

from pyomo.core.expr.visitor import identify_variables
from pyomo.environ import value

from gridpath.project.common_functions import get_energy_budget_balancing_type
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
NAME_OF_MODULE_BEING_TESTED = "project.operations.operational_types.gen_hydro_must_take"
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


def rhs_at_zero_vars(constraint):
    """
    The right-hand side of a less-than-or-equal constraint: its upper bound
    minus the constant part of its body (Pyomo may fold a param-valued
    right-hand side into the body).
    """
    assert constraint.lower is None
    body_vars = list(identify_variables(constraint.body))
    saved = [v.value for v in body_vars]
    for v in body_vars:
        v.set_value(0, skip_validation=True)
    rhs = value(constraint.upper) - value(constraint.body)
    for v, val in zip(body_vars, saved):
        v.set_value(val, skip_validation=True)
    return rhs


class TestGenHydroMustTake(unittest.TestCase):
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

        # Sets: GEN_HYDRO_MUST_TAKE
        expected_projects = ["Hydro_NonCurtailable"]
        actual_projects = [p for p in instance.GEN_HYDRO_MUST_TAKE]
        self.assertListEqual(expected_projects, actual_projects)

        # Sets: GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS
        expected_operational_horizons = sorted(
            [
                ("Hydro_NonCurtailable", "year", 2020),
                ("Hydro_NonCurtailable", "year", 2030),
            ]
        )
        actual_operational_horizons = sorted(
            [
                (prj, bt, hrz)
                for (prj, bt, hrz) in instance.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS
            ]
        )
        self.assertListEqual(expected_operational_horizons, actual_operational_horizons)

        # Param: gen_hydro_must_take_average_power_fraction
        expected_average_power = OrderedDict(
            sorted(
                {
                    ("Hydro_NonCurtailable", "year", 2020): 0.5,
                    ("Hydro_NonCurtailable", "year", 2030): 0.5,
                }.items()
            )
        )
        actual_average_power = OrderedDict(
            sorted(
                {
                    (prj, bt, hrz): instance.gen_hydro_must_take_average_power_fraction[
                        prj, bt, hrz
                    ]
                    for (prj, bt, hrz) in instance.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS
                }.items()
            )
        )
        self.assertDictEqual(expected_average_power, actual_average_power)

        # Param: gen_hydro_must_take_min_power_fraction
        expected_min_power = OrderedDict(
            sorted(
                {
                    ("Hydro_NonCurtailable", "year", 2020): 0.15,
                    ("Hydro_NonCurtailable", "year", 2030): 0.15,
                }.items()
            )
        )
        actual_min_power = OrderedDict(
            sorted(
                {
                    (prj, bt, hrz): instance.gen_hydro_must_take_min_power_fraction[
                        prj, bt, hrz
                    ]
                    for (prj, bt, hrz) in instance.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS
                }.items()
            )
        )
        self.assertDictEqual(expected_min_power, actual_min_power)

        # Param: gen_hydro_must_take_max_power_fraction
        expected_max_power = OrderedDict(
            sorted(
                {
                    ("Hydro_NonCurtailable", "year", 2020): 1,
                    ("Hydro_NonCurtailable", "year", 2030): 1,
                }.items()
            )
        )
        actual_max_power = OrderedDict(
            sorted(
                {
                    (prj, bt, hrz): instance.gen_hydro_must_take_max_power_fraction[
                        prj, bt, hrz
                    ]
                    for (prj, bt, hrz) in instance.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS
                }.items()
            )
        )
        self.assertDictEqual(expected_max_power, actual_max_power)

        # GEN_HYDRO_MUST_TAKE_OPR_TMPS
        expected_tmps = sorted(get_project_operational_timepoints(expected_projects))
        actual_tmps = sorted([tmp for tmp in instance.GEN_HYDRO_MUST_TAKE_OPR_TMPS])
        self.assertListEqual(expected_tmps, actual_tmps)

        # Param: gen_hydro_must_take_ramp_up_when_on_rate
        expected_ramp_up = OrderedDict(sorted({"Hydro_NonCurtailable": 0.5}.items()))
        actual_ramp_up = OrderedDict(
            sorted(
                {
                    prj: instance.gen_hydro_must_take_ramp_up_when_on_rate[prj]
                    for prj in instance.GEN_HYDRO_MUST_TAKE
                }.items()
            )
        )
        self.assertDictEqual(expected_ramp_up, actual_ramp_up)

        # Param: gen_hydro_must_take_ramp_down_when_on_rate
        expected_ramp_down = OrderedDict(sorted({"Hydro_NonCurtailable": 0.5}.items()))
        actual_ramp_down = OrderedDict(
            sorted(
                {
                    prj: instance.gen_hydro_must_take_ramp_down_when_on_rate[prj]
                    for prj in instance.GEN_HYDRO_MUST_TAKE
                }.items()
            )
        )
        self.assertDictEqual(expected_ramp_down, actual_ramp_down)

        # Sets: GEN_HYDRO_MUST_TAKE_BUDGET_ALLOC_BT_HRZS
        expected_alloc_bt_hrzs = sorted(
            [
                ("Hydro_NonCurtailable", "day", 202001),
                ("Hydro_NonCurtailable", "day", 202002),
                ("Hydro_NonCurtailable", "day", 203001),
                ("Hydro_NonCurtailable", "day", 203002),
            ]
        )
        actual_alloc_bt_hrzs = sorted(
            [idx for idx in instance.GEN_HYDRO_MUST_TAKE_BUDGET_ALLOC_BT_HRZS]
        )
        self.assertListEqual(expected_alloc_bt_hrzs, actual_alloc_bt_hrzs)

        # Param: gen_hydro_must_take_budget_alloc_min_fraction (sparse: only
        # specified limits are loaded)
        expected_min_frac = OrderedDict(
            sorted(
                {
                    ("Hydro_NonCurtailable", "day", 202001): 0.4,
                    ("Hydro_NonCurtailable", "day", 202002): 0.4,
                    ("Hydro_NonCurtailable", "day", 203002): 0.45,
                }.items()
            )
        )
        actual_min_frac = OrderedDict(
            sorted(
                {
                    idx: instance.gen_hydro_must_take_budget_alloc_min_fraction[idx]
                    for idx in instance.GEN_HYDRO_MUST_TAKE_BUDGET_ALLOC_BT_HRZS
                    if idx in instance.gen_hydro_must_take_budget_alloc_min_fraction
                }.items()
            )
        )
        self.assertDictEqual(expected_min_frac, actual_min_frac)

        # Param: gen_hydro_must_take_budget_alloc_max_fraction
        expected_max_frac = OrderedDict(
            sorted(
                {
                    ("Hydro_NonCurtailable", "day", 202001): 0.6,
                    ("Hydro_NonCurtailable", "day", 203001): 0.55,
                    ("Hydro_NonCurtailable", "day", 203002): 0.55,
                }.items()
            )
        )
        actual_max_frac = OrderedDict(
            sorted(
                {
                    idx: instance.gen_hydro_must_take_budget_alloc_max_fraction[idx]
                    for idx in instance.GEN_HYDRO_MUST_TAKE_BUDGET_ALLOC_BT_HRZS
                    if idx in instance.gen_hydro_must_take_budget_alloc_max_fraction
                }.items()
            )
        )
        self.assertDictEqual(expected_max_frac, actual_max_frac)

        # Param: gen_hydro_must_take_budget_alloc_parent_hrz (the day
        # horizons nest within the project's year horizons)
        expected_parent_hrz = OrderedDict(
            sorted(
                {
                    ("Hydro_NonCurtailable", "day", 202001): 2020,
                    ("Hydro_NonCurtailable", "day", 202002): 2020,
                    ("Hydro_NonCurtailable", "day", 203001): 2030,
                    ("Hydro_NonCurtailable", "day", 203002): 2030,
                }.items()
            )
        )
        actual_parent_hrz = OrderedDict(
            sorted(
                {
                    idx: instance.gen_hydro_must_take_budget_alloc_parent_hrz[idx]
                    for idx in instance.GEN_HYDRO_MUST_TAKE_BUDGET_ALLOC_BT_HRZS
                }.items()
            )
        )
        self.assertDictEqual(expected_parent_hrz, actual_parent_hrz)

        # Constraints are built only where a limit is specified
        self.assertListEqual(
            sorted(expected_min_frac.keys()),
            sorted(
                idx for idx in instance.GenHydroMustTake_Budget_Alloc_Min_Constraint
            ),
        )
        self.assertListEqual(
            sorted(expected_max_frac.keys()),
            sorted(
                idx for idx in instance.GenHydroMustTake_Budget_Alloc_Max_Constraint
            ),
        )

    def build_instance(self, extra_prereq_modules=()):
        prereq_modules = IMPORTED_PREREQ_MODULES + [
            import_module("." + mdl, package="gridpath") for mdl in extra_prereq_modules
        ]
        m, data = add_components_and_load_data(
            prereq_modules=prereq_modules,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        return m.create_instance(data)

    def test_reserves_max_power_fraction_loaded(self):
        """
        The fraction is sparse (no default): only specified values load.
        """
        instance = self.build_instance()
        self.assertDictEqual(
            {"Hydro_NonCurtailable": 0.95},
            {
                p: instance.gen_hydro_must_take_reserves_max_power_fraction[p]
                for p in instance.GEN_HYDRO_MUST_TAKE
                if p in instance.gen_hydro_must_take_reserves_max_power_fraction
            },
        )

    def test_max_power_plus_reserves_skipped_without_reserves(self):
        """
        With no reserve module loaded, the project has no upward reserve
        variables, so the power-plus-reserves constraint is skipped and the
        max power constraint limits power output alone.
        """
        instance = self.build_instance()
        self.assertEqual(
            len(instance.GenHydroMustTake_Max_Power_Plus_Reserves_Constraint), 0
        )
        self.assertEqual(
            len(instance.GenHydroMustTake_Max_Power_Constraint),
            len(instance.GEN_HYDRO_MUST_TAKE_OPR_TMPS),
        )

    def test_max_power_plus_reserves_with_reserves(self):
        """
        With an upward reserve module loaded, the max power constraint limits
        power output only (by the horizon's max_power_fraction) and the
        power-plus-reserves constraint limits power output plus upward
        reserves by the reserves max power fraction, in every timepoint.
        """
        instance = self.build_instance(
            extra_prereq_modules=[
                "geography.load_following_up_balancing_areas",
                "project.operations.reserves.lf_reserves_up",
            ]
        )
        self.assertIn("Hydro_NonCurtailable", instance.LF_RESERVES_UP_PROJECTS)
        opr_tmps = sorted(instance.GEN_HYDRO_MUST_TAKE_OPR_TMPS)
        self.assertListEqual(
            opr_tmps,
            sorted(instance.GenHydroMustTake_Max_Power_Plus_Reserves_Constraint.keys()),
        )

        bt = get_energy_budget_balancing_type(
            instance,
            "Hydro_NonCurtailable",
            instance.gen_hydro_must_take_energy_budget_balancing_type,
        )
        for prj, tmp in opr_tmps:
            available_mw = value(
                instance.Capacity_MW[prj, instance.period[tmp]]
                * instance.Availability_Derate[prj, tmp]
            )
            max_power = instance.GenHydroMustTake_Max_Power_Constraint[prj, tmp]
            self.assertNotIn(
                "Provide_LF_Reserves_Up_MW",
                {v.parent_component().name for v in identify_variables(max_power.body)},
            )
            self.assertAlmostEqual(
                rhs_at_zero_vars(max_power),
                instance.gen_hydro_must_take_max_power_fraction[
                    prj, bt, instance.horizon[tmp, bt]
                ]
                * available_mw,
            )

            plus_reserves = (
                instance.GenHydroMustTake_Max_Power_Plus_Reserves_Constraint[prj, tmp]
            )
            self.assertSetEqual(
                {"Provide_LF_Reserves_Up_MW", "GenHydroMustTake_Gross_Power_MW"},
                {
                    v.parent_component().name
                    for v in identify_variables(plus_reserves.body)
                },
            )
            self.assertAlmostEqual(rhs_at_zero_vars(plus_reserves), 0.95 * available_mw)


if __name__ == "__main__":
    unittest.main()
