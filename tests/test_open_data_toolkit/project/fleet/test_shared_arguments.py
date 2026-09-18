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
Pin every EIA860(M)-based project step to the shared-argument profile it
declares. These settings decide which units become which projects, so a
step that quietly takes a subset of them — or re-declares one with a
drifted default — generates inputs for a different fleet than its
siblings, and nothing downstream catches that.
"""

import importlib
import unittest
from argparse import ArgumentParser

from open_data_toolkit.project.fleet.step_common import (
    add_shared_project_step_arguments,
    get_shared_project_step_settings,
)
from open_data_toolkit.run_data_toolkit import (
    PROJECT_STEP_SCRIPTS,
    SHARED_PROJECT_STEP_SETTINGS,
)

# Every project step, the module it lives in, and the shared-argument
# profile it is allowed to have. A new step belongs here; the coverage
# test below fails if one is registered with the orchestrator but not
# listed, or vice versa.
DEFAULT_PROFILE = {}
ZONE_AGNOSTIC_PROFILE = {"zone_aware": False, "aggregation": False}
POST_PROCESSING_PROFILE = {"fleet_selection": False}

STEP_PROFILES = {
    "eia860_to_project_portfolio_input_csvs": (
        "open_data_toolkit.project.portfolios",
        DEFAULT_PROFILE,
    ),
    "eia860_to_project_load_zone_input_csvs": (
        "open_data_toolkit.project.load_zones",
        DEFAULT_PROFILE,
    ),
    "eia860_to_project_availability_input_csvs": (
        "open_data_toolkit.project.availability",
        DEFAULT_PROFILE,
    ),
    "eia860_to_project_specified_capacity_input_csvs": (
        "open_data_toolkit.project.capacity_specified",
        DEFAULT_PROFILE,
    ),
    "eia860m_to_project_specified_capacity_input_csvs": (
        "open_data_toolkit.project.capacity_specified",
        DEFAULT_PROFILE,
    ),
    "eia860_to_project_fixed_cost_input_csvs": (
        "open_data_toolkit.project.fixed_cost",
        DEFAULT_PROFILE,
    ),
    "eia860_to_project_opchar_input_csvs": (
        "open_data_toolkit.project.opchar",
        DEFAULT_PROFILE,
    ),
    "eia860_to_project_power_output_group_input_csvs": (
        "open_data_toolkit.project.opchar.power_output_groups",
        DEFAULT_PROFILE,
    ),
    "fleet_audit": ("open_data_toolkit.project.fleet", DEFAULT_PROFILE),
    "eia860_to_project_fuel_input_csvs": (
        "open_data_toolkit.project.opchar.fuels",
        ZONE_AGNOSTIC_PROFILE,
    ),
    "eia860_to_project_heat_rate_input_csvs": (
        "open_data_toolkit.project.opchar.heat_rates",
        ZONE_AGNOSTIC_PROFILE,
    ),
    "manual_adjustments": ("open_data_toolkit.project", POST_PROCESSING_PROFILE),
}


def get_step_defaults(package, step):
    """The step's parsed defaults, as {setting: default}."""
    module = importlib.import_module(f"{package}.{step}")

    return vars(module.parse_arguments([]))


def get_reference_defaults(profile):
    """What add_shared_project_step_arguments alone produces."""
    parser = ArgumentParser(add_help=False)
    add_shared_project_step_arguments(parser=parser, **profile)

    return vars(parser.parse_args([]))


class TestSharedProjectStepArguments(unittest.TestCase):
    def test_every_step_takes_exactly_its_profile_s_shared_settings(self):
        all_shared = set(get_shared_project_step_settings())

        for step, (package, profile) in STEP_PROFILES.items():
            with self.subTest(step=step):
                expected = set(get_shared_project_step_settings(**profile))
                present = all_shared & set(get_step_defaults(package, step))
                self.assertEqual(
                    present,
                    expected,
                    f"{step} takes shared settings {sorted(present)}, but its "
                    f"profile declares {sorted(expected)}. Steps must take "
                    f"the whole set for their profile — call "
                    f"add_shared_project_step_arguments, do not assemble it.",
                )

    def test_no_step_drifts_from_the_shared_defaults(self):
        for step, (package, profile) in STEP_PROFILES.items():
            with self.subTest(step=step):
                step_defaults = get_step_defaults(package, step)
                for setting, default in get_reference_defaults(profile).items():
                    self.assertEqual(
                        step_defaults[setting],
                        default,
                        f"{step} has a drifted default for --{setting}: "
                        f"{step_defaults[setting]!r} instead of {default!r}.",
                    )

    def test_setting_names_match_what_the_parser_adds(self):
        """
        get_shared_project_step_settings is what the orchestrator's
        consistency check reads; it must report exactly what
        add_shared_project_step_arguments adds, for every profile.
        """
        for profile in (
            DEFAULT_PROFILE,
            ZONE_AGNOSTIC_PROFILE,
            POST_PROCESSING_PROFILE,
        ):
            with self.subTest(profile=profile):
                self.assertEqual(
                    set(get_shared_project_step_settings(**profile)),
                    set(get_reference_defaults(profile)),
                )

    def test_orchestrator_checks_every_registered_step(self):
        """
        A step consistency-checked by the orchestrator must be pinned
        here, and vice versa.
        """
        self.assertEqual(set(PROJECT_STEP_SCRIPTS), set(STEP_PROFILES))

    def test_orchestrator_shared_settings_are_the_full_set(self):
        self.assertEqual(
            set(SHARED_PROJECT_STEP_SETTINGS),
            set(get_shared_project_step_settings()),
        )


if __name__ == "__main__":
    unittest.main()
