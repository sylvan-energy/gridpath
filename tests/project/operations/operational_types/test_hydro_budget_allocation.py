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
Test the hydro energy-budget allocation limits shared by the gen_hydro*
operational types: the database query (with and without an opchar horizon
map), the input validation, and the model-side nesting checks. The loaded
values and constraint indexing are checked in test_gen_hydro_must_take (the
fixture's Hydro_NonCurtailable project has yearly budgets and daily
sub-horizon limits); the binding behavior is checked by the
2horizons_w_hydro_w_budget_allocation example.
"""

import contextlib
import csv
from importlib import import_module
import logging
import os.path
import shutil
import sqlite3
import tempfile
import unittest

from gridpath.project.operations.operational_types.gen_hydro_common import (
    get_hydro_budget_allocation_inputs_from_db,
    get_hydro_budget_allocation_results_file_name,
    import_hydro_budget_allocation_results_into_database,
    validate_hydro_budget_allocation,
    write_hydro_budget_allocation_inputs,
    HYDRO_BUDGET_ALLOCATION_RESULTS_COLUMNS,
    HYDRO_BUDGET_ALLOCATION_RESULTS_TABLE,
    HYDRO_BUDGET_ALLOCATION_TAB_FILE,
)
from tests.common_functions import add_components_and_load_data

DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db", "db_schema.sql"
)
TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
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


class SubScenariosStub:
    PROJECT_PORTFOLIO_SCENARIO_ID = 1
    PROJECT_OPERATIONAL_CHARS_SCENARIO_ID = 1
    TEMPORAL_SCENARIO_ID = 1


def get_allocation_inputs(conn):
    return sorted(
        get_hydro_budget_allocation_inputs_from_db(
            subscenarios=SubScenariosStub(),
            weather_iteration=0,
            hydro_iteration=0,
            availability_iteration=0,
            subproblem=1,
            stage=1,
            conn=conn,
            op_type="gen_hydro",
        ).fetchall()
    )


class TestHydroBudgetAllocationDatabase(unittest.TestCase):
    """
    In-memory database from the real schema with a two-month fixture: a
    'month' balancing type (the Hydro project's own) with horizons 202001
    and 202002, each covering two 'day' sub-horizons of two timepoints, and
    a 'week' balancing type whose single horizon straddles both months (so
    it is NOT nested). Allocation limits are specified for the two days of
    month 202001 only.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        c = self.conn.cursor()

        tmp_hrzs = [
            (2020010101, 202001, 202001),
            (2020010102, 202001, 202001),
            (2020010201, 202001, 202002),
            (2020010202, 202001, 202002),
            (2020020101, 202002, 202003),
            (2020020102, 202002, 202003),
            (2020020201, 202002, 202004),
            (2020020202, 202002, 202004),
        ]
        for tmp, month, day in tmp_hrzs:
            c.execute(
                """INSERT INTO inputs_temporal
                (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                period, number_of_hours_in_timepoint, timepoint_weight,
                spinup_or_lookahead)
                VALUES (1, 1, 1, ?, 2020, 1, 1, 0)""",
                (tmp,),
            )
            for bt, hrz in [("month", month), ("day", day), ("week", 202001)]:
                c.execute(
                    """INSERT INTO inputs_temporal_horizon_timepoints
                    (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                    balancing_type_horizon, horizon)
                    VALUES (1, 1, 1, ?, ?, ?)""",
                    (tmp, bt, hrz),
                )

        c.execute("""INSERT INTO inputs_project_portfolios
            (project_portfolio_scenario_id, project, capacity_type)
            VALUES (1, 'Hydro', 'gen_spec'), (1, 'Other_Hydro', 'gen_spec')""")
        # Other_Hydro is a gen_hydro project without allocation limits
        c.execute("""INSERT INTO inputs_project_operational_chars
            (project_operational_chars_scenario_id, project, operational_type,
            balancing_type_project, hydro_budget_allocation_scenario_id,
            hydro_budget_allocation_hrz_map_scenario_id)
            VALUES (1, 'Hydro', 'gen_hydro', 'month', 1, NULL),
            (1, 'Other_Hydro', 'gen_hydro', 'month', NULL, NULL)""")
        c.execute("""INSERT INTO inputs_project_hydro_budget_allocation
            (project, hydro_budget_allocation_scenario_id, weather_iteration,
            hydro_iteration, stage_id, balancing_type_horizon, horizon,
            min_budget_fraction, max_budget_fraction)
            VALUES ('Hydro', 1, 0, 0, 1, 'day', 202001, 0.45, 0.55),
            ('Hydro', 1, 0, 0, 1, 'day', 202002, 0.45, NULL)""")
        c.execute("""INSERT INTO inputs_project_hydro_budget_allocation_iterations
            (project, hydro_budget_allocation_scenario_id,
            varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES ('Hydro', 1, 0, 0)""")
        # Horizon map 1: the days of month 202002 read the data of the days
        # of month 202001
        c.execute("""INSERT INTO inputs_project_opchar_horizon_map
            (opchar_horizon_map_scenario_id, balancing_type_horizon, horizon,
            data_horizon)
            VALUES (1, 'day', 202003, 202001), (1, 'day', 202004, 202002)""")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def get_validation_errors(self):
        validate_hydro_budget_allocation(
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

    def test_inputs_without_map(self):
        """
        Only the specified sub-horizons are returned, NULL limits pass
        through, and projects without limits contribute no rows.
        """
        self.assertListEqual(
            [
                ("Hydro", "day", 202001, 0.45, 0.55),
                ("Hydro", "day", 202002, 0.45, None),
            ],
            get_allocation_inputs(self.conn),
        )

    def test_inputs_with_horizon_map(self):
        """
        With the horizon map assigned, the days of the second month read the
        first month's limits, relabeled with their own horizons.
        """
        self.conn.execute("""UPDATE inputs_project_operational_chars
            SET hydro_budget_allocation_hrz_map_scenario_id = 1
            WHERE project = 'Hydro'""")
        self.assertListEqual(
            [
                ("Hydro", "day", 202001, 0.45, 0.55),
                ("Hydro", "day", 202002, 0.45, None),
                ("Hydro", "day", 202003, 0.45, 0.55),
                ("Hydro", "day", 202004, 0.45, None),
            ],
            get_allocation_inputs(self.conn),
        )

    def test_validation_passes_for_nested_limits(self):
        self.assertListEqual([], self.get_validation_errors())

    def test_validation_flags_non_nested_sub_horizon(self):
        """
        The 'week' horizon straddles both months.
        """
        self.conn.execute("""INSERT INTO inputs_project_hydro_budget_allocation
            (project, hydro_budget_allocation_scenario_id, weather_iteration,
            hydro_iteration, stage_id, balancing_type_horizon, horizon,
            min_budget_fraction, max_budget_fraction)
            VALUES ('Hydro', 1, 0, 0, 1, 'week', 202001, 0.2, 0.3)""")
        errors = self.get_validation_errors()
        self.assertEqual(1, len(errors))
        self.assertEqual("High", errors[0][0])
        self.assertIn("not nested", errors[0][1])
        self.assertIn("'week', 202001", errors[0][1])

    def test_validation_flags_project_balancing_type(self):
        self.conn.execute("""INSERT INTO inputs_project_hydro_budget_allocation
            (project, hydro_budget_allocation_scenario_id, weather_iteration,
            hydro_iteration, stage_id, balancing_type_horizon, horizon,
            min_budget_fraction, max_budget_fraction)
            VALUES ('Hydro', 1, 0, 0, 1, 'month', 202001, 0.2, 0.3)""")
        errors = self.get_validation_errors()
        self.assertEqual(1, len(errors))
        self.assertEqual("High", errors[0][0])
        self.assertIn("own balancing type", errors[0][1])

    def test_validation_flags_share_sums_and_ranges(self):
        """
        Minimum shares summing to more than 1 and maximum shares summing to
        less than 1 within a parent horizon are flagged (Low), as are
        fractions outside [0, 1] (Low) and min > max (Mid).
        """
        self.conn.execute("""UPDATE inputs_project_hydro_budget_allocation
            SET min_budget_fraction = 0.6, max_budget_fraction = 0.45
            WHERE horizon = 202001""")
        self.conn.execute("""UPDATE inputs_project_hydro_budget_allocation
            SET min_budget_fraction = 0.6, max_budget_fraction = 1.2
            WHERE horizon = 202002""")
        errors = self.get_validation_errors()
        descriptions = " | ".join(d for _, d in errors)
        self.assertEqual(
            ["Low", "Low", "Mid"], sorted(severity for severity, _ in errors)
        )
        self.assertIn("minimum shares sum to more than 1", descriptions)
        self.assertNotIn("maximum shares sum to less than 1", descriptions)
        self.assertIn("<= 'max_budget_fraction' <= 1", descriptions)
        self.assertIn("Values cannot decrease", descriptions)

    def test_validation_flags_max_shares_summing_below_one(self):
        """
        With a maximum specified for every sub-horizon covering the parent
        horizon, maximum shares that sum to less than 1 are flagged (each
        stays at or above its own minimum, so nothing else is flagged).
        """
        self.conn.execute("""UPDATE inputs_project_hydro_budget_allocation
            SET max_budget_fraction = 0.5 WHERE horizon = 202001""")
        self.conn.execute("""UPDATE inputs_project_hydro_budget_allocation
            SET max_budget_fraction = 0.45 WHERE horizon = 202002""")
        errors = self.get_validation_errors()
        self.assertEqual(1, len(errors))
        self.assertEqual("Low", errors[0][0])
        self.assertIn("maximum shares sum to less than 1", errors[0][1])

    def test_both_hydro_op_types_share_one_tab_file(self):
        """
        Both hydro operational types write their limits to the same tab
        file, so the second writer must append its rows to the first
        writer's file rather than repeat the header (no example combines
        the two op types, so this is the only coverage of that path).
        """
        self.conn.execute("""UPDATE inputs_project_operational_chars
            SET operational_type = 'gen_hydro_must_take',
            hydro_budget_allocation_scenario_id = 2
            WHERE project = 'Other_Hydro'""")
        self.conn.execute("""INSERT INTO inputs_project_hydro_budget_allocation
            (project, hydro_budget_allocation_scenario_id, weather_iteration,
            hydro_iteration, stage_id, balancing_type_horizon, horizon,
            min_budget_fraction, max_budget_fraction)
            VALUES ('Other_Hydro', 2, 0, 0, 1, 'day', 202001, 0.5, 0.5)""")
        self.conn.execute("""INSERT INTO
            inputs_project_hydro_budget_allocation_iterations
            (project, hydro_budget_allocation_scenario_id,
            varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES ('Other_Hydro', 2, 0, 0)""")

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        os.makedirs(os.path.join(tmp_dir.name, "inputs"))
        for op_type in ["gen_hydro", "gen_hydro_must_take"]:
            write_hydro_budget_allocation_inputs(
                scenario_directory=tmp_dir.name,
                subscenarios=SubScenariosStub(),
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
                conn=self.conn,
                op_type=op_type,
            )
        with open(
            os.path.join(tmp_dir.name, "inputs", HYDRO_BUDGET_ALLOCATION_TAB_FILE)
        ) as f:
            lines = f.read().splitlines()
        self.assertEqual(
            [
                "project\tbalancing_type_horizon\thorizon\tmin_budget_fraction"
                "\tmax_budget_fraction",
                "Hydro\tday\t202001\t0.45\t0.55",
                "Hydro\tday\t202002\t0.45\t.",
                "Other_Hydro\tday\t202001\t0.5\t0.5",
            ],
            lines,
        )

    def test_share_sums_not_checked_when_parent_not_covered(self):
        """
        The share sums say nothing unless the sub-horizons cover the whole
        parent horizon: dropping the second day of month 202001 leaves
        maximum shares summing to 0.55, which must NOT be flagged.
        """
        self.conn.execute("""DELETE FROM inputs_project_hydro_budget_allocation
            WHERE horizon = 202002""")
        self.assertListEqual([], self.get_validation_errors())


class TestHydroBudgetAllocationResultsImport(unittest.TestCase):
    """
    The results of both hydro operational types land in one shared results
    table. A results CSV whose columns don't match the table's is only
    caught when the import actually runs, so the column lists are pinned
    against the real schema here too.
    """

    KEY_COLUMNS = [
        "scenario_id",
        "weather_iteration",
        "hydro_iteration",
        "availability_iteration",
        "subproblem_id",
        "stage_id",
    ]

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.addCleanup(self.conn.close)

    def table_columns(self):
        return [
            row[1]
            for row in self.conn.execute(
                f"PRAGMA table_info({HYDRO_BUDGET_ALLOCATION_RESULTS_TABLE})"
            )
        ]

    def write_results_csv(self, op_type, rows):
        path = os.path.join(
            self.tmp_dir.name, get_hydro_budget_allocation_results_file_name(op_type)
        )
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HYDRO_BUDGET_ALLOCATION_RESULTS_COLUMNS)
            writer.writerows(rows)

    def import_results(self, op_type):
        import_hydro_budget_allocation_results_into_database(
            scenario_id=1,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
            conn=self.conn,
            cursor=self.conn.cursor(),
            results_directory=self.tmp_dir.name,
            quiet=True,
            op_type=op_type,
        )

    def test_results_table_columns_match_the_csv(self):
        self.assertListEqual(
            self.KEY_COLUMNS + HYDRO_BUDGET_ALLOCATION_RESULTS_COLUMNS,
            self.table_columns(),
        )

    def test_both_op_types_import_into_one_table(self):
        """
        Each operational type imports its own CSV; the rows accumulate in
        the shared table. An unspecified limit has no constraint and so no
        dual, which arrives as NULL.
        """
        self.write_results_csv(
            "gen_hydro",
            [
                [
                    "Hydro",
                    "day",
                    202001,
                    "month",
                    202001,
                    0.45,
                    0.55,
                    4.5,
                    10,
                    0.45,
                    1.5,
                    "",
                ]
            ],
        )
        self.write_results_csv(
            "gen_hydro_must_take",
            [
                [
                    "Other_Hydro",
                    "day",
                    202001,
                    "month",
                    202001,
                    "",
                    0.6,
                    5.0,
                    10,
                    0.5,
                    "",
                    0,
                ]
            ],
        )
        for op_type in ["gen_hydro", "gen_hydro_must_take"]:
            self.import_results(op_type)

        self.assertListEqual(
            [
                ("Hydro", 0.45, 0.55, 1.5, None),
                ("Other_Hydro", None, 0.6, None, 0.0),
            ],
            self.conn.execute(
                f"""SELECT project, min_budget_fraction, max_budget_fraction,
                min_constraint_dual, max_constraint_dual
                FROM {HYDRO_BUDGET_ALLOCATION_RESULTS_TABLE}
                ORDER BY project"""
            ).fetchall(),
        )

    def test_missing_csv_is_skipped(self):
        """
        An operational type with no allocation limits writes no CSV; its
        import is a no-op rather than an error.
        """
        self.import_results("gen_hydro")
        self.assertEqual(
            0,
            self.conn.execute(
                f"SELECT COUNT(*) FROM {HYDRO_BUDGET_ALLOCATION_RESULTS_TABLE}"
            ).fetchone()[0],
        )


class TestHydroBudgetAllocationModelChecks(unittest.TestCase):
    """
    Model construction must fail loudly for allocation limits that don't
    nest: copies the unit-test fixture and edits the allocation tab file.
    The fixture's Hydro project has 'day' budgets and Hydro_NonCurtailable
    'year' budgets.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.test_data_dir = os.path.join(self.tmp_dir.name, "test_data")
        shutil.copytree(TEST_DATA_DIRECTORY, self.test_data_dir)

    def write_allocation_tab(self, rows):
        with open(
            os.path.join(
                self.test_data_dir, "inputs", HYDRO_BUDGET_ALLOCATION_TAB_FILE
            ),
            "w",
        ) as f:
            f.write(
                "project\tbalancing_type_horizon\thorizon\tmin_budget_fraction"
                "\tmax_budget_fraction\n"
            )
            for row in rows:
                f.write("\t".join(str(x) for x in row) + "\n")

    @staticmethod
    @contextlib.contextmanager
    def quiet_pyomo_construction_errors():
        """
        Pyomo logs a component-construction failure at ERROR level before
        re-raising it; silence that for deliberately failing constructions
        so a passing suite run stays free of error output.
        """
        logger = logging.getLogger("pyomo.core")
        was_disabled = logger.disabled
        logger.disabled = True
        try:
            yield
        finally:
            logger.disabled = was_disabled

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

    def test_missing_file_means_no_limits(self):
        os.remove(
            os.path.join(self.test_data_dir, "inputs", HYDRO_BUDGET_ALLOCATION_TAB_FILE)
        )
        instance = self.build_instance(GEN_HYDRO_MUST_TAKE_MODULE)
        self.assertEqual(0, len(instance.GEN_HYDRO_MUST_TAKE_BUDGET_ALLOC_BT_HRZS))

    def test_sub_horizon_straddling_project_horizons_raises(self):
        # The year horizon spans the day-budget project's day horizons
        self.write_allocation_tab([("Hydro", "year", 2020, 0.4, 0.6)])
        with self.quiet_pyomo_construction_errors():
            with self.assertRaisesRegex(
                ValueError, "not nested within a single horizon"
            ):
                self.build_instance(GEN_HYDRO_MODULE)

    def test_project_balancing_type_sub_horizon_raises(self):
        self.write_allocation_tab([("Hydro_NonCurtailable", "year", 2020, 0.4, 0.6)])
        with self.quiet_pyomo_construction_errors():
            with self.assertRaisesRegex(ValueError, "project's own balancing type"):
                self.build_instance(GEN_HYDRO_MUST_TAKE_MODULE)


if __name__ == "__main__":
    unittest.main()
