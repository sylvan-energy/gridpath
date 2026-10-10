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
Calendar rows (month-of-year and day-of-year rows) for horizon-indexed
inputs.

The built-in calendar balancing types have one horizon per period and month
(horizon = period * 100 + month) or per period and day (horizon = period *
10000 + month * 100 + day_of_month, i.e. YYYYMMDD when periods are calendar
years). On these balancing types, an input row whose horizon is a calendar
key -- the month (1-12) on the month types, month * 100 + day_of_month
(101-1231) on the day types -- supplies the data for that month or date in
every period without an explicit row for its own horizon. Calendar keys
can't be real horizons (or the horizon = 0 wildcards), and the data key is
kept separate from the constraint horizon, so horizon-level constraints
never span periods.

Calendar rows always rank just below the explicit rows. How they combine
with the explicit rows follows what a NULL means in the input's table:

* where NULL cells already fall through to a default (the market volume
  profiles), the calendar row is one more layer of a per-column COALESCE
  (see :code:`calendar_join_sql`);
* where an explicit row is a complete record and a NULL cell may itself
  mean something (e.g. no limit in the hydro budget allocation inputs), the
  explicit row wins as a whole (see :code:`calendar_rows_sql`).

Each horizon's calendar key is read from its timepoints' month and
day_of_month columns, not derived from the horizon ID.

Timepoint-indexed inputs can't have calendar rows the same way, as timepoint
IDs are arbitrary (a temporal scenario may number its timepoints 1-8760).
Instead, the built-in calendar-hour opchar timepoint map
(:code:`CALENDAR_HOUR_TIMEPOINT_MAP_ID`, selected through the opchar
``*_tmp_map_scenario_id`` columns) reads each timepoint's data at its
calendar hour, month * 10000 + day_of_month * 100 + hour_of_day (e.g. 60307
for hour 7 of 3 June), so one year of data serves every period of any
temporal scenario whose timepoints have those columns; see
:code:`calendar_hour_sql`.

