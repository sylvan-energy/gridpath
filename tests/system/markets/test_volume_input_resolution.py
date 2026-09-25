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
Resolution of the market volume limits against a scenario's temporal
structure, including the wildcard (default) rows.

The example scenarios cover the by-market timepoint limits; this covers the
other four limit tables and the cases an example cannot easily express: a
wildcard row on its own, a wildcard row overridden for one index, and a NULL
cell in an explicit row falling through to the wildcard row.
"""

import os.path
import sqlite3
import unittest

from gridpath.system.markets.volume import get_inputs_from_database

DB_SCHEMA = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "db", "db_schema.sql"
)

TEMPORAL_SCENARIO_ID = 1
MARKET_SCENARIO_ID = 1
MARKET_VOLUME_SCENARIO_ID = 1
MARKET_VOLUME_PROFILE_SCENARIO_ID = 1

# Two timepoints in one period, spanned by one 'day' horizon; a second
# 'month' horizon of the same balancing type as no market limit rows, so it
# also checks that a balancing type's wildcard does not leak across types
TIMEPOINTS = [1, 2]
PERIOD = 2020
SUBPROBLEM = 1
STAGE = 1


class SubScenarios(object):
    """Stand-in for the SubScenarios object the module reads IDs from."""

    def __init__(self, **ids):
        self.TEMPORAL_SCENARIO_ID = TEMPORAL_SCENARIO_ID
        self.MARKET_SCENARIO_ID = MARKET_SCENARIO_ID
        self.MARKET_VOLUME_SCENARIO_ID = MARKET_VOLUME_SCENARIO_ID
        # Unset subscenario IDs come back from the database as the string
        # "NULL", not None
        self.MARKET_VOLUME_TOTAL_IN_TMP_SCENARIO_ID = "NULL"
        self.MARKET_VOLUME_TOTAL_IN_HRZ_SCENARIO_ID = "NULL"
        self.MARKET_VOLUME_TOTAL_IN_PRD_SCENARIO_ID = "NULL"
        for key, value in ids.items():
            setattr(self, key, value)


class TestMarketVolumeInputResolution(unittest.TestCase):
    """ """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA) as f:
            self.conn.executescript(f.read())

        c = self.conn.cursor()
        c.execute(
            "INSERT INTO inputs_temporal_periods (temporal_scenario_id, period) "
            "VALUES (?, ?)",
            (TEMPORAL_SCENARIO_ID, PERIOD),
        )
        for tmp in TIMEPOINTS:
            c.execute(
                """INSERT INTO inputs_temporal
                (temporal_scenario_id, subproblem_id, stage_id, timepoint, period,
                 number_of_hours_in_timepoint, timepoint_weight,
                 spinup_or_lookahead)
                VALUES (?, ?, ?, ?, ?, 1, 1, 0)""",
                (TEMPORAL_SCENARIO_ID, SUBPROBLEM, STAGE, tmp, PERIOD),
            )
            c.execute(
                """INSERT INTO inputs_temporal_horizon_timepoints
                (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                 balancing_type_horizon, horizon)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (TEMPORAL_SCENARIO_ID, SUBPROBLEM, STAGE, tmp, "day", 202001),
            )
        for bt, hrz in [("day", 202001), ("month", 202001)]:
            c.execute(
                """INSERT INTO inputs_temporal_horizons
                (temporal_scenario_id, balancing_type_horizon, horizon, boundary)
                VALUES (?, ?, ?, ?)""",
                (TEMPORAL_SCENARIO_ID, bt, hrz, "circular"),
            )

        c.execute(
            "INSERT INTO inputs_geography_markets (market_scenario_id, market) "
            "VALUES (?, ?)",
            (MARKET_SCENARIO_ID, "Market_Hub"),
        )
        c.execute(
            """INSERT INTO inputs_market_volume
            (market_volume_scenario_id, market, market_volume_profile_scenario_id,
             varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES (?, ?, ?, ?, ?)""",
            (
                MARKET_VOLUME_SCENARIO_ID,
                "Market_Hub",
                MARKET_VOLUME_PROFILE_SCENARIO_ID,
                0,
                0,
            ),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def resolve(self, subscenarios):
        """
        Run the module's input queries and return the five results as lists
        of rows.
        """
        return [
            cursor.fetchall()
            for cursor in get_inputs_from_database(
                scenario_id=1,
                subscenarios=subscenarios,
                weather_iteration=0,
                hydro_iteration=0,
                availability_iteration=0,
                subproblem=SUBPROBLEM,
                stage=STAGE,
                conn=self.conn,
            )
        ]

    def insert_tmp_profile_rows(self, rows):
        c = self.conn.cursor()
        c.executemany(
            """INSERT INTO inputs_market_volume_profiles
            (market, market_volume_profile_scenario_id, weather_iteration,
             hydro_iteration, stage_id, timepoint, max_market_sales,
             max_market_purchases, max_final_market_sales,
             max_final_market_purchases)
            VALUES ('Market_Hub', ?, 0, 0, ?, ?, ?, ?, ?, ?)""",
            [(MARKET_VOLUME_PROFILE_SCENARIO_ID, STAGE) + r for r in rows],
        )
        self.conn.commit()

    def insert_hrz_profile_rows(self, rows):
        c = self.conn.cursor()
        c.executemany(
            """INSERT INTO inputs_market_volume_hrz_profiles
            (market, market_volume_profile_scenario_id, weather_iteration,
             hydro_iteration, stage_id, balancing_type_horizon, horizon,
             max_market_sales_in_hrz, max_market_purchases_in_hrz)
            VALUES ('Market_Hub', ?, 0, 0, ?, ?, ?, ?, ?)""",
            [(MARKET_VOLUME_PROFILE_SCENARIO_ID, STAGE) + r for r in rows],
        )
        self.conn.commit()

    def test_timepoint_limits_wildcard_row_applies_to_every_timepoint(self):
        """
        A wildcard row (timepoint 0) supplies the limits for the timepoints
        without their own row.
        """
        self.insert_tmp_profile_rows([(0, 10, 5, None, None)])
        volume = self.resolve(SubScenarios())[0]
        self.assertListEqual(
            [
                ("Market_Hub", 1, 10, 5, None, None),
                ("Market_Hub", 2, 10, 5, None, None),
            ],
            volume,
        )

    def test_timepoint_limits_explicit_row_overrides_wildcard_per_column(self):
        """
        An explicit row wins column by column; the columns it leaves NULL
        fall through to the wildcard row.
        """
        self.insert_tmp_profile_rows(
            [
                (0, 10, 5, None, 99),
                # Overrides only the purchases limit
                (2, None, 7, None, None),
            ]
        )
        volume = self.resolve(SubScenarios())[0]
        self.assertListEqual(
            [
                ("Market_Hub", 1, 10, 5, None, 99),
                ("Market_Hub", 2, 10, 7, None, 99),
            ],
            volume,
        )

    def test_horizon_limits_wildcard_is_per_balancing_type(self):
        """
        A wildcard row (horizon 0) applies to the horizons of its own
        balancing type only, and an explicit row still wins.
        """
        self.insert_hrz_profile_rows([(("day"), 0, 100, 200), (("month"), 0, 300, 400)])
        volume_hrz = self.resolve(SubScenarios())[1]
        # Only 'day' 202001 is in this subproblem and stage
        self.assertListEqual([("Market_Hub", "day", 202001, 100, 200)], volume_hrz)

        self.insert_hrz_profile_rows([("day", 202001, None, 250)])
        volume_hrz = self.resolve(SubScenarios())[1]
        self.assertListEqual([("Market_Hub", "day", 202001, 100, 250)], volume_hrz)

    def test_no_limits_resolve_to_no_rows_for_the_total_limits(self):
        """
        With no subscenario specified, the total limit queries return no
        rows at all rather than a row of defaults per index, so no input
        file is written.
        """
        _, _, totals_in_tmp, totals_in_hrz, totals_in_prd = self.resolve(SubScenarios())
        self.assertListEqual([], totals_in_tmp)
        self.assertListEqual([], totals_in_hrz)
        self.assertListEqual([], totals_in_prd)

    def test_total_limit_wildcard_rows_resolve_for_every_index(self):
        """
        The wildcard row of each total limit table is expanded over the
        scenario's timepoints, horizons and periods, and an explicit row
        overrides it per column.
        """
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO subscenarios_market_volume_totals_in_tmp "
            "(market_volume_total_in_tmp_scenario_id, name) VALUES (1, 'test')"
        )
        c.executemany(
            """INSERT INTO inputs_market_volume_totals_in_tmp
            (market_volume_total_in_tmp_scenario_id, weather_iteration, timepoint,
             max_total_net_market_purchases_in_tmp, max_total_net_market_sales_in_tmp)
            VALUES (1, 0, ?, ?, ?)""",
            [(0, 50, 60), (2, 55, None)],
        )
        c.execute(
            "INSERT INTO subscenarios_market_volume_totals_in_hrz "
            "(market_volume_total_in_hrz_scenario_id, name) VALUES (1, 'test')"
        )
        c.execute("""INSERT INTO inputs_market_volume_totals_in_hrz
            (market_volume_total_in_hrz_scenario_id, weather_iteration,
             balancing_type_horizon, horizon,
             max_total_net_market_purchases_in_hrz,
             max_total_net_market_sales_in_hrz,
             max_total_net_market_sales_in_hrz_include_storage_losses)
            VALUES (1, 0, 'day', 0, 500, 600, 1)""")
        c.execute(
            "INSERT INTO subscenarios_market_volume_totals_in_prd "
            "(market_volume_total_in_prd_scenario_id, name) VALUES (1, 'test')"
        )
        c.execute("""INSERT INTO inputs_market_volume_totals_in_prd
            (market_volume_total_in_prd_scenario_id, period,
             max_total_net_market_purchases_in_prd,
             max_total_net_market_sales_in_prd,
             max_total_net_market_sales_in_prd_include_storage_losses)
            VALUES (1, 0, 5000, 6000, 1)""")
        self.conn.commit()

        _, _, totals_in_tmp, totals_in_hrz, totals_in_prd = self.resolve(
            SubScenarios(
                MARKET_VOLUME_TOTAL_IN_TMP_SCENARIO_ID=1,
                MARKET_VOLUME_TOTAL_IN_HRZ_SCENARIO_ID=1,
                MARKET_VOLUME_TOTAL_IN_PRD_SCENARIO_ID=1,
            )
        )
        # Timepoint 2 overrides the purchases limit and falls through to the
        # wildcard row for the sales limit
        self.assertListEqual([(1, 50, 60), (2, 55, 60)], totals_in_tmp)
        self.assertListEqual([("day", 202001, 500, 600, 1)], totals_in_hrz)
        self.assertListEqual([(PERIOD, 5000, 6000, 1)], totals_in_prd)


if __name__ == "__main__":
    unittest.main()
