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
Download the EIA-930A Annual Balancing Authority Generator Inventory Report
and convert it to the GridPath raw data CSV format with the
``gridpath_get_eia930a_data`` command.

EIA-930A is the authoritative plant/generator → operational-BA crosswalk:
it collects, from each balancing authority, the inventory of generators the
BA actually operates, reconciling the EIA-860 survey-reported BA
assignments with the EIA-930 operational boundaries. EIA publishes it
annually as an Excel workbook on the Hourly Electric Grid Monitor's About
page (``EIA_930A_<year>_with layout.xlsx``), with the submissions matched
to EIA-860 Plant and Generator IDs where possible. It is not (as of July
2026) available via PUDL or the EIA API.

The workbook's three data schedules are combined into one
``eia930a_generators.csv`` (loads into ``raw_data_eia930a_generators``):

* Schedule 2 — operating generators;
* Schedule 3 — planned generators;
* Schedule 4 — generators with a pseudo-tie or dynamic-scheduling
  relationship to other BAs (see the reported_on_schedule_2 and
  pseudo_tie_bas columns).

Generators the BA reported that could not be matched to EIA-860 IDs keep
their BA-reported IDs in the ``*_eia930a`` columns instead.

.. note:: Reading the workbook uses duckdb's ``excel`` extension, which
    duckdb downloads automatically on first use.

=====
Usage
=====

>>> gridpath_get_eia930a_data --download_directory PATH/TO/DOWNLOAD --raw_data_directory PATH/TO/RAW/DATA/CSVS

=========
Settings
=========
    * download_directory
    * raw_data_directory
    * data_year

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import duckdb
import os.path
import pandas as pd
import sys

from data_toolkit.raw_data.common_functions import log_data_metadata
from data_toolkit.raw_data.pudl.download_data_from_pudl import (
    download_file_with_progress,
)
from data_toolkit.raw_data.pudl.pudl_to_gridpath_raw_data import determine_proceed

# The publication lives on the Hourly Electric Grid Monitor's About page;
# note the space in the filename
EIA930A_URL_TEMPLATE = (
    "https://www.eia.gov/electricity/930-content/"
    "EIA_930A_{data_year}_with%20layout.xlsx"
)
DOWNLOAD_DIRECTORY_DEFAULT = "./eia930a_download"
RAW_DATA_DIRECTORY_DEFAULT = "./raw_data"
DATA_YEAR_DEFAULT = 2024

