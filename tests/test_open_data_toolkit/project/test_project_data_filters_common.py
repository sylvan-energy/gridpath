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
import itertools
import os
import sqlite3
import tempfile
import unittest

from db.create_database import main as create_database_main
from open_data_toolkit.geographic_scope import (
    check_aggregation_level_refines_zone_level,
)
from open_data_toolkit.project.fleet.fleet_filters import (
    ensure_net_metering_table,
    get_fleet_relation_sql,
    get_net_metering_filter_string,
    warn_on_missing_net_metering_data,
)
from open_data_toolkit.project.fleet.unit_overrides import get_unit_override_sql
from open_data_toolkit.project.project_data_filters_common import (
    AGGREGATION_DIMENSIONS,
    ALL_KNOWN_STATUS_CODES,
    LOAD_ZONE_LEVEL_CHOICES,
    LOAD_ZONE_LEVEL_COLUMNS,
    check_custom_zone_level_ready,
    BTM_SECTOR_IDS,
    BTM_SECTOR_NAMES,
    DISAGG_PROJECT_NAME_STR,
    GENERATORS_TABLE_COLUMNS,
    get_aggregation_dimensions_sql,
    get_allowed_status_codes,
    get_btm_filter_string,
    get_eia860_sql_filter_string,
    get_eia860m_sql_filter_string,
    get_generators_table_str,
    get_project_name_str,
    warn_on_null_sector_rows,
    warn_on_missing_planned_retirement_data,
    get_retired_filter_string,
    warn_on_uncovered_status_codes,
)

RAW_DATA_DB_SCHEMA = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "open_data_toolkit",
    "raw_data_db_schema.sql",
)

# The full operational_status_code vocabulary of PUDL's
# core_eia__codes_operational_status, verified against v2026.7.2 — if a
# future dataset version adds codes, they must be added to a tier in
# open_data_toolkit/project/fleet_filters.py (or to
# NEVER_INCLUDED_STATUS_CODES) and to this snapshot
PUDL_STATUS_CODE_VOCABULARY = {
    "CN",  # cancelled
    "CO",  # under construction (older annual vintages)
    "IP",  # indefinitely postponed
    "L",  # planned, approvals pending
    "OA",  # out of service, short-term
    "OP",  # operating
    "OS",  # out of service, long-term
    "OT",  # other (proposed)
    "OZ",  # ozone-season-only emissions equipment
    "P",  # planned, approvals not initiated
    "PL",  # planned (generic)
    "RE",  # retired
    "SB",  # standby
    "SC",  # cold standby / deactivated
    "T",  # planned, approvals received
    "TS",  # construction complete, not yet commercial
    "U",  # under construction, <= 50% complete
    "V",  # under construction, > 50% complete
}


class TestGetAllowedStatusCodes(unittest.TestCase):
    def test_tier_composition(self):
        expected = {
            ("none", "none"): {"OP"},
            ("under_construction", "none"): {"OP", "CO", "U", "V", "TS"},
            ("all", "none"): {
                "OP",
                "CO",
                "U",
                "V",
                "TS",
                "P",
                "L",
                "T",
                "OT",
                "PL",
            },
            ("none", "standby"): {"OP", "SB"},
            ("none", "out_of_service_short_term"): {"OP", "SB", "OA"},
            ("none", "all"): {"OP", "SB", "OA", "OS", "SC"},
            ("under_construction", "standby"): {
                "OP",
                "CO",
                "U",
                "V",
                "TS",
                "SB",
            },
        }
        for (planned, inactive), codes in expected.items():
            self.assertEqual(
                set(
                    get_allowed_status_codes(
                        planned_inclusion=planned, inactive_inclusion=inactive
                    )
                ),
                codes,
                msg=f"planned_inclusion={planned}, inactive_inclusion={inactive}",
            )

    def test_unknown_levels_raise(self):
        with self.assertRaises(ValueError):
            get_allowed_status_codes(planned_inclusion="bogus")
        with self.assertRaises(ValueError):
            get_allowed_status_codes(
                planned_inclusion="none", inactive_inclusion="bogus"
            )

    def test_all_known_codes_cover_the_pudl_vocabulary(self):
        # Every code in the (verified) PUDL vocabulary is accounted for —
        # includable at some setting, retired, or deliberately excluded —
        # and the known set contains nothing else
        self.assertEqual(set(ALL_KNOWN_STATUS_CODES), PUDL_STATUS_CODE_VOCABULARY)
        # No code is in two tiers
        self.assertEqual(len(ALL_KNOWN_STATUS_CODES), len(set(ALL_KNOWN_STATUS_CODES)))


