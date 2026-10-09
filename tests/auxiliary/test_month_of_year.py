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
The shared month-of-year SQL building blocks; their use by the opchar and
market volume inputs is tested with those modules.
"""

import os.path
import sqlite3
import unittest

from gridpath.auxiliary.month_of_year import (
    MONTH_HORIZON_TYPES,
    bt_hrz_month_index_sql,
    month_of_year_row_sql,
)
from gridpath.temporal.operations.horizons import BUILTIN_HORIZON_TYPES

DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "db", "db_schema.sql"
)

MONTH_BT = "subproblem_period_month_linear"


class TestMonthOfYear(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        # Period 2020, months 1 and 2, one timepoint each; every timepoint is
        # in a 'day' horizon and in its built-in month horizon
        for tmp, month in [(1, 1), (2, 2)]:
            self.conn.execute(
                """INSERT INTO inputs_temporal
                (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                period, number_of_hours_in_timepoint, timepoint_weight,
                spinup_or_lookahead, month)
                VALUES (1, 1, 1, ?, 2020, 1, 1, 0, ?)""",
                (tmp, month),
            )
            for bt, hrz in [("day", tmp), (MONTH_BT, 202000 + month)]:
                self.conn.execute(
                    """INSERT INTO inputs_temporal_horizon_timepoints
                    (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                    balancing_type_horizon, horizon)
                    VALUES (1, 1, 1, ?, ?, ?)""",
                    (tmp, bt, hrz),
                )

    def tearDown(self):
        self.conn.close()

    def test_month_horizon_types_are_builtin(self):
        self.assertTrue(set(MONTH_HORIZON_TYPES) <= set(BUILTIN_HORIZON_TYPES))

    def test_index_has_months_of_month_horizons_only(self):
        rows = self.conn.execute(bt_hrz_month_index_sql(1, 1, 1)).fetchall()
        self.assertListEqual(
            sorted(rows, key=str),
            sorted(
                [
                    ("day", 1, None),
                    ("day", 2, None),
                    (MONTH_BT, 202001, 1),
                    (MONTH_BT, 202002, 2),
                ],
                key=str,
            ),
        )
        rows = self.conn.execute(
            bt_hrz_month_index_sql(1, 1, 1, month_horizons_only=True)
        ).fetchall()
        self.assertListEqual(
            sorted(rows), [(MONTH_BT, 202001, 1), (MONTH_BT, 202002, 2)]
        )

    def test_month_of_year_row_condition(self):
        rows = [(MONTH_BT, 1), (MONTH_BT, 12), (MONTH_BT, 13), (MONTH_BT, 0)]
        rows += [(MONTH_BT, 202001), ("day", 1)]
        matches = [
            row
            for row in rows
            if self.conn.execute(
                f"""SELECT {month_of_year_row_sql("bt", "hrz")}
                FROM (SELECT ? AS bt, ? AS hrz)""",
                row,
            ).fetchone()[0]
        ]
        self.assertListEqual([(MONTH_BT, 1), (MONTH_BT, 12)], matches)


if __name__ == "__main__":
    unittest.main()
