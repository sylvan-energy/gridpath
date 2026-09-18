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
PREREQUISITE_MODULE_NAMES = ["temporal.operations.timepoints"]
NAME_OF_MODULE_BEING_TESTED = "temporal.investment.periods"
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


class TestPeriods(unittest.TestCase):
    """
    Unit tests for gridpath.temporal.investment.periods
    """

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

        # Load test data
        periods_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "periods.tab"), sep="\t"
        )
        timepoints_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "timepoints.tab"),
            sep="\t",
            usecols=[
                "timepoint",
                "period",
                "number_of_hours_in_timepoint",
                "timepoint_weight",
            ],
        )

        # PERIODS set
        expected_periods = periods_df["period"].tolist()
        actual_periods = [p for p in instance.PERIODS]
        self.assertListEqual(
            expected_periods,
            actual_periods,
            msg="PERIODS set data does not load correctly.",
        )
        # TODO: set index and convert to dict once
        # Param: discount_factor
        expected_discount_factor_param = periods_df.set_index("period").to_dict()[
            "discount_factor"
        ]
        actual_discount_factor_param = {
            p: instance.discount_factor[p] for p in instance.PERIODS
        }
        self.assertDictEqual(
            expected_discount_factor_param,
            actual_discount_factor_param,
            msg="Data for param 'discount_factor' param " "not loaded correctly",
        )
        # Param: period_start_year
        expected_period_start_year_param = periods_df.set_index("period").to_dict()[
            "period_start_year"
        ]
        actual_period_start_year_param = {
            p: instance.period_start_year[p] for p in instance.PERIODS
        }
        self.assertDictEqual(
            expected_period_start_year_param,
            actual_period_start_year_param,
            msg="Data for param 'period_start_year' " "param not loaded correctly",
        )

        # Param: period_end_year
        expected_period_end_year_param = periods_df.set_index("period").to_dict()[
            "period_end_year"
        ]
        actual_period_end_year_param = {
            p: instance.period_end_year[p] for p in instance.PERIODS
        }
        self.assertDictEqual(
            expected_period_end_year_param,
            actual_period_end_year_param,
            msg="Data for param 'period_end_year' " "param not loaded correctly",
        )

        # Param: hours_in_period_timepoints
        expected_hours_in_period_timepoints = periods_df.set_index("period").to_dict()[
            "hours_in_period_timepoints"
        ]
        actual_hours_in_period_timepoints = {
            p: instance.hours_in_period_timepoints[p] for p in instance.PERIODS
        }
        self.assertDictEqual(
            expected_hours_in_period_timepoints,
            actual_hours_in_period_timepoints,
            msg="Data for param 'hours_in_period_timepoints' "
            "param not loaded correctly",
        )

        # Params: period
        expected_period_param = timepoints_df.set_index("timepoint").to_dict()["period"]
        actual_period_param = {tmp: instance.period[tmp] for tmp in instance.TMPS}

        self.assertDictEqual(
            expected_period_param,
            actual_period_param,
            msg="Data for param 'period' not loaded correctly",
        )

        # Set TMPS_IN_PRD
        expected_tmp_in_p = dict()
        for tmp in timepoints_df["timepoint"].tolist():
            if expected_period_param[tmp] not in expected_tmp_in_p.keys():
                expected_tmp_in_p[expected_period_param[tmp]] = [tmp]
            else:
                expected_tmp_in_p[expected_period_param[tmp]].append(tmp)

        actual_tmps_in_p = {
            p: sorted([tmp for tmp in instance.TMPS_IN_PRD[p]])
            for p in list(instance.TMPS_IN_PRD.keys())
        }
        self.assertDictEqual(
            expected_tmp_in_p,
            actual_tmps_in_p,
            msg="TMPS_IN_PRD data do not match " "expected.",
        )

        # Param: number_years_represented
        expected_num_years_param = {}
        for p in expected_periods:
            expected_num_years_param[p] = (
                expected_period_end_year_param[p] - expected_period_start_year_param[p]
            )
        actual_num_years_param = {
            p: instance.number_years_represented[p] for p in instance.PERIODS
        }
        self.assertDictEqual(
            expected_num_years_param,
            actual_num_years_param,
            msg="Data for param 'number_years_represented' "
            "param not loaded correctly",
        )

        # Param: first_period
        expected_first_period = expected_periods[0]
        actual_first_period = instance.first_period
        self.assertEqual(expected_first_period, actual_first_period)

        # Set: NOT_FIRST_PRDS
        expected_not_first_periods = expected_periods[1:]
        actual_not_first_periods = [p for p in instance.NOT_FIRST_PRDS]
        self.assertListEqual(expected_not_first_periods, actual_not_first_periods)

        # Param: prev_period
        expected_prev_periods = {
            p: expected_periods[expected_periods.index(p) - 1]
            for p in expected_not_first_periods
        }
        actual_prev_periods = {
            p: instance.prev_period[p] for p in instance.NOT_FIRST_PRDS
        }
        self.assertDictEqual(expected_prev_periods, actual_prev_periods)

        # Param: hours_in_subproblem_period
        timepoints_df["tot_hours"] = (
            timepoints_df["number_of_hours_in_timepoint"]
            * timepoints_df["timepoint_weight"]
        )
        expected_hours_in_subproblem_period = (
            timepoints_df.groupby(["period"])["tot_hours"].sum().to_dict()
        )

        actual_hours_in_subproblem_period = {
            p: instance.hours_in_subproblem_period[p] for p in instance.PERIODS
        }
        self.assertDictEqual(
            expected_hours_in_subproblem_period,
            actual_hours_in_subproblem_period,
            msg="Data for param 'hours_in_subproblem_period' "
            "param not loaded correctly",
        )

    def test_period_tree_sets(self):
        """
        Build the periods module on a three-level period tree and check the
        trajectory sets. Tree: 2020 -> {2030, 20302}; 2030 -> {20401, 20402};
        20302 -> {20403}. The timepoints.tab of the test data (periods 2020
        and 2030 only) is reused as is.
        """
        tree_periods_tab = (
            "period\tdiscount_factor\thours_in_period_timepoints\t"
            "period_start_year\tperiod_end_year\tprev_period\tprobability\n"
            "2020\t1\t8760\t2020\t2030\t.\t.\n"
            "2030\t0.8\t8760\t2030\t2040\t2020\t0.6\n"
            "20302\t0.8\t8760\t2030\t2040\t2020\t0.4\n"
            "20401\t0.5\t8760\t2040\t2050\t2030\t0.2\n"
            "20402\t0.5\t8760\t2040\t2050\t2030\t0.4\n"
            "20403\t0.5\t8760\t2040\t2050\t20302\t0.4\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            shutil.copytree(
                os.path.join(TEST_DATA_DIRECTORY, "inputs"),
                os.path.join(tmp_dir, "inputs"),
            )
            with open(os.path.join(tmp_dir, "inputs", "periods.tab"), "w") as f:
                f.write(tree_periods_tab)

            m, data = add_components_and_load_data(
                prereq_modules=IMPORTED_PREREQ_MODULES,
                module_to_test=MODULE_BEING_TESTED,
                test_data_dir=tmp_dir,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
            )
            instance = m.create_instance(data)

        expected_prev_period = {
            2030: 2020,
            20302: 2020,
            20401: 2030,
            20402: 2030,
            20403: 20302,
        }
        actual_prev_period = {
            p: instance.prev_period[p] for p in instance.NOT_FIRST_PRDS
        }
        self.assertDictEqual(expected_prev_period, actual_prev_period)

        # Each period with its ancestors, nearest first
        expected_prev_periods_on_trajectory = {
            2020: [2020],
            2030: [2030, 2020],
            20302: [20302, 2020],
            20401: [20401, 2030, 2020],
            20402: [20402, 2030, 2020],
            20403: [20403, 20302, 2020],
        }
        actual_prev_periods_on_trajectory = {
            p: list(instance.FUTURE_TRAJECTORY_PREV_PERIODS_BY_PERIOD[p])
            for p in instance.PERIODS
        }
        self.assertDictEqual(
            expected_prev_periods_on_trajectory, actual_prev_periods_on_trajectory
        )

        # Each period and its descendants, sorted: the periods in which
        # capacity of that vintage can be operational
        expected_future_trajectory = {
            2020: [2020, 2030, 20302, 20401, 20402, 20403],
            2030: [2030, 20401, 20402],
            20302: [20302, 20403],
            20401: [20401],
            20402: [20402],
            20403: [20403],
        }
        actual_future_trajectory = {
            p: list(instance.PERIOD_FUTURE_TRAJECTORY[p]) for p in instance.PERIODS
        }
        self.assertDictEqual(expected_future_trajectory, actual_future_trajectory)

        # Params: probability (default 1 for the root) and the weight used in
        # the objective function, discount_factor * probability
        expected_probability = {
            2020: 1,
            2030: 0.6,
            20302: 0.4,
            20401: 0.2,
            20402: 0.4,
            20403: 0.4,
        }
        expected_weight = {
            2020: 1.0,
            2030: 0.48,
            20302: 0.32,
            20401: 0.1,
            20402: 0.2,
            20403: 0.2,
        }
        for period in instance.PERIODS:
            self.assertAlmostEqual(
                expected_probability[period], instance.probability[period]
            )
            self.assertAlmostEqual(
                expected_weight[period],
                instance.probability_weighted_discount_factor[period],
            )

    def test_validate_period_tree(self):
        """
        Check the prev_period validation on valid and invalid period trees
        """
        validate = MODULE_BEING_TESTED.validate_period_tree

        def make_df(rows):
            return pd.DataFrame(
                rows,
                columns=[
                    "period",
                    "period_start_year",
                    "period_end_year",
                    "prev_period",
                ],
            )

        # Deterministic problem: nothing specified, nothing to check
        self.assertListEqual(
            [], validate(make_df([(2020, 2020, 2030, None), (2030, 2030, 2040, None)]))
        )
        # Valid two-branch tree
        self.assertListEqual(
            [],
            validate(
                make_df(
                    [
                        (2020, 2020, 2030, None),
                        (20301, 2030, 2040, 2020),
                        (20302, 2030, 2040, 2020),
                    ]
                )
            ),
        )
        # Partially specified: the second branch would silently default to
        # the first branch as its previous period
        errors = validate(
            make_df(
                [
                    (2020, 2020, 2030, None),
                    (20301, 2030, 2040, 2020),
                    (20302, 2030, 2040, None),
                ]
            )
        )
        self.assertEqual(1, len(errors))
        self.assertIn("periods without a prev_period: [2020, 20302]", errors[0])
        # Root is not the first period
        errors = validate(make_df([(2020, 2020, 2030, 2030), (2030, 2030, 2040, None)]))
        self.assertTrue(any("must be the first period 2020" in e for e in errors))
        # Unknown previous period
        errors = validate(make_df([(2020, 2020, 2030, None), (2030, 2030, 2040, 2025)]))
        self.assertEqual(1, len(errors))
        self.assertIn("unknown prev_period by period: {2030: 2025}", errors[0])
        # Cycle
        errors = validate(
            make_df(
                [
                    (2020, 2020, 2030, None),
                    (20301, 2030, 2040, 20302),
                    (20302, 2030, 2040, 20301),
                ]
            )
        )
        self.assertTrue(any("never reaches a root period" in e for e in errors))
        # Child starts before its parent ends
        errors = validate(make_df([(2020, 2020, 2030, None), (2025, 2025, 2035, 2020)]))
        self.assertEqual(1, len(errors))
        self.assertIn(
            "Period 2025 starts in 2025, before its prev_period 2020 ends in 2030",
            errors[0],
        )

    def test_validate_period_probabilities(self):
        """
        Check the probability validation against the period tree: the
        probability of reaching a period; the root is 1 and the periods
        following a period sum to that period's probability.
        """
        validate = MODULE_BEING_TESTED.validate_period_probabilities

        def make_df(rows):
            return pd.DataFrame(rows, columns=["period", "prev_period", "probability"])

        # Valid two-branch tree, root unspecified (defaults to 1)
        self.assertListEqual(
            [],
            validate(
                make_df([(2020, None, None), (20301, 2020, 0.5), (20302, 2020, 0.5)])
            ),
        )
        # Valid three-stage tree: leaves sum to their parent's 0.5
        self.assertListEqual(
            [],
            validate(
                make_df(
                    [
                        (2020, None, 1.0),
                        (20301, 2020, 0.5),
                        (20302, 2020, 0.5),
                        (20401, 20301, 0.2),
                        (20402, 20301, 0.3),
                        (20403, 20302, 0.5),
                    ]
                )
            ),
        )
        # Valid: deterministic, nothing specified; single child defaults to 1
        self.assertListEqual(
            [], validate(make_df([(2020, None, None), (2030, None, None)]))
        )
        self.assertListEqual(
            [], validate(make_df([(2020, None, None), (2030, 2020, None)]))
        )
        # A probability without a tree
        errors = validate(make_df([(2020, None, None), (2030, None, 0.5)]))
        self.assertEqual(1, len(errors))
        self.assertIn("requires a period tree", errors[0])
        # Children not summing to their parent's probability
        errors = validate(
            make_df([(2020, None, None), (20301, 2020, 0.5), (20302, 2020, 0.4)])
        )
        self.assertEqual(1, len(errors))
        self.assertIn("must sum to its probability 1.0", errors[0])
        self.assertIn("periods [20301, 20302] sum to 0.9", errors[0])
        # Leaves given as if conditional (0.5 each under a 0.5 parent)
        errors = validate(
            make_df(
                [
                    (2020, None, None),
                    (20301, 2020, 0.5),
                    (20302, 2020, 0.5),
                    (20401, 20301, 0.5),
                    (20402, 20301, 0.5),
                ]
            )
        )
        self.assertEqual(1, len(errors))
        self.assertIn(
            "following period 20301 must sum to its probability 0.5", errors[0]
        )
        # Root probability other than 1
        errors = validate(make_df([(2020, None, 0.9), (20301, 2020, 0.9)]))
        self.assertEqual(1, len(errors))
        self.assertIn("root period 2020 must have a probability of 1", errors[0])
        # Out of range
        errors = validate(
            make_df([(2020, None, None), (20301, 2020, 1.5), (20302, 2020, -0.5)])
        )
        self.assertTrue(any("between 0 and 1" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
