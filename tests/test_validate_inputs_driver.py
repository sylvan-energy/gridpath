# Copyright 2026 Sylvan Energy Analytics LLC
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
The input-validation driver must call each module's validate_inputs exactly
once per (weather, hydro, availability) iteration x subproblem x stage. Until
September 2026 main() looped over the iterations around a function that
already looped over them, so every validator ran N times per iteration for
N iterations (two hours to validate a 15-iteration ensemble).
"""

import types
import unittest
from unittest import mock

from gridpath import validate_inputs


class FakeStructure:
    # 3 weather iterations, 1 hydro, 2 availability iterations, subproblems
    # 1 and 2 with one stage each -> 3 x 2 x 2 = 12 (iteration, subproblem,
    # stage) cells
    WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT = {
        w: {0: {a: {1: [1], 2: [1]} for a in (1, 2)}} for w in (2019, 2020, 2021)
    }
    STAGE_FLAG = False


def _recording_module(calls, name):
    module = types.ModuleType(name)

    def validate(**kwargs):
        calls.append(
            (
                name,
                kwargs["weather_iteration"],
                kwargs["hydro_iteration"],
                kwargs["availability_iteration"],
                kwargs["subproblem"],
                kwargs["stage"],
            )
        )

    module.validate_inputs = validate
    return module


class TestValidateInputsDriver(unittest.TestCase):
    def test_each_module_validates_each_cell_exactly_once(self):
        calls = []
        modules = [
            _recording_module(calls, "mod_a"),
            _recording_module(calls, "mod_b"),
            types.ModuleType("no_validator"),
        ]
        validate_inputs.validate_inputs(
            scenario_structure=FakeStructure(),
            loaded_modules=modules,
            scenario_id=1,
            subscenarios=object(),
            conn=object(),
        )
        self.assertEqual(len(calls), 2 * 12)
        self.assertEqual(len(set(calls)), len(calls))  # no cell validated twice
        expected_cells = {
            (w, 0, a, sp, 1)
            for w in (2019, 2020, 2021)
            for a in (1, 2)
            for sp in (1, 2)
        }
        self.assertEqual({c[1:] for c in calls if c[0] == "mod_a"}, expected_cells)

    def test_main_calls_the_driver_once_per_scenario(self):
        # main() must not loop over the iterations around validate_inputs()
        # (that was the N-squared bug) -- pin it by counting the calls made
        # for a multi-iteration structure with everything else stubbed out
        fake_conn = mock.MagicMock()
        with (
            mock.patch.object(
                validate_inputs, "connect_to_database", return_value=fake_conn
            ),
            mock.patch.object(
                validate_inputs, "get_scenario_id_and_name", return_value=(1, "s")
            ),
            mock.patch.object(validate_inputs, "reset_input_validation"),
            mock.patch.object(validate_inputs, "OptionalFeatures") as features,
            mock.patch.object(validate_inputs, "SubScenarios"),
            mock.patch.object(
                validate_inputs,
                "get_scenario_structure_from_db",
                return_value=FakeStructure(),
            ),
            mock.patch.object(
                validate_inputs, "validate_subscenario_ids", return_value=True
            ),
            mock.patch.object(validate_inputs, "determine_modules", return_value=[]),
            mock.patch.object(validate_inputs, "load_modules", return_value=[]),
            mock.patch.object(validate_inputs, "update_validation_status"),
            mock.patch.object(validate_inputs, "validate_inputs") as driver,
        ):
            features.return_value.get_active_features.return_value = []
            validate_inputs.main(
                ["--database", "unused.db", "--scenario_id", "1", "--quiet"]
            )

        self.assertEqual(driver.call_count, 1)


if __name__ == "__main__":
    unittest.main()
