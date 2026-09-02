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
Run GridPath RA Toolkit steps per a settings CSV (the
``gridpath_run_ra_toolkit`` command). The steps are resolved by name from
the 'gridpath.ra_toolkit_steps' entry-point group (declared in
pyproject.toml), not from a hardcoded import list — see
:mod:`gridpath.step_runner` for the generic engine. The Data Toolkit's
steps live in their own entry-point group and are run with the Data
Toolkit's own ``gridpath_run_data_toolkit`` command.
"""

import sys

from gridpath import step_runner
from gridpath.step_runner import get_setting  # noqa: F401  (re-exported)

STEP_ENTRY_POINT_GROUP = "gridpath.ra_toolkit_steps"


def get_registered_steps():
    """
    Return {step_name: EntryPoint} for every registered RA Toolkit step.
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


def parse_arguments(args):
    return step_runner.parse_arguments(
        args=args,
        entry_point_group=STEP_ENTRY_POINT_GROUP,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    step_runner.run_steps(
        args=args,
        entry_point_group=STEP_ENTRY_POINT_GROUP,
    )


if __name__ == "__main__":
    main()
