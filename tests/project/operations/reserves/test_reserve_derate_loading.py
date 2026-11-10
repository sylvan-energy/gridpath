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
The reserve provision derates come from projects.tab, which lists every
project in the portfolio; only the reserve's projects may be loaded into the
derate param (it is indexed by them), so a derate specified for a project
that does not provide the reserve is ignored rather than failing the model
build.
"""

from importlib import import_module
import csv
import os.path
import shutil
import tempfile
import unittest

from tests.common_functions import add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

RESERVE_TYPES = [
    "lf_reserves_up",
    "lf_reserves_down",
    "regulation_up",
    "regulation_down",
    "frequency_response",
    "spinning_reserves",
]


def read_tab(path):
    with open(path, newline="") as f:
        return list(csv.reader(f, delimiter="\t"))


class TestReserveDerateLoading(unittest.TestCase):
    def test_derates_load_for_reserve_projects_only(self):
        for reserve in RESERVE_TYPES:
            with self.subTest(reserve=reserve):
                self.check_derates(reserve)

    def check_derates(self, reserve):
        module = import_module(
            ".project.operations.reserves." + reserve, package="gridpath"
        )
        test_module = import_module("tests.project.operations.reserves.test_" + reserve)
        column = module.RESERVE_PROVISION_DERATE_COLUMN_NAME_IN_INPUT_FILE

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        shutil.copytree(
            os.path.join(TEST_DATA_DIRECTORY, "inputs"),
            os.path.join(tmp.name, "inputs"),
        )

        # Specify the derate for every project in projects.tab
        projects_tab = os.path.join(tmp.name, "inputs", "projects.tab")
        rows = read_tab(projects_tab)
        idx = rows[0].index(column)
        for row in rows[1:]:
            row[idx] = "0.5"
        with open(projects_tab, "w", newline="") as f:
            csv.writer(f, delimiter="\t", lineterminator="\n").writerows(rows)

        ba_idx = rows[0].index(module.BA_COLUMN_NAME_IN_INPUT_FILE)
        reserve_projects = {row[0] for row in rows[1:] if row[ba_idx] != "."}
        self.assertTrue({row[0] for row in rows[1:]} - reserve_projects)

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

        param = getattr(instance, module.RESERVE_PROVISION_DERATE_PARAM_NAME)
        projects = getattr(instance, module.RESERVE_PROJECTS_SET_NAME)
        self.assertSetEqual(reserve_projects, set(projects))
        self.assertDictEqual(
            {prj: 0.5 for prj in reserve_projects},
            {prj: param[prj] for prj in projects},
        )


if __name__ == "__main__":
    unittest.main()
