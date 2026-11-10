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
Round trip of the reserve provision ramp rate limit inputs: each reserve
module's write_model_inputs amends projects.tab from the database, and its
load_model_data must read back what was written (the column names once
diverged, so the limits were silently never loaded), for the reserve's
projects only.
"""

from importlib import import_module
import csv
import os.path
import shutil
import sqlite3
import tempfile
import unittest

from tests.common_functions import add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "test_data"
)

RESERVE_TYPES = [
    "lf_reserves_up",
    "lf_reserves_down",
    "regulation_up",
    "regulation_down",
    "frequency_response",
    "spinning_reserves",
]

OPCHAR_SCENARIO_ID = 1


class SubScenariosStub:
    PROJECT_OPERATIONAL_CHARS_SCENARIO_ID = OPCHAR_SCENARIO_ID


def read_projects_tab(path):
    with open(path, newline="") as f:
        return list(csv.reader(f, delimiter="\t"))


def write_projects_tab(path, rows):
    with open(path, "w", newline="") as f:
        csv.writer(f, delimiter="\t", lineterminator="\n").writerows(rows)


class TestReserveRampRateRoundTrip(unittest.TestCase):
    def test_ramp_rate_limits_written_are_loaded(self):
        for reserve in RESERVE_TYPES:
            with self.subTest(reserve=reserve):
                self.check_round_trip(reserve)

    def check_round_trip(self, reserve):
        module = import_module(
            ".project.operations.reserves.op_type_dependent." + reserve,
            package="gridpath",
        )
        # The existing per-reserve test module has the prerequisite modules
        test_module = import_module(
            "tests.project.operations.reserves.op_type_dependent.test_" + reserve
        )
        column = module.RESERVE_PROVISION_RAMP_RATE_LIMIT_COLUMN_NAME_IN_INPUT_FILE

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        shutil.copytree(
            os.path.join(TEST_DATA_DIRECTORY, "inputs"),
            os.path.join(tmp.name, "inputs"),
        )
        projects_tab = os.path.join(tmp.name, "inputs", "projects.tab")

        # Take the fixture's values as the database inputs and remove the
        # column, so the only way it can get back is through the writer
        rows = read_projects_tab(projects_tab)
        idx = rows[0].index(column)
        db_values = {
            row[0]: (None if row[idx] == "." else float(row[idx])) for row in rows[1:]
        }
        # Also give a limit to every project that does not provide the
        # reserve: the opchar table is shared across reserve setups, so
        # these values must be ignored rather than fail the param's index
        ba_idx = rows[0].index(f"{reserve}_ba")
        reserve_projects = {row[0] for row in rows[1:] if row[ba_idx] != "."}
        non_reserve_projects = set(db_values) - reserve_projects
        self.assertTrue(non_reserve_projects)
        for prj in non_reserve_projects:
            db_values[prj] = 0.5
        expected = {
            prj: v
            for prj, v in db_values.items()
            if prj in reserve_projects and v is not None
        }
        self.assertTrue(expected)
        write_projects_tab(projects_tab, [row[:idx] + row[idx + 1 :] for row in rows])

        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute(
            "CREATE TABLE inputs_project_operational_chars "
            "(project_operational_chars_scenario_id INTEGER, project TEXT, "
            "{} FLOAT)".format(column)
        )
        conn.executemany(
            "INSERT INTO inputs_project_operational_chars VALUES (?, ?, ?)",
            [(OPCHAR_SCENARIO_ID, prj, v) for prj, v in db_values.items()],
        )

        module.write_model_inputs(
            scenario_directory=tmp.name,
            scenario_id=1,
            subscenarios=SubScenariosStub(),
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
            conn=conn,
        )

        m, data = add_components_and_load_data(
            prereq_modules=test_module.IMPORTED_PREREQ_MODULES,
            module_to_test=module,
            test_data_dir=tmp.name,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        instance = m.create_instance(data)

        param = getattr(instance, module.RESERVE_PROVISION_RAMP_RATE_LIMIT_PARAM_NAME)
        projects = getattr(instance, module.RESERVE_PROJECTS_SET_NAME)
        self.assertSetEqual(reserve_projects, set(projects))
        self.assertDictEqual(
            expected,
            {prj: param[prj] for prj in projects if param[prj] != float("inf")},
        )

        # The limit constraint is built for every timepoint of each project
        # with a limit (and only for those)
        constraint = getattr(
            instance, module.RESERVE_PROVISION_RAMP_RATE_LIMIT_CONSTRAINT_NAME
        )
        prj_tmps = getattr(instance, module.RESERVE_PRJ_OPR_TMPS_SET_NAME)
        expected_idxs = sorted((prj, tmp) for (prj, tmp) in prj_tmps if prj in expected)
        self.assertTrue(expected_idxs)
        self.assertListEqual(expected_idxs, sorted(constraint.keys()))


if __name__ == "__main__":
    unittest.main()
