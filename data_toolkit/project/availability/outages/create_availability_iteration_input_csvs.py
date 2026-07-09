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
# simulate_unit_outages() function
# Copyright 2023 Moment Energy Insights LLC. Licensed under the Apache
# License, Version 2.0.
# Modifications Copyright 2024 Blue Marble Analytics LLC. Licensed under the
# Apache License, Version 2.0.

"""
Availability Iteration Inputs
*****************************

Run unit outage simulation and create availability iteration inputs.

===================
What this step does
===================

This module runs a Monte Carlo unit-outage simulation and writes the resulting
exogenous availability (derate) input CSVs. Using the per-unit availability
parameters loaded from ``--outage_params_input_csv`` (into the
``raw_data_unit_availability_params`` table) -- forced-outage rates
(``unit_for``), mean time to repair (``unit_mttr``), the number of units
(``n_units``), the unit weight, and the per-unit outage model
(``unit_fo_model``) -- it simulates ``--n_iterations`` independent outage
timelines for each project, drawing random forced and (under the sequential
model) repair/maintenance transitions.

The outage model is selected per unit via the ``unit_fo_model`` column and may
be one of:

    * ``Derate`` -- a static derate ``1 - unit_for`` applied in every timepoint.
    * ``MC_independent`` -- each timepoint's outage state is drawn independently
      from a uniform distribution against the forced-outage rate.
    * ``MC_sequential`` -- a sequential (exponential) failure/repair process
      driven by the forced-outage rate and ``unit_mttr`` (the implied mean time
      to failure is ``mttr * (1 / for - 1)``), preserving outage persistence
      across timepoints.
    * ``historical_year`` -- instead of simulating, a random historical year is
      sampled for the unit from ``--historical_availability_csv`` and that
      year's hourly derate series is used directly. (This is can be used for
      units whose availability is taken from a historical record rather than
      simulated; the choice is driven by the unit's ``unit_fo_model`` value,
      not by project type.)

For each project the per-unit availability adjustments are combined using each
unit's ``unit_weight`` to form a weighted project-level derate. Hybrid-storage
projects (``hybrid_stor`` set) additionally get a separately simulated derate
for the storage component. By default only rows whose derate differs from 1 are
written (as default availability in GridPath is 1); pass ``--print_ones`` to
retain all rows.

Output is written to ``--output_directory`` as one CSV per project, named
``<project>-<project_availability_scenario_id>-<project_availability_scenario_name>.csv``.
``--n_parallel_projects`` parallelizes the simulation across projects and
``--overwrite`` replaces existing files (otherwise existing files are appended
to). ``--sort`` re-sorts each output file at the end. These outage iterations
are intended to align with the weather/hydro iterations to form complete Monte
Carlo draws.

=========================
Reproducibility (seeding)
=========================

By default seeding is OFF: ``--user_provided_seeding`` is not set, so the
outage simulation is fully random and non-reproducible from run to run. When
seeding is off, *all* of the seeding flags below are ignored -- the seed
arguments are replaced with ``None`` before the simulation runs, and NumPy's
global RNG is never explicitly seeded.

To get reproducible outages, set ``--user_provided_seeding`` together with a
``--starting_project_iteration_seed <int>`` (defaults to ``0``). With seeding
on:

    * **Per-project, non-overlapping seed ranges.** Each project is assigned a
      starting seed of ``starting_project_iteration_seed + project_idx *
      n_iterations``. Within a project the per-iteration seed starts at that
      value and is incremented by 1 for each of the ``n_iterations``
      iterations, so the seed ranges of distinct projects do not overlap.
    * **Per-unit seeds within an iteration.** For a given project iteration, the
      per-iteration seed is used to seed NumPy's RNG, which then draws one
      integer seed per unit via ``np.random.randint(1,
      max_integer_for_unit_outage_seeding, size=n_units_in_project)``. Each
      unit's outage timeline is then simulated from its own seed.
      ``--max_integer_for_unit_outage_seeding`` defaults to ``1000000``.
    * **Hybrid-storage offset.** For hybrid-storage projects, the storage
      component is simulated with a seed offset from the generator component's
      unit seed by ``--hybrid_storage_seed_increment`` (defaults to ``1000``).

Every project / unit / iteration still draws its own independent random outage
timeline, but the whole simulation reproduces exactly when re-run with the same
seed settings. Again, these flags are ignored unless ``--user_provided_seeding``
is set. Caution advised when seeding.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_availability_iteration_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database table has been populated:
    * raw_data_unit_availability_params

This table can be populated ahead of time, or loaded at run time by passing
``--outage_params_input_csv``. Units that use the ``historical_year`` outage
model additionally read their derate series from the CSV passed via
``--historical_availability_csv``.

=========
Settings
=========
    * database
    * outage_params_input_csv
    * historical_availability_csv
    * stage_id
    * n_iterations
    * study_year
    * project_availability_scenario_id
    * project_availability_scenario_name
    * output_directory
    * overwrite
    * sort
    * print_ones
    * n_parallel_projects
    * user_provided_seeding
    * starting_project_iteration_seed
    * max_integer_for_unit_outage_seeding
    * hybrid_storage_seed_increment

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import csv
from multiprocessing import get_context
import numpy as np
import os.path
import pandas as pd
import sys

from db.common_functions import connect_to_database
from data_toolkit.load_raw_data import read_and_import_csv


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
        "-o_csv",
        "--outage_params_input_csv",
        default=None,
        help="""Path to the unit availability  params CSV file to load into the 
        raw_data_unit_availability_params table in the database. If not 
        specified, data will be assumed to have been already loaded into the 
        database.""",
    )
    parser.add_argument(
        "-hist_csv",
        "--historical_availability_csv",
        default=None,
        help="""Path to the historical availability data CSV file to load for the
        historical_year outage model. Expected columns: year, month, day_of_month,
        hour_of_day, unit, derate. Each unit can have multiple years of hourly
        derate data. If not specified, model will not be able to use historical_year
        outage_model.""",
    )
    parser.add_argument("-stage", "--stage_id", default=1, help="Defaults to 1.")
    parser.add_argument("-n_iter", "--n_iterations")
    parser.add_argument(
        "-user_seeding",
        "--user_provided_seeding",
        default=False,
        action="store_true",
        help="WARNING: make sure you understand what this script does with "
        "the user-defined seeds before enabling this.",
    )
    parser.add_argument(
        "-seed",
        "--starting_project_iteration_seed",
        default=0,
        help="Starting seed for an iteration-project combination. If selected, "
        "this script increments the seed by 1 for each project-iteration. "
        "Setting the seeds will ensure that you get the same results each "
        "time, but can compromise randomness. Make sure to set "
        "'--user_provided_seeding' flag to True to use this functionality and "
        "proceed with caution. If the '--user_provided_seeding' flag is not set, "
        "this seed will be ignored.",
    )
    parser.add_argument(
        "-max_unit_seed_int",
        "--max_integer_for_unit_outage_seeding",
        default=1000000,
        type=int,
        help="The max integer for assigning seeds to each unit outage "
        "simulation for a given project. The --user_provided_seeding flag must "
        "be set to True for this to take effect. Proceed with caution.",
    )
    parser.add_argument(
        "-hyb_s_seed_inc",
        "--hybrid_storage_seed_increment",
        default=1000,
        help="The seed increment for hybrid storage components relative to "
        "the generator component. If the --user_provided_seeding flag is not set, this value will be ignored.",
    )
    parser.add_argument(
        "-s_y",
        "--study_year",
        default=0,
        help=f"Defaults to 0. Timepoint IDs will start at 1. Set to YYYY to "
        f"have timepoint IDs start at YYYY0001.",
    )
    parser.add_argument(
        "-id", "--project_availability_scenario_id", default=1, help="Defaults to 1."
    )
    parser.add_argument(
        "-name",
        "--project_availability_scenario_name",
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
        "-sort",
        "--sort",
        default=False,
        action="store_true",
        help="Sorts output file at the " "end if enabled.",
    )

    parser.add_argument(
        "-parallel",
        "--n_parallel_projects",
        default=1,
        help="The number of projects to simulate in parallel. Defaults to 1.",
    )

    parser.add_argument(
        "-print_ones",
        "--print_ones",
        default=False,
        action="store_true",
        help="Include rows where derate values equal 1. Defaults to False.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_temporal_structure(study_year):
    stage_tmp_dict = {
        1: [tmp for tmp in range(study_year * 10000 + 1, study_year * 10000 + 8760 + 1)]
    }

    return stage_tmp_dict


def get_weighted_availability_adjustment(
    project_df,
    tmps,
    user_provided_seeding,
    project_iteration_seed,
    max_integer_for_unit_outage_seeding,
    hyb_stor_seed_unit_increment,
    historical_data=None,
):
    project_outage_adjustment = []
    project_hyb_stor_outage_adjustment = []

    # Seed the unit seeds based on the project_iteration_seed; this will only
    # be used if --random is set to False; otherwise, the unit_seeds will be
    # reset to None
    if user_provided_seeding:
        # For each project iteration, we assign a seed to each unit outage
        # simulation based on the project_iteration_seed and a
        # max_integer_for_unit_seeding number set by the user
        # Draw a distinct generator-component seed per unit (without
        # replacement) so no two units share a seed and thus an identical
        # outage timeline. To also keep each hybrid unit's storage-component
        # seed (generator seed + hyb_stor_seed_unit_increment, assigned below)
        # from coinciding with another unit's generator or storage seed, draw
        # the generator seeds from values spaced (increment + 1) apart: no two
        # then differ by exactly the increment, so {seeds} and
        # {seeds + increment} are disjoint.
        n_units_in_project = len(project_df.index)
        seed_population = np.arange(
            1,
            max_integer_for_unit_outage_seeding,
            hyb_stor_seed_unit_increment + 1,
        )
        # Guard: np.random.choice(replace=False) cannot draw more values than
        # are available. Fail with an actionable message rather than an opaque
        # ValueError.
        if n_units_in_project > len(seed_population):
            raise ValueError(
                f"Cannot assign {n_units_in_project} distinct, "
                f"non-colliding outage seeds to project "
                f"'{project_df['project'].iloc[0]}': only "
                f"{len(seed_population)} are available given "
                f"max_integer_for_unit_outage_seeding="
                f"{max_integer_for_unit_outage_seeding} and "
                f"hybrid_storage_seed_increment={hyb_stor_seed_unit_increment}. "
                f"Increase --max_integer_for_unit_outage_seeding."
            )
        np.random.seed(project_iteration_seed)
        unit_seeds = np.random.choice(
            seed_population, size=n_units_in_project, replace=False
        )
    else:
        unit_seeds = [None for n in project_df.index]

    for index, row in project_df.iterrows():
        unit = row["unit"]
        project = row["project"]
        n_units = row["n_units"]
        unit_weight = row["unit_weight"]
        outage_model = row["unit_fo_model"]
        unit_for = row["unit_for"]
        unit_mttr = row["unit_mttr"]
        hybrid_stor = row["hybrid_stor"]

        # This is None if no seed was provided
        unit_seed = unit_seeds[index]

        unit_for_array = np.full((len(tmps), 1), unit_for, dtype=float)

        unit_outage_adjustment = simulate_unit_outages(
            outage_model=outage_model,
            for_array=unit_for_array,
            mttr=unit_mttr,
            n_units=n_units,
            unit_seed=unit_seed,
            historical_data=historical_data,
            unit=unit,
        )

        # Get the project outage
        # For hybrids, this is applied to the generator component
        project_outage_adjustment.append(unit_outage_adjustment * unit_weight)

        # For hybrids, also get the outage for the storage component
        # TODO: check that this works properly
        if hybrid_stor:
            unit_outage_adjustment = simulate_unit_outages(
                outage_model=outage_model,
                for_array=unit_for_array,
                mttr=unit_mttr,
                n_units=n_units,
                unit_seed=(
                    None
                    if unit_seed is None
                    else unit_seed + hyb_stor_seed_unit_increment
                ),
                historical_data=historical_data,
                unit=unit,
            )
            project_hyb_stor_outage_adjustment.append(
                unit_outage_adjustment * unit_weight
            )

    # Only sum the unit outages if there were units, otherwise, pass None
    if project_outage_adjustment:
        adjustment = sum(project_outage_adjustment)
    else:
        adjustment = None

    if hybrid_stor:
        hyb_stor_adjustment = sum(project_hyb_stor_outage_adjustment)
    else:
        hyb_stor_adjustment = None

    return adjustment, hyb_stor_adjustment


def simulate_project_availability(
    project_df,
    project,
    iteration_n,
    user_provided_seeding,
    project_iteration_seed,
    max_integer_for_unit_outage_seeding,
    hyb_stor_seed_unit_increment,
    stage_id,
    study_year,
    filepath,
    print_ones,
    historical_data=None,
):

    # print(f"Simulating project {project}, iteration {iteration_n}")
    stage_tmp_dict = get_temporal_structure(study_year)

    # No stage simulation at this point; assume single stage
    tmps = stage_tmp_dict[1]

    availability_derate, hyb_stor_derate = get_weighted_availability_adjustment(
        project_df=project_df,
        tmps=tmps,
        user_provided_seeding=user_provided_seeding,
        project_iteration_seed=project_iteration_seed,
        max_integer_for_unit_outage_seeding=max_integer_for_unit_outage_seeding,
        hyb_stor_seed_unit_increment=hyb_stor_seed_unit_increment,
        historical_data=historical_data,
    )

    export_df = pd.DataFrame(
        {
            "availability_iteration": [iteration_n] * len(tmps),
            "stage_id": [stage_id] * len(tmps),
            "timepoint": tmps,
            "availability_derate_independent": availability_derate,
            "hyb_stor_cap_availability_derate": hyb_stor_derate,
        }
    )

    # Filter out rows where derate values are 1, unless print_ones is True
    if not print_ones:
        # For non-hybrids, find rows with (!=1, None)
        export_df_non_hyb = export_df[
            (
                (export_df["availability_derate_independent"] != 1)
                & (export_df["hyb_stor_cap_availability_derate"].isna())
            )
        ]

        # For hybrids, find rows where either column is not 1
        # First, skip the rows where the storage derate is NA (so that we
        # don't end up including the ones for non-hybrids)
        export_df_hyb = export_df[
            (
                (export_df["hyb_stor_cap_availability_derate"].notna())
                & (
                    (export_df["availability_derate_independent"] != 1)
                    | ((export_df["hyb_stor_cap_availability_derate"] != 1))
                )
            )
        ]

        export_df = pd.concat([export_df_non_hyb, export_df_hyb]).drop_duplicates()

    export_df.to_csv(
        filepath,
        mode="a",
        header=False,
        index=False,
    )


def simulate_unit_outages(
    outage_model,
    for_array,
    mttr,
    n_units,
    unit_seed,
    dt=1,
    starting_outage_states=None,
    historical_data=None,
    unit=None,
):
    """
    outage_model: ["Derate", "MC_independent", "MC_sequential", "historical_year"]
    FOR: numpy array with the length of the simulation window and the FOR as
        value; note this can vary by timepoint
    N_units: integer, number of units modeled
    starting_outage_states: array with the starting outage state (1/0) for
        each of the N units
    dt: outage timestep length
    historical_data: dict with unit names as keys and DataFrames containing
        historical availability data with columns: year, month, day_of_month,
        hour_of_day, unit, derate (for historical_year model)
    unit: unit name (for historical_year model)
    """
    # print(f"Simulating unit outages for {unit}... Outage model: {outage_model}")
    # Seed the simulation if requested
    if unit_seed is not None:
        np.random.seed(unit_seed)

    if starting_outage_states is None:
        starting_outage_states = []

    # TODO: probably remove derates; should be handled via default availablity
    #  values rather than writing timepoint-level derates
    if outage_model == "Derate":
        availability = 1 - np.outer(for_array, np.ones(n_units))

    elif outage_model == "MC_independent":
        # randomly draw whether each unit is out using a uniform distribution
        # LHS is an array of the simulation window length with a random number
        # the RHS is an array of the simulation window length with the forced
        # outage rate
        # the results is an array with True/False (will be True FOR percent
        # of the time), so the final result (1.0 - ()) will be an array with
        # ones and zeros in which we'll have zeros FOR percent of the time
        availability = 1.0 - (
            np.random.rand(len(for_array), n_units)
            < np.outer(for_array, np.ones(n_units))
        )

    elif outage_model == "MC_sequential":
        # initialize with starting outage states, if they are provided.
        # Otherwise, initialize with randomly selected outages
        if np.size(starting_outage_states) == 0:
            avail_last = 1.0 - (
                np.random.rand(1, n_units) < np.outer(for_array[0], np.ones(n_units))
            )
        else:
            avail_last = starting_outage_states

        # calculate mean time to failure [MTTR = FOR * (MTTR + MTTF)]
        MTTF = float(mttr) * (1 / for_array - 1)

        # Randomly draw whether each unit fails or is repaired in each time
        # step using an exponential model
        availability = np.zeros([len(for_array), n_units])

        for t in range(len(for_array)):
            # If the unit was available in the last timepoint, use the MTTF
            # to determine if it will be available in the current timepoint
            # This depends on the timepoint-dependent FOR, so MTTF is indexed
            # by timepoint
            if_avail_last = (avail_last == 1) * (
                1.0 - (np.random.exponential(MTTF[t], n_units) < dt)
            )
            if_unavail_last = (avail_last == 0) * (
                np.random.exponential(float(mttr), n_units) < dt
            )
            avail_tmp = if_avail_last + if_unavail_last
            availability[t, :] = avail_tmp
            avail_last = avail_tmp

    elif outage_model == "historical_year":
        # Sample a random year from historical data for this unit
        if historical_data is None or unit not in historical_data:
            raise ValueError(
                f"Historical data not provided for unit {unit}. "
                "Please provide historical_availability_csv."
            )

        unit_hist_data = historical_data[unit]

        # Get list of unique years in the historical data
        available_years = unit_hist_data["year"].unique()

        if len(available_years) == 0:
            raise ValueError(f"No historical years found for unit {unit}.")

        # Randomly select a year
        selected_year = np.random.choice(available_years)

        # Get the derate values for the selected year
        # Data is already sorted by year, month, day_of_month, hour_of_day
        year_data = unit_hist_data[unit_hist_data["year"] == selected_year]
        derate_values = year_data["value"].values

        # Check if we have the right number of hours
        if len(derate_values) != len(for_array):
            raise ValueError(
                f"Historical data for unit {unit}, year {selected_year} "
                f"has {len(derate_values)} hours, but expected {len(for_array)}."
            )

        # Create availability array - replicate the same derate pattern for each
        # of the n_units (this represents multiple identical units with the same
        # historical outage pattern)
        availability = np.outer(derate_values, np.ones(n_units))

    else:
        availability = np.ones([len(for_array), n_units])

    outage_adjustment = np.mean(availability, axis=1)

    return outage_adjustment


def simulate_all_project_iterations(pool_datum):
    """
    Helper function to simulate all iterations for a single project.
    This allows parallelization by project rather than by project-iteration.
    """
    [
        conn_string,
        project,
        n_iterations,
        user_provided_seeding,
        starting_project_iteration_seed,
        max_integer_for_unit_outage_seeding,
        hyb_stor_seed_unit_increment,
        stage_id,
        study_year,
        filepath,
        print_ones,
        historical_data,
    ] = pool_datum

    # Reconnect to database in this process
    conn = connect_to_database(conn_string)

    # Loop through all iterations for this project
    project_iteration_seed = starting_project_iteration_seed
    for iteration_n in range(1, n_iterations + 1):
        # ORDER BY unit so each unit maps to the same drawn seed (unit_seeds is
        # indexed positionally) across runs; required for reproducible draws
        project_df = pd.read_sql(
            f"""
                SELECT * FROM raw_data_unit_availability_params
                WHERE project = '{project}'
                ORDER BY unit
                ;""",
            conn,
        )

        simulate_project_availability(
            project_df=project_df,
            project=project,
            iteration_n=iteration_n,
            user_provided_seeding=user_provided_seeding,
            project_iteration_seed=(
                project_iteration_seed if user_provided_seeding else None
            ),
            max_integer_for_unit_outage_seeding=(
                max_integer_for_unit_outage_seeding if user_provided_seeding else None
            ),
            hyb_stor_seed_unit_increment=(
                hyb_stor_seed_unit_increment if user_provided_seeding else None
            ),
            stage_id=stage_id,
            study_year=study_year,
            filepath=filepath,
            print_ones=print_ones,
            historical_data=historical_data,
        )

        project_iteration_seed += 1

    conn.close()


def sort_csv_file(filepath, columns_to_sort_by, ascending):
    df = pd.read_csv(filepath, delimiter=",", low_memory=False, on_bad_lines="warn")
    df.sort_values(by=columns_to_sort_by, ascending=ascending, inplace=True)

    df.to_csv(
        filepath,
        mode="w",
        header=True,
        index=False,
    )


def main(args=None):

    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating availability iteration CSVs...")

    conn = connect_to_database(parsed_args.database)

    # ### Load data from CSV
    if parsed_args.outage_params_input_csv is not None:
        read_and_import_csv(
            conn=conn,
            f_path=parsed_args.outage_params_input_csv,
            table="raw_data_unit_availability_params",
        )

    # Load historical availability data if provided
    # Not loaded into the database for now
    historical_data = None
    if parsed_args.historical_availability_csv is not None:
        # Read the CSV file directly into a DataFrame
        hist_df = pd.read_csv(parsed_args.historical_availability_csv)

        # Expected columns: year, month, day_of_month, hour_of_day, unit, derate
        # Create an hour index for ordering (1-8760 or 1-8784 for leap years)
        # Sort by temporal columns to ensure proper ordering
        hist_df = hist_df.sort_values(["year", "month", "day_of_month", "hour_of_day"])

        # Group by unit for unit-level access
        historical_data = {unit: group for unit, group in hist_df.groupby("unit")}

    # Make out directory if it doesn't exist
    if not os.path.exists(parsed_args.output_directory):
        os.makedirs(parsed_args.output_directory)

    # Get projects. ORDER BY so that project_idx (and therefore each project's
    # seed base, starting_project_iteration_seed + project_idx * n_iterations)
    # is stable across runs -- otherwise seeded results are not reproducible.
    projects = [i[0] for i in conn.execute("""
        SELECT DISTINCT project FROM raw_data_unit_availability_params
        ORDER BY project;
        """).fetchall()]

    all_files = []
    pool_data = []
    project_iteration_seed = int(parsed_args.starting_project_iteration_seed)
    hyb_stor_seed_unit_increment = int(parsed_args.hybrid_storage_seed_increment)
    n_iterations = int(parsed_args.n_iterations)

    # Calculate total iterations per project for seed incrementing
    iterations_per_project = n_iterations

    for project_idx, project in enumerate(projects):
        # Write header if we are overwriting the file or it doesn't exist
        overwrite = parsed_args.overwrite
        header = [
            "availability_iteration",
            "stage_id",
            "timepoint",
            "availability_derate_independent",
            "hyb_stor_cap_availability_derate_independent",
        ]

        filepath = os.path.join(
            parsed_args.output_directory,
            f"{project}-{parsed_args.project_availability_scenario_id}-{parsed_args.project_availability_scenario_name}.csv",
        )
        all_files.append(filepath)

        if not os.path.exists(filepath) or overwrite:
            with open(filepath, "w", newline="") as f:
                csvwriter = csv.writer(f)
                csvwriter.writerow(header)

        # Calculate starting seed for this project
        starting_seed_for_project = (
            int(parsed_args.starting_project_iteration_seed)
            + project_idx * iterations_per_project
        )

        # Create pool data entry for this project (all iterations)
        pool_data.append(
            [
                parsed_args.database,
                project,
                n_iterations,
                parsed_args.user_provided_seeding,
                starting_seed_for_project,
                parsed_args.max_integer_for_unit_outage_seeding,
                hyb_stor_seed_unit_increment,
                parsed_args.stage_id,
                int(parsed_args.study_year),
                filepath,
                parsed_args.print_ones,
                historical_data,
            ]
        )

    pool_data = tuple(pool_data)

    # Pool must use spawn to work properly on Linux
    pool = get_context("spawn").Pool(int(parsed_args.n_parallel_projects))

    pool.map(simulate_all_project_iterations, pool_data)
    pool.close()

    # Sort the resulting CSV file if requested
    # TODO: could parallelize this
    if parsed_args.sort:
        for filepath in all_files:
            sort_csv_file(
                filepath=filepath,
                columns_to_sort_by=[
                    "availability_iteration",
                    "stage_id",
                    "timepoint",
                ],
                ascending=[True, True, True],
            )

    conn.close()


if __name__ == "__main__":
    main()
