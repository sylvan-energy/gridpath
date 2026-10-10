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
The shared calendar row SQL building blocks; their use by the opchar, market
volume and availability inputs is tested with those modules.
"""

import os.path
import sqlite3
import unittest

from gridpath.auxiliary.calendar_rows import (
    DAY_HORIZON_TYPES,
    MONTH_HORIZON_TYPES,
    bt_hrz_calendar_index_sql,
    calendar_row_sql,
)
from gridpath.temporal.operations.horizons import BUILTIN_HORIZON_TYPES

DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "db", "db_schema.sql"
)

MONTH_BT = "subproblem_period_month_linear"
DAY_BT = "subproblem_period_day_circular"


class TestCalendarRows(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        # Period 2020: 3 January and 14 February, one timepoint each; every
        # timepoint is in a 'day' horizon and in its built-in month and day
        # horizons
        for tmp, month, day in [(1, 1, 3), (2, 2, 14)]:
            self.conn.execute(
                """INSERT INTO inputs_temporal
                (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                period, number_of_hours_in_timepoint, timepoint_weight,
                spinup_or_lookahead, month, day_of_month)
                VALUES (1, 1, 1, ?, 2020, 1, 1, 0, ?, ?)""",
                (tmp, month, day),
            )
            for bt, hrz in [
                ("day", tmp),
                (MONTH_BT, 202000 + month),
                (DAY_BT, 20200000 + month * 100 + day),
            ]:
                self.conn.execute(
                    """INSERT INTO inputs_temporal_horizon_timepoints
                    (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                    balancing_type_horizon, horizon)
                    VALUES (1, 1, 1, ?, ?, ?)""",
                    (tmp, bt, hrz),
                )

    def tearDown(self):
        self.conn.close()

    def test_calendar_horizon_types_are_builtin(self):
        self.assertTrue(
            set(MONTH_HORIZON_TYPES + DAY_HORIZON_TYPES) <= set(BUILTIN_HORIZON_TYPES)
        )

    def test_index_has_calendar_keys_of_calendar_horizons_only(self):
        rows = self.conn.execute(bt_hrz_calendar_index_sql(1, 1, 1)).fetchall()
        calendar_rows = [
            (MONTH_BT, 202001, 1),
            (MONTH_BT, 202002, 2),
            (DAY_BT, 20200103, 103),
            (DAY_BT, 20200214, 214),
        ]
        self.assertListEqual(
            sorted(rows, key=str),
            sorted([("day", 1, None), ("day", 2, None)] + calendar_rows, key=str),
        )
        rows = self.conn.execute(
            bt_hrz_calendar_index_sql(1, 1, 1, calendar_horizons_only=True)
        ).fetchall()
        self.assertListEqual(sorted(rows), sorted(calendar_rows))

    def test_calendar_row_condition(self):
        rows = [(MONTH_BT, 1), (MONTH_BT, 12), (MONTH_BT, 13), (MONTH_BT, 0)]
        rows += [(MONTH_BT, 202001), (MONTH_BT, 101)]
        rows += [(DAY_BT, 101), (DAY_BT, 1231), (DAY_BT, 1), (DAY_BT, 0)]
        rows += [(DAY_BT, 1232), (DAY_BT, 20200101), ("day", 1), ("day", 101)]
        matches = [
            row
            for row in rows
            if self.conn.execute(
                f"""SELECT {calendar_row_sql("bt", "hrz")}
                FROM (SELECT ? AS bt, ? AS hrz)""",
                row,
            ).fetchone()[0]
        ]
        self.assertListEqual(
            [(MONTH_BT, 1), (MONTH_BT, 12), (DAY_BT, 101), (DAY_BT, 1231)], matches
        )


if __name__ == "__main__":
    unittest.main()
