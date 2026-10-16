# Copyright 2016-2023 Blue Marble Analytics LLC.
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
from importlib import import_module
import os.path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest

import pandas as pd

from gridpath.auxiliary.db_interface import import_csv
from gridpath.project import PROJECT_TIMEPOINT_DF
from tests.common_functions import create_abstract_model, add_components_and_load_data
from tests.project.operations.common_functions import get_project_operational_timepoints

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)
DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db", "db_schema.sql"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.frequency_response_balancing_areas",
    "project",
    "project.capacity.capacity",
]
NAME_OF_MODULE_BEING_TESTED = "project.operations.reserves.frequency_response"
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


class TestProjFrequencyResponse(unittest.TestCase):
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
        Test that the data loaded are as expected
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

        # Set: FREQUENCY_RESPONSE_PROJECTS
        expected_projects = sorted(
            [
                "Gas_CCGT",
                "Gas_CCGT_New",
                "Gas_CCGT_New_Binary",
                "Gas_CCGT_z2",
                "Battery",
                "Battery_Binary",
                "Battery_Specified",
                "Hydro",
                "Hydro_NonCurtailable",
            ]
        )
        actual_projects = sorted([prj for prj in instance.FREQUENCY_RESPONSE_PROJECTS])
        self.assertListEqual(expected_projects, actual_projects)

        # Set: FREQUENCY_RESPONSE_PARTIAL_PROJECTS
        expected_partial_projects = sorted(
            ["Gas_CCGT", "Gas_CCGT_New", "Gas_CCGT_New_Binary", "Gas_CCGT_z2"]
        )
        actual_partial_projects = sorted(
            [prj for prj in instance.FREQUENCY_RESPONSE_PARTIAL_PROJECTS]
        )
        self.assertListEqual(expected_partial_projects, actual_partial_projects)

        # Param: frequency_response_ba
        expected_reserves_zone = OrderedDict(
            sorted(
                {
                    "Gas_CCGT": "Zone1",
                    "Gas_CCGT_New": "Zone1",
                    "Gas_CCGT_New_Binary": "Zone1",
                    "Gas_CCGT_z2": "Zone2",
                    "Battery": "Zone1",
                    "Battery_Binary": "Zone1",
                    "Battery_Specified": "Zone1",
                    "Hydro": "Zone1",
                    "Hydro_NonCurtailable": "Zone1",
                }.items()
            )
        )
        actual_reserves_zone = OrderedDict(
            sorted(
                {
                    prj: instance.frequency_response_ba[prj]
                    for prj in instance.FREQUENCY_RESPONSE_PROJECTS
                }.items()
            )
        )
        self.assertDictEqual(expected_reserves_zone, actual_reserves_zone)

        # Set: FREQUENCY_RESPONSE_PRJ_OPR_TMPS
        expected_prj_op_tmps = sorted(
            get_project_operational_timepoints(expected_projects)
        )
        actual_prj_op_tmps = sorted(
            [(prj, tmp) for (prj, tmp) in instance.FREQUENCY_RESPONSE_PRJ_OPR_TMPS]
        )
        self.assertListEqual(expected_prj_op_tmps, actual_prj_op_tmps)

        # Param: frequency_response_derate (defaults to 1 if not specified)
        expected_derate = OrderedDict(
            sorted(
                {
                    "Battery": 1,
                    "Battery_Binary": 1,
                    "Battery_Specified": 0.5,
                    "Gas_CCGT": 1,
                    "Gas_CCGT_New": 1,
                    "Gas_CCGT_New_Binary": 1,
                    "Gas_CCGT_z2": 1,
                    "Hydro": 1,
                    "Hydro_NonCurtailable": 1,
                }.items()
            )
        )
        actual_derate = OrderedDict(
            sorted(
                {
                    prj: instance.frequency_response_derate[prj]
                    for prj in instance.FREQUENCY_RESPONSE_PROJECTS
                }.items()
            )
        )
        self.assertDictEqual(expected_derate, actual_derate)

        # Param: frequency_response_reserve_to_energy_adjustment
        # (defaults to 0 if not specified)
        expected_adjustment = OrderedDict(sorted({"Zone1": 0.1, "Zone2": 0}.items()))
        actual_adjustment = OrderedDict(
            sorted(
                {
                    z: instance.frequency_response_reserve_to_energy_adjustment[z]
                    for z in instance.FREQUENCY_RESPONSE_BAS
                }.items()
            )
        )
        self.assertDictEqual(expected_adjustment, actual_adjustment)

    def test_export_results_import_into_database(self):
        """
        Test that the project-timepoint results exported by this module can
        be imported into the results_project_timepoint table
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
        for var in instance.Provide_Frequency_Response_MW.values():
            var.set_value(1.5)

        prj_tmps = sorted(instance.FREQUENCY_RESPONSE_PRJ_OPR_TMPS)
        d = SimpleNamespace()
        setattr(
            d,
            PROJECT_TIMEPOINT_DF,
            pd.DataFrame(
                index=pd.MultiIndex.from_tuples(
                    prj_tmps, names=["project", "timepoint"]
                )
            ),
        )
        MODULE_BEING_TESTED.export_results(
            scenario_directory="",
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
            m=instance,
            d=d,
        )

        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with open(DB_SCHEMA_FILE) as f:
            conn.executescript(f.read())

        with tempfile.TemporaryDirectory() as results_directory:
            getattr(d, PROJECT_TIMEPOINT_DF).to_csv(
                os.path.join(results_directory, "project_timepoint.csv")
            )
            import_csv(
                conn=conn,
                cursor=conn.cursor(),
                scenario_id=1,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
                quiet=True,
                results_directory=results_directory,
                which_results="project_timepoint",
            )

        expected_rows = [
            (
                prj,
                tmp,
                instance.frequency_response_ba[prj],
                1.5,
                1 if prj in instance.FREQUENCY_RESPONSE_PARTIAL_PROJECTS else 0,
            )
            for (prj, tmp) in prj_tmps
        ]
        actual_rows = conn.execute("""SELECT project, timepoint, frequency_response_ba,
            frequency_response_reserve_provision_mw,
            frequency_response_partial_reserve_provision
            FROM results_project_timepoint
            ORDER BY project, timepoint""").fetchall()
        self.assertListEqual(expected_rows, actual_rows)


if __name__ == "__main__":
    unittest.main()
