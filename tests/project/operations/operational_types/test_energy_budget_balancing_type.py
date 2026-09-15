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
The optional ``energy_budget_balancing_type`` operational characteristic lets
a hydro project's energy budgets (and per-horizon min/max power fractions)
follow the horizons of a balancing type other than its
``balancing_type_project``, which keeps governing chronology (ramps and
horizon-boundary handling).
"""

import contextlib
from importlib import import_module
import logging
import os.path
import shutil
import sqlite3
import tempfile
import unittest

import pandas as pd
from pyomo.core.expr import identify_variables
from pyomo.repn import generate_standard_repn

from gridpath.project.operations.operational_types.common_functions import (
    validate_hydro_opchars,
)
from gridpath.project.operations.operational_types.gen_hydro_common import (
    HYDRO_BUDGET_ALLOCATION_TAB_FILE,
)
from tests.common_functions import add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)
DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db", "db_schema.sql"
)

PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "project",
    "project.capacity.capacity",
    "project.availability.availability",
    "project.fuels",
    "project.operations",
]
IMPORTED_PREREQ_MODULES = [
    import_module("." + mdl, package="gridpath") for mdl in PREREQUISITE_MODULE_NAMES
]
GEN_HYDRO_MODULE = import_module(
    ".project.operations.operational_types.gen_hydro", package="gridpath"
)
GEN_HYDRO_MUST_TAKE_MODULE = import_module(
    ".project.operations.operational_types.gen_hydro_must_take", package="gridpath"
)
HYDRO_TAB_FILE = "hydro_conventional_horizon_params.tab"


class TestEnergyBudgetBalancingTypeModel(unittest.TestCase):
    """
    Copies the unit-test fixture and edits the Hydro (gen_hydro, 'day'
    budgets, ramp rates specified) and Hydro_NonCurtailable
    (gen_hydro_must_take, 'year' budgets) projects. In the fixture, day
    202001 (timepoints 20200101-20200124) has a circular boundary and day
    202002 (20200201-20200224) a linear one; year 2020 spans both days with
    a circular boundary.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.test_data_dir = os.path.join(self.tmp_dir.name, "test_data")
        shutil.copytree(TEST_DATA_DIRECTORY, self.test_data_dir)

    def set_project_chars(self, project, **chars):
        path = os.path.join(self.test_data_dir, "inputs", "projects.tab")
        df = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
        for col, val in chars.items():
            df.loc[df["project"] == project, col] = val
        df.to_csv(path, sep="\t", index=False)

    def set_hydro_rows(self, project, rows):
        """
        Replace the project's rows in the hydro horizon params tab file with
        *rows* of (balancing_type, horizon, avg, min, max).
        """
        path = os.path.join(self.test_data_dir, "inputs", HYDRO_TAB_FILE)
        df = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
        df = df[df["project"] != project]
        new = pd.DataFrame(
            [[project] + [str(x) for x in row] for row in rows], columns=df.columns
        )
        pd.concat([df, new]).to_csv(path, sep="\t", index=False)

    def build_instance(self, module):
        m, data = add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=module,
            test_data_dir=self.test_data_dir,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        return m.create_instance(data)

    @staticmethod
    def prev_power_tmps(constraint, power_var_name, prj, tmp):
        """
        The timepoints other than *tmp* whose gross power variable enters the
        project's ramp constraint at *tmp*, i.e. the previous timepoint the
        ramp is measured from.
        """
        return {
            v.index()[1]
            for v in identify_variables(constraint[prj, tmp].body)
            if v.parent_component().name == power_var_name and v.index()[1] != tmp
        }

    @staticmethod
    def max_power_constant(instance, prj, tmp):
        """
        The constant term of the max-power constraint body, i.e. minus the
        max power fraction times the (constant) available capacity.
        """
        return generate_standard_repn(
            instance.GenHydro_Max_Power_Constraint[prj, tmp].body
        ).constant

    def test_default_is_balancing_type_project(self):
        instance = self.build_instance(GEN_HYDRO_MODULE)
        self.assertEqual(
            [], list(instance.gen_hydro_energy_budget_balancing_type.sparse_keys())
        )
        # Ramps follow the day horizons: the circular first day wraps onto
        # itself and the linear second day has no ramp constraint at its
        # first timepoint
        self.assertEqual(
            {20200124},
            self.prev_power_tmps(
                instance.GenHydro_Ramp_Up_Constraint,
                "GenHydro_Gross_Power_MW",
                "Hydro",
                20200101,
            ),
        )
        self.assertNotIn(("Hydro", 20200201), instance.GenHydro_Ramp_Up_Constraint)

    def test_budgets_by_day_with_year_chronology(self):
        self.set_project_chars(
            "Hydro", balancing_type_project="year", energy_budget_balancing_type="day"
        )
        # Different max fractions in the two days so the lookup is testable
        self.set_hydro_rows(
            "Hydro",
            [
                ("day", 202001, 0.5, 0.15, 1),
                ("day", 202002, 0.5, 0.15, 0.8),
                ("day", 203001, 0.5, 0.15, 1),
                ("day", 203002, 0.5, 0.15, 1),
            ],
        )
        instance = self.build_instance(GEN_HYDRO_MODULE)

        self.assertEqual(
            {"Hydro": "day"},
            dict(instance.gen_hydro_energy_budget_balancing_type.items()),
        )
        # Budgets and per-horizon limits follow the day horizons ...
        self.assertListEqual(
            [
                ("Hydro", "day", 202001),
                ("Hydro", "day", 202002),
                ("Hydro", "day", 203001),
                ("Hydro", "day", 203002),
            ],
            sorted(instance.GEN_HYDRO_OPR_BT_HRZS),
        )
        self.assertAlmostEqual(
            0.8,
            self.max_power_constant(instance, "Hydro", 20200201)
            / self.max_power_constant(instance, "Hydro", 20200101),
        )
        # ... while ramps follow the circular year: the year's first
        # timepoint ramps from its last one and the second day's first
        # timepoint from the first day's last one
        self.assertEqual(
            {20200224},
            self.prev_power_tmps(
                instance.GenHydro_Ramp_Up_Constraint,
                "GenHydro_Gross_Power_MW",
                "Hydro",
                20200101,
            ),
        )
        self.assertEqual(
            {20200124},
            self.prev_power_tmps(
                instance.GenHydro_Ramp_Down_Constraint,
                "GenHydro_Gross_Power_MW",
                "Hydro",
                20200201,
            ),
        )

    def test_must_take_budgets_by_day_with_year_chronology(self):
        self.set_project_chars(
            "Hydro_NonCurtailable", energy_budget_balancing_type="day"
        )
        # The fixture allocates this project's year budgets among its days;
        # with day budgets those limits would (correctly) be rejected
        os.remove(
            os.path.join(self.test_data_dir, "inputs", HYDRO_BUDGET_ALLOCATION_TAB_FILE)
        )
        self.set_hydro_rows(
            "Hydro_NonCurtailable",
            [
                ("day", 202001, 0.5, 0.15, 1),
                ("day", 202002, 0.5, 0.15, 1),
                ("day", 203001, 0.5, 0.15, 1),
                ("day", 203002, 0.5, 0.15, 1),
            ],
        )
        instance = self.build_instance(GEN_HYDRO_MUST_TAKE_MODULE)
        self.assertEqual(
            {"Hydro_NonCurtailable": "day"},
            dict(instance.gen_hydro_must_take_energy_budget_balancing_type.items()),
        )
        self.assertListEqual(
            [
                ("Hydro_NonCurtailable", "day", 202001),
                ("Hydro_NonCurtailable", "day", 202002),
                ("Hydro_NonCurtailable", "day", 203001),
                ("Hydro_NonCurtailable", "day", 203002),
            ],
            sorted(instance.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS),
        )
        self.assertEqual(
            {20200124},
            self.prev_power_tmps(
                instance.GenHydroMustTake_Ramp_Up_Constraint,
                "GenHydroMustTake_Gross_Power_MW",
                "Hydro_NonCurtailable",
                20200201,
            ),
        )

    def test_unknown_balancing_type_raises(self):
        self.set_project_chars("Hydro", energy_budget_balancing_type="month")
        logger = logging.getLogger("pyomo.core")
        was_disabled = logger.disabled
        logger.disabled = True
        try:
            # Pyomo raises the domain ValueError, or wraps it in a RuntimeError
            with self.assertRaisesRegex((ValueError, RuntimeError), "month"):
                self.build_instance(GEN_HYDRO_MODULE)
        finally:
            logger.disabled = was_disabled


