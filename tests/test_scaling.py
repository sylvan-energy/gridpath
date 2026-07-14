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
Tests for numerical scaling (gridpath/auxiliary/scaling.py) and its integration
into the solve path (gridpath/run_scenario.py::solve_problem).

The correctness property being verified: solving with scale factors and mapping
the solution back yields the same objective, variable values, and duals as
solving unscaled -- i.e. the scaling is an exact reformulation, not an
approximation.
"""

import tempfile
import types
import unittest

from pyomo.environ import (
    Binary,
    ConcreteModel,
    Constraint,
    NonNegativeReals,
    Objective,
    Reals,
    Set,
    SolverFactory,
    Suffix,
    TransformationFactory,
    Var,
    minimize,
    value,
)

from gridpath import run_scenario
from gridpath.auxiliary.scaling import (
    assign_scaling_factors,
    classify_variable_units,
)

# Scale factors used throughout: 1000 (MW -> GW) and 1e6 ($ -> $M).
POWER_SCALE = 1000.0
DOLLAR_SCALE = 1e6


def _build_dispatch_model():
    """Build a small LP that mimics GridPath's structure and naming.

    A two-timepoint economic dispatch: a generator (power, MW) and unserved
    energy (power, MW) serve a load; a cost variable (dollars) is defined by a
    $/MWh cost curve. The load-balance constraint is binding, so its dual is a
    non-zero marginal price -- exercising dual propagation through the
    S_dollar/S_power ratio.

    Returns:
        A Pyomo ``ConcreteModel`` with a ``dual`` Suffix (as run_scenario sets).
    """
    m = ConcreteModel()
    m.T = Set(initialize=[1, 2], ordered=True)
    load = {1: 800.0, 2: 5000.0}  # tmp 2 exceeds the 4000 MW gen cap -> unserved

    m.GenSimple_Provide_Power_MW = Var(m.T, bounds=(0, 4000))
    m.Unserved_Energy_MW = Var(m.T, within=NonNegativeReals)
    m.Variable_OM_Curve_Cost = Var(m.T, within=Reals)

    def meet_load_rule(mod, t):
        return mod.GenSimple_Provide_Power_MW[t] + mod.Unserved_Energy_MW[t] == load[t]

    m.Meet_Load_Constraint = Constraint(m.T, rule=meet_load_rule)

    # Cost curve: $30/MWh generation, $500/MWh unserved-energy penalty. The
    # rate constants live inside this (cost-definition) row.
    def cost_rule(mod, t):
        return mod.Variable_OM_Curve_Cost[t] >= (
            30 * mod.GenSimple_Provide_Power_MW[t] + 500 * mod.Unserved_Energy_MW[t]
        )

    m.Cost_Constraint = Constraint(m.T, rule=cost_rule)

    m.NPV = Objective(
        expr=sum(m.Variable_OM_Curve_Cost[t] for t in m.T), sense=minimize
    )
    # run_scenario declares this on every model; scale_model uses it to map
    # duals back.
    m.dual = Suffix(direction=Suffix.IMPORT)
    return m


def _fake_parsed_arguments(power_scale_factor, dollar_scale_factor):
    """Build a minimal parsed-arguments stand-in for solve_problem/solve.

    Points the (non-existent) scenario directory at a temp location so that no
    ``solver_options.csv`` is found and ``solve`` falls back to cbc.
    """
    return types.SimpleNamespace(
        quiet=True,
        power_scale_factor=power_scale_factor,
        dollar_scale_factor=dollar_scale_factor,
        solver=None,
        solver_executable=None,
        mute_solver_output=True,
        keepfiles=False,
        symbolic=False,
        scenario_location=tempfile.gettempdir(),
        scenario="_scaling_unittest_no_such_scenario",
    )


class TestClassifyVariableUnits(unittest.TestCase):
    """Name-based unit classification against real GridPath variable names."""

    def test_power_energy_names(self):
        for name in [
            "GenSimple_Provide_Power_MW",
            "Stor_Starting_Energy_in_Storage_MWh",
            "Inertia_Reserves_Violation_MWs",
            "Transmission_Target_Energy_MW_Neg_Dir",
            "Net_Market_Purchased_Power",  # unsuffixed, trailing "Power"
        ]:
            self.assertEqual(classify_variable_units(name), "power", msg=name)

    def test_dollar_names(self):
        for name in [
            "Hurdle_Cost_Pos_Dir",  # "Cost" token, not last
            "Variable_OM_Curve_Cost",
            "Carbon_Tax_Cost",
            "Ramp_Up_Tuning_Cost",
        ]:
            self.assertEqual(classify_variable_units(name), "dollar", msg=name)

    def test_unrecognized_names(self):
        for name in [
            "Fuel_Prod_Consume_Power_PowerUnit",  # trailing "PowerUnit", not "Power"
            "Import_Carbon_Emissions_Tons",
            "Load_Component_Modifier_Fraction_Invested",
            "LZ_Exports",
        ]:
            self.assertIsNone(classify_variable_units(name), msg=name)


class TestAssignScalingFactors(unittest.TestCase):
    """Factor assignment on a built instance."""

    def setUp(self):
        self.m = _build_dispatch_model()
        assign_scaling_factors(self.m, POWER_SCALE, DOLLAR_SCALE)

    def test_positive_factor_validation(self):
        for bad in [(0, 1), (1, 0), (-1, 1), (1, -5)]:
            with self.assertRaises(ValueError):
                assign_scaling_factors(_build_dispatch_model(), bad[0], bad[1])

    def test_power_variable_factor(self):
        self.assertEqual(
            self.m.scaling_factor[self.m.GenSimple_Provide_Power_MW],
            1.0 / POWER_SCALE,
        )
        self.assertEqual(
            self.m.scaling_factor[self.m.Unserved_Energy_MW], 1.0 / POWER_SCALE
        )

    def test_dollar_variable_factor(self):
        self.assertEqual(
            self.m.scaling_factor[self.m.Variable_OM_Curve_Cost],
            1.0 / DOLLAR_SCALE,
        )

    def test_objective_factor(self):
        self.assertEqual(self.m.scaling_factor[self.m.NPV], 1.0 / DOLLAR_SCALE)

    def test_homogeneous_power_constraint_factor(self):
        # Meet_Load: sum(MW) == load -> power factor.
        self.assertEqual(
            self.m.scaling_factor[self.m.Meet_Load_Constraint],
            1.0 / POWER_SCALE,
        )

    def test_cost_definition_constraint_factor(self):
        # Cost_Constraint contains a dollar variable -> dollar factor.
        self.assertEqual(
            self.m.scaling_factor[self.m.Cost_Constraint], 1.0 / DOLLAR_SCALE
        )

    def test_container_granularity(self):
        # One suffix entry per container (not per index), so the count is small
        # and independent of the timepoint set size: 3 vars + 2 constraints + 1
        # objective = 6 entries, even though each indexed component has 2 data.
        self.assertEqual(len(self.m.scaling_factor), 6)

    def test_integer_variable_not_scaled(self):
        m = _build_dispatch_model()
        m.GenNewBin_Build = Var(within=Binary)
        assign_scaling_factors(m, POWER_SCALE, DOLLAR_SCALE)
        self.assertNotIn(m.GenNewBin_Build, m.scaling_factor)


class TestScaledSolveEquivalence(unittest.TestCase):
    """The scaled solve must reproduce the unscaled solution exactly."""

    @classmethod
    def setUpClass(cls):
        if not SolverFactory("cbc").available():
            raise unittest.SkipTest("cbc not available")

    def _solve(self, power_scale_factor, dollar_scale_factor):
        instance = _build_dispatch_model()
        args = _fake_parsed_arguments(power_scale_factor, dollar_scale_factor)
        solved, _ = run_scenario.solve_problem(args, instance)
        gen = {t: value(solved.GenSimple_Provide_Power_MW[t]) for t in solved.T}
        use = {t: value(solved.Unserved_Energy_MW[t]) for t in solved.T}
        price = {t: solved.dual[solved.Meet_Load_Constraint[t]] for t in solved.T}
        return value(solved.NPV), gen, use, price

    def test_objective_variables_and_duals_match(self):
        base_obj, base_gen, base_use, base_price = self._solve(1.0, 1.0)
        scl_obj, scl_gen, scl_use, scl_price = self._solve(POWER_SCALE, DOLLAR_SCALE)

        # Objective (native dollars): 800*30 + 4000*30 + 1000*500 = 644000.
        self.assertAlmostEqual(base_obj, scl_obj, places=3)
        self.assertAlmostEqual(base_obj, 644000.0, places=1)

        for t in base_gen:
            self.assertAlmostEqual(base_gen[t], scl_gen[t], places=4, msg=f"gen[{t}]")
            self.assertAlmostEqual(base_use[t], scl_use[t], places=4, msg=f"use[{t}]")
            # Marginal price ($/MWh) recovered via the S_dollar/S_power ratio.
            self.assertAlmostEqual(
                base_price[t], scl_price[t], places=4, msg=f"price[{t}]"
            )

        # tmp 2 is short 1000 MW -> its marginal price is the $500/MWh penalty.
        self.assertAlmostEqual(scl_price[2], 500.0, places=3)

    def test_no_scaling_path_leaves_no_suffix(self):
        # The (1.0, 1.0) default path must not touch the instance (no clone, no
        # scaling_factor suffix).
        instance = _build_dispatch_model()
        args = _fake_parsed_arguments(1.0, 1.0)
        solved, _ = run_scenario.solve_problem(args, instance)
        self.assertIs(solved, instance)
        self.assertFalse(hasattr(instance, "scaling_factor"))


class TestIncompatibleFlagGuard(unittest.TestCase):
    """Scaling combined with a load-solution / lp-only flag must fail fast."""

    def test_scaling_with_load_solution_raises(self):
        # The guard runs right after argument parsing, before the scenario
        # directory is checked, so a placeholder --scenario is enough.
        with self.assertRaises(ValueError):
            run_scenario.main(
                [
                    "--scenario",
                    "_scaling_unittest",
                    "--power_scale_factor",
                    "1000",
                    "--load_highs_solution",
                ]
            )

    def test_scaling_with_lp_only_raises(self):
        with self.assertRaises(ValueError):
            run_scenario.main(
                [
                    "--scenario",
                    "_scaling_unittest",
                    "--dollar_scale_factor",
                    "1000000",
                    "--create_lp_problem_file_only",
                ]
            )


if __name__ == "__main__":
    unittest.main()
