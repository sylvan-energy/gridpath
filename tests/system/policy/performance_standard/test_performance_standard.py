# Copyright 2022 (c) Crown Copyright, GC.
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


from collections import OrderedDict
import csv
from importlib import import_module
import os.path
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.performance_standard_zones",
    "project",
]
NAME_OF_MODULE_BEING_TESTED = "system.policy.performance_standard.performance_standard"
IMPORTED_PREREQ_MODULES = list()
for mdl in PREREQUISITE_MODULE_NAMES:
    try:
        imported_module = import_module("." + str(mdl), package="gridpath")
        IMPORTED_PREREQ_MODULES.append(imported_module)
    except ImportError:
        print("ERROR! Module " + str(mdl) + " not found.")
        sys.exit(1)
# Import the module we'll test
try:
    MODULE_BEING_TESTED = import_module(
        "." + NAME_OF_MODULE_BEING_TESTED, package="gridpath"
    )
except ImportError:
    print("ERROR! Couldn't import module " + NAME_OF_MODULE_BEING_TESTED + " to test.")


class TestPerformanceStandard(unittest.TestCase):
    """ """

    def test_add_model_components(self):
        """
        Test that there are no errors when adding model components
        :return:
        """
        create_abstract_model(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_load_model_data(self):
        """
        Test that data are loaded with no errors
        :return:
        """
        add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_data_loaded_correctly(self):
        """
        Test components initialized with data as expected
        :return:
        """
        m, data = add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        instance = m.create_instance(data)

        # Set: PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD
        expected_ps_zone_periods = sorted(
            [
                ("PS_Zone1", 2020),
                ("PS_Zone1", 2030),
                ("PS_Zone2", 2020),
                ("PS_Zone2", 2030),
            ]
        )
        actual_ps_zone_periods = sorted(
            [
                (z, p)
                for (
                    z,
                    p,
                ) in instance.PERFORMANCE_STANDARD_ZONE_PERIODS_WITH_PERFORMANCE_STANDARD
            ]
        )
        self.assertListEqual(expected_ps_zone_periods, actual_ps_zone_periods)

        expected_project_keys = sorted(
            [
                ("PS_Zone1", "Gas_CCGT", 2020),
                ("PS_Zone1", "Gas_CCGT", 2030),
                ("PS_Zone2", "Gas_CCGT", 2020),
                ("PS_Zone2", "Gas_CCGT", 2030),
                ("PS_Zone2", "Gas_CT", 2020),
                ("PS_Zone2", "Gas_CT", 2030),
            ]
        )
        self.assertListEqual(
            expected_project_keys,
            sorted(
                instance.PERFORMANCE_STANDARD_ZONE_PERIODS_PROJECTS_WITH_PERFORMANCE_STANDARD
            ),
        )

        # Param: performance_standard_tco2_per_mwh
        expected_ps = OrderedDict(
            sorted(
                {
                    ("PS_Zone1", "Gas_CCGT", 2020): 0.1,
                    ("PS_Zone1", "Gas_CCGT", 2030): 0.15,
                    ("PS_Zone2", "Gas_CCGT", 2020): 0.2,
                    ("PS_Zone2", "Gas_CCGT", 2030): 0.25,
                    ("PS_Zone2", "Gas_CT", 2020): 0.3,
                    ("PS_Zone2", "Gas_CT", 2030): 0.35,
                }.items()
            )
        )
        actual_ps = OrderedDict(
            sorted(
                {
                    (z, prj, p): instance.performance_standard_tco2_per_mwh[z, prj, p]
                    for (
                        z,
                        prj,
                        p,
                    ) in instance.PERFORMANCE_STANDARD_ZONE_PERIODS_PROJECTS_WITH_PERFORMANCE_STANDARD
                }.items()
            )
        )
        self.assertDictEqual(expected_ps, actual_ps)

        # Param: performance_standard_tco2_per_mw
        expected_ps_mw = OrderedDict(
            sorted(
                {
                    ("PS_Zone1", "Gas_CCGT", 2020): 876,
                    ("PS_Zone1", "Gas_CCGT", 2030): 1314,
                    ("PS_Zone2", "Gas_CCGT", 2020): 1752,
                    ("PS_Zone2", "Gas_CCGT", 2030): 2190,
                    ("PS_Zone2", "Gas_CT", 2020): 2628,
                    ("PS_Zone2", "Gas_CT", 2030): 3066,
                }.items()
            )
        )
        actual_ps_mw = OrderedDict(
            sorted(
                {
                    (z, prj, p): instance.performance_standard_tco2_per_mw[z, prj, p]
                    for (
                        z,
                        prj,
                        p,
                    ) in instance.PERFORMANCE_STANDARD_ZONE_PERIODS_PROJECTS_WITH_PERFORMANCE_STANDARD
                }.items()
            )
        )
        self.assertDictEqual(expected_ps_mw, actual_ps_mw)

    def test_database_inputs_and_schema_order(self):
        root = Path(__file__).resolve().parents[4]
        schema = (root / "db" / "db_schema.sql").read_text()
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        tables = [
            "inputs_temporal_periods",
            "inputs_geography_performance_standard_zones",
            "inputs_project_portfolios",
            "inputs_system_performance_standard",
            "results_system_performance_standard_project",
        ]
        for table in tables:
            definition = re.search(
                rf"CREATE TABLE {table}\s*\(.*?\);", schema, re.DOTALL
            )
            self.assertIsNotNone(definition, table)
            conn.executescript(definition.group())

        for table in tables[-2:]:
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            self.assertLess(columns.index("project"), columns.index("period"))

        conn.executescript(
            """
            INSERT INTO inputs_temporal_periods (temporal_scenario_id, period)
                VALUES (11, 2020), (11, 2030);
            INSERT INTO inputs_geography_performance_standard_zones
                (performance_standard_zone_scenario_id, performance_standard_zone)
                VALUES (22, 'PS_Zone1');
            INSERT INTO inputs_project_portfolios
                (project_portfolio_scenario_id, project)
                VALUES (33, 'Gas_CCGT'), (33, 'Gas_CT');
            """
        )
        expected = [
            ("PS_Zone1", "Gas_CCGT", 2020, 0.1, 876),
            ("PS_Zone1", "Gas_CCGT", 2030, 0.2, 1752),
            ("PS_Zone1", "Gas_CT", 2020, 0.3, 2628),
            ("PS_Zone1", "Gas_CT", 2030, 0.4, 3504),
        ]
        conn.executemany(
            """INSERT INTO inputs_system_performance_standard
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (44, z, prj, p, 1, 1, energy, capacity)
                for z, prj, p, energy, capacity in reversed(expected)
            ],
        )
        conn.execute(
            """INSERT INTO inputs_system_performance_standard
            VALUES (45, 'PS_Zone1', 'Gas_CCGT', 2020, 1, 1, 9, 9)"""
        )
        subscenarios = SimpleNamespace(
            TEMPORAL_SCENARIO_ID=11,
            PERFORMANCE_STANDARD_ZONE_SCENARIO_ID=22,
            PROJECT_PORTFOLIO_SCENARIO_ID=33,
            PERFORMANCE_STANDARD_SCENARIO_ID=44,
        )
        actual = MODULE_BEING_TESTED.get_inputs_from_database(
            1, subscenarios, "", "", "", 1, 1, conn
        ).fetchall()
        self.assertListEqual(expected, actual)

    def test_write_model_inputs_column_order(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory) / "inputs"
            inputs.mkdir()
            with patch.object(
                MODULE_BEING_TESTED,
                "get_inputs_from_database",
                return_value=[("PS_Zone1", "Gas_CCGT", 2020, 0.1, None)],
            ):
                MODULE_BEING_TESTED.write_model_inputs(
                    directory, 1, None, "", "", "", "", "", None
                )
            with (inputs / "performance_standard.tab").open(newline="") as stream:
                rows = list(csv.reader(stream, delimiter="\t"))
        self.assertListEqual(
            [
                [
                    "performance_standard_zone",
                    "project",
                    "period",
                    "performance_standard_tco2_per_mwh",
                    "performance_standard_tco2_per_mw",
                ],
                ["PS_Zone1", "Gas_CCGT", "2020", "0.1", "."],
            ],
            rows,
        )

    def test_project_results_index_order(self):
        m, data = add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        instance = m.create_instance(data)
        package = import_module("gridpath.system.policy.performance_standard")
        consolidate = import_module(
            "gridpath.system.policy.performance_standard.consolidate_results"
        )
        dynamic_components = SimpleNamespace()
        package.export_results("", "", "", "", "", "", instance, dynamic_components)
        MODULE_BEING_TESTED.export_results(
            "", "", "", "", "", "", instance, dynamic_components
        )
        results = getattr(dynamic_components, package.PERFORMANCE_STANDARD_Z_PRJ_PRD_DF)
        self.assertListEqual(
            ["performance_standard_zone", "project", "period"],
            list(results.index.names),
        )
        self.assertEqual(
            0.35,
            results.loc[
                ("PS_Zone2", "Gas_CT", 2030), "performance_standard_tco2_per_mwh"
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "results").mkdir()
            consolidate.export_results(
                directory, "", "", "", "", "", instance, dynamic_components
            )
            output = (
                Path(directory) / "results" / "system_performance_standard_project.csv"
            )
            with output.open(newline="") as stream:
                rows = list(csv.reader(stream))
        self.assertListEqual(
            ["performance_standard_zone", "project", "period"], rows[0][:3]
        )
        self.assertEqual(6, len(rows) - 1)

    def test_input_fixture_column_order(self):
        root = Path(__file__).resolve().parents[4]
        files = list(
            (root / "examples").glob(
                "test_performance_standard*/inputs/performance_standard.tab"
            )
        )
        files.append(Path(TEST_DATA_DIRECTORY) / "inputs" / "performance_standard.tab")
        files.extend(
            (
                root
                / "db"
                / "csvs_test_examples"
                / "policy"
                / "performance_standard"
                / "system_performance_standard"
            ).glob("*.csv")
        )
        self.assertEqual(9, len(files))
        for path in files:
            with self.subTest(path=path):
                with path.open(newline="") as stream:
                    reader = csv.reader(
                        stream, delimiter="\t" if path.suffix == ".tab" else ","
                    )
                    header = next(reader)
                    self.assertListEqual(
                        ["performance_standard_zone", "project", "period"], header[:3]
                    )
                    for row in reader:
                        self.assertEqual(len(header), len(row))


if __name__ == "__main__":
    unittest.main()
