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
EIA 930 BAs
***********

Create GridPath load_zone inputs (load_zone_scenario_id) based on BAs in Form
EIA 930.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia930_load_zone_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This script depends on having loaded the Form EIA 930 hourly interchange data
and to have defined a region for each BA in the user_defined_baa_key table (
in order to filter BAs if needed). It assumes the following raw input
database tables have been populated:

* raw_data_eia930_hourly_interchange
* user_defined_baa_key

=========
Settings
=========

* database
* lz_output_directory
* load_zone_scenario_id
* load_zone_scenario_name
* lb_output_directory
* load_balance_scenario_id
* load_balance_scenario_name
* allow_overgeneration
* overgeneration_penalty_per_mw
* allow_unserved_energy
* unserved_energy_penalty_per_mwh
* max_unserved_load_penalty_per_mw
* avg_unserved_load_penalty_per_mwa
* export_penalty_cost_per_mwh
* unserved_energy_stats_threshold_mw

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from db.common_functions import connect_to_database


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="../../../db/open_data.db")
    parser.add_argument("-r", "--region", default="WECC")

    # Load zones
    parser.add_argument("-lz_id", "--load_zone_scenario_id", default=1)
    parser.add_argument(
        "-lz_name", "--load_zone_scenario_name", default="eia_wecc_baas"
    )
    parser.add_argument(
        "-lz_o",
        "--lz_output_directory",
        default="../../csvs_open_data/system_load/load_zones",
    )

    # Load balance
    parser.add_argument("--allow_overgeneration", default=0)
    parser.add_argument("--overgeneration_penalty_per_mw", default=0)
    parser.add_argument("--allow_unserved_energy", default=1)
    parser.add_argument("--unserved_energy_penalty_per_mwh", default=20000)
    parser.add_argument("--unserved_energy_limit_mwh", default=None)
    parser.add_argument("--max_unserved_load_penalty_per_mw", default=0)
    parser.add_argument("--max_unserved_load_limit_mw", default=None)
    parser.add_argument("--avg_unserved_load_penalty_per_mwa", default=0)
    parser.add_argument("--export_penalty_cost_per_mwh", default=0)
    parser.add_argument("--unserved_energy_stats_threshold_mw", default=None)
    parser.add_argument(
        "-lb_o",
        "--lb_output_directory",
        default="../../csvs_open_data/system_load/load_balance",
    )
    parser.add_argument("-lb_id", "--load_balance_scenario_id", default=1)
    parser.add_argument(
        "-lb_name", "--load_balance_scenario_name", default="eia_wecc_baas"
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_all_lzs_sql(region):
    all_lzs_sql = f"""
        SELECT DISTINCT baa from (
            SELECT DISTINCT balancing_authority_code_eia as baa
            FROM raw_data_eia930_hourly_interchange
            UNION
            SELECT DISTINCT balancing_authority_code_adjacent_eia as ba
            FROM raw_data_eia930_hourly_interchange
            ) AS distinct_baa_tbl
        LEFT OUTER JOIN
        user_defined_baa_key
        USING (baa)
        WHERE region = '{region}'
        ;
        """

    return all_lzs_sql


def make_load_zones_csv(
    all_lzs,
    output_directory,
    subscenario_id,
    subscenario_name,
):
    """ """
    lz_dict = {
        "load_zone": all_lzs,
    }

    df = pd.DataFrame(lz_dict)

    df.to_csv(
        os.path.join(output_directory, f"{subscenario_id}_{subscenario_name}.csv"),
        index=False,
    )


def make_load_balance_csv(
    all_lzs,
    allow_overgeneration,
    overgeneration_penalty_per_mw,
    allow_unserved_energy,
    unserved_energy_penalty_per_mwh,
    unserved_energy_limit_mwh,
    max_unserved_load_penalty_per_mw,
    max_unserved_load_limit_mw,
    avg_unserved_load_penalty_per_mwa,
    export_penalty_cost_per_mwh,
    unserved_energy_stats_threshold_mw,
    output_directory,
    subscenario_id,
    subscenario_name,
):
    """ """
    lz_dict = {
        "load_zone": all_lzs,
        "allow_overgeneration": [allow_overgeneration for lz in all_lzs],
        "overgeneration_penalty_per_mw": [
            overgeneration_penalty_per_mw for lz in all_lzs
        ],
        "allow_unserved_energy": [allow_unserved_energy for lz in all_lzs],
        "unserved_energy_penalty_per_mwh": [
            unserved_energy_penalty_per_mwh for lz in all_lzs
        ],
        "unserved_energy_limit_mwh": [unserved_energy_limit_mwh for lz in all_lzs],
        "max_unserved_load_penalty_per_mw": [
            max_unserved_load_penalty_per_mw for lz in all_lzs
        ],
        "max_unserved_load_limit_mw": [max_unserved_load_limit_mw for lz in all_lzs],
        "avg_unserved_load_penalty_per_mwa": [
            avg_unserved_load_penalty_per_mwa for lz in all_lzs
        ],
        "export_penalty_cost_per_mwh": [export_penalty_cost_per_mwh for lz in all_lzs],
        "unserved_energy_stats_threshold_mw": [
            unserved_energy_stats_threshold_mw for lz in all_lzs
        ],
    }

    df = pd.DataFrame(lz_dict)

    df.to_csv(
        os.path.join(output_directory, f"{subscenario_id}_{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating load zone inputs")

    os.makedirs(parsed_args.lb_output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    c = conn.cursor()

    all_lzs = [
        lz[0] for lz in c.execute(get_all_lzs_sql(region=parsed_args.region)).fetchall()
    ]

    make_load_zones_csv(
        all_lzs=all_lzs,
        output_directory=parsed_args.lz_output_directory,
        subscenario_id=parsed_args.load_zone_scenario_id,
        subscenario_name=parsed_args.load_zone_scenario_name,
    )

    make_load_balance_csv(
        all_lzs=all_lzs,
        allow_overgeneration=parsed_args.allow_overgeneration,
        overgeneration_penalty_per_mw=parsed_args.overgeneration_penalty_per_mw,
        allow_unserved_energy=parsed_args.allow_unserved_energy,
        unserved_energy_penalty_per_mwh=parsed_args.unserved_energy_penalty_per_mwh,
        unserved_energy_limit_mwh=parsed_args.unserved_energy_limit_mwh,
        max_unserved_load_penalty_per_mw=parsed_args.max_unserved_load_penalty_per_mw,
        max_unserved_load_limit_mw=parsed_args.max_unserved_load_limit_mw,
        avg_unserved_load_penalty_per_mwa=parsed_args.avg_unserved_load_penalty_per_mwa,
        export_penalty_cost_per_mwh=parsed_args.export_penalty_cost_per_mwh,
        unserved_energy_stats_threshold_mw=parsed_args.unserved_energy_stats_threshold_mw,
        output_directory=parsed_args.lb_output_directory,
        subscenario_id=parsed_args.load_balance_scenario_id,
        subscenario_name=parsed_args.load_balance_scenario_name,
    )

    conn.close()


if __name__ == "__main__":
    main()
