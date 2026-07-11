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
#
# create_weather_draws() function
# Copyright 2023 Moment Energy Insights LLC. Licensed under the Apache
# License, Version 2.0.
# Modifications Copyright 2024 Blue Marble Analytics LLC. Licensed under the
# Apache License, Version 2.0.

"""
.. _monte-carlo-draws-section-ref:

Monte Carlo Weather Iteration Draws
***********************************

The Monte Carlo approach employed in the GridPath RA Toolkit study synthesizes
multiple years of plausible hourly load, wind availability, solar availability,
and temperature-driven thermal derate data over which the system operations can
be simulated. Synthetic days are built by combining load, wind, solar, and
temperature derate shapes from different but similar days in the historical
record. For a detailed description of the methodology, see Appendix B of the
report available at
https://gridlab.org/wp-content/uploads/2022/10/GridLab_RA-Toolkit-Report-10-12-22.pdf.

===========
Methodology
===========

This module produces, for each Monte Carlo iteration, a full synthetic
study-year sequence of *weather day bins*. A weather day bin is a categorical
label (e.g., one of five quintiles per month/day_type) that indicates the
historical day's weather (e.g., based on maximum or average temperature). The
bins themselves are produced upstream by the user and are stored in
``user_defined_weather_bins``; this module only resamples them into
new synthetic chronologies. The downstream
``create_monte_carlo_weather_draw_profiles`` step then maps each drawn bin to
an actual historical day's load/wind/solar/derate shapes.

----------------------------
First-order Markov bin chain
----------------------------

The synthetic bin sequence is generated as a *first-order Markov chain* over
the historical record, in order to preserve realistic day-to-day persistence
of weather (e.g., heat waves and cold snaps span multiple days):

    1. The first day of the year (Jan 1) is seeded by drawing uniformly at
       random from all historical January bins (see ``starting_weather_bin``).
    2. For each subsequent calendar day, given the *prior* day's bin ``b``, we
       look across the historical record for every day in the *current month*
       whose bin equals ``b``, take the bin of the day that *immediately
       followed* each such day, and draw uniformly at random from that set of
       "following-day" bins. That draw becomes the current day's bin and the
       prior bin for the next step. In effect, step 2 samples from the
       empirically estimated transition probability ``P(bin_today |
       bin_yesterday)`` for the relevant month.

-------------------------
Reproducibility (seeding)
-------------------------

By default no seed is set (``weather_draws_seed`` defaults to ``None``), so each
run produces a different random ensemble of synthetic weather years. To get
reproducible draws, pass ``--weather_draws_seed <int>``. The seed actually used
is recorded in ``aux_weather_draws_info`` alongside the draws.

------------------------
Other notes
------------------------
Modeled distributions may deviate from historical averages depending on
within-month weather drift. In shoulder seasons, day-to-day directional trends
can cause modeled averages to deviate from historical means by ~1–3% (skewing
lower in warming months and higher in cooling months).


=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_monte_carlo_weather_draws --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * user_defined_weather_bins

=========
Settings
=========
    * database
    * weather_bins_id
    * weather_draws_id
    * weather_draws_seed
    * n_iterations
    * study_year
    * timeseries_iteration_draw_initial_seed

"""

import sys
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import calendar
import datetime


import numpy as np
import pandas as pd

