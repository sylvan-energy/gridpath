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
Calendar rows (day-of-year and month-of-year rows) in the exogenous
balancing type - horizon availability derates: a recurring outage given
once by date applies in every period, and an explicit row for one year's
date takes precedence.
"""

import os.path
import sqlite3
import unittest

from gridpath.project.availability.availability_types import exogenous

DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db", "db_schema.sql"
)

DAY_BT = "subproblem_period_day_linear"
MONTH_BT = "subproblem_period_month_circular"


class SubScenarios:
    """Scenario subscenario IDs; unset IDs are "NULL" as in the database"""

    TEMPORAL_SCENARIO_ID = 1
    PROJECT_PORTFOLIO_SCENARIO_ID = 1
    PROJECT_AVAILABILITY_SCENARIO_ID = 1

    def __getattr__(self, name):
        return "NULL"


class TestExogenousCalendarRows(unittest.TestCase):
    """
    Periods 2020 and 2030, with one timepoint on each of 3 and 4 June
    (timepoints 1-2 in 2020, 3-4 in 2030), in the built-in day horizons
    (20200603, 20200604, 20300603, 20300604) and month horizons (202006,
    203006); subproblem 1, stage 1.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())

        for tmp, period, day in [
            (1, 2020, 3),
            (2, 2020, 4),
            (3, 2030, 3),
            (4, 2030, 4),
        ]:
            self.conn.execute(
                """INSERT INTO inputs_temporal (temporal_scenario_id,
                subproblem_id, stage_id, timepoint, period,
                number_of_hours_in_timepoint, timepoint_weight,
                spinup_or_lookahead, month, day_of_month)
                VALUES (1, 1, 1, ?, ?, 1, 1, 0, 6, ?)""",
                (tmp, period, day),
            )
            for bt, hrz in [
                (DAY_BT, period * 10000 + 600 + day),
                (MONTH_BT, period * 100 + 6),
            ]:
                self.conn.execute(
                    """INSERT INTO inputs_temporal_horizon_timepoints
                    VALUES (1, 1, 1, ?, ?, ?)""",
                    (tmp, bt, hrz),
                )
                self.conn.execute(
                    """INSERT OR IGNORE INTO inputs_temporal_horizons
                    (temporal_scenario_id, balancing_type_horizon, horizon,
                    boundary)
                    VALUES (1, ?, ?, ?)""",
                    (bt, hrz, bt.split("_")[-1]),
                )

        self.conn.executescript("""
            INSERT INTO inputs_project_portfolios
            (project_portfolio_scenario_id, project, capacity_type)
            VALUES (1, 'Coal', 'gen_spec'), (1, 'Gas', 'gen_spec');

            INSERT INTO inputs_project_availability
            (project_availability_scenario_id, project, availability_type,
             exogenous_availability_independent_bt_hrz_scenario_id,
             exogenous_availability_weather_bt_hrz_scenario_id)
            VALUES (1, 'Coal', 'exogenous', 1, NULL),
                   (1, 'Gas', 'exogenous', NULL, 1);
            """)
        # Coal: an outage on 3-4 June every year, except that 4 June 2030 is
        # a partial derate; a 0.9 derate in June (month-of-year row) on the
        # month balancing type; a row for another stage that doesn't apply
        self.conn.executemany(
            """INSERT INTO inputs_project_availability_exogenous_independent_bt_hrz
            VALUES ('Coal', 1, 0, ?, ?, ?, ?)""",
            [
                (1, DAY_BT, 603, 0.0),
                (1, DAY_BT, 604, 0.0),
                (1, DAY_BT, 20300604, 0.5),
                (1, MONTH_BT, 6, 0.9),
                (2, DAY_BT, 20200603, 0.3),
            ],
        )
        # Gas: weather-dependent derate on 3 June every year
        self.conn.execute(
            """INSERT INTO inputs_project_availability_exogenous_weather_bt_hrz
            VALUES ('Gas', 1, 0, 1, 'subproblem_period_day_linear', 603, 0.8)"""
        )

    def get_bt_hrz_derates(self):
        _, _, bt_hrz_ind, bt_hrz_weather, _ = exogenous.get_inputs_from_database(
            scenario_id=1,
            subscenarios=SubScenarios(),
            weather_iteration=0,
            hydro_iteration=0,
            availability_iteration=0,
            subproblem=1,
            stage=1,
            conn=self.conn,
        )
        return sorted(bt_hrz_ind.fetchall()), sorted(bt_hrz_weather.fetchall())

    def test_calendar_rows_apply_in_every_period(self):
        independent, weather = self.get_bt_hrz_derates()
        self.assertListEqual(
            [
                ("Coal", DAY_BT, 20200603, 0.0),
                ("Coal", DAY_BT, 20200604, 0.0),
                ("Coal", DAY_BT, 20300603, 0.0),
                ("Coal", DAY_BT, 20300604, 0.5),
                ("Coal", MONTH_BT, 202006, 0.9),
                ("Coal", MONTH_BT, 203006, 0.9),
            ],
            independent,
        )
        self.assertListEqual(
            [("Gas", DAY_BT, 20200603, 0.8), ("Gas", DAY_BT, 20300603, 0.8)],
            weather,
        )

    def test_explicit_row_of_another_stage_does_not_override(self):
        """
        Stage 2's explicit 20200603 row isn't read in stage 1 and doesn't
        block stage 1's day-of-year row.
        """
        independent, _ = self.get_bt_hrz_derates()
        self.assertIn(("Coal", DAY_BT, 20200603, 0.0), independent)
        self.assertNotIn(("Coal", DAY_BT, 20200603, 0.3), independent)


if __name__ == "__main__":
    unittest.main()
