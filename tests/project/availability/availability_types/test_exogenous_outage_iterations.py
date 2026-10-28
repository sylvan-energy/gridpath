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
Iteration keying of the outage exogenous availability derates.

The rows of inputs_project_availability_exogenous_outage are keyed by
weather and availability iteration. A project's derates vary by the weather
iteration only when its row in
inputs_project_availability_exogenous_outage_iterations says so (no row:
they do not); the rows of a project that does not vary by weather iteration
sit at weather_iteration 0 and are read whatever the run's weather
iteration is.
"""

import os.path
import sqlite3
import unittest

from gridpath.project.availability.availability_types.exogenous import (
    check_outage_iteration_config,
    get_inputs_from_database,
    get_outage_derate_sql,
    get_unread_outage_rows,
)

DB_SCHEMA = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db", "db_schema.sql"
)

TIMEPOINTS = [1, 2, 3]

# project: varies_by_weather_iteration; None = no row in the iterations table
PROJECTS = {
    "Fixed": None,
    "Unflagged": 0,
    "WeatherVaries": 1,
}

# (project, weather_iteration, availability_iteration): derate (the same in
# every timepoint)
DERATES = {
    ("Fixed", 0, 1): 0.9,
    ("Fixed", 0, 2): 0.8,
    ("Unflagged", 0, 1): 0.85,
    ("WeatherVaries", 1, 1): 0.71,
    ("WeatherVaries", 2, 1): 0.72,
    ("WeatherVaries", 1, 2): 0.61,
    ("WeatherVaries", 2, 2): 0.62,
}


class SubScenarios(object):
    """Stand-in for the SubScenarios object the module reads IDs from."""

    TEMPORAL_SCENARIO_ID = 1
    PROJECT_PORTFOLIO_SCENARIO_ID = 1
    PROJECT_AVAILABILITY_SCENARIO_ID = 1


def build_fixture_db():
    conn = sqlite3.connect(":memory:")
    with open(DB_SCHEMA) as f:
        conn.executescript(f.read())

    conn.executemany(
        "INSERT INTO inputs_temporal (temporal_scenario_id, subproblem_id, "
        "stage_id, timepoint, period, number_of_hours_in_timepoint, "
        "timepoint_weight, spinup_or_lookahead) VALUES (1, 1, 1, ?, 2030, 1, 1, 0);",
        [(tmp,) for tmp in TIMEPOINTS],
    )
    for project, flag in PROJECTS.items():
        conn.execute(
            "INSERT INTO inputs_project_portfolios (project_portfolio_scenario_id, "
            "project, capacity_type) VALUES (1, ?, 'gen_spec');",
            (project,),
        )
        conn.execute(
            "INSERT INTO inputs_project_availability "
            "(project_availability_scenario_id, project, availability_type, "
            "exogenous_availability_outage_scenario_id) "
            "VALUES (1, ?, 'exogenous', 1);",
            (project,),
        )
        if flag is not None:
            conn.execute(
                "INSERT INTO inputs_project_availability_exogenous_outage_iterations "
                "VALUES (?, 1, ?);",
                (project, flag),
            )
    conn.executemany(
        "INSERT INTO inputs_project_availability_exogenous_outage "
        "(project, exogenous_availability_outage_scenario_id, weather_iteration, "
        "availability_iteration, stage_id, timepoint, availability_derate_outage) "
        "VALUES (?, 1, ?, ?, 1, ?, ?);",
        [
            (prj, w, a, tmp, derate)
            for (prj, w, a), derate in DERATES.items()
            for tmp in TIMEPOINTS
        ],
    )
    conn.commit()

    return conn


def outage_table_lookups(conn, sql):
    """
    :return: the EXPLAIN QUERY PLAN details of the outage table's lookups
    """
    return [
        detail
        for (*_, detail) in conn.execute(f"EXPLAIN QUERY PLAN {sql}")
        if detail.split()[:2]
        in (
            ["SEARCH", "inputs_project_availability_exogenous_outage"],
            ["SCAN", "inputs_project_availability_exogenous_outage"],
        )
    ]


def get_outage_derates(conn, weather_iteration, avl_iteration):
    outage_availabilities = get_inputs_from_database(
        scenario_id=1,
        subscenarios=SubScenarios(),
        weather_iteration=weather_iteration,
        hydro_iteration=0,
        availability_iteration=avl_iteration,
        subproblem=1,
        stage=1,
        conn=conn,
    )[0]

    return {(prj, tmp): derate for prj, tmp, derate, _ in outage_availabilities}


class TestExogenousOutageIterations(unittest.TestCase):
    def setUp(self):
        self.conn = build_fixture_db()

    def tearDown(self):
        self.conn.close()

    def test_each_project_reads_its_own_iteration(self):
        """Each project's rows come from the run's weather iteration when the
        project varies by it and from weather_iteration 0 otherwise."""
        for weather, avl, expected in [
            (1, 1, {"Fixed": 0.9, "Unflagged": 0.85, "WeatherVaries": 0.71}),
            (2, 1, {"Fixed": 0.9, "Unflagged": 0.85, "WeatherVaries": 0.72}),
            (2, 2, {"Fixed": 0.8, "Unflagged": None, "WeatherVaries": 0.62}),
        ]:
            derates = get_outage_derates(self.conn, weather, avl)
            self.assertDictEqual(
                derates,
                {
                    (prj, tmp): derate
                    for prj, derate in expected.items()
                    if derate is not None
                    for tmp in TIMEPOINTS
                },
                (weather, avl),
            )

    def test_run_without_weather_iterations_raises(self):
        """A project cannot vary by weather iteration when the run has none."""
        with self.assertRaises(ValueError) as context:
            check_outage_iteration_config(
                subscenarios=SubScenarios(), weather_iteration=0, conn=self.conn
            )
        self.assertIn("['WeatherVaries']", str(context.exception))

        with self.assertRaises(ValueError):
            get_outage_derates(self.conn, 0, 1)

        # Fine when the run has weather iterations
        check_outage_iteration_config(
            subscenarios=SubScenarios(), weather_iteration=1, conn=self.conn
        )

    def test_rows_at_a_weather_iteration_not_varied_by_are_reported(self):
        """Rows at a non-zero weather iteration of a project not flagged to
        vary by it are never read; validation reports them."""
        self.assertEqual(get_unread_outage_rows(SubScenarios(), self.conn), [])

        self.conn.execute(
            "INSERT INTO inputs_project_availability_exogenous_outage "
            "(project, exogenous_availability_outage_scenario_id, "
            "weather_iteration, availability_iteration, stage_id, timepoint, "
            "availability_derate_outage) "
            "VALUES ('Fixed', 1, 2, 1, 1, 1, 0.5), ('Unflagged', 1, 3, 1, 1, 1, 0.5);"
        )
        self.assertEqual(
            get_unread_outage_rows(SubScenarios(), self.conn),
            [("Fixed", 2), ("Unflagged", 3)],
        )
        # ... and the rows are indeed not read
        self.assertEqual(get_outage_derates(self.conn, 2, 1)[("Fixed", 1)], 0.9)

        # Negative weather iterations are reported too
        self.conn.execute(
            "INSERT INTO inputs_project_availability_exogenous_outage "
            "(project, exogenous_availability_outage_scenario_id, "
            "weather_iteration, availability_iteration, stage_id, timepoint, "
            "availability_derate_outage) "
            "VALUES ('Unflagged', 1, -1, 1, 1, 1, 0.5);"
        )
        self.assertEqual(
            get_unread_outage_rows(SubScenarios(), self.conn),
            [("Fixed", 2), ("Unflagged", -1), ("Unflagged", 3)],
        )

    def test_outage_search_uses_iteration_keys(self):
        """The outage table is searched by its primary key including the
        weather and availability iterations: the weather iteration to read
        depends on the project's flag, so with the flag looked up in an
        inner loop SQLite reads every iteration of each project in every
        subproblem (hundreds of times slower on a table with many draws)."""
        lookups = outage_table_lookups(
            self.conn,
            get_outage_derate_sql(
                subscenarios=SubScenarios(),
                weather_iteration=2,
                availability_iteration=1,
                subproblem=1,
                stage=1,
            ),
        )
        self.assertEqual(len(lookups), 1, lookups)
        self.assertIn("weather_iteration=?", lookups[0])
        self.assertIn("availability_iteration=?", lookups[0])

    def test_unread_rows_search_by_weather_iteration_range(self):
        """The check for never-read rows searches only the non-zero weather
        iterations of the outage table instead of every row."""
        statements = []
        self.conn.set_trace_callback(statements.append)
        get_unread_outage_rows(SubScenarios(), self.conn)
        self.conn.set_trace_callback(None)

        lookups = outage_table_lookups(self.conn, statements[0])
        self.assertTrue(lookups)
        for lookup in lookups:
            self.assertRegex(lookup, r"weather_iteration[<>]\?")


if __name__ == "__main__":
    unittest.main()
