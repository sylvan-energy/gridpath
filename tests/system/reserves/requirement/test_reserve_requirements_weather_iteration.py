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
Weather iteration keying of the by-timepoint reserve requirements, for all
seven reserve types, against an in-memory database built from the real
schema: each BA's rows are read at the run's weather iteration when the BA
is flagged to vary by it and at weather iteration 0 otherwise, a flagged BA
fails in a run without weather iterations, and validation reports flagged
BAs without rows at the run's weather iteration and rows that are never
read.
"""

import importlib
import os
import sqlite3
import unittest
from types import SimpleNamespace

from gridpath.system.reserves.requirement.reserve_requirements import (
    get_bas_missing_weather_slice,
    get_tmp_requirement_sql,
    get_unread_requirement_rows,
)

REPO_DIRECTORY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

RESERVE_TYPES = [
    "lf_reserves_up",
    "lf_reserves_down",
    "regulation_up",
    "regulation_down",
    "frequency_response",
    "spinning_reserves",
    "inertia_reserves",
]

TIMEPOINTS = [1, 2]

# (BA, weather_iteration): requirement in timepoints 1 and 2; BA_FLAT does not
# vary by weather iteration (no flag row) and carries a never-read row at
# weather iteration 3; BA_WEATHER is flagged and has slices 1 and 2 only
ROWS = {
    ("BA_FLAT", 0): [10, 11],
    ("BA_FLAT", 3): [99, 99],
    ("BA_WEATHER", 1): [21, 22],
    ("BA_WEATHER", 2): [31, 32],
}


def requirement_column(reserve_type):
    return (
        "inertia_reserves_mws"
        if reserve_type == "inertia_reserves"
        else f"{reserve_type}_mw"
    )


def make_db(reserve_type):
    conn = sqlite3.connect(":memory:")
    with open(os.path.join(REPO_DIRECTORY, "db", "db_schema.sql")) as f:
        conn.executescript(f.read())

    conn.executemany(
        """INSERT INTO inputs_temporal
        (temporal_scenario_id, subproblem_id, stage_id, timepoint, period,
        number_of_hours_in_timepoint, timepoint_weight, spinup_or_lookahead)
        VALUES (1, 1, 1, ?, 2030, 1, 1, 0);""",
        [(tmp,) for tmp in TIMEPOINTS],
    )
    conn.execute(
        f"INSERT INTO subscenarios_system_{reserve_type} "
        f"({reserve_type}_scenario_id) VALUES (1);"
    )
    conn.executemany(
        f"""INSERT INTO inputs_geography_{reserve_type}_bas
        ({reserve_type}_ba_scenario_id, {reserve_type}_ba) VALUES (1, ?);""",
        [("BA_FLAT",), ("BA_WEATHER",)],
    )
    conn.executemany(
        f"""INSERT INTO inputs_system_{reserve_type}
        ({reserve_type}_scenario_id, {reserve_type}_ba, weather_iteration,
        stage_id, timepoint, {requirement_column(reserve_type)})
        VALUES (1, ?, ?, 1, ?, ?);""",
        [
            (ba, weather, tmp, req)
            for (ba, weather), reqs in ROWS.items()
            for tmp, req in zip(TIMEPOINTS, reqs)
        ],
    )
    conn.execute(f"""INSERT INTO inputs_system_{reserve_type}_iterations
        ({reserve_type}_scenario_id, {reserve_type}_ba,
        varies_by_weather_iteration)
        VALUES (1, 'BA_WEATHER', 1);""")

    return conn


def requirement_table_lookups(conn, reserve_type, sql):
    """
    :return: the EXPLAIN QUERY PLAN details of the requirement table's
        lookups
    """
    return [
        detail
        for (*_, detail) in conn.execute(f"EXPLAIN QUERY PLAN {sql}")
        if detail.split()[:2]
        in (
            ["SEARCH", f"inputs_system_{reserve_type}"],
            ["SCAN", f"inputs_system_{reserve_type}"],
        )
    ]


def make_subscenarios(reserve_type):
    return SimpleNamespace(
        TEMPORAL_SCENARIO_ID=1,
        PROJECT_PORTFOLIO_SCENARIO_ID="NULL",
        LOAD_SCENARIO_ID="NULL",
        **{
            f"{reserve_type.upper()}_BA_SCENARIO_ID": 1,
            f"{reserve_type.upper()}_SCENARIO_ID": 1,
        },
    )


def req_kwargs(conn, reserve_type):
    return dict(
        conn=conn,
        reserve_type=reserve_type,
        reserve_type_ba_subscenario_id=1,
        reserve_type_req_subscenario_id=1,
    )


class TestReserveRequirementWeatherIteration(unittest.TestCase):
    def read_tmp_requirement(self, reserve_type, conn, weather_iteration):
        """
        :return: {(BA, timepoint): requirement} read by the reserve type's
            module for the weather iteration
        """
        module = importlib.import_module(
            f"gridpath.system.reserves.requirement.{reserve_type}"
        )
        tmp_req = module.get_inputs_from_database(
            scenario_id=1,
            subscenarios=make_subscenarios(reserve_type),
            weather_iteration=weather_iteration,
            hydro_iteration=0,
            availability_iteration=0,
            subproblem=1,
            stage=1,
            conn=conn,
        )[0]
        return {(ba, tmp): req for (ba, tmp, req, *_) in tmp_req.fetchall()}

    def expected(self, weather_slices):
        return {
            (ba, tmp): req
            for (ba, weather), reqs in ROWS.items()
            if weather_slices[ba] == weather
            for tmp, req in zip(TIMEPOINTS, reqs)
        }

    def test_each_weather_iteration_reads_its_own_slice(self):
        for reserve_type in RESERVE_TYPES:
            conn = make_db(reserve_type)
            for weather in [1, 2]:
                with self.subTest(reserve_type=reserve_type, weather=weather):
                    self.assertDictEqual(
                        self.read_tmp_requirement(reserve_type, conn, weather),
                        self.expected({"BA_FLAT": 0, "BA_WEATHER": weather}),
                    )
            conn.close()

    def test_flagged_ba_without_slice_reads_nothing(self):
        """BA_WEATHER has no rows at weather iteration 3: it reads nothing
        rather than falling back to weather iteration 0 or another slice."""
        for reserve_type in RESERVE_TYPES:
            with self.subTest(reserve_type=reserve_type):
                conn = make_db(reserve_type)
                self.assertDictEqual(
                    self.read_tmp_requirement(reserve_type, conn, 3),
                    self.expected({"BA_FLAT": 0, "BA_WEATHER": None}),
                )
                conn.close()

    def test_flagged_ba_without_weather_iterations_raises(self):
        for reserve_type in RESERVE_TYPES:
            with self.subTest(reserve_type=reserve_type):
                conn = make_db(reserve_type)
                with self.assertRaisesRegex(ValueError, r"\['BA_WEATHER'\]"):
                    self.read_tmp_requirement(reserve_type, conn, 0)
                conn.close()

    def test_unflagged_bas_read_weather_iteration_zero(self):
        """Without the flag row, both BAs read their weather iteration 0 rows
        in any weather iteration (BA_WEATHER has none)."""
        for reserve_type in RESERVE_TYPES:
            with self.subTest(reserve_type=reserve_type):
                conn = make_db(reserve_type)
                conn.execute(f"DELETE FROM inputs_system_{reserve_type}_iterations;")
                for weather in [0, 1]:
                    self.assertDictEqual(
                        self.read_tmp_requirement(reserve_type, conn, weather),
                        self.expected({"BA_FLAT": 0, "BA_WEATHER": 0}),
                    )
                conn.close()

    def test_unread_rows(self):
        for reserve_type in RESERVE_TYPES:
            with self.subTest(reserve_type=reserve_type):
                conn = make_db(reserve_type)
                self.assertListEqual(
                    get_unread_requirement_rows(**req_kwargs(conn, reserve_type)),
                    [("BA_FLAT", 3)],
                )
                # Negative weather iterations are reported too
                conn.execute(f"""INSERT INTO inputs_system_{reserve_type}
                    ({reserve_type}_scenario_id, {reserve_type}_ba,
                    weather_iteration, stage_id, timepoint,
                    {requirement_column(reserve_type)})
                    VALUES (1, 'BA_FLAT', -1, 1, 1, 5);""")
                self.assertListEqual(
                    get_unread_requirement_rows(**req_kwargs(conn, reserve_type)),
                    [("BA_FLAT", -1), ("BA_FLAT", 3)],
                )
                conn.close()

    def test_requirement_search_uses_weather_iteration(self):
        """The requirement table is searched by its primary key including
        the weather iteration (which depends on the BA's flag) rather than
        reading every BA and weather iteration of the subscenario, and the
        never-read-rows check searches only the non-zero weather
        iterations."""
        for reserve_type in RESERVE_TYPES:
            with self.subTest(reserve_type=reserve_type):
                conn = make_db(reserve_type)
                lookups = requirement_table_lookups(
                    conn,
                    reserve_type,
                    get_tmp_requirement_sql(
                        subscenarios=make_subscenarios(reserve_type),
                        weather_iteration=2,
                        subproblem=1,
                        stage=1,
                        reserve_type=reserve_type,
                        value_columns=requirement_column(reserve_type),
                        reserve_type_ba_subscenario_id=1,
                        reserve_type_req_subscenario_id=1,
                    ),
                )
                self.assertEqual(len(lookups), 1, lookups)
                self.assertIn(
                    f"{reserve_type}_ba=? AND weather_iteration=?", lookups[0]
                )

                statements = []
                conn.set_trace_callback(statements.append)
                get_unread_requirement_rows(**req_kwargs(conn, reserve_type))
                conn.set_trace_callback(None)
                lookups = requirement_table_lookups(conn, reserve_type, statements[0])
                self.assertTrue(lookups)
                for lookup in lookups:
                    self.assertRegex(lookup, r"weather_iteration[<>]\?")
                conn.close()

    def test_missing_weather_slice(self):
        for reserve_type in RESERVE_TYPES:
            conn = make_db(reserve_type)
            for weather, expected in [(1, []), (2, []), (3, ["BA_WEATHER"])]:
                with self.subTest(reserve_type=reserve_type, weather=weather):
                    self.assertListEqual(
                        get_bas_missing_weather_slice(
                            subscenarios=make_subscenarios(reserve_type),
                            weather_iteration=weather,
                            subproblem=1,
                            stage=1,
                            **req_kwargs(conn, reserve_type),
                        ),
                        expected,
                    )
            conn.close()

    def validation_errors(self, reserve_type, conn, weather_iteration):
        """
        :return: sorted list of (gridpath_module, db_table, severity,
            description) the module's validate_inputs writes
        """
        module_name = f"gridpath.system.reserves.requirement.{reserve_type}"
        importlib.import_module(module_name).validate_inputs(
            scenario_id=1,
            subscenarios=make_subscenarios(reserve_type),
            weather_iteration=weather_iteration,
            hydro_iteration=0,
            availability_iteration=0,
            subproblem=1,
            stage=1,
            conn=conn,
        )
        return sorted(
            conn.execute("""SELECT gridpath_module, db_table, severity, description
                FROM status_validation;""").fetchall()
        )

    def test_validation(self):
        for reserve_type in RESERVE_TYPES:
            module_name = f"gridpath.system.reserves.requirement.{reserve_type}"
            table = f"inputs_system_{reserve_type}"
            unread = (
                module_name,
                table,
                "High",
                f"BA BA_FLAT has rows at weather_iteration 3 but is not "
                f"flagged to vary by weather iteration in {table}_iterations, "
                f"so they are never read.",
            )
            for weather, expected in [
                (1, [unread]),
                (
                    3,
                    [
                        (
                            module_name,
                            table,
                            "High",
                            f"BA BA_WEATHER is flagged to vary by weather "
                            f"iteration but has no {table} rows at "
                            f"weather_iteration 3, so its requirement would be "
                            f"0 in every timepoint.",
                        ),
                        unread,
                    ],
                ),
                (
                    0,
                    [
                        (
                            module_name,
                            table,
                            "High",
                            f"BAs ['BA_WEATHER'] are flagged in "
                            f"{table}_iterations to vary by weather iteration "
                            f"but the scenario has no weather iterations.",
                        ),
                        unread,
                    ],
                ),
            ]:
                with self.subTest(reserve_type=reserve_type, weather=weather):
                    conn = make_db(reserve_type)
                    self.assertListEqual(
                        self.validation_errors(reserve_type, conn, weather),
                        sorted(expected),
                    )
                    conn.close()


if __name__ == "__main__":
    unittest.main()
