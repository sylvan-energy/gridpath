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
Resolution of the market volume limits against a scenario's market groups and
temporal structure, including the wildcard (default) rows.

Covers what an example scenario cannot easily express: a wildcard row on its
own, a wildcard row overridden for one index, a NULL cell in an explicit row
falling through to the wildcard row, a group that narrows to none of the
scenario's markets, and a group limited at one resolution only.
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
MARKET_GROUP_SCENARIO_ID = 1
MARKET_VOLUME_SCENARIO_ID = 1

# Two timepoints in one period, spanned by one 'day' horizon; a 'month'
# balancing type the scenario also defines checks that a wildcard row of one
# balancing type does not leak into another
TIMEPOINTS = [1, 2]
PERIOD = 2020
SUBPROBLEM = 1
STAGE = 1

# Market_Hub_2 is deliberately not one of the scenario's markets, so the
# group containing it narrows to Market_Hub_1 and the group containing only
# it narrows to nothing
SCENARIO_MARKETS = ["Market_Hub_1"]
ALL_MARKETS = ["Market_Hub_1", "Market_Hub_2"]


class SubScenarios(object):
    """Stand-in for the SubScenarios object the module reads IDs from."""

    def __init__(self, **ids):
        self.TEMPORAL_SCENARIO_ID = TEMPORAL_SCENARIO_ID
        self.MARKET_SCENARIO_ID = MARKET_SCENARIO_ID
        self.MARKET_GROUP_SCENARIO_ID = MARKET_GROUP_SCENARIO_ID
        self.MARKET_VOLUME_SCENARIO_ID = MARKET_VOLUME_SCENARIO_ID
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

        for market in SCENARIO_MARKETS:
            c.execute(
                "INSERT INTO inputs_geography_markets (market_scenario_id, market) "
                "VALUES (?, ?)",
                (MARKET_SCENARIO_ID, market),
            )

        # All_Hubs spans both markets and so narrows to Market_Hub_1;
        # Market_Hub_2 is a group that narrows to nothing
        for group, markets in [
            ("All_Hubs", ALL_MARKETS),
            ("Market_Hub_1", ["Market_Hub_1"]),
            ("Market_Hub_2", ["Market_Hub_2"]),
        ]:
            for market in markets:
                c.execute(
                    """INSERT INTO inputs_market_groups
                    (market_group_scenario_id, market_group, market)
                    VALUES (?, ?, ?)""",
                    (MARKET_GROUP_SCENARIO_ID, group, market),
                )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def limit_group(self, group, tmp=None, hrz=None, prd=None):
        """
        Give *group* a volume profile, at the resolutions whose profile ID is
        passed. Creates the profile subscenario rows the limits hang off.
        """
        c = self.conn.cursor()
        for profile_id, table, column in [
            (
                tmp,
                "subscenarios_market_volume_profiles",
                "market_volume_profile_scenario_id",
            ),
            (
                hrz,
                "subscenarios_market_volume_hrz_profiles",
                "market_volume_hrz_profile_scenario_id",
            ),
            (
                prd,
                "subscenarios_market_volume_prd_profiles",
                "market_volume_prd_profile_scenario_id",
            ),
        ]:
            if profile_id is not None:
                c.execute(
                    f"INSERT INTO {table} (market_group, {column}, name) "
                    f"VALUES (?, ?, 'test')",
                    (group, profile_id),
                )
        c.execute(
            """INSERT INTO inputs_market_volume
            (market_volume_scenario_id, market_group,
             market_volume_profile_scenario_id,
             market_volume_hrz_profile_scenario_id,
             market_volume_prd_profile_scenario_id,
             varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES (?, ?, ?, ?, ?, 0, 0)""",
            (MARKET_VOLUME_SCENARIO_ID, group, tmp, hrz, prd),
        )
        self.conn.commit()

    def insert_tmp_limits(self, group, profile_id, rows):
        self.conn.cursor().executemany(
            """INSERT INTO inputs_market_volume_profiles
            (market_group, market_volume_profile_scenario_id, weather_iteration,
             hydro_iteration, stage_id, timepoint, max_market_sales,
             max_market_purchases, max_final_market_sales,
             max_final_market_purchases)
            VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?, ?)""",
            [(group, profile_id, STAGE) + r for r in rows],
        )
        self.conn.commit()

    def insert_hrz_limits(self, group, profile_id, rows):
        self.conn.cursor().executemany(
            """INSERT INTO inputs_market_volume_hrz_profiles
            (market_group, market_volume_hrz_profile_scenario_id,
             weather_iteration, hydro_iteration, stage_id,
             balancing_type_horizon, horizon, max_market_sales_in_hrz,
             max_market_purchases_in_hrz,
             max_market_sales_in_hrz_include_storage_losses)
            VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?, ?)""",
            [(group, profile_id, STAGE) + r for r in rows],
        )
        self.conn.commit()

    def insert_prd_limits(self, group, profile_id, rows):
        self.conn.cursor().executemany(
            """INSERT INTO inputs_market_volume_prd_profiles
            (market_group, market_volume_prd_profile_scenario_id,
             weather_iteration, hydro_iteration, stage_id, period,
             max_market_sales_in_prd, max_market_purchases_in_prd,
             max_market_sales_in_prd_include_storage_losses)
            VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?)""",
            [(group, profile_id, STAGE) + r for r in rows],
        )
        self.conn.commit()

    def resolve(self):
        """
        Run the module's input queries and return the four results as lists
        of rows.
        """
        return [
            cursor.fetchall()
            for cursor in get_inputs_from_database(
                scenario_id=1,
                subscenarios=SubScenarios(),
                weather_iteration=0,
                hydro_iteration=0,
                availability_iteration=0,
                subproblem=SUBPROBLEM,
                stage=STAGE,
                conn=self.conn,
            )
        ]

    def test_groups_are_narrowed_to_the_scenarios_markets(self):
        """
        A group keeps the members the scenario models and a group left with
        none of them does not appear at all.
        """
        groups, _, _, _ = self.resolve()
        self.assertListEqual(
            [("All_Hubs", "Market_Hub_1"), ("Market_Hub_1", "Market_Hub_1")], groups
        )

    def test_limits_of_a_group_with_no_market_are_dropped(self):
        """
        A group that narrows to none of the scenario's markets contributes no
        limits, so a scenario-wide group definition can be shared.
        """
        self.limit_group("Market_Hub_2", tmp=1)
        self.insert_tmp_limits("Market_Hub_2", 1, [(0, 10, 5, None, None)])
        groups, tmp_limits, _, _ = self.resolve()
        self.assertNotIn("Market_Hub_2", [grp for grp, mrkt in groups])
        self.assertListEqual([], tmp_limits)

    def test_timepoint_wildcard_row_applies_to_every_timepoint(self):
        """
        A wildcard row (timepoint 0) supplies the limits for the timepoints
        without their own row.
        """
        self.limit_group("All_Hubs", tmp=1)
        self.insert_tmp_limits("All_Hubs", 1, [(0, 10, 5, None, None)])
        _, tmp_limits, _, _ = self.resolve()
        self.assertListEqual(
            [
                ("All_Hubs", 1, 10, 5, None, None),
                ("All_Hubs", 2, 10, 5, None, None),
            ],
            tmp_limits,
        )

    def test_explicit_row_overrides_the_wildcard_per_column(self):
        """
        An explicit row wins column by column; the columns it leaves NULL
        fall through to the wildcard row.
        """
        self.limit_group("All_Hubs", tmp=1)
        self.insert_tmp_limits(
            "All_Hubs",
            1,
            [(0, 10, 5, None, 99), (2, None, 7, None, None)],
        )
        _, tmp_limits, _, _ = self.resolve()
        self.assertListEqual(
            [("All_Hubs", 1, 10, 5, None, 99), ("All_Hubs", 2, 10, 7, None, 99)],
            tmp_limits,
        )

    def test_horizon_wildcard_is_per_balancing_type(self):
        """
        A wildcard row (horizon 0) applies to the horizons of its own
        balancing type only, and an explicit row still wins.
        """
        self.limit_group("All_Hubs", hrz=1)
        self.insert_hrz_limits(
            "All_Hubs", 1, [("day", 0, 100, 200, 1), ("month", 0, 300, 400, None)]
        )
        _, _, hrz_limits, _ = self.resolve()
        # Only 'day' 202001 is in this subproblem and stage
        self.assertListEqual([("All_Hubs", "day", 202001, 100, 200, 1)], hrz_limits)

        self.insert_hrz_limits("All_Hubs", 1, [("day", 202001, None, 250, None)])
        _, _, hrz_limits, _ = self.resolve()
        self.assertListEqual([("All_Hubs", "day", 202001, 100, 250, 1)], hrz_limits)

    def test_a_group_may_be_limited_at_one_resolution_only(self):
        """
        The three resolutions have their own profile subscenarios, so a group
        limited only by period needs no timepoint or horizon profile.
        """
        self.limit_group("All_Hubs", prd=1)
        self.insert_prd_limits("All_Hubs", 1, [(0, 5000, 6000, 1)])
        _, tmp_limits, hrz_limits, prd_limits = self.resolve()
        self.assertListEqual([], tmp_limits)
        self.assertListEqual([], hrz_limits)
        self.assertListEqual([("All_Hubs", PERIOD, 5000, 6000, 1)], prd_limits)

    def test_groups_are_resolved_independently(self):
        """
        Two groups limited at different resolutions each get their own
        limits, and nothing leaks between them.
        """
        self.limit_group("All_Hubs", tmp=1, prd=1)
        self.insert_tmp_limits("All_Hubs", 1, [(0, 10, 5, None, None)])
        self.insert_prd_limits("All_Hubs", 1, [(0, 5000, None, None)])
        self.limit_group("Market_Hub_1", tmp=1)
        self.insert_tmp_limits("Market_Hub_1", 1, [(1, 3, 4, None, None)])

        _, tmp_limits, hrz_limits, prd_limits = self.resolve()
        self.assertListEqual(
            [
                ("All_Hubs", 1, 10, 5, None, None),
                ("All_Hubs", 2, 10, 5, None, None),
                ("Market_Hub_1", 1, 3, 4, None, None),
            ],
            tmp_limits,
        )
        self.assertListEqual([], hrz_limits)
        self.assertListEqual([("All_Hubs", PERIOD, 5000, None, None)], prd_limits)

    def test_no_limits_resolve_to_no_rows(self):
        """
        With no group in the volume subscenario, the limit queries return no
        rows at all rather than a row of defaults per index, so no input file
        is written.
        """
        _, tmp_limits, hrz_limits, prd_limits = self.resolve()
        self.assertListEqual([], tmp_limits)
        self.assertListEqual([], hrz_limits)
        self.assertListEqual([], prd_limits)


if __name__ == "__main__":
    unittest.main()