This module imports nothing from the rest of GridPath, so the temporal,
project and system modules can all use it.
"""

# The built-in balancing types with one horizon per (period, month) and per
# (period, month, day of month)
MONTH_HORIZON_TYPES = [
    "subproblem_period_month_circular",
    "subproblem_period_month_linear",
]
DAY_HORIZON_TYPES = [
    "subproblem_period_day_circular",
    "subproblem_period_day_linear",
]

# The reserved opchar timepoint map ID of the built-in calendar-hour map; the
# database schema seeds it in subscenarios_project_opchar_timepoint_map
CALENDAR_HOUR_TIMEPOINT_MAP_ID = 0


def sql_list(values):
    return ", ".join(f"'{v}'" for v in values)


def calendar_row_sql(bt_column="balancing_type_horizon", horizon_column="horizon"):
    """
    :return: a SQL condition that is true for calendar rows: horizon 1-12 on
        a built-in month balancing type, or 101-1231 on a built-in day
        balancing type
    """
    return (
        f"(({bt_column} IN ({sql_list(MONTH_HORIZON_TYPES)}) "
        f"AND {horizon_column} BETWEEN 1 AND 12) "
        f"OR ({bt_column} IN ({sql_list(DAY_HORIZON_TYPES)}) "
        f"AND {horizon_column} BETWEEN 101 AND 1231))"
    )


def bt_hrz_calendar_index_sql(
    temporal_scenario_id, subproblem, stage, calendar_horizons_only=False
):
    """
    :return: SQL selecting the (balancing_type_horizon, horizon)s of the
        subproblem and stage with each horizon's calendar key as
        calendar_key: its timepoints' month on the built-in month balancing
        types, month * 100 + day_of_month on the built-in day balancing types
        (one key per horizon, as the temporal loader writes them), NULL on
        the others. With *calendar_horizons_only*, only the calendar
        horizons are selected.
    """
    calendar_horizons_filter = (
        f"""AND hts.balancing_type_horizon IN (
            {sql_list(MONTH_HORIZON_TYPES + DAY_HORIZON_TYPES)}
        )
        AND t.month IS NOT NULL"""
        if calendar_horizons_only
        else ""
    )
    return f"""
        SELECT DISTINCT hts.balancing_type_horizon AS balancing_type_horizon,
            hts.horizon AS horizon,
            CASE
                WHEN hts.balancing_type_horizon IN ({sql_list(MONTH_HORIZON_TYPES)})
                THEN t.month
                WHEN hts.balancing_type_horizon IN ({sql_list(DAY_HORIZON_TYPES)})
                THEN t.month * 100 + t.day_of_month
            END AS calendar_key
        FROM inputs_temporal_horizon_timepoints AS hts
        JOIN inputs_temporal AS t
            USING (temporal_scenario_id, subproblem_id, stage_id, timepoint)
        WHERE hts.temporal_scenario_id = {temporal_scenario_id}
        AND hts.subproblem_id = {subproblem}
        AND hts.stage_id = {stage}
        {calendar_horizons_filter}
        """


def calendar_join_sql(data_subquery, alias="calendar", index_alias="idx"):
    """
    Per-column precedence: LEFT JOIN the calendar rows of *data_subquery*
    (whose ``{wildcard_filter}`` placeholder is filled with the calendar row
    condition; it must select balancing_type_horizon and horizon) to an
    index from :code:`bt_hrz_calendar_index_sql` aliased *index_alias*, as
    *alias*; the caller COALESCEs *alias*'s columns below the explicit
    rows'.

    :return: the LEFT JOIN clause
    """
    return f"""
        LEFT OUTER JOIN (
            {data_subquery.format(wildcard_filter=calendar_row_sql())}
        ) AS {alias}
            ON {index_alias}.balancing_type_horizon = {alias}.balancing_type_horizon
            AND {index_alias}.calendar_key = {alias}.horizon"""


def calendar_rows_sql(
    table,
    bt_column,
    select_columns,
    row_filter,
    key_columns,
    explicit_filter="",
    calendar_index="calendar_index",
):
    """
    Row-level precedence: the calendar rows of *table* relabeled with each
    calendar horizon (as *bt_column*, horizon) that has no explicit row, to
    UNION ALL with the explicit rows.

    :param table: the input table
    :param bt_column: the table's balancing type column
    :param select_columns: the table's columns to select before the
        balancing type and horizon, and after them, as a (before, after)
        tuple of SQL strings
    :param row_filter: SQL condition on the table's rows (scenario,
        subscenario, iteration, stage filters)
    :param key_columns: the columns identifying a series of the table (e.g.
        project and its subscenario ID): an explicit row of the same series
        for the calendar horizon takes precedence
    :param explicit_filter: SQL conditions (starting with AND) on the
        explicit rows, aliased explicit, e.g. their iteration and stage
    :param calendar_index: the name of a CTE defined with
        :code:`calendar_index_cte_sql`
    :return: the SQL string
    """
    before, after = select_columns
    key_match = " AND ".join(f"explicit.{c} = {table}.{c}" for c in key_columns)
    return f"""
            SELECT {before}, cal.cal_bt AS {bt_column},
                cal.cal_horizon AS horizon, {after}
            FROM {calendar_index} AS cal
            CROSS JOIN {table}
                ON {table}.{bt_column} = cal.cal_bt
                AND {table}.horizon = cal.cal_key
            WHERE {row_filter}
            AND NOT EXISTS (
                SELECT 1 FROM {table} AS explicit
                WHERE {key_match}
                AND explicit.{bt_column} = cal.cal_bt
                AND explicit.horizon = cal.cal_horizon
                {explicit_filter}
            )
        """


def calendar_index_cte_sql(
    temporal_scenario_id, subproblem, stage, name="calendar_index", first=False
):
    """
    :return: a CTE named *name* of the subproblem and stage's calendar
        horizons and their calendar keys for :code:`calendar_rows_sql`,
        starting with WITH if *first*, else with a comma (to follow other
        CTEs); its columns are prefixed (cal_bt, cal_horizon, cal_key) so
        they can't clash with the data columns
    """
    index_sql = bt_hrz_calendar_index_sql(
        temporal_scenario_id, subproblem, stage, calendar_horizons_only=True
    )
    return f"""{"WITH" if first else ","}
        {name} AS (
            SELECT balancing_type_horizon AS cal_bt, horizon AS cal_horizon,
                calendar_key AS cal_key
            FROM ({index_sql})
        )"""


def calendar_hour_sql(alias="t"):
    """
    :return: SQL for the calendar hour, month * 10000 + day_of_month * 100 +
        hour_of_day, of the inputs_temporal rows aliased *alias*
    """
    return (
        f"{alias}.month * 10000 + {alias}.day_of_month * 100 "
        f"+ CAST({alias}.hour_of_day AS INTEGER)"
    )


def timepoints_without_calendar_hour_sql(temporal_scenario_id, subproblem, stage):
    """
    :return: SQL selecting the timepoints of the subproblem and stage
        without a calendar hour: with no month, day_of_month or hour_of_day,
        or with an hour_of_day that isn't a whole hour from 0 to 24 or a
        day_of_month that isn't 1-31
    """
    return f"""
        SELECT timepoint
        FROM inputs_temporal
        WHERE temporal_scenario_id = {temporal_scenario_id}
        AND subproblem_id = {subproblem}
        AND stage_id = {stage}
        AND (
            month IS NULL OR day_of_month IS NULL OR hour_of_day IS NULL
            OR day_of_month NOT BETWEEN 1 AND 31
            OR hour_of_day NOT BETWEEN 0 AND 24
            OR hour_of_day != CAST(hour_of_day AS INTEGER)
        )
        ORDER BY timepoint
        """
