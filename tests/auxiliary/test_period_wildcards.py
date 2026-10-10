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

"""
The shared period wildcard (period = 0) resolution: the SQL used when
writing the inputs, the same rule for input files, and the check for
wildcard rows that apply to no period.
"""

import os.path
import sqlite3
import unittest

import pandas as pd

from gridpath.auxiliary.period_wildcards import (
    expand_period_wildcard_rows,
    period_wildcard_rows_sql,
    redundant_period_wildcards_sql,
    subproblem_periods_sql,
    temporal_periods_sql,
)

DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "db", "db_schema.sql"
)

PERIODS = [2030, 2035, 2040]


class TestPeriodWildcards(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        # Subproblem 1 has 2030 and 2035; subproblem 2 has 2040
        for period, subproblem in zip(PERIODS, [1, 1, 2]):
            self.conn.execute(
                """INSERT INTO inputs_temporal_periods
                (temporal_scenario_id, period) VALUES (1, ?)""",
                (period,),
            )
            self.conn.execute(
                """INSERT INTO inputs_temporal
                (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                period, number_of_hours_in_timepoint, timepoint_weight,
                spinup_or_lookahead)
                VALUES (1, ?, 1, ?, ?, 1, 1, 0)""",
                (subproblem, period, period),
            )
        # Curtailment costs: Wind has a wildcard and an explicit 2035 row;
        # Solar only a wildcard; Hydro explicit rows only; Coal a wildcard
        # and explicit rows for every period; Wind in subscenario 2 is not
        # selected
        self.conn.executemany(
            """INSERT INTO inputs_project_curtailment_cost
            (project, curtailment_cost_scenario_id, period,
            curtailment_cost_per_powerunithour)
            VALUES (?, ?, ?, ?)""",
            [
                ("Wind", 1, 0, 10.0),
                ("Wind", 1, 2035, 15.0),
                ("Solar", 1, 0, 20.0),
                ("Hydro", 1, 2030, 30.0),
                ("Hydro", 1, 2040, 31.0),
                ("Coal", 1, 0, 40.0),
                ("Coal", 1, 2030, 41.0),
                ("Coal", 1, 2035, 42.0),
                ("Coal", 1, 2040, 43.0),
                ("Wind", 2, 0, 99.0),
            ],
        )
        # Heat rate curves: Gas has a two-point wildcard curve and a one-point
        # 2035 curve, which replaces the wildcard curve as a whole
        self.conn.executemany(
            """INSERT INTO inputs_project_heat_rate_curves
            (project, heat_rate_curves_scenario_id, period,
            load_point_fraction, average_heat_rate_mmbtu_per_mwh)
            VALUES ('Gas', 1, ?, ?, ?)""",
            [(0, 0.5, 9.0), (0, 1.0, 8.0), (2035, 1.0, 7.0)],
        )

    def curtailment_rows(self, subproblem):
        return self.conn.execute(
            period_wildcard_rows_sql(
                table="inputs_project_curtailment_cost",
                columns=["project", "period", "curtailment_cost_per_powerunithour"],
                key_columns=["project", "curtailment_cost_scenario_id"],
                row_filter="curtailment_cost_scenario_id = 1",
                periods_sql=subproblem_periods_sql(1, subproblem),
            )
        ).fetchall()

    def test_explicit_rows_win_and_wildcards_fill_the_rest(self):
        self.assertListEqual(
            [
                ("Coal", 2030, 41.0),
                ("Coal", 2035, 42.0),
                ("Hydro", 2030, 30.0),
                ("Solar", 2030, 20.0),
                ("Solar", 2035, 20.0),
                ("Wind", 2030, 10.0),
                ("Wind", 2035, 15.0),
            ],
            self.curtailment_rows(subproblem=1),
        )

    def test_rows_are_resolved_for_the_subproblems_periods_only(self):
        self.assertListEqual(
            [
                ("Coal", 2040, 43.0),
                ("Hydro", 2040, 31.0),
                ("Solar", 2040, 20.0),
                ("Wind", 2040, 10.0),
            ],
            self.curtailment_rows(subproblem=2),
        )

    def test_an_explicit_period_replaces_a_wildcard_curve_as_a_whole(self):
        rows = self.conn.execute(
            period_wildcard_rows_sql(
                table="inputs_project_heat_rate_curves",
                columns=[
                    "project",
                    "period",
                    "load_point_fraction",
                    "average_heat_rate_mmbtu_per_mwh",
                ],
                key_columns=["project", "heat_rate_curves_scenario_id"],
                row_filter="heat_rate_curves_scenario_id = 1",
                periods_sql=temporal_periods_sql(1),
            )
        ).fetchall()
        self.assertListEqual(
            [
                ("Gas", 2030, 0.5, 9.0),
                ("Gas", 2030, 1.0, 8.0),
                ("Gas", 2035, 1.0, 7.0),
                ("Gas", 2040, 0.5, 9.0),
                ("Gas", 2040, 1.0, 8.0),
            ],
            rows,
        )

    def test_redundant_wildcards(self):
        """
        Only Coal's wildcard row applies to no period of the temporal
        scenario.
        """
        rows = self.conn.execute(
            redundant_period_wildcards_sql(
                table="inputs_project_curtailment_cost",
                key_columns=["project", "curtailment_cost_scenario_id"],
                row_filter="curtailment_cost_scenario_id = 1",
                periods_sql=temporal_periods_sql(1),
            )
        ).fetchall()
        self.assertListEqual([("Coal", 1)], rows)

    def test_input_file_rows_resolve_the_same_way(self):
        """
        The input file resolution gives the same rows as the database
        resolution (selected subscenario only, as the input files carry no
        subscenario IDs).
        """
        df = pd.read_sql(
            """SELECT project, period, curtailment_cost_per_powerunithour
            FROM inputs_project_curtailment_cost
            WHERE curtailment_cost_scenario_id = 1""",
            self.conn,
        )
        resolved = expand_period_wildcard_rows(
            df, key_columns=["project"], periods={2030, 2035}
        )
        resolved = resolved[resolved["period"].isin([2030, 2035])]
        self.assertListEqual(
            self.curtailment_rows(subproblem=1),
            sorted(resolved.itertuples(index=False, name=None)),
        )

    def test_input_file_without_wildcards_is_unchanged(self):
        df = pd.DataFrame({"project": ["A"], "period": [2030], "value": [1.0]})
        self.assertIs(df, expand_period_wildcard_rows(df, ["project"], {2030}))


if __name__ == "__main__":
    unittest.main()
