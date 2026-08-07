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
from importlib.metadata import entry_points

import pandas as pd
import sys

from gridpath.common_functions import get_version_parser

# TODO: add checks if files exists, tell user to delete before running

# Data Toolkit steps are resolved by name from this entry-point group
# (declared in pyproject.toml), not from a hardcoded import list. Each
# entry maps a step name — the name used in the settings CSV's 'script'
# column and by --single_step_only — to the module implementing it; the
# module must expose main(args_list) and parse_arguments(args_list).
# Any installed package (e.g. ra_toolkit, or third-party plugins) can
# register steps in this group, and they become runnable from the same
# settings CSV with no changes here.
STEP_ENTRY_POINT_GROUP = "gridpath.data_toolkit_steps"


def get_registered_steps():
    """
    Return {step_name: EntryPoint} for every step registered in the
    STEP_ENTRY_POINT_GROUP entry-point group across all installed
    packages. Modules are NOT imported here — call .load() on an entry
    point (or use get_step_module) to get the module.
    """
    registered_steps = {}
    for entry_point in entry_points(group=STEP_ENTRY_POINT_GROUP):
        already_registered = registered_steps.get(entry_point.name)
        if already_registered is not None and already_registered.value != (
            entry_point.value
        ):
            raise RuntimeError(
                f"Data Toolkit step '{entry_point.name}' is registered "
                f"twice with different targets: "
                f"'{already_registered.value}' and '{entry_point.value}'. "
                f"Check for conflicting installed packages."
            )
        registered_steps[entry_point.name] = entry_point

    if not registered_steps:
        raise RuntimeError(
            f"No Data Toolkit steps found in the "
            f"'{STEP_ENTRY_POINT_GROUP}' entry-point group. The installed "
            f"GridPath package metadata is likely stale — re-run "
            f"'pip install -e .' (or reinstall GridPath) and try again."
        )

    return registered_steps


def get_step_module(script_name, registered_steps=None):
    """
    Import and return the module implementing the *script_name* step.
    """
    if registered_steps is None:
        registered_steps = get_registered_steps()
    try:
        entry_point = registered_steps[script_name]
    except KeyError:
        raise ValueError(
            f"Unknown Data Toolkit step '{script_name}'. Registered "
            f"steps: {', '.join(sorted(registered_steps))}. If this step "
            f"was recently added, re-run 'pip install -e .' to refresh "
            f"the entry-point registry."
        )
    return entry_point.load()


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
        choices=sorted(get_registered_steps()),
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

    registered_steps = get_registered_steps()

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
            get_step_module(script_name, registered_steps)  # raises

    for script_name in scripts_to_run:
        settings_list = build_settings_list(
            settings_dict=settings_dict,
            script_name=script_name,
            quiet=parsed_args.quiet,
        )

        # Run the script's main function with the requested arguments
        get_step_module(script_name, registered_steps).main(settings_list)


if __name__ == "__main__":
    main()
