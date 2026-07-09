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
Form EIA 930 Transmission Portfolio
***********************************

This module creates a transmission line portfolio input CSV for an EIA930-based
transmission portfolio. The transmission capacity type is set "tx_spec" for
all lines.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia930_to_transmission_portfolio_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_eia930_hourly_interchange

=========
Settings
=========
    * database
    * output_directory
    * region
    * transmission_portfolio_scenario_id
    * transmission_portfolio_scenario_name

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from db.common_functions import connect_to_database
from data_toolkit.transmission.transmission_data_filters_common import (
    get_all_links_sql,
    get_unique_tx_lines,
)


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="../../open_data_raw.db")
    parser.add_argument("-r", "--region", default="WECC")
    parser.add_argument(
        "-o",
        "--output_directory",
        default="../../csvs_open_data/transmission/portfolios",
    )
    parser.add_argument("-p_id", "--transmission_portfolio_scenario_id", default=1)
    parser.add_argument(
        "-p_name", "--transmission_portfolio_scenario_name", default="eia930"
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_tx_portfolio_for_region(
    unique_tx_lines,
    output_directory,
    subscenario_id,
    subscenario_name,
):
    """ """
    df = pd.DataFrame(unique_tx_lines, columns=["transmission_line"])
    df["capacity_type"] = "tx_spec"

    df.to_csv(
        os.path.join(output_directory, f"{subscenario_id}_{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):

    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating transmission portfolio inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    c = conn.cursor()

    all_links = c.execute(get_all_links_sql(region=parsed_args.region)).fetchall()
    unique_tx_lines = get_unique_tx_lines(all_links=all_links)

    get_tx_portfolio_for_region(
        unique_tx_lines=unique_tx_lines,
        output_directory=parsed_args.output_directory,
        subscenario_id=parsed_args.transmission_portfolio_scenario_id,
        subscenario_name=parsed_args.transmission_portfolio_scenario_name,
    )

    conn.close()


if __name__ == "__main__":
    main()
