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

"""
Generic engine for running toolkit steps listed in a settings CSV.

A "toolkit" here is a settings-CSV-driven pipeline (the GridPath Data
Toolkit and the GridPath RA Toolkit) whose steps are registered in an
entry-point group declared in pyproject.toml. Each entry in the group maps
a step name — the name used in the settings CSV's 'script' column and by
--single_step_only — to the module implementing it; the module must expose
main(args_list) and parse_arguments(args_list). Any installed package can
register steps in a group, and they become runnable from the same settings
CSV with no changes here.

Each toolkit's runner command (gridpath_run_data_toolkit,
gridpath_run_ra_toolkit) is a thin wrapper around this engine,
parameterized by its own entry-point group.
"""

from argparse import ArgumentParser
from importlib.metadata import entry_points

import pandas as pd
import sys

from gridpath.common_functions import get_version_parser


def get_registered_steps(entry_point_group):
    """
    Return {step_name: EntryPoint} for every step registered in the
    *entry_point_group* entry-point group across all installed packages.
    Modules are NOT imported here — call .load() on an entry point (or use
    get_step_module) to get the module.
    """
    registered_steps = {}
    for entry_point in entry_points(group=entry_point_group):
        already_registered = registered_steps.get(entry_point.name)
        if already_registered is not None and already_registered.value != (
            entry_point.value
        ):
            raise RuntimeError(
                f"Toolkit step '{entry_point.name}' is registered "
                f"twice with different targets: "
                f"'{already_registered.value}' and '{entry_point.value}'. "
                f"Check for conflicting installed packages."
            )
        registered_steps[entry_point.name] = entry_point

    if not registered_steps:
        raise RuntimeError(
            f"No toolkit steps found in the "
            f"'{entry_point_group}' entry-point group. The installed "
            f"GridPath package metadata is likely stale — re-run "
            f"'pip install -e .' (or reinstall GridPath) and try again."
        )

    return registered_steps


def get_step_module(script_name, entry_point_group, registered_steps=None):
    """
    Import and return the module implementing the *script_name* step from
    the *entry_point_group* entry-point group.
    """
    if registered_steps is None:
        registered_steps = get_registered_steps(entry_point_group)
    try:
        entry_point = registered_steps[script_name]
    except KeyError:
        raise ValueError(
            f"Unknown step '{script_name}' in the '{entry_point_group}' "
            f"entry-point group. Registered "
            f"steps: {', '.join(sorted(registered_steps))}. If this step "
            f"was recently added, re-run 'pip install -e .' to refresh "
            f"the entry-point registry; if it belongs to a different "
            f"toolkit, run it with that toolkit's own command."
        )
    return entry_point.load()


def parse_arguments(args, entry_point_group):
    """
    :param args: the script arguments specified by the user
    :param entry_point_group: the entry-point group whose registered step
        names are the valid --single_step_only choices
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-s", "--settings_csv", default="./settings.csv")
    parser.add_argument("-q", "--quiet", default=False, action="store_true")
    # Run only a single toolkit step
    parser.add_argument(
        "-step",
        "--single_step_only",
        choices=sorted(get_registered_steps(entry_point_group)),
        help="Run only the specified toolkit step. All others "
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


def build_settings_list(settings_dict, script_name, quiet):
    """
    The argument list for a script's main(), built from its settings-CSV
    rows: regular settings become '--setting value' pairs; rows flagged
    script_true_false_arg become a bare '--setting' flag (or nothing,
    per reverse_default_behavior).
    """
    settings_list = []
    for setting in settings_dict[script_name]:
        if pd.isna(setting[2]) or setting[2] == 0:
            settings_list.append(f"--{setting[0]}")
            settings_list.append(setting[1])
        else:
            settings_list.append(f"--{setting[0]}" if int(setting[3]) else "")

    settings_list.append("--quiet" if quiet else "")

    return settings_list


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


def run_steps(args, entry_point_group):
    """
    Run the steps listed in the settings CSV (or the single requested
    step), resolving each step's module from the *entry_point_group*
    entry-point group. This is the generic main() behind each toolkit's
    runner command.
    """
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args, entry_point_group=entry_point_group)

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

    registered_steps = get_registered_steps(entry_point_group)

    scripts_to_run = [
        script_name
        for script_name in settings_dict.keys()
        if not determine_skip(
            single_step_only=parsed_args.single_step_only,
            settings_dict=settings_dict,
            script_name=script_name,
        )
    ]

    # Validate all requested step names upfront so an unknown name fails
    # before any step has run (and had side effects)
    for script_name in scripts_to_run:
        if script_name not in registered_steps:
            get_step_module(script_name, entry_point_group, registered_steps)  # raises

    for script_name in scripts_to_run:
        settings_list = build_settings_list(
            settings_dict=settings_dict,
            script_name=script_name,
            quiet=parsed_args.quiet,
        )

        # Run the script's main function with the requested arguments
        get_step_module(script_name, entry_point_group, registered_steps).main(
            settings_list
        )
