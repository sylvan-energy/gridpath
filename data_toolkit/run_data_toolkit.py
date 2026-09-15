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
Run GridPath Data Toolkit steps per a settings CSV (the
``gridpath_run_data_toolkit`` command). The steps are resolved by name
from the 'gridpath.data_toolkit_steps' entry-point group (declared in
pyproject.toml), not from a hardcoded import list — see
:mod:`gridpath.step_runner` for the generic engine. The RA Toolkit's steps
live in their own entry-point group and are run with the RA Toolkit's own
``gridpath_run_ra_toolkit`` command.

On top of the generic engine, this command cross-checks that the settings
the project-level steps must share resolve to the same values for every
project step in the settings CSV (the ``--check_settings_consistency``
argument).
"""

import sys

from gridpath import step_runner
from gridpath.step_runner import (  # noqa: F401  (re-exported)
    build_settings_list,
    get_setting,
)
from data_toolkit.project.fleet.step_common import (
    get_shared_project_step_settings,
)

# TODO: add checks if files exists, tell user to delete before running

STEP_ENTRY_POINT_GROUP = "gridpath.data_toolkit_steps"


def get_registered_steps():
    """
    Return {step_name: EntryPoint} for every registered Data Toolkit step.
    """
    return step_runner.get_registered_steps(
        entry_point_group=STEP_ENTRY_POINT_GROUP,
    )


def get_step_module(script_name, registered_steps=None):
    """
    Import and return the module implementing the *script_name* step.
    """
    return step_runner.get_step_module(
        script_name=script_name,
        entry_point_group=STEP_ENTRY_POINT_GROUP,
        registered_steps=registered_steps,
    )


def add_data_toolkit_arguments(parser):
    """
    The Data-Toolkit-specific arguments added on top of the generic step
    runner's.
    """
    parser.add_argument(
        "-check",
        "--check_settings_consistency",
        default="warn",
        choices=["warn", "error", "off"],
        help="Cross-check that the settings the project-level steps must "
        "share (footprint, study_year, ba_source, load_zone_level, the "
        "fleet-selection settings, and the aggregation settings) resolve "
        "to the same values for every project step in the settings CSV — "
        "today a typo'd or drifted setting is silently ignored by the "
        "step (parse_known_args) and the default applies. 'warn' (the "
        "default) reports mismatches loudly; 'error' fails on them; 'off' "
        "skips the check (e.g. for a settings file that deliberately "
        "builds alternative subscenarios with different settings).",
    )


def parse_arguments(args):
    return step_runner.parse_arguments(
        args=args,
        entry_point_group=STEP_ENTRY_POINT_GROUP,
        extra_parser_setup=add_data_toolkit_arguments,
    )


# The project-level steps that must share consistent settings (they all
# select and aggregate the same fleet) and the settings they must agree
# on. A step is only compared on the settings its own parser defines —
# e.g. the zone-agnostic fuel/heat-rate steps take no aggregation
# settings and are not flagged for lacking them.
PROJECT_STEP_SCRIPTS = [
    "eia860_to_project_portfolio_input_csvs",
    "eia860_to_project_load_zone_input_csvs",
    "eia860_to_project_specified_capacity_input_csvs",
    "eia860m_to_project_specified_capacity_input_csvs",
    "eia860_to_project_fixed_cost_input_csvs",
    "eia860_to_project_availability_input_csvs",
    "eia860_to_project_opchar_input_csvs",
    "eia860_to_project_fuel_input_csvs",
    "eia860_to_project_heat_rate_input_csvs",
    "manual_adjustments",
    "fleet_audit",
]
# Read from the same source the steps' parsers do (their single
# add_shared_project_step_arguments call), so this check cannot go stale
# when a shared setting is added or removed
SHARED_PROJECT_STEP_SETTINGS = list(get_shared_project_step_settings())


def check_project_step_settings_consistency(settings_dict, mode="warn"):
    """
    Resolve each project-level step's effective settings by running its
    OWN argument parser on its settings-CSV rows — so defaults, flag
    handling, and parse_known_args' silent tolerance of unknown keys are
    exactly what the step itself will see — and compare the
    must-be-consistent settings (SHARED_PROJECT_STEP_SETTINGS) across the
    project steps present in the settings CSV. Because a typo'd or
    missing setting silently falls back to the step's default, drift is
    otherwise invisible until the generated inputs mismatch (e.g. a
    portfolio aggregated one way and capacities another). *mode* 'warn'
    reports mismatches loudly (regardless of any quiet setting), 'error'
    raises, 'off' skips. Returns the list of (setting, {script: value})
    mismatches.
    """
    if mode == "off":
        return []

    present_scripts = [s for s in PROJECT_STEP_SCRIPTS if s in settings_dict]
    if len(present_scripts) < 2:
        return []

    values_by_setting = {}
    for script_name in present_scripts:
        namespace = get_step_module(script_name).parse_arguments(
            build_settings_list(
                settings_dict=settings_dict, script_name=script_name, quiet=True
            )
        )
        for setting in SHARED_PROJECT_STEP_SETTINGS:
            if hasattr(namespace, setting):
                values_by_setting.setdefault(setting, {})[script_name] = str(
                    getattr(namespace, setting)
                )

    mismatches = [
        (setting, by_script)
        for setting, by_script in values_by_setting.items()
        if len(set(by_script.values())) > 1
    ]

    if mismatches:
        mismatch_strs = []
        for setting, by_script in mismatches:
            per_script = ", ".join(
                f"{script}={value}" for script, value in sorted(by_script.items())
            )
            mismatch_strs.append(f"{setting}: {per_script}")
        message = (
            "the project-level steps in this settings CSV resolve to "
            "DIFFERENT values for settings they must share — their "
            "generated inputs will not describe the same fleet: "
            + "; ".join(mismatch_strs)
            + ". Note a typo'd setting name is silently ignored by the "
            "step and its default applies. If the mismatch is deliberate "
            "(e.g. alternative subscenarios from one settings file), run "
            "with --check_settings_consistency off."
        )
        if mode == "error":
            raise ValueError(message)
        print(f"WARNING: {message}")

    return mismatches


def settings_consistency_pre_run_hook(settings_dict, parsed_args):
    """
    Cross-check the settings the project-level steps must share before
    running anything (skipped when running a single step).
    """
    if parsed_args.single_step_only is None:
        check_project_step_settings_consistency(
            settings_dict=settings_dict,
            mode=parsed_args.check_settings_consistency,
        )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    step_runner.run_steps(
        args=args,
        entry_point_group=STEP_ENTRY_POINT_GROUP,
        extra_parser_setup=add_data_toolkit_arguments,
        pre_run_hook=settings_consistency_pre_run_hook,
    )


if __name__ == "__main__":
    main()
