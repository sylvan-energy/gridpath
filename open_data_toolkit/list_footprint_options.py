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
List Footprint Options
**********************

List the values the data toolkit steps' ``--footprint`` argument accepts:
the distinct EIA930 regions and interconnects in the EIA
balancing-authority map, each shown with its type and the number of BAs it
covers, plus the special value ``all`` (no footprint filter). The steps
accept either vocabulary without the user having to say which type they
mean — this command shows the menu.

The BA map is read from the most-processed source available, so the
options can be listed at any point in the workflow from right after the
PUDL download onward:

1. the ``raw_data_eia_baa_codes`` table of the raw database (after
   ``gridpath_load_raw_data``);
2. otherwise the ``pudl_eia_baa_codes.csv`` file in the raw-data directory
   (after ``gridpath_pudl_to_gridpath_raw``);
3. otherwise the ``core_eia__codes_balancing_authorities.parquet`` file in
   the PUDL download directory (after ``gridpath_get_pudl_data``).

=====
Usage
=====

>>> gridpath_list_footprint_options --database PATH/TO/RAW/DB

===================
Input prerequisites
===================

Any ONE of the three sources above; the source used is reported in the
output.

"""

import os.path
import sqlite3
import sys
from argparse import ArgumentParser

import duckdb
import pandas as pd

from db.common_functions import connect_to_database
from open_data_toolkit.geographic_scope import get_footprint_options
from open_data_toolkit.raw_data.pudl.pudl_to_gridpath_raw_data import (
    DOWNLOAD_DIRECTORY_DEFAULT,
    RAW_DATA_DIRECTORY_DEFAULT,
)
from gridpath.common_functions import get_version_parser

BAA_CODES_CSV = "pudl_eia_baa_codes.csv"
BAA_CODES_PARQUET = "core_eia__codes_balancing_authorities.parquet"


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="./open_data_raw.db")
    parser.add_argument(
        "-d",
        "--raw_data_directory",
        default=RAW_DATA_DIRECTORY_DEFAULT,
        help=f"Directory with the converted raw CSVs ({BAA_CODES_CSV}); "
        f"used if the raw database is not available. Defaults to "
        f"{RAW_DATA_DIRECTORY_DEFAULT}.",
    )
    parser.add_argument(
        "-pudl",
        "--pudl_download_directory",
        default=DOWNLOAD_DIRECTORY_DEFAULT,
        help=f"Directory with the downloaded PUDL files "
        f"({BAA_CODES_PARQUET}); used if neither the raw database nor the "
        f"raw CSV is available. Defaults to {DOWNLOAD_DIRECTORY_DEFAULT}.",
    )

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def dataframe_to_baa_map_connection(baa_map_df):
    """
    An in-memory SQLite connection exposing *baa_map_df* as the
    raw_data_eia_baa_codes table, so every source is queried identically to
    the raw database.
    """
    conn = sqlite3.connect(":memory:")
    baa_map_df.to_sql("raw_data_eia_baa_codes", conn, index=False)

    return conn


def get_baa_map_connection(database, raw_data_directory, pudl_download_directory):
    """
    Resolve the BA map from the most-processed source available — the raw
    database, the converted raw CSV, or the downloaded PUDL parquet — and
    return (connection, source description). The connection always exposes
    the map as the raw_data_eia_baa_codes table. Returns (None, None) if no
    source is available.
    """
    if os.path.exists(database):
        conn = connect_to_database(db_path=database)
        try:
            n_bas = (
                conn.cursor()
                .execute("SELECT COUNT(*) FROM raw_data_eia_baa_codes")
                .fetchone()[0]
            )
        except sqlite3.OperationalError:  # table doesn't exist
            n_bas = 0
        if n_bas:
            return conn, f"raw database {database}"
        conn.close()

    csv_path = os.path.join(raw_data_directory, BAA_CODES_CSV)
    if os.path.exists(csv_path):
        return (
            dataframe_to_baa_map_connection(pd.read_csv(csv_path)),
            f"raw-data CSV {csv_path}",
        )

    parquet_path = os.path.join(pudl_download_directory, BAA_CODES_PARQUET)
    if os.path.exists(parquet_path):
        baa_map_df = duckdb.sql(f"""
            SELECT
                code AS baa,
                balancing_authority_region_code_eia AS region,
                interconnect_code_eia AS interconnect
            FROM read_parquet('{parquet_path}')
            """).df()
        return (
            dataframe_to_baa_map_connection(baa_map_df),
            f"PUDL download {parquet_path}",
        )

    return None, None


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    conn, source = get_baa_map_connection(
        database=parsed_args.database,
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
    )

    if conn is None:
        print(
            "No BA map found. The footprint options come from the EIA "
            "balancing-authority map, which requires any one of:\n"
            f"  * a raw database with the raw_data_eia_baa_codes table "
            f"loaded (gridpath_load_raw_data); looked for "
            f"{parsed_args.database}\n"
            f"  * the converted {BAA_CODES_CSV} "
            f"(gridpath_pudl_to_gridpath_raw); looked in "
            f"{parsed_args.raw_data_directory}\n"
            f"  * the downloaded {BAA_CODES_PARQUET} "
            f"(gridpath_get_pudl_data); looked in "
            f"{parsed_args.pudl_download_directory}"
        )
        sys.exit(1)

    footprint_options = get_footprint_options(conn=conn)

    print(f"Available --footprint values (from {source}):")
    for footprint_type, footprint, n_bas in footprint_options:
        print(f"  {footprint_type}: {footprint} ({n_bas} BAs)")

    n_mapped_bas = (
        conn.cursor()
        .execute("SELECT COUNT(*) FROM raw_data_eia_baa_codes")
        .fetchone()[0]
    )
    print(f"  all: no footprint filter ({n_mapped_bas} mapped BAs)")

    conn.close()


if __name__ == "__main__":
    main()
