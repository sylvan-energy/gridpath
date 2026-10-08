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
Period coverage of the specified-capacity inputs.

A specified project is operational in exactly the periods for which it has a
capacity row, so one portfolio and one specified-capacity subscenario can
serve a run over 2030 and 2035 together as well as a run over either period
alone, with some projects having capacity in only one of the two. Until
October 2026 a project with no row in any period of the subproblem failed
validation at High severity and raised at model load, which forced either
zero-capacity rows (every project in every model) or a portfolio per horizon.
A row with every capacity column blank, as a dense project-by-period grid
naturally produces, counts as absent; a row with some but not all of a
type's capacity columns filled in is still a missing-input error.
"""

import os.path
import shutil
import sqlite3
import tempfile
import unittest

import pandas as pd

from gridpath.project.capacity.capacity_types import gen_spec, stor_spec
from gridpath.project.capacity.capacity_types.common_methods import (
    spec_get_inputs_from_database,
)
from tests.common_functions import add_components_and_load_data
from tests.project.capacity.capacity_types.test_gen_spec import (
    IMPORTED_PREREQ_MODULES,
    MODULE_BEING_TESTED,
    TEST_DATA_DIRECTORY,
)

DB_SCHEMA = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db", "db_schema.sql"
)

# Temporal scenario 1 has 2030 and 2035 in separate subproblems, 2 has both
# in one subproblem, and 3 adds 2040 to that single subproblem
PERIODS_BY_TEMPORAL_SCENARIO_AND_SUBPROBLEM = {
    1: {1: [2030], 2: [2035]},
    2: {1: [2030, 2035]},
    3: {1: [2030, 2035, 2040]},
}

# Capacity (MW) by project and period; Gap skips 2035 between two periods
# with capacity, and Blank has a 2035 row with no capacity in it
CAPACITY_ROWS = {
    "Retiring": {2030: 10},
    "Coming_Online": {2035: 10},
    "Always": {2030: 10, 2035: 10, 2040: 10},
    "Gap": {2030: 10, 2040: 10},
    "Blank": {2030: 10, 2035: None},
}

PORTFOLIO_SCENARIO_ID = 1
OPCHAR_SCENARIO_ID = 1
SPEC_CAPACITY_SCENARIO_ID = 1


class SubScenarios(object):
    """Stand-in for the SubScenarios object the module reads IDs from."""

    def __init__(self, temporal_scenario_id):
        self.TEMPORAL_SCENARIO_ID = temporal_scenario_id
        self.PROJECT_PORTFOLIO_SCENARIO_ID = PORTFOLIO_SCENARIO_ID
        self.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID = OPCHAR_SCENARIO_ID
        self.PROJECT_SPECIFIED_CAPACITY_SCENARIO_ID = SPEC_CAPACITY_SCENARIO_ID
        self.PROJECT_SPECIFIED_FIXED_COST_SCENARIO_ID = "NULL"


class TestSpecCapacityCoverageValidation(unittest.TestCase):
    """
    The validation findings of gen_spec for the fixture above; the other
    specified capacity types share the check.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA) as f:
            self.conn.executescript(f.read())
        c = self.conn.cursor()

        for tsid, subproblems in PERIODS_BY_TEMPORAL_SCENARIO_AND_SUBPROBLEM.items():
            periods = sorted(p for prds in subproblems.values() for p in prds)
            c.executemany(
                "INSERT INTO inputs_temporal_periods (temporal_scenario_id, period) "
                "VALUES (?, ?)",
                [(tsid, p) for p in periods],
            )
            for subproblem, prds in subproblems.items():
                c.executemany(
                    """INSERT INTO inputs_temporal
                    (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                     period, number_of_hours_in_timepoint, timepoint_weight,
                     spinup_or_lookahead)
                    VALUES (?, ?, 1, ?, ?, 1, 1, 0)""",
                    [(tsid, subproblem, p * 100 + 1, p) for p in prds],
                )

        self.add_projects(CAPACITY_ROWS.keys())
        self.add_capacity_rows(
            [
                (prj, p, mw)
                for prj, rows in CAPACITY_ROWS.items()
                for p, mw in rows.items()
            ]
        )

    def tearDown(self):
        self.conn.close()

    def add_projects(self, projects, capacity_type="gen_spec"):
        c = self.conn.cursor()
        for prj in projects:
            c.execute(
                """INSERT INTO inputs_project_portfolios
                (project_portfolio_scenario_id, project, specified, new_build,
                 capacity_type)
                VALUES (?, ?, 1, 0, ?)""",
                (PORTFOLIO_SCENARIO_ID, prj, capacity_type),
            )
            c.execute(
                """INSERT INTO inputs_project_operational_chars
                (project_operational_chars_scenario_id, project,
                 operational_type)
                VALUES (?, ?, 'gen_simple')""",
                (OPCHAR_SCENARIO_ID, prj),
            )
        self.conn.commit()

    def add_capacity_rows(self, rows):
        """
        Insert (project, period, specified_capacity_mw) rows, or
        (project, period, specified_capacity_mw, specified_stor_capacity_mwh)
        ones; None inserts NULL.
        """
        self.conn.cursor().executemany(
            """INSERT INTO inputs_project_specified_capacity
            (project_specified_capacity_scenario_id, project, period,
             specified_capacity_mw, specified_stor_capacity_mwh)
            VALUES (?, ?, ?, ?, ?)""",
            [
                (SPEC_CAPACITY_SCENARIO_ID,) + tuple(r) + (None,) * (4 - len(r))
                for r in rows
            ],
        )
        self.conn.commit()

    def findings(self, temporal_scenario_id, subproblem):
        """
        Run the validation for one subproblem and return its findings as
        (severity, description) tuples.
        """
        c = self.conn.cursor()
        c.execute("DELETE FROM status_validation")
        gen_spec.validate_inputs(
            scenario_id=1,
            subscenarios=SubScenarios(temporal_scenario_id),
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem=subproblem,
            stage=1,
            conn=self.conn,
        )
        return c.execute(
            "SELECT severity, description FROM status_validation"
        ).fetchall()

    def test_projects_with_capacity_in_one_period_pass_the_combined_run(self):
        self.assertEqual(self.findings(temporal_scenario_id=2, subproblem=1), [])

    def test_a_project_with_no_capacity_in_the_subproblem_is_a_low_note(self):
        # Gap has no 2035 row and Blank's 2035 row has no capacity, so both
        # sit out the 2035 subproblem
        for subproblem, absent in [
            (1, "['Coming_Online']"),
            (2, "['Blank', 'Gap', 'Retiring']"),
        ]:
            with self.subTest(subproblem=subproblem):
                findings = self.findings(temporal_scenario_id=1, subproblem=subproblem)
                self.assertEqual(len(findings), 1, findings)
                severity, description = findings[0]
                self.assertEqual(severity, "Low")
                self.assertIn(absent, description)
                self.assertIn("will not be operational", description)

    def test_a_gap_between_covered_periods_is_a_low_note(self):
        findings = self.findings(temporal_scenario_id=3, subproblem=1)
        self.assertEqual(len(findings), 1, findings)
        severity, description = findings[0]
        self.assertEqual(severity, "Low")
        self.assertIn("Non-contiguous", description)
        self.assertIn("{'Gap': [2035]}", description)
        # Capacity ending early (Retiring) or starting late (Coming_Online)
        # is a retirement or a new unit, not a gap
        self.assertNotIn("Retiring", description)
        self.assertNotIn("Coming_Online", description)

    def test_a_project_with_no_capacity_row_at_all_is_an_error(self):
        self.add_projects(["Misnamed"])
        for temporal_scenario_id, subproblem in [(2, 1), (1, 1), (1, 2)]:
            with self.subTest(temporal_scenario_id=temporal_scenario_id):
                findings = self.findings(temporal_scenario_id, subproblem)
                high = [d for s, d in findings if s == "High"]
                self.assertEqual(len(high), 1, findings)
                self.assertIn("['Misnamed']", high[0])
                self.assertIn("at least one period", high[0])

    def test_a_blank_row_is_not_written_to_the_model_inputs(self):
        rows = spec_get_inputs_from_database(
            self.conn, SubScenarios(temporal_scenario_id=2), 1, "gen_spec"
        ).fetchall()
        blank_rows = [(r[0], r[1]) for r in rows if r[0] == "Blank"]
        self.assertEqual(blank_rows, [("Blank", 2030)])

    def test_a_project_with_only_blank_rows_is_an_error(self):
        self.add_projects(["All_Blank"])
        self.add_capacity_rows([("All_Blank", 2030, None), ("All_Blank", 2035, None)])
        findings = self.findings(temporal_scenario_id=2, subproblem=1)
        high = [d for s, d in findings if s == "High"]
        self.assertEqual(len(high), 1, findings)
        self.assertIn("['All_Blank']", high[0])

    def test_a_partly_blank_row_is_still_a_missing_input(self):
        # Storage needs both a power and an energy capacity; a row with one
        # of them is incomplete, not absent
        self.add_projects(["Partial"], capacity_type="stor_spec")
        self.add_capacity_rows([("Partial", 2030, 10, None)])
        c = self.conn.cursor()
        c.execute("DELETE FROM status_validation")
        stor_spec.validate_inputs(
            scenario_id=1,
            subscenarios=SubScenarios(temporal_scenario_id=2),
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem=1,
            stage=1,
            conn=self.conn,
        )
        findings = c.execute(
            "SELECT severity, description FROM status_validation"
        ).fetchall()
        high = [d for s, d in findings if s == "High"]
        self.assertEqual(len(high), 1, findings)
        self.assertIn("Missing specified_stor_capacity_mwh", high[0])
        self.assertIn("Partial", high[0])


class TestSpecCapacityCoverageModelLoad(unittest.TestCase):
    """
    A specified project with no capacity row in any of the subproblem's
    periods loads as a project with no operational periods.
    """

    def test_project_without_capacity_rows_has_no_operational_periods(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        test_data_dir = os.path.join(tmp_dir.name, "test_data")
        shutil.copytree(TEST_DATA_DIRECTORY, test_data_dir)

        params_file = os.path.join(
            test_data_dir, "inputs", "spec_capacity_period_params.tab"
        )
        params = pd.read_csv(params_file, sep="\t")
        params[params["project"] != "Nuclear"].to_csv(
            params_file, sep="\t", index=False
        )

        m, data = add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=test_data_dir,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        instance = m.create_instance(data)

        self.assertIn("Nuclear", instance.PROJECTS)
        self.assertEqual(
            [prj for (prj, prd) in instance.GEN_SPEC_OPR_PRDS if prj == "Nuclear"], []
        )
        # The other projects are unaffected
        self.assertIn(("Gas_CCGT", 2020), instance.GEN_SPEC_OPR_PRDS)
        self.assertIn(("Gas_CCGT", 2030), instance.GEN_SPEC_OPR_PRDS)


if __name__ == "__main__":
    unittest.main()
