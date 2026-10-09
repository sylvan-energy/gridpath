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
Month-of-year rows for horizon-indexed inputs.

The built-in month balancing types have one horizon per period and month
(horizon = period * 100 + month). On these balancing types, an input row
with horizon 1-12 (which can't be a real horizon) supplies the data for that
month of the year in every period without an explicit row for its own
horizon. The data key (the month) is kept separate from the constraint
horizon (the period's month), so horizon-level constraints never span
periods.

Month-of-year rows always rank just below the explicit rows. How they
combine with the explicit rows follows what a NULL means in the input's
table:

* where NULL cells already fall through to a default (the market volume
  profiles), the month-of-year row is one more layer of a per-column
  COALESCE (see :code:`month_of_year_join_sql`);
* where an explicit row is a complete record and a NULL cell may itself
  mean something (e.g. no limit in the hydro budget allocation inputs), the
  explicit row wins as a whole (see :code:`month_of_year_rows_sql`).

Each horizon's month is read from the timepoints' month column, not derived
from the horizon ID. This module imports nothing from the rest of GridPath,
so the temporal, project and system modules can all use it.
"""

# The built-in balancing types with one horizon per (period, month)
MONTH_HORIZON_TYPES = [
    "subproblem_period_month_circular",
    "subproblem_period_month_linear",
]

MONTH_HORIZON_TYPES_SQL = ", ".join(f"'{bt}'" for bt in MONTH_HORIZON_TYPES)


def month_of_year_row_sql(bt_column="balancing_type_horizon", horizon_column="horizon"):
    """
    :return: a SQL condition that is true for month-of-year rows (horizon
        1-12 on a built-in month balancing type)
    """
    return (
        f"{bt_column} IN ({MONTH_HORIZON_TYPES_SQL}) "
        f"AND {horizon_column} BETWEEN 1 AND 12"
    )


def bt_hrz_month_index_sql(
    temporal_scenario_id, subproblem, stage, month_horizons_only=False
):
    """
    :return: SQL selecting the (balancing_type_horizon, horizon)s of the
        subproblem and stage with each horizon's month as month_of_year: the
        month of its timepoints on the built-in month balancing types
        (one month per horizon, as the temporal loader writes them), NULL on
        the others. With *month_horizons_only*, only the month horizons are
        selected.
    """
    month_horizons_filter = (
        f"""AND hts.balancing_type_horizon IN ({MONTH_HORIZON_TYPES_SQL})
        AND t.month IS NOT NULL"""
        if month_horizons_only
        else ""
    )
    return f"""
        SELECT DISTINCT hts.balancing_type_horizon AS balancing_type_horizon,
            hts.horizon AS horizon,
            CASE WHEN hts.balancing_type_horizon IN ({MONTH_HORIZON_TYPES_SQL})
                THEN t.month END AS month_of_year
        FROM inputs_temporal_horizon_timepoints AS hts
        JOIN inputs_temporal AS t
            USING (temporal_scenario_id, subproblem_id, stage_id, timepoint)
        WHERE hts.temporal_scenario_id = {temporal_scenario_id}
        AND hts.subproblem_id = {subproblem}
        AND hts.stage_id = {stage}
        {month_horizons_filter}
        """


def month_of_year_join_sql(data_subquery, alias="month_of_year", index_alias="idx"):
    """
    Per-column precedence: LEFT JOIN the month-of-year rows of
    *data_subquery* (whose ``{wildcard_filter}`` placeholder is filled with
    the month-of-year row condition; it must select balancing_type_horizon
    and horizon) to an index from :code:`bt_hrz_month_index_sql` aliased
    *index_alias*, as *alias*; the caller COALESCEs *alias*'s columns below
    the explicit rows'.

    :return: the LEFT JOIN clause
    """
    return f"""
        LEFT OUTER JOIN (
            {data_subquery.format(wildcard_filter=month_of_year_row_sql())}
        ) AS {alias}
            ON {index_alias}.balancing_type_horizon = {alias}.balancing_type_horizon
            AND {index_alias}.month_of_year = {alias}.horizon"""


def month_of_year_rows_sql(
    table,
    bt_column,
    select_columns,
    row_filter,
    key_columns,
    explicit_filter="",
    month_index="month_of_year_index",
):
    """
    Row-level precedence: the month-of-year rows of *table* relabeled with
    each month horizon (as *bt_column*, horizon) that has no explicit row,
    to UNION ALL with the explicit rows.

    :param table: the input table
    :param bt_column: the table's balancing type column
    :param select_columns: the table's columns to select before the
        balancing type and horizon, and after them, as a (before, after)
        tuple of SQL strings
    :param row_filter: SQL condition on the table's rows (scenario,
        subscenario, iteration, stage filters)
    :param key_columns: the columns identifying a series of the table (e.g.
        project and its subscenario ID): an explicit row of the same series
        for the month horizon takes precedence
    :param explicit_filter: SQL conditions (starting with AND) on the
        explicit rows, aliased explicit, e.g. their iteration and stage
    :param month_index: the name of a CTE defined with
        :code:`month_of_year_index_cte_sql`
    :return: the SQL string
    """
    before, after = select_columns
    key_match = " AND ".join(f"explicit.{c} = {table}.{c}" for c in key_columns)
    return f"""
            SELECT {before}, moy.moy_bt AS {bt_column},
                moy.moy_horizon AS horizon, {after}
            FROM {month_index} AS moy
            CROSS JOIN {table}
                ON {table}.{bt_column} = moy.moy_bt
                AND {table}.horizon = moy.moy_month
            WHERE {row_filter}
            AND NOT EXISTS (
                SELECT 1 FROM {table} AS explicit
                WHERE {key_match}
                AND explicit.{bt_column} = moy.moy_bt
                AND explicit.horizon = moy.moy_horizon
                {explicit_filter}
            )
        """


def month_of_year_index_cte_sql(
    temporal_scenario_id, subproblem, stage, name="month_of_year_index"
):
    """
    :return: a CTE (to follow other CTEs, so starting with a comma) named
        *name* of the subproblem and stage's month horizons and their months
        for :code:`month_of_year_rows_sql`; its columns are prefixed (moy_bt,
        moy_horizon, moy_month) so they can't clash with the data columns
    """
    index_sql = bt_hrz_month_index_sql(
        temporal_scenario_id, subproblem, stage, month_horizons_only=True
    )
    return f""",
        {name} AS (
            SELECT balancing_type_horizon AS moy_bt, horizon AS moy_horizon,
                month_of_year AS moy_month
            FROM ({index_sql})
        )"""
