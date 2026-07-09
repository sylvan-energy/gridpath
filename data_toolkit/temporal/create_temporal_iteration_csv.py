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
Create Temporal Iterations CSV
******************************

Create temporal iterations CSV from user-defined params. Does not cover all
possible cases yet.

===================
What this step does
===================

This module builds the temporal ``iterations.csv`` that tells GridPath which
combinations of weather, hydro, and availability iterations to run. It reads
the user-defined ``--iterations_csv_path`` (which specifies, per dimension, the
sampling "mode" and the iterations to draw from) and writes an
``iterations.csv`` -- with ``weather_iteration``, ``hydro_iteration``, and
``availability_iteration`` columns -- into ``--output_directory``. This file
ties together the per-dimension Monte Carlo draws produced by the earlier steps
(e.g., ``create_monte_carlo_weather_draws``) into the actual set of scenario
iterations the model runs.

===========
Methodology
===========

The input file at ``--iterations_csv_path`` is a CSV with one column per
dimension: ``weather``, ``hydro``, and ``availability``. Within each column the
*first* data row holds that dimension's sampling **mode** (a string), and the
remaining non-empty rows list the iteration numbers available to draw from for
that dimension. The columns may be of unequal length; trailing blank cells are
ignored.

----------------
Sampling modes
----------------

Every dimension (``weather``, ``hydro``, and ``availability``) supports the
same set of modes; the mode in a column's first row controls how iterations are
selected for that dimension:

    * ``loop`` -- enumerate over every listed iteration. ``loop`` dimensions are
      the *drivers*: the output is the Cartesian product across all dimensions
      set to ``loop`` (see below).
    * ``ordered`` -- step through the listed iterations sequentially, advancing
      an index by one each time a value is requested.
    * ``random_keep`` -- draw an iteration uniformly at random, leaving the pool
      unchanged (sampling with replacement).
    * ``random_remove`` -- draw an iteration uniformly at random and remove it
      from the pool (sampling without replacement).
    * ``all`` -- always return the first listed iteration.

------------------------------
How combinations are generated
------------------------------

The dimensions set to ``loop`` drive enumeration: the script writes one row for
every combination in the Cartesian product of those dimensions' iteration
lists, taken in ``weather``, ``hydro``, ``availability`` order. For each such
row, every dimension *not* set to ``loop`` contributes a single iteration drawn
according to its own mode (``ordered`` / ``random_keep`` / ``random_remove`` /
``all``). Some examples:

    * ``weather`` ``loop`` and ``hydro`` ``loop`` -> one row per
      ``(weather_iteration, hydro_iteration)`` pair, with each row's
      ``availability_iteration`` chosen according to the ``availability`` mode.
    * Only ``weather`` ``loop`` -> one row per ``weather_iteration``, with the
      ``hydro`` and ``availability`` iterations each drawn per row by their
      modes.
    * No dimension ``loop`` -> the product is a single (empty) combination, so
      each pass produces exactly one row with all three iterations drawn by
      their modes (useful for fully random sampling of combinations).

The ``--n_passes`` argument (default ``1``) repeats this whole generation
process ``n_passes`` times, with each pass starting from a fresh copy of the
iteration pools (and a fresh ``ordered`` index); this is useful with the random
modes to accumulate additional draws. After all passes complete,
``iterations.csv`` is sorted ascending by ``weather_iteration``, then
``hydro_iteration``, then ``availability_iteration``.

------------------------
Reproducibility (seeding)
------------------------

The random sampling modes (``random_keep`` and ``random_remove``) draw from
Python's ``random`` module. By default ``--seed`` is unset, so the module is
seeded from system entropy and repeated runs produce different draws. Pass
``--seed <int>`` to seed the RNG once, up front, before any pass begins;
re-running with the same seed (and the same inputs and ``--n_passes``) then
reproduces the identical ``iterations.csv``. The non-random modes (``loop``,
``ordered``, ``all``) are deterministic regardless of the seed.

=====
Usage
=====

>>> python -m data_toolkit.temporal.create_temporal_iteration_csv --iterations_csv_path PATH/TO/ITERATIONS/CSV --output_directory PATH/TO/OUTPUT/DIR

===================
Input prerequisites
===================

This module requires a user-defined iterations CSV at ``--iterations_csv_path``
with the columns ``weather``, ``hydro``, and ``availability`` populated as
described above (a mode in the first row, followed by the iteration numbers to
draw from).

=========
Settings
=========
    * n_passes
    * iterations_csv_path
    * output_directory
    * seed