class TestEIA860EIA860MFilterSymmetry(unittest.TestCase):
    def test_filters_identical_at_every_setting(self):
        # The 860M filter delegates to the 860 one; this pins that the two
        # never diverge silently (the status-code vocabularies are
        # identical in current PUDL data). The one intended difference is
        # the behind-the-meter sector clause — 860M only carries the
        # numeric sector_id_eia — checked separately below; with
        # include_btm_plants there is no sector clause and the filters
        # must be byte-identical
        for include_retired, planned, inactive, incl_pret in itertools.product(
            (False, True),
            ("none", "under_construction", "all"),
            ("none", "standby", "out_of_service_short_term", "all"),
            (False, True),
        ):
            kwargs = dict(
                study_year=2030,
                footprint="western",
                load_zone_level="region",
                include_retired=include_retired,
                planned_inclusion=planned,
                inactive_inclusion=inactive,
                include_planned_retirements=incl_pret,
                include_btm_plants=True,
            )
            self.assertEqual(
                get_eia860m_sql_filter_string(**kwargs),
                get_eia860_sql_filter_string(**kwargs),
            )

    def test_default_filters_differ_only_by_the_btm_sector_clause(self):
        kwargs = dict(study_year=2030, footprint="western", load_zone_level="region")
        filter_860 = get_eia860_sql_filter_string(**kwargs)
        filter_860m = get_eia860m_sql_filter_string(**kwargs)
        clause_860 = get_btm_filter_string(include_btm_plants=False)
        clause_860m = get_btm_filter_string(
            include_btm_plants=False,
            sector_column="sector_id_eia",
            btm_sector_values=BTM_SECTOR_IDS,
        )
        self.assertIn(clause_860, filter_860)
        self.assertIn(clause_860m, filter_860m)
        self.assertEqual(
            filter_860.replace(clause_860, ""),
            filter_860m.replace(clause_860m, ""),
        )


class TestBTMFilter(unittest.TestCase):
    def test_btm_sector_constants(self):
        # The commercial/industrial EIA sectors; the id set is the EIA
        # standard mapping of the same four sectors (4=Commercial Non-CHP,
        # 5=Commercial CHP, 6=Industrial Non-CHP, 7=Industrial CHP),
        # verified against v2026.7.2 unit counts
        self.assertEqual(
            BTM_SECTOR_NAMES,
            (
                "Commercial CHP",
                "Commercial Non-CHP",
                "Industrial CHP",
                "Industrial Non-CHP",
            ),
        )
        self.assertEqual(BTM_SECTOR_IDS, (4, 5, 6, 7))

    def test_include_btm_plants_removes_the_clause(self):
        self.assertEqual(get_btm_filter_string(include_btm_plants=True), "")

    def test_clause_excludes_btm_and_keeps_null_sector_rows(self):
        # Behavior-level check against sqlite: BTM-sector units drop,
        # non-BTM and NULL-sector units are kept — on the name column
        # (annual 860) and the integer id column (860M) alike
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE units (unit TEXT, name_col TEXT, id_col INTEGER)")
        conn.executemany(
            "INSERT INTO units VALUES (?, ?, ?)",
            [
                ("utility", "Electric Utility", 1),
                ("ipp", "IPP Non-CHP", 2),
                ("industrial_chp", "Industrial CHP", 7),
                ("commercial", "Commercial Non-CHP", 4),
                ("unclassified", None, None),
            ],
        )
        name_clause = get_btm_filter_string(
            include_btm_plants=False, sector_column="name_col"
        )
        id_clause = get_btm_filter_string(
            include_btm_plants=False,
            sector_column="id_col",
            btm_sector_values=BTM_SECTOR_IDS,
        )
        for clause in (name_clause, id_clause):
            kept = {
                row[0]
                for row in conn.execute(
                    f"SELECT unit FROM units WHERE 1 = 1 {clause}"
                ).fetchall()
            }
            self.assertEqual(kept, {"utility", "ipp", "unclassified"})
        conn.close()


