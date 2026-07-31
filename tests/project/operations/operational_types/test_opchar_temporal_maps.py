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
Test the opchar timepoint/horizon maps: projects pointing their
timepoint-/horizon-indexed operating characteristics inputs at data stored
under other timepoints/horizons via the *_tmp_map_scenario_id /
*_hrz_map_scenario_id columns of inputs_project_operational_chars.
"""

import os.path
import sqlite3
import unittest

from gridpath.project.operations import validate_opchar_temporal_map_references
from gridpath.project.operations.operational_types.common_functions import (
    get_prj_temporal_index_opr_inputs_from_db,
    BT_HRZ_INDEX_QUERY_PARAMS,
)

DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "db", "db_schema.sql"
)


class SubScenariosStub:
    PROJECT_PORTFOLIO_SCENARIO_ID = 1
    PROJECT_OPERATIONAL_CHARS_SCENARIO_ID = 1
    TEMPORAL_SCENARIO_ID = 1


def get_var_profile_inputs(conn, weather_iteration=0, hydro_iteration=0):
    results = get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=SubScenariosStub(),
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=0,
        subproblem=1,
        stage=1,
        conn=conn,
        op_type="gen_var",
        table="inputs_project_variable_generator_profiles",
        subscenario_id_column="variable_generator_profile_scenario_id",
        data_column="cap_factor",
    )

    return sorted(results.fetchall())


def get_hydro_opchar_inputs(conn):
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
        data_column="average_power_fraction, min_power_fraction, " "max_power_fraction",
        opr_index_dict=BT_HRZ_INDEX_QUERY_PARAMS,
    )

    return sorted(results.fetchall())


class TestOpcharTemporalMaps(unittest.TestCase):
    """
    Build an in-memory database from the real schema, load a small
    two-period fixture, and check the inputs returned with and without
    timepoint/horizon maps assigned.

    Fixture temporal structure: periods 2020 and 2030 with two timepoints
    each (2020010101/2020010102 and 2030010101/2030010102), one 'day'
    balancing-type horizon per period (202001 and 203001), subproblem 1,
    stage 1.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())
        c = self.conn.cursor()

        for tmp, period, hrz in [
            (2020010101, 2020, 202001),
            (2020010102, 2020, 202001),
            (2030010101, 2030, 203001),
            (2030010102, 2030, 203001),
        ]:
            c.execute(
                """INSERT INTO inputs_temporal
                (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                period, number_of_hours_in_timepoint, timepoint_weight,
                spinup_or_lookahead)
                VALUES (1, 1, 1, ?, ?, 1, 4380, 0)""",
                (tmp, period),
            )
            c.execute(
                """INSERT INTO inputs_temporal_horizon_timepoints
                (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                balancing_type_horizon, horizon)
                VALUES (1, 1, 1, ?, 'day', ?)""",
                (tmp, hrz),
            )

        c.execute("""INSERT INTO inputs_project_portfolios
            (project_portfolio_scenario_id, project, capacity_type)
            VALUES (1, 'Wind', 'gen_spec'), (1, 'Solar', 'gen_spec'),
            (1, 'Solar_Rep_Day', 'gen_spec'), (1, 'Hydro', 'gen_spec')""")

        # Wind uses timepoint map 1 (2030 --> 2020); Solar_Rep_Day uses
        # timepoint map 2 (everything --> the first 2020 timepoint); Solar
        # has no map; Hydro uses horizon map 1 (203001 --> 202001)
        c.execute("""INSERT INTO inputs_project_operational_chars
            (project_operational_chars_scenario_id, project,
            operational_type, variable_generator_profile_scenario_id,
            variable_generator_profile_tmp_map_scenario_id,
            hydro_operational_chars_scenario_id,
            hydro_operational_chars_hrz_map_scenario_id)
            VALUES
            (1, 'Wind', 'gen_var', 1, 1, NULL, NULL),
            (1, 'Solar', 'gen_var', 1, NULL, NULL, NULL),
            (1, 'Solar_Rep_Day', 'gen_var', 1, 2, NULL, NULL),
            (1, 'Hydro', 'gen_hydro', NULL, NULL, 1, 1)""")

        c.execute("""INSERT INTO inputs_project_opchar_timepoint_map
            (opchar_timepoint_map_scenario_id, timepoint, data_timepoint)
            VALUES
            (1, 2030010101, 2020010101), (1, 2030010102, 2020010102),
            (2, 2020010102, 2020010101), (2, 2030010101, 2020010101),
            (2, 2030010102, 2020010101)""")
        c.execute("""INSERT INTO inputs_project_opchar_horizon_map
            (opchar_horizon_map_scenario_id, balancing_type_horizon,
            horizon, data_horizon)
            VALUES (1, 'day', 203001, 202001)""")

        # Wind profiles: 2020 timepoints only; Solar profiles: all
        # timepoints; Solar_Rep_Day profiles: first 2020 timepoint only
        for prj, tmp, cf in [
            ("Wind", 2020010101, 0.5),
            ("Wind", 2020010102, 0.6),
            ("Solar", 2020010101, 0.1),
            ("Solar", 2020010102, 0.2),
            ("Solar", 2030010101, 0.3),
            ("Solar", 2030010102, 0.4),
            ("Solar_Rep_Day", 2020010101, 0.7),
        ]:
            c.execute(
                """INSERT INTO inputs_project_variable_generator_profiles
                (project, variable_generator_profile_scenario_id,
                weather_iteration, hydro_iteration, stage_id, timepoint,
                cap_factor)
                VALUES (?, 1, 0, 0, 1, ?, ?)""",
                (prj, tmp, cf),
            )
        c.execute("""INSERT INTO inputs_project_variable_generator_profiles_iterations
            (project, variable_generator_profile_scenario_id,
            varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES ('Wind', 1, 0, 0), ('Solar', 1, 0, 0),
            ('Solar_Rep_Day', 1, 0, 0)""")

        # Hydro opchars: 2020 horizon only
        c.execute("""INSERT INTO inputs_project_hydro_operational_chars
            (project, hydro_operational_chars_scenario_id,
            weather_iteration, hydro_iteration, stage_id,
            balancing_type_project, horizon, average_power_fraction,
            min_power_fraction, max_power_fraction)
            VALUES ('Hydro', 1, 0, 0, 1, 'day', 202001, 0.5, 0.2, 0.9)""")
        c.execute("""INSERT INTO inputs_project_hydro_operational_chars_iterations
            (project, hydro_operational_chars_scenario_id,
            varies_by_weather_iteration, varies_by_hydro_iteration)
            VALUES ('Hydro', 1, 0, 0)""")

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_no_map_returns_data_as_is(self):
        """
        A project without a map reads its data at the model timepoints,
        exactly as before the maps were introduced.
        """
        self.conn.execute("""UPDATE inputs_project_operational_chars
            SET variable_generator_profile_tmp_map_scenario_id = NULL""")
        # Give the mapped projects full profiles so all model timepoints
        # are covered without maps
        for prj, tmp, cf in [
            ("Wind", 2030010101, 0.5),
            ("Wind", 2030010102, 0.5),
            ("Solar_Rep_Day", 2020010102, 0.7),
            ("Solar_Rep_Day", 2030010101, 0.7),
            ("Solar_Rep_Day", 2030010102, 0.7),
        ]:
            self.conn.execute(
                """INSERT INTO inputs_project_variable_generator_profiles
                VALUES (?, 1, 0, 0, 1, ?, ?)""",
                (prj, tmp, cf),
            )
        results = get_var_profile_inputs(self.conn)
        self.assertEqual(
            results,
            sorted(
                [
                    ("Wind", 2020010101, 0.5),
                    ("Wind", 2020010102, 0.6),
                    ("Wind", 2030010101, 0.5),
                    ("Wind", 2030010102, 0.5),
                    ("Solar", 2020010101, 0.1),
                    ("Solar", 2020010102, 0.2),
                    ("Solar", 2030010101, 0.3),
                    ("Solar", 2030010102, 0.4),
                    ("Solar_Rep_Day", 2020010101, 0.7),
                    ("Solar_Rep_Day", 2020010102, 0.7),
                    ("Solar_Rep_Day", 2030010101, 0.7),
                    ("Solar_Rep_Day", 2030010102, 0.7),
                ]
            ),
        )

    def test_tmp_maps_expand_data(self):
        """
        Wind's 2020-only profile is repeated in 2030 via map 1;
        Solar_Rep_Day's single-timepoint profile is repeated everywhere via
        map 2 (many-to-one); Solar's fully specified profile is returned
        as-is -- all three in the same query.
        """
        results = get_var_profile_inputs(self.conn)
        self.assertEqual(
            results,
            sorted(
                [
                    ("Wind", 2020010101, 0.5),
                    ("Wind", 2020010102, 0.6),
                    ("Wind", 2030010101, 0.5),
                    ("Wind", 2030010102, 0.6),
                    ("Solar", 2020010101, 0.1),
                    ("Solar", 2020010102, 0.2),
                    ("Solar", 2030010101, 0.3),
                    ("Solar", 2030010102, 0.4),
                    ("Solar_Rep_Day", 2020010101, 0.7),
                    ("Solar_Rep_Day", 2020010102, 0.7),
                    ("Solar_Rep_Day", 2030010101, 0.7),
                    ("Solar_Rep_Day", 2030010102, 0.7),
                ]
            ),
        )

    def test_mapped_timepoints_ignore_own_data(self):
        """
        For a mapped model timepoint, the data at the map's data_timepoint
        governs even if the project also has data stored at the model
        timepoint itself.
        """
        self.conn.execute("""INSERT INTO inputs_project_variable_generator_profiles
            VALUES ('Wind', 1, 0, 0, 1, 2030010101, 0.99)""")
        results = get_var_profile_inputs(self.conn)
        wind_2030 = [r for r in results if r[:2] == ("Wind", 2030010101)]
        self.assertEqual(wind_2030, [("Wind", 2030010101, 0.5)])

    def test_unmapped_timepoints_of_mapped_project_use_own_data(self):
        """
        Timepoints not listed in a project's map read the project's data at
        the timepoint itself (map 1 lists only the 2030 timepoints; the
        2020 timepoints resolve to themselves).
        """
        results = get_var_profile_inputs(self.conn)
        wind_2020 = [r for r in results if r[0] == "Wind" and r[1] < 2030000000]
        self.assertEqual(
            wind_2020, [("Wind", 2020010101, 0.5), ("Wind", 2020010102, 0.6)]
        )

    def test_hrz_map_expands_data(self):
        """
        Hydro's 2020-horizon opchars are repeated for the 2030 horizon via
        horizon map 1.
        """
        results = get_hydro_opchar_inputs(self.conn)
        self.assertEqual(
            results,
            sorted(
                [
                    ("Hydro", "day", 202001, 0.5, 0.2, 0.9),
                    ("Hydro", "day", 203001, 0.5, 0.2, 0.9),
                ]
            ),
        )

    def test_map_with_weather_iterations(self):
        """
        The map composes with the iterations mechanism: a project whose
        profiles vary by weather iteration gets the requested iteration's
        data at the mapped timepoints.
        """
        c = self.conn.cursor()
        c.execute("""UPDATE inputs_project_variable_generator_profiles_iterations
            SET varies_by_weather_iteration = 1 WHERE project = 'Wind'""")
        c.execute("""DELETE FROM inputs_project_variable_generator_profiles
            WHERE project = 'Wind'""")
        for weather_iteration, cf1, cf2 in [(1, 0.51, 0.61), (2, 0.52, 0.62)]:
            c.execute(
                """INSERT INTO inputs_project_variable_generator_profiles
                VALUES ('Wind', 1, ?, 0, 1, 2020010101, ?),
                       ('Wind', 1, ?, 0, 1, 2020010102, ?)""",
                (weather_iteration, cf1, weather_iteration, cf2),
            )
        self.conn.commit()

        results = get_var_profile_inputs(self.conn, weather_iteration=2)
        wind = [r for r in results if r[0] == "Wind"]
        self.assertEqual(
            wind,
            [
                ("Wind", 2020010101, 0.52),
                ("Wind", 2020010102, 0.62),
                ("Wind", 2030010101, 0.52),
                ("Wind", 2030010102, 0.62),
            ],
        )

    def test_validate_dangling_map_reference(self):
        """
        A map reference with no rows in the map inputs table produces a
        validation error; valid references produce none.
        """
        c = self.conn.cursor()
        # Point Wind at a nonexistent map
        c.execute("""UPDATE inputs_project_operational_chars
            SET variable_generator_profile_tmp_map_scenario_id = 99
            WHERE project = 'Wind'""")
        self.conn.commit()

        validate_opchar_temporal_map_references(
            scenario_id=1,
            subscenarios=SubScenariosStub(),
            weather_iteration=0,
            hydro_iteration=0,
            availability_iteration=0,
            subproblem=1,
            stage=1,
            conn=self.conn,
        )

        validation_results = c.execute(
            "SELECT description FROM status_validation"
        ).fetchall()
        self.assertEqual(len(validation_results), 1)
        self.assertIn("Wind", validation_results[0][0])
        self.assertIn(
            "variable_generator_profile_tmp_map_scenario_id", validation_results[0][0]
        )


if __name__ == "__main__":
    unittest.main()
