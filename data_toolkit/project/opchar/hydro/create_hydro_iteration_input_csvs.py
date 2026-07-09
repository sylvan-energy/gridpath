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
Hydro Gen Inputs
****************

Create hydro iteration input CSVs from year/month data.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_hydro_iteration_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_project_hydro_opchars_by_year_month
    * raw_data_hydro_years
    * user_defined_balancing_type_horizons

=========
Settings
=========
    * database
    * output_directory
    * hydro_operational_chars_scenario_id
    * hydro_operational_chars_scenario_name
    * overwrite
    * n_parallel_projects

===================
What this step does
===================

This module builds GridPath hydro operational-characteristics input CSVs from
the year/month hydro data loaded earlier
(``raw_data_project_hydro_opchars_by_year_month``, ``raw_data_hydro_years``,
and the user-defined balancing-type horizons in
``user_defined_balancing_type_horizons``). For each hydro iteration it derives
the per-horizon hydro operating parameters -- the average, minimum, and maximum
power fractions -- and writes them to ``--output_directory`` under the given
``hydro_operational_chars_scenario_id`` and
``hydro_operational_chars_scenario_name``. ``--n_parallel_projects N`` runs up
to ``N`` projects at once, and ``--overwrite`` replaces existing CSVs.

===========
Methodology
===========

The distinct projects to process are read from
``raw_data_project_hydro_opchars_by_year_month``, and one CSV is written per
project, named ``<project>-<scenario_id>-<scenario_name>.csv`` in
``--output_directory``. Projects are processed in a multiprocessing pool sized
by ``--n_parallel_projects`` (defaults to ``1``).

--------------------------------------------
Hydro iterations and balancing-type horizons
--------------------------------------------

The set of hydro years is read from ``raw_data_hydro_years`` and each year is
treated as one hydro iteration (written into the ``hydro_iteration`` column).
The set of ``(balancing_type, horizon)`` pairs is read from
``user_defined_balancing_type_horizons``; if ``--hydro_balancing_type`` is
supplied, the pairs are filtered to that single balancing type (e.g. ``day``,
``week``, ``month``), otherwise all balancing types are included. For every
combination of hydro year and balancing-type horizon, one output row is
produced.

------------------------------------
Deriving per-horizon power fractions
------------------------------------

The ``average_power_fraction``, ``min_power_fraction``, and
``max_power_fraction`` for each horizon are computed by month-weighting the raw
monthly opchar values. For a given balancing-type horizon, the module reads its
``hour_ending_of_year_start`` and ``hour_ending_of_year_end`` from
``user_defined_balancing_type_horizons`` and walks each hour of the year in that
range, mapping the hour to a calendar month (via a ``pandas.Timestamp`` anchored
at January 1 of the hydro year) and counting the number of hours that fall in
each month. These hour counts become the per-month weights for the horizon.

For each month touched by the horizon, the module looks up the project's
``average_power_fraction``, ``min_power_fraction``, and ``max_power_fraction``
for that hydro year and month in
``raw_data_project_hydro_opchars_by_year_month``, multiplies each by the month's
hour-count weight, sums across months, and divides by the total number of hours
in the horizon. The result is an hours-weighted average of the monthly
fractions for each of the three parameters, written as a single row keyed by
``balancing_type_project`` and ``horizon`` (with ``weather_iteration`` set to
``0``, i.e. no weather iteration). Note we take the weighted averages of the
mins and maxes, not the mins of the mins or the maxes of the maxes.

----------------------------------
Writing and overwriting output
----------------------------------

Rows are appended to the project's CSV as they are generated, with the header
written only when the file does not yet exist. When ``--overwrite`` is set, any
existing CSV for the project is deleted before processing begins so it is
rebuilt from scratch; without ``--overwrite``, new rows are appended to any
existing file.

If the corresponding ``--*_input_csv`` paths are provided, the raw-data tables
(``raw_data_project_hydro_opchars_by_year_month``, ``raw_data_hydro_years``,
``user_defined_balancing_type_horizons``) are loaded from those CSVs before the
inputs are built; otherwise the data is assumed to already be present in the
database.
"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
from multiprocessing import current_process, get_context
import os.path
import pandas as pd
import sys

