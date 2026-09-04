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
import pandas as pd
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
NAME_OF_MODULE_BEING_TESTED = "project.operations.operational_types.gen_var_stor_hyb"
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


class TestGenVarStorHybOpType(unittest.TestCase):
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

        # Set: GEN_VAR_STOR_HYB
        expected_gen_set = sorted(["Wind_Battery_Hybrid"])
        actual_gen_set = sorted([prj for prj in instance.GEN_VAR_STOR_HYB])
        self.assertListEqual(expected_gen_set, actual_gen_set)

        # Set: GEN_VAR_STOR_HYB_OPR_TMPS
        expected_operational_timepoints_by_project = sorted(
            get_project_operational_timepoints(expected_gen_set)
        )
        actual_operational_timepoints_by_project = sorted(
            [(g, tmp) for (g, tmp) in instance.GEN_VAR_STOR_HYB_OPR_TMPS]
        )
        self.assertListEqual(
            expected_operational_timepoints_by_project,
            actual_operational_timepoints_by_project,
        )

        # Param: gen_var_cap_factor_default
        expected_cap_factor_default = {"Wind_Battery_Hybrid": "undefined"}
        actual_cap_factor_default = {
            prj: instance.gen_var_stor_hyb_cap_factor_default[prj]
            for prj in instance.GEN_VAR_STOR_HYB
        }
        self.assertDictEqual(expected_cap_factor_default, actual_cap_factor_default)

        # Param: gen_var_stor_hyb_cap_factor
        all_df = pd.read_csv(
            os.path.join(
                TEST_DATA_DIRECTORY, "inputs", "variable_generator_profiles.tab"
            ),
            sep="\t",
        )

        # We only want projects of the 'gen_var_stor_hyb' operational type
        v_df = all_df[all_df["project"].isin(expected_gen_set)]
        expected_cap_factor = v_df.set_index(["project", "timepoint"]).to_dict()[
            "cap_factor"
        ]

        actual_cap_factor = {
            (g, tmp): instance.gen_var_stor_hyb_cap_factor[g, tmp]
            for (g, tmp) in instance.GEN_VAR_STOR_HYB_OPR_TMPS
        }
        self.assertDictEqual(expected_cap_factor, actual_cap_factor)

        # Params: gen_var_stor_hyb_charging_efficiency
        expected_ch_eff = OrderedDict(sorted({"Wind_Battery_Hybrid": 0.8}.items()))
        actual_ch_eff = OrderedDict(
            sorted(
                {
                    prj: instance.gen_var_stor_hyb_charging_efficiency[prj]
                    for prj in instance.GEN_VAR_STOR_HYB
                }.items()
            )
        )
        self.assertDictEqual(expected_ch_eff, actual_ch_eff)

        # Params: gen_var_stor_hyb_discharging_efficiency
        expected_disch_eff = OrderedDict(sorted({"Wind_Battery_Hybrid": 0.8}.items()))
        actual_disch_eff = OrderedDict(
            sorted(
                {
                    prj: instance.gen_var_stor_hyb_discharging_efficiency[prj]
                    for prj in instance.GEN_VAR_STOR_HYB
                }.items()
            )
        )
        self.assertDictEqual(expected_disch_eff, actual_disch_eff)

        # Param: gen_var_stor_hyb_reserves_setpoint_duration_hours (sparse: no
        # default, so only projects with a specified value are "in" the param)
        expected_reserves_setpoint_duration = {"Wind_Battery_Hybrid": 2}
        actual_reserves_setpoint_duration = {
            prj: instance.gen_var_stor_hyb_reserves_setpoint_duration_hours[prj]
            for prj in instance.GEN_VAR_STOR_HYB
            if prj in instance.gen_var_stor_hyb_reserves_setpoint_duration_hours
        }
        self.assertDictEqual(
            expected_reserves_setpoint_duration, actual_reserves_setpoint_duration
        )


if __name__ == "__main__":
    unittest.main()
