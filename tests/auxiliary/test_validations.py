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

import numpy as np
import pandas as pd
import sqlite3
import unittest

import gridpath.auxiliary.validations as module_to_test


class TestValidations(unittest.TestCase):
    """ """

    def test_get_expected_dtypes(self):
        """

        :return:
        """

        # Setup
        conn = sqlite3.connect(":memory:")
        conn.execute("""CREATE TABLE table1 (
            col1 INTEGER, col2 FLOAT, col3 DOUBLE, col4 TEXT, col5 VARCHAR(32)
            );""")
        conn.execute("""CREATE TABLE table2 (
            col1 TEXT, col6 VARCHAR(64), col7 VARCHAR(128)
            );""")
        conn.commit()

        # Test dict gets created properly for one table
        expected_dict = {
            "col1": "numeric",
            "col2": "numeric",
            "col3": "numeric",
            "col4": "string",
            "col5": "string",
        }
        actual_dict = module_to_test.get_expected_dtypes(conn, ["table1"])
        self.assertDictEqual(expected_dict, actual_dict)

        # Test dict gets created properly for multiple tables
        expected_dict = {
            "col1": "string",
            "col2": "numeric",
            "col3": "numeric",
            "col4": "string",
            "col5": "string",
            "col6": "string",
            "col7": "string",
        }
        actual_dict = module_to_test.get_expected_dtypes(conn, ["table1", "table2"])
        self.assertDictEqual(expected_dict, actual_dict)

        # Tear down: close connection
        conn.close()

    def test_validate_dtypes(self):
        """

        :return:
        """
        df_columns = ["project", "capacity"]
        test_cases = {
            # Make sure correct inputs don't throw error
            1: {
                "df": pd.DataFrame(
                    columns=df_columns, data=[["gas_ct", 10], ["coal_plant", 20]]
                ),
                "expected_dtypes": {"project": "string", "capacity": "numeric"},
                "result": ([], []),
            },
            # Test invalid string in numeric column
            2: {
                "df": pd.DataFrame(
                    columns=df_columns, data=[["gas_ct", 10], ["coal_plant", "string"]]
                ),
                "expected_dtypes": {"project": "string", "capacity": "numeric"},
                "result": (
                    ["Invalid data type for column 'capacity'; expected numeric"],
                    ["capacity"],
                ),
            },
            # Test invalid numeric column in string column (all rows)
            3: {
                "df": pd.DataFrame(columns=df_columns, data=[[1, 10], [1, 20]]),
                "expected_dtypes": {"project": "string", "capacity": "numeric"},
                "result": (
                    ["Invalid data type for column 'project'; expected string"],
                    ["project"],
                ),
            },
            # Test invalid numeric column in string column (any row)
            4: {
                "df": pd.DataFrame(columns=df_columns, data=[["gas_ct", 10], [1, 20]]),
                "expected_dtypes": {"project": "string", "capacity": "numeric"},
                "result": (
                    ["Invalid data type for column 'project'; expected string"],
                    ["project"],
                ),
            },
            # Columns with all None are ignored
            5: {
                "df": pd.DataFrame(columns=df_columns, data=[[None, 10], [None, 20]]),
                "expected_dtypes": {"project": "string", "capacity": "numeric"},
                "result": ([], []),
            },
            # Columns with all NaN are ignored
            6: {
                "df": pd.DataFrame(
                    columns=df_columns, data=[[np.nan, 10], [np.nan, 20]]
                ),
                "expected_dtypes": {"project": "string", "capacity": "numeric"},
                "result": ([], []),
            },
            # Columns with some None are not ignored
            7: {
                "df": pd.DataFrame(columns=df_columns, data=[[10, 10], [None, 20]]),
                "expected_dtypes": {"project": "string", "capacity": "numeric"},
                "result": (
                    ["Invalid data type for column 'project'; expected string"],
                    ["project"],
                ),
            },
            # Test multiple error columns
            8: {
                "df": pd.DataFrame(
                    columns=df_columns, data=[[10, "string"], [10, "string"]]
                ),
                "expected_dtypes": {"project": "string", "capacity": "numeric"},
                "result": (
                    [
                        "Invalid data type for column 'project'; expected string",
                        "Invalid data type for column 'capacity'; expected numeric",
                    ],
                    ["project", "capacity"],
                ),
            },
        }

        for test_case in test_cases.keys():
            expected_tuple = test_cases[test_case]["result"]
            actual_tuple = module_to_test.validate_dtypes(
                df=test_cases[test_case]["df"],
                expected_dtypes=test_cases[test_case]["expected_dtypes"],
            )
            self.assertTupleEqual(expected_tuple, actual_tuple)

    def test_validate_values(self):
        """

        :return:
        """
        cols = ["project", "load_point_fraction", "average_heat_rate_mmbtu_per_mwh"]
        cols_to_check = ["load_point_fraction", "average_heat_rate_mmbtu_per_mwh"]
        idx_col = "project"
        test_cases = {
            # Make sure correct inputs aren't flagged
            1: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 0, 10.5],
                        ["gas_ct", 1, 9],
                        ["coal_plant", 0.5, 10],
                    ],
                ),
                "min": 0,
                "max": np.inf,
                "strict_min": False,
                "strict_max": False,
                "result": [],
            },
            # Make sure strict inequality requirement works
            2: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 0, 10.5],
                        ["gas_ct", 1, 9],
                        ["coal_plant", 0.5, 10],
                    ],
                ),
                "min": 0,
                "max": np.inf,
                "strict_min": True,
                "strict_max": False,
                "result": [
                    "project(s) 'gas_ct': Expected 0 < 'load_point_fraction' <= inf"
                ],
            },
            # If >1 error in different columns separate error msgs are created
            3: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 0, -10.5],
                        ["gas_ct", -1, 9],
                        ["coal_plant", -0.5, 10],
                    ],
                ),
                "min": 0,
                "max": np.inf,
                "strict_min": False,
                "strict_max": False,
                "result": [
                    "project(s) 'gas_ct, coal_plant': Expected 0 <= 'load_point_fraction' <= inf",
                    "project(s) 'gas_ct': Expected 0 <= 'average_heat_rate_mmbtu_per_mwh' <= inf",
                ],
            },
            # Make sure upper bounds are working
            4: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 0.2, 1],
                        ["gas_ct", 0.5, 0.9],
                        ["coal_plant", 1, 1.9],
                    ],
                ),
                "min": 0,
                "max": 1,
                "strict_min": False,
                "strict_max": False,
                "result": [
                    "project(s) 'coal_plant': Expected 0 <= 'average_heat_rate_mmbtu_per_mwh' <= 1"
                ],
            },
        }

        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_values(
                df=test_cases[test_case]["df"],
                col=cols_to_check,
                idx_col=idx_col,
                min=test_cases[test_case]["min"],
                max=test_cases[test_case]["max"],
                strict_min=test_cases[test_case]["strict_min"],
                strict_max=test_cases[test_case]["strict_max"],
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_values_multi_column_index(self):
        """
        A list-valued idx_col (a multi-column index, e.g. project plus
        balancing type and horizon) formats the offending indices as a flat
        string rather than raising.
        """
        df = pd.DataFrame(
            columns=["project", "balancing_type_horizon", "horizon", "share"],
            data=[
                ["Hydro", "day", 202001, 0.5],
                ["Hydro", "day", 202002, 1.5],
            ],
        )
        self.assertListEqual(
            [
                "['project', 'balancing_type_horizon', 'horizon'](s) "
                "'Hydro-day-202002': Expected 0 <= 'share' <= 1"
            ],
            module_to_test.validate_values(
                df=df,
                col=["share"],
                idx_col=["project", "balancing_type_horizon", "horizon"],
                min=0,
                max=1,
            ),
        )

    def test_validate_req_cols(self):
        """

        :return:
        """

        df_columns = [
            "project",
            "min_stable_level_fraction",
            "unit_size_mw",
            "startup_cost_per_mw",
            "shutdown_cost_per_mw",
        ]
        test_cases = {
            # Make sure correct inputs don't throw error
            1: {
                "df": pd.DataFrame(
                    columns=df_columns, data=[["nuclear", 0.5, 100, None, None]]
                ),
                "columns": ["min_stable_level_fraction", "unit_size_mw"],
                "required": True,
                "category": "Always_on",
                "result": [],
            },
            # Make sure missing required inputs are flagged
            2: {
                "df": pd.DataFrame(
                    columns=df_columns, data=[["nuclear", None, 100, None, None]]
                ),
                "columns": ["min_stable_level_fraction", "unit_size_mw"],
                "required": True,
                "category": "Always_on",
                "result": [
                    "project(s) 'nuclear'; Always_on should have "
                    "inputs for 'min_stable_level_fraction'"
                ],
            },
            # Make sure incompatible inputs are flagged
            3: {
                "df": pd.DataFrame(
                    columns=df_columns, data=[["nuclear", 0.5, 100, 1000, None]]
                ),
                "columns": ["startup_cost_per_mw", "shutdown_cost_per_mw"],
                "required": False,
                "category": "Always_on",
                "result": [
                    "project(s) 'nuclear'; Always_on should not have inputs for 'startup_cost_per_mw'"
                ],
            },
        }

        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_req_cols(
                df=test_cases[test_case]["df"],
                columns=test_cases[test_case]["columns"],
                required=test_cases[test_case]["required"],
                category=test_cases[test_case]["category"],
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_columns(self):
        cols1 = ["project", "capacity_type", "operational_type"]
        cols2 = ["transmission_line", "capacity_type", "operational_type"]
        test_cases = {
            # Make sure matching valids don't throw errors
            1: {
                "df": pd.DataFrame(
                    columns=cols1, data=[["gas_ct", "gen_new_lin", "gen_commit_cap"]]
                ),
                "columns": "capacity_type",
                "valids": ["gen_new_lin"],
                "invalids": [],
                "result": [],
            },
            # Make sure non-matching invalids don't throw errors
            # and test out multiple columns
            2: {
                "df": pd.DataFrame(
                    columns=cols1, data=[["gas_ct", "gen_new_lin", "gen_commit_cap"]]
                ),
                "columns": ["capacity_type", "operational_type"],
                "valids": [],
                "invalids": [("invalid1", "invalid2")],
                "result": [],
            },
            # Make sure non-matching valids are detected
            3: {
                "df": pd.DataFrame(
                    columns=cols1,
                    data=[
                        ["gas_ct1", "gen_new_lin", "gen_commit_cap"],
                        ["gas_ct2", "invalid_cap_type", "gen_commit_cap"],
                        ["storage_plant", "stor_new_lin", "stor"],
                    ],
                ),
                "columns": "capacity_type",
                "valids": ["gen_new_lin", "stor_new_lin"],
                "invalids": [],
                "result": [
                    "project(s) 'gas_ct2': Invalid entry for "
                    "capacity_type. Valid options are ['gen_new_lin', "
                    "'stor_new_lin']."
                ],
            },
            # Make sure matching invalids are detected
            4: {
                "df": pd.DataFrame(
                    columns=cols1,
                    data=[["gas_ct1", "cap1", "op2"], ["gas_ct2", "cap1", "op3"]],
                ),
                "columns": ["capacity_type", "operational_type"],
                "valids": [],
                "invalids": [("cap1", "op2")],
                "result": [
                    "project(s) 'gas_ct1': Invalid entry for "
                    "['capacity_type', 'operational_type']. Invalid "
                    "options are [('cap1', 'op2')]."
                ],
            },
            # Make sure non-matching valids and matching invalids and are
            # detected
            5: {
                "df": pd.DataFrame(
                    columns=cols1,
                    data=[
                        ["gas_ct1", "cap1", "op2"],
                        ["gas_ct2", "cap1", "op3"],
                    ],
                ),
                "columns": ["capacity_type", "operational_type"],
                "valids": [("cap1", "op1")],
                "invalids": [("cap1", "op2")],
                "result": [
                    "project(s) 'gas_ct1, gas_ct2': Invalid entry for "
                    "['capacity_type', 'operational_type']. Valid "
                    "options are [('cap1', 'op1')]. Invalid "
                    "options are [('cap1', 'op2')]."
                ],
            },
            # Test idx_col lookup for transmission lines
            6: {
                "df": pd.DataFrame(
                    columns=cols2,
                    data=[
                        ["tx1", "new_build", "tx_dcopf"],
                        ["tx2", "new_build", "tx_simple"],
                    ],
                ),
                "columns": ["capacity_type", "operational_type"],
                "valids": [],
                "invalids": [("new_build", "tx_dcopf")],
                "result": [
                    "transmission_line(s) 'tx1': Invalid entry for "
                    "['capacity_type', 'operational_type']. Invalid "
                    "options are [('new_build', 'tx_dcopf')]."
                ],
            },
        }

        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_columns(
                df=test_cases[test_case]["df"],
                columns=test_cases[test_case]["columns"],
                valids=test_cases[test_case]["valids"],
                invalids=test_cases[test_case]["invalids"],
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_idxs(self):
        test_cases = {
            # Make sure correct inputs don't throw error
            1: {
                "actual_idxs": ["gas_ct", "coal_plant"],
                "req_idxs": ["gas_ct"],
                "invalid_idxs": ["gen_gas_ct2"],
                "idx_label": "project",
                "msg": "",
                "result": [],
            },
            # Make sure missing required indexes inputs are detected
            2: {
                "actual_idxs": [],
                "req_idxs": ["gas_ct"],
                "invalid_idxs": [],
                "idx_label": "project",
                "msg": "",
                "result": ["Missing required inputs for project: ['gas_ct']. "],
            },
            # Make sure missing required tuple indexes are properly detected
            3: {
                "actual_idxs": [],
                "req_idxs": [("gas_ct", 2020)],
                "invalid_idxs": [],
                "idx_label": "(project, period)",
                "msg": "",
                "result": [
                    "Missing required inputs for (project, period): [('gas_ct', 2020)]. "
                ],
            },
            # Make sure multiple missing required tuple indexes are properly
            # detected (results are sorted!)
            4: {
                "actual_idxs": [],
                "req_idxs": [("gas_ct", 2020), ("coal_plant", 2020)],
                "invalid_idxs": [],
                "idx_label": "(project, period)",
                "msg": "",
                "result": [
                    "Missing required inputs for (project, period): [('coal_plant', 2020), ('gas_ct', 2020)]. "
                ],
            },
            # Make sure invalid idxs are detected and error message is added.
            5: {
                "actual_idxs": ["gas_ct", "btm_solar"],
                "req_idxs": [],
                "invalid_idxs": ["btm_solar"],
                "idx_label": "project",
                "msg": "gen_var_must_take cannot provide lf_down.",
                "result": [
                    "Invalid inputs for project: ['btm_solar']. gen_var_must_take cannot provide lf_down."
                ],
            },
            # Make sure multiple invalid idxs are detected correctly
            6: {
                "actual_idxs": ["gas_ct", "btm_solar", "btm_wind"],
                "req_idxs": [],
                "invalid_idxs": ["btm_solar", "btm_wind"],
                "idx_label": "project",
                "msg": "gen_var_must_take cannot provide lf_down.",
                "result": [
                    "Invalid inputs for project: ['btm_solar', 'btm_wind']. gen_var_must_take cannot provide lf_down."
                ],
            },
        }

        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_idxs(
                actual_idxs=test_cases[test_case]["actual_idxs"],
                req_idxs=test_cases[test_case]["req_idxs"],
                invalid_idxs=test_cases[test_case]["invalid_idxs"],
                idx_label=test_cases[test_case]["idx_label"],
                msg=test_cases[test_case]["msg"],
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_single_input(self):
        """

        :return:
        """

        df_columns = ["project", "load_point_fraction"]
        test_cases = {
            # Make sure correct inputs don't throw error
            1: {
                "df": pd.DataFrame(columns=df_columns, data=[["nuclear", 100]]),
                "idx_col": "project",
                "msg": "test msg",
                "result": [],
            },
            # Make sure multiple inputs per index are flagged
            2: {
                "df": pd.DataFrame(
                    columns=df_columns,
                    data=[["nuclear", 100], ["nuclear", 200], ["gas_ct", 10]],
                ),
                "idx_col": "project",
                "msg": "test msg",
                "result": [
                    "project(s) 'nuclear': Too many inputs! Maximum 1 input per project. test msg"
                ],
            },
        }

        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_single_input(
                df=test_cases[test_case]["df"],
                idx_col=test_cases[test_case]["idx_col"],
                msg=test_cases[test_case]["msg"],
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_piecewise_curves(self):
        df_columns = [
            "project",
            "period",
            "load_point_fraction",
            "average_heat_rate_mmbtu_per_mwh",
        ]
        x_col = "load_point_fraction"
        slope_col = "average_heat_rate_mmbtu_per_mwh"
        y_name = "fuel burn"
        test_cases = {
            # Make sure correct inputs don't throw error
            1: {
                "df": pd.DataFrame(
                    columns=df_columns,
                    data=[
                        ["gas_ct", 2020, 10, 10.5],
                        ["gas_ct", 2020, 20, 9],
                        ["coal_plant", 2020, 100, 10],
                    ],
                ),
                "result": [],
            },
            # Make sure all different error types are detected
            2: {
                "df": pd.DataFrame(
                    columns=df_columns,
                    data=[
                        ["gas_ct2", 2020, 10, 11],
                        ["gas_ct2", 2020, 10, 12],
                        ["gas_ct3", 2020, 10, 11],
                        ["gas_ct3", 2020, 20, 5],
                        ["gas_ct4", 2020, 10, 11],
                        ["gas_ct4", 2020, 20, 10],
                        ["gas_ct4", 2020, 30, 9],
                    ],
                ),
                "result": [
                    "project-period 'gas_ct2-2020': load_point_fraction values can not be identical",
                    "project-period 'gas_ct3-2020': fuel burn should increase with increasing load",
                    "project-period 'gas_ct4-2020': fuel burn curve should be convex, i.e. the slope should increase with increasing load_point_fraction",
                ],
            },
        }

        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_piecewise_curves(
                df=test_cases[test_case]["df"],
                x_col=x_col,
                slope_col=slope_col,
                y_name=y_name,
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_startup_shutdown_rate_inputs(self):
        """
        Test input validation for startup and shutdown rates
        :return:
        """

        prj_df_columns = ["project", "operational_type", "min_stable_level_fraction"]
        su_df_columns = [
            "project",
            "down_time_cutoff_hours",
            "startup_plus_ramp_up_rate",
        ]
        test_cases = {
            # Make sure a case with only basic inputs doesn't throw errors
            1: {
                "prj_df": pd.DataFrame(
                    columns=prj_df_columns, data=[["ccgt", "gen_commit_bin", 0.6]]
                ),
                "su_df": pd.DataFrame(columns=su_df_columns),
                "result": [],
            },
            # Make sure correct inputs don't throw errors
            2: {
                "prj_df": pd.DataFrame(
                    columns=prj_df_columns
                    + [
                        "min_down_time_hours",
                        "shutdown_plus_ramp_down_rate",
                        "startup_fuel_mmbtu_per_mw",
                    ],
                    data=[["ccgt", "gen_commit_bin", 0.6, 8, 0.00334, 0]],
                ),
                "su_df": pd.DataFrame(
                    columns=su_df_columns,
                    data=[["ccgt", 8, 0.00334], ["ccgt", 12, 0.002]],
                ),
                "result": [],
            },
            # Make sure too short min down time is flagged
            3: {
                "prj_df": pd.DataFrame(
                    columns=prj_df_columns
                    + [
                        "min_down_time_hours",
                        "shutdown_plus_ramp_down_rate",
                        "startup_fuel_mmbtu_per_mw",
                    ],
                    data=[["ccgt", "gen_commit_bin", 0.6, 4, 0.00334, 0]],
                ),
                "su_df": pd.DataFrame(
                    columns=su_df_columns,
                    data=[["ccgt", 4, 0.00334], ["ccgt", 12, 0.002]],
                ),
                "result": [
                    "Project(s) 'ccgt': Startup ramp duration plus shutdown ramp duration "
                    "should be less than the minimum down time. Make sure the minimum "
                    "down time is long enough to fit the (coldest) "
                    "trajectories!"
                ],
            },
            # Make sure multiple projects get flagged correctly
            4: {
                "prj_df": pd.DataFrame(
                    columns=prj_df_columns
                    + [
                        "min_down_time_hours",
                        "shutdown_plus_ramp_down_rate",
                        "startup_fuel_mmbtu_per_mw",
                    ],
                    data=[
                        ["ccgt", "gen_commit_bin", 0.6, 4, 0.00334, 0],
                        ["ccgt2", "gen_commit_bin", 0.6, 4, 0.00334, 0],
                    ],
                ),
                "su_df": pd.DataFrame(
                    columns=su_df_columns,
                    data=[["ccgt", 4, 0.00334], ["ccgt2", 4, 0.00334]],
                ),
                "result": [
                    "Project(s) 'ccgt, ccgt2': Startup ramp duration plus shutdown ramp duration"
                    " should be less than the minimum down time. Make sure the minimum"
                    " down time is long enough to fit the (coldest) "
                    "trajectories!"
                ],
            },
            # Make sure a startup trajectory without min down time gets flagged
            5: {
                "prj_df": pd.DataFrame(
                    columns=prj_df_columns, data=[["ccgt", "gen_commit_bin", 0.6]]
                ),
                "su_df": pd.DataFrame(
                    columns=su_df_columns, data=[["ccgt", 8, 0.00334]]
                ),
                "result": [
                    "Project(s) 'ccgt': Startup ramp duration plus shutdown ramp duration"
                    " should be less than the minimum down time. Make sure the minimum"
                    " down time is long enough to fit the (coldest) trajectories!",
                    "Project(s) 'ccgt': down_time_cutoff_hours of hottest start should "
                    "match project's minimum_down_time_hours. If there is no minimum "
                    "down time, set cutoff to zero.",
                ],
            },
            # Make sure quick-start units don't get flagged even if no min down
            # time provided (defaults to zero)
            6: {
                "prj_df": pd.DataFrame(
                    columns=prj_df_columns, data=[["ccgt", "gen_commit_bin", 0.6]]
                ),
                "su_df": pd.DataFrame(columns=su_df_columns, data=[["ccgt", 0, 0.012]]),
                "result": [],
            },
            # Make sure startup fuel + trajectory combination is flagged
            7: {
                "prj_df": pd.DataFrame(
                    columns=prj_df_columns
                    + [
                        "min_down_time_hours",
                        "shutdown_plus_ramp_down_rate",
                        "startup_fuel_mmbtu_per_mw",
                    ],
                    data=[["ccgt", "gen_commit_bin", 0.6, 8, 0.00334, 1]],
                ),
                "su_df": pd.DataFrame(
                    columns=su_df_columns, data=[["ccgt", 8, 0.00334]]
                ),
                "result": [
                    "Project(s) 'ccgt': Cannot have both startup_fuel inputs and a startup "
                    "trajectory that takes multiple timepoints as this will double "
                    "count startup fuel consumption. Please adjust startup ramp rate or"
                    " startup fuel consumption inputs"
                ],
            },
            # Make sure ramp rates decrease with increasing down time cutoff
            8: {
                "prj_df": pd.DataFrame(
                    columns=prj_df_columns
                    + [
                        "min_down_time_hours",
                        "shutdown_plus_ramp_down_rate",
                        "startup_fuel_mmbtu_per_mw",
                    ],
                    data=[["ccgt", "gen_commit_bin", 0.6, 8, 0.00334, 0]],
                ),
                "su_df": pd.DataFrame(
                    columns=su_df_columns,
                    data=[["ccgt", 8, 0.00334], ["ccgt", 12, 0.005]],
                ),
                "result": [
                    "Project(s) 'ccgt': Startup ramp rate should decrease with "
                    "increasing down time cutoff (colder starts are slower)."
                ],
            },
            # TODO: there are more situations to test (see aux #4 and #5)
        }

        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_startup_shutdown_rate_inputs(
                prj_df=test_cases[test_case]["prj_df"],
                su_df=test_cases[test_case]["su_df"],
                hrs_in_tmp=1,
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_cols_equal(self):
        """
        :return:
        """

        cols = ["stage_id", "period", "n_hours", "hours_in_period_timepoints"]
        col1 = "n_hours"
        col2 = "hours_in_period_timepoints"
        idx_col = ["stage_id", "period"]

        test_cases = {
            # Make sure a case with only basic inputs doesn't throw errors
            1: {
                "df": pd.DataFrame(
                    columns=cols, data=[[1, 2020, 8760, 8760], [1, 2030, 8760, 8760]]
                ),
                "result": [],
            },
            # Make sure invalids are properly captured. Note that .values
            # somehow adds whitespace in front of the number
            2: {
                "df": pd.DataFrame(
                    columns=cols, data=[[1, 2020, 8761, 8760], [1, 2030, 8760, 8760]]
                ),
                "result": [
                    "['stage_id', 'period'](s) [[   1 2020]]: values in "
                    "column n_hours and hours_in_period_timepoints should be equal. "
                ],
            },
        }

        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_cols_equal(
                df=test_cases[test_case]["df"], col1=col1, col2=col2, idx_col=idx_col
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_missing_inputs(self):
        """
        :return:
        """

        cols = ["project", "capacity_type", "operational_type"]

        test_cases = {
            # Make sure a case with only basic inputs doesn't throw errors
            1: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[["gas_ct", "cap1", "op1"], ["gas_ct2", "cap2", "op1"]],
                ),
                "idx_col": "project",
                "result_cap_col": [],
                "result_both_cols": [],
            },
            # Make sure missing inputs are detected
            2: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[["gas_ct", "cap1", "op1"], ["gas_ct2", None, None]],
                ),
                "idx_col": "project",
                "result_cap_col": [
                    "Missing capacity_type inputs for project(s): ['gas_ct2']. "
                ],
                "result_both_cols": [
                    "Missing capacity_type inputs for project(s): ['gas_ct2']. ",
                    "Missing operational_type inputs for project(s): ['gas_ct2']. ",
                ],
            },
            # Make sure idx_col with list of cols works
            3: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[["gas_ct", "cap1", "op1"], ["gas_ct2", "cap1", None]],
                ),
                "idx_col": ["project", "capacity_type"],
                "result_cap_col": [],
                "result_both_cols": [
                    "Missing operational_type inputs for ['project', 'capacity_type'](s): [['gas_ct2' 'cap1']]. "
                ],
            },
        }

        for test_case in test_cases.keys():
            # single column
            expected_list = test_cases[test_case]["result_cap_col"]
            actual_list = module_to_test.validate_missing_inputs(
                df=test_cases[test_case]["df"],
                idx_col=test_cases[test_case]["idx_col"],
                col="capacity_type",
            )
            self.assertListEqual(expected_list, actual_list)

            # multiple columns
            expected_list = test_cases[test_case]["result_both_cols"]
            actual_list = module_to_test.validate_missing_inputs(
                df=test_cases[test_case]["df"],
                idx_col=test_cases[test_case]["idx_col"],
                col=["capacity_type", "operational_type"],
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_row_monotonicity(self):
        """
        :return:
        """

        cols = ["project", "period", "max_mw", "max_mwh"]
        test_cases = {
            # Make sure a case with only basic inputs doesn't throw errors
            1: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 20],
                        ["gas_ct", 2030, 10, 20],
                        ["coal", 2030, 20, 20],
                    ],
                ),
                "col": ["max_mw"],
                "increasing": True,
                "result": [],
            },
            # Make sure a case with only basic inputs doesn't throw errors
            # - checking multiple columns
            2: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 20],
                        ["gas_ct", 2030, 10, 20],
                        ["coal", 2030, 20, 20],
                    ],
                ),
                "col": ["max_mw", "max_mwh"],
                "increasing": True,
                "result": [],
            },
            # Decreasing values are flagged
            3: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 20],
                        ["gas_ct", 2030, 5, 20],
                        ["coal", 2030, 20, 20],
                    ],
                ),
                "col": ["max_mw"],
                "increasing": True,
                "result": [
                    "project(s) 'gas_ct': max_mw should monotonically "
                    "increase with period. "
                ],
            },
            # Decreasing values are flagged - multiple columns
            4: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 20],
                        ["gas_ct", 2030, 5, 15],
                        ["coal", 2030, 20, 20],
                    ],
                ),
                "col": ["max_mw", "max_mwh"],
                "increasing": True,
                "result": [
                    "project(s) 'gas_ct': max_mw should monotonically "
                    "increase with period. ",
                    "project(s) 'gas_ct': max_mwh should monotonically "
                    "increase with period. ",
                ],
            },
            # None values are ignored
            5: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 20],
                        ["gas_ct", 2030, 5, None],
                        ["coal", 2030, 20, 20],
                    ],
                ),
                "col": ["max_mw", "max_mwh"],
                "increasing": True,
                "result": [
                    "project(s) 'gas_ct': max_mw should monotonically "
                    "increase with period. "
                ],
            },
            # Increasing values are flagged w increasing=False
            6: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 5, 20],
                        ["gas_ct", 2030, 10, 20],
                        ["coal", 2030, 20, 20],
                    ],
                ),
                "col": ["max_mw"],
                "increasing": False,
                "result": [
                    "project(s) 'gas_ct': max_mw should monotonically "
                    "decrease with period. "
                ],
            },
        }
        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_row_monotonicity(
                df=test_cases[test_case]["df"],
                col=test_cases[test_case]["col"],
                rank_col="period",
                increasing=test_cases[test_case]["increasing"],
            )
            self.assertListEqual(expected_list, actual_list)

    def test_validate_column_monotonicity(self):
        """
        :return:
        """

        cols = ["project", "period", "min_mw", "avg_mw", "max_mw"]
        test_cases = {
            # Make sure a case with only basic inputs doesn't throw errors
            1: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 15, 20],
                        ["gas_ct", 2030, 10, 15, 20],
                        ["coal", 2030, 20, 20, 20],
                    ],
                ),
                "cols": ["min_mw", "avg_mw", "max_mw"],
                "idx_col": "project",
                "result": [],
            },
            # Make sure erroneous inputs are properly caught
            2: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 15, 20],
                        ["gas_ct", 2030, 21, 15, 20],
                        ["coal", 2030, 20, 20, 20],
                    ],
                ),
                "cols": ["min_mw", "avg_mw", "max_mw"],
                "idx_col": "project",
                "result": [
                    "project(s) ['gas_ct']: Values cannot decrease "
                    "between ['min_mw', 'avg_mw', 'max_mw']. "
                ],
            },
            # None values are ignored
            3: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 15, 20],
                        ["gas_ct", 2030, None, 15, 20],
                        ["coal", 2030, 20, 20, 20],
                    ],
                ),
                "cols": ["min_mw", "max_mw"],
                "idx_col": "project",
                "result": [],
            },
            # idx_col can be list of strings
            4: {
                "df": pd.DataFrame(
                    columns=cols,
                    data=[
                        ["gas_ct", 2020, 10, 15, 20],
                        ["gas_ct", 2030, 21, 15, 20],
                        ["coal", 2030, 20, 20, 20],
                    ],
                ),
                "cols": ["min_mw", "avg_mw", "max_mw"],
                "idx_col": ["project", "period"],
                "result": [
                    "['project', 'period'](s) [['gas_ct' 2030]]: "
                    "Values cannot decrease between "
                    "['min_mw', 'avg_mw', 'max_mw']. "
                ],
            },
        }
        for test_case in test_cases.keys():
            expected_list = test_cases[test_case]["result"]
            actual_list = module_to_test.validate_column_monotonicity(
                df=test_cases[test_case]["df"],
                cols=test_cases[test_case]["cols"],
                idx_col=test_cases[test_case]["idx_col"],
            )
            self.assertListEqual(expected_list, actual_list)


if __name__ == "__main__":
    unittest.main()
