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
Load data into the GridPath raw data database. See the documentation of each
GridPath Data Toolkit module for data prerequisites. Use the
``files_to_import.csv`` file to tell GridPath which CSV files should be loaded
into which database table.

===================
What this step does
===================

This module is a generic bulk loader for raw CSV data into the GridPath
database. It reads a  file named ``files_to_import.csv`` located in the
directory given by ``--csv_location``. Each row of that file describes one
CSV file: an import flag (whether the file should be loaded), the CSV
filename (relative to ``--csv_location``), and the database table the file
should be loaded into.

The loader iterates over the CSV file rows and, for each row whose import flag
is True, reads the corresponding CSV from ``--csv_location`` and appends its
contents to the named database table (existing rows are preserved; data is
inserted with ``if_exists="append"``). Rows whose import flag is False are
skipped.

This generic loader is used throughout the Data Toolkit workflow to populate
``raw_data`` tables (e.g., the EIA-860 generators and EIA-930 hourly
interchange data and the user-defined mapping tables) that later Data
Toolkit steps depend on. The RA Toolkit's raw database has its own
counterpart of this step (:mod:`ra_toolkit.load_raw_data`).

=====
Usage
=====

>>> python -m data_toolkit.load_raw_data --database PATH/TO/DATABASE --csv_location PATH/TO/CSV/DIRECTORY

=========
Settings
=========
    * database
    * csv_location

The ``--csv_location`` directory must contain a ``files_to_import.csv``
manifest with columns for the import flag, the CSV filename, and the
destination database table, in that order.

"""

import sys
from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path

import pandas as pd

from db.common_functions import connect_to_database, read_and_import_csv


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database")
    parser.add_argument("-csv", "--csv_location")
    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Importing raw data...")

    conn = connect_to_database(db_path=parsed_args.database)

    files_to_import_df = pd.read_csv(
        os.path.join(parsed_args.csv_location, "files_to_import.csv")
    )
    for index, row in files_to_import_df.iterrows():
        import_bool, f, table = row

        if import_bool:
            if not parsed_args.quiet:
                print(f"... {f}...")
            f_path = str(os.path.join(parsed_args.csv_location, f))

            read_and_import_csv(conn, f_path, table)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
