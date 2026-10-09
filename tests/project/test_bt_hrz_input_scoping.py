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
The get_inputs queries of project inputs indexed by stage or by balancing
type - horizon select only the rows of the subproblem, stage, and
operational type being written: rows from other stages would duplicate
indices (the model silently keeps the last one), and rows for other
subproblems' horizons or other operational types fail at model load.
"""

import os.path
import sqlite3
import unittest

from gridpath.project.availability.availability_types import exogenous
from gridpath.project import operations
from gridpath.project.operations.operational_types import gen_hydro_water

DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "db", "db_schema.sql"
)


class SubScenarios:
    """Scenario subscenario IDs; unset IDs are "NULL" as in the database"""

    TEMPORAL_SCENARIO_ID = 1
    PROJECT_PORTFOLIO_SCENARIO_ID = 1
    PROJECT_OPERATIONAL_CHARS_SCENARIO_ID = 1
    PROJECT_AVAILABILITY_SCENARIO_ID = 1

    def __getattr__(self, name):
        return "NULL"


class TestBtHrzInputScoping(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        with open(DB_SCHEMA_FILE) as f:
            self.conn.executescript(f.read())

        # Two subproblems with their own day horizon (timepoints 1-2 and
        # 3-4); each subproblem has two stages with the same timepoints
        for subproblem, tmps in [(1, [1, 2]), (2, [3, 4])]:
            for stage in [1, 2]:
                for tmp in tmps:
                    self.conn.execute(
                        """INSERT INTO inputs_temporal (temporal_scenario_id,
                        subproblem_id, stage_id, timepoint, period,
                        number_of_hours_in_timepoint, timepoint_weight,
                        spinup_or_lookahead) VALUES (1, ?, ?, ?, 2030, 1, 1, 0)""",
                        (subproblem, stage, tmp),
                    )
                    self.conn.execute(
                        """INSERT INTO inputs_temporal_horizon_timepoints
                        VALUES (1, ?, ?, ?, 'day', ?)""",
                        (subproblem, stage, tmp, subproblem),
                    )
            self.conn.execute(
                """INSERT INTO inputs_temporal_horizons (temporal_scenario_id,
                balancing_type_horizon, horizon, boundary)
                VALUES (1, 'day', ?, 'circular')""",
                (subproblem,),
            )

        self.conn.executescript("""
            INSERT INTO inputs_project_portfolios
            (project_portfolio_scenario_id, project, capacity_type)
            VALUES (1, 'Water', 'gen_spec'), (1, 'Hydro', 'gen_spec');

            INSERT INTO inputs_project_operational_chars
            (project_operational_chars_scenario_id, project, operational_type,
             cap_factor_limits_scenario_id, total_ramp_up_limit_scenario_id)
            VALUES (1, 'Water', 'gen_hydro_water', 1, 1),
                   (1, 'Hydro', 'gen_hydro', NULL, 1);

            INSERT INTO inputs_project_cap_factor_limits
            VALUES ('Water', 1, 'day', 1, NULL, 0.5),
                   ('Water', 1, 'day', 2, NULL, 0.6);

            INSERT INTO inputs_project_total_ramp_up_limits
            VALUES ('Water', 1, 'day', 1, 10), ('Hydro', 1, 'day', 1, 20);

            INSERT INTO inputs_project_availability
            (project_availability_scenario_id, project, availability_type,
             exogenous_availability_independent_scenario_id,
             exogenous_availability_independent_bt_hrz_scenario_id)
            VALUES (1, 'Water', 'exogenous', 1, 1);
            """)
        # Stage-specific derates
        for stage, derate in [(1, 0.7), (2, 0.9)]:
            for tmp in [1, 2, 3, 4]:
                self.conn.execute(
                    """INSERT INTO inputs_project_availability_exogenous_independent
                    (project, exogenous_availability_independent_scenario_id,
                     availability_iteration, stage_id, timepoint,
                     availability_derate_independent)
                    VALUES ('Water', 1, 0, ?, ?, ?)""",
                    (stage, tmp, derate),
                )
            for hrz in [1, 2]:
                self.conn.execute(
                    """INSERT INTO
                    inputs_project_availability_exogenous_independent_bt_hrz
                    VALUES ('Water', 1, 0, ?, 'day', ?, ?)""",
                    (stage, hrz, derate),
                )

    def get_inputs(self, module, subproblem, stage):
        return module.get_inputs_from_database(
            scenario_id=1,
            subscenarios=SubScenarios(),
            weather_iteration=0,
            hydro_iteration=0,
            availability_iteration=0,
            subproblem=subproblem,
            stage=stage,
            conn=self.conn,
        )

    def test_exogenous_derates_are_the_stages_own(self):
        ind, _, bt_hrz_ind, _, _ = self.get_inputs(exogenous, subproblem=1, stage=2)
        self.assertEqual(
            sorted(ind.fetchall()), [("Water", 1, 0.9, None), ("Water", 2, 0.9, None)]
        )
        self.assertEqual(bt_hrz_ind.fetchall(), [("Water", "day", 1, 0.9)])

    def test_cap_factor_limits_are_the_subproblems_own(self):
        cap_factor_limits = self.get_inputs(operations, subproblem=2, stage=1)[8]
        self.assertEqual(cap_factor_limits.fetchall(), [("Water", "day", 2, None, 0.6)])

    def test_gen_hydro_water_ramp_limits_are_gen_hydro_water_only(self):
        # Operational type modules take directory names: "" = subproblem 1,
        # stage 1
        total_ramp_up_limits = gen_hydro_water.get_model_inputs_from_database(
            scenario_id=1,
            subscenarios=SubScenarios(),
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
            conn=self.conn,
        )[2]
        self.assertEqual(total_ramp_up_limits.fetchall(), [("Water", "day", 1, 10)])


if __name__ == "__main__":
    unittest.main()