class SubScenariosStub:
    PROJECT_PORTFOLIO_SCENARIO_ID = 1
    PROJECT_OPERATIONAL_CHARS_SCENARIO_ID = 1
    TEMPORAL_SCENARIO_ID = 1


class TestEnergyBudgetBalancingTypeValidation(unittest.TestCase):
    """
    In-memory database from the real schema: two 'day' horizons of two
    timepoints each, one 'year' horizon spanning both. The Hydro project is
    a gen_hydro project.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        c = self.conn.cursor()
        for tmp, day in [(1, 202001), (2, 202001), (3, 202002), (4, 202002)]:
            c.execute(
                """INSERT INTO inputs_temporal
                (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                period, number_of_hours_in_timepoint, timepoint_weight,
                spinup_or_lookahead)
                VALUES (1, 1, 1, ?, 2020, 1, 1, 0)""",
                (tmp,),
            )
            for bt, hrz in [("day", day), ("year", 2020)]:
                c.execute(
                    """INSERT INTO inputs_temporal_horizon_timepoints
                    (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                    balancing_type_horizon, horizon)
                    VALUES (1, 1, 1, ?, ?, ?)""",
                    (tmp, bt, hrz),
                )
        c.execute("""INSERT INTO inputs_project_portfolios
            (project_portfolio_scenario_id, project, capacity_type)
            VALUES (1, 'Hydro', 'gen_spec')""")
        c.execute("""INSERT INTO inputs_project_hydro_operational_chars_iterations
            (project, hydro_operational_chars_scenario_id,
            varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES ('Hydro', 1, 0, 0)""")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def set_inputs(self, balancing_type_project, energy_budget_balancing_type, rows):
        c = self.conn.cursor()
        c.execute(
            """INSERT INTO inputs_project_operational_chars
            (project_operational_chars_scenario_id, project, operational_type,
            balancing_type_project, energy_budget_balancing_type,
            hydro_operational_chars_scenario_id)
            VALUES (1, 'Hydro', 'gen_hydro', ?, ?, 1)""",
            (balancing_type_project, energy_budget_balancing_type),
        )
        for bt, hrz in rows:
            c.execute(
                """INSERT INTO inputs_project_hydro_operational_chars
                (project, hydro_operational_chars_scenario_id, weather_iteration,
                hydro_iteration, stage_id, balancing_type_project, horizon,
                average_power_fraction, min_power_fraction, max_power_fraction)
                VALUES ('Hydro', 1, 0, 0, 1, ?, ?, 0.5, 0.2, 1)""",
                (bt, hrz),
            )
        self.conn.commit()

    def get_validation_errors(self):
        validate_hydro_opchars(
            scenario_id=1,
            subscenarios=SubScenariosStub(),
            weather_iteration=0,
            hydro_iteration=0,
            availability_iteration=0,
            subproblem=1,
            stage=1,
            conn=self.conn,
            op_type="gen_hydro",
        )
        return self.conn.execute(
            "SELECT severity, description FROM status_validation"
        ).fetchall()

    def test_default_balancing_type_passes(self):
        self.set_inputs("day", None, [("day", 202001), ("day", 202002)])
        self.assertListEqual([], self.get_validation_errors())

    def test_budget_balancing_type_passes(self):
        self.set_inputs("year", "day", [("day", 202001), ("day", 202002)])
        self.assertListEqual([], self.get_validation_errors())

    def test_rows_for_other_balancing_type_flagged(self):
        # Rows for the project's own balancing type are wrong once the
        # budgets are specified to follow another one
        self.set_inputs("year", "day", [("year", 2020)])
        errors = self.get_validation_errors()
        self.assertEqual(1, len(errors))
        self.assertEqual("High", errors[0][0])
        self.assertIn("['year']", errors[0][1])
        self.assertIn("energy-budget balancing type", errors[0][1])

    def test_balancing_type_not_in_temporal_scenario_flagged(self):
        self.set_inputs("year", "month", [("year", 2020)])
        errors = self.get_validation_errors()
        self.assertEqual("High", errors[0][0])
        self.assertIn("['month']", errors[0][1])
        self.assertIn("not balancing types of the temporal scenario", errors[0][1])


if __name__ == "__main__":
    unittest.main()
