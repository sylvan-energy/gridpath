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
To download data from PUDL, use the ``gridpath_get_pudl_data`` command.
This will download the *pudl.sqlite* database as well as the RA Toolkit
wind and solar profiles Parquet file, and the EIA930 hourly interchange
data Parquet file. See *--help* menu for options and defaults, e.g., download
location, the Zenodo record number for each dataset, skipping datasets, etc.
"""

ZENODO_PUDL_SQLITE_DEFAULT = 13346011
ZENODO_RA_TOOLKIT_DEFAULT = 11292273
ZENODO_EIA930_DEFAULT = 11292273
DOWNLOAD_DIRECTORY_DEFAULT = "./pudl_download"

import gzip
import shutil
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import io
import os.path
import requests
import sys
import zipfile

from db.utilities.common_functions import confirm


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument(
        "-z_db",
        "--zenodo_record_pudl_sqlite",
        default=ZENODO_PUDL_SQLITE_DEFAULT,
        help=f"Defaults to {ZENODO_PUDL_SQLITE_DEFAULT}.",
    )
    parser.add_argument(
        "-z_ra",
        "--zenodo_record_ra_toolkit",
        default=ZENODO_RA_TOOLKIT_DEFAULT,
        help=f"Defaults to {ZENODO_RA_TOOLKIT_DEFAULT}.",
    )
    parser.add_argument(
        "-z_eia930",
        "--zenodo_record_eia930",
        default=ZENODO_EIA930_DEFAULT,
        help=f"Defaults to {ZENODO_EIA930_DEFAULT}.",
    )
    parser.add_argument(
        "-skip_db", "--skip_pudl_sqlite_download", default=False, action="store_true"
    )
    parser.add_argument(
        "-skip_ra",
        "--skip_ra_toolkit_profiles_download",
        default=False,
        action="store_true",
    )

    parser.add_argument(
        "-skip_eia930",
        "--skip_eia930_hourly_interchange_download",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-d",
        "--pudl_download_directory",
        default=DOWNLOAD_DIRECTORY_DEFAULT,
        help=f"Defaults to {DOWNLOAD_DIRECTORY_DEFAULT}",
    )

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_pudl_sqlite_from_pudl_zenodo(zenodo_record_pudl_sqlite, download_directory):
    """ """
    proceed = True
    filename = "pudl.sqlite"
    filepath = os.path.join(download_directory, filename)
    if os.path.exists(filepath):
        proceed = confirm(
            f"WARNING: The file {filepath} already exists. Downloading "
            f"the data again will overwrite the previous file. Are you sure?"
        )

    if proceed:
        url = f"https://zenodo.org/records/{str(zenodo_record_pudl_sqlite)}/files/{filename}.zip?download=1"
        print("Downloading compressed pudl.sqlite...")
        pudl_request_content = requests.get(url, stream=True).content

        print("Extracting pudl.sqlite database...")
        z = zipfile.ZipFile(io.BytesIO(pudl_request_content))
        z.extractall(download_directory)

        # For gzip files use the following
        # with gzip.open(io.BytesIO(pudl_request_content), "rb") as f_in:
        #     with open(db_filepath, "wb") as f_out:
        #         shutil.copyfileobj(f_in, f_out)


def get_parquet_file_from_pudl_zenodo(
    zenodo_record_pudl_sqlite, filename, download_directory
):
    """ """
    proceed = True
    filepath = os.path.join(download_directory, f"{filename}.parquet")
    if os.path.exists(filepath):
        proceed = confirm(
            f"WARNING: The file {filepath} already exists. Downloading "
            f"the data again will overwrite the previous file. Are you sure?"
        )

    if proceed:
        print(f"Downloading {filename}.parquet...")
        url = (
            f"https://zenodo.org/records/{zenodo_record_pudl_sqlite}/files"
            f"/{filename}.parquet?download=1"
        )

        data = requests.get(url, stream=True).content

        with open(
            filepath,
            "wb",
        ) as f:
            f.write(data)


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    os.makedirs(parsed_args.pudl_download_directory, exist_ok=True)

    # Download the PUDL database
    if not parsed_args.skip_pudl_sqlite_download:
        get_pudl_sqlite_from_pudl_zenodo(
            zenodo_record_pudl_sqlite=parsed_args.zenodo_record_pudl_sqlite,
            download_directory=parsed_args.pudl_download_directory,
        )

    # RA Toolkit profiles parquet file
    parquet_dict = {
        "out_gridpathratoolkit__hourly_available_capacity_factor": {
            "skip": parsed_args.skip_ra_toolkit_profiles_download,
            "zenodo": parsed_args.zenodo_record_ra_toolkit,
        },
        "core_eia930__hourly_interchange": {
            "skip": parsed_args.skip_eia930_hourly_interchange_download,
            "zenodo": parsed_args.zenodo_record_eia930,
        },
    }
    for filename in parquet_dict.keys():
        skip = parquet_dict[filename]["skip"]
        zenodo_record = parquet_dict[filename]["zenodo"]
        if not skip:
            get_parquet_file_from_pudl_zenodo(
                zenodo_record_pudl_sqlite=zenodo_record,
                download_directory=parsed_args.pudl_download_directory,
                filename=filename,
            )


if __name__ == "__main__":
    main()
