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

import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from argparse import Namespace

from db.create_database import main as create_database_main
from open_data_toolkit.project.fleet.aggregation import get_project_name_str
from open_data_toolkit.project.fleet.fleet_filters import get_fleet_relation_sql
from open_data_toolkit.project.fleet.step_common import (
    EIA860M_GENERATORS_TABLE,
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    warn_on_fleet_data_gaps,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "..",
    "open_data_toolkit",
    "raw_data_db_schema.sql",
)

# The settings a zone-aware project step's parser produces
ZONE_AWARE_SETTINGS = dict(
    ba_source="eia930a",
    study_year=2026,
    footprint="Region1",
    load_zone_level="region",
    include_retired=False,
    planned_inclusion="under_construction",
    inactive_inclusion="none",
    exclude_commercial_industrial_sectors=True,
    project_aggregation="agg_project_keyed",
    aggregation_dimensions="technology_description",
    quiet=True,
)

# The zone-agnostic steps (fuels, heat rates) define no --load_zone_level
ZONE_AGNOSTIC_SETTINGS = {
    setting: value
    for setting, value in ZONE_AWARE_SETTINGS.items()
    if setting
    not in ("load_zone_level", "project_aggregation", "aggregation_dimensions")
}


class TestStepCommonWrappers(unittest.TestCase):
    """
    The parsed-arguments wrappers must produce exactly what the steps used
    to build inline, including for the zone-agnostic steps whose parsers
    define no load-zone level.
    """

    def test_fleet_relation_matches_direct_call(self):
        parsed_args = Namespace(**ZONE_AWARE_SETTINGS)

        self.assertEqual(
            get_fleet_relation_sql_from_args(parsed_args),
            get_fleet_relation_sql(
                ba_source="eia930a",
                study_year=2026,
                footprint="Region1",
                load_zone_level="region",
                include_retired=False,
                planned_inclusion="under_construction",
                inactive_inclusion="none",
                exclude_commercial_industrial_sectors=True,
            ),
        )

    def test_fleet_relation_without_load_zone_level(self):
        """
        A step that takes no --load_zone_level gets get_fleet_relation_sql's
        default level rather than an AttributeError.
        """
        parsed_args = Namespace(**ZONE_AGNOSTIC_SETTINGS)

        self.assertEqual(
            get_fleet_relation_sql_from_args(parsed_args, join_ba_map=False),
            get_fleet_relation_sql(
                ba_source="eia930a",
                study_year=2026,
                footprint="Region1",
                include_retired=False,
                planned_inclusion="under_construction",
                inactive_inclusion="none",
                exclude_commercial_industrial_sectors=True,
                join_ba_map=False,
            ),
        )

    def test_overrides_win_over_parsed_arguments(self):
        parsed_args = Namespace(**ZONE_AWARE_SETTINGS)

        self.assertEqual(
            get_fleet_relation_sql_from_args(
                parsed_args,
                generators_table=EIA860M_GENERATORS_TABLE,
                extra_where="1 = 0",
            ),
            get_fleet_relation_sql(
                ba_source="eia930a",
                study_year=2026,
                footprint="Region1",
                load_zone_level="region",
                include_retired=False,
                planned_inclusion="under_construction",
                inactive_inclusion="none",
                exclude_commercial_industrial_sectors=True,
                generators_table=EIA860M_GENERATORS_TABLE,
                extra_where="1 = 0",
            ),
        )

    def test_project_name_str_matches_direct_call(self):
        parsed_args = Namespace(**ZONE_AWARE_SETTINGS)

        self.assertEqual(
            get_project_name_str_from_args(parsed_args),
            get_project_name_str(
                project_aggregation="agg_project_keyed",
                load_zone_level="region",
                footprint="Region1",
                aggregation_dimensions="technology_description",
            ),
        )

    def test_bad_settings_raise_before_any_database_work(self):
        """
        The wrappers validate, which is why the steps call them before
        connecting.
        """
        with self.assertRaises(ValueError):
            get_project_name_str_from_args(
                Namespace(**{**ZONE_AWARE_SETTINGS, "aggregation_dimensions": "nope"})
            )
        with self.assertRaises(ValueError):
            get_fleet_relation_sql_from_args(
                Namespace(**{**ZONE_AWARE_SETTINGS, "inactive_inclusion": "nope"})
            )


class TestStepCommonDatabaseChecks(unittest.TestCase):
    """
    The scope checks and data-gap warnings, against a raw database built
    from the real schema.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "step_common_test_raw.db")

        create_database_main(
            [
                "--database",
                cls.db_path,
                "--db_schema",
                RAW_DATA_DB_SCHEMA,
                "--quiet",
            ]
        )

        conn = sqlite3.connect(cls.db_path)
        conn.execute(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES ('Zone1', 'Region1', 'Interconnect1')"
        )
        # One EIA860M unit with no sector, to trigger the NULL-sector warning
        conn.execute("""
            INSERT INTO raw_data_eia860m_generators
            (version_num, report_date, plant_id_eia, generator_id,
            operational_status_code, balancing_authority_code_eia,
            capacity_mw, prime_mover_code, energy_source_code_1)
            VALUES ('v-test', '2026-01-01', 1, '1', 'OP', 'Zone1', 100, 'CT',
            'NG')
            """)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def test_custom_level_check_runs_for_a_zone_aware_step(self):
        parsed_args = Namespace(
            **{**ZONE_AWARE_SETTINGS, "load_zone_level": "custom"},
            database=self.db_path,
        )

        # No BA has a custom zone, so the level is not usable
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(io.StringIO()):
                connect_and_check_scope(parsed_args)

    def test_custom_level_check_skipped_for_a_zone_agnostic_step(self):
        """
        The fuel and heat-rate steps take no load-zone level, so there is
        no level to check — connecting must still work.
        """
        parsed_args = Namespace(**ZONE_AGNOSTIC_SETTINGS, database=self.db_path)

        with contextlib.redirect_stdout(io.StringIO()):
            conn = connect_and_check_scope(parsed_args)
        conn.close()

    def test_null_sector_warning_uses_the_table_s_sector_column(self):
        """
        EIA860M carries sector_id_eia, not the annual table's
        sector_name_eia; the warning must test the right column.
        """
        parsed_args = Namespace(**ZONE_AWARE_SETTINGS, database=self.db_path)

        with contextlib.redirect_stdout(io.StringIO()) as output:
            conn = connect_and_check_scope(parsed_args)
            warn_on_fleet_data_gaps(
                conn=conn,
                parsed_args=parsed_args,
                generators_table=EIA860M_GENERATORS_TABLE,
            )
        conn.close()

        printed = output.getvalue()
        self.assertIn("WARNING", printed)
        self.assertIn("sector", printed)


if __name__ == "__main__":
    unittest.main()
