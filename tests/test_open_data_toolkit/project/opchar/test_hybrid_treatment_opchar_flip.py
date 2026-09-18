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
The opchar step's hybrid-treatment operational-type flip: under
``hybrid_treatment power_output_group``, paired variable components flip
from gen_var_must_take to the curtailable gen_var (a must-take component
that can exceed the shared interconnection limit would make the power
output group's max constraint infeasible); standalone variable units,
batteries, and the default 'independent' treatment are untouched.
"""

import os
import pandas as pd
import sqlite3
import tempfile
import unittest

from db.create_database import main as create_database_main
from open_data_toolkit.project.opchar import eia860_to_project_opchar_input_csvs

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "..",
    "open_data_toolkit",
    "raw_data_db_schema.sql",
)


class TestHybridTreatmentOpcharFlip(unittest.TestCase):
    """
    Fixture fleet (all operating, one BA): plant 1 — co-located solar +
    battery (the solar flips); plant 2 — standalone solar (stays
    must-take).
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.db_path = os.path.join(self.tmp_dir.name, "opchar_flip_test_raw.db")
        create_database_main(
            ["--database", self.db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        conn = sqlite3.connect(self.db_path)

        conn.execute(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES ('BA1', 'Region1', 'Interconnect1')"
        )
        conn.executemany(
            """
            INSERT INTO user_defined_eia_gridpath_key
            (prime_mover_code, energy_source_code, gridpath_capacity_type,
            gridpath_operational_type, gridpath_balancing_type,
            gridpath_technology)
            VALUES (?, ?, 'cap', ?, 'year', ?)
            """,
            [
                ("PV", "SUN", "gen_var_must_take", "Solar"),
                ("BA", "MWH", "stor", "Batteries"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            balancing_authority_code_eia, prime_mover_code,
            energy_source_code_1, operational_status_code,
            sector_name_eia, planned_generator_retirement_date, capacity_mw)
            VALUES ('v-test', '2026-01-01', ?, ?, 'BA1', ?, ?, 'OP',
            'Electric Utility', '2099-01-01', 100)
            """,
            [
                (1, "S1", "PV", "SUN"),
                (1, "B1", "BA", "MWH"),
                (2, "S1", "PV", "SUN"),
            ],
        )
        conn.commit()
        conn.close()

    def get_opchar_optypes(self, hybrid_treatment):
        output_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        eia860_to_project_opchar_input_csvs.main(
            [
                "--database",
                self.db_path,
                "--output_directory",
                output_directory,
                "--study_year",
                "2030",
                "--footprint",
                "Interconnect1",
                "--hybrid_treatment",
                hybrid_treatment,
                "--quiet",
            ]
        )
        (csv_file,) = os.listdir(output_directory)
        df = pd.read_csv(os.path.join(output_directory, csv_file))

        return dict(zip(df["project"], df["operational_type"]))

    def test_paired_variable_component_flips_under_group_treatment(self):
        optypes = self.get_opchar_optypes(hybrid_treatment="power_output_group")
        self.assertEqual(optypes["1__S1"], "gen_var")
        self.assertEqual(optypes["2__S1"], "gen_var_must_take")
        self.assertEqual(optypes["1__B1"], "stor")

    def test_no_flip_under_independent_treatment(self):
        optypes = self.get_opchar_optypes(hybrid_treatment="independent")
        self.assertEqual(optypes["1__S1"], "gen_var_must_take")
        self.assertEqual(optypes["2__S1"], "gen_var_must_take")
        self.assertEqual(optypes["1__B1"], "stor")


if __name__ == "__main__":
    unittest.main()
