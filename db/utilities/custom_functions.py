# Copyright 2016-2024 Blue Marble Analytics LLC.
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
Custom functions to be run after loading data from CSVs.
"""

from db.common_functions import spin_on_database_lock


def temporal(conn, subscenario_id):
    """

    :param conn:
    :param subscenario_id:
    """
    c = conn.cursor()

    # Subproblems
    subproblems_sql = """
        INSERT INTO inputs_temporal_subproblems
        (temporal_scenario_id, subproblem_id)
        SELECT DISTINCT temporal_scenario_id, subproblem_id
        FROM inputs_temporal
        WHERE temporal_scenario_id = ?;
        """
    spin_on_database_lock(
        conn=conn, cursor=c, sql=subproblems_sql, data=(subscenario_id,), many=False
    )

    # Stages
    # TODO: stage_name not currently included; decide whether to keep this
    #  column in the database and how to import data for it if we do want it
    stages_sql = """
        INSERT INTO inputs_temporal_subproblems_stages
        (temporal_scenario_id, subproblem_id, stage_id)
        SELECT DISTINCT temporal_scenario_id, subproblem_id, stage_id
        FROM inputs_temporal
        WHERE temporal_scenario_id = ?;
        """
    spin_on_database_lock(
        conn=conn, cursor=c, sql=stages_sql, data=(subscenario_id,), many=False
    )

    # ### Built-in horizons ### #
    boundaries = ["circular", "linear", "linked"]
    periods = [p[0] for p in c.execute(f"""SELECT DISTINCT period
        FROM inputs_temporal
        WHERE temporal_scenario_id = {subscenario_id}""").fetchall()]
    subproblem_stages = [
        subproblem_stage
        for subproblem_stage in c.execute(f"""SELECT DISTINCT subproblem_id, stage_id
        FROM inputs_temporal
        WHERE temporal_scenario_id = {subscenario_id}""").fetchall()
    ]
    subproblem_stage_periods = [
        subproblem_stage_period
        for subproblem_stage_period in c.execute(
            f"""SELECT DISTINCT subproblem_id, stage_id, period
        FROM inputs_temporal
        WHERE temporal_scenario_id = {subscenario_id}"""
        ).fetchall()
    ]

    # Insert into inputs_temporal_horizons
    for boundary in boundaries:
        # ### Insert into inputs_temporal_horizons ### #
        # Subproblem balancing type
        subproblem_balancing_type_sql = f"""
            INSERT INTO inputs_temporal_horizons
            (temporal_scenario_id, balancing_type_horizon, horizon, boundary)
            VALUES ({subscenario_id}, "subproblem_{boundary}", 1, '{boundary}')
            ;
            """
        c.execute(subproblem_balancing_type_sql, ())

        # Subproblem-period balancing type
        for period in periods:
            subproblem_period_balancing_type_sql = f"""
                INSERT INTO inputs_temporal_horizons
                (temporal_scenario_id, balancing_type_horizon, horizon, boundary)
                VALUES ({subscenario_id}, "subproblem_period_{boundary}", 
                {period}, '{boundary}')
                ;
                """
            c.execute(subproblem_period_balancing_type_sql, ())

        # ### Insert into inputs_temporal_horizon_timepoints_start_end ### #
        # Subproblem balancing type
        for subproblem_stage in subproblem_stages:
            subproblem, stage = subproblem_stage
            subproblem_tmp_start_end_sql = f"""
                INSERT INTO inputs_temporal_horizon_timepoints_start_end
                (temporal_scenario_id, stage_id, balancing_type_horizon, 
                horizon, tmp_start, tmp_start_spinup_or_lookahead, 
                tmp_end, tmp_end_spinup_or_lookahead)
                VALUES ({subscenario_id}, {stage}, 
                "subproblem_{boundary}", 1,
                (SELECT MIN(timepoint) FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}),
                (SELECT spinup_or_lookahead FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                ORDER BY timepoint ASC LIMIT 1),
                (SELECT MAX(timepoint) FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}),
                (SELECT spinup_or_lookahead FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                ORDER BY timepoint DESC LIMIT 1)
                )
                ;
                """

            c.execute(subproblem_tmp_start_end_sql, ())

        # Subproblem-period balancing type
        for subproblem, stage, period in subproblem_stage_periods:
            subproblem_period_tmp_start_end_sql = f"""
                INSERT INTO inputs_temporal_horizon_timepoints_start_end
                (temporal_scenario_id, stage_id, balancing_type_horizon, 
                horizon, tmp_start, tmp_start_spinup_or_lookahead, 
                tmp_end, tmp_end_spinup_or_lookahead)
                VALUES ({subscenario_id}, {stage}, 
                "subproblem_period_{boundary}", {period},
                (SELECT MIN(timepoint) FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                AND period = {period}),
                (SELECT spinup_or_lookahead FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                AND period = {period}
                ORDER BY timepoint ASC LIMIT 1),
                (SELECT MAX(timepoint) FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                AND period = {period}),
                (SELECT spinup_or_lookahead FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                AND period = {period}
                ORDER BY timepoint DESC LIMIT 1)
                )
                ;
                """

            c.execute(subproblem_period_tmp_start_end_sql, ())

    # Subproblem-period-month balancing type (linear and circular only, as
    # in the model): a horizon (period * 100 + month) holds the timepoints
    # with that period and month, so write its timepoints directly rather
    # than via a start/end timepoint range, which would assume a month's
    # timepoint IDs are contiguous
    for boundary in ["circular", "linear"]:
        month_horizons_sql = f"""
            INSERT INTO inputs_temporal_horizons
            (temporal_scenario_id, balancing_type_horizon, horizon, boundary)
            SELECT DISTINCT temporal_scenario_id,
                'subproblem_period_month_{boundary}', period * 100 + month,
                '{boundary}'
            FROM inputs_temporal
            WHERE temporal_scenario_id = ?
            AND month IS NOT NULL;
            """
        spin_on_database_lock(
            conn=conn,
            cursor=c,
            sql=month_horizons_sql,
            data=(subscenario_id,),
            many=False,
        )

        month_horizon_timepoints_sql = f"""
            INSERT INTO inputs_temporal_horizon_timepoints
            (temporal_scenario_id, subproblem_id, stage_id, timepoint,
            balancing_type_horizon, horizon)
            SELECT temporal_scenario_id, subproblem_id, stage_id, timepoint,
                'subproblem_period_month_{boundary}', period * 100 + month
            FROM inputs_temporal
            WHERE temporal_scenario_id = ?
            AND month IS NOT NULL;
            """
        spin_on_database_lock(
            conn=conn,
            cursor=c,
            sql=month_horizon_timepoints_sql,
            data=(subscenario_id,),
            many=False,
        )

    # Subproblem-period-day balancing type (linear and circular only, as in
    # the model): a horizon (period * 10000 + month * 100 + day_of_month)
    # holds the timepoints with that period, month, and day of month;
    # timepoints without a month or day of month are in no day horizon
    for boundary in ["circular", "linear"]:
        day_horizons_sql = f"""
            INSERT INTO inputs_temporal_horizons
            (temporal_scenario_id, balancing_type_horizon, horizon, boundary)
            SELECT DISTINCT temporal_scenario_id,
                'subproblem_period_day_{boundary}',
                period * 10000 + month * 100 + day_of_month, '{boundary}'
            FROM inputs_temporal
            WHERE temporal_scenario_id = ?
            AND month IS NOT NULL
            AND day_of_month IS NOT NULL;
            """
        spin_on_database_lock(
            conn=conn,
            cursor=c,
            sql=day_horizons_sql,
            data=(subscenario_id,),
            many=False,
        )

        day_horizon_timepoints_sql = f"""
            INSERT INTO inputs_temporal_horizon_timepoints
            (temporal_scenario_id, subproblem_id, stage_id, timepoint,
            balancing_type_horizon, horizon)
            SELECT temporal_scenario_id, subproblem_id, stage_id, timepoint,
                'subproblem_period_day_{boundary}',
                period * 10000 + month * 100 + day_of_month
            FROM inputs_temporal
            WHERE temporal_scenario_id = ?
            AND month IS NOT NULL
            AND day_of_month IS NOT NULL;
            """
        spin_on_database_lock(
            conn=conn,
            cursor=c,
            sql=day_horizon_timepoints_sql,
            data=(subscenario_id,),
            many=False,
        )

    # TIMEPOINT HORIZONS
    subproblem_stages = c.execute(f"""
        SELECT subproblem_id, stage_id
        FROM inputs_temporal_subproblems_stages
        WHERE temporal_scenario_id = {subscenario_id}
        """).fetchall()

    # For each subproblem-stage, figure out how the timepoints are organized
    # into horizons
    for subproblem, stage in subproblem_stages:
        # Find the relevant balancing_type-horizons for this subproblem, stage
        bt_hr_sql = f"""
            SELECT balancing_type_horizon, horizon, tmp_start, tmp_end
            FROM inputs_temporal_horizon_timepoints_start_end
            WHERE temporal_scenario_id = {subscenario_id}
            AND stage_id = {stage}
            AND (tmp_start, tmp_start_spinup_or_lookahead) in (
                SELECT timepoint, spinup_or_lookahead
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                )
            AND (tmp_end, tmp_end_spinup_or_lookahead) in (
                SELECT timepoint, spinup_or_lookahead
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                )
            ;
            """

        bt_hr = c.execute(bt_hr_sql, ()).fetchall()

        hor_tmps_tuples_list = list()

        for bt, hr, tmp_start, tmp_end in bt_hr:
            sid_tmps = [tmp[0] for tmp in c.execute(f"""
                SELECT timepoint
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenario_id}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                AND timepoint >= {tmp_start}
                AND timepoint <= {tmp_end}
                ;
                """).fetchall()]

            for tmp in sid_tmps:
                hor_tmps_tuples_list.append(
                    (subscenario_id, subproblem, stage, tmp, bt, hr)
                )

        horizon_timepoints_sql = """
            INSERT INTO inputs_temporal_horizon_timepoints
            (temporal_scenario_id, subproblem_id, stage_id, timepoint, 
            balancing_type_horizon, horizon)
            VALUES (?, ?, ?, ?, ?, ?);
            """

        spin_on_database_lock(
            conn=conn, cursor=c, sql=horizon_timepoints_sql, data=hor_tmps_tuples_list
        )
