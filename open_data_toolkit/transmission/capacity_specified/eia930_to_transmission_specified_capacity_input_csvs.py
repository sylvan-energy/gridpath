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
Form EIA 930 Transmission Capacity
**********************************

Create specified capacity CSV for a EIA930-based transmission portfolio.

.. note:: The query in this module is consistent with the transmission selection
    from ``eia930_to_transmission_portfolio_input_csvs``.

.. warning:: Only minimal, manual data cleaning has been conducted on this
    dataset. More robust processing is required for usability past the demo
    stage.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia930_to_transmission_specified_capacity_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

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
    * study_year
    * footprint
    * load_zone_level
    * transmission_specified_capacity_scenario_id
    * transmission_specified_capacity_scenario_name

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import numpy as np
import os.path
import pandas as pd
import sys

from db.common_functions import connect_to_database
from open_data_toolkit.geographic_scope import (
    LOAD_ZONE_LEVEL_CHOICES,
    check_custom_zone_level_ready,
    report_footprint_type,
)
from open_data_toolkit.transmission.transmission_data_filters_common import (
    get_all_links_sql,
    get_interchange_relation_str,
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
    parser.add_argument("-y", "--study_year", default=2026)
    parser.add_argument(
        "-fp",
        "--footprint",
        default="western",
        help="The study footprint: an EIA930 region or interconnect value "
        "from the BA map (e.g. 'CAL' or 'western'), or 'all' for no "
        "footprint filter (every mapped BA with a load zone at the chosen "
        "load-zone level). Defaults to 'western'.",
    )
    parser.add_argument(
        "-lzl",
        "--load_zone_level",
        default="baa",
        choices=list(LOAD_ZONE_LEVEL_CHOICES),
        help="The level at which to define the transmission network: lines "
        "between BAs, EIA930 regions, or interconnects (at the aggregated "
        "levels, parallel BA pairs collapse into one line per zone pair, "
        "and intra-zone links are dropped); at the 'all' level the whole "
        "--footprint is a single zone, so the network is empty; 'custom' "
        "uses the user-defined zones applied by gridpath_apply_custom_zones "
        "(BAs without a custom zone are excluded). "
        "Must match the level used for the load-zone and project-level "
        "steps. Defaults to 'baa'.",
    )

    parser.add_argument(
        "-o",
        "--output_directory",
        default="../../csvs_open_data/transmission/capacity_specified",
    )
    parser.add_argument(
        "-cap_id", "--transmission_specified_capacity_scenario_id", default=1
    )
    parser.add_argument(
        "-cap_name", "--transmission_specified_capacity_scenario_name", default="base"
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_tx_capacities(
    conn,
    all_links,
    interchange_str,
    period,
    threshold,
    output_directory,
    subscenario_id,
    subscenario_name,
):
    df_list = []
    from_to_combos = []
    for lz_from, lz_to in all_links:
        if (lz_from, lz_to) not in from_to_combos:
            # Exclude values abs(x) >= cap
            # TODO: this is based on a manual scan of the data; we need a more robust
            #  way of cleaning it and detecting outliers
            min_max_sql = f"""
                SELECT
                    CASE WHEN max(i1) IS NULL THEN 0 ELSE max(i1) END,
                    CASE WHEN min(i1) IS NULL THEN 0 ELSE min(i1) END,
                    CASE WHEN max(i2) IS NULL THEN 0 ELSE max(i2) END,
                    CASE WHEN min(i2) IS NULL THEN 0 ELSE min(i2) END
                FROM (
                SELECT datetime_pst_he, from1, to1, i1, from2, to2, i2, i1/i2, i2/i1 FROM (
                SELECT datetime_pst_he, balancing_authority_code_eia as from1, balancing_authority_code_adjacent_eia as to1, interchange_reported_mwh as i1
                FROM {interchange_str}
                WHERE balancing_authority_code_eia = '{lz_from}' AND 
                balancing_authority_code_adjacent_eia = '{lz_to}'
                ) as tbl1
                JOIN (
                SELECT datetime_pst_he, balancing_authority_code_eia as from2, balancing_authority_code_adjacent_eia as to2, interchange_reported_mwh as i2
                FROM {interchange_str}
                WHERE balancing_authority_code_eia = '{lz_to}' 
                AND balancing_authority_code_adjacent_eia = '{lz_from}'
                ) as tbl2
                USING (datetime_pst_he)
                )
            """

            c = conn.cursor()
            max_i1, min_i1, max_i2, min_i2 = c.execute(min_max_sql).fetchone()

            # If the same is reported on both sides (within some threshold
            # percentage), use values directly and take the average
            if (1 - threshold) * -min_i2 <= max_i1 <= (1 + threshold) * -min_i2 or (
                1 - threshold
            ) * max_i1 <= -min_i2 <= (1 + threshold) * max_i1:
                max_to_use = np.mean([max_i1, -min_i2])
            else:
                max_to_use = min([max_i1, -min_i2])

            if (1 - threshold) * max_i2 <= -min_i1 <= (1 + threshold) * max_i2 or (
                1 - threshold
            ) * -min_i1 <= max_i2 <= (1 + threshold) * -min_i1:
                min_to_use = np.mean([-min_i1, max_i2])
            else:
                min_to_use = min([-min_i1, max_i2])

            tx_capacity = max([max_to_use, min_to_use])

            df = pd.DataFrame(
                {
                    "transmission_line": [f"{lz_from}_{lz_to}"],
                    "period": [period],
                    "min_mw": [-tx_capacity],
                    "max_mw": [tx_capacity],
                    "fixed_cost_per_mw_yr": [0],
                }
            )

            df_list.append(df)

            from_to_combos.append((lz_from, lz_to))
            from_to_combos.append((lz_to, lz_from))

    # Concat the individual line dataframes for export; no links (e.g. at
    # the 'all' load-zone level, where a single zone has no transmission)
    # means a header-only CSV
    if df_list:
        df = pd.concat(df_list)
    else:
        df = pd.DataFrame(
            columns=[
                "transmission_line",
                "period",
                "min_mw",
                "max_mw",
                "fixed_cost_per_mw_yr",
            ]
        )
    df.to_csv(
        os.path.join(output_directory, f"{subscenario_id}_{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating transmission specified capacity inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    conn = connect_to_database(db_path=parsed_args.database)

    report_footprint_type(
        conn=conn, footprint=parsed_args.footprint, quiet=parsed_args.quiet
    )
    check_custom_zone_level_ready(
        conn=conn,
        load_zone_level=parsed_args.load_zone_level,
        footprint=parsed_args.footprint,
    )

    c = conn.cursor()

    all_links = c.execute(
        get_all_links_sql(
            footprint=parsed_args.footprint,
            load_zone_level=parsed_args.load_zone_level,
        )
    ).fetchall()

    get_tx_capacities(
        conn=conn,
        all_links=all_links,
        interchange_str=get_interchange_relation_str(
            footprint=parsed_args.footprint,
            load_zone_level=parsed_args.load_zone_level,
            max_value_exclude=19000,
        ),
        period=parsed_args.study_year,
        threshold=0.5,
        output_directory=parsed_args.output_directory,
        subscenario_id=parsed_args.transmission_specified_capacity_scenario_id,
        subscenario_name=parsed_args.transmission_specified_capacity_scenario_name,
    )

    conn.close()


if __name__ == "__main__":
    main()
