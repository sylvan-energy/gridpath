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
Results are exported module by module in the order of all_modules_list().
Several modules add columns to a shared results dataframe (e.g. the
transmission-timepoint dataframe) with update_results_df, and one module
writes that dataframe to CSV. Columns added after the CSV is written are
silently dropped, so every module adding to a dataframe must come before the
module writing it.
"""

import ast
from importlib import import_module
import inspect
import unittest

from gridpath.auxiliary.module_list import all_modules_list


def get_dataframe_name(module, node):
    """
    The dataframe name in getattr(d, NAME_DF), or None if node is not such a
    call
    """
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) == 2
        and isinstance(node.args[1], ast.Name)
    ):
        return getattr(module, node.args[1].id, None)
    return None


def get_dataframes_added_to_and_written(module):
    """
    The dataframes that the module's export_results adds to with
    update_results_df and the dataframes it writes with to_csv
    """
    added_to, written = set(), set()
    if not hasattr(module, "export_results"):
        return added_to, written
    tree = ast.parse(inspect.getsource(module.export_results))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "update_results_df"
            and node.args
        ):
            df = get_dataframe_name(module, node.args[0])
            if df is not None:
                added_to.add(df)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "to_csv":
            df = get_dataframe_name(module, node.func.value)
            if df is not None:
                written.add(df)
    return added_to, written


class TestResultsExportOrder(unittest.TestCase):
    def setUp(self):
        self.added_to = {}
        self.written = {}
        for position, name in enumerate(all_modules_list()):
            module = import_module("." + name, package="gridpath")
            added_to, written = get_dataframes_added_to_and_written(module)
            for df in added_to:
                self.added_to.setdefault(df, []).append((position, name))
            for df in written:
                self.written.setdefault(df, []).append((position, name))

    def test_discovery_finds_known_modules(self):
        self.assertIn(
            "project.consolidate_results",
            [name for _, name in self.written["project_timepoint_df"]],
        )
        self.assertIn(
            "transmission.operations.hurdle_costs",
            [name for _, name in self.added_to["transmission_timepoint_df"]],
        )

    def test_dataframes_written_after_all_additions(self):
        late_additions = [
            f"{adder} adds to {df} after {writer} writes it to CSV"
            for df, writers in self.written.items()
            for writer_position, writer in writers
            for adder_position, adder in self.added_to.get(df, [])
            if adder_position > writer_position
        ]
        self.assertListEqual([], late_additions)


if __name__ == "__main__":
    unittest.main()
