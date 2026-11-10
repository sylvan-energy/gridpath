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
run_scenario calls every rule's export and export_summary entries with the
keyword arguments instance and quiet, so each must be a callable accepting
them.
"""

import inspect
import unittest

from gridpath.auxiliary.import_export_rules import import_export_rules


class TestImportExportRules(unittest.TestCase):
    def test_export_rules_accept_instance_and_quiet(self):
        for rule_name, rule in import_export_rules.items():
            for step in ("export", "export_summary"):
                with self.subTest(rule=rule_name, step=step):
                    # Binding checks the call shape without needing a solved
                    # instance; export_rule_use reads the instance
                    inspect.signature(rule[step]).bind(instance=None, quiet=True)

    def test_export_summary_rules_return_booleans(self):
        for rule_name, rule in import_export_rules.items():
            with self.subTest(rule=rule_name):
                self.assertIsInstance(
                    rule["export_summary"](instance=None, quiet=True), bool
                )


if __name__ == "__main__":
    unittest.main()
