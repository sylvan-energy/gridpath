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
Period wildcard rows for period-indexed inputs.

In the period-indexed inputs that support it, a row with ``period = 0``
gives the data for every period of the subproblem without an explicit row
for that period, so data that doesn't change across periods needs one row
instead of one per period, and periods that differ need rows only for
themselves. The rows are resolved when the model inputs are written
(:code:`period_wildcard_rows_sql`), so the input files written from the
database carry real periods only; input files written by other means may
still contain period 0 rows, which the model data loaders resolve the same
way (:code:`expand_period_wildcard_rows`).

An explicit period's rows take precedence over the wildcard rows as a whole:
for inputs with several rows per period (e.g. the load points of a heat rate
curve), a period with any explicit row reads only its explicit rows. (The
market volume period profiles, whose NULL cells fall through to the next
layer, resolve their wildcard rows per column instead; see
:code:`gridpath.system.markets.volume`.)

This module imports nothing from the rest of GridPath, so any module can
use it.
"""

import pandas as pd


def subproblem_periods_sql(temporal_scenario_id, subproblem):
    """
    :return: SQL selecting the periods (as period) of the subproblem
    """
    return f"""
        SELECT DISTINCT period
        FROM inputs_temporal
        WHERE temporal_scenario_id = {temporal_scenario_id}
        AND subproblem_id = {subproblem}
        """


def temporal_periods_sql(temporal_scenario_id):
    """
    :return: SQL selecting the periods (as period) of the temporal scenario
    """
    return f"""
        SELECT period
        FROM inputs_temporal_periods
        WHERE temporal_scenario_id = {temporal_scenario_id}
        """


def period_wildcard_rows_sql(table, columns, key_columns, row_filter, periods_sql):
    """
    :param table: the input table
    :param columns: the table's columns to select, in order, including
        period
    :param key_columns: the columns identifying a series of the table (e.g.
        project and its subscenario ID); a period with an explicit row of the
        series doesn't read the series' wildcard rows
    :param row_filter: SQL condition on the table's rows selecting the
        series that apply (e.g. the portfolio projects with their
        subscenario IDs); it must not reference period
    :param periods_sql: SQL selecting the periods (as period) to resolve the
        rows for, e.g. from :code:`subproblem_periods_sql`
    :return: SQL selecting *columns* for the explicit rows of the periods in
        *periods_sql*, and the wildcard (period 0) rows relabeled with each
        of those periods that has no explicit row of the same series,
        ordered by *key_columns*, period, and the other columns
    """
    explicit_columns = ", ".join(f"{table}.{c} AS {c}" for c in columns)
    wildcard_columns = ", ".join(
        (
            "wildcard_periods.wildcard_period AS period"
            if c == "period"
            else f"{table}.{c} AS {c}"
        )
        for c in columns
    )
    key_match = " AND ".join(f"explicit.{c} = {table}.{c}" for c in key_columns)
    # Deterministic output: by series, period, then the remaining columns
    # (e.g. the load points of a curve)
    order_by = ", ".join(
        [c for c in key_columns if c in columns]
        + ["period"]
        + [c for c in columns if c not in key_columns and c != "period"]
    )
    return f"""
        SELECT * FROM (
            SELECT {explicit_columns}
            FROM {table}
            WHERE {row_filter}
            AND {table}.period IN ({periods_sql})
            UNION ALL
            SELECT {wildcard_columns}
            FROM {table}
            CROSS JOIN (
                SELECT period AS wildcard_period FROM ({periods_sql})
            ) AS wildcard_periods
            WHERE {row_filter}
            AND {table}.period = 0
            AND NOT EXISTS (
                SELECT 1 FROM {table} AS explicit
                WHERE {key_match}
                AND explicit.period = wildcard_periods.wildcard_period
            )
        )
        ORDER BY {order_by}
        """


def redundant_period_wildcards_sql(table, key_columns, row_filter, periods_sql):
    """
    :return: SQL selecting the series (*key_columns*) of *table* matching
        *row_filter* that have wildcard (period 0) rows and explicit rows
        for every period in *periods_sql*, so that their wildcard rows apply
        to no period
    """
    key_select = ", ".join(key_columns)
    key_match = " AND ".join(f"explicit.{c} = {table}.{c}" for c in key_columns)
    return f"""
        SELECT DISTINCT {key_select}
        FROM {table}
        WHERE {row_filter}
        AND period = 0
        AND NOT EXISTS (
            SELECT 1 FROM ({periods_sql}) AS model_periods
            WHERE NOT EXISTS (
                SELECT 1 FROM {table} AS explicit
                WHERE {key_match}
                AND explicit.period = model_periods.period
            )
        )
        """


def expand_period_wildcard_rows(df, key_columns, periods):
    """
    The same resolution for an input file's rows: replace the period 0 rows
    of *df* with a copy for each of *periods* that has no explicit row of the
    same series (*key_columns*); explicit rows are kept as they are.

    :param df: DataFrame with a period column and *key_columns*
    :param key_columns: the columns identifying a series
    :param periods: the modeling periods
    :return: the DataFrame with the wildcard rows resolved
    """
    is_wildcard = df["period"] == 0
    if not is_wildcard.any():
        return df
    explicit = df[~is_wildcard]
    wildcard = df[is_wildcard]
    explicit_keys = set(
        explicit[key_columns + ["period"]].itertuples(index=False, name=None)
    )
    expanded = pd.concat(
        [wildcard.assign(period=period) for period in sorted(periods)]
        or [wildcard.iloc[0:0]]
    )
    keep = [
        key not in explicit_keys
        for key in expanded[key_columns + ["period"]].itertuples(index=False, name=None)
    ]
    return pd.concat([explicit, expanded[keep]], ignore_index=True)
