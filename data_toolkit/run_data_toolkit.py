# Copyright 2016-2025 Blue Marble Analytics LLC.
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

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser

import pandas as pd
import sys

# GridPath modules
from db import create_database
from data_toolkit import load_raw_data
from data_toolkit.temporal import (
    create_temporal_scenarios,
    create_monte_carlo_weather_draws,
    create_monte_carlo_weather_draw_profiles,
)
from data_toolkit.system import (
    eia930_load_zone_input_csvs,
    create_monte_carlo_load_input_csvs,
    create_sync_load_input_csvs,
)
from data_toolkit.project.portfolios import (
    eia860_to_project_portfolio_input_csvs,
)
from data_toolkit.project.load_zones import (
    eia860_to_project_load_zone_input_csvs,
)
from data_toolkit.project.capacity_specified import (
    eia860_to_project_specified_capacity_input_csvs,
)
from data_toolkit.project.fixed_cost import (
    eia860_to_project_fixed_cost_input_csvs,
)
from data_toolkit.project.availability import (
    eia860_to_project_availability_input_csvs,
)
from data_toolkit.project.availability.outages import (
    create_availability_iteration_input_csvs,
)
from data_toolkit.project.availability.weather_derates import (
    create_sync_gen_weather_derate_input_csvs,
    create_monte_carlo_gen_weather_derate_input_csvs,
)
from data_toolkit.project.opchar import (
    eia860_to_project_opchar_input_csvs,
)
from data_toolkit.project.opchar.fuels import (
    eia860_to_project_fuel_input_csvs,
)
from data_toolkit.project.opchar.heat_rates import (
    eia860_to_project_heat_rate_input_csvs,
)
from data_toolkit.project.opchar.var_profiles import (
    create_monte_carlo_var_gen_input_csvs,
    create_sync_var_gen_input_csvs,
)
from data_toolkit.project.opchar.hydro import (
    create_hydro_iteration_input_csvs,
)
from data_toolkit.fuels import (
    eiaaeo_to_fuel_chars_input_csvs,
    eiaaeo_fuel_price_input_csvs,
)
from data_toolkit.transmission.portfolios import (
    eia930_to_transmission_portfolio_input_csvs,
)
from data_toolkit.transmission.load_zones import (
    eia930_to_transmission_load_zone_input_csvs,
)
from data_toolkit.transmission.capacity_specified import (
    eia930_to_transmission_specified_capacity_input_csvs,
)
from data_toolkit.transmission.availability import (
    eia930_to_transmission_availability_input_csvs,
)
from data_toolkit.transmission.opchar import (
    eia930_to_transmission_opchar_input_csvs,
)
from data_toolkit import manual_adjustments

# TODO: add checks if files exists, tell user to delete before running


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-s", "--settings_csv", default="./settings.csv")
    parser.add_argument("-q", "--quiet", default=False, action="store_true")
    # Run only a single Data Toolkit step
    parser.add_argument(
        "-step",
        "--single_step_only",
        choices=[
            "create_database",
            "load_raw_data",
            "create_sync_load_input_csvs",
            "create_sync_var_gen_input_csvs",
            "create_monte_carlo_weather_draws",
            "create_monte_carlo_weather_draw_profiles",
            "create_monte_carlo_load_input_csvs",
            "create_monte_carlo_var_gen_input_csvs",
            "create_hydro_iteration_input_csvs",
            "create_availability_iteration_input_csvs",
            "create_sync_gen_weather_derate_input_csvs",
            "create_monte_carlo_gen_weather_derate_input_csvs",
            "create_temporal_scenarios",
            "create_project_input_csvs",
            "create_transmission_input_csvs",
            "create_fuel_input_csvs",
            "eia860_to_project_portfolio_input_csvs",
        ],
        help="Run only the specified GridPath Data Toolkit step. All others "
        "will be skipped. If not specified, all steps in the settings "
        "file will be run.",
    )

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_setting(settings_df, script, setting):
    try:
        return settings_df[
            (settings_df["script"] == script) & (settings_df["setting"] == setting)
        ]["value"].values[0]
    except IndexError:
        return None


def determine_skip(single_step_only, settings_dict, script_name):
    # If we are running a different step; skip
    if single_step_only is not None and single_step_only != script_name:
        skip = True
    # If we have specifically called for this step or we find it in the
    # settings, don't skip
    elif single_step_only == script_name or script_name in settings_dict.keys():
        skip = False
    # Otherwise, skip
    else:
        skip = True

    return skip


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    # Get the settings
    settings_df = pd.read_csv(parsed_args.settings_csv)

    settings_dict = {}
    for index, row in settings_df.iterrows():
        if row["script"] not in settings_dict.keys():
            settings_dict[row["script"]] = [
                (
                    row["setting"],
                    row["value"],
                    row["script_true_false_arg"],
                    row["reverse_default_behavior"],
                )
            ]
        else:
            settings_dict[row["script"]].append(
                (
                    row["setting"],
                    row["value"],
                    row["script_true_false_arg"],
                    row["reverse_default_behavior"],
                )
            )

    for script_name in settings_dict.keys():
        skip = determine_skip(
            single_step_only=parsed_args.single_step_only,
            settings_dict=settings_dict,
            script_name=script_name,
        )
        if not skip:
            settings_list = []
            for setting in settings_dict[script_name]:
                if pd.isna(setting[2]) or setting[2] == 0:
                    settings_list.append(f"--{setting[0]}")
                    settings_list.append(setting[1])
                else:
                    settings_list.append(f"--{setting[0]}" if int(setting[3]) else "")

            settings_list.append("--quiet" if parsed_args.quiet else "")

            # Run the script's main function with the requested arguments
            getattr(globals()[script_name], "main")(settings_list)


if __name__ == "__main__":
    main()