class TestPlannedRetirementFilter(unittest.TestCase):
    PLANNED_RET_CLAUSE = (
        "AND (unixepoch(planned_generator_retirement_date) > "
        "unixepoch('2030-12-31') or planned_generator_retirement_date IS "
        "NULL)"
    )

    def test_excluded_by_default(self):
        filter_string = get_retired_filter_string(
            study_year=2030,
            allowed_status_codes=("OP",),
            include_retired=False,
        )
        self.assertIn(self.PLANNED_RET_CLAUSE, filter_string)

    def test_include_planned_retirements_removes_the_clause(self):
        with_clause = get_retired_filter_string(
            study_year=2030,
            allowed_status_codes=("OP",),
            include_retired=False,
        )
        without_clause = get_retired_filter_string(
            study_year=2030,
            allowed_status_codes=("OP",),
            include_retired=False,
            include_planned_retirements=True,
        )
        self.assertNotIn("planned_generator_retirement_date", without_clause)
        # the clause is the ONLY difference
        self.assertEqual(
            with_clause.replace("\n     " + self.PLANNED_RET_CLAUSE, ""),
            without_clause,
        )

    def test_applies_independently_of_include_retired(self):
        # include_retired drops the actual-retirement window but the
        # planned-retirement window still applies by default
        filter_string = get_retired_filter_string(
            study_year=2030,
            allowed_status_codes=("OP",),
            include_retired=True,
        )
        self.assertIn(self.PLANNED_RET_CLAUSE, filter_string)
        self.assertIn("'RE'", filter_string)


