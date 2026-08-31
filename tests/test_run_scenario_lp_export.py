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
The --create_lp_problem_file_only symbol-map export must share a single
cuid_buffer across all ComponentUID constructions: when a buffer is passed,
Pyomo populates it by iterating every index of the component's parent, so a
fresh buffer per call makes the export quadratic in component size (>12
hours on a 2.7M-variable model vs seconds with a shared buffer). Constraint
symbols are only needed to load duals, so they must be skipped when the
instance has no dual suffix (--skip_duals).
"""

import os
import tempfile
import unittest
from unittest import mock

import dill
from pyomo.environ import (
    ConcreteModel,
    Constraint,
    NonNegativeReals,
    Objective,
    Set,
    Suffix,
    Var,
)
from pyomo.core import ComponentUID, SymbolMap

from gridpath import run_scenario


def build_test_instance(with_dual_suffix):
    instance = ConcreteModel()
    instance.S = Set(initialize=[("Project_A", 1), ("Project_A", 2), ("B", 1)])
    instance.Power = Var(instance.S, within=NonNegativeReals)
    instance.Max_Power_Constraint = Constraint(
        instance.S, rule=lambda mod, prj, tmp: mod.Power[prj, tmp] <= 10
    )
    instance.Total_Cost = Objective(expr=sum(instance.Power[idx] for idx in instance.S))
    if with_dual_suffix:
        instance.dual = Suffix(direction=Suffix.IMPORT)

    return instance


def write_lp_and_get_symbol_map(instance, directory):
    smap_id = run_scenario.write_problem_file(
        instance=instance, prob_sol_files_directory=directory
    )

    return instance.solutions.symbol_map[smap_id]


class TestBuildSymbolCUIDPairs(unittest.TestCase):
    def setUp(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.tmp_dir_name = tmp_dir.name

    def test_cuid_buffer_is_shared_across_calls(self):
        """A single cuid_buffer dict must be passed to every ComponentUID
        call; a fresh dict per call is quadratic in component size."""
        instance = build_test_instance(with_dual_suffix=True)
        symbol_map = write_lp_and_get_symbol_map(instance, self.tmp_dir_name)

        # Hold strong references to the passed buffers so a
        # fresh-dict-per-call implementation can't alias ids via
        # garbage-collection reuse
        recorded_buffers = []

        def recording_cuid(component, cuid_buffer=None, **kwargs):
            recorded_buffers.append(cuid_buffer)
            return ComponentUID(component, cuid_buffer=cuid_buffer, **kwargs)

        with mock.patch.object(
            run_scenario, "ComponentUID", side_effect=recording_cuid
        ):
            run_scenario.build_symbol_cuid_pairs(symbol_map=symbol_map)

        self.assertEqual(len(recorded_buffers), len(symbol_map.bySymbol))
        self.assertIsNotNone(recorded_buffers[0])
        for buffer in recorded_buffers[1:]:
            self.assertIs(buffer, recorded_buffers[0])

    def test_round_trip_resolves_all_symbols(self):
        """Pickled (symbol, CUID) pairs must resolve back to the identical
        component objects, the way load_problem_info() reconstructs the
        symbol map."""
        instance = build_test_instance(with_dual_suffix=True)
        symbol_map = write_lp_and_get_symbol_map(instance, self.tmp_dir_name)

        symbol_cuid_pairs = run_scenario.build_symbol_cuid_pairs(
            symbol_map=symbol_map,
            include_constraints=hasattr(instance, "dual"),
        )
        # With a dual suffix, all symbols are kept
        self.assertEqual(len(symbol_cuid_pairs), len(symbol_map.bySymbol))

        pickle_path = os.path.join(self.tmp_dir_name, "symbol_map.pickle")
        with open(pickle_path, "wb") as f_out:
            dill.dump(symbol_cuid_pairs, f_out)
        with open(pickle_path, "rb") as map_in:
            reloaded_pairs = dill.load(map_in)
        reconstructed_map = SymbolMap()
        reconstructed_map.addSymbols(
            (cuid.find_component_on(instance), symbol)
            for symbol, cuid in reloaded_pairs
        )

        for symbol, component in symbol_map.bySymbol.items():
            self.assertIs(reconstructed_map.bySymbol[symbol], component)

    def test_constraint_symbols_skipped_without_duals(self):
        """Without a dual suffix, constraint symbols are dead weight — only
        variable (and objective) symbols should be exported."""
        instance = build_test_instance(with_dual_suffix=False)
        symbol_map = write_lp_and_get_symbol_map(instance, self.tmp_dir_name)

        symbol_cuid_pairs = run_scenario.build_symbol_cuid_pairs(
            symbol_map=symbol_map,
            include_constraints=hasattr(instance, "dual"),
        )

        kept_symbols = {symbol for symbol, cuid in symbol_cuid_pairs}
        for symbol, component in symbol_map.bySymbol.items():
            if component.ctype is Constraint:
                self.assertNotIn(symbol, kept_symbols)
            else:
                self.assertIn(symbol, kept_symbols)
        # The model has constraints, so something must have been skipped
        self.assertLess(len(kept_symbols), len(symbol_map.bySymbol))
        # All variable symbols resolve to the identical objects
        for symbol, cuid in symbol_cuid_pairs:
            self.assertIs(cuid.find_component_on(instance), symbol_map.bySymbol[symbol])


if __name__ == "__main__":
    unittest.main()
