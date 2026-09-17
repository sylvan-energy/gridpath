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

"""
Differential tests for stochastic scenario trees (prev_period on the periods
table). The example tests only pin objective function values; these tests
compare decisions:

* a stochastic example whose two branches carry identical data must make
  exactly the decisions of its deterministic twin in every period;
* on a three-stage tree, capacity in each period must equal the new build
  summed along the path from the root to that period (and nothing from any
  sibling branch).

The scenarios are solved into a temporary directory so that the committed
example directories are not touched.
"""

import os
import shutil
import tempfile
import unittest

import pandas as pd

from db import create_database
from db.utilities import port_csvs_to_db, scenario
from gridpath import run_end_to_end

REPO_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_TEMPLATE_ENV_VAR = "GRIDPATH_TEST_EXAMPLES_DB_TEMPLATE"

IDENTICAL_BRANCHES = (
    "2periods_new_build_2zones_new_build_transmission_stochastic_identical_branches"
)
DETERMINISTIC_TWIN = (
    "2periods_new_build_2zones_new_build_transmission_deterministic_twin"
)
THREE_STAGE_TREE = "3stage_new_build_2zones_new_build_transmission_stochastic_tree"

# Branch periods of the identical-branches example and the twin's period
# they stand in for
BRANCH_TO_TWIN_PERIOD = {20301: 2030, 20302: 2030}
# Period tree of the three-stage example
PREV_PERIOD = {
    20301: 2020,
    20302: 2020,
    20401: 20301,
    20402: 20301,
    20403: 20302,
    20404: 20302,
}


def path_to_root(period):
    """Periods on the path from *period* back to the root, inclusive."""
    path = [period]
    while period in PREV_PERIOD:
        period = PREV_PERIOD[period]
        path.append(period)
    return path


class TestStochasticTreeExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "examples.db")
        cls.scenario_location = os.path.join(cls.tmp_dir.name, "scenarios")
        os.makedirs(cls.scenario_location)

        template_path = os.environ.get(DB_TEMPLATE_ENV_VAR)
        if template_path and os.path.exists(template_path):
            shutil.copyfile(template_path, cls.db_path)
        else:
            csv_path = os.path.join(REPO_DIRECTORY, "db", "csvs_test_examples")
            create_database.main(
                [
                    "--database",
                    cls.db_path,
                    "--db_schema",
                    os.path.join(REPO_DIRECTORY, "db", "db_schema.sql"),
                    "--data_directory",
                    os.path.join(REPO_DIRECTORY, "db", "data"),
                ]
            )
            port_csvs_to_db.main(
                ["--database", cls.db_path, "--csv_location", csv_path, "--quiet"]
            )
            scenario.main(
                [
                    "--database",
                    cls.db_path,
                    "--csv_path",
                    os.path.join(csv_path, "scenarios.csv"),
                    "--quiet",
                ]
            )

        for scenario_name in [IDENTICAL_BRANCHES, DETERMINISTIC_TWIN, THREE_STAGE_TREE]:
            run_end_to_end.main(
                [
                    "--database",
                    cls.db_path,
                    "--scenario",
                    scenario_name,
                    "--scenario_location",
                    cls.scenario_location,
                    "--quiet",
                    "--mute_solver_output",
                    "--testing",
                ]
            )

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def read_results(self, scenario_name, results_file):
        return pd.read_csv(
            os.path.join(self.scenario_location, scenario_name, "results", results_file)
        )

    def test_identical_branches_match_deterministic_twin(self):
        """
        Every project and transmission decision in each branch equals the
        twin's decision in the period the branch stands in for.
        """
        for results_file, index_col, value_cols in [
            ("project_period.csv", "project", ["capacity_mw", "new_build_mw"]),
            (
                "transmission_period.csv",
                "transmission_line",
                ["min_mw", "max_mw", "new_build_capacity_mw"],
            ),
        ]:
            stochastic = self.read_results(IDENTICAL_BRANCHES, results_file)
            twin = self.read_results(DETERMINISTIC_TWIN, results_file).set_index(
                [index_col, "period"]
            )
            self.assertEqual(
                len(stochastic), len(twin) + len(twin.xs(2030, level="period"))
            )
            for _, row in stochastic.iterrows():
                twin_period = BRANCH_TO_TWIN_PERIOD.get(row["period"], row["period"])
                twin_row = twin.loc[(row[index_col], twin_period)]
                for col in value_cols:
                    with self.subTest(
                        file=results_file,
                        entity=row[index_col],
                        period=row["period"],
                        col=col,
                    ):
                        if pd.isna(row[col]):
                            self.assertTrue(pd.isna(twin_row[col]))
                        else:
                            self.assertAlmostEqual(row[col], twin_row[col], places=6)

    def test_three_stage_tree_capacity_follows_path(self):
        """
        Capacity in each period is the new build summed over the path from
        the root to that period; a sibling branch's build never counts.
        """
        checks = [
            (
                "project_period.csv",
                "project",
                "gen_new_lin",
                "capacity_type",
                "new_build_mw",
                "capacity_mw",
            ),
            (
                "transmission_period.csv",
                "transmission_line",
                "tx_new_lin",
                "tx_capacity_type",
                "new_build_capacity_mw",
                "max_mw",
            ),
        ]
        for (
            results_file,
            index_col,
            cap_type,
            cap_type_col,
            build_col,
            capacity_col,
        ) in checks:
            df = self.read_results(THREE_STAGE_TREE, results_file)
            df = df[df[cap_type_col] == cap_type]
            self.assertTrue(len(df) > 0)
            for entity, entity_df in df.groupby(index_col):
                build = entity_df.set_index("period")[build_col].fillna(0)
                capacity = entity_df.set_index("period")[capacity_col]
                for period in capacity.index:
                    with self.subTest(file=results_file, entity=entity, period=period):
                        expected = sum(build.get(p, 0) for p in path_to_root(period))
                        self.assertAlmostEqual(expected, capacity[period], places=6)
            # The tree is exercised: siblings 20301/20302 must differ somewhere
            # for at least one entity (otherwise the path check is vacuous)
            by_period = df.pivot(index=index_col, columns="period", values=capacity_col)
            self.assertFalse(
                (by_period[20301] == by_period[20302]).all(),
                msg=f"{results_file}: branches identical",
            )


if __name__ == "__main__":
    unittest.main()
