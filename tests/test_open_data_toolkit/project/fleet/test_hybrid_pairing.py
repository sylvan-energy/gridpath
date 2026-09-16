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
Hybrid-component pairing (the 'hybrid' aggregation dimension and the fleet
audit's hybrid columns): plant co-location and EIA860 energy-storage
supplement direct-support links as pairing bases, is_independent
exclusions, in-fleet-partner semantics, degradation to co-location on an
empty supplement table, the runtime-built dimension expression's plumbing
through the project names, and the coupling-flag labels.
"""

import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from argparse import Namespace

from db.create_database import main as create_database_main
from open_data_toolkit.project.fleet.aggregation import (
    get_aggregation_dimensions_sql,
    get_project_name_str,
)
from open_data_toolkit.project.fleet.fleet_filters import (
    ensure_energy_storage_table,
    get_fleet_relation_sql,
    get_hybrid_pairing_basis_expr,
    get_hybrid_pairing_expr,
    get_storage_coupling_expr,
    warn_on_missing_energy_storage_data,
)
from open_data_toolkit.project.fleet.step_common import (
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    requests_hybrid_dimension,
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

GENERATORS_TABLE = "raw_data_eia860_generators"


class TestHybridPairing(unittest.TestCase):
    """
    Fixture fleet, one BA:

    * plant 1 — operating solar + battery, co-located (pairs via
      co-location);
    * plant 2 — standalone operating solar (never pairs);
    * plant 3 — operating solar + battery the supplement flags
      is_independent (never pairs, despite co-location);
    * plant 4 — operating battery with a direct-support link to plant 5's
      solar (cross-plant: pairs via the link, invisible to co-location);
    * plant 5 — operating solar, no battery at the plant (pairs via plant
      4's link);
    * plant 6 — operating battery whose co-located solar is
      planned-not-under-construction ('T' — outside the default fleet
      tiers: the partner is not in fleet, so the battery does not pair);
    * plant 7 — operating wind + battery, co-located (the variable side
      also covers WT).
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "hybrid_pairing_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)

        self.conn.execute(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES ('BA1', 'Region1', 'Interconnect1')"
        )
        self.conn.executemany(
            """
            INSERT INTO user_defined_eia_gridpath_key
            (prime_mover_code, energy_source_code, gridpath_capacity_type,
            gridpath_operational_type, gridpath_technology, agg_project)
            VALUES (?, ?, 'cap', 'op', ?, ?)
            """,
            [
                ("PV", "SUN", "Solar", "Solar"),
                ("WT", "WND", "Wind", "Wind"),
                ("BA", "MWH", "Batteries", "Batteries"),
            ],
        )
        self.conn.executemany(
            """
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            balancing_authority_code_eia, prime_mover_code,
            energy_source_code_1, operational_status_code,
            sector_name_eia, planned_generator_retirement_date, capacity_mw)
            VALUES ('v-test', '2026-01-01', ?, ?, 'BA1', ?, ?, ?,
            'Electric Utility', '2099-01-01', ?)
            """,
            [
                (1, "S1", "PV", "SUN", "OP", 100),
                (1, "B1", "BA", "MWH", "OP", 50),
                (2, "S1", "PV", "SUN", "OP", 80),
                (3, "S1", "PV", "SUN", "OP", 60),
                (3, "B1", "BA", "MWH", "OP", 20),
                (4, "B1", "BA", "MWH", "OP", 30),
                (5, "S1", "PV", "SUN", "OP", 90),
                (6, "B1", "BA", "MWH", "OP", 25),
                (6, "S9", "PV", "SUN", "T", 70),
                (7, "W1", "WT", "WND", "OP", 40),
                (7, "B1", "BA", "MWH", "OP", 10),
            ],
        )
        self.conn.executemany(
            """
            INSERT INTO raw_data_eia860_energy_storage
            (version_num, report_date, plant_id_eia, generator_id,
            is_ac_coupled, is_dc_coupled, is_dc_coupled_tightly,
            is_independent, is_direct_support,
            plant_id_eia_direct_support_1, generator_id_direct_support_1)
            VALUES ('v-test', '2025-01-01', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "B1", 1, 0, 0, 0, 0, None, None),
                (3, "B1", 0, 0, 0, 1, 0, None, None),
                (4, "B1", 0, 1, 1, 0, 1, 5, "S1"),
            ],
        )
        self.conn.commit()

    def get_pairing(self, **fleet_kwargs):
        kwargs = {**FLEET_KWARGS, **fleet_kwargs}
        fleet_relation_sql = get_fleet_relation_sql(**kwargs)
        pairing_expr = get_hybrid_pairing_expr(
            generators_table=GENERATORS_TABLE,
            fleet_relation_sql=fleet_relation_sql,
        )
        basis_expr = get_hybrid_pairing_basis_expr(
            generators_table=GENERATORS_TABLE,
            fleet_relation_sql=fleet_relation_sql,
        )
        return {
            (plant, gen): (pairing, basis)
            for plant, gen, pairing, basis in self.conn.execute(
                f"SELECT plant_id_eia, generator_id, {pairing_expr}, "
                f"{basis_expr} {fleet_relation_sql}"
            )
        }

    def test_pairing_verdicts_and_bases(self):
        pairing = self.get_pairing()
        self.assertEqual(
            pairing,
            {
                # co-location pairs both components
                (1, "S1"): ("Hybrid", "co_located"),
                (1, "B1"): ("Hybrid", "co_located"),
                # standalone solar never pairs
                (2, "S1"): (None, None),
                # is_independent blocks the battery AND its co-located solar
                (3, "S1"): (None, None),
                (3, "B1"): (None, None),
                # the cross-plant direct-support link pairs both units —
                # plant co-location alone could never connect them
                (4, "B1"): ("Hybrid", "direct_support"),
                (5, "S1"): ("Hybrid", "direct_support"),
                # the co-located partner is outside the fleet tiers
                (6, "B1"): (None, None),
                # wind pairs like solar
                (7, "W1"): ("Hybrid", "co_located"),
                (7, "B1"): ("Hybrid", "co_located"),
            },
        )

    def test_out_of_fleet_partner_pairs_when_tier_included(self):
        # With planned_inclusion 'all', plant 6's 'T' solar joins the fleet
        # and its battery pairs — the in-fleet-partner semantics
        pairing = self.get_pairing(planned_inclusion="all")
        self.assertEqual(pairing[(6, "B1")], ("Hybrid", "co_located"))
        self.assertEqual(pairing[(6, "S9")], ("Hybrid", "co_located"))

    def test_empty_supplement_degrades_to_colocation(self):
        # Without supplement rows: plant 3 pairs (no is_independent to
        # block it), the cross-plant plants 4/5 no longer pair (no links),
        # plant 1 still pairs via co-location
        self.conn.execute("DELETE FROM raw_data_eia860_energy_storage")
        self.conn.commit()
        pairing = self.get_pairing()
        self.assertEqual(pairing[(1, "B1")], ("Hybrid", "co_located"))
        self.assertEqual(pairing[(3, "B1")], ("Hybrid", "co_located"))
        self.assertEqual(pairing[(3, "S1")], ("Hybrid", "co_located"))
        self.assertEqual(pairing[(4, "B1")], (None, None))
        self.assertEqual(pairing[(5, "S1")], (None, None))

    def test_storage_coupling_labels(self):
        coupling_expr = get_storage_coupling_expr(generators_table=GENERATORS_TABLE)
        fleet_relation_sql = get_fleet_relation_sql(**FLEET_KWARGS)
        coupling = {
            (plant, gen): value
            for plant, gen, value in self.conn.execute(
                f"SELECT plant_id_eia, generator_id, {coupling_expr} "
                f"{fleet_relation_sql}"
            )
        }
        self.assertEqual(coupling[(1, "B1")], "ac_coupled")
        self.assertEqual(coupling[(3, "B1")], "independent")
        # dc_coupled_tightly beats the also-set dc_coupled
        self.assertEqual(coupling[(4, "B1")], "dc_coupled_tightly")
        # no supplement row: NULL — non-batteries and batteries newer than
        # the loaded vintage
        self.assertIsNone(coupling[(6, "B1")])
        self.assertIsNone(coupling[(1, "S1")])

    def make_step_args(self, **kwargs):
        args = dict(
            project_aggregation="all",
            aggregation_dimensions="hybrid",
            aggregation_level=None,
            include_retired=False,
            planned_inclusion="under_construction",
            inactive_inclusion="none",
            include_planned_retirements=True,
            exclude_commercial_industrial_sectors=False,
            include_net_metered=True,
            **FLEET_KWARGS,
        )
        args.update(kwargs)
        return Namespace(**args)

    def test_hybrid_dimension_splits_aggregates(self):
        # The steps' shared adapter builds the pairing expression and the
        # names split hybrid components from standalone ones
        parsed_args = self.make_step_args()
        project_name_str = get_project_name_str_from_args(parsed_args)
        fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)
        projects = {
            project: (n, mw)
            for project, n, mw in self.conn.execute(
                f"SELECT {project_name_str} AS project, COUNT(*), "
                f"SUM(capacity_mw) {fleet_relation_sql} "
                f"GROUP BY project ORDER BY project"
            )
        }
        self.assertEqual(
            projects,
            {
                "Batteries_BA1": (2, 45),  # plants 3 (independent), 6
                "Batteries_Hybrid_BA1": (3, 90),  # plants 1, 4, 7
                "Solar_BA1": (2, 140),  # plants 2, 3
                "Solar_Hybrid_BA1": (2, 190),  # plants 1, 5
                "Wind_Hybrid_BA1": (1, 40),  # plant 7
            },
        )

    def test_hybrid_dimension_inert_in_disaggregated_mode(self):
        # Mode 'none' never applies dimensions: same expression with and
        # without 'hybrid', no fleet relation built
        parsed_args = self.make_step_args(project_aggregation="none")
        self.assertFalse(requests_hybrid_dimension(parsed_args))
        self.assertEqual(
            get_project_name_str_from_args(parsed_args),
            get_project_name_str(
                project_aggregation="none",
                load_zone_level="baa",
                footprint="Interconnect1",
            ),
        )

    def test_hybrid_dimension_requires_runtime_expr(self):
        # A direct caller that doesn't supply the runtime-built expression
        # fails loudly instead of silently dropping the dimension
        with self.assertRaisesRegex(ValueError, "hybrid_pairing_expr"):
            get_aggregation_dimensions_sql(aggregation_dimensions="hybrid")
        with self.assertRaisesRegex(ValueError, "hybrid_pairing_expr"):
            get_project_name_str(
                project_aggregation="all",
                load_zone_level="baa",
                footprint="Interconnect1",
                aggregation_dimensions="hybrid",
            )

    def test_pairing_on_the_eia860m_table(self):
        # The same pairing rules against the changelog table: the inner
        # column references must qualify correctly on ITS aliased relation
        self.conn.executemany(
            """
            INSERT INTO raw_data_eia860m_generators
            (version_num, report_date, valid_until_date, plant_id_eia,
            generator_id, balancing_authority_code_eia, prime_mover_code,
            energy_source_code_1, operational_status_code, sector_id_eia,
            planned_generator_retirement_date, capacity_mw)
            VALUES ('v-test', '2026-06-01', '2026-07-01', ?, ?, 'BA1', ?,
            ?, 'OP', 1, '2099-01-01', ?)
            """,
            [
                (1, "S1", "PV", "SUN", 100),
                (1, "B1", "BA", "MWH", 50),
                (2, "S1", "PV", "SUN", 80),
            ],
        )
        self.conn.commit()
        fleet_relation_sql = get_fleet_relation_sql(
            generators_table="raw_data_eia860m_generators", **FLEET_KWARGS
        )
        pairing_expr = get_hybrid_pairing_expr(
            generators_table="raw_data_eia860m_generators",
            fleet_relation_sql=fleet_relation_sql,
        )
        pairing = {
            (plant, gen): value
            for plant, gen, value in self.conn.execute(
                f"SELECT plant_id_eia, generator_id, {pairing_expr} "
                f"{fleet_relation_sql}"
            )
        }
        self.assertEqual(pairing[(1, "S1")], "Hybrid")
        self.assertEqual(pairing[(1, "B1")], "Hybrid")
        self.assertIsNone(pairing[(2, "S1")])

    def test_warn_on_missing_energy_storage_data(self):
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            n_rows = warn_on_missing_energy_storage_data(conn=self.conn)
        self.assertEqual(n_rows, 3)
        self.assertEqual(captured.getvalue(), "")

        self.conn.execute("DELETE FROM raw_data_eia860_energy_storage")
        self.conn.commit()
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            n_rows = warn_on_missing_energy_storage_data(conn=self.conn)
        self.assertEqual(n_rows, 0)
        self.assertIn("WARNING", captured.getvalue())
        self.assertIn("co-location", captured.getvalue())

    def test_ensure_energy_storage_table_on_predating_database(self):
        # A raw database from before the table existed gets it (empty) on
        # first use, and re-running against a populated table is a no-op
        self.conn.execute("DROP TABLE raw_data_eia860_energy_storage")
        self.conn.commit()
        ensure_energy_storage_table(conn=self.conn)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM raw_data_eia860_energy_storage"
            ).fetchone()[0],
            0,
        )
        self.conn.execute(
            "INSERT INTO raw_data_eia860_energy_storage "
            "(version_num, report_date, plant_id_eia, generator_id) "
            "VALUES ('v', '2025-01-01', 1, 'B1')"
        )
        self.conn.commit()
        ensure_energy_storage_table(conn=self.conn)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM raw_data_eia860_energy_storage"
            ).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
