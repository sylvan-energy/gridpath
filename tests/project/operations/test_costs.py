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


from importlib import import_module
import os.path
import pandas as pd
import sys
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data
from tests.project.operations.common_functions import get_project_operational_timepoints

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.markets",
    "system.markets.prices",
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
    "system.load_balance.static_load_requirement",
    "project.capacity.potential",
    "project.operations.operational_types",
    "project.operations.power",
    "project.operations.fuel_burn",
]
NAME_OF_MODULE_BEING_TESTED = "project.operations.costs"
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


class TestOperationalCosts(unittest.TestCase):
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

        # Load test data as dataframes
        projects_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "projects.tab"), sep="\t"
        )

        var_om_curve_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "variable_om_curves.tab"),
            sep="\t",
        )

        startup_by_st_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "startup_chars.tab"), sep="\t"
        )

        timepoints_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "timepoints.tab"),
            sep="\t",
            usecols=["timepoint", "period"],
        )

        # Set: VAR_OM_COST_SIMPLE_PRJ_OPR_TMPS
        expected_var_om_simple_projects = sorted(
            projects_df[projects_df["variable_om_cost_per_mwh"] != "."][
                "project"
            ].tolist()
        )
        expected_var_om_simple_prj_tmps = get_project_operational_timepoints(
            expected_var_om_simple_projects
        )

        actual_var_om_simple_prj_tmps = sorted(
            [(p, tmp) for (p, tmp) in instance.VAR_OM_COST_SIMPLE_PRJ_OPR_TMPS]
        )

        self.assertListEqual(
            expected_var_om_simple_prj_tmps, actual_var_om_simple_prj_tmps
        )

        # Set: VAR_OM_COST_CURVE_PRJS_OPR_TMPS
        expected_var_om_curve_projects = sorted(
            var_om_curve_df["project"].unique().tolist()
        )

        expected_var_om_curve_prj_tmps = get_project_operational_timepoints(
            expected_var_om_curve_projects
        )

        actual_var_om_curve_prj_tmps = sorted(
            [(p, tmp) for (p, tmp) in instance.VAR_OM_COST_CURVE_PRJS_OPR_TMPS]
        )

        self.assertListEqual(
            expected_var_om_curve_prj_tmps, actual_var_om_curve_prj_tmps
        )

        # Set: VAR_OM_COST_CURVE_PRJS_OPR_TMPS_SGMS
        expected_segments_by_prj_period = {
            ("Disp_Binary_Commit", 2020): [0, 1],
            ("Disp_Binary_Commit", 2030): [0],
            ("Disp_Cont_Commit", 2020): [0],
            ("Disp_Cont_Commit", 2030): [0],
        }
        expected_var_om_curve_prj_tmp_sgms = list()
        for prj, tmp in expected_var_om_curve_prj_tmps:
            prd = timepoints_df[timepoints_df["timepoint"] == tmp].iloc[0]["period"]
            segments = expected_segments_by_prj_period[prj, prd]
            for sgm in segments:
                expected_var_om_curve_prj_tmp_sgms.append((prj, tmp, sgm))

        actual_var_om_curve_prj_tmp_sgms = sorted(
            [
                (prj, tmp, sgm)
                for (prj, tmp, sgm) in instance.VAR_OM_COST_CURVE_PRJS_OPR_TMPS_SGMS
            ]
        )

        self.assertListEqual(
            expected_var_om_curve_prj_tmp_sgms, actual_var_om_curve_prj_tmp_sgms
        )

        # Set: VAR_OM_COST_ALL_PRJS_OPR_TMPS
        expected_var_om_all_prj_tmps = sorted(
            list(set(expected_var_om_simple_prj_tmps + expected_var_om_curve_prj_tmps))
        )

        actual_var_om_all_prj_tmps = sorted(
            [(p, tmp) for (p, tmp) in instance.VAR_OM_COST_ALL_PRJS_OPR_TMPS]
        )

        self.assertListEqual(expected_var_om_all_prj_tmps, actual_var_om_all_prj_tmps)

        # Set: STARTUP_COST_PRJ_OPR_TMPS
        expected_startup_cost_simple_projects = sorted(
            projects_df[projects_df["startup_cost_per_mw"] != "."]["project"].tolist()
        )
        expected_startup_by_st_projects = sorted(
            startup_by_st_df["project"].unique().tolist()
        )
        expected_startup_cost_all_projects = sorted(
            list(
                set(
                    expected_startup_cost_simple_projects
                    + expected_startup_by_st_projects
                )
            )
        )
        expected_startup_cost_all_prj_tmps = get_project_operational_timepoints(
            expected_startup_cost_all_projects
        )
        actual_startup_cost_all_prj_tmps = sorted(
            [(p, tmp) for (p, tmp) in instance.STARTUP_COST_PRJ_OPR_TMPS]
        )

        self.assertListEqual(
            expected_startup_cost_all_prj_tmps, actual_startup_cost_all_prj_tmps
        )

        # Set: SHUTDOWN_COST_PRJ_OPR_TMPS
        expected_shutdown_cost_projects = sorted(
            projects_df[projects_df["shutdown_cost_per_mw"] != "."]["project"].tolist()
        )
        expected_shutdown_cost_prj_tmps = get_project_operational_timepoints(
            expected_shutdown_cost_projects
        )

        actual_shutdown_cost_prj_tmps = sorted(
            [(p, tmp) for (p, tmp) in instance.SHUTDOWN_COST_PRJ_OPR_TMPS]
        )

        self.assertListEqual(
            expected_shutdown_cost_prj_tmps, actual_shutdown_cost_prj_tmps
        )

        # Set: VIOL_ALL_PRJ_OPR_TMPS
        expected_ramp_up_viol_projects = sorted(
            projects_df[projects_df["ramp_up_violation_penalty"] != "."][
                "project"
            ].tolist()
        )
        expected_ramp_down_viol_projects = sorted(
            projects_df[projects_df["ramp_down_violation_penalty"] != "."][
                "project"
            ].tolist()
        )
        expected_min_up_time_viol_projects = sorted(
            projects_df[projects_df["min_up_time_violation_penalty"] != "."][
                "project"
            ].tolist()
        )
        expected_min_down_time_viol_projects = sorted(
            projects_df[projects_df["min_down_time_violation_penalty"] != "."][
                "project"
            ].tolist()
        )
        expected_opr_viol_prj_tmps = get_project_operational_timepoints(
            expected_ramp_up_viol_projects
            + expected_ramp_down_viol_projects
            + expected_min_up_time_viol_projects
            + expected_min_down_time_viol_projects
        )

        actual_opr_viol_prj_tmps = sorted(
            [(p, tmp) for (p, tmp) in instance.VIOL_ALL_PRJ_OPR_TMPS]
        )

        self.assertListEqual(expected_opr_viol_prj_tmps, actual_opr_viol_prj_tmps)

        # Set: CURTAILMENT_COST_PRJ_OPR_TMPS
        expected_curt_cost_projects = ["Battery", "Wind", "Wind_Battery_Hybrid"]

        expected_curt_cost_prj_tmps = get_project_operational_timepoints(
            expected_curt_cost_projects
        )

        actual_curt_cost_prj_tmps = sorted(
            [(p, tmp) for (p, tmp) in instance.CURTAILMENT_COST_PRJ_OPR_TMPS]
        )

        self.assertListEqual(expected_curt_cost_prj_tmps, actual_curt_cost_prj_tmps)


if __name__ == "__main__":
    unittest.main()