class TestWarnOnMissingPlannedRetirementData(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "planned_ret_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)

    def insert_units(self, rows):
        self.conn.executemany(
            "INSERT INTO raw_data_eia860_generators (plant_id_eia, "
            "generator_id, planned_generator_retirement_date) "
            "VALUES (?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = warn_on_missing_planned_retirement_data(
                conn=self.conn,
                generators_table="raw_data_eia860_generators",
            )
        return result, out.getvalue()

    def test_no_warning_when_any_row_has_a_date(self):
        self.insert_units([(1, "1", "2027-06-01"), (2, "1", None)])
        (n_populated, n_rows), output = self.check()
        self.assertEqual((n_populated, n_rows), (1, 2))
        self.assertEqual(output, "")

    def test_warns_when_column_entirely_null(self):
        self.insert_units([(1, "1", None), (2, "1", None)])
        (n_populated, n_rows), output = self.check()
        self.assertEqual((n_populated, n_rows), (0, 2))
        self.assertIn("WARNING", output)
        self.assertIn("gridpath_pudl_to_gridpath_raw", output)

    def test_no_warning_on_empty_table(self):
        # an empty generators table is some other problem, not this one
        (n_populated, n_rows), output = self.check()
        self.assertEqual((n_populated, n_rows), (0, 0))
        self.assertEqual(output, "")


class TestCustomZoneLevel(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "custom_level_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)
        self.conn.executemany(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES (?, ?, ?)",
            [
                ("Zone1", "Region1", "Interconnect1"),
                ("Zone2", "Region1", "Interconnect1"),
                ("ZoneX", "RegionX", "InterconnectX"),
            ],
        )
        self.conn.commit()

    def check(self, load_zone_level="custom", footprint="Region1"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = check_custom_zone_level_ready(
                conn=self.conn,
                load_zone_level=load_zone_level,
                footprint=footprint,
            )
        return result, out.getvalue()

    def test_choices_are_the_columns_plus_all(self):
        self.assertEqual(
            LOAD_ZONE_LEVEL_CHOICES, tuple(LOAD_ZONE_LEVEL_COLUMNS) + ("all",)
        )
        self.assertEqual(LOAD_ZONE_LEVEL_COLUMNS["custom"], "custom_zone")

    def test_noop_at_other_levels(self):
        result, output = self.check(load_zone_level="baa")
        self.assertEqual(result, [])
        self.assertEqual(output, "")

    def test_missing_column_raises(self):
        self.conn.execute("ALTER TABLE raw_data_eia_baa_codes DROP COLUMN custom_zone")
        with self.assertRaises(ValueError):
            self.check()

    def test_no_mapped_in_footprint_bas_raises(self):
        # only an out-of-footprint BA is mapped
        self.conn.execute(
            "UPDATE raw_data_eia_baa_codes SET custom_zone = 'X' " "WHERE baa = 'ZoneX'"
        )
        with self.assertRaises(ValueError):
            self.check(footprint="Region1")

    def test_warns_on_unmapped_in_footprint_bas(self):
        self.conn.execute(
            "UPDATE raw_data_eia_baa_codes SET custom_zone = 'A' " "WHERE baa = 'Zone1'"
        )
        unmapped, output = self.check(footprint="Region1")
        # Zone2 is in footprint and unmapped; ZoneX is out of footprint
        self.assertEqual(unmapped, ["Zone2"])
        self.assertIn("WARNING", output)
        self.assertIn("Zone2", output)
        self.assertNotIn("ZoneX", output)

    def test_all_mapped_is_quiet(self):
        self.conn.execute(
            "UPDATE raw_data_eia_baa_codes SET custom_zone = 'A' "
            "WHERE baa IN ('Zone1', 'Zone2')"
        )
        unmapped, output = self.check(footprint="Region1")
        self.assertEqual(unmapped, [])
        self.assertEqual(output, "")


class TestWarnOnNullSectorRows(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "sector_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)

    def insert_units(self, rows):
        self.conn.executemany(
            "INSERT INTO raw_data_eia860_generators (plant_id_eia, "
            "generator_id, sector_name_eia, capacity_mw) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = warn_on_null_sector_rows(
                conn=self.conn,
                generators_table="raw_data_eia860_generators",
                sector_column="sector_name_eia",
            )
        return result, out.getvalue()

    def test_no_warning_when_all_rows_have_a_sector(self):
        self.insert_units([(1, "1", "Electric Utility", 100)])
        (n_null, null_mw, n_rows), output = self.check()
        self.assertEqual((n_null, n_rows), (0, 1))
        self.assertEqual(output, "")

    def test_warns_on_some_null_sector_rows(self):
        self.insert_units(
            [
                (1, "1", "Electric Utility", 100),
                (2, "1", None, 40),
                (3, "1", None, 60),
            ]
        )
        (n_null, null_mw, n_rows), output = self.check()
        self.assertEqual((n_null, null_mw, n_rows), (2, 100, 3))
        self.assertIn("WARNING", output)
        self.assertIn("2 units (100 MW)", output)
        self.assertIn("INCLUDED", output)
        # not the all-NULL case: no stale-raw-data hint
        self.assertNotIn("gridpath_pudl_to_gridpath_raw", output)

    def test_all_null_mentions_stale_raw_data(self):
        self.insert_units([(1, "1", None, 100), (2, "1", None, 50)])
        (n_null, null_mw, n_rows), output = self.check()
        self.assertEqual((n_null, n_rows), (2, 2))
        self.assertIn("entirely NULL", output)
        self.assertIn("gridpath_pudl_to_gridpath_raw", output)


class TestWarnOnUncoveredStatusCodes(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "status_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)

    def insert_units(self, rows):
        self.conn.executemany(
            "INSERT INTO raw_data_eia860_generators (plant_id_eia, "
            "generator_id, operational_status_code, capacity_mw) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def test_no_warning_when_all_codes_covered(self):
        self.insert_units(
            [(i, "1", code, 100) for i, code in enumerate(ALL_KNOWN_STATUS_CODES)]
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            uncovered = warn_on_uncovered_status_codes(
                conn=self.conn, generators_table="raw_data_eia860_generators"
            )
        self.assertEqual(uncovered, [])
        self.assertEqual(out.getvalue(), "")

    def test_warns_on_unknown_and_null_codes(self):
        self.insert_units(
            [
                (1, "1", "OP", 100),
                (2, "1", "XX", 40),  # unknown code
                (3, "1", "XX", 60),
                (4, "1", None, 20),  # NULL code
            ]
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            uncovered = warn_on_uncovered_status_codes(
                conn=self.conn, generators_table="raw_data_eia860_generators"
            )
        self.assertEqual(uncovered, [(None, 1, 20), ("XX", 2, 100)])
        output = out.getvalue()
        self.assertIn("WARNING", output)
        self.assertIn("'XX' (2 units, 100 MW)", output)
        self.assertNotIn("'OP'", output)


class TestAggregationNaming(unittest.TestCase):
    def test_none_mode_is_the_disaggregated_name(self):
        self.assertEqual(
            get_project_name_str(
                project_aggregation="none",
                load_zone_level="baa",
                footprint="western",
            ),
            DISAGG_PROJECT_NAME_STR,
        )

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            get_project_name_str(
                project_aggregation="bogus",
                load_zone_level="baa",
                footprint="western",
            )

    def test_keyed_mode_mixes_aggregate_and_unit_names(self):
        name_str = get_project_name_str(
            project_aggregation="agg_project_keyed",
            load_zone_level="baa",
            footprint="western",
        )
        self.assertIn("CASE WHEN agg_project IS NOT NULL", name_str)
        self.assertIn(DISAGG_PROJECT_NAME_STR, name_str)
        self.assertIn("COALESCE(agg_project, gridpath_technology)", name_str)

    def test_dimensions_insert_between_technology_and_zone(self):
        name_str = get_project_name_str(
            project_aggregation="all",
            load_zone_level="baa",
            footprint="western",
            aggregation_dimensions="vintage_decade,status",
        )
        aggregation_override_sql = get_unit_override_sql(column="aggregation")
        self.assertEqual(
            name_str,
            "COALESCE(agg_project, gridpath_technology)"
            " || COALESCE('_' || CAST(CAST(STRFTIME('%Y', "
            "generator_operating_date) AS INTEGER) / 10 * 10 AS TEXT) || 's', '')"
            " || COALESCE('_' || operational_status_code, '')"
            f" || '_' || COALESCE({aggregation_override_sql}, "
            "raw_data_eia_baa_codes.baa)",
        )

    def test_unknown_dimension_raises(self):
        with self.assertRaisesRegex(ValueError, "Unknown aggregation dimension"):
            get_aggregation_dimensions_sql(aggregation_dimensions="bogus")

    def test_dimension_unsupported_by_table_raises(self):
        # Every current catalog dimension is carried by both generator
        # tables, so exercise the missing-column guard with a synthetic
        # dimension needing an annual-table column the 860M changelog lacks
        from unittest.mock import patch

        with patch.dict(
            AGGREGATION_DIMENSIONS,
            {"synthetic": {"expr": "sector_name_eia", "columns": ["sector_name_eia"]}},
        ):
            with self.assertRaisesRegex(ValueError, "does not carry"):
                get_aggregation_dimensions_sql(
                    aggregation_dimensions="synthetic",
                    generators_table="raw_data_eia860m_generators",
                )

    def test_every_dimension_supported_on_the_eia860_table(self):
        # The annual table must carry every catalog dimension's columns —
        # a new dimension whose columns aren't in GENERATORS_TABLE_COLUMNS
        # (and the raw table) would fail at query time in every step
        for dimension, spec in AGGREGATION_DIMENSIONS.items():
            missing = [
                c
                for c in spec["columns"]
                if c not in GENERATORS_TABLE_COLUMNS["raw_data_eia860_generators"]
            ]
            self.assertEqual(missing, [], msg=dimension)

    def test_empty_dimensions_contribute_nothing(self):
        self.assertEqual(get_aggregation_dimensions_sql(aggregation_dimensions=""), "")
        self.assertEqual(get_aggregation_dimensions_sql(aggregation_dimensions=[]), "")

    def test_unset_aggregation_level_is_the_zone_level(self):
        # The default must stay byte-identical to pre-aggregation_level
        # behavior: None resolves to the load-zone level
        for load_zone_level in LOAD_ZONE_LEVEL_CHOICES:
            self.assertEqual(
                get_project_name_str(
                    project_aggregation="all",
                    load_zone_level=load_zone_level,
                    footprint="western",
                ),
                get_project_name_str(
                    project_aggregation="all",
                    load_zone_level=load_zone_level,
                    footprint="western",
                    aggregation_level=load_zone_level,
                ),
                msg=load_zone_level,
            )

    def test_aggregation_level_replaces_the_name_zone_token(self):
        # zone level 'custom' with per-BA aggregation: the NAME uses the
        # baa column, not the custom_zone column
        name_str = get_project_name_str(
            project_aggregation="all",
            load_zone_level="custom",
            footprint="western",
            aggregation_level="baa",
        )
        aggregation_override_sql = get_unit_override_sql(column="aggregation")
        self.assertEqual(
            name_str,
            "COALESCE(agg_project, gridpath_technology)"
            f" || '_' || COALESCE({aggregation_override_sql}, "
            "raw_data_eia_baa_codes.baa)",
        )
        self.assertNotIn("custom_zone", name_str)


class TestAggregationLevelRefinesZoneLevel(unittest.TestCase):
    """
    check_aggregation_level_refines_zone_level: an aggregation level must
    refine the load-zone level over the in-footprint BAs — a value spanning
    zones or a NULL value at the aggregation level raises.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "agg_level_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)
        self.conn.executemany(
            "INSERT INTO raw_data_eia_baa_codes "
            "(baa, region, interconnect, custom_zone) VALUES (?, ?, ?, ?)",
            [
                ("BA1", "Region1", "Interconnect1", "CustomA"),
                ("BA2", "Region1", "Interconnect1", "CustomA"),
                ("BA3", "Region2", "Interconnect1", "CustomB"),
                # out of footprint: its inconsistencies must not matter
                ("BAX", "RegionX", "InterconnectX", "CustomA"),
            ],
        )
        self.conn.commit()

    def check(self, aggregation_level, load_zone_level, footprint="Interconnect1"):
        return check_aggregation_level_refines_zone_level(
            conn=self.conn,
            aggregation_level=aggregation_level,
            load_zone_level=load_zone_level,
            footprint=footprint,
        )

    def test_noop_when_unset_or_equal(self):
        self.assertEqual(self.check(None, "custom"), [])
        self.assertEqual(self.check("custom", "custom"), [])

    def test_baa_refines_every_level(self):
        for load_zone_level in ("region", "interconnect", "custom", "all"):
            self.assertEqual(self.check("baa", load_zone_level), [])

    def test_region_under_custom_passes_here(self):
        # In this fixture regions nest inside custom zones (Region1 ->
        # CustomA, Region2 -> CustomB), so region-level aggregation under
        # custom zones is valid
        self.assertEqual(self.check("region", "custom"), [])

    def test_coarser_level_raises(self):
        # Interconnect1 spans CustomA and CustomB
        with self.assertRaisesRegex(ValueError, "does not refine"):
            self.check("interconnect", "custom")
        # 'all' (one name token for the whole footprint) over multiple zones
        with self.assertRaisesRegex(ValueError, "does not refine"):
            self.check("all", "region")

    def test_crosscutting_level_raises(self):
        # Make CustomA cut across regions: BA3 (Region2) joins CustomA, so
        # neither nests in the other
        self.conn.execute(
            "UPDATE raw_data_eia_baa_codes SET custom_zone = 'CustomA' "
            "WHERE baa = 'BA3'"
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "does not refine"):
            self.check("custom", "region")

    def test_null_aggregation_level_value_raises(self):
        # BA2 has a load zone (custom) but no region: its aggregated name
        # would be NULL under region-level aggregation
        self.conn.execute(
            "UPDATE raw_data_eia_baa_codes SET region = NULL WHERE baa = 'BA2'"
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "no value at the aggregation level"):
            self.check("region", "custom")

    def test_out_of_footprint_inconsistencies_ignored(self):
        # BAX crosses zones relative to the others but is out of footprint
        self.assertEqual(self.check("region", "custom"), [])

    def test_custom_aggregation_level_needs_the_column_ready(self):
        # A custom AGGREGATION level gets the same readiness check as a
        # custom zone level: no mapped in-footprint BA raises
        self.conn.execute("UPDATE raw_data_eia_baa_codes SET custom_zone = NULL")
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "gridpath_apply_custom_zones"):
            self.check("custom", "baa")


class TestNetMeteringFilter(unittest.TestCase):
    """
    The net-metered exclusion (raw_data_eia860_solar flag): flagged units
    drop by default, everything absent from the solar table is kept,
    include_net_metered keeps everything, and an empty table is a no-op
    (with the loud warning).
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        db_path = os.path.join(self.tmp_dir.name, "net_metering_test_raw.db")
        create_database_main(
            ["--database", db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        self.conn = sqlite3.connect(db_path)
        self.addCleanup(self.conn.close)
        self.conn.execute(
            "INSERT INTO raw_data_eia_baa_codes (baa, region, interconnect) "
            "VALUES ('BA1', 'Region1', 'Interconnect1')"
        )
        self.conn.execute("""
            INSERT INTO user_defined_eia_gridpath_key
            (prime_mover_code, energy_source_code, gridpath_capacity_type,
            gridpath_operational_type, gridpath_technology, agg_project)
            VALUES ('PV', 'SUN', 'gen_spec', 'gen_var', 'Solar', 'Solar')
            """)
        self.conn.executemany(
            """
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            balancing_authority_code_eia, prime_mover_code,
            energy_source_code_1, operational_status_code, sector_name_eia,
            capacity_mw)
            VALUES ('v-test', '2026-01-01', ?, ?, 'BA1', 'PV', 'SUN', 'OP',
            'Electric Utility', 100)
            """,
            [(1, "1"), (2, "1"), (3, "1")],
        )
        # Unit 1__1 is net-metered; 2__1 has a flag-0 row; 3__1 is absent
        # from the solar table (e.g. newer than the loaded solar vintage)
        self.conn.executemany(
            """
            INSERT INTO raw_data_eia860_solar
            (version_num, report_date, plant_id_eia, generator_id,
            uses_net_metering_agreement)
            VALUES ('v-test', '2025-01-01', ?, ?, ?)
            """,
            [(1, "1", 1), (2, "1", 0)],
        )
        self.conn.commit()

    def query_fleet(self, **kwargs):
        sql = f"""
            SELECT plant_id_eia || '__' || generator_id AS project
            {get_fleet_relation_sql(
                ba_source="eia860",
                study_year=2030,
                footprint="Interconnect1",
                **kwargs,
            )}
            ORDER BY project
            ;
            """
        return [p for (p,) in self.conn.cursor().execute(sql)]

    def test_flagged_units_excluded_by_default(self):
        self.assertEqual(self.query_fleet(), ["2__1", "3__1"])

    def test_include_net_metered_keeps_them(self):
        self.assertEqual(
            self.query_fleet(include_net_metered=True), ["1__1", "2__1", "3__1"]
        )

    def test_empty_table_is_a_noop(self):
        self.conn.execute("DELETE FROM raw_data_eia860_solar")
        self.conn.commit()
        self.assertEqual(self.query_fleet(), ["1__1", "2__1", "3__1"])

    def test_clause_present_only_when_excluding(self):
        self.assertIn(
            "raw_data_eia860_solar",
            get_net_metering_filter_string(include_net_metered=False),
        )
        self.assertEqual(get_net_metering_filter_string(include_net_metered=True), "")

    def test_warns_on_empty_table(self):
        self.conn.execute("DELETE FROM raw_data_eia860_solar")
        self.conn.commit()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            n_rows = warn_on_missing_net_metering_data(conn=self.conn)
        self.assertEqual(n_rows, 0)
        self.assertIn("WARNING", out.getvalue())
        self.assertIn("raw_data_eia860_solar", out.getvalue())

    def test_no_warning_when_table_has_rows(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            n_rows = warn_on_missing_net_metering_data(conn=self.conn)
        self.assertEqual(n_rows, 2)
        self.assertEqual(out.getvalue(), "")

    def test_table_created_on_first_use(self):
        self.conn.execute("DROP TABLE raw_data_eia860_solar")
        self.conn.commit()
        ensure_net_metering_table(conn=self.conn)
        self.assertEqual(self.query_fleet(), ["1__1", "2__1", "3__1"])


class TestBAAssignmentPrecedence(unittest.TestCase):
    """
    The generator -> BA assignment relation: manual overrides beat the
    EIA-930A operational assignment, which beats the EIA-860 survey answer.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "ba_precedence_test.db")
        create_database_main(
            ["--database", cls.db_path, "--db_schema", RAW_DATA_DB_SCHEMA, "--quiet"]
        )
        conn = sqlite3.connect(cls.db_path)
        conn.executemany(
            """
            INSERT INTO raw_data_eia860_generators
            (version_num, report_date, plant_id_eia, generator_id,
            balancing_authority_code_eia, capacity_mw)
            VALUES ('v-test', '2026-01-01', ?, ?, ?, 100)
            """,
            [
                # Not in EIA-930A: keeps its EIA-860 BA
                (1, "1", "Zone860"),
                # In EIA-930A under a different BA: reassigned
                (2, "1", "Zone860"),
                # Two units at one plant, only one of them in EIA-930A —
                # the split a plant-wide '*' override is meant to heal
                (3, "A", "Zone860"),
                (3, "B", "Zone860"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO raw_data_eia930a_generators
            (data_year, ba, schedule, plant_id_eia, generator_id)
            VALUES (2024, ?, 2, ?, ?)
            """,
            [("Zone930A", 2, "1"), ("Zone930A", 3, "A")],
        )
        conn.commit()
        conn.close()

    def assigned_bas(self, ba_source, overrides=()):
        """The (plant, generator) -> assigned BA map for a set of overrides."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM user_defined_baa_overrides")
            conn.executemany(
                """
                INSERT INTO user_defined_baa_overrides
                (plant_id_eia, generator_id, balancing_authority_code_eia)
                VALUES (?, ?, ?)
                """,
                overrides,
            )
            conn.commit()
            return {(plant, generator): ba for plant, generator, ba in conn.execute(f"""
                    SELECT plant_id_eia, generator_id,
                        balancing_authority_code_eia
                    FROM {get_generators_table_str(ba_source=ba_source)}
                    """).fetchall()}
        finally:
            conn.close()

    def test_no_overrides_eia860_uses_the_survey_answer(self):
        self.assertEqual(
            self.assigned_bas(ba_source="eia860"),
            {
                (1, "1"): "Zone860",
                (2, "1"): "Zone860",
                (3, "A"): "Zone860",
                (3, "B"): "Zone860",
            },
        )

    def test_no_overrides_eia930a_reassigns_only_matched_units(self):
        self.assertEqual(
            self.assigned_bas(ba_source="eia930a"),
            {
                (1, "1"): "Zone860",
                (2, "1"): "Zone930A",
                # Plant 3 is split: only unit A matched EIA-930A
                (3, "A"): "Zone930A",
                (3, "B"): "Zone860",
            },
        )

    def test_override_beats_both_sources(self):
        overrides = [(2, "1", "ZoneManual")]
        for ba_source in ["eia860", "eia930a"]:
            with self.subTest(ba_source=ba_source):
                self.assertEqual(
                    self.assigned_bas(ba_source=ba_source, overrides=overrides)[
                        (2, "1")
                    ],
                    "ZoneManual",
                    msg="a manual override must win under either ba_source",
                )

    def test_plant_wide_override_heals_a_split_plant(self):
        assigned = self.assigned_bas(
            ba_source="eia930a", overrides=[(3, "*", "ZoneManual")]
        )
        self.assertEqual(assigned[(3, "A")], "ZoneManual")
        self.assertEqual(assigned[(3, "B")], "ZoneManual")
        # Other plants are untouched
        self.assertEqual(assigned[(1, "1")], "Zone860")
        self.assertEqual(assigned[(2, "1")], "Zone930A")

    def test_generator_row_wins_over_plant_wide_row(self):
        assigned = self.assigned_bas(
            ba_source="eia930a",
            overrides=[(3, "*", "ZonePlantWide"), (3, "B", "ZoneSpecific")],
        )
        self.assertEqual(assigned[(3, "A")], "ZonePlantWide")
        self.assertEqual(assigned[(3, "B")], "ZoneSpecific")

    def test_overlapping_overrides_do_not_duplicate_generators(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM user_defined_baa_overrides")
            conn.executemany(
                """
                INSERT INTO user_defined_baa_overrides
                (plant_id_eia, generator_id, balancing_authority_code_eia)
                VALUES (?, ?, ?)
                """,
                [(3, "*", "ZonePlantWide"), (3, "B", "ZoneSpecific")],
            )
            conn.commit()
            n_rows = conn.execute(
                f"SELECT COUNT(*) FROM "
                f"{get_generators_table_str(ba_source='eia930a')}"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n_rows, 4, msg="overrides must not multiply generator rows")

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
