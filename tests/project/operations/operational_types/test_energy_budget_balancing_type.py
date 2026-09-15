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
    validate_energy_budget_balancing_type_rows,
    validate_hydro_opchars,
)
from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.project.operations.operational_types.gen_hydro_common import (
    HYDRO_BUDGET_ALLOCATION_TAB_FILE,
)
from gridpath.project.operations import validate_project_balancing_types
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
# energy_slice_hrz_shaping also needs the project potential (max_total_energy)
SLICE_PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "project",
    "project.capacity.capacity",
    "project.capacity.potential",
    "project.availability.availability",
    "project.fuels",
    "project.operations",
]
IMPORTED_SLICE_PREREQ_MODULES = [
    import_module("." + mdl, package="gridpath")
    for mdl in SLICE_PREREQUISITE_MODULE_NAMES
]
GEN_HYDRO_MODULE = import_module(
    ".project.operations.operational_types.gen_hydro", package="gridpath"
)
GEN_HYDRO_MUST_TAKE_MODULE = import_module(
    ".project.operations.operational_types.gen_hydro_must_take", package="gridpath"
)
STOR_MODULE = import_module(
    ".project.operations.operational_types.stor", package="gridpath"
)
ENERGY_HRZ_SHAPING_MODULE = import_module(
    ".project.operations.operational_types.energy_hrz_shaping", package="gridpath"
)
ENERGY_SLICE_HRZ_SHAPING_MODULE = import_module(
    ".project.operations.operational_types.energy_slice_hrz_shaping",
    package="gridpath",
)
STOR_STRESS_HRZ_MODULE = import_module(
    ".project.operations.operational_types.stor_stress_hrz", package="gridpath"
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

    def build_instance(self, module, prereq_modules=IMPORTED_PREREQ_MODULES):
        m, data = add_components_and_load_data(
            prereq_modules=prereq_modules,
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

    @staticmethod
    def losses_horizon_bts(instance, prj):
        return {
            bt
            for (p, bt, hrz) in instance.STOR_OPR_BT_HRZ
            if p == prj and (p, bt, hrz) in instance.Stor_Max_Losses_Constraint
        }

    def test_storage_default_is_balancing_type_project(self):
        self.set_project_chars(
            "Battery_Specified", max_losses_in_hrz_frac_stor_energy_capacity="0.1"
        )
        instance = self.build_instance(STOR_MODULE)
        self.assertEqual(
            [], list(instance.stor_energy_budget_balancing_type.sparse_keys())
        )
        self.assertEqual(
            {"day"}, self.losses_horizon_bts(instance, "Battery_Specified")
        )

    def test_storage_losses_limit_by_year_with_day_chronology(self):
        self.set_project_chars(
            "Battery_Specified",
            max_losses_in_hrz_frac_stor_energy_capacity="0.1",
            energy_budget_balancing_type="year",
        )
        instance = self.build_instance(STOR_MODULE)
        self.assertEqual(
            {"Battery_Specified": "year"},
            dict(instance.stor_energy_budget_balancing_type.items()),
        )
        # The losses limit applies over the year horizons ...
        self.assertEqual(
            {"year"}, self.losses_horizon_bts(instance, "Battery_Specified")
        )
        self.assertFalse(
            [
                idx
                for idx in instance.STOR_OPR_BT_HRZ
                if idx[0] == "Battery_Specified" and idx[1] == "day"
            ]
        )
        # ... while state-of-charge tracking still follows the circular day:
        # the first timepoint of day 202001 tracks from the day's last one
        self.assertEqual(
            {20200124},
            {
                v.index()[1]
                for v in identify_variables(
                    instance.Stor_Energy_Tracking_Constraint[
                        "Battery_Specified", 20200101
                    ].body
                )
                if v.index()[1] != 20200101
            },
        )

    def test_energy_hrz_shaping_budgets_by_year_with_day_chronology(self):
        self.set_project_chars(
            "Energy_Hrz_Shaping", energy_budget_balancing_type="year"
        )
        path = os.path.join(
            self.test_data_dir, "inputs", "energy_hrz_shaping_params.tab"
        )
        with open(path, "w") as f:
            f.write(
                "project\tbalancing_type_project\thorizon\thrz_energy_fraction\tmin_power\tmax_power\n"
            )
            for hrz in (2020, 2030):
                f.write(f"Energy_Hrz_Shaping\tyear\t{hrz}\t1\t1.000002\t6\n")
        instance = self.build_instance(ENERGY_HRZ_SHAPING_MODULE)
        self.assertEqual(
            {"Energy_Hrz_Shaping": "year"},
            dict(instance.energy_hrz_shaping_energy_budget_balancing_type.items()),
        )
        self.assertListEqual(
            [
                ("Energy_Hrz_Shaping", "year", 2020),
                ("Energy_Hrz_Shaping", "year", 2030),
            ],
            sorted(instance.ENERGY_HRZ_SHAPING_OPR_BT_HRZS),
        )
        # Min/max power constraints look the year horizon up for every
        # timepoint
        self.assertIn(
            ("Energy_Hrz_Shaping", 20200201),
            instance.EnergyHrzShaping_Max_Power_Constraint,
        )
        # Chronology still follows the days: no power delta at the first
        # timepoint of the linear day 202002, but one within the day
        self.assertIsNone(
            ENERGY_HRZ_SHAPING_MODULE.power_delta_rule(
                instance, "Energy_Hrz_Shaping", 20200201
            )
        )
        self.assertIsNotNone(
            ENERGY_HRZ_SHAPING_MODULE.power_delta_rule(
                instance, "Energy_Hrz_Shaping", 20200202
            )
        )

    def test_energy_slice_hrz_shaping_budgets_by_year_with_day_chronology(self):
        self.set_project_chars(
            "Energy_Slice_Hrz_Shaping", energy_budget_balancing_type="year"
        )
        path = os.path.join(
            self.test_data_dir, "inputs", "energy_slice_hrz_shaping_params.tab"
        )
        with open(path, "w") as f:
            f.write(
                "project\tbalancing_type_project\thorizon\thrz_energy\tmin_power"
                "\tmax_power\n"
                "Energy_Slice_Hrz_Shaping\tyear\t2020\t2000\t1.000002\t6\n"
                "Energy_Slice_Hrz_Shaping\tyear\t2030\t2000\t1.000002\t6\n"
            )
        instance = self.build_instance(
            ENERGY_SLICE_HRZ_SHAPING_MODULE, IMPORTED_SLICE_PREREQ_MODULES
        )
        self.assertEqual(
            {"Energy_Slice_Hrz_Shaping": "year"},
            dict(
                instance.energy_slice_hrz_shaping_energy_budget_balancing_type.items()
            ),
        )
        self.assertListEqual(
            [
                ("Energy_Slice_Hrz_Shaping", "year", 2020),
                ("Energy_Slice_Hrz_Shaping", "year", 2030),
            ],
            sorted(instance.ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS),
        )
        self.assertIn(
            ("Energy_Slice_Hrz_Shaping", 20200201),
            instance.EnergySliceHrzShaping_Max_Power_Constraint,
        )
        # Chronology still follows the days (linear day 202002)
        self.assertIsNone(
            ENERGY_SLICE_HRZ_SHAPING_MODULE.power_delta_rule(
                instance, "Energy_Slice_Hrz_Shaping", 20200201
            )
        )
        self.assertIsNotNone(
            ENERGY_SLICE_HRZ_SHAPING_MODULE.power_delta_rule(
                instance, "Energy_Slice_Hrz_Shaping", 20200202
            )
        )

    @staticmethod
    def tracked_from_tmps(instance, prj, tmp):
        """
        The other timepoints whose starting state of charge enters the
        stress-horizon tracking constraint at *tmp*.
        """
        return {
            v.index()[1]
            for v in identify_variables(
                instance.StorStressHrz_Stress_Hrz_Energy_Tracking_Constraint[
                    prj, tmp
                ].body
            )
            if v.parent_component().name
            == "StorStressHrz_Starting_Energy_in_Storage_MWh"
            and v.index()[1] != tmp
        }

    def test_stor_stress_hrz_horizons_by_day_with_year_chronology(self):
        """
        The fixture types day 202002 as a stress horizon. With the project
        on the circular year, the horizon typing and the stress-horizon
        state-of-charge chain still follow the days.
        """
        prj = "Battery_Stress_Hrz"
        self.set_project_chars(
            prj, balancing_type_project="year", energy_budget_balancing_type="day"
        )
        instance = self.build_instance(STOR_STRESS_HRZ_MODULE)
        self.assertEqual(
            {prj: "day"},
            dict(instance.stor_stress_hrz_energy_budget_balancing_type.items()),
        )
        self.assertListEqual(
            [(prj, "day", 202001), (prj, "day", 202002)],
            sorted(instance.STOR_STRESS_HRZ_OPR_BT_HRZ),
        )
        self.assertListEqual(
            [(prj, "day", 202002)], sorted(instance.STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ)
        )
        # First stress-horizon timepoint is anchored (tracked from no other
        # timepoint); the next one tracks from it
        self.assertEqual(set(), self.tracked_from_tmps(instance, prj, 20200201))
        self.assertEqual({20200201}, self.tracked_from_tmps(instance, prj, 20200202))
        # The tuning-cost power delta follows the year: at the stress
        # horizon's first timepoint it reaches back into the preceding
        # average-condition day (which has no discharging variable)
        self.assertIsNotNone(
            STOR_STRESS_HRZ_MODULE.power_delta_rule(instance, prj, 20200201)
        )

    def test_stor_stress_hrz_default_power_delta_skips_linear_day_start(self):
        instance = self.build_instance(STOR_STRESS_HRZ_MODULE)
        self.assertIsNone(
            STOR_STRESS_HRZ_MODULE.power_delta_rule(
                instance, "Battery_Stress_Hrz", 20200201
            )
        )


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

    def set_inputs_for(self, project, balancing_type_project, energy_budget_bt):
        """
        Add a non-hydro opchar row; 'Other' is in the portfolio, any other
        name is not.
        """
        c = self.conn.cursor()
        if project == "Other":
            c.execute("""INSERT INTO inputs_project_portfolios
                (project_portfolio_scenario_id, project, capacity_type)
                VALUES (1, 'Other', 'gen_spec')""")
        c.execute(
            """INSERT INTO inputs_project_operational_chars
            (project_operational_chars_scenario_id, project, operational_type,
            balancing_type_project, energy_budget_balancing_type)
            VALUES (1, ?, 'gen_simple', ?, ?)""",
            (project, balancing_type_project, energy_budget_bt),
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

    def set_shaping_inputs(self, balancing_type_project, energy_budget_bt, rows):
        c = self.conn.cursor()
        c.execute("""INSERT INTO inputs_project_portfolios
            (project_portfolio_scenario_id, project, capacity_type)
            VALUES (1, 'Shaped', 'energy_spec')""")
        c.execute(
            """INSERT INTO inputs_project_operational_chars
            (project_operational_chars_scenario_id, project, operational_type,
            balancing_type_project, energy_budget_balancing_type,
            energy_hrz_shaping_scenario_id)
            VALUES (1, 'Shaped', 'energy_hrz_shaping', ?, ?, 1)""",
            (balancing_type_project, energy_budget_bt),
        )
        c.execute("""INSERT INTO inputs_project_energy_hrz_shaping_iterations
            (project, energy_hrz_shaping_scenario_id,
            varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES ('Shaped', 1, 0, 0)""")
        for bt, hrz in rows:
            c.execute(
                """INSERT INTO inputs_project_energy_hrz_shaping
                (project, energy_hrz_shaping_scenario_id, weather_iteration,
                hydro_iteration, stage_id, balancing_type_project, horizon,
                hrz_energy_fraction, min_power, max_power)
                VALUES ('Shaped', 1, 0, 0, 1, ?, ?, 0.5, 1, 6)""",
                (bt, hrz),
            )
        self.conn.commit()

    def get_shaping_validation_errors(self):
        df = cursor_to_df(
            ENERGY_HRZ_SHAPING_MODULE.get_energy_hrz_shaping_inputs_from_db(
                subscenarios=SubScenariosStub(),
                weather_iteration=0,
                hydro_iteration=0,
                availability_iteration=0,
                subproblem=1,
                stage=1,
                conn=self.conn,
            )
        )
        validate_energy_budget_balancing_type_rows(
            conn=self.conn,
            scenario_id=1,
            subscenarios=SubScenariosStub(),
            weather_iteration=0,
            hydro_iteration=0,
            availability_iteration=0,
            subproblem=1,
            stage=1,
            op_type="energy_hrz_shaping",
            db_table="inputs_project_energy_hrz_shaping",
            df=df,
        )
        return self.conn.execute(
            "SELECT severity, description FROM status_validation"
        ).fetchall()

    def test_energy_hrz_shaping_rows_by_budget_balancing_type_pass(self):
        self.set_shaping_inputs("day", "year", [("year", 2020)])
        self.assertListEqual([], self.get_shaping_validation_errors())

    def test_energy_hrz_shaping_rows_for_other_balancing_type_flagged(self):
        self.set_shaping_inputs("day", "year", [("day", 202001), ("day", 202002)])
        errors = self.get_shaping_validation_errors()
        self.assertEqual(1, len(errors))
        self.assertIn("inputs_project_energy_hrz_shaping", errors[0][1])
        self.assertIn("['day']", errors[0][1])

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

    def get_balancing_type_errors(self):
        return validate_project_balancing_types(
            conn=self.conn, subscenarios=SubScenariosStub(), subproblem=1, stage=1
        )

    def test_balancing_types_in_temporal_scenario_pass(self):
        self.set_inputs("year", "day", [("day", 202001), ("day", 202002)])
        self.assertListEqual([], self.get_balancing_type_errors())
        self.set_inputs_for("Other", "day", None)
        self.assertListEqual([], self.get_balancing_type_errors())

    def test_energy_budget_balancing_type_not_in_temporal_scenario_flagged(self):
        self.set_inputs("year", "month", [("year", 2020)])
        errors = self.get_balancing_type_errors()
        self.assertEqual(1, len(errors))
        self.assertIn("energy_budget_balancing_type ['month']", errors[0])
        self.assertIn("['Hydro']", errors[0])

    def test_balancing_type_project_not_in_temporal_scenario_flagged(self):
        self.set_inputs("month", None, [("month", 202001)])
        errors = self.get_balancing_type_errors()
        self.assertEqual(1, len(errors))
        self.assertIn("balancing_type_project ['month']", errors[0])

    def test_projects_outside_portfolio_ignored(self):
        self.set_inputs("year", "day", [("day", 202001)])
        self.set_inputs_for("Not_In_Portfolio", "month", "week")
        self.assertListEqual([], self.get_balancing_type_errors())


if __name__ == "__main__":
    unittest.main()
