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
import shutil
import sys
import tempfile
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
]
NAME_OF_MODULE_BEING_TESTED = "system.water.water_nodes"
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


class TestWaterNodes(unittest.TestCase):
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

        # Set: WATER_NODES
        expected_wn = sorted(["Water_Node_1", "Water_Node_2", "Water_Node_3"])
        actual_wn = sorted([wn for wn in instance.WATER_NODES])
        self.assertListEqual(expected_wn, actual_wn)

        # Param: exogenous_water_inflow_rate_vol_per_sec
        df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "water_inflows.tab"),
            sep="\t",
        )

        # Check that no values are getting the default value of 0
        df = df.replace(".", 0)
        df["exogenous_water_inflow_rate_vol_per_sec"] = pd.to_numeric(
            df["exogenous_water_inflow_rate_vol_per_sec"]
        )

        expected_min_bound = df.set_index(["water_node", "timepoint"]).to_dict()[
            "exogenous_water_inflow_rate_vol_per_sec"
        ]
        actual_min_bound = {
            (wl, tmp): instance.exogenous_water_inflow_rate_vol_per_sec[wl, tmp]
            for wl in instance.WATER_NODES
            for tmp in instance.TMPS
        }
        self.assertDictEqual(expected_min_bound, actual_min_bound)

        # Set: WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS
        expected_bt_hrz = sorted(
            [("Water_Node_2", "day", 202001), ("Water_Node_3", "day", 202002)]
        )
        actual_bt_hrz = sorted(
            [
                (wn, bt, hrz)
                for (wn, bt, hrz) in instance.WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS
            ]
        )
        self.assertListEqual(expected_bt_hrz, actual_bt_hrz)

        # Param: exogenous_water_inflow_rate_avg_vol_per_sec
        expected_avg_inflow = {
            ("Water_Node_2", "day", 202001): 0.5,
            ("Water_Node_3", "day", 202002): 0.25,
        }
        actual_avg_inflow = {
            (wn, bt, hrz): instance.exogenous_water_inflow_rate_avg_vol_per_sec[
                wn, bt, hrz
            ]
            for (wn, bt, hrz) in instance.WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS
        }
        self.assertDictEqual(expected_avg_inflow, actual_avg_inflow)

        # Param: total_exogenous_water_inflow_rate_vol_per_sec
        # The timepoint-level and horizon-level inflows are additive: the
        # horizon-level average rate is added in each of the horizon's
        # timepoints
        hrz_tmp_df = pd.read_csv(
            os.path.join(
                TEST_DATA_DIRECTORY, "inputs", "horizon_user_defined_timepoints.tab"
            ),
            sep="\t",
        )
        expected_total = dict(expected_min_bound)
        for (wn, bt, hrz), avg_rate in expected_avg_inflow.items():
            hrz_tmps = hrz_tmp_df.loc[
                (hrz_tmp_df["balancing_type_horizon"] == bt)
                & (hrz_tmp_df["horizon"] == hrz),
                "timepoint",
            ]
            for tmp in hrz_tmps:
                expected_total[wn, tmp] = expected_total[wn, tmp] + avg_rate
        actual_total = {
            (wn, tmp): instance.total_exogenous_water_inflow_rate_vol_per_sec[wn, tmp]
            for wn in instance.WATER_NODES
            for tmp in instance.TMPS
        }
        self.assertDictEqual(expected_total, actual_total)

        # Set: WATER_LINKS_TO_BY_WATER_NODE
        expected_l = {
            "Water_Node_1": [],
            "Water_Node_2": ["Water_Link_12"],
            "Water_Node_3": ["Water_Link_23"],
        }
        actual_l = {
            wn: instance.WATER_LINKS_TO_BY_WATER_NODE[wn]
            for wn in instance.WATER_LINKS_TO_BY_WATER_NODE.keys()
        }
        self.assertDictEqual(expected_l, actual_l)

        # Set: WATER_LINKS_FROM_BY_WATER_NODE
        expected_l = {
            "Water_Node_1": ["Water_Link_12"],
            "Water_Node_2": ["Water_Link_23"],
            "Water_Node_3": [],
        }
        actual_l = {
            wn: instance.WATER_LINKS_FROM_BY_WATER_NODE[wn]
            for wn in instance.WATER_LINKS_FROM_BY_WATER_NODE.keys()
        }
        self.assertDictEqual(expected_l, actual_l)

    def test_tmp_inflow_file_is_optional(self):
        """
        Both inflow files are optional: with no water_inflows.tab, the
        timepoint-level inflows default to 0 and the total inflows equal
        the horizon-level contributions alone.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_data_dir = os.path.join(tmp_dir, "test_data")
            shutil.copytree(TEST_DATA_DIRECTORY, test_data_dir)
            os.remove(os.path.join(test_data_dir, "inputs", "water_inflows.tab"))

            m, data = add_components_and_load_data(
                prereq_modules=IMPORTED_PREREQ_MODULES,
                module_to_test=MODULE_BEING_TESTED,
                test_data_dir=test_data_dir,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
            )
            instance = m.create_instance(data)

        # Timepoint-level inflows are all at their default of 0
        for wn in instance.WATER_NODES:
            for tmp in instance.TMPS:
                self.assertEqual(
                    0, instance.exogenous_water_inflow_rate_vol_per_sec[wn, tmp]
                )

        # Totals equal the horizon-level contributions alone
        hrz_tmp_df = pd.read_csv(
            os.path.join(
                TEST_DATA_DIRECTORY, "inputs", "horizon_user_defined_timepoints.tab"
            ),
            sep="\t",
        )
        expected_total = {
            (wn, tmp): 0 for wn in instance.WATER_NODES for tmp in instance.TMPS
        }
        for wn, bt, hrz in instance.WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS:
            avg_rate = instance.exogenous_water_inflow_rate_avg_vol_per_sec[wn, bt, hrz]
            hrz_tmps = hrz_tmp_df.loc[
                (hrz_tmp_df["balancing_type_horizon"] == bt)
                & (hrz_tmp_df["horizon"] == hrz),
                "timepoint",
            ]
            for tmp in hrz_tmps:
                expected_total[wn, tmp] = expected_total[wn, tmp] + avg_rate
        actual_total = {
            (wn, tmp): instance.total_exogenous_water_inflow_rate_vol_per_sec[wn, tmp]
            for wn in instance.WATER_NODES
            for tmp in instance.TMPS
        }
        self.assertDictEqual(expected_total, actual_total)