from db.common_functions import spin_on_database_lock_generic, connect_to_database
from data_toolkit.load_raw_data import read_and_import_csv


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
        "-csv",
        "--input_csv",
        default=None,
        help="""This is the path to the CSV file containing the 
                        weather bins. If not specified, the weather bins will be 
                        assumed to have been already loaded into the 
                        database.""",
    ),
    parser.add_argument(
        "-bins_id", "--weather_bins_id", default=1, help="Defaults to 1."
    )
    parser.add_argument(
        "-wd_seed",
        "--weather_draws_seed",
        default=None,
        help="Defaults to None (no seeding). WARNING: Proceed with caution if "
        "you set a seed and make sure you understand what this script "
        "does with it.",
    )
    parser.add_argument(
        "-draws_id",
        "--weather_draws_id",
        default=1,
        help="Defaults to 1.",
    )
    parser.add_argument("-n_iter", "--n_iterations")
    parser.add_argument("-yr", "--study_year")
    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def create_weather_draws(
    conn,
    weather_bins_id,
    weather_draws_seed,
    n_iterations,
    weather_draws_id,
    study_year,
    quiet,
):
    """
    Load in weather bin info
    Create synthetic weather years for the study year
    """
    if not quiet:
        print("...drawing weather...")
    # Get the weather bins
    weather_bins_sql = f"""
        SELECT year, month, day_of_month, day_type, weather_bin
        FROM user_defined_weather_bins
        WHERE weather_bins_id = {weather_bins_id}
        ORDER BY year, month, day_of_month
        """
    weather_bins = pd.read_sql(sql=weather_bins_sql, con=conn)

    # Study-year-based params
    starting_date = np.datetime64(str(study_year) + "-01-01")  # Jan 1
    days_per_iteration = 365 + calendar.isleap(study_year)

    # Create the list for the data, seed, and start the iterations
    data = []
    np.random.seed(seed=weather_draws_seed)
    for iteration in range(1, n_iterations + 1):
        # ### Starting conditions ### #
        # Start on January 1; note this can be made flexible
        draw_number = 1
        current_date = starting_date
        # Day type of the recorded calendar date (1 if weekend, 0 if weekday).
        # Used only for the stored day_type column / downstream profile draws,
        # NOT to condition the weather-bin draw.
        current_day_type_bool = (
            current_date.astype(datetime.datetime).isoweekday() > 5
        ) * 1
        # Find the weather conditions on all January weather days
        starting_weather_bin_options = weather_bins[weather_bins["month"] == 1][
            "weather_bin"
        ].to_numpy()
        # Randomly draw from those weather conditions for the first day of the
        # year
        starting_weather_bin = starting_weather_bin_options[
            np.random.randint(len(starting_weather_bin_options))
        ]

        data.append(
            (
                weather_bins_id,
                weather_draws_id,
                iteration,
                draw_number,
                str(current_date),
                current_date.astype(object).month,
                current_day_type_bool,
                int(starting_weather_bin),
            )
        )

        # ### Loop through the rest of the study year days ### #
        prior_weather_bin = starting_weather_bin
        total_days_in_iteration = days_per_iteration

        for day_of_iteration in range(2, total_days_in_iteration + 1):
            draw_number += 1
            current_date += np.timedelta64(1, "D")

            # Determine the month and day_type/weekday type
            current_month = current_date.astype(object).month
            # determine the day type (1 if day_type, 0 if weekday, must match
            # day-type bin convention)
            current_day_type_bool = (
                current_date.astype(datetime.datetime).isoweekday() > 5
            ) * 1

            # Get the weather bins (and aligned years) across all days in the
            # month, in chronological order. Note: the weather-bin draw is
            # intentionally NOT conditioned on day type -- the bin reflects
            # weather severity, which is day-type-agnostic. Day-type matching is
            # handled (and is optional) downstream in
            # create_monte_carlo_weather_draw_profiles.
            weather_bins_in_current_month_df = weather_bins[
                weather_bins["month"] == current_month
            ]
            weather_bins_in_current_month = weather_bins_in_current_month_df[
                "weather_bin"
            ].to_numpy()
            years_in_current_month = weather_bins_in_current_month_df["year"].to_numpy()

            # Find the indices where the weather bin matches the prior weather
            # bin; the "following day" candidates are those indices + 1
            match_indices = np.where(
                weather_bins_in_current_month == prior_weather_bin
            )[0]
            current_weather_bin_index_options = match_indices + 1
            # Drop any index that runs past the end of the month's record (a
            # match on the very last day has no "following" day)
            in_bounds = current_weather_bin_index_options < len(
                weather_bins_in_current_month
            )
            match_indices = match_indices[in_bounds]
            current_weather_bin_index_options = current_weather_bin_index_options[
                in_bounds
            ]
            # Exclude year-boundary crossings: because the record is restricted
            # to a single month, the day after the last day of the month in one
            # year is positionally the first day of the same month in the next
            # year -- not a real next-day transition. Keep only followers that
            # fall in the same year as their matched day.
            same_year = (
                years_in_current_month[current_weather_bin_index_options]
                == years_in_current_month[match_indices]
            )
            current_weather_bin_index_options = current_weather_bin_index_options[
                same_year
            ]
            # Randomly select from the above list of indices and get the
            # corresponding weather bin to assign to the current day. If no
            # valid follower exists -- e.g., the prior bin does not occur in
            # this month at all (this happens at month boundaries when bins are
            # month-specific, since the prior bin comes from the previous month)
            # or it occurs only on end-of-month days -- fall back to sampling
            # unconditionally from the month's bins, mirroring the
            # start-of-year draw.
            if len(current_weather_bin_index_options) > 0:
                chosen_index = current_weather_bin_index_options[
                    np.random.randint(len(current_weather_bin_index_options))
                ]
            else:
                chosen_index = np.random.randint(len(weather_bins_in_current_month))
            current_weather_bin = weather_bins_in_current_month[chosen_index]

            data.append(
                (
                    weather_bins_id,
                    weather_draws_id,
                    iteration,
                    draw_number,
                    str(current_date),
                    current_month,
                    current_day_type_bool,
                    int(current_weather_bin),
                )
            )

            # Change the prior_weather_bin for the next day
            prior_weather_bin = current_weather_bin

    c = conn.cursor()

    sql_info = f"""
        INSERT INTO aux_weather_draws_info ( 
            weather_bins_id,
            weather_draws_id,
            seed,
            n_iterations
        ) VALUES (
            {weather_bins_id}, 
            {weather_draws_id}, 
            {weather_draws_seed if weather_draws_seed is not None else 'NULL'}, 
            {n_iterations}
        );
    """

    spin_on_database_lock_generic(command=c.execute(sql_info))

    sql = """
        INSERT INTO aux_weather_iterations (
            weather_bins_id,
            weather_draws_id,
            weather_iteration,
            draw_number,
            study_date,
            month,
            day_type,
            weather_day_bin
        ) VALUES (
        ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?
        )
    """
    spin_on_database_lock_generic(command=c.executemany(sql, data))

    conn.commit()


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating Monte Carlo weather draws...")

    conn = connect_to_database(db_path=parsed_args.database)

    # ### Load data from CSV
    if parsed_args.input_csv is not None:
        read_and_import_csv(
            conn=conn, f_path=parsed_args.input_csv, table="user_defined_weather_bins"
        )

    # ###################### Create the weather draws # ########################
    create_weather_draws(
        conn=conn,
        weather_bins_id=int(parsed_args.weather_bins_id),
        weather_draws_seed=(
            int(parsed_args.weather_draws_seed)
            if parsed_args.weather_draws_seed is not None
            else None
        ),
        n_iterations=int(parsed_args.n_iterations),
        weather_draws_id=int(parsed_args.weather_draws_id),
        study_year=int(parsed_args.study_year),
        quiet=parsed_args.quiet,
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