from db.common_functions import connect_to_database
from data_toolkit.load_raw_data import read_and_import_csv

# TODO: leap years
# TODO: hydro bins -- pick bin at random, pick year from bin at random; match
#  month


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])
    parser.add_argument("-db", "--database", default="../../io.db")
    parser.add_argument(
        "-h_opchar_y_m_csv",
        "--project_hydro_opchars_by_year_month_input_csv",
        default=None,
        help="""Path to the CSV file to load into the 
        raw_data_project_hydro_opchars_by_year_month table.
            If not specified, data will be assumed to have been
            already loaded into the database.""",
    )

    parser.add_argument(
        "-h_y_csv",
        "--hydro_years_input_csv",
        default=None,
        help="""Path to the CSV file to load into the 
        raw_data_hydro_years table.
            If not specified, data will be assumed to have been
            already loaded into the database.""",
    )
    parser.add_argument(
        "-bt_csv",
        "--balancing_type_horizons_input_csv",
        default=None,
        help="""Path to the CSV file to load into the 
        user_defined_balancing_type_horizons table.
            If not specified, data will be assumed to have been
            already loaded into the database.""",
    )
    parser.add_argument("-stage", "--stage_id", default=1, help="Defaults to 1.")
    parser.add_argument(
        "-id",
        "--hydro_operational_chars_scenario_id",
        default=1,
        help="Defaults to 1.",
    )
    parser.add_argument(
        "-name",
        "--hydro_operational_chars_scenario_name",
        default="ra_toolkit",
        help="Defaults to ra_toolkit.",
    )
    parser.add_argument("-out_dir", "--output_directory")
    parser.add_argument(
        "-o",
        "--overwrite",
        default=False,
        action="store_true",
        help="Overwrite existing files.",
    )

    parser.add_argument(
        "-hydro_bt",
        "--hydro_balancing_type",
        default=None,
        help="Filter to a specific balancing type (e.g., 'day', 'week', 'month'). "
        "If not specified, all balancing types from "
        "user_defined_balancing_type_horizons are included.",
    )

    parser.add_argument(
        "-parallel",
        "--n_parallel_projects",
        default=1,
        help="The number of projects to simulate in parallel. Defaults to 1.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def calculate_from_project_year_month_data(
    db_path,
    prj,
    stage_id,
    hydro_operational_chars_scenario_id,
    hydro_operational_chars_scenario_name,
    output_directory,
    overwrite,
    hydro_balancing_type=None,
):
    """
    Create hydro project CSVs for a temporal subscenario and a balancing
    type from year/month data.
    """
    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    hydro_years = [y[0] for y in c.execute("""
            SELECT DISTINCT year FROM raw_data_hydro_years;
    """).fetchall()]

    bt_horizons = [bt_h for bt_h in c.execute("""
            SELECT DISTINCT balancing_type, horizon
            FROM user_defined_balancing_type_horizons;
            """).fetchall()]

    if hydro_balancing_type is not None:
        bt_horizons = [bt_h for bt_h in bt_horizons if bt_h[0] == hydro_balancing_type]

    if overwrite:
        filename = get_filename(
            output_directory,
            prj,
            hydro_operational_chars_scenario_id,
            hydro_operational_chars_scenario_name,
        )
        try:
            os.remove(filename)
        except OSError:
            pass

    # Create hydro inputs for each year and balancing type
    for yr in hydro_years:
        for bt, h in bt_horizons:
            hr_start, hr_end = c.execute(f"""
                    SELECT hour_ending_of_year_start, hour_ending_of_year_end
                    FROM user_defined_balancing_type_horizons
                    WHERE balancing_type = '{bt}'
                    AND horizon = {h}
                    ;
                """).fetchone()

            month_weights = {}
            total = 0
            for hr_of_year in range(hr_start - 1, hr_end):
                timestamp = pd.Timestamp(f"{yr}-01-01") + pd.to_timedelta(
                    hr_of_year, unit="h"
                )
                hr_month = timestamp.month
                if hr_month in month_weights.keys():
                    month_weights[hr_month] += 1
                else:
                    month_weights[hr_month] = 1

                total += 1

            df = pd.DataFrame(
                columns=[
                    "weather_iteration",
                    "hydro_iteration",
                    "stage_id",
                    "balancing_type_project",
                    "horizon",
                    "average_power_fraction",
                    "min_power_fraction",
                    "max_power_fraction",
                ]
            )
            weighted_avg, weighted_min, weighted_max = 0, 0, 0
            for month in month_weights.keys():
                weight = month_weights[month]
                avg, min, max = c.execute(f"""
                    SELECT average_power_fraction, min_power_fraction, 
                    max_power_fraction
                    FROM raw_data_project_hydro_opchars_by_year_month
                    WHERE project = '{prj}'
                    AND hydro_year = {yr}
                    AND month = {month}
                    ;
                """).fetchone()

                weighted_avg += weight * avg
                weighted_min += weight * min
                weighted_max += weight * max

            weighted_avg = weighted_avg / total
            weighted_min = weighted_min / total
            weighted_max = weighted_max / total

            df.loc[len(df)] = [
                0,  # no weather iteration
                yr,
                stage_id,
                bt,
                h,
                weighted_avg,
                weighted_min,
                weighted_max,
            ]

            filename = get_filename(
                output_directory,
                prj,
                hydro_operational_chars_scenario_id,
                hydro_operational_chars_scenario_name,
            )

            df.to_csv(
                filename,
                mode="a",
                header=not os.path.exists(filename),
                index=False,
            )

            # TODO: add iterations CSVs


