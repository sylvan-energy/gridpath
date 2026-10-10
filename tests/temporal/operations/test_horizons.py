# Copyright 2016-2025 Blue Marble Analytics LLC.
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
import shutil
import sqlite3
import sys
import tempfile
import unittest
import warnings

from db.utilities.custom_functions import temporal
from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")
DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "db", "db_schema.sql"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
]
NAME_OF_MODULE_BEING_TESTED = "temporal.operations.horizons"
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


class TestHorizons(unittest.TestCase):
    """ """

    def test_add_model_components(self):
        """
        Test that there are no errors when adding model components
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

    def test_initialized_components(self):
        """
        Create components; check they are initialized with data as expected
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

        # TODO: add test data with more horizon types

        # Load test data
        balancing_type_horizon_horizons_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "horizons_user_defined.tab"),
            sep="\t",
        )

        timepoints_on_balancing_type_horizon_df = pd.read_csv(
            os.path.join(
                TEST_DATA_DIRECTORY, "inputs", "horizon_user_defined_timepoints.tab"
            ),
            sep="\t",
        )

        # Check data are as expected
        # BLN_TYPE_HRZS set
        horizon_balancing_types_builtin = (
            [("subproblem_circular", 1)]
            + [("subproblem_period_circular", period) for period in [2020, 2030]]
            + [("subproblem_linear", 1)]
            + [("subproblem_period_linear", period) for period in [2020, 2030]]
            + [("subproblem_linked", 1)]
            + [("subproblem_period_linked", period) for period in [2020, 2030]]
            + [
                ("subproblem_period_month_circular", period * 100 + month)
                for (period, month) in [(2020, 5), (2020, 9), (2030, 4), (2030, 7)]
            ]
            + [
                ("subproblem_period_month_linear", period * 100 + month)
                for (period, month) in [(2020, 5), (2020, 9), (2030, 4), (2030, 7)]
            ]
        )
        expected_horizons = sorted(
            [
                (b, h)
                for (b, h) in zip(
                    balancing_type_horizon_horizons_df.balancing_type_horizon,
                    balancing_type_horizon_horizons_df.horizon,
                )
            ]
            + horizon_balancing_types_builtin
        )

        actual_horizons = sorted([(b, h) for (b, h) in instance.BLN_TYPE_HRZS])

        self.assertListEqual(
            expected_horizons,
            actual_horizons,
            msg="HORIZONS set data does not load correctly.",
        )

        # Params: boundary
        user_defined_boundary_param = (
            balancing_type_horizon_horizons_df.set_index(
                ["balancing_type_horizon", "horizon"]
            ).to_dict()
        )["boundary"]

        builtin_boundary_param = {
            (b, h): b.split("_")[-1] for (b, h) in horizon_balancing_types_builtin
        }

        actual_boundary_param = {
            (b, h): instance.boundary[b, h] for (b, h) in instance.BLN_TYPE_HRZS
        }

        expected_boundary_param = user_defined_boundary_param | builtin_boundary_param

        self.assertDictEqual(
            expected_boundary_param,
            actual_boundary_param,
            msg="Data for param 'boundary' not loaded " "correctly",
        )

        # BLN_TYPES set
        expected_balancing_type_horizons = list(
            balancing_type_horizon_horizons_df.balancing_type_horizon.unique()
        ) + list(set([b for (b, h) in horizon_balancing_types_builtin]))
        expected_balancing_type_horizons = sorted(expected_balancing_type_horizons)
        actual_balancing_type_horizons = sorted(list(instance.BLN_TYPES))

        self.assertListEqual(
            expected_balancing_type_horizons, actual_balancing_type_horizons
        )

        # HRZS_BY_BLN_TYPE set
        horizon_balancing_types_builtin_by_bt = {}
        timepoints_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "timepoints.tab"),
            sep="\t",
            usecols=["timepoint", "period", "month"],
        )

        def get_hrz_by_bt_for_builtin():
            builtin_hrzs_by_bt = {}
            for b, h in horizon_balancing_types_builtin:
                if b in [
                    "subproblem_circular",
                    "subproblem_linear",
                    "subproblem_linked",
                ]:
                    builtin_hrzs_by_bt[b] = [1]
                elif b in [
                    "subproblem_period_circular",
                    "subproblem_period_linear",
                    "subproblem_period_linked",
                ]:
                    builtin_hrzs_by_bt[b] = [2020, 2030]
                elif b in [
                    "subproblem_period_month_circular",
                    "subproblem_period_month_linear",
                ]:
                    builtin_hrzs_by_bt[b] = [202005, 202009, 203004, 203007]

            return builtin_hrzs_by_bt

        horizon_balancing_types_builtin_by_bt = get_hrz_by_bt_for_builtin()
        expected_horizon_by_balancing_type_horizon = {
            balancing_type_horizon: sorted(horizons["horizon"].tolist())
            for balancing_type_horizon, horizons in balancing_type_horizon_horizons_df.groupby(
                "balancing_type_horizon"
            )
        } | horizon_balancing_types_builtin_by_bt
        expected_horizon_by_balancing_type_horizon = dict(
            sorted(expected_horizon_by_balancing_type_horizon.items())
        )
        actual_horizon_by_balancing_type_horizon = dict(
            sorted(
                {
                    balancing_type_horizon: [
                        horizon
                        for horizon in sorted(
                            list(instance.HRZS_BY_BLN_TYPE[balancing_type_horizon])
                        )
                    ]
                    for balancing_type_horizon in instance.HRZS_BY_BLN_TYPE.keys()
                }.items()
            )
        )

        self.assertDictEqual(
            expected_horizon_by_balancing_type_horizon,
            actual_horizon_by_balancing_type_horizon,
        )

        # Set TMPS_BY_BLN_TYPE_HRZ
        expected_tmps_on_horizon_user_defined = {
            (balancing_type, horizon): sorted(timepoints["timepoint"].tolist())
            for (
                (balancing_type, horizon),
                timepoints,
            ) in timepoints_on_balancing_type_horizon_df.groupby(
                ["balancing_type_horizon", "horizon"]
            )
        }

        def get_tmps_for_builtin():
            builtin_tmps_by_bt = {}
            for b, h in horizon_balancing_types_builtin:
                if b in [
                    "subproblem_circular",
                    "subproblem_linear",
                    "subproblem_linked",
                ]:
                    builtin_tmps_by_bt[b, 1] = timepoints_df["timepoint"].tolist()
                elif b in [
                    "subproblem_period_circular",
                    "subproblem_period_linear",
                    "subproblem_period_linked",
                ]:
                    if (b, h) not in builtin_tmps_by_bt.keys():
                        builtin_tmps_by_bt[b, h] = timepoints_df.loc[
                            timepoints_df["period"] == h, "timepoint"
                        ].tolist()
                elif b in [
                    "subproblem_period_month_circular",
                    "subproblem_period_month_linear",
                ]:
                    if (b, h) not in builtin_tmps_by_bt.keys():
                        period = h // 100  # floor division
                        month = h % 100  # modulo division
                        builtin_tmps_by_bt[b, h] = timepoints_df.loc[
                            (timepoints_df["period"] == period)
                            & (timepoints_df["month"] == month),
                            "timepoint",
                        ].tolist()

            return builtin_tmps_by_bt

        expected_tmps_on_horizon_builtin = get_tmps_for_builtin()

        expected_tmps_on_horizon = (
            expected_tmps_on_horizon_user_defined | expected_tmps_on_horizon_builtin
        )

        actual_tmps_on_horizon = {
            (b, h): sorted([tmp for tmp in instance.TMPS_BY_BLN_TYPE_HRZ[b, h]])
            for (b, h) in list(instance.TMPS_BY_BLN_TYPE_HRZ.keys())
        }

        self.assertDictEqual(
            expected_tmps_on_horizon,
            actual_tmps_on_horizon,
            msg="TMPS_BY_BLN_TYPE_HRZ data do not match expected.",
        )

        # TMPS_BLN_TYPES
        expected_tmps_bln_types_user_defined = sorted(
            timepoints_on_balancing_type_horizon_df[
                ["timepoint", "balancing_type_horizon"]
            ]
            .drop_duplicates()
            .to_records(index=False)
            .tolist()
        )
        expected_tmps_bln_types_builtin = sorted(
            list(
                set(
                    [
                        (tmp, bt)
                        for (bt, h) in horizon_balancing_types_builtin
                        for tmp in expected_tmps_on_horizon_builtin[bt, h]
                    ]
                ),
            )
        )

        expected_tmps_bln_types = sorted(
            expected_tmps_bln_types_user_defined + expected_tmps_bln_types_builtin
        )
        actual_tmps_bln_types = sorted(
            (tmp, bt) for (tmp, bt) in instance.TMPS_BLN_TYPES
        )
        self.assertListEqual(expected_tmps_bln_types, actual_tmps_bln_types)

        # Param: horizon
        def expected_horizon_by_tmp_init():
            expected_horizon_by_tmp = {}
            for tmp in timepoints_df["timepoint"].tolist():
                for bt in expected_balancing_type_horizons:
                    for h in expected_horizon_by_balancing_type_horizon[bt]:
                        if tmp in expected_tmps_on_horizon[bt, h]:
                            expected_horizon_by_tmp[tmp, bt] = h

            return expected_horizon_by_tmp

        expected_horizon_by_tmp_type = expected_horizon_by_tmp_init()

        actual_horizon_by_tmp_type = {
            (tmp, _type): instance.horizon[tmp, _type]
            for tmp in instance.TMPS
            for _type in instance.BLN_TYPES
        }

        self.assertDictEqual(expected_horizon_by_tmp_type, actual_horizon_by_tmp_type)

        # Param: first_hrz_tmp
        expected_first_hrz_tmp = {
            (b, h): expected_tmps_on_horizon[b, h][0] for (b, h) in expected_horizons
        }
        actual_first_hrz_tmp = {
            (b, h): instance.first_hrz_tmp[b, h] for (b, h) in instance.BLN_TYPE_HRZS
        }
        self.assertDictEqual(
            expected_first_hrz_tmp,
            actual_first_hrz_tmp,
            msg="Data for param first_hrz_tmp do not match expected.",
        )

        # Param: last_hrz_tmp
        expected_last_hrz_tmp = {
            (b, h): expected_tmps_on_horizon[b, h][-1] for (b, h) in expected_horizons
        }
        actual_last_hrz_tmp = {
            (b, h): instance.last_hrz_tmp[b, h] for (b, h) in instance.BLN_TYPE_HRZS
        }
        self.assertDictEqual(
            expected_last_hrz_tmp,
            actual_last_hrz_tmp,
            msg="Data for param " "last_hrz_tmp do " "not match expected.",
        )

        # Param: prev_tmp
        # Testing for both horizons that are 'circular' and 'linear'
        # TODO: should we have the actual previous timepoints in a data file
        #  somewhere as opposed to figuring it out here
        expected_prev_tmp = dict()
        prev_tmp = None

        h_bt_tmp_tuples_list = [
            (h, bt, tmp)
            for (bt, h) in expected_tmps_on_horizon.keys()
            for tmp in expected_tmps_on_horizon[bt, h]
        ]
        for horizon, balancing_type, tmp in h_bt_tmp_tuples_list:
            if tmp == expected_first_hrz_tmp[balancing_type, horizon]:
                if expected_boundary_param[balancing_type, horizon] == "circular":
                    expected_prev_tmp[tmp, balancing_type] = expected_last_hrz_tmp[
                        balancing_type, horizon
                    ]
                elif expected_boundary_param[balancing_type, horizon] in [
                    "linear",
                    "linked",
                ]:
                    expected_prev_tmp[tmp, balancing_type] = "."
                else:
                    raise (
                        ValueError,
                        "Test data specifies horizon boundary different "
                        "from allowed values of 'circular' and 'linear'",
                    )
            else:
                expected_prev_tmp[tmp, balancing_type] = prev_tmp
            prev_tmp = tmp

        actual_prev_tmp = {
            (tmp, bt): instance.prev_tmp[tmp, bt]
            for (tmp, bt) in instance.TMPS_BLN_TYPES
        }

        expected_prev_tmp_ordered = OrderedDict(sorted(expected_prev_tmp.items()))
        actual_prev_tmp_ordered = OrderedDict(sorted(actual_prev_tmp.items()))

        self.assertDictEqual(
            expected_prev_tmp_ordered,
            actual_prev_tmp_ordered,
            msg="Data for param prev_tmp do " "not match expected.",
        )

        # Param: next_tmp
        # Testing for both horizons that 'circular' and 'linear'
        expected_next_tmp = dict()
        prev_tmp = None
        for horizon, balancing_type, tmp in h_bt_tmp_tuples_list:
            if prev_tmp is None:
                if expected_boundary_param[balancing_type, horizon] == "circular":
                    expected_next_tmp[
                        expected_last_hrz_tmp[balancing_type, horizon], balancing_type
                    ] = expected_first_hrz_tmp[balancing_type, horizon]
                elif expected_boundary_param[balancing_type, horizon] in [
                    "linear",
                    "linked",
                ]:
                    expected_next_tmp[
                        expected_last_hrz_tmp[balancing_type, horizon], balancing_type
                    ] = "."
                else:
                    raise (
                        ValueError,
                        "Test data specifies horizon boundary different "
                        "from allowed values of 'circular' and 'linear'",
                    )
            else:
                expected_next_tmp[prev_tmp, balancing_type] = tmp
            # If we have reached the last horizon timepoint, set the
            # previous timepoint to None (to enter the boundary logic above)
            if tmp == expected_last_hrz_tmp[balancing_type, horizon]:
                prev_tmp = None
            else:
                prev_tmp = tmp

        expected_next_tmp_ordered = OrderedDict(sorted(expected_next_tmp.items()))

        actual_next_tmp = {
            (tmp, bt): instance.next_tmp[tmp, bt]
            for (tmp, bt) in instance.TMPS_BLN_TYPES
        }
        actual_next_tmp_ordered = OrderedDict(sorted(actual_next_tmp.items()))

        self.assertDictEqual(
            expected_next_tmp_ordered,
            actual_next_tmp_ordered,
            msg="Data for param next_tmp do not match " "expected.",
        )

    def _create_instance_and_record_span_warnings(self, test_data_dir):
        """
        Create an instance from the given test data directory and return it
        along with any warnings about horizons spanning periods
        """
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
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            instance = m.create_instance(data)
        span_warnings = [
            w for w in caught if "Horizon found that spans periods" in str(w.message)
        ]
        return instance, span_warnings

    def test_hrz_period(self):
        """
        Horizons get the period of their first timepoint; the built-in
        subproblem horizons span both test periods without warning
        """
        instance, span_warnings = self._create_instance_and_record_span_warnings(
            TEST_DATA_DIRECTORY
        )

        self.assertEqual(span_warnings, [])
        self.assertEqual(instance.hrz_period["day", 202001], 2020)
        self.assertEqual(instance.hrz_period["subproblem_circular", 1], 2020)
        self.assertEqual(instance.hrz_period["subproblem_period_circular", 2030], 2030)

    def test_hrz_period_warns_on_user_defined_horizon_spanning_periods(self):
        """
        A user-defined horizon whose timepoints belong to more than one period
        triggers a warning and is assigned the period of its first timepoint
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_data_dir = os.path.join(tmp_dir, "test_data")
            shutil.copytree(
                os.path.join(TEST_DATA_DIRECTORY, "inputs"),
                os.path.join(test_data_dir, "inputs"),
            )
            tmps_file = os.path.join(test_data_dir, "inputs", "timepoints.tab")
            tmps_df = pd.read_csv(tmps_file, sep="\t", dtype=str, keep_default_na=False)
            # Move the last timepoint of day horizon 202001 into period 2030
            tmps_df.loc[tmps_df["timepoint"] == "20200124", "period"] = "2030"
            tmps_df.to_csv(tmps_file, sep="\t", index=False)

            instance, span_warnings = self._create_instance_and_record_span_warnings(
                test_data_dir
            )

        # The moved timepoint belongs to both the day and the year horizon
        warned_horizons = sorted(
            hrz
            for hrz in ["day, horizon 202001", "year, horizon 2020"]
            for w in span_warnings
            if hrz in str(w.message)
        )
        self.assertEqual(len(span_warnings), 2)
        self.assertEqual(warned_horizons, ["day, horizon 202001", "year, horizon 2020"])
        self.assertEqual(instance.hrz_period["day", 202001], 2020)
        self.assertEqual(instance.hrz_period["year", 2020], 2020)

    def test_db_builtin_horizons_match_model(self):
        """
        The built-in horizons the database temporal loader writes match the
        model's built-in horizons, boundaries, and timepoints for every
        built-in balancing type, so horizon-indexed inputs on built-in
        horizons reach the model; one month's timepoints are not contiguous,
        days of month cycle so that days' timepoints are not contiguous
        either, and one timepoint has no day of month (so is in no day
        horizon)
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_data_dir = os.path.join(tmp_dir, "test_data")
            shutil.copytree(
                os.path.join(TEST_DATA_DIRECTORY, "inputs"),
                os.path.join(test_data_dir, "inputs"),
            )
            tmps_file = os.path.join(test_data_dir, "inputs", "timepoints.tab")
            tmps_df = pd.read_csv(tmps_file, sep="\t", dtype=str, keep_default_na=False)
            # Put a timepoint in the middle of May 2020 in September 2020
            tmps_df.loc[tmps_df["timepoint"] == "20200112", "month"] = "9"
            tmps_df["day_of_month"] = [str(i % 3 + 1) for i in range(len(tmps_df))]
            tmps_df.loc[tmps_df["timepoint"] == "20200105", "day_of_month"] = "."
            tmps_df.to_csv(tmps_file, sep="\t", index=False)

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

        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with open(DB_SCHEMA_FILE) as f:
            conn.executescript(f.read())
        conn.executemany(
            """INSERT INTO inputs_temporal (temporal_scenario_id, subproblem_id,
            stage_id, timepoint, period, number_of_hours_in_timepoint,
            timepoint_weight, spinup_or_lookahead, month, day_of_month)
            VALUES (1, 1, 1, ?, ?, ?, ?, 0, ?, ?)""",
            tmps_df[
                [
                    "timepoint",
                    "period",
                    "number_of_hours_in_timepoint",
                    "timepoint_weight",
                    "month",
                    "day_of_month",
                ]
            ]
            .replace(".", None)
            .astype(float)
            .values.tolist(),
        )
        temporal(conn=conn, subscenario_id=1)

        db_boundaries = {
            (bt, hrz): boundary
            for bt, hrz, boundary in conn.execute(
                """SELECT balancing_type_horizon, horizon, boundary
                FROM inputs_temporal_horizons"""
            )
        }
        db_tmps = {}
        for bt, hrz, tmp in conn.execute(
            """SELECT balancing_type_horizon, horizon, timepoint
            FROM inputs_temporal_horizon_timepoints"""
        ):
            db_tmps.setdefault((bt, hrz), set()).add(tmp)

        model_tmps = {
            (bt, hrz): set(instance.TMPS_BY_BLN_TYPE_HRZ_BUILTIN[bt, hrz])
            for bt, hrz in instance.BLN_TYPE_HRZS_BUILTIN
        }
        model_boundaries = {
            (bt, hrz): instance.boundary_builtin[bt, hrz]
            for bt, hrz in instance.BLN_TYPE_HRZS_BUILTIN
        }

        self.assertEqual(
            sorted({bt for bt, _ in model_tmps}),
            sorted(MODULE_BEING_TESTED.BUILTIN_HORIZON_TYPES),
        )
        self.assertIn(("subproblem_period_month_linear", 202009), model_tmps)
        self.assertIn(20200112, model_tmps["subproblem_period_month_linear", 202009])
        self.assertIn(("subproblem_period_day_circular", 20200502), model_tmps)
        self.assertNotIn(
            20200105,
            set().union(
                *(
                    tmps
                    for (bt, _), tmps in model_tmps.items()
                    if bt.startswith("subproblem_period_day")
                )
            ),
        )
        self.assertEqual(db_tmps, model_tmps)
        self.assertEqual(db_boundaries, model_boundaries)


if __name__ == "__main__":
    unittest.main()
