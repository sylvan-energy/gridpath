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
You can use the ``gridpath_get_ra_toolkit_data_raw`` command to obtain the
load data and hydro data from the RA Toolkit, two datasets that are not yet
available on PUDL:

* WECC BA projected 2026 hourly load profiles for weather years 2006-2020: see the study for how profiles were created and note the study was conducted in 2022
* WECC BA monthly hydro energy, Pmin, and Pmax for years 2001-2020: see the study for how data were derived


Note that these are the same datasets as what is
available for download on GridLab RA Toolkit website but in a modified format
for easier processing.


Running this command will download the following files:

* ra_toolkit_load.csv
* ra_toolkit_hydro.csv

For options, including download location, see the ``--help`` menu.

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import sys

from data_toolkit.raw_data.common_functions import download_file_from_gdrive

RAW_DATA_DIRECTORY_DEFAULT = "./raw_data"


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument(
        "-d",
        "--raw_data_directory",
        default=RAW_DATA_DIRECTORY_DEFAULT,
        help=f"Defaults to {RAW_DATA_DIRECTORY_DEFAULT}",
    )

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    os.makedirs(parsed_args.raw_data_directory, exist_ok=True)

    file_dict = {
        "ra_toolkit_hydro.csv": "1k5FtwE44avnicAXSHbo1twR7zwh2hjo9",
        "ra_toolkit_load.csv": "1k4JdsUhMyZg_OQR5rvteg-tg-s2kS8Za",
    }
    for filename in file_dict.keys():
        download_file_from_gdrive(
            download_directory=parsed_args.raw_data_directory,
            filename=filename,
            gdrive_file_id=file_dict[filename],
        )


if __name__ == "__main__":
    main()