def calculate_from_project_year_month_data_pool(pool_datum):
    (
        db_path,
        prj,
        hydro_operational_chars_scenario_id,
        hydro_operational_chars_scenario_name,
        output_directory,
        overwrite,
        stage_id,
        hydro_balancing_type,
    ) = pool_datum

    calculate_from_project_year_month_data(
        db_path=db_path,
        prj=prj,
        hydro_operational_chars_scenario_id=hydro_operational_chars_scenario_id,
        hydro_operational_chars_scenario_name=hydro_operational_chars_scenario_name,
        output_directory=output_directory,
        overwrite=overwrite,
        stage_id=stage_id,
        hydro_balancing_type=hydro_balancing_type,
    )


def get_filename(
    output_directory,
    prj,
    hydro_operational_chars_scenario_id,
    hydro_operational_chars_scenario_name,
):
    return os.path.join(
        output_directory,
        f"{prj}-{hydro_operational_chars_scenario_id}-{hydro_operational_chars_scenario_name}.csv",
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating hydro CSVs...")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(parsed_args.database)

    # ### Load data from CSV
    if parsed_args.project_hydro_opchars_by_year_month_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.project_hydro_opchars_by_year_month_input_csv,
            table="raw_data_project_hydro_opchars_by_year_month",
        )

    if parsed_args.hydro_years_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.hydro_years_input_csv,
            table="raw_data_hydro_years",
        )

    if parsed_args.balancing_type_horizons_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.balancing_type_horizons_input_csv,
            table="user_defined_balancing_type_horizons",
        )

    c = conn.cursor()
    projects = [prj[0] for prj in c.execute("""
                SELECT DISTINCT project
                FROM raw_data_project_hydro_opchars_by_year_month;
            """).fetchall()]
    pool_data = tuple(
        [
            [
                parsed_args.database,
                prj,
                parsed_args.hydro_operational_chars_scenario_id,
                parsed_args.hydro_operational_chars_scenario_name,
                parsed_args.output_directory,
                parsed_args.overwrite,
                parsed_args.stage_id,
                parsed_args.hydro_balancing_type,
            ]
            for prj in projects
        ]
    )

    # Close before spawning workers: on Windows, holding an open SQLite file
    # handle in the main process conflicts with spawn workers opening the same
    # file (WinError 32). Workers each open their own connection.
    conn.commit()
    conn.close()

    # Pool must use spawn to work properly on Linux.
    # Guard against re-entry on Windows: spawn re-imports __main__ in each
    # worker, triggering main() again. current_process().name is set during
    # prepare() before __main__ is re-imported, so it reliably identifies
    # worker processes (unlike parent_process(), which isn't set until later).
    if current_process().name != "MainProcess":
        return

    pool = get_context("spawn").Pool(int(parsed_args.n_parallel_projects))

    pool.map(calculate_from_project_year_month_data_pool, pool_data)
    pool.close()
    pool.join()


if __name__ == "__main__":
    main()
