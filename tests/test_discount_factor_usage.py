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
Static audit of how the period discount factor is used.

Objective-function terms must be weighted by
``probability_weighted_discount_factor`` (discount factor times the
probability of reaching the period in a stochastic scenario tree), never by
the raw ``discount_factor``: a raw reference would silently drop branch
probabilities from that term. Outside the objective package, the raw
``discount_factor`` may only appear where it is exported to results next to
``probability_weighted_discount_factor``.
"""

import os
import re
import unittest

GRIDPATH_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "gridpath")
PERIODS_MODULE = os.path.join("temporal", "investment", "periods.py")

RAW_REFERENCE = re.compile(r"\bdiscount_factor\[")
WEIGHTED_REFERENCE = re.compile(r"\bprobability_weighted_discount_factor\[")


def python_files():
    for root, _, files in os.walk(GRIDPATH_DIRECTORY):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                yield os.path.relpath(path, GRIDPATH_DIRECTORY), path


class TestDiscountFactorUsage(unittest.TestCase):
    def test_objective_terms_use_probability_weighted_discount_factor(self):
        offenders = []
        for rel_path, path in python_files():
            if not rel_path.startswith("objective" + os.sep):
                continue
            with open(path) as f:
                for line_number, line in enumerate(f, start=1):
                    if RAW_REFERENCE.search(line):
                        offenders.append(f"{rel_path}:{line_number}: {line.strip()}")
        self.assertListEqual(
            [],
            offenders,
            msg="Objective-function terms must use "
            "probability_weighted_discount_factor, not discount_factor",
        )

    def test_raw_discount_factor_only_exported_alongside_weighted(self):
        offenders = []
        for rel_path, path in python_files():
            if rel_path == PERIODS_MODULE:
                continue
            with open(path) as f:
                content = f.read()
            if RAW_REFERENCE.search(content) and not WEIGHTED_REFERENCE.search(content):
                offenders.append(rel_path)
        self.assertListEqual(
            [],
            offenders,
            msg="Files referencing the raw discount_factor must also reference "
            "probability_weighted_discount_factor (results exports carry both)",
        )


if __name__ == "__main__":
    unittest.main()
