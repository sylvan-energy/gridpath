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

import contextlib
import io
import unittest

from data_toolkit.run_data_toolkit import (
    check_project_step_settings_consistency,
)


def make_settings_dict(rows_by_script):
    """
    Build the orchestrator's settings_dict shape from
    {script: [(setting, value), ...]}: regular settings only (no
    true/false flags needed for these tests).
    """
    return {
        script: [(setting, value, None, None) for setting, value in rows]
        for script, rows in rows_by_script.items()
    }


class TestSettingsConsistencyCheck(unittest.TestCase):
    def run_check(self, settings_dict, mode="warn"):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            mismatches = check_project_step_settings_consistency(
                settings_dict=settings_dict, mode=mode
            )
        return mismatches, output.getvalue()

    def test_consistent_settings_pass(self):
        settings_dict = make_settings_dict(
            {
                "eia860_to_project_portfolio_input_csvs": [
                    ("footprint", "Region1"),
                    ("study_year", "2030"),
                ],
                "eia860_to_project_specified_capacity_input_csvs": [
                    ("footprint", "Region1"),
                    ("study_year", "2030"),
                ],
            }
        )
        mismatches, output = self.run_check(settings_dict)

        self.assertEqual(mismatches, [])
        self.assertNotIn("WARNING", output)

    def test_explicit_drift_flagged(self):
        settings_dict = make_settings_dict(
            {
                "eia860_to_project_portfolio_input_csvs": [
                    ("footprint", "Region1"),
                ],
                "eia860_to_project_specified_capacity_input_csvs": [
                    ("footprint", "Region2"),
                ],
            }
        )
        mismatches, output = self.run_check(settings_dict)

        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0][0], "footprint")
        self.assertIn("WARNING", output)
        self.assertIn("footprint", output)
        self.assertIn("Region1", output)
        self.assertIn("Region2", output)

    def test_explicit_vs_default_drift_flagged(self):
        # One step sets footprint explicitly, the other falls back to its
        # parser default ('western') — that IS drift, and exactly the case
        # a typo'd setting name produces (parse_known_args ignores it)
        settings_dict = make_settings_dict(
            {
                "eia860_to_project_portfolio_input_csvs": [
                    ("footprint", "Region1"),
                ],
                "eia860_to_project_specified_capacity_input_csvs": [
                    ("output_directory", "somewhere"),
                ],
            }
        )
        mismatches, output = self.run_check(settings_dict)

        self.assertEqual([m[0] for m in mismatches], ["footprint"])
        self.assertIn("western", output)

    def test_steps_without_a_setting_not_compared(self):
        # The fuel step's parser has no aggregation settings — keyed
        # aggregation on the other steps must not be flagged against it
        settings_dict = make_settings_dict(
            {
                "eia860_to_project_portfolio_input_csvs": [
                    ("project_aggregation", "agg_project_keyed"),
                    ("aggregation_dimensions", "technology_description"),
                ],
                "eia860_to_project_specified_capacity_input_csvs": [
                    ("project_aggregation", "agg_project_keyed"),
                    ("aggregation_dimensions", "technology_description"),
                ],
                "eia860_to_project_fuel_input_csvs": [
                    ("output_directory", "somewhere"),
                ],
            }
        )
        mismatches, output = self.run_check(settings_dict)

        self.assertEqual(mismatches, [])

    def test_error_mode_raises(self):
        settings_dict = make_settings_dict(
            {
                "eia860_to_project_portfolio_input_csvs": [
                    ("ba_source", "eia860"),
                ],
                "eia860_to_project_opchar_input_csvs": [
                    ("ba_source", "eia930a"),
                ],
            }
        )
        with self.assertRaises(ValueError):
            self.run_check(settings_dict, mode="error")

    def test_off_mode_skips(self):
        settings_dict = make_settings_dict(
            {
                "eia860_to_project_portfolio_input_csvs": [
                    ("footprint", "Region1"),
                ],
                "eia860_to_project_specified_capacity_input_csvs": [
                    ("footprint", "Region2"),
                ],
            }
        )
        mismatches, output = self.run_check(settings_dict, mode="off")

        self.assertEqual(mismatches, [])
        self.assertNotIn("WARNING", output)

    def test_single_project_step_skipped(self):
        settings_dict = make_settings_dict(
            {
                "eia860_to_project_portfolio_input_csvs": [
                    ("footprint", "Region1"),
                ],
                "eia930_load_zone_input_csvs": [
                    ("footprint", "Region2"),
                ],
            }
        )
        mismatches, output = self.run_check(settings_dict)

        # Only one PROJECT step present; the system step is not part of
        # the project-step consistency contract
        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
