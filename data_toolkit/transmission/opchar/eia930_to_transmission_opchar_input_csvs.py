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
Form EIA 930 Transmission Opchar
********************************

This module creates transmission opchar input CSV for an EIA930-based
transmission portfolio. The transmission operational type is set to
"tx_simple" and the losses are set to 2% by default.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia930_to_transmission_ochar_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

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
    * tx_simple_loss_factor
    * region
    * transmission_operational_chars_scenario_id
    * transmission_operational_chars_scenario_name

"""

from argparse import ArgumentParser
import numpy as np
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
    parser = ArgumentParser(add_help=True)

    parser.add_argument("-db", "--database", default="../../open_data_raw.db")
    parser.add_argument("-r", "--region", default="WECC")
    parser.add_argument("-l", "--tx_simple_loss_factor", default=0.02)
    parser.add_argument("-l_tuning", "--losses_tuning_cost_per_mw", default=0)
    parser.add_argument(
        "-o",
        "--output_directory",
        default="../../csvs_open_data/transmission/opchar",
    )
    parser.add_argument(
        "-opchar_id", "--transmission_operational_chars_scenario_id", default=1
    )
    parser.add_argument(
        "-opchar_name",
        "--transmission_operational_chars_scenario_name",
        default="wecc_tx_opchar",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_tx_opchar(
    unique_tx_lines,
    tx_simple_loss_factor,
    losses_tuning_cost_per_mw,
    output_directory,
    subscenario_id,
    subscenario_name,
):
    df = pd.DataFrame(unique_tx_lines, columns=["transmission_line"])
    df["operational_type"] = "tx_simple"
    df["tx_simple_loss_factor"] = tx_simple_loss_factor
    df["losses_tuning_cost_per_mw"] = losses_tuning_cost_per_mw
    df["reactance_ohms"] = None
    df["tx_curtailment_cost_scenario_id"] = None
    df["tx_losses_factor_curtailment"] = None

    df.to_csv(
        os.path.join(output_directory, f"{subscenario_id}_{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating transmission opchar inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    c = conn.cursor()

    all_links = c.execute(get_all_links_sql(region=parsed_args.region)).fetchall()
    unique_tx_lines = get_unique_tx_lines(all_links=all_links)

    get_tx_opchar(
        unique_tx_lines=unique_tx_lines,
        tx_simple_loss_factor=parsed_args.tx_simple_loss_factor,
        losses_tuning_cost_per_mw=parsed_args.losses_tuning_cost_per_mw,
        output_directory=parsed_args.output_directory,
        subscenario_id=parsed_args.transmission_operational_chars_scenario_id,
        subscenario_name=parsed_args.transmission_operational_chars_scenario_name,
    )

    conn.close()


if __name__ == "__main__":
    main()
