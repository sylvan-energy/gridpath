# Copyright 2016-2025 Blue Marble Analytics LLC.
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
.. _monte-carlo-draw-profiles-section-ref:
Monte Carlo Weather Draw Profiles
*********************************

This module maps the abstract weather draws produced by the
``create_monte_carlo_weather_draws`` step onto real historical data for a single
timeseries (e.g., system load, a VER profile, or a thermal availability
profile). Each synthetic study year produced upstream is only a sequence of
weather *bins* (one bin per day), not actual data; this module turns each
abstract day into a concrete historical calendar day for the timeseries, and
optionally loads the raw timeseries data and its unit mapping into the database
first.

===========
Methodology
===========

For each synthetic day, the upstream draws (stored in
``aux_weather_iterations``) provide a ``month``, a ``day_type`` (1 for weekend,
0 for weekday), and a ``weather_day_bin``. This module looks up every historical
day that shares that same weather bin and month -- and, when
``consider_day_types`` is set, the same ``day_type`` -- restricted to the years
for which this timeseries actually has data, then randomly picks one of those
matching historical days and records its ``year`` / ``month`` /
``day_of_month`` against the synthetic day.

----------------------------
Matching historical days
----------------------------

The candidate pool for each synthetic day is built in ``build_options_cache``
(one query per unique ``(month, day_type, weather_bin)`` combination, cached to
avoid redundant queries):

    1. Candidate historical days are read from ``user_defined_weather_bins``,
       filtered to the synthetic day's ``month`` and ``weather_bin`` (for the
       active ``weather_bins_id``).
    2. The pool is restricted to the set of years for which this timeseries has
       data. That set is derived from the distinct ``year`` values in the
       timeseries' profiles table (e.g., ``raw_data_system_load``) for the
       ``unit`` records mapped to the timeseries in its units table (e.g.,
       ``user_defined_load_zone_units``).
    3. ``draw_conditions_batch`` selects uniformly at random one day from the
       resulting list and returns its ``(year, month, day_of_month)``, which is
       written back into per-timeseries columns
       (``<timeseries_name>_year`` / ``_month`` / ``_day_of_month``) on
       ``aux_weather_iterations``.

Edge case -- no data for a draw: a ``(month [, day_type], weather_bin)``
combination may have no matching historical day (e.g., that bin never occurred
in a year for which this timeseries has data). ``build_options_cache`` falls
back through progressively relaxed criteria so the day still gets a plausible
same-month source day, preserving the weather bin as far as possible: it relaxes
the day type first, then substitutes the *nearest available* bin in the month.
Only when the timeseries has no data for the month at all is the synthetic day
left unassigned (NULL source day). Every relaxed match and every unmatched draw
is reported at the end of the timeseries (unmatched draws raise a
``UserWarning``), so compromised coverage is never silent.

The actual hourly values for these source days are not assembled here; they are
pulled later, when the input CSVs are written. Because every timeseries is
matched against the *same* weather draws, all timeseries stay
weather-consistent with one another (the same bin is used on the same synthetic
day), while each pulls from a real historical day for which it has data.

------------------------------
The ``consider_day_types`` flag
------------------------------

When ``consider_day_types`` is truthy, the cache key and the candidate-day query
additionally filter on ``day_type``, so a weekend synthetic day draws only from
historical weekend days and a weekday from weekdays. When it is falsy, the
``day_type`` filter is dropped and candidates are drawn from any matching day
regardless of weekday/weekend. Run this module once per timeseries:
weather-driven renewables typically use ``consider_day_types 0`` (solar/wind
output does not depend on weekday vs. weekend), while load and imports use
``consider_day_types 1``.

------------------------
Reproducibility (seeding)
------------------------

By default no seed is set (``timeseries_iteration_draw_initial_seed`` defaults
to ``None``). When a timeseries is requested explicitly via ``--timeseries_name``
and no initial seed is given, the script emits a ``UserWarning`` that the draws
will not be reproducible. (When timeseries are instead loaded from
``user_defined_monte_carlo_timeseries``, each row supplies its own
``initial_seed`` and no such warning is emitted.) To make source-day selection
reproducible, pass ``--timeseries_iteration_draw_initial_seed <int>``.

