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
Per-unit manual overrides (user_defined_unit_overrides): membership
force-include/force-exclude folded into the fleet relation, aggregation
carve-outs in project names, load-zone overrides, '*' wildcard
precedence, the one-zone-per-project invariant, and the
create-on-first-use behavior for raw databases that predate the table.
"""

import os
import pandas as pd
import sqlite3
import tempfile
import unittest

from db.create_database import main as create_database_main
from open_data_toolkit.project.fleet.aggregation import get_project_name_str
from open_data_toolkit.project.fleet.fleet_filters import get_fleet_relation_sql
from open_data_toolkit.project.fleet.unit_overrides import (
    check_one_zone_per_project,
    ensure_unit_overrides_table,
    get_project_load_zone_str,
    get_unit_override_sql,
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

FLEET_KWARGS = dict(
    ba_source="eia860",
    study_year=2030,
    footprint="Interconnect1",
    load_zone_level="baa",
)


class TestUnitOverrides(unittest.TestCase):
    """
    Fixture fleet: three operating units and one unit excluded by its
    planned retirement date, across two BAs of one interconnect.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "unit_overrides_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)

        self.conn.executemany(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES (?, ?, ?)",
            [
                ("BA1", "Region1", "Interconnect1"),
                ("BA2", "Region1", "Interconnect1"),
            ],
        )
        self.conn.execute("""
            INSERT INTO user_defined_eia_gridpath_key
            (prime_mover_code, energy_source_code, gridpath_capacity_type,
            gridpath_operational_type, gridpath_technology, agg_project)
            VALUES ('HY', 'WAT', 'gen_spec', 'gen_hydro', 'Hydro', 'Hydro')
            """)
        # (plant, gen, BA, status, planned retirement, capacity)
        self.conn.executemany(
            """
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            balancing_authority_code_eia, prime_mover_code,
            energy_source_code_1, operational_status_code,
            sector_name_eia, planned_generator_retirement_date, capacity_mw)
            VALUES ('v-test', '2026-01-01', ?, ?, ?, 'HY', 'WAT', ?,
            'Electric Utility', ?, 100)
            """,
            [
                (1, "1", "BA1", "OP", None),
                (1, "2", "BA1", "OP", None),
                (2, "1", "BA2", "OP", None),
                # excluded by default: planned retirement before study year
                (3, "1", "BA2", "OP", "2028-06-01"),
            ],
        )
        self.conn.commit()

    def add_overrides(self, rows):
        self.conn.executemany(
            "INSERT INTO user_defined_unit_overrides "
            "(plant_id_eia, generator_id, include, aggregation, load_zone, "
            "reason) VALUES (?, ?, ?, ?, ?, 'test')",
            rows,
        )
        self.conn.commit()

    def query_fleet(self, project_aggregation="none", **name_kwargs):
        name_str = get_project_name_str(
            project_aggregation=project_aggregation,
            load_zone_level="baa",
            footprint="Interconnect1",
            **name_kwargs,
        )
        zone_str = get_project_load_zone_str(
            load_zone_level="baa", footprint="Interconnect1"
        )
        group_by = (
            "GROUP BY project, load_zone" if project_aggregation != "none" else ""
        )
        sql = f"""
            SELECT {name_str} AS project, {zone_str} AS load_zone
            {get_fleet_relation_sql(**FLEET_KWARGS)}
            {group_by}
            ;
            """
        return pd.read_sql(sql, self.conn)

    def test_empty_table_is_a_noop(self):
        df = self.query_fleet()
        self.assertEqual(sorted(df["project"]), ["1__1", "1__2", "2__1"])
        self.assertEqual(sorted(df["load_zone"].unique()), ["BA1", "BA2"])

    def test_force_include_bypasses_characteristic_filters(self):
        self.add_overrides([(3, "1", 1, None, None)])
        df = self.query_fleet()
        self.assertIn("3__1", set(df["project"]))

    def test_force_exclude(self):
        self.add_overrides([(2, "1", 0, None, None)])
        df = self.query_fleet()
        self.assertEqual(sorted(df["project"]), ["1__1", "1__2"])

    def test_force_include_does_not_bypass_geography(self):
        # A unit whose BA is out of the footprint stays out even with
        # include=1 — the override bypasses the characteristics stage only
        self.conn.execute(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES ('BAX', 'RegionX', 'InterconnectX')"
        )
        self.conn.execute("""
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            balancing_authority_code_eia, prime_mover_code,
            energy_source_code_1, operational_status_code,
            sector_name_eia, capacity_mw)
            VALUES ('v-test', '2026-01-01', 9, '1', 'BAX', 'HY', 'WAT',
            'OP', 'Electric Utility', 100)
            """)
        self.add_overrides([(9, "1", 1, None, None)])
        df = self.query_fleet()
        self.assertNotIn("9__1", set(df["project"]))

    def test_star_wildcard_and_specific_precedence(self):
        # '*' excludes the whole plant; the generator-specific row wins
        # for unit 1__2
        self.add_overrides([(1, "*", 0, None, None), (1, "2", 1, None, None)])
        df = self.query_fleet()
        self.assertEqual(sorted(df["project"]), ["1__2", "2__1"])

    def test_override_columns_compose_across_rows(self):
        # A '*' aggregation carve-out and a specific include override on
        # the same plant apply independently (per-column resolution)
        self.add_overrides(
            [(3, "*", None, "Carveout", "ZoneC"), (3, "1", 1, None, None)]
        )
        df = self.query_fleet(project_aggregation="all")
        self.assertIn("Hydro_Carveout", set(df["project"]))
        self.assertEqual(
            df.loc[df["project"] == "Hydro_Carveout", "load_zone"].tolist(),
            ["ZoneC"],
        )

    def test_aggregation_carveout_and_zone_override(self):
        # Plant 1 carved out of the BA1 aggregate into its own project in
        # its own zone; plant 2 keeps the map-derived aggregate and zone
        self.add_overrides([(1, "*", None, "Hoover", "ZoneH")])
        df = self.query_fleet(project_aggregation="all")
        df = df.set_index("project")
        self.assertEqual(sorted(df.index), ["Hydro_BA2", "Hydro_Hoover"])
        self.assertEqual(df.loc["Hydro_Hoover", "load_zone"], "ZoneH")
        self.assertEqual(df.loc["Hydro_BA2", "load_zone"], "BA2")

    def test_aggregation_override_inert_in_disaggregated_mode(self):
        self.add_overrides([(1, "*", None, "Hoover", None)])
        df = self.query_fleet(project_aggregation="none")
        self.assertEqual(sorted(df["project"]), ["1__1", "1__2", "2__1"])

    def test_one_zone_per_project_check(self):
        # A zone override on only ONE unit of the plant-1 aggregate makes
        # Hydro_BA1 span two zones — the check must catch it (the query
        # groups by project AND zone precisely so this stays visible)
        self.add_overrides([(1, "1", None, None, "ZoneH")])
        df = self.query_fleet(project_aggregation="all")
        with self.assertRaisesRegex(ValueError, "more than one load zone"):
            check_one_zone_per_project(project_load_zones_df=df)
        # and the healthy fleet passes
        self.assertEqual(
            check_one_zone_per_project(project_load_zones_df=self.query_fleet()),
            [],
        )

    def test_unknown_override_column_raises(self):
        with self.assertRaisesRegex(ValueError, "Unknown unit-override column"):
            get_unit_override_sql(column="bogus")

    def test_table_created_on_first_use(self):
        # A raw database from before the table existed gets it (empty) on
        # ensure_unit_overrides_table, and the fleet relation then works
        self.conn.execute("DROP TABLE user_defined_unit_overrides")
        self.conn.commit()
        ensure_unit_overrides_table(conn=self.conn)
        df = self.query_fleet()
        self.assertEqual(len(df), 3)
        # idempotent, and existing rows survive a re-ensure
        self.add_overrides([(2, "1", 0, None, None)])
        ensure_unit_overrides_table(conn=self.conn)
        self.assertEqual(len(self.query_fleet()), 2)


if __name__ == "__main__":
    unittest.main()
