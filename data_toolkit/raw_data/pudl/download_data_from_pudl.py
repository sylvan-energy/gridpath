# Copyright 2016-2024 Blue Marble Analytics LLC.
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
To download data from PUDL, use the ``gridpath_get_pudl_data`` command.
This will download the individual Parquet files for the PUDL tables
GridPath uses — the EIA860 generator and plant tables, the EIA AEO fuel
price projections, the RA Toolkit wind and solar profiles, and the EIA930
hourly interchange data — from a versioned PUDL data release on the PUDL
AWS Open Data Registry endpoint (PUDL releases are also archived on Zenodo
under concept DOI `10.5281/zenodo.3653158
<https://doi.org/10.5281/zenodo.3653158>`__, but individual Parquet files
are only available via the AWS endpoint). The full *pudl.sqlite* database
is not needed by the GridPath Data Toolkit; if you also want a local copy
for ad hoc exploration of other PUDL tables, pass *--include_pudl_sqlite*
(a multi-GB download). See *--help* menu for options and defaults, e.g.,
download location, the PUDL release version, skipping datasets, etc.
"""

PUDL_VERSION_DEFAULT = "v2026.7.2"
PUDL_S3_BASE_URL = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop"
DOWNLOAD_DIRECTORY_DEFAULT = "./pudl_download"

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import requests
import sys
import zipfile

from db.utilities.common_functions import confirm

DOWNLOAD_CHUNK_SIZE_BYTES = 1024 * 1024


def download_file_with_progress(url, filepath):
    """
    Stream a file from *url* to *filepath*, printing download progress.
    The file is downloaded to a temporary .part file first, so an
    interrupted download doesn't leave a partial file at *filepath*.
    """
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    total_bytes = int(response.headers.get("content-length", 0))

    tmp_filepath = f"{filepath}.part"
    downloaded_bytes = 0
    last_printed = -1
    with open(tmp_filepath, "wb") as f:
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE_BYTES):
            f.write(chunk)
            downloaded_bytes += len(chunk)
            downloaded_mb = downloaded_bytes / 1024**2
            if total_bytes:
                # Print on each whole-percent change
                pct = int(downloaded_bytes / total_bytes * 100)
                if pct > last_printed:
                    last_printed = pct
                    sys.stdout.write(
                        f"\r... {downloaded_mb:,.0f} MB of "
                        f"{total_bytes / 1024 ** 2:,.0f} MB ({pct}%)"
                    )
                    sys.stdout.flush()
            else:
                # No content-length header; print every 10 MB
                if int(downloaded_mb) // 10 > last_printed:
                    last_printed = int(downloaded_mb) // 10
                    sys.stdout.write(f"\r... {downloaded_mb:,.0f} MB")
                    sys.stdout.flush()
    sys.stdout.write("\n")

    os.replace(tmp_filepath, filepath)


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument(
        "-v_pudl",
        "--pudl_version",
        default=PUDL_VERSION_DEFAULT,
        help=f"PUDL data release version to download. Defaults to "
        f"{PUDL_VERSION_DEFAULT}.",
    )
    parser.add_argument(
        "-incl_db",
        "--include_pudl_sqlite",
        default=False,
        action="store_true",
        help="Also download the full pudl.sqlite database (multi-GB; not "
        "needed by the Data Toolkit, but useful for ad hoc exploration of "
        "other PUDL tables).",
    )
    parser.add_argument(
        "-skip_eia860",
        "--skip_eia860_download",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-skip_eiaaeo",
        "--skip_eiaaeo_fuel_prices_download",
        default=False,
        action="store_true",
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


def get_pudl_sqlite_from_pudl_s3(pudl_version, download_directory):
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
        url = f"{PUDL_S3_BASE_URL}/{pudl_version}/{filename}.zip"
        zip_filepath = os.path.join(download_directory, f"{filename}.zip")
        print("Downloading compressed pudl.sqlite...")
        download_file_with_progress(url=url, filepath=zip_filepath)

        print("Extracting pudl.sqlite database...")
        with zipfile.ZipFile(zip_filepath) as z:
            z.extractall(download_directory)
        os.remove(zip_filepath)


def get_parquet_file_from_pudl_s3(pudl_version, filename, download_directory):
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
        url = f"{PUDL_S3_BASE_URL}/{pudl_version}/{filename}.parquet"
        download_file_with_progress(url=url, filepath=filepath)


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    os.makedirs(parsed_args.pudl_download_directory, exist_ok=True)

    # Optionally download the full PUDL database (not needed by the Data
    # Toolkit itself). Note this is large file.
    if parsed_args.include_pudl_sqlite:
        get_pudl_sqlite_from_pudl_s3(
            pudl_version=parsed_args.pudl_version,
            download_directory=parsed_args.pudl_download_directory,
        )

    # Per-table parquet files
    parquet_dict = {
        "core_eia860__scd_generators": {
            "skip": parsed_args.skip_eia860_download,
        },
        "core_eia860__scd_plants": {
            "skip": parsed_args.skip_eia860_download,
        },
        "core_eiaaeo__yearly_projected_fuel_cost_in_electric_sector_by_type": {
            "skip": parsed_args.skip_eiaaeo_fuel_prices_download,
        },
        "out_gridpathratoolkit__hourly_available_capacity_factor": {
            "skip": parsed_args.skip_ra_toolkit_profiles_download,
        },
        "core_eia930__hourly_interchange": {
            "skip": parsed_args.skip_eia930_hourly_interchange_download,
        },
    }
    for filename in parquet_dict.keys():
        skip = parquet_dict[filename]["skip"]
        if not skip:
            get_parquet_file_from_pudl_s3(
                pudl_version=parsed_args.pudl_version,
                download_directory=parsed_args.pudl_download_directory,
                filename=filename,
            )


if __name__ == "__main__":
    main()