The RNG is re-seeded before *every single day's draw*: ``draw_conditions_batch``
calls ``np.random.seed(seed=...)`` immediately before each selection, and
``make_timeseries_draw_profiles`` increments the seed by 1 after each draw. The
draw sequence therefore starts from the initial seed and steps through
``seed``, ``seed + 1``, ``seed + 2``, ... Re-seeding with a different value per
draw (rather than one fixed seed for all draws) keeps each day's selection
independent, while re-running with the same initial seed reproduces the exact
same set of source days. When running once per timeseries, give each timeseries
its own initial seed so their selections do not correlate. Use seeding with
caution.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_monte_carlo_weather_draw_profiles --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes that the **create_monte_carlo_weather_draws** step has
been run and the following raw input database tables have been populated:
    * user_defined_monte_carlo_timeseries

=========
Settings
=========
    * database
    * weather_bins_id
    * weather_draws_id
    * study_year
    * timeseries_iteration_draw_initial_seed

"""

import sys
import warnings
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser

import numpy as np

from data_toolkit.load_raw_data import read_and_import_csv
from db.common_functions import spin_on_database_lock_generic, connect_to_database

TIMESERIES_TYPE = {
    "load": {
        "profiles_table": "raw_data_system_load",
        "units_table": "user_defined_load_zone_units",
    },
    "var_profiles": {
        "profiles_table": "raw_data_var_profiles",
        "units_table": "raw_data_var_project_units",
    },
    "availability": {
        "profiles_table": "raw_data_availability_profiles",
        "units_table": "raw_data_unit_availability_params",
    },
}


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database")

    parser.add_argument(
        "-rd_csv",
        "--raw_data_input_csv",
        default=None,
        help="""Path to the CSV file to load into the 
        raw data table for the timeseries. If not specified, data will be 
        assumed to 
        have been already loaded into the database.""",
    )
    parser.add_argument(
        "-u_csv",
        "--units_input_csv",
        default=None,
        help="""Path to the unit CSV file to load into the 
        units table for the timeseries. If not specified, data will be 
        assumed to have been already loaded into the database.""",
    )
    parser.add_argument(
        "-ts_csv",
        "--timeseries_input_csv",
        default=None,
        help="""Path to the timeseries CSV file to load. If not specified, 
        data will be assumed to have been already loaded into the database.""",
    )
    parser.add_argument(
        "-t",
        "--timeseries_name",
        default=None,
        help="Timeseries names to draw from. If not specified, a list of "
        "timeseries will be loaded from the database.",
    )
    parser.add_argument(
        "-d",
        "--consider_day_types",
        default=None,
        type=int,
        help="Required boolean if timeseries_name is specified. Use 1 for "
        "'yes' and 0 for 'no'. NOTE: parsed as an int -- passing the string "
        "'0' without int parsing would be truthy and silently enable day-type "
        "matching.",
    )
    parser.add_argument(
        "-ts_type",
        "--timeseries_type",
        default=None,
        choices=list(TIMESERIES_TYPE.keys()),
        help="Required boolean if timeseries_name is specified or to load "
        "data intputs.",
    )

    parser.add_argument(
        "-bins_id", "--weather_bins_id", default=1, help="Defaults to 1."
    )
    parser.add_argument(
        "-draws_id",
        "--weather_draws_id",
        default=1,
        help="Defaults to 1.",
    )
    parser.add_argument("-yr", "--study_year")
    parser.add_argument(
        "-it_seed",
        "--timeseries_iteration_draw_initial_seed",
        default=None,
        help="Defaults to None (no seeding). WARNING: Proceed with caution if "
        "you set a seed and make sure you understand what this script "
        "does with it.",
    )
    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def make_timeseries_draw_profiles(
    conn,
    timeseries_name,
    consider_day_types,
    timeseries_type,
    timeseries_iteration_draw_initial_seed,
    weather_bins_id,
    weather_draws_id,
    quiet,
):
    """
    Draw from the timeseries raw data to create synthetic weather iteration
    profiles based on particular weather draws.
    """

    if not quiet:
        print("   ...creating synthetic iterations...")

    # Get the timeseries
    if timeseries_name is None:
        c = conn.cursor()
        timeseries = [
            (timeseries_name, consider_day_types, timeseries_type, initial_seed)
            for (
                timeseries_name,
                consider_day_types,
                timeseries_type,
                initial_seed,
            ) in c.execute(
                f"""SELECT timeseries_name, consider_day_types,
                timeseries_type, initial_seed
                FROM user_defined_monte_carlo_timeseries
                ;"""
            ).fetchall()
        ]
    else:
        timeseries = [
            (
                timeseries_name,
                consider_day_types,
                timeseries_type,
                timeseries_iteration_draw_initial_seed,
            )
        ]

    # Get the weather draws
    weather_draws = get_weather_draws(
        conn=conn,
        weather_bins_id=weather_bins_id,
        weather_draws_id=weather_draws_id,
    )

    # Iterate over timeseries
    for (
        timeseries_name,
        consider_day_types,
        timeseries_type,
        timeseries_iteration_draw_initial_seed,
    ) in timeseries:
        if not timeseries_type in TIMESERIES_TYPE.keys():
            raise ValueError(
                f"Invalid draw profile type: {timeseries_type}. "
                f"Valid options are:"
                f" {list(TIMESERIES_TYPE.keys())}."
            )

        if not quiet:
            print(f"      ...processing timeseries: {timeseries_name}")

        # Set a starting seed if requested
        timeseries_iteration_draw_seed = (
            int(timeseries_iteration_draw_initial_seed)
            if timeseries_iteration_draw_initial_seed is not None
            else None
        )

        # Base availability on the data in the raw_data_var_profiles table
        # rather than exogenously defined by user
        # TODO: add option to exogenously define
        # WHERE
        # year in (
        #     SELECT year
        # FROM user_defined_data_availability
        # WHERE timeseries_name = '{timeseries_name}'
        # )

        data_av_c = conn.cursor()
        data_availability_list = [str(i[0]) for i in data_av_c.execute(f"""
                    SELECT DISTINCT year
                    FROM {TIMESERIES_TYPE[timeseries_type]["profiles_table"]}
                    WHERE unit in (
                    SELECT unit
                    FROM {TIMESERIES_TYPE[timeseries_type]["units_table"]}
                    WHERE timeseries_name = '{timeseries_name}'
                    );""")]
        data_av_c.close()

        # Bail out with a clear message if no data years were found for this
        # timeseries. Otherwise data_availability_string would be empty and the
        # candidate-day query below would build an invalid "year IN ()" clause.
        if not data_availability_list:
            raise ValueError(
                f"No data years found for timeseries '{timeseries_name}' "
                f"(type '{timeseries_type}'). Check that "
                f"{TIMESERIES_TYPE[timeseries_type]['profiles_table']} and "
                f"{TIMESERIES_TYPE[timeseries_type]['units_table']} are "
                f"populated and that the unit mapping references this "
                f"timeseries."
            )
        data_availability_string = ", ".join(data_availability_list)

        # Add the necessary columns
        columns_to_add = [
            f"{timeseries_name}_year",
            f"{timeseries_name}_month",
            f"{timeseries_name}_day_of_month",
        ]

        c = conn.cursor()
        # Only add columns that don't already exist. SQLite has no
        # "ADD COLUMN IF NOT EXISTS", so re-running this step for a timeseries
        # whose columns are already present would otherwise raise a
        # "duplicate column name" error.
        existing_columns = {
            row[1]
            for row in c.execute(
                "PRAGMA table_info(aux_weather_iterations);"
            ).fetchall()
        }
        for column in columns_to_add:
            if column in existing_columns:
                if not quiet:
                    warnings.warn(
                        f"Column {column }already exists. Is this "
                        f"expected? Skipping column addition."
                    )
                continue
            sql = f"""
                    ALTER TABLE aux_weather_iterations
                    ADD COLUMN {column} INTEGER
                    ;
                """
            spin_on_database_lock_generic(c.execute(sql))

        # Build cache of options by (month, day_type, weather_bin)
        if not quiet:
            print(f"         ...building options cache...")

        options_cache = build_options_cache(
            conn=conn,
            weather_draws=weather_draws,
            consider_day_types=consider_day_types,
            weather_bins_id=weather_bins_id,
            data_availability_string=data_availability_string,
        )

        # Collect all updates in batch
        if not quiet:
            print(f"         ...generating draws...")

        batch_updates = []
        prev_weather_iteration = None

        # Track edge cases for reporting: draws that needed relaxed (fallback)
        # matching, and draws that could not be matched to any historical day.
        fallback_counts = {"dropped_day_type": 0, "nearest_bin": 0}
        fallback_keys = {"dropped_day_type": set(), "nearest_bin": set()}
        unmatched_draws = 0
        unmatched_keys = set()

        for (
            weather_iteration,
            draw_number,
            month,
            day_type,
            weather_bin,
        ) in weather_draws:
            if (
                prev_weather_iteration is not None
                and prev_weather_iteration != weather_iteration
                and weather_iteration % 10 == 0
            ):
                if not quiet:
                    print(f"         ...weather iteration {weather_iteration}")
            prev_weather_iteration = weather_iteration

            # Get cached options for this (month, day_type, weather_bin)
            cache_key = (month, day_type if consider_day_types else None, weather_bin)
            cache_entry = options_cache.get(
                cache_key, {"options": [], "fallback": "none"}
            )
            options_list = cache_entry["options"]

            # Edge case: no historical day matched even after relaxing the day
            # type and weather bin (the timeseries has no data for this month at
            # all in its data-availability years). Leave the synthetic day
            # unassigned and record it for the warning emitted below.
            if not options_list:
                unmatched_draws += 1
                unmatched_keys.add(cache_key)
                continue

            # Record any relaxed (fallback) match for the summary below.
            if cache_entry["fallback"] in fallback_counts:
                fallback_counts[cache_entry["fallback"]] += 1
                fallback_keys[cache_entry["fallback"]].add(cache_key)

            # Draw the conditions
            year, month_out, day_of_month = draw_conditions_batch(
                options_list=options_list,
                timeseries_iteration_draw_seed=timeseries_iteration_draw_seed,
            )

            # Add to batch
            batch_updates.append(
                (
                    year,
                    month_out,
                    day_of_month,
                    weather_draws_id,
                    weather_iteration,
                    draw_number,
                )
            )

            if timeseries_iteration_draw_seed is not None:
                # TODO: instead of incrementing seed, possibly set seeds via CSV
                #  data input for easier reproducibility
                timeseries_iteration_draw_seed += 1

        # ### Report edge cases for this timeseries ### #
        # Draws that used relaxed matching: surface them so the user knows the
        # synthetic series is not a perfect (month, day_type, weather_bin) match
        # everywhere.
        total_fallback = sum(fallback_counts.values())
        if total_fallback and not quiet:
            # Warn so relaxed matching is not silent (suppressed in quiet mode).
            warnings.warn(
                f"{total_fallback} draw(s) for timeseries '{timeseries_name}' "
                f"had no exact (month, "
                f"{'day_type, ' if consider_day_types else ''}weather_bin) "
                f"match and were assigned a historical day using relaxed "
                f"criteria ({fallback_counts['dropped_day_type']} with the day "
                f"type ignored, {fallback_counts['nearest_bin']} using the "
                f"nearest available weather bin). The synthetic series is "
                f"therefore not an exact weather match on those days."
            )
            print(
                f"         ...note: {total_fallback} draw(s) for "
                f"'{timeseries_name}' had no exact match and used relaxed "
                f"criteria:"
            )
            if fallback_counts["dropped_day_type"]:
                print(
                    f"            - same weather bin, day type ignored: "
                    f"{fallback_counts['dropped_day_type']} draw(s); "
                    f"(month, day_type, weather_bin): "
                    f"{sorted(fallback_keys['dropped_day_type'])}"
                )
            if fallback_counts["nearest_bin"]:
                print(
                    f"            - nearest available weather bin substituted: "
                    f"{fallback_counts['nearest_bin']} draw(s); "
                    f"(month, day_type, weather_bin): "
                    f"{sorted(fallback_keys['nearest_bin'])}"
                )
        # Draws that could not be matched at all: warn (suppressed in quiet
        # mode), since these synthetic days are left with a NULL source day.
        if unmatched_draws and not quiet:
            warnings.warn(
                f"{unmatched_draws} draw(s) for timeseries '{timeseries_name}' "
                f"could not be matched to any historical day -- the timeseries "
                f"has no data for these months in its data-availability years. "
                f"These synthetic days were left unassigned (NULL source day). "
                f"Affected (month, day_type, weather_bin) combinations: "
                f"{sorted(unmatched_keys)}."
            )

        # Execute batch update
        if not quiet:
            print(f"         ...executing batch update ({len(batch_updates)} rows)...")

        execute_batch_update(
            conn=conn,
            timeseries_name=timeseries_name,
            batch_updates=batch_updates,
            weather_draws_id=weather_draws_id,
        )


def get_weather_draws(conn, weather_bins_id, weather_draws_id):
    c = conn.cursor()
    draws = c.execute(f"""
        SELECT weather_iteration, draw_number, month, day_type, weather_day_bin
        FROM aux_weather_iterations
        WHERE weather_bins_id = {weather_bins_id}
        AND weather_draws_id = {weather_draws_id}
    """).fetchall()

    return draws


def build_options_cache(
    conn,
    weather_draws,
    consider_day_types,
    weather_bins_id,
    data_availability_string,
):
    """
    Build a cache of candidate historical days for each unique
    ``(month, day_type, weather_bin)`` combination that appears in the weather
    draws. Querying once per unique combination avoids redundant queries.

    Edge case -- no data for a draw: a ``(month [, day_type], weather_bin)``
    combination can have no candidate historical day -- for example when that
    weather bin never occurred in a year for which this timeseries has data.
    Rather than silently leaving the synthetic day unassigned, we fall back
    through progressively relaxed criteria so the day still receives a plausible
    same-month source day. The weather bin is a severity signal and is preserved
    as far as possible: the day type is relaxed first, then the bin is relaxed
    to the *nearest available* bin in the month (ties broken toward the lower
    bin).

    Returns a dict mapping ``cache_key`` ->
    ``{"options": [...], "fallback": <level>}``, where ``<level>`` is one of:

        * ``"exact"``            -- matched month (+ day_type) + weather_bin
        * ``"dropped_day_type"`` -- matched month + weather_bin, day type ignored
        * ``"nearest_bin"``      -- matched month (+ day_type), nearest available
                                    bin substituted for the requested one
        * ``"none"``             -- no historical day for the month at all in the
                                    timeseries' data-availability years (the
                                    ``options`` list is empty)
    """
    c = conn.cursor()

    def query_days(month, day_type, weather_bin):
        """Historical (year, month, day_of_month) matching the given filters.

        ``day_type`` and/or ``weather_bin`` of ``None`` drop that filter.
        """
        filters = [
            f"month = {month}",
            f"weather_bins_id = {weather_bins_id}",
            f"year in ({data_availability_string})",
        ]
        if day_type is not None:
            filters.append(f"day_type = {day_type}")
        if weather_bin is not None:
            filters.append(f"weather_bin = {weather_bin}")
        sql = f"""
            SELECT year, month, day_of_month
            FROM user_defined_weather_bins
            WHERE {" AND ".join(filters)}
            ORDER BY year, month, day_of_month
        ;
        """
        return c.execute(sql).fetchall()

    def available_bins(month, day_type):
        """Distinct weather bins present in the month (within data years)."""
        filters = [
            f"month = {month}",
            f"weather_bins_id = {weather_bins_id}",
            f"year in ({data_availability_string})",
        ]
        if day_type is not None:
            filters.append(f"day_type = {day_type}")
        sql = f"""
            SELECT DISTINCT weather_bin
            FROM user_defined_weather_bins
            WHERE {" AND ".join(filters)}
        ;
        """
        return sorted(row[0] for row in c.execute(sql).fetchall())

    cache = {}
    unique_keys = set()
    for _, _, month, day_type, weather_bin in weather_draws:
        cache_key = (month, day_type if consider_day_types else None, weather_bin)
        unique_keys.add(cache_key)

    for cache_key in unique_keys:
        month, day_type, weather_bin = cache_key

        # 1. Exact match: month (+ day_type) + weather_bin.
        options = query_days(month, day_type, weather_bin)
        fallback = "exact"

        # 2. Relax the day type but keep the weather bin.
        if not options and day_type is not None:
            options = query_days(month, None, weather_bin)
            if options:
                fallback = "dropped_day_type"

        # 3. Relax the bin to the nearest available bin in the month, preferring
        #    the same day type and then any day type.
        if not options:
            for dt in ([day_type, None] if day_type is not None else [None]):
                bins = available_bins(month, dt)
                if not bins:
                    continue
                nearest = min(bins, key=lambda b: (abs(b - weather_bin), b))
                options = query_days(month, dt, nearest)
                if options:
                    fallback = "nearest_bin"
                    break

        if not options:
            fallback = "none"

        cache[cache_key] = {"options": options, "fallback": fallback}

    c.close()
    return cache


def draw_conditions_batch(
    options_list,
    timeseries_iteration_draw_seed,
):
    """
    Draw random conditions from the options list.
    Returns (year, month, day_of_month) tuple.
    """
    np.random.seed(seed=timeseries_iteration_draw_seed)

    # Randomly select from list
    year, month, day_of_month = options_list[np.random.randint(len(options_list))]

    return year, month, day_of_month


def execute_batch_update(
    conn,
    timeseries_name,
    batch_updates,
    weather_draws_id,
):
    """
    Execute batch update using executemany for better performance.
    """
    if not batch_updates:
        return

    c = conn.cursor()

    # Use executemany for bulk updates
    update_sql = f"""
        UPDATE aux_weather_iterations
        SET {timeseries_name}_year = ?,
            {timeseries_name}_month = ?,
            {timeseries_name}_day_of_month = ?
        WHERE weather_draws_id = ?
        AND weather_iteration = ?
        AND draw_number = ?
    """

    spin_on_database_lock_generic(c.executemany(update_sql, batch_updates))
    conn.commit()
    c.close()


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating Monte Carlo weather draw profiles...")

    conn = connect_to_database(db_path=parsed_args.database)

    # ##### Load raw data if requested #####
    # ### Load data from CSVs
    if parsed_args.timeseries_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.timeseries_input_csv,
            table="user_defined_monte_carlo_timeseries",
        )

    if (
        parsed_args.raw_data_input_csv is not None
        or parsed_args.units_input_csv is not None
    ):
        if parsed_args.timeseries_type is None:
            raise ValueError(
                "Timeseries type must be specified to load "
                "data into the correct table."
            )
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.raw_data_input_csv,
            table=TIMESERIES_TYPE[parsed_args.timeseries_type]["profiles_table"],
        )
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.units_input_csv,
            table=TIMESERIES_TYPE[parsed_args.timeseries_type]["units_table"],
        )

    # #### Check if specific timeseries is requested #### #
    if parsed_args.timeseries_name is not None:
        if parsed_args.consider_day_types is None:
            raise ValueError(
                "The consider_day_types must be specified if "
                "timeseries_name is specified."
            )
        if parsed_args.timeseries_type is None:
            raise ValueError(
                "The timeseries_type must be specified if "
                "timeseries_name is specified."
            )

        if parsed_args.timeseries_iteration_draw_initial_seed is None:
            warnings.warn(
                "Timeseries iteration draw initial seed is not "
                "specified. The draws will not be reproducible."
            )
        else:
            if not parsed_args.quiet:
                print(
                    f"Timeseries iteration draw initial seed is {parsed_args.timeseries_iteration_draw_initial_seed}."
                )

    # ####### Based on the weather draws, create timeseries profiles ###########
    make_timeseries_draw_profiles(
        conn=conn,
        timeseries_name=parsed_args.timeseries_name,
        consider_day_types=parsed_args.consider_day_types,
        timeseries_type=parsed_args.timeseries_type,
        timeseries_iteration_draw_initial_seed=parsed_args.timeseries_iteration_draw_initial_seed,
        weather_bins_id=parsed_args.weather_bins_id,
        weather_draws_id=parsed_args.weather_draws_id,
        quiet=parsed_args.quiet,
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
