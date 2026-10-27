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
Percent requirement maps by load zone and load component, for all seven
reserve types, against an in-memory database built from the real schema:
map rows with an empty load_component go to the whole-load-zone map file and
the others to the load component map file, and validation reports load
components that are not among the scenario's load components and load
zones mapped both whole and by load component.
"""

import csv
import importlib
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

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

# The scenario's load components by load zone
LOAD_COMPONENTS = [("Z1", "c1"), ("Z1", "c2"), ("Z2", "c1")]

# (BA, load_zone, load_component): BA_WHOLE maps whole load zones, BA_CMPNT
# load components, BA_DOUBLE both the whole of Z1 and its load component c1,
# BA_TYPO a load component Z2 does not have
MAP_ROWS = [
    ("BA_WHOLE", "Z1", None),
    ("BA_WHOLE", "Z2", None),
    ("BA_CMPNT", "Z1", "c1"),
    ("BA_CMPNT", "Z2", "c1"),
    ("BA_DOUBLE", "Z1", None),
    ("BA_DOUBLE", "Z1", "c1"),
    ("BA_TYPO", "Z2", "c2"),
]

BAS = sorted(set(ba for (ba, _, _) in MAP_ROWS))


def make_db(reserve_type):
    conn = sqlite3.connect(":memory:")
    with open(os.path.join(REPO_DIRECTORY, "db", "db_schema.sql")) as f:
        conn.executescript(f.read())

    conn.execute("""INSERT INTO inputs_system_load
        (load_scenario_id, load_components_scenario_id, load_levels_scenario_id)
        VALUES (1, 1, 1);""")
    conn.executemany(
        """INSERT INTO inputs_system_load_components
        (load_components_scenario_id, load_zone, load_component)
        VALUES (1, ?, ?);""",
        LOAD_COMPONENTS,
    )
    conn.execute(
        f"INSERT INTO subscenarios_system_{reserve_type} "
        f"({reserve_type}_scenario_id) VALUES (1);"
    )
    conn.executemany(
        f"""INSERT INTO inputs_geography_{reserve_type}_bas
        ({reserve_type}_ba_scenario_id, {reserve_type}_ba) VALUES (1, ?);""",
        [(ba,) for ba in BAS],
    )
    conn.executemany(
        f"""INSERT INTO inputs_system_{reserve_type}_percent
        ({reserve_type}_scenario_id, {reserve_type}_ba, stage_id,
        percent_load_req)
        VALUES (1, ?, 1, 0.1);""",
        [(ba,) for ba in BAS],
    )
    conn.executemany(
        f"""INSERT INTO inputs_system_{reserve_type}_percent_lz_map
        ({reserve_type}_scenario_id, {reserve_type}_ba, load_zone,
        load_component)
        VALUES (1, ?, ?, ?);""",
        MAP_ROWS,
    )

    return conn


def make_subscenarios(reserve_type):
    return SimpleNamespace(
        TEMPORAL_SCENARIO_ID=1,
        PROJECT_PORTFOLIO_SCENARIO_ID="NULL",
        LOAD_SCENARIO_ID=1,
        **{
            f"{reserve_type.upper()}_BA_SCENARIO_ID": 1,
            f"{reserve_type.upper()}_SCENARIO_ID": 1,
        },
    )


def iteration_kwargs():
    return dict(
        weather_iteration="",
        hydro_iteration="",
        availability_iteration="",
        subproblem="",
        stage="",
    )


def read_tab(filename):
    with open(filename) as f:
        return list(csv.reader(f, delimiter="\t"))


class TestReserveRequirementPercentLoadComponent(unittest.TestCase):
    def module(self, reserve_type):
        return importlib.import_module(
            f"gridpath.system.reserves.requirement.{reserve_type}"
        )

    def test_map_files(self):
        for reserve_type in RESERVE_TYPES:
            with self.subTest(reserve_type=reserve_type):
                conn = make_db(reserve_type)
                with tempfile.TemporaryDirectory() as scenario_directory:
                    inputs_dir = os.path.join(scenario_directory, "inputs")
                    os.makedirs(inputs_dir)
                    self.module(reserve_type).write_model_inputs(
                        scenario_directory=scenario_directory,
                        scenario_id=1,
                        subscenarios=make_subscenarios(reserve_type),
                        conn=conn,
                        **iteration_kwargs(),
                    )
                    whole = read_tab(
                        os.path.join(inputs_dir, f"{reserve_type}_percent_map.tab")
                    )
                    by_component = read_tab(
                        os.path.join(
                            inputs_dir,
                            f"{reserve_type}_percent_load_component_map.tab",
                        )
                    )
                conn.close()

                self.assertListEqual(whole[0], ["ba", "load_zone"])
                self.assertListEqual(
                    sorted(whole[1:]),
                    sorted([[ba, lz] for (ba, lz, cmp) in MAP_ROWS if cmp is None]),
                )
                self.assertListEqual(
                    by_component[0], ["ba", "load_zone", "load_component"]
                )
                self.assertListEqual(
                    sorted(by_component[1:]),
                    sorted(
                        [[ba, lz, cmp] for (ba, lz, cmp) in MAP_ROWS if cmp is not None]
                    ),
                )

    def test_no_load_component_map_file_without_load_component_rows(self):
        """Whole-load-zone maps write the map file they always did and no
        load component map file."""
        for reserve_type in RESERVE_TYPES:
            with self.subTest(reserve_type=reserve_type):
                conn = make_db(reserve_type)
                conn.execute(f"""DELETE FROM inputs_system_{reserve_type}_percent_lz_map
                    WHERE load_component IS NOT NULL;""")
                with tempfile.TemporaryDirectory() as scenario_directory:
                    inputs_dir = os.path.join(scenario_directory, "inputs")
                    os.makedirs(inputs_dir)
                    self.module(reserve_type).write_model_inputs(
                        scenario_directory=scenario_directory,
                        scenario_id=1,
                        subscenarios=make_subscenarios(reserve_type),
                        conn=conn,
                        **iteration_kwargs(),
                    )
                    self.assertTrue(
                        os.path.exists(
                            os.path.join(inputs_dir, f"{reserve_type}_percent_map.tab")
                        )
                    )
                    self.assertFalse(
                        os.path.exists(
                            os.path.join(
                                inputs_dir,
                                f"{reserve_type}_percent_load_component_map.tab",
                            )
                        )
                    )
                conn.close()

    def test_validation(self):
        for reserve_type in RESERVE_TYPES:
            with self.subTest(reserve_type=reserve_type):
                module_name = f"gridpath.system.reserves.requirement.{reserve_type}"
                table = f"inputs_system_{reserve_type}_percent_lz_map"
                conn = make_db(reserve_type)
                self.module(reserve_type).validate_inputs(
                    scenario_id=1,
                    subscenarios=make_subscenarios(reserve_type),
                    weather_iteration=0,
                    hydro_iteration=0,
                    availability_iteration=0,
                    subproblem=1,
                    stage=1,
                    conn=conn,
                )
                errors = sorted(
                    conn.execute("""SELECT gridpath_module, db_table, severity,
                        description FROM status_validation;""").fetchall()
                )
                conn.close()

                self.assertListEqual(
                    errors,
                    sorted(
                        [
                            (
                                module_name,
                                table,
                                "High",
                                "BA BA_TYPO's percent requirement includes load "
                                "component c2 of load zone Z2, which is not "
                                "among the scenario's load components for that "
                                "load zone.",
                            ),
                            (
                                module_name,
                                table,
                                "High",
                                "BA BA_DOUBLE's percent requirement includes "
                                "both the whole load of load zone Z1 (empty "
                                "load_component) and some of its load "
                                "components, so those load components are "
                                "counted twice.",
                            ),
                        ]
                    ),
                )


if __name__ == "__main__":
    unittest.main()
