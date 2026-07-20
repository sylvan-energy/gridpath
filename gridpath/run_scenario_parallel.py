# Copyright 2016-2023 Blue Marble Analytics LLC.
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
Parallel gridpath_run. Note that parallel gridpath_run_e2e is not yet
supported. You can get the scenario inputs, solve the scenarios in parallel
with gridpath_run_parallel, the import the results to the database in sequence.
"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import csv
from multiprocessing import get_context
import sys

from gridpath.run_scenario import main as run_scenario_main


def parse_arguments(arguments):
    """

    :return:
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    # Scenario name and location options
    parser.add_argument(
        "--scenarios_csv",
        default="./scenarios_to_run.csv",
        help="The file containing the scenarios to run along with their run_scenario options.",
    )
    parser.add_argument("--n_parallel_scenarios", help="Solve n scenarios in parallel.")
    # Parse arguments
    parsed_arguments = parser.parse_known_args(args=arguments)[0]

    return parsed_arguments


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    # Parse arguments
    parsed_args = parse_arguments(args)
    scenarios_csv_path = parsed_args.scenarios_csv
    n_parallel_scenarios = int(parsed_args.n_parallel_scenarios)

    # Encoding needed to avoid \ufeff when CSVs opened in Excel,
    # which is likely how they will be generated
    args_for_run_scenario = []
    with open(scenarios_csv_path, "r", encoding="utf-8-sig") as scenarios_csv_in:
        reader = csv.reader(scenarios_csv_in, delimiter=",")
        header = next(reader)
        if header[0] == "scenario":
            scenarios = header[1:]
            for scenario in scenarios:
                args_for_run_scenario.append(["--scenario", scenario])
        else:
            raise (
                ValueError(
                    "Scenarios must be in the top row with 'scenario' in the first column."
                )
            )
        for row in reader:
            argument = row[0]
            values = row[1:]

            id = 0
            for value in values:
                args_for_run_scenario[id].append(f"--{argument}")
                args_for_run_scenario[id].append(value)

                id += 1

    # Create pool
    pool = get_context("spawn").Pool(n_parallel_scenarios)

    pool_data = tuple(args_for_run_scenario)
    pool.map(run_scenario_pool, pool_data)
    pool.close()
    pool.join()


def run_scenario_pool(pool_datum):
    """
    Helper function to pass to pool.map if solving scenarios in parallel.
    """
    run_scenario_main(
        args=pool_datum,
    )


if __name__ == "__main__":
    main()
