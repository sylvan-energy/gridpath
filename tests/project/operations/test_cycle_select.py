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
]
NAME_OF_MODULE_BEING_TESTED = "project.operations.cycle_select"
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


class TestCycleSelect(unittest.TestCase):
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

        # Set: GEN_COMMIT_BINLIN
        expected_gen_commit_binlin = sorted(
            [
                "Disp_Binary_Commit",
                "Disp_Cont_Commit",
                "Clunky_Old_Gen",
                "Clunky_Old_Gen2",
            ]
        )
        actual_gen_commit_binlin = sorted([prj for prj in instance.GEN_COMMIT_BINLIN])

        self.assertListEqual(expected_gen_commit_binlin, actual_gen_commit_binlin)

        # Set: GEN_W_CYCLE_SELECT
        expected_gen_w_cycle_select = sorted(["Disp_Binary_Commit", "Clunky_Old_Gen"])
        actual_gen_w_cycle_select = sorted([prj for prj in instance.GEN_W_CYCLE_SELECT])

        self.assertListEqual(expected_gen_w_cycle_select, actual_gen_w_cycle_select)

        # Set: GEN_CYCLE_SELECT_BY_GEN
        expected_select_cycle_by_prj = {
            "Disp_Binary_Commit": ["Disp_Cont_Commit"],
            "Clunky_Old_Gen": ["Clunky_Old_Gen2"],
        }
        actual_select_cycle_by_prj = {
            g: [g_c for g_c in instance.GEN_CYCLE_SELECT_BY_GEN[g]]
            for g in instance.GEN_W_CYCLE_SELECT
        }

        self.assertDictEqual(expected_select_cycle_by_prj, actual_select_cycle_by_prj)

        # Set: GEN_W_GEN_CYCLE_SELECT_OPR_TMPS
        expected_operational_timepoints_by_project = sorted(
            get_project_operational_timepoints(expected_gen_w_cycle_select)
        )
        expected_cycle_select_opr_tmps = list()
        for p, tmp in expected_operational_timepoints_by_project:
            cycle_select_prj_list = expected_select_cycle_by_prj[p]
            # Only expecting the timepoints for projects that do have cycle-select
            # projects
            if cycle_select_prj_list:
                for g_cycle in cycle_select_prj_list:
                    expected_cycle_select_opr_tmps.append((p, g_cycle, tmp))

        expected_cycle_select_opr_tmps = sorted(expected_cycle_select_opr_tmps)

        actual_cycle_select_opr_tmps = sorted(
            [
                (g, g_cycle, tmp)
                for (
                    g,
                    g_cycle,
                    tmp,
                ) in instance.GEN_W_GEN_CYCLE_SELECT_OPR_TMPS
            ]
        )
        self.assertListEqual(
            expected_cycle_select_opr_tmps, actual_cycle_select_opr_tmps
        )


if __name__ == "__main__":
    unittest.main()
