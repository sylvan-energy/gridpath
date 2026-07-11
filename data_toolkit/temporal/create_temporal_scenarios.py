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
Temporal Scenarios
******************

This is a very basic module that copies over the base CSVs created by the user
and calls the temporal iterations method to create the iterations.csv file if
needed. The location of the base CSVs and the iterations description CSV are
specified in a settings file you can point to with the ``--csv_path`` argument.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step create_temporal_scenarios --settings_csv PATH/TO/SETTINGS/CSV

=========
Settings
=========
    * csv_path

"""

import shutil
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import glob
import os.path
import pandas as pd
import sys

from data_toolkit.temporal import create_temporal_iteration_csv


# TODO: create CSVs based on user settings rather than just copying them over?
# TODO: put RA toolkit base CSVs in raw directory and copy them over during
#  testing
def copy_base_csvs(base_csvs_directory, subscenario_directory):
    for f in glob.glob(os.path.join(base_csvs_directory, "*.*")):
        shutil.copyfile(f, os.path.join(subscenario_directory, os.path.basename(f)))


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """

    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-csv", "--csv_path")

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating temporal scenarios...")

    df = pd.read_csv(parsed_args.csv_path, delimiter=",")

    for index, row in df.iterrows():
        (
            output_directory,
            temporal_scenario_id,
            temporal_scenario_name,
            n_passes,
            iterations_csv,
            base_csvs_directory,
        ) = row

        if not parsed_args.quiet:
            print(f"...{temporal_scenario_id}_{temporal_scenario_name}...")
        subscenario_directory = os.path.join(
            os.getcwd(),
            output_directory,
            f"{str(temporal_scenario_id)}" f"_{temporal_scenario_name}",
        )

        os.makedirs(subscenario_directory, exist_ok=True)

        create_temporal_iteration_csv.main(
            [
                "--n_passes",
                str(n_passes),
                "--iterations_csv_path",
                iterations_csv,
                "--output_directory",
                subscenario_directory,
            ]
        )

        copy_base_csvs(
            base_csvs_directory=base_csvs_directory,
            subscenario_directory=subscenario_directory,
        )


if __name__ == "__main__":
    main()
