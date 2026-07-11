# Copyright 2026 Sylvan Energy Analytics LLC
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

import unittest
import warnings

import numpy as np
import pandas as pd

from gridpath.common_functions import create_results_df, update_results_df


class TestUpdateResultsDf(unittest.TestCase):
    """
    update_results_df must add results columns to the consolidated results
    dataframes at the *source* column's dtype. Creating the columns as
    object dtype (e.g. by assigning None first) makes numeric columns store
    boxed Python floats -- roughly an order of magnitude more memory on the
    multi-million-row production-scale results dataframes.
    """

    def setUp(self):
        self.index = pd.MultiIndex.from_tuples(
            [("p1", 1), ("p1", 2), ("p2", 1)], names=["project", "timepoint"]
        )
        self.target = pd.DataFrame(index=self.index)

    def test_numeric_columns_stay_float64(self):
        results_df = pd.DataFrame({"power_mw": [1.5, 2.5]}, index=self.index[:2])
        update_results_df(self.target, results_df)

        self.assertEqual(str(self.target["power_mw"].dtype), "float64")
        self.assertEqual(self.target["power_mw"].tolist()[:2], [1.5, 2.5])
        # rows not covered by the results are NaN
        self.assertTrue(np.isnan(self.target["power_mw"].iloc[2]))

    def test_none_values_coerce_to_float64_nan(self):
        # Duals can be None (e.g. duals_wrapper on a MIP); pandas coerces
        # [float, None] to float64 with NaN at DataFrame construction
        results_df = create_results_df(
            index_columns=["project", "timepoint"],
            results_columns=["dual"],
            data=[["p1", 1, 100.0], ["p1", 2, None]],
        )
        update_results_df(self.target, results_df)

        self.assertEqual(str(self.target["dual"].dtype), "float64")
        self.assertEqual(self.target["dual"].iloc[0], 100.0)
        self.assertTrue(np.isnan(self.target["dual"].iloc[1]))

    def test_string_columns_stay_object_without_warnings(self):
        results_df = pd.DataFrame({"ba": ["Zone1", "Zone2"]}, index=self.index[:2])
        with warnings.catch_warnings():
            # a float-initialized target column would raise a pandas
            # FutureWarning on string update; the source-dtype
            # initialization must not
            warnings.simplefilter("error")
            update_results_df(self.target, results_df)

        self.assertEqual(str(self.target["ba"].dtype), "object")
        self.assertEqual(self.target["ba"].tolist()[:2], ["Zone1", "Zone2"])

    def test_existing_column_values_are_merged_not_wiped(self):
        # Multiple modules (e.g. operational types) can write disjoint row
        # subsets of the same column; a later write must not wipe an
        # earlier one
        update_results_df(
            self.target, pd.DataFrame({"committed_mw": [5.0]}, index=self.index[:1])
        )
        update_results_df(
            self.target, pd.DataFrame({"committed_mw": [7.0]}, index=self.index[2:])
        )

        self.assertEqual(self.target["committed_mw"].iloc[0], 5.0)
        self.assertTrue(np.isnan(self.target["committed_mw"].iloc[1]))
        self.assertEqual(self.target["committed_mw"].iloc[2], 7.0)


if __name__ == "__main__":
    unittest.main()
