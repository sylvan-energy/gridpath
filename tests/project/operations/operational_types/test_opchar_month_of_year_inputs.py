# Copyright 2026 Sylvan Energy Analytics LLC
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
Test month-of-year rows for horizon-indexed opchar inputs: on the built-in
subproblem_period_month_* balancing types, a row with horizon 1-12 gives the
data for that month of every period without an explicit row; and the
get_inputs check that every project has rows.
"""

import os.path
import sqlite3
import unittest

from gridpath.project.operations.operational_types.common_functions import (
    get_prj_temporal_index_opr_inputs_from_db,
    require_bt_hrz_rows_for_every_project,
    BT_HRZ_INDEX_QUERY_PARAMS,
)

DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db", "db_schema.sql"
)

MONTH_BT = "subproblem_period_month_circular"


class SubScenariosStub:
    PROJECT_PORTFOLIO_SCENARIO_ID = 1
    PROJECT_OPERATIONAL_CHARS_SCENARIO_ID = 1
    TEMPORAL_SCENARIO_ID = 1


def get_hydro_opchar_inputs(conn, exclude_stage=False):
    results = get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=SubScenariosStub(),
        weather_iteration=0,
        hydro_iteration=0,
        availability_iteration=0,
        subproblem=1,
        stage=1,
        conn=conn,
        op_type="gen_hydro",
        table="inputs_project_hydro_operational_chars",
        subscenario_id_column="hydro_operational_chars_scenario_id",
        data_column="average_power_fraction",
        opr_index_dict=BT_HRZ_INDEX_QUERY_PARAMS,
        exclude_stage=exclude_stage,
    )

    return sorted(results.fetchall())


class TestOpcharMonthOfYearInputs(unittest.TestCase):
    """
    Build an in-memory database from the real schema with periods 2020 and
    2030, two months each (one timepoint per month), the built-in month
    horizons (202001, 202002, 203001, 203002), and one 'day' horizon per
    timepoint with the same IDs; subproblem 1, stage 1.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        c = self.conn.cursor()

        for period in [2020, 2030]:
            for month in [1, 2]:
                tmp = period * 10000 + month * 100 + 1
                hrz = period * 100 + month
                c.execute(
                    """INSERT INTO inputs_temporal
                    (temporal_scenario_id, subproblem_id, stage_id,
                    timepoint, period, number_of_hours_in_timepoint,
                    timepoint_weight, spinup_or_lookahead, month)
                    VALUES (1, 1, 1, ?, ?, 1, 4380, 0, ?)""",
                    (tmp, period, month),
                )
                for bt in [MONTH_BT, "day"]:
                    c.execute(
                        """INSERT INTO inputs_temporal_horizon_timepoints
                        (temporal_scenario_id, subproblem_id, stage_id,
                        timepoint, balancing_type_horizon, horizon)
                        VALUES (1, 1, 1, ?, ?, ?)""",
                        (tmp, bt, hrz),
                    )

        self.projects = ["Hydro_MOY", "Hydro_Explicit", "Hydro_Mapped", "Hydro_Day"]
        c.executemany(
            """INSERT INTO inputs_project_portfolios
            (project_portfolio_scenario_id, project, capacity_type)
            VALUES (1, ?, 'gen_hydro_spec')""",
            [(prj,) for prj in self.projects],
        )
        # Hydro_Mapped uses horizon map 1 (203001 --> 202001)
        c.executemany(
            """INSERT INTO inputs_project_operational_chars
            (project_operational_chars_scenario_id, project,
            operational_type, balancing_type_project,
            hydro_operational_chars_scenario_id,
            hydro_operational_chars_hrz_map_scenario_id)
            VALUES (1, ?, 'gen_hydro', ?, 1, ?)""",
            [
                ("Hydro_MOY", MONTH_BT, None),
                ("Hydro_Explicit", MONTH_BT, None),
                ("Hydro_Mapped", MONTH_BT, 1),
                ("Hydro_Day", "day", None),
            ],
        )
        c.execute("""INSERT INTO inputs_project_opchar_horizon_map
            (opchar_horizon_map_scenario_id, balancing_type_horizon,
            horizon, data_horizon)
            VALUES (1, 'subproblem_period_month_circular', 203001, 202001)""")

        self.insert_rows(
            [
                # Month-of-year rows, with an explicit row overriding month 2
                # in 2030
                ("Hydro_MOY", 1, MONTH_BT, 1, 0.1),
                ("Hydro_MOY", 1, MONTH_BT, 2, 0.2),
                ("Hydro_MOY", 1, MONTH_BT, 203002, 0.9),
                # Explicit rows only (plus a month-of-year row that they all
                # override)
                ("Hydro_Explicit", 1, MONTH_BT, 1, 0.5),
                ("Hydro_Explicit", 1, MONTH_BT, 202001, 0.11),
                ("Hydro_Explicit", 1, MONTH_BT, 202002, 0.12),
                ("Hydro_Explicit", 1, MONTH_BT, 203001, 0.31),
                ("Hydro_Explicit", 1, MONTH_BT, 203002, 0.32),
                # Mapped: strict, the month-of-year rows are not read
                ("Hydro_Mapped", 1, MONTH_BT, 1, 0.5),
                ("Hydro_Mapped", 1, MONTH_BT, 2, 0.5),
                ("Hydro_Mapped", 1, MONTH_BT, 202001, 0.7),
                # Not a month balancing type: horizon 1 is just a horizon
                ("Hydro_Day", 1, "day", 1, 0.5),
            ]
        )
        c.executemany(
            """INSERT INTO inputs_project_hydro_operational_chars_iterations
            (project, hydro_operational_chars_scenario_id,
            varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES (?, 1, 0, 0)""",
            [(prj,) for prj in self.projects],
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def insert_rows(self, rows, stage=1):
        self.conn.executemany(
            f"""INSERT INTO inputs_project_hydro_operational_chars
            (project, hydro_operational_chars_scenario_id,
            weather_iteration, hydro_iteration, stage_id,
            balancing_type_project, horizon, average_power_fraction)
            VALUES (?, ?, 0, 0, {stage}, ?, ?, ?)""",
            rows,
        )

    def project_rows(self, prj, **kwargs):
        return [r for r in get_hydro_opchar_inputs(self.conn, **kwargs) if r[0] == prj]

    def test_month_of_year_rows_apply_to_every_period(self):
        """
        Month-of-year rows supply the months of every period without an
        explicit row, relabeled with the model horizon; the explicit 203002
        row takes precedence over the month 2 row.
        """
        self.assertEqual(
            self.project_rows("Hydro_MOY"),
            [
                ("Hydro_MOY", MONTH_BT, 202001, 0.1),
                ("Hydro_MOY", MONTH_BT, 202002, 0.2),
                ("Hydro_MOY", MONTH_BT, 203001, 0.1),
                ("Hydro_MOY", MONTH_BT, 203002, 0.9),
            ],
        )

    def test_explicit_rows_override_month_of_year_rows(self):
        self.assertEqual(
            self.project_rows("Hydro_Explicit"),
            [
                ("Hydro_Explicit", MONTH_BT, 202001, 0.11),
                ("Hydro_Explicit", MONTH_BT, 202002, 0.12),
                ("Hydro_Explicit", MONTH_BT, 203001, 0.31),
                ("Hydro_Explicit", MONTH_BT, 203002, 0.32),
            ],
        )

    def test_mapped_project_ignores_month_of_year_rows(self):
        """
        A project with a horizon map reads only what the map points to
        (202001 for itself and 203001); its unmapped month horizons read
        their own (missing) rows, not the month-of-year rows.
        """
        self.assertEqual(
            self.project_rows("Hydro_Mapped"),
            [
                ("Hydro_Mapped", MONTH_BT, 202001, 0.7),
                ("Hydro_Mapped", MONTH_BT, 203001, 0.7),
            ],
        )

    def test_other_balancing_types_have_no_month_of_year_rows(self):
        self.assertEqual(self.project_rows("Hydro_Day"), [])

    def test_month_of_year_rows_scoped_to_stage(self):
        """
        Another stage's explicit row doesn't block the month-of-year row,
        and another stage's month-of-year row isn't read; with
        exclude_stage, rows of every stage count.
        """
        self.insert_rows([("Hydro_MOY", 1, MONTH_BT, 202001, 0.8)], stage=2)
        self.insert_rows([("Hydro_Day", 1, MONTH_BT, 1, 0.4)], stage=2)
        self.conn.execute("""UPDATE inputs_project_operational_chars
            SET balancing_type_project = 'subproblem_period_month_circular'
            WHERE project = 'Hydro_Day'""")
        self.assertIn(
            ("Hydro_MOY", MONTH_BT, 202001, 0.1), self.project_rows("Hydro_MOY")
        )
        self.assertEqual(self.project_rows("Hydro_Day"), [])
        self.assertIn(
            ("Hydro_MOY", MONTH_BT, 202001, 0.8),
            self.project_rows("Hydro_MOY", exclude_stage=True),
        )
        self.assertNotIn(
            ("Hydro_MOY", MONTH_BT, 202001, 0.1),
            self.project_rows("Hydro_MOY", exclude_stage=True),
        )

    def test_require_rows_for_every_project(self):
        """
        The get_inputs check raises, naming the projects without rows
        (Hydro_Day), before anything is written; it passes once every
        project has rows.
        """
        check_rows = require_bt_hrz_rows_for_every_project(
            conn=self.conn,
            subscenarios=SubScenariosStub(),
            op_type="gen_hydro",
            db_table="inputs_project_hydro_operational_chars",
        )
        with self.assertRaisesRegex(ValueError, r"\['Hydro_Day'\]"):
            check_rows(get_hydro_opchar_inputs(self.conn))

        self.insert_rows([("Hydro_Day", 1, "day", 202001, 0.5)])
        check_rows(get_hydro_opchar_inputs(self.conn))


if __name__ == "__main__":
    unittest.main()
