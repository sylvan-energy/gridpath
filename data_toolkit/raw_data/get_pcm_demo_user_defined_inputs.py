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
You can use the ``gridpath_get_pcm_demo_inputs`` command to obtain these demo
mappings and inputs.

For options, including download location, see the ``--help`` menu.

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import sys

from data_toolkit.raw_data.common_functions import download_file_from_gdrive, unzip_file

RAW_DATA_DIRECTORY_DEFAULT = "."


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

    raw_data_directory = parsed_args.raw_data_directory
    filename = "pcm_demo_user_defined.zip"
    zipfile_path = os.path.join(raw_data_directory, filename)
    # Download zipped file
    download_file_from_gdrive(
        download_directory=parsed_args.raw_data_directory,
        filename=filename,
        gdrive_file_id="1Dod9btojXK1aVbvdFaSHFMpfodjXGFAR",
    )

    # Unzip
    unzip_file(zipfile_path=zipfile_path, output_directory=raw_data_directory)

    # Delete zipped file
    print(f"Deleting {zipfile_path}")
    os.remove(zipfile_path)


if __name__ == "__main__":
    main()
