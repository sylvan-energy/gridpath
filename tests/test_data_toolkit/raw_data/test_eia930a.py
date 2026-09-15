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

import unittest

import pandas as pd

from data_toolkit.raw_data.eia930a import RAW_CSV_COLUMNS, convert_eia930a_sheets


class TestEIA930AConversion(unittest.TestCase):
    """
    Test combining the workbook's three schedules (with their differing
    column sets, including EIA's 'Opeartion Month' typo) into the raw CSV
    shape.
    """

    def test_convert_eia930a_sheets(self):
        schedule_dfs = {
            2: pd.DataFrame(
                {
                    "BA Code": ["Zone1"],
                    "Plant Name": ["Gas Plant"],
                    "EIA Plant ID": ["1"],
                    "EIA Generator ID": ["1"],
                    "Plant ID (EIA-930A)": [None],
                    "Generator ID (EIA-930A)": [None],
                    "Electric Generator Technology": ["Natural Gas Fired"],
                    "Nameplate Capacity (MW) (EIA-860)": ["100"],
                    "State (EIA-860)": ["CA"],
                    "County (EIA-860)": ["Kern"],
                    "Latitude (EIA-860)": ["35.0"],
                    "Longitude (EIA-860)": ["-118.0"],
                    "Operation Year (EIA-860)": ["2010"],
                    "Opeartion Month (EIA-860)": ["6"],
                    "Nameplate Capacity (MW) (EIA-930A)": [None],
                    "State (EIA-930A)": [None],
                    "County (EIA-930A)": [None],
                }
            ),
            3: pd.DataFrame(
                {
                    "BA Code": ["Zone1"],
                    "Plant Name": ["Planned Plant"],
                    "EIA Plant ID": ["2"],
                    "EIA Generator ID": ["P1"],
                    "Plant ID (EIA-930A)": [None],
                    "Generator ID (EIA-930A)": [None],
                    "Electric Generator Technology": ["Batteries"],
                    "Nameplate Capacity (MW) (EIA-860)": ["50"],
                    "State (EIA-860)": ["CA"],
                    "County (EIA-860)": ["Kern"],
                    "Latitude (EIA-860)": ["35.1"],
                    "Longitude (EIA-860)": ["-118.1"],
                    "Planned Operation Year (EIA-860)": ["2027"],
                    "Planned Operation Month (EIA-860)": ["3"],
                    "Nameplate Capacity (MW) (EIA-930A)": [None],
                    "State (EIA-930A)": [None],
                    "County (EIA-930A)": [None],
                }
            ),
            4: pd.DataFrame(
                {
                    "BA Code": ["Zone2"],
                    "Plant Name": ["Tied Plant"],
                    "EIA Plant ID": ["3"],
                    "EIA Generator ID": ["1"],
                    "Plant ID (EIA-930A)": [None],
                    "Generator ID (EIA-930A)": [None],
                    "Generator Reported on EIA-930A Schedule 2?": ["Yes"],
                    "BAs having a Pseudo-Tie or Dynamic Relationship": ["Zone1,ZoneX"],
                    "Electric Generator Technology": ["Conventional Hydro"],
                    "Nameplate Capacity (MW) (EIA-860)": ["25"],
                    "State (EIA-860)": ["WA"],
                    "County (EIA-860)": ["Grant"],
                    "Latitude (EIA-860)": ["47.6"],
                    "Longitude (EIA-860)": ["-119.3"],
                    "Operation Year (EIA-860)": ["1987"],
                    "Opeartion Month (EIA-860)": ["1"],
                    "Nameplate Capacity (MW) (EIA-930A)": [None],
                    "State (EIA-930A)": [None],
                    "County (EIA-930A)": [None],
                }
            ),
        }

        df = convert_eia930a_sheets(schedule_dfs=schedule_dfs, data_year=2024)

        self.assertEqual(df.columns.tolist(), RAW_CSV_COLUMNS)
        self.assertEqual(df["schedule"].tolist(), [2, 3, 4])
        self.assertEqual(df["data_year"].unique().tolist(), [2024])
        # Schedule-specific columns land in the right place: planned dates
        # fill operation_year/month for schedule 3, pseudo-tie info only on
        # schedule 4
        self.assertEqual(df["operation_year"].tolist(), ["2010", "2027", "1987"])
        self.assertEqual(df["pseudo_tie_bas"].tolist(), [None, None, "Zone1,ZoneX"])
        self.assertEqual(df["reported_on_schedule_2"].tolist(), [None, None, "Yes"])
        self.assertEqual(df["ba"].tolist(), ["Zone1", "Zone1", "Zone2"])


if __name__ == "__main__":
    unittest.main()