# Workbook column -> raw CSV column, per schedule (None: not in that
# schedule). The typo in 'Opeartion Month' is EIA's, not ours.
COMMON_COLUMN_MAP = {
    "BA Code": "ba",
    "Plant Name": "plant_name",
    "EIA Plant ID": "plant_id_eia",
    "EIA Generator ID": "generator_id",
    "Plant ID (EIA-930A)": "plant_id_eia930a",
    "Generator ID (EIA-930A)": "generator_id_eia930a",
    "Electric Generator Technology": "technology",
    "Nameplate Capacity (MW) (EIA-860)": "nameplate_capacity_mw",
    "State (EIA-860)": "state",
    "County (EIA-860)": "county",
    "Latitude (EIA-860)": "latitude",
    "Longitude (EIA-860)": "longitude",
    "Nameplate Capacity (MW) (EIA-930A)": "nameplate_capacity_mw_eia930a",
    "State (EIA-930A)": "state_eia930a",
    "County (EIA-930A)": "county_eia930a",
}
SCHEDULE_COLUMN_MAPS = {
    2: {
        **COMMON_COLUMN_MAP,
        "Operation Year (EIA-860)": "operation_year",
        "Opeartion Month (EIA-860)": "operation_month",
    },
    3: {
        **COMMON_COLUMN_MAP,
        "Planned Operation Year (EIA-860)": "operation_year",
        "Planned Operation Month (EIA-860)": "operation_month",
    },
    4: {
        **COMMON_COLUMN_MAP,
        "Operation Year (EIA-860)": "operation_year",
        "Opeartion Month (EIA-860)": "operation_month",
        "Generator Reported on EIA-930A Schedule 2?": "reported_on_schedule_2",
        "BAs having a Pseudo-Tie or Dynamic Relationship": "pseudo_tie_bas",
    },
}
RAW_CSV_COLUMNS = [
    "data_year",
    "ba",
    "schedule",
    "plant_name",
    "plant_id_eia",
    "generator_id",
    "plant_id_eia930a",
    "generator_id_eia930a",
    "technology",
    "nameplate_capacity_mw",
    "state",
    "county",
    "latitude",
    "longitude",
    "operation_year",
    "operation_month",
    "reported_on_schedule_2",
    "pseudo_tie_bas",
    "nameplate_capacity_mw_eia930a",
    "state_eia930a",
    "county_eia930a",
]


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
        "--download_directory",
        default=DOWNLOAD_DIRECTORY_DEFAULT,
        help=f"Defaults to {DOWNLOAD_DIRECTORY_DEFAULT}",
    )
    parser.add_argument(
        "-raw",
        "--raw_data_directory",
        default=RAW_DATA_DIRECTORY_DEFAULT,
        help=f"Defaults to {RAW_DATA_DIRECTORY_DEFAULT}",
    )
    parser.add_argument(
        "-y",
        "--data_year",
        default=DATA_YEAR_DEFAULT,
        help=f"The EIA-930A data year to download (the publication is "
        f"annual). Defaults to {DATA_YEAR_DEFAULT}.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def download_eia930a(download_directory, data_year, quiet=False):
    """
    Download the EIA-930A workbook for *data_year* as published (an .xlsx
    file).
    """
    filename = f"EIA_930A_{data_year}_with_layout.xlsx"
    filepath = os.path.join(download_directory, filename)

    if determine_proceed(filepath):
        url = EIA930A_URL_TEMPLATE.format(data_year=data_year)
        if not quiet:
            print(f"Downloading {filename}...")
        download_file_with_progress(url=url, filepath=filepath, quiet=quiet)

        log_data_metadata(
            directory=download_directory,
            script="eia930a",
            output_file=filename,
            settings={"data_year": data_year, "source_url": url},
        )

    return filepath


def convert_eia930a_sheets(schedule_dfs, data_year):
    """
    Combine the workbook's three data schedules — given as a
    {schedule_number: dataframe} dict with the workbook's column names —
    into one dataframe with the raw CSV columns.
    """
    normalized = []
    for schedule, df in sorted(schedule_dfs.items()):
        column_map = SCHEDULE_COLUMN_MAPS[schedule]
        df = df.rename(columns=column_map)
        df["data_year"] = data_year
        df["schedule"] = schedule
        for column in RAW_CSV_COLUMNS:
            if column not in df.columns:
                df[column] = None
        normalized.append(df[RAW_CSV_COLUMNS])

    return pd.concat(normalized, ignore_index=True)


def convert_eia930a_to_csv(
    raw_data_directory, workbook_filepath, data_year, quiet=False
):
    """
    Convert the EIA-930A workbook's data schedules to
    eia930a_generators.csv.
    """
    filepath = os.path.join(raw_data_directory, "eia930a_generators.csv")

    if determine_proceed(filepath):
        if not quiet:
            print(f"Converting EIA-930A schedules to {filepath}...")
        duckdb.sql("INSTALL excel; LOAD excel;")
        schedule_dfs = {
            schedule: duckdb.sql(
                f"SELECT * FROM read_xlsx('{workbook_filepath}', "
                f"sheet='SCH {schedule}', all_varchar=true)"
            ).df()
            for schedule in (2, 3, 4)
        }

        eia930a_generators = convert_eia930a_sheets(
            schedule_dfs=schedule_dfs, data_year=data_year
        )
        eia930a_generators.to_csv(
            filepath,
            index=False,
        )

        log_data_metadata(
            directory=raw_data_directory,
            script="eia930a",
            output_file="eia930a_generators.csv",
            settings={
                "data_year": data_year,
                "source_file": os.path.basename(workbook_filepath),
            },
        )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    os.makedirs(parsed_args.download_directory, exist_ok=True)
    os.makedirs(parsed_args.raw_data_directory, exist_ok=True)

    workbook_filepath = download_eia930a(
        download_directory=parsed_args.download_directory,
        data_year=parsed_args.data_year,
        quiet=parsed_args.quiet,
    )

    convert_eia930a_to_csv(
        raw_data_directory=parsed_args.raw_data_directory,
        workbook_filepath=workbook_filepath,
        data_year=parsed_args.data_year,
        quiet=parsed_args.quiet,
    )


if __name__ == "__main__":
    main()
