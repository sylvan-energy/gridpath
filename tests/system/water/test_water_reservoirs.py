# Copyright 2016-2024 Blue Marble Analytics LLC.
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

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.water_network",
    "system.water.water_system_params",
    "system.water.water_nodes",
    "system.water.water_flows",
    "system.water.water_node_inflows_outflows",
]
NAME_OF_MODULE_BEING_TESTED = "system.water.reservoirs"
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


class TestReservoirs(unittest.TestCase):
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

        # Set: WATER_NODES_W_RESERVOIRS
        expected_r_n = sorted(["Water_Node_1", "Water_Node_2", "Water_Node_3"])
        actual_r_n = sorted([n for n in instance.WATER_NODES_W_RESERVOIRS])

        self.assertListEqual(expected_r_n, actual_r_n)

        # Set: WATER_NODE_WATER_NODE_RESERVOIR_TMPS_W_TARGET_STARTING_VOLUME
        expected_r_tmp = [
            ("Water_Node_1", 20200101),
            ("Water_Node_2", 20200101),
            ("Water_Node_3", 20200101),
        ]

        actual_r_tmp = sorted(
            [
                (r, tmp)
                for (
                    r,
                    tmp,
                ) in instance.WATER_NODE_RESERVOIR_TMPS_W_TARGET_STARTING_VOLUME
            ]
        )

        self.assertListEqual(expected_r_tmp, actual_r_tmp)

        # Param: reservoir_target_starting_volume
        expected_te = {
            ("Water_Node_1", 20200101): 110000,
            ("Water_Node_2", 20200101): 7500,
            ("Water_Node_3", 20200101): 3600,
        }
        actual_te = {
            (r, tmp): instance.reservoir_target_starting_volume[r, tmp]
            for (r, tmp) in instance.WATER_NODE_RESERVOIR_TMPS_W_TARGET_STARTING_VOLUME
        }
        self.assertDictEqual(expected_te, actual_te)

        # Param: reservoir_target_ending_volume
        expected_te = {
            ("Water_Node_1", 20200101): 120000,
            ("Water_Node_2", 20200101): 8000,
            ("Water_Node_3", 20200101): 4000,
        }
        actual_te = {
            (r, tmp): instance.reservoir_target_ending_volume[r, tmp]
            for (r, tmp) in instance.WATER_NODE_RESERVOIR_TMPS_W_TARGET_ENDING_VOLUME
        }
        self.assertDictEqual(expected_te, actual_te)

        # Param: reservoir_target_release_avg_flow_volunit_per_sec
        expected_rt = {
            ("Water_Node_1", "day", 202001): 200,
            ("Water_Node_2", "day", 202001): 200,
            ("Water_Node_3", "day", 202001): 200,
        }
        actual_rt = {
            (r, bt, hrz): instance.reservoir_target_release_avg_flow_volunit_per_sec[
                r, bt, hrz
            ]
            for (
                r,
                bt,
                hrz,
            ) in instance.WATER_NODE_RESERVOIR_BT_HRZS_WITH_TOTAL_RELEASE_REQUIREMENTS
        }
        self.assertDictEqual(expected_rt, actual_rt)

        # Param: maximum_volume_volumeunit
        expected_maxe = {
            "Water_Node_1": 1200,
            "Water_Node_2": 800,
            "Water_Node_3": 600,
        }
        actual_maxe = {
            r: instance.maximum_volume_volumeunit[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(expected_maxe, actual_maxe)

        # Param: minimum_volume_volumeunit
        expected_mine = {
            "Water_Node_1": 1000,
            "Water_Node_2": 700,
            "Water_Node_3": 500,
        }
        actual_mine = {
            r: instance.minimum_volume_volumeunit[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(expected_mine, actual_mine)

        # Param: max_powerhouse_release_vol_unit_per_sec
        expected_maxrelease = {
            "Water_Node_1": 5000,
            "Water_Node_2": 5000,
            "Water_Node_3": 5000,
        }
        actual_maxrelease = {
            r: instance.max_powerhouse_release_vol_unit_per_sec[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(expected_maxrelease, actual_maxrelease)

        # Param: max_spill_vol_unit_per_sec
        expected_maxspill = {
            "Water_Node_1": 100000,
            "Water_Node_2": 100000,
            "Water_Node_3": 100000,
        }
        actual_maxspill = {
            r: instance.max_spill_vol_unit_per_sec[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(expected_maxspill, actual_maxspill)

        # Param: max_total_outflow_vol_unit_per_sec
        expected_max_total_outflow_vol_unit_per_sec = {
            "Water_Node_1": 100001,
            "Water_Node_2": 100001,
            "Water_Node_3": 100001,
        }
        actual_max_total_outflow_vol_unit_per_sec = {
            r: instance.max_total_outflow_vol_unit_per_sec[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(
            expected_max_total_outflow_vol_unit_per_sec,
            actual_max_total_outflow_vol_unit_per_sec,
        )

        # Param: evaporation_coefficient
        expected_evap = {
            "Water_Node_1": 0.1,
            "Water_Node_2": 0.1,
            "Water_Node_3": 0.1,
        }
        actual_evap = {
            r: instance.evaporation_coefficient[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(expected_evap, actual_evap)

        # Param: allow_min_volume_violation
        e_allow_min_volume_violation = {
            "Water_Node_1": 1,
            "Water_Node_2": 1,
            "Water_Node_3": 1,
        }
        a_allow_min_volume_violation = {
            r: instance.allow_min_volume_violation[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(e_allow_min_volume_violation, a_allow_min_volume_violation)

        # Param: min_volume_violation_cost
        e_min_volume_violation_cost = {
            "Water_Node_1": 110,
            "Water_Node_2": 120,
            "Water_Node_3": 130,
        }
        a_min_volume_violation_cost = {
            r: instance.min_volume_violation_cost[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(e_min_volume_violation_cost, a_min_volume_violation_cost)

        # Param: allow_max_volume_violation
        e_allow_max_volume_violation = {
            "Water_Node_1": 1,
            "Water_Node_2": 1,
            "Water_Node_3": 1,
        }
        a_allow_max_volume_violation = {
            r: instance.allow_max_volume_violation[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(e_allow_max_volume_violation, a_allow_max_volume_violation)

        # Param: max_volume_violation_cost
        e_max_volume_violation_cost = {
            "Water_Node_1": 210,
            "Water_Node_2": 220,
            "Water_Node_3": 230,
        }
        a_max_volume_violation_cost = {
            r: instance.max_volume_violation_cost[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(e_max_volume_violation_cost, a_max_volume_violation_cost)

        # Param: allow_target_release_violation
        e_allow_target_release_violation = {
            "Water_Node_1": 1,
            "Water_Node_2": 1,
            "Water_Node_3": 1,
        }
        a_allow_target_release_violation = {
            r: instance.allow_target_release_violation[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(
            e_allow_target_release_violation, a_allow_target_release_violation
        )

        # Param: target_release_violation_cost
        e_target_release_violation_cost = {
            "Water_Node_1": 15000,
            "Water_Node_2": 16000,
            "Water_Node_3": 17000,
        }
        a_target_release_violation_cost = {
            r: instance.target_release_violation_cost[r]
            for r in instance.WATER_NODES_W_RESERVOIRS
        }
        self.assertDictEqual(
            e_target_release_violation_cost, a_target_release_violation_cost
        )
