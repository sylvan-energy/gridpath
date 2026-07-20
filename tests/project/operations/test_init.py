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
import numpy as np
import pandas as pd

from tests.common_functions import add_components_and_load_data

from gridpath.project.operations import (
    calculate_slope_intercept,
    get_slopes_intercept_by_project_period_segment,
)

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

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
]
NAME_OF_MODULE_BEING_TESTED = "project.operations"
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


# TODO: not sure whether to suppress these
#  annoying warnings
#  https://stackoverflow.com/questions/40659212/futurewarning-elementwise-comparison-failed-returning-scalar-but-in-the-futur


class TestOperationsInit(unittest.TestCase):
    """ """

    def assertDictAlmostEqual(self, d1, d2, msg=None, places=7):
        # check if both inputs are dicts
        self.assertIsInstance(d1, dict, "First argument is not a dictionary")
        self.assertIsInstance(d2, dict, "Second argument is not a dictionary")

        # check if both inputs have the same keys
        self.assertEqual(d1.keys(), d2.keys())

        # check each key
        for key, value in d1.items():
            if isinstance(value, dict):
                self.assertDictAlmostEqual(d1[key], d2[key], msg=msg)
            else:
                self.assertAlmostEqual(d1[key], d2[key], places=places, msg=msg)

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

        # Load test data as dataframes
        projects_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "projects.tab"), sep="\t"
        )

        prj_fuels_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "project_fuels.tab"),
            sep="\t",
        )

        fuels_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "fuels.tab"),
            sep="\t",
        )

        var_om_curve_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "variable_om_curves.tab"),
            sep="\t",
        )

        startup_by_st_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "startup_chars.tab"), sep="\t"
        )

        hr_curve_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "heat_rate_curves.tab"),
            sep="\t",
        )

        # Set: VAR_OM_COST_SIMPLE_PRJS
        expected_var_om_simple_projects = sorted(
            projects_df[projects_df["variable_om_cost_per_mwh"] != "."][
                "project"
            ].tolist()
        )

        actual_var_om_simple_projects = sorted(
            [p for p in instance.VAR_OM_COST_SIMPLE_PRJS]
        )

        self.assertListEqual(
            expected_var_om_simple_projects, actual_var_om_simple_projects
        )

        # Set: VAR_OM_COST_CURVE_PRJS_PRDS_SGMS
        expected_var_om_curve_projects_periods_sgms = sorted(
            [
                ("Disp_Binary_Commit", 2020, 0),
                ("Disp_Binary_Commit", 2020, 1),
                ("Disp_Binary_Commit", 2030, 0),
                ("Disp_Cont_Commit", 2020, 0),
                ("Disp_Cont_Commit", 2030, 0),
            ]
        )

        actual_var_om_curve_projects_periods_sgms = sorted(
            [
                (prj, prd, s)
                for (prj, prd, s) in instance.VAR_OM_COST_CURVE_PRJS_PRDS_SGMS
            ]
        )

        self.assertListEqual(
            expected_var_om_curve_projects_periods_sgms,
            actual_var_om_curve_projects_periods_sgms,
        )

        # Set: VAR_OM_COST_CURVE_PRJS
        expected_var_om_curve_projects = sorted(
            var_om_curve_df["project"].unique().tolist()
        )

        actual_var_om_curve_projects = sorted(
            [p for p in instance.VAR_OM_COST_CURVE_PRJS]
        )

        self.assertListEqual(
            expected_var_om_curve_projects, actual_var_om_curve_projects
        )

        # Set: VAR_OM_COST_ALL_PRJS
        expected_var_om_all_projects = sorted(
            list(set(expected_var_om_simple_projects + expected_var_om_curve_projects))
        )

        actual_var_om_all_projects = sorted([p for p in instance.VAR_OM_COST_ALL_PRJS])

        self.assertListEqual(expected_var_om_all_projects, actual_var_om_all_projects)

        # Set: STARTUP_COST_SIMPLE_PRJS
        expected_startup_cost_simple_projects = sorted(
            projects_df[projects_df["startup_cost_per_mw"] != "."]["project"].tolist()
        )

        actual_startup_cost_simple_projects = sorted(
            [p for p in instance.STARTUP_COST_SIMPLE_PRJS]
        )

        self.assertListEqual(
            expected_startup_cost_simple_projects, actual_startup_cost_simple_projects
        )

        # Set: STARTUP_BY_ST_PRJS_TYPES
        expected_startup_by_st_projects_types = sorted(
            [
                ("Disp_Binary_Commit", 1),
                ("Disp_Cont_Commit", 1),
                ("Disp_Cont_Commit", 2),
                ("Clunky_Old_Gen", 1),
                ("Clunky_Old_Gen2", 1),
            ]
        )

        actual_startup_by_st_projects_types = sorted(
            [(prj, s) for (prj, s) in instance.STARTUP_BY_ST_PRJS_TYPES]
        )

        self.assertListEqual(
            expected_startup_by_st_projects_types, actual_startup_by_st_projects_types
        )

        # Set: STARTUP_BY_ST_PRJS
        expected_startup_by_st_projects = sorted(
            startup_by_st_df["project"].unique().tolist()
        )

        actual_startup_by_st_projects = sorted([p for p in instance.STARTUP_BY_ST_PRJS])

        self.assertListEqual(
            expected_startup_by_st_projects, actual_startup_by_st_projects
        )

        # Set: STARTUP_COST_PRJS
        expected_startup_cost_all_projects = sorted(
            list(
                set(
                    expected_startup_cost_simple_projects
                    + expected_startup_by_st_projects
                )
            )
        )

        actual_startup_cost_all_projects = sorted(
            [p for p in instance.STARTUP_COST_PRJS]
        )

        self.assertListEqual(
            expected_startup_cost_all_projects, actual_startup_cost_all_projects
        )

        # Set: SHUTDOWN_COST_PRJS
        expected_shutdown_cost_projects = sorted(
            projects_df[projects_df["shutdown_cost_per_mw"] != "."]["project"].tolist()
        )

        actual_shutdown_cost_projects = sorted([p for p in instance.SHUTDOWN_COST_PRJS])

        self.assertListEqual(
            expected_shutdown_cost_projects, actual_shutdown_cost_projects
        )

        # Set: FUEL_PRJ_FUELS
        expected_fuel_project_fuels = list(
            prj_fuels_df[["project", "fuel"]].to_records(index=False)
        )

        # Need to convert to tuples from numpy arrays to allow assert below
        expected_fuel_project_fuels = sorted(
            [tuple(i) for i in expected_fuel_project_fuels]
        )

        actual_fuel_project_fuels = sorted(
            [(p, f) for (p, f) in instance.FUEL_PRJ_FUELS]
        )

        self.assertListEqual(expected_fuel_project_fuels, actual_fuel_project_fuels)

        # Set: FUEL_PRJS
        expected_fuel_projects = sorted(prj_fuels_df["project"].unique().tolist())

        actual_fuel_projects = sorted([p for p in instance.FUEL_PRJS])

        self.assertListEqual(expected_fuel_projects, actual_fuel_projects)

        # Set: FUELS_BY_PRJ
        expected_fuels_by_prj = {}
        for p, f in expected_fuel_project_fuels:
            if p not in expected_fuels_by_prj.keys():
                expected_fuels_by_prj[p] = [f]
            else:
                expected_fuels_by_prj[p].append(f)
        expected_fuels_by_prj_od = OrderedDict(sorted(expected_fuels_by_prj.items()))

        actual_fuels_by_project = {
            p: [f for f in instance.FUELS_BY_PRJ[p]]
            for p in instance.FUELS_BY_PRJ.keys()
        }
        for p in actual_fuels_by_project.keys():
            actual_fuels_by_project[p] = sorted(actual_fuels_by_project[p])
        actual_fuels_by_project_od = OrderedDict(
            sorted(actual_fuels_by_project.items())
        )

        self.assertDictEqual(expected_fuels_by_prj_od, actual_fuels_by_project_od)

        # Set: FUEL_PRJ_FUELS_FUEL_GROUP
        fuel_group_fuels = list(
            fuels_df[["fuel_group", "fuel"]].to_records(index=False)
        )
        fuel_group_fuels = sorted([tuple(i) for i in fuel_group_fuels])
        expected_fuel_project_fuels_fuel_group = sorted(
            [
                (prj, fg, f)
                for (prj, f) in expected_fuel_project_fuels
                for (fg, _f) in fuel_group_fuels
                if f == _f
            ]
        )

        actual_fuel_project_fuels_fuel_group = sorted(
            [(p, fg, f) for (p, fg, f) in instance.FUEL_PRJ_FUELS_FUEL_GROUP]
        )

        self.assertListEqual(
            expected_fuel_project_fuels_fuel_group, actual_fuel_project_fuels_fuel_group
        )

        # Set: HR_CURVE_PRJS_PRDS_SGMS
        expected_hr_curve_projects_periods_sgms = sorted(
            [
                ("Coal", 2020, 0),
                ("Coal", 2030, 0),
                ("Gas_CCGT", 2020, 0),
                ("Gas_CCGT", 2030, 0),
                ("Gas_CT", 2020, 0),
                ("Gas_CT", 2030, 0),
                ("Nuclear", 2020, 0),
                ("Nuclear", 2030, 0),
                ("Gas_CCGT_New", 2020, 0),
                ("Gas_CCGT_New", 2030, 0),
                ("Gas_CCGT_New_Binary", 2020, 0),
                ("Gas_CCGT_New_Binary", 2030, 0),
                ("Gas_CT_New", 2020, 0),
                ("Gas_CT_New", 2030, 0),
                ("Coal_z2", 2020, 0),
                ("Coal_z2", 2030, 0),
                ("Gas_CCGT_z2", 2020, 0),
                ("Gas_CCGT_z2", 2030, 0),
                ("Gas_CT_z2", 2020, 0),
                ("Gas_CT_z2", 2030, 0),
                ("Nuclear_z2", 2020, 0),
                ("Nuclear_z2", 2030, 0),
                ("Disp_Binary_Commit", 2020, 0),
                ("Disp_Binary_Commit", 2030, 0),
                ("Disp_Cont_Commit", 2020, 0),
                ("Disp_Cont_Commit", 2030, 0),
                ("Disp_No_Commit", 2020, 0),
                ("Disp_No_Commit", 2030, 0),
                ("Clunky_Old_Gen", 2020, 0),
                ("Clunky_Old_Gen", 2030, 0),
                ("Clunky_Old_Gen2", 2020, 0),
                ("Clunky_Old_Gen2", 2030, 0),
                ("Nuclear_Flexible", 2020, 0),
                ("Nuclear_Flexible", 2030, 0),
                ("DAC", 2020, 0),
                ("DAC", 2030, 0),
            ]
        )

        actual_hr_curve_projects_periods_sgms = sorted(
            [(prj, prd, s) for (prj, prd, s) in instance.HR_CURVE_PRJS_PRDS_SGMS]
        )

        self.assertListEqual(
            expected_hr_curve_projects_periods_sgms,
            actual_hr_curve_projects_periods_sgms,
        )

        # Set: HR_CURVE_PRJS
        expected_hr_curve_projects = sorted(hr_curve_df["project"].unique().tolist())

        actual_hr_curve_projects = sorted([p for p in instance.HR_CURVE_PRJS])

        self.assertListEqual(expected_hr_curve_projects, actual_hr_curve_projects)

        # Set: STARTUP_FUEL_PRJS
        expected_startup_fuel_projects = sorted(
            projects_df[projects_df["startup_fuel_mmbtu_per_mw"] != "."][
                "project"
            ].tolist()
        )

        actual_startup_fuel_projects = sorted([p for p in instance.STARTUP_FUEL_PRJS])

        self.assertListEqual(
            expected_startup_fuel_projects, actual_startup_fuel_projects
        )

        # Set: RAMP_UP_VIOL_PRJS
        expected_ramp_up_viol_projects = sorted(
            projects_df[projects_df["ramp_up_violation_penalty"] != "."][
                "project"
            ].tolist()
        )

        actual_ramp_up_viol_projects = sorted([p for p in instance.RAMP_UP_VIOL_PRJS])

        self.assertListEqual(
            expected_ramp_up_viol_projects, actual_ramp_up_viol_projects
        )

        # Set: RAMP_DOWN_VIOL_PRJS
        expected_ramp_down_viol_projects = sorted(
            projects_df[projects_df["ramp_down_violation_penalty"] != "."][
                "project"
            ].tolist()
        )

        actual_ramp_down_viol_projects = sorted(
            [p for p in instance.RAMP_DOWN_VIOL_PRJS]
        )

        self.assertListEqual(
            expected_ramp_down_viol_projects, actual_ramp_down_viol_projects
        )

        # Set: MIN_UP_TIME_VIOL_PRJS
        expected_min_up_time_viol_projects = sorted(
            projects_df[projects_df["min_up_time_violation_penalty"] != "."][
                "project"
            ].tolist()
        )

        actual_min_up_time_viol_projects = sorted(
            [p for p in instance.MIN_UP_TIME_VIOL_PRJS]
        )

        self.assertListEqual(
            expected_min_up_time_viol_projects, actual_min_up_time_viol_projects
        )

        # Set: MIN_DOWN_TIME_VIOL_PRJS
        expected_min_down_time_viol_projects = sorted(
            projects_df[projects_df["min_down_time_violation_penalty"] != "."][
                "project"
            ].tolist()
        )

        actual_min_down_time_viol_projects = sorted(
            [p for p in instance.MIN_DOWN_TIME_VIOL_PRJS]
        )

        self.assertListEqual(
            expected_min_down_time_viol_projects, actual_min_down_time_viol_projects
        )

        # Set: VIOL_ALL_PRJS
        expected_viol_all_projects = sorted(
            list(
                set(
                    expected_ramp_up_viol_projects
                    + expected_ramp_down_viol_projects
                    + expected_min_up_time_viol_projects
                    + expected_min_down_time_viol_projects
                )
            )
        )

        actual_viol_all_projects = sorted([p for p in instance.VIOL_ALL_PRJS])

        self.assertListEqual(expected_viol_all_projects, actual_viol_all_projects)

        # Set: CURTAILMENT_COST_PRJ_PRDS
        expected_curtailment_cost_project_periods = [
            ("Battery", 2020),
            ("Battery", 2030),
            ("Wind", 2020),
            ("Wind", 2030),
            ("Wind_Battery_Hybrid", 2020),
            ("Wind_Battery_Hybrid", 2030),
        ]

        actual_curtailment_cost_project_periods = sorted(
            [(prj, prd) for (prj, prd) in instance.CURTAILMENT_COST_PRJ_PRDS]
        )

        self.assertListEqual(
            expected_curtailment_cost_project_periods,
            actual_curtailment_cost_project_periods,
        )

        # Set: CURTAILMENT_COST_PRJS
        expected_curtailment_cost_projects = sorted(
            ["Wind", "Battery", "Wind_Battery_Hybrid"]
        )

        actual_curtailment_cost_projects = sorted(
            [p for p in instance.CURTAILMENT_COST_PRJS]
        )

        self.assertListEqual(
            expected_curtailment_cost_projects, actual_curtailment_cost_projects
        )

        # Set: SOC_PENALTY_COST_PRJS
        expected_soc_penalty_cost_projects = sorted(
            projects_df[projects_df["soc_penalty_cost_per_energyunit"] != "."][
                "project"
            ].tolist()
        )

        actual_soc_penalty_cost_projects = sorted(
            [p for p in instance.SOC_PENALTY_COST_PRJS]
        )

        self.assertListEqual(
            expected_soc_penalty_cost_projects, actual_soc_penalty_cost_projects
        )

        # Set: SOC_LAST_TMP_PENALTY_COST_PRJS
        expected_soc_last_tmp_penalty_cost_projects = sorted(
            projects_df[projects_df["soc_last_tmp_penalty_cost_per_energyunit"] != "."][
                "project"
            ].tolist()
        )

        actual_soc_last_tmp_penalty_cost_projects = sorted(
            [p for p in instance.SOC_LAST_TMP_PENALTY_COST_PRJS]
        )

        self.assertListEqual(
            expected_soc_last_tmp_penalty_cost_projects,
            actual_soc_last_tmp_penalty_cost_projects,
        )

        # Set: NONFUEL_CARBON_EMISSIONS_PRJS
        expected_nonfuel_em_projects = sorted(
            projects_df[projects_df["nonfuel_carbon_emissions_per_mwh"] != "."][
                "project"
            ].tolist()
        )

        actual_nonfuelfuel_em_projects = sorted(
            [p for p in instance.NONFUEL_CARBON_EMISSIONS_PRJS]
        )

        self.assertListEqual(
            expected_nonfuel_em_projects, actual_nonfuelfuel_em_projects
        )

        # Param: variable_om_cost_per_mwh
        var_om_cost_df = projects_df[projects_df["variable_om_cost_per_mwh"] != "."]
        expected_var_om_cost_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        var_om_cost_df["project"],
                        pd.to_numeric(var_om_cost_df["variable_om_cost_per_mwh"]),
                    )
                ).items()
            )
        )
        actual_var_om_cost_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.variable_om_cost_per_mwh[p]
                    for p in instance.VAR_OM_COST_SIMPLE_PRJS
                }.items()
            )
        )
        self.assertDictEqual(expected_var_om_cost_by_prj, actual_var_om_cost_by_prj)

        # Param: vom_slope_cost_per_mwh
        expected_vom_slope = OrderedDict(
            sorted(
                {
                    ("Disp_Binary_Commit", 2020, 0): 2.25,
                    ("Disp_Binary_Commit", 2020, 1): 2.75,
                    ("Disp_Binary_Commit", 2030, 0): 1.0,
                    ("Disp_Cont_Commit", 2020, 0): 1.0,
                    ("Disp_Cont_Commit", 2030, 0): 1.0,
                }.items()
            )
        )
        actual_vom_slope = OrderedDict(
            sorted(
                {
                    (prj, p, s): instance.vom_slope_cost_per_mwh[(prj, p, s)]
                    for (prj, p, s) in instance.VAR_OM_COST_CURVE_PRJS_PRDS_SGMS
                }.items()
            )
        )

        self.assertDictAlmostEqual(expected_vom_slope, actual_vom_slope, places=5)

        # Param: vom_intercept_cost_per_mw_hr
        expected_vom_intercept = OrderedDict(
            sorted(
                {
                    ("Disp_Binary_Commit", 2020, 0): -0.375,
                    ("Disp_Binary_Commit", 2020, 1): -0.75,
                    ("Disp_Binary_Commit", 2030, 0): 0.5,
                    ("Disp_Cont_Commit", 2020, 0): 0,
                    ("Disp_Cont_Commit", 2030, 0): 0,
                }.items()
            )
        )
        actual_vom_intercept = OrderedDict(
            sorted(
                {
                    (prj, p, s): instance.vom_intercept_cost_per_mw_hr[(prj, p, s)]
                    for (prj, p, s) in instance.VAR_OM_COST_CURVE_PRJS_PRDS_SGMS
                }.items()
            )
        )

        self.assertDictAlmostEqual(
            expected_vom_intercept, actual_vom_intercept, places=5
        )

        # Param: startup_cost_per_mw
        startup_cost_df = projects_df[projects_df["startup_cost_per_mw"] != "."]
        expected_startup_cost_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        startup_cost_df["project"],
                        pd.to_numeric(startup_cost_df["startup_cost_per_mw"]),
                    )
                ).items()
            )
        )
        actual_startup_cost_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.startup_cost_per_mw[p]
                    for p in instance.STARTUP_COST_SIMPLE_PRJS
                }.items()
            )
        )

        self.assertDictEqual(expected_startup_cost_by_prj, actual_startup_cost_by_prj)

        # Param: startup_cost_by_st_per_mw
        expected_startup_cost_by_st = OrderedDict(
            sorted(
                {
                    ("Clunky_Old_Gen", 1): 1.0,
                    ("Clunky_Old_Gen2", 1): 1.0,
                    ("Disp_Binary_Commit", 1): 1.0,
                    ("Disp_Cont_Commit", 1): 1.0,
                    ("Disp_Cont_Commit", 2): 10.0,
                }.items()
            )
        )
        actual_startup_cost_by_st = OrderedDict(
            sorted(
                {
                    (prj, st): instance.startup_cost_by_st_per_mw[(prj, st)]
                    for (prj, st) in instance.STARTUP_BY_ST_PRJS_TYPES
                }.items()
            )
        )

        self.assertDictAlmostEqual(
            expected_startup_cost_by_st, actual_startup_cost_by_st, places=5
        )

        # Param: shutdown_cost_per_mw
        shutdown_cost_df = projects_df[projects_df["shutdown_cost_per_mw"] != "."]
        expected_shutdown_cost_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        shutdown_cost_df["project"],
                        pd.to_numeric(shutdown_cost_df["shutdown_cost_per_mw"]),
                    )
                ).items()
            )
        )
        actual_shutdown_cost_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.shutdown_cost_per_mw[p]
                    for p in instance.SHUTDOWN_COST_PRJS
                }.items()
            )
        )

        self.assertDictEqual(expected_shutdown_cost_by_prj, actual_shutdown_cost_by_prj)

        # Param: fuel_burn_slope_mmbtu_per_mwh
        expected_fuel_burn_slope = OrderedDict(
            sorted(
                {
                    ("Clunky_Old_Gen", 2020, 0): 14.999996666666675,
                    ("Clunky_Old_Gen", 2030, 0): 14.999996666666675,
                    ("Clunky_Old_Gen2", 2020, 0): 14.999996666666675,
                    ("Clunky_Old_Gen2", 2030, 0): 14.999996666666675,
                    ("Coal", 2020, 0): 10.0,
                    ("Coal", 2030, 0): 10.0,
                    ("Coal_z2", 2020, 0): 10.0,
                    ("Coal_z2", 2030, 0): 10.0,
                    ("Disp_Binary_Commit", 2020, 0): 7.999996666666647,
                    ("Disp_Binary_Commit", 2030, 0): 7.999996666666647,
                    ("Disp_Cont_Commit", 2020, 0): 7.999996666666647,
                    ("Disp_Cont_Commit", 2030, 0): 7.999996666666647,
                    ("Disp_No_Commit", 2020, 0): 8.0,
                    ("Disp_No_Commit", 2030, 0): 8.0,
                    ("Gas_CCGT", 2020, 0): 6.0,
                    ("Gas_CCGT", 2030, 0): 6.0,
                    ("Gas_CCGT_New", 2020, 0): 6.0,
                    ("Gas_CCGT_New", 2030, 0): 6.0,
                    ("Gas_CCGT_New_Binary", 2020, 0): 6.0,
                    ("Gas_CCGT_New_Binary", 2030, 0): 6.0,
                    ("Gas_CCGT_z2", 2020, 0): 6.0,
                    ("Gas_CCGT_z2", 2030, 0): 6.0,
                    ("Gas_CT", 2020, 0): 7.999996666666647,
                    ("Gas_CT", 2030, 0): 7.999996666666647,
                    ("Gas_CT_New", 2020, 0): 7.999996666666647,
                    ("Gas_CT_New", 2030, 0): 7.999996666666647,
                    ("Gas_CT_z2", 2020, 0): 7.999996666666647,
                    ("Gas_CT_z2", 2030, 0): 7.999996666666647,
                    ("Nuclear", 2020, 0): 1666.67,
                    ("Nuclear", 2030, 0): 1666.67,
                    ("Nuclear_Flexible", 2020, 0): 10.0,
                    ("Nuclear_Flexible", 2030, 0): 9.0,
                    ("Nuclear_z2", 2020, 0): 1666.67,
                    ("Nuclear_z2", 2030, 0): 1666.67,
                    ("DAC", 2020, 0): 1000.0,
                    ("DAC", 2030, 0): 1000.0,
                }.items()
            )
        )
        actual_fuel_burn_slope = OrderedDict(
            sorted(
                {
                    (prj, p, s): instance.fuel_burn_slope_mmbtu_per_mwh[(prj, p, s)]
                    for (prj, p, s) in instance.HR_CURVE_PRJS_PRDS_SGMS
                }.items()
            )
        )

        self.assertDictAlmostEqual(
            expected_fuel_burn_slope, actual_fuel_burn_slope, places=5
        )

        # Param: fuel_burn_intercept_mmbtu_per_mw_hr
        expected_fuel_burn_intercept = OrderedDict(
            sorted(
                {
                    ("Clunky_Old_Gen", 2020, 0): 827.3333333333334,
                    ("Clunky_Old_Gen", 2030, 0): 827.3333333333334,
                    ("Clunky_Old_Gen2", 2020, 0): 827.3333333333334,
                    ("Clunky_Old_Gen2", 2030, 0): 827.3333333333334,
                    ("Coal", 2020, 0): 496.0,
                    ("Coal", 2030, 0): 496.0,
                    ("Coal_z2", 2020, 0): 496.0,
                    ("Coal_z2", 2030, 0): 496.0,
                    ("Disp_Binary_Commit", 2020, 0): 80.13333333333335,
                    ("Disp_Binary_Commit", 2030, 0): 80.13333333333335,
                    ("Disp_Cont_Commit", 2020, 0): 80.13333333333335,
                    ("Disp_Cont_Commit", 2030, 0): 80.13333333333335,
                    ("Disp_No_Commit", 2020, 0): 0,
                    ("Disp_No_Commit", 2030, 0): 0,
                    ("Gas_CCGT", 2020, 0): 250.0,
                    ("Gas_CCGT", 2030, 0): 250.0,
                    ("Gas_CCGT_New", 2020, 0): 250.0,
                    ("Gas_CCGT_New", 2030, 0): 250.0,
                    ("Gas_CCGT_New_Binary", 2020, 0): 250.0,
                    ("Gas_CCGT_New_Binary", 2030, 0): 250.0,
                    ("Gas_CCGT_z2", 2020, 0): 250.0,
                    ("Gas_CCGT_z2", 2030, 0): 250.0,
                    ("Gas_CT", 2020, 0): 80.13333333333335,
                    ("Gas_CT", 2030, 0): 80.13333333333335,
                    ("Gas_CT_New", 2020, 0): 80.13333333333335,
                    ("Gas_CT_New", 2030, 0): 80.13333333333335,
                    ("Gas_CT_z2", 2020, 0): 80.13333333333335,
                    ("Gas_CT_z2", 2030, 0): 80.13333333333335,
                    ("Nuclear", 2020, 0): 0,
                    ("Nuclear", 2030, 0): 0,
                    ("Nuclear_Flexible", 2020, 0): 0,
                    ("Nuclear_Flexible", 2030, 0): 0,
                    ("Nuclear_z2", 2020, 0): 0,
                    ("Nuclear_z2", 2030, 0): 0,
                    ("DAC", 2020, 0): 0,
                    ("DAC", 2030, 0): 0,
                }.items()
            )
        )
        actual_fuel_burn_intercept = OrderedDict(
            sorted(
                {
                    (prj, p, s): instance.fuel_burn_intercept_mmbtu_per_mw_hr[
                        (prj, p, s)
                    ]
                    for (prj, p, s) in instance.HR_CURVE_PRJS_PRDS_SGMS
                }.items()
            )
        )

        self.assertDictAlmostEqual(
            expected_fuel_burn_intercept, actual_fuel_burn_intercept, places=5
        )

        # Param: startup_fuel_mmbtu_per_mw
        startup_fuel_df = projects_df[projects_df["startup_fuel_mmbtu_per_mw"] != "."]
        expected_startup_fuel_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        startup_fuel_df["project"],
                        pd.to_numeric(startup_fuel_df["startup_fuel_mmbtu_per_mw"]),
                    )
                ).items()
            )
        )
        actual_startup_fuel_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.startup_fuel_mmbtu_per_mw[p]
                    for p in instance.STARTUP_FUEL_PRJS
                }.items()
            )
        )

        self.assertDictEqual(expected_startup_fuel_by_prj, actual_startup_fuel_by_prj)

        # Param: ramp_up_violation_penalty
        ramp_up_viol_df = projects_df[projects_df["ramp_up_violation_penalty"] != "."]
        expected_ramp_up_viol_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        ramp_up_viol_df["project"],
                        pd.to_numeric(ramp_up_viol_df["ramp_up_violation_penalty"]),
                    )
                ).items()
            )
        )
        actual_ramp_up_viol_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.ramp_up_violation_penalty[p]
                    for p in instance.RAMP_UP_VIOL_PRJS
                }.items()
            )
        )

        self.assertDictEqual(expected_ramp_up_viol_by_prj, actual_ramp_up_viol_by_prj)

        # Param: ramp_down_violation_penalty
        ramp_down_viol_df = projects_df[
            projects_df["ramp_down_violation_penalty"] != "."
        ]
        expected_ramp_down_viol_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        ramp_down_viol_df["project"],
                        pd.to_numeric(ramp_down_viol_df["ramp_down_violation_penalty"]),
                    )
                ).items()
            )
        )
        actual_ramp_down_viol_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.ramp_down_violation_penalty[p]
                    for p in instance.RAMP_DOWN_VIOL_PRJS
                }.items()
            )
        )

        self.assertDictEqual(
            expected_ramp_down_viol_by_prj, actual_ramp_down_viol_by_prj
        )

        # Param: ramp_tuning_cost_per_mw
        ramp_tuning_cost_df = projects_df
        # Change ramp_tuning_cost_per_mw to 0 where ramp_tuning_cost_per_mw
        # is ".
        ramp_tuning_cost_df.loc[
            ramp_tuning_cost_df["ramp_tuning_cost_per_mw"] == ".",
            "ramp_tuning_cost_per_mw",
        ] = "0"

        expected_ramp_tuning_cost_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        ramp_tuning_cost_df["project"],
                        pd.to_numeric(ramp_tuning_cost_df["ramp_tuning_cost_per_mw"]),
                    )
                ).items()
            )
        )
        actual_ramp_tuning_cost_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.ramp_tuning_cost_per_mw[p] for p in instance.PROJECTS
                }.items()
            )
        )
        self.assertDictEqual(
            expected_ramp_tuning_cost_by_prj, actual_ramp_tuning_cost_by_prj
        )

        # Param: min_up_time_violation_penalty
        min_up_time_viol_df = projects_df[
            projects_df["min_up_time_violation_penalty"] != "."
        ]
        expected_min_up_time_viol_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        min_up_time_viol_df["project"],
                        pd.to_numeric(
                            min_up_time_viol_df["min_up_time_violation_penalty"]
                        ),
                    )
                ).items()
            )
        )
        actual_min_up_time_viol_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.min_up_time_violation_penalty[p]
                    for p in instance.MIN_UP_TIME_VIOL_PRJS
                }.items()
            )
        )

        self.assertDictEqual(
            expected_min_up_time_viol_by_prj, actual_min_up_time_viol_by_prj
        )

        # Param: min_down_time_violation_penalty
        min_down_time_viol_df = projects_df[
            projects_df["min_down_time_violation_penalty"] != "."
        ]
        expected_min_down_time_viol_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        min_down_time_viol_df["project"],
                        pd.to_numeric(
                            min_down_time_viol_df["min_down_time_violation_penalty"]
                        ),
                    )
                ).items()
            )
        )
        actual_min_down_time_viol_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.min_down_time_violation_penalty[p]
                    for p in instance.MIN_DOWN_TIME_VIOL_PRJS
                }.items()
            )
        )

        self.assertDictEqual(
            expected_min_down_time_viol_by_prj, actual_min_down_time_viol_by_prj
        )

        # Param: curtailment_cost_per_powerunithour
        expected_curtailment_cost_by_prj = {
            ("Wind", 2020): 10,
            ("Wind", 2030): 10,
            ("Battery", 2020): 10,
            ("Battery", 2030): 0,
            ("Wind_Battery_Hybrid", 2020): 0,
            ("Wind_Battery_Hybrid", 2030): 10,
        }
        actual_curtailment_cost_by_prj = OrderedDict(
            sorted(
                {
                    (prj, prd): instance.curtailment_cost_per_powerunithour[prj, prd]
                    for (prj, prd) in instance.CURTAILMENT_COST_PRJ_PRDS
                }.items()
            )
        )

        self.assertDictEqual(
            expected_curtailment_cost_by_prj, actual_curtailment_cost_by_prj
        )

        # Param: soc_penalty_cost_per_energyunit
        soc_penalty_cost_df = projects_df[
            projects_df["soc_penalty_cost_per_energyunit"] != "."
        ]
        expected_soc_penalty_cost_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        soc_penalty_cost_df["project"],
                        pd.to_numeric(
                            soc_penalty_cost_df["soc_penalty_cost_per_energyunit"]
                        ),
                    )
                ).items()
            )
        )
        actual_soc_penalty_cost_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.soc_penalty_cost_per_energyunit[p]
                    for p in instance.SOC_PENALTY_COST_PRJS
                }.items()
            )
        )

        self.assertDictEqual(
            expected_soc_penalty_cost_by_prj, actual_soc_penalty_cost_by_prj
        )

        # Param: soc_last_tmp_penalty_cost_per_energyunit
        soc_last_tmp_penalty_cost_df = projects_df[
            projects_df["soc_last_tmp_penalty_cost_per_energyunit"] != "."
        ]
        expected_soc_last_tmp_penalty_cost_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        soc_last_tmp_penalty_cost_df["project"],
                        pd.to_numeric(
                            soc_last_tmp_penalty_cost_df[
                                "soc_last_tmp_penalty_cost_per_energyunit"
                            ]
                        ),
                    )
                ).items()
            )
        )
        actual_soc_last_tmp_penalty_cost_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.soc_last_tmp_penalty_cost_per_energyunit[p]
                    for p in instance.SOC_LAST_TMP_PENALTY_COST_PRJS
                }.items()
            )
        )

        self.assertDictEqual(
            expected_soc_last_tmp_penalty_cost_by_prj,
            actual_soc_last_tmp_penalty_cost_by_prj,
        )

        # Param: nonfuel_carbon_emissions_per_mwh
        nonfuel_em_df = projects_df[
            projects_df["nonfuel_carbon_emissions_per_mwh"] != "."
        ]
        expected_nonfuel_em_by_prj = OrderedDict(
            sorted(
                dict(
                    zip(
                        nonfuel_em_df["project"],
                        pd.to_numeric(
                            nonfuel_em_df["nonfuel_carbon_emissions_per_mwh"]
                        ),
                    )
                ).items()
            )
        )
        actual_nonfuel_em_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.nonfuel_carbon_emissions_per_mwh[p]
                    for p in instance.NONFUEL_CARBON_EMISSIONS_PRJS
                }.items()
            )
        )
        self.assertDictEqual(expected_nonfuel_em_by_prj, actual_nonfuel_em_by_prj)

    def test_get_slopes_intercept_by_project_period_segment(self):
        """
        Check that slope and intercept dictionaries are correctly constructed
        from the input data frames
        :return:
        """
        hr_columns = [
            "project",
            "period",
            "load_point_fraction",
            "average_heat_rate_mmbtu_per_mwh",
        ]
        vom_columns = [
            "project",
            "period",
            "load_point_fraction",
            "average_variable_om_cost_per_mwh",
        ]
        test_cases = {
            # Check heat rates curves
            1: {
                "df": pd.DataFrame(
                    columns=hr_columns,
                    data=[
                        ["gas_ct", 2020, 0.5, 10],
                        ["gas_ct", 2020, 1, 7],
                        ["coal_plant", 2020, 1, 10],
                    ],
                ),
                "input_col": "average_heat_rate_mmbtu_per_mwh",
                "projects": ["gas_ct", "coal_plant"],
                "periods": {2020},
                "slope_dict": {("gas_ct", 2020, 0): 4, ("coal_plant", 2020, 0): 10},
                "intercept_dict": {("gas_ct", 2020, 0): 3, ("coal_plant", 2020, 0): 0},
            },
            # Check VOM curves
            2: {
                "df": pd.DataFrame(
                    columns=vom_columns,
                    data=[
                        ["gas_ct", 2020, 0.5, 2],
                        ["gas_ct", 2020, 1, 1.5],
                        ["coal_plant", 2020, 1, 3],
                    ],
                ),
                "input_col": "average_variable_om_cost_per_mwh",
                "projects": ["gas_ct", "coal_plant"],
                "periods": {2020},
                "slope_dict": {("gas_ct", 2020, 0): 1, ("coal_plant", 2020, 0): 3},
                "intercept_dict": {
                    ("gas_ct", 2020, 0): 0.5,
                    ("coal_plant", 2020, 0): 0,
                },
            },
            # Check that "0" input for period results in same inputs for all
            3: {
                "df": pd.DataFrame(
                    columns=hr_columns,
                    data=[
                        ["gas_ct", 0, 0.5, 10],
                        ["gas_ct", 0, 1, 7],
                        ["coal_plant", 0, 1, 10],
                    ],
                ),
                "input_col": "average_heat_rate_mmbtu_per_mwh",
                "projects": ["gas_ct", "coal_plant"],
                "periods": {2020, 2030},
                "slope_dict": {
                    ("gas_ct", 2020, 0): 4,
                    ("gas_ct", 2030, 0): 4,
                    ("coal_plant", 2020, 0): 10,
                    ("coal_plant", 2030, 0): 10,
                },
                "intercept_dict": {
                    ("gas_ct", 2020, 0): 3,
                    ("gas_ct", 2030, 0): 3,
                    ("coal_plant", 2020, 0): 0,
                    ("coal_plant", 2030, 0): 0,
                },
            },
        }
        for test_case in test_cases.keys():
            expected_slope_dict = test_cases[test_case]["slope_dict"]
            expected_intercept_dict = test_cases[test_case]["intercept_dict"]
            (
                actual_slope_dict,
                actual_intercept_dict,
            ) = get_slopes_intercept_by_project_period_segment(
                df=test_cases[test_case]["df"],
                input_col=test_cases[test_case]["input_col"],
                projects=test_cases[test_case]["projects"],
                periods=test_cases[test_case]["periods"],
            )

            self.assertDictEqual(expected_slope_dict, actual_slope_dict)
            self.assertDictEqual(expected_intercept_dict, actual_intercept_dict)

    # TODO: re-scale load points to fractions
    def test_calculate_slope_intercept(self):
        """
        Check that slope and intercept calculation gives expected
        results for examples with different number of load points
        """
        test_cases = {
            1: {
                "project": "test1",
                "load_points": np.array([10]),
                "heat_rates": np.array([8]),
                "slopes": np.array([8]),
                "intercepts": np.array([0]),
            },
            2: {
                "project": "test2",
                "load_points": np.array([5, 10]),
                "heat_rates": np.array([10, 7]),
                "slopes": np.array([4]),
                "intercepts": np.array([30]),
            },
            3: {
                "project": "test3",
                "load_points": np.array([5, 10, 20]),
                "heat_rates": np.array([10, 7, 6]),
                "slopes": np.array([4, 5]),
                "intercepts": np.array([30, 20]),
            },
        }
        for test_case in test_cases.keys():
            expected_slopes = test_cases[test_case]["slopes"]
            expected_intercepts = test_cases[test_case]["intercepts"]
            actual_slopes, actual_intercepts = calculate_slope_intercept(
                project=test_cases[test_case]["project"],
                load_points=test_cases[test_case]["load_points"],
                heat_rates=test_cases[test_case]["heat_rates"],
            )

            self.assertListEqual(expected_slopes.tolist(), actual_slopes.tolist())
            self.assertListEqual(
                expected_intercepts.tolist(), actual_intercepts.tolist()
            )


if __name__ == "__main__":
    unittest.main()
