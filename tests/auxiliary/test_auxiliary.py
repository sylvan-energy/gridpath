# Copyright 2016-2023 Blue Marble Analytics LLC.
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

from pyomo.environ import AbstractModel
import os
import tempfile
import unittest

import gridpath.auxiliary.auxiliary as auxiliary_module_to_test


class TestAuxiliary(unittest.TestCase):
    """ """

    def test_join_sets(self):
        """

        :return:
        """
        mod = AbstractModel()

        # If set list empty
        set_list_empty_actual = auxiliary_module_to_test.join_sets(mod, [])
        self.assertListEqual(set_list_empty_actual, [])

        # If single set in list
        mod.set1 = [1, 2, 3]
        set_list_single_set = ["set1"]
        single_set_expected = [1, 2, 3]
        single_set_actual = auxiliary_module_to_test.join_sets(mod, set_list_single_set)
        self.assertListEqual(single_set_expected, single_set_actual)

        # If more than one set
        mod.set2 = [4, 5, 6]
        set_list_two_sets = ["set1", "set2"]
        two_sets_joined_expected = [1, 2, 3, 4, 5, 6]
        two_sets_joined_actual = auxiliary_module_to_test.join_sets(
            mod, set_list_two_sets
        )
        self.assertListEqual(two_sets_joined_expected, two_sets_joined_actual)

    def test_check_list_has_single_item(self):
        """

        :return:
        """
        with self.assertRaises(ValueError):
            auxiliary_module_to_test.check_list_has_single_item([1, 2], "Error_Msg")

    def test_find_item_position(self):
        """

        :return:
        """
        l = [1, 2, 3]
        self.assertEqual(
            [0], auxiliary_module_to_test.find_list_item_position(l=l, item=1)
        )

        self.assertEqual(
            [1], auxiliary_module_to_test.find_list_item_position(l=l, item=2)
        )

        self.assertEqual(
            [2], auxiliary_module_to_test.find_list_item_position(l=l, item=3)
        )

    def test_check_list_items_are_unique(self):
        """

        :return:
        """
        with self.assertRaises(ValueError):
            auxiliary_module_to_test.check_list_items_are_unique([1, 1])

    def test_is_number(self):
        """

        :return:
        """
        self.assertEqual(True, auxiliary_module_to_test.is_number(1))
        self.assertEqual(True, auxiliary_module_to_test.is_number(100.5))
        self.assertEqual(False, auxiliary_module_to_test.is_number("string"))

    def _write_projects_tab(self, tmp_dir, rows):
        os.makedirs(os.path.join(tmp_dir, "inputs"))
        with open(os.path.join(tmp_dir, "inputs", "projects.tab"), "w") as f:
            f.write("project\toperational_type\n")
            for prj, op_type in rows:
                f.write("{}\t{}\n".format(prj, op_type))

    def test_get_required_subtype_modules(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_projects_tab(
                tmp_dir,
                [("Prj1", "gen_spec"), ("Prj2", "gen_var"), ("Prj3", "gen_spec")],
            )
            actual = auxiliary_module_to_test.get_required_subtype_modules(
                scenario_directory=tmp_dir,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
                which_type="operational_type",
            )
            self.assertListEqual(sorted(actual), ["gen_spec", "gen_var"])

    def test_get_required_subtype_modules_unspecified_passes_through(self):
        """
        "." is GridPath's marker for an unspecified value and is returned
        as-is; whether that is allowed is decided by the type's callers.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_projects_tab(
                tmp_dir, [("Prj1", "binary"), ("Prj2", "."), ("Prj3", ".")]
            )
            actual = auxiliary_module_to_test.get_required_subtype_modules(
                scenario_directory=tmp_dir,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
                which_type="operational_type",
            )
            self.assertListEqual(sorted(actual), [".", "binary"])

    def test_get_required_subtype_modules_blank_raises(self):
        """
        A blank cell (as opposed to ".") is malformed input; the reader
        raises naming the affected entities.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_projects_tab(
                tmp_dir, [("Prj1", "gen_simple"), ("Prj2", ""), ("Prj3", "")]
            )
            with self.assertRaises(ValueError) as cm:
                auxiliary_module_to_test.get_required_subtype_modules(
                    scenario_directory=tmp_dir,
                    weather_iteration="",
                    hydro_iteration="",
                    availability_iteration="",
                    subproblem="",
                    stage="",
                    which_type="operational_type",
                )
            self.assertIn("Blank operational_type", str(cm.exception))
            self.assertIn("project(s) Prj2, Prj3", str(cm.exception))
            self.assertNotIn("Prj1", str(cm.exception))

    def test_load_subtype_modules_unspecified_raises(self):
        """
        "." reaching the loader means a required type is unspecified. It must
        raise a clear error rather than import the parent package.
        """
        with self.assertRaises(ValueError) as cm:
            auxiliary_module_to_test.load_subtype_modules(
                required_subtype_modules=["gen_simple", "."],
                package="gridpath.project.operations.operational_types",
                required_attributes=[],
            )
        self.assertIn("Unspecified type ('.')", str(cm.exception))
        self.assertIn("operational_types", str(cm.exception))

    def test_load_subtype_modules_invalid_name_raises(self):
        with self.assertRaises(ValueError) as cm:
            auxiliary_module_to_test.load_subtype_modules(
                required_subtype_modules=[""],
                package="gridpath.project.operations.operational_types",
                required_attributes=[],
            )
        self.assertIn("Invalid subtype module name", str(cm.exception))

    def test_load_subtype_modules(self):
        imported = auxiliary_module_to_test.load_subtype_modules(
            required_subtype_modules=["gen_simple"],
            package="gridpath.project.operations.operational_types",
            required_attributes=["power_provision_rule"],
        )
        self.assertTrue(hasattr(imported["gen_simple"], "power_provision_rule"))


if __name__ == "__main__":
    unittest.main()