"""

import sys
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import csv
import itertools
import os.path
import pandas as pd
import random

N_PASSES_DEFAULT = 1

# Sampling modes available to every dimension (weather, hydro, availability).
VALID_MODES = ("loop", "ordered", "random_keep", "random_remove", "all")


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """

    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument(
        "-n",
        "--n_passes",
        default=N_PASSES_DEFAULT,
        help=f"Defaults to {N_PASSES_DEFAULT}.",
    )
    parser.add_argument("-csv", "--iterations_csv_path")

    parser.add_argument("-o", "--output_directory")

    parser.add_argument(
        "-s",
        "--seed",
        default=None,
        help="Random seed for the random sampling modes (random_keep, "
        "random_remove). Defaults to None (no seeding; draws differ each run). "
        "Set an integer for reproducible draws.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def create_temporal_scenario_iterations_csv(
    n_passes, filepath, output_directory, seed=None
):
    # Seed the RNG once, up front, before any pass begins, so that the random
    # sampling modes (random_keep / random_remove) are reproducible when a seed
    # is provided. seed=None falls back to system (non-reproducible)
    random.seed(seed)

    with open(os.path.join(output_directory, "iterations.csv"), "w") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(
            ["weather_iteration", "hydro_iteration", "availability_iteration"]
        )

    # print(os.path.abspath(filepath))
    df = pd.read_csv(filepath)

    # Parse the mode (first data row) and the available iterations (remaining
    # non-empty rows) for each dimension.
    dimension_order = ["weather", "hydro", "availability"]
    modes = {}
    iterations_pass = {}
    for dim in dimension_order:
        column = [i[1] for i in df[dim].items()]
        modes[dim] = column[0]
        iterations_pass[dim] = [i for i in column[1:] if not pd.isna(i)]
        if modes[dim] not in VALID_MODES:
            raise ValueError(
                f"Unknown sampling mode '{modes[dim]}' for the '{dim}' "
                f"dimension. Valid modes are: {', '.join(VALID_MODES)}."
            )

    rows = []
    for _ in range(n_passes):
        # Each pass starts from a fresh copy of every dimension's pool (and a
        # fresh "ordered" index), so the random/ordered modes restart per pass.
        pools = {dim: iterations_pass[dim].copy() for dim in dimension_order}
        ordered_indices = {dim: 0 for dim in dimension_order}

        # Dimensions in "loop" mode drive the enumeration: we write one row for
        # every combination in their Cartesian product (in weather, hydro,
        # availability order). Dimensions not in "loop" mode each contribute a
        # single drawn iteration per row, according to their own mode. If no
        # dimension is in "loop" mode, the product is a single empty
        # combination, so each pass produces exactly one row.
        loop_dims = [dim for dim in dimension_order if modes[dim] == "loop"]
        loop_pools = [pools[dim] for dim in loop_dims]

        for loop_combo in itertools.product(*loop_pools):
            row_values = dict(zip(loop_dims, loop_combo))
            for dim in dimension_order:
                if modes[dim] == "loop":
                    continue
                row_values[dim], ordered_indices[dim] = draw_single_iteration(
                    mode=modes[dim],
                    pool=pools[dim],
                    ordered_index=ordered_indices[dim],
                )
            rows.append([row_values[d] for d in dimension_order])

    with open(os.path.join(output_directory, "iterations.csv"), "a") as f_out:
        writer = csv.writer(f_out, delimiter=",")
        writer.writerows(rows)


def random_remove(starting_list):
    i = random.randrange(len(starting_list))
    starting_list[i], starting_list[-1] = starting_list[-1], starting_list[i]
    iteration = starting_list.pop()

    return iteration


def random_keep(starting_list):
    i = random.randrange(len(starting_list))
    iteration = starting_list[i]

    return iteration


def sort_final_file(filepath):
    df = pd.read_csv(filepath, delimiter=",")

    df = df.sort_values(
        ["weather_iteration", "hydro_iteration", "availability_iteration"],
        ascending=[True, True, True],
    )

    df.to_csv(filepath, index=False)


def draw_single_iteration(mode, pool, ordered_index):
    """
    Return ``(iteration, next_ordered_index)`` for a single draw from a
    non-"loop" dimension. ``pool`` is the (mutable) list of remaining iterations
    for the current pass; ``ordered_index`` is the position used by the
    ``ordered`` mode.

    This handles every non-"loop" mode; "loop" dimensions are enumerated by the
    Cartesian product in ``create_temporal_scenario_iterations_csv`` and never
    reach this function.
    """
    if mode == "ordered":
        iteration = pool[ordered_index]
        ordered_index += 1
    elif mode == "random_remove":
        iteration = random_remove(pool)
    elif mode == "random_keep":
        iteration = random_keep(pool)
    elif mode == "all":
        iteration = pool[0]
    else:
        raise ValueError(
            f"Unknown sampling mode '{mode}'. Valid modes are: "
            f"{', '.join(VALID_MODES)}."
        )

    return iteration, ordered_index


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    create_temporal_scenario_iterations_csv(
        n_passes=int(parsed_args.n_passes),
        filepath=parsed_args.iterations_csv_path,
        output_directory=parsed_args.output_directory,
        seed=int(parsed_args.seed) if parsed_args.seed is not None else None,
    )
    sort_final_file(
        filepath=os.path.join(parsed_args.output_directory, "iterations.csv")
    )


if __name__ == "__main__":
    main()
