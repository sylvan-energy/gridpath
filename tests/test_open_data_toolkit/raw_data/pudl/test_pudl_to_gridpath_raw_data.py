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
import tempfile
import unittest

import duckdb
import pandas as pd

from open_data_toolkit.raw_data.common_functions import log_data_metadata
from open_data_toolkit.raw_data.pudl.pudl_to_gridpath_raw_data import (
    ANNUAL_ONLY_GENERATOR_COLUMNS,
    ANNUAL_ONLY_PLANT_COLUMNS,
    convert_eia923_generation_fuel_to_csv,
    convert_eia930_net_generation_to_csv,
    convert_eia930_operations_to_csv,
    determine_eia860_report_date,
    determine_pudl_version,
    get_eia860m_generator_data_from_pudl_parquet,
    get_eia_baa_codes_from_pudl_parquet,
    get_eia_generator_data_from_pudl_parquet,
    get_eia860_solar_data_from_pudl_parquet,
    main as pudl_to_gridpath_raw_data_main,
    warn_on_baa_coverage,
)

# Two EIA860 report dates; plant 1's generator is uprated 100 -> 150 MW,
# plant 2's generator is retired, and plant 3's battery first appears in the
# 2025 data. The generator-type/ownership columns (aggregation dimensions)
# are appended per prime mover / plant so their passthrough is assertable.
GENERATORS_FIXTURE_SQL = """
    SELECT t.*,
        CASE prime_mover_code
            WHEN 'CT' THEN 'Natural Gas Fired Combustion Turbine'
            WHEN 'ST' THEN 'Natural Gas Steam Turbine'
            WHEN 'BA' THEN 'Batteries'
        END AS technology_description,
        CASE prime_mover_code WHEN 'BA' THEN 'other' ELSE 'gas'
        END AS fuel_type_code_pudl,
        CASE WHEN plant_id_eia = 1 THEN
            CASE WHEN report_date = DATE '2024-01-01' THEN 'RFO' ELSE 'DFO' END
        END AS energy_source_code_2,
        plant_id_eia = 1 AS can_burn_multiple_fuels,
        FALSE AS can_cofire_fuels,
        plant_id_eia = 1 AS can_switch_oil_gas,
        FALSE AS carbon_capture,
        CASE WHEN plant_id_eia = 1 THEN '12H'
        END AS time_cold_shutdown_full_load_code,
        CASE WHEN plant_id_eia = 1 THEN
            CASE WHEN report_date = DATE '2024-01-01' THEN 45.0 ELSE 50.0 END
        END AS minimum_load_mw,
        'S' AS ownership_code,
        100 + plant_id_eia AS utility_id_eia,
        CASE WHEN plant_id_eia = 1 AND report_date = DATE '2025-01-01'
            THEN DATE '2027-06-01'
        END AS planned_generator_retirement_date
    FROM (VALUES
        (1, '1', DATE '2024-01-01', 'OP', 'existing', 100.0, 100.0, 100.0,
         CAST(NULL AS FLOAT), 'CT', 'NG', CAST(NULL AS DATE),
         CAST(NULL AS DATE)),
        (2, '1', DATE '2024-01-01', 'RE', 'retired', 40.0, 40.0, 40.0,
         CAST(NULL AS FLOAT), 'ST', 'NG', CAST(NULL AS DATE),
         DATE '2023-06-01'),
        (1, '1', DATE '2025-01-01', 'OP', 'existing', 150.0, 150.0, 150.0,
         CAST(NULL AS FLOAT), 'CT', 'NG', CAST(NULL AS DATE),
         CAST(NULL AS DATE)),
        (2, '1', DATE '2025-01-01', 'RE', 'retired', 40.0, 40.0, 40.0,
         CAST(NULL AS FLOAT), 'ST', 'NG', CAST(NULL AS DATE),
         DATE '2023-06-01'),
        (3, 'B1', DATE '2025-01-01', 'OP', 'existing', 20.0, 20.0, 20.0,
         80.0, 'BA', 'MWH', CAST(NULL AS DATE), CAST(NULL AS DATE))
    ) t(plant_id_eia, generator_id, report_date, operational_status_code,
        operational_status, capacity_mw, summer_capacity_mw,
        winter_capacity_mw, energy_storage_capacity_mwh, prime_mover_code,
        energy_source_code_1, current_planned_generator_operating_date,
        generator_retirement_date)
"""

PLANTS_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        (1, DATE '2024-01-01', 'Zone1', 7, 'Electric Utility', FALSE, 22),
        (2, DATE '2024-01-01', 'Zone1', 7, 'Electric Utility', TRUE, 22),
        (1, DATE '2025-01-01', 'Zone1', 1, 'Electric Utility', FALSE, 22),
        (2, DATE '2025-01-01', 'Zone1', 1, 'Electric Utility', TRUE, 22),
        (3, DATE '2025-01-01', 'Zone2', 2, 'IPP Non-CHP', FALSE, 22)
    ) t(plant_id_eia, report_date, balancing_authority_code_eia,
        sector_id_eia, sector_name_eia, ferc_cogen_status,
        primary_purpose_id_naics)
"""

# The static generator entity table; plant 3's battery is deliberately
# absent, so its entity-derived columns come through NULL (LEFT JOIN)
ENTITY_GENERATORS_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        (1, '1', DATE '2005-07-01', FALSE),
        (2, '1', DATE '1985-03-01', TRUE)
    ) t(plant_id_eia, generator_id, generator_operating_date,
        associated_combined_heat_power)
"""

# Two solar vintages: unit 1-1 flips to net-metered in the 2025 filing;
# unit 5-PV exists only in 2024
SOLAR_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        (DATE '2024-01-01', 1, '1', FALSE, NULL, FALSE, NULL),
        (DATE '2024-01-01', 5, 'PV', TRUE, 2.5, FALSE, NULL),
        (DATE '2025-01-01', 1, '1', TRUE, 1.2, FALSE, NULL)
    ) t(report_date, plant_id_eia, generator_id,
        uses_net_metering_agreement, net_metering_capacity_mwdc,
        uses_virtual_net_metering_agreement, virtual_net_metering_capacity_mwdc)
"""

EIA860M_FIXTURE_SQL = """
    SELECT t.*,
        'gas' AS fuel_type_code_pudl,
        CASE prime_mover_code
            WHEN 'CT' THEN 'Natural Gas Fired Combustion Turbine'
            WHEN 'ST' THEN 'Natural Gas Steam Turbine'
        END AS technology_description,
        1 AS sector_id_eia,
        CASE WHEN plant_id_eia = 1 AND report_date = DATE '2025-06-01'
            THEN DATE '2030-12-01'
        END AS planned_generator_retirement_date
    FROM (VALUES
        -- Operating generator with a pre-uprate history row: only the
        -- latest (150 MW) row is kept unless the full changelog is asked
        -- for
        (DATE '2024-01-01', DATE '2025-06-01', 1, '1', 'OP', 'existing',
         'Zone1', 100.0, 100.0, 100.0, CAST(NULL AS FLOAT), 'CT', 'NG',
         DATE '2010-01-01', CAST(NULL AS DATE), CAST(NULL AS DATE)),
        (DATE '2025-06-01', DATE '2025-12-01', 1, '1', 'OP', 'existing',
         'Zone1', 150.0, 150.0, 150.0, CAST(NULL AS FLOAT), 'CT', 'NG',
         DATE '2010-01-01', CAST(NULL AS DATE), CAST(NULL AS DATE)),
        -- Generator retired in its latest changelog entry: its whole
        -- history goes when retired units are excluded
        (DATE '2020-01-01', DATE '2023-01-01', 2, '1', 'OP', 'existing',
         'Zone1', 40.0, 40.0, 40.0, CAST(NULL AS FLOAT), 'ST', 'NG',
         DATE '1990-01-01', CAST(NULL AS DATE), CAST(NULL AS DATE)),
        (DATE '2023-01-01', DATE '2025-12-01', 2, '1', 'RE', 'retired',
         'Zone1', 40.0, 40.0, 40.0, CAST(NULL AS FLOAT), 'ST', 'NG',
         DATE '1990-01-01', CAST(NULL AS DATE), DATE '2022-12-01')
    ) t(report_date, valid_until_date, plant_id_eia, generator_id,
        operational_status_code, operational_status,
        balancing_authority_code_eia, capacity_mw, summer_capacity_mw,
        winter_capacity_mw, energy_storage_capacity_mwh, prime_mover_code,
        energy_source_code_1, generator_operating_date,
        current_planned_generator_operating_date, generator_retirement_date)
"""

EIAAEO_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        (2023, 'western_electricity_coordinating_council_basin', 'aeo2022',
         2025, 'coal', 1.9, 1.9, 2022),
        (2023, 'some_other_region', 'aeo2022', 2025, 'coal', 2.5, 2.5, 2022)
    ) t(report_year, electricity_market_module_region_eiaaeo,
        model_case_eiaaeo, projection_year, fuel_type_eiaaeo,
        fuel_cost_per_mmbtu, fuel_cost_real_per_mmbtu_eiaaeo,
        real_cost_basis_year)
"""

EIA930_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        (TIMESTAMP '2024-06-01 10:00:00', 'Zone1', 'Zone2', 100.0),
        (TIMESTAMP '2024-06-01 11:00:00', 'Zone1', 'Zone2', 120.0)
    ) t(datetime_utc, balancing_authority_code_eia,
        balancing_authority_code_adjacent_eia, interchange_reported_mwh)
"""

# Hourly generation by energy source; the first row is 00:00 PST = hour
# ending 24 of May 31, so it must aggregate into May, not June. Zone1 wind
# comes as a main-category row plus an overlapping subcategory row (the
# vocabulary is kept as published).
EIA930_NET_GEN_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        (TIMESTAMP '2024-06-01 08:00:00', 'Zone1', 'gas', 100.0, 100.0,
         100.0),
        (TIMESTAMP '2024-06-01 09:00:00', 'Zone1', 'gas', 50.0, 50.0, 50.0),
        (TIMESTAMP '2024-06-01 10:00:00', 'Zone1', 'gas', 30.0, 25.0, 30.0),
        (TIMESTAMP '2024-06-01 10:00:00', 'Zone1', 'wind', 10.0, 10.0, 10.0),
        (TIMESTAMP '2024-06-01 10:00:00', 'Zone1',
         'wind_wo_integrated_battery_storage', 10.0, 10.0, 10.0),
        (TIMESTAMP '2024-06-01 10:00:00', 'Zone2', 'coal', 300.0, 290.0,
         300.0)
    ) t(datetime_utc, balancing_authority_code_eia, generation_energy_source,
        net_generation_reported_mwh, net_generation_adjusted_mwh,
        net_generation_imputed_eia_mwh)
"""

# Per-BA operations. Zone1's three hours all report everything and satisfy
# demand = generation - interchange. Zone2's second hour is missing
# interchange, so it counts toward the all-hours sums but not the
# complete-hours ones — the basis the identity residual is computed on.
EIA930_OPERATIONS_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        (TIMESTAMP '2024-06-01 08:00:00', 'Zone1', 100.0, 30.0, 70.0, 70.0),
        (TIMESTAMP '2024-06-01 09:00:00', 'Zone1', 200.0, 50.0, 150.0, 150.0),
        (TIMESTAMP '2024-06-01 10:00:00', 'Zone1', 300.0, 60.0, 240.0, 245.0),
        (TIMESTAMP '2024-06-01 09:00:00', 'Zone2', 400.0, 100.0, 300.0,
         300.0),
        (TIMESTAMP '2024-06-01 10:00:00', 'Zone2', 500.0,
         CAST(NULL AS DOUBLE), 380.0, 380.0)
    ) t(datetime_utc, balancing_authority_code_eia,
        net_generation_reported_mwh, interchange_reported_mwh,
        demand_reported_mwh, demand_adjusted_mwh)
"""

# Monthly plant-fuel generation actuals; the 2017 row predates the default
# start year and must be dropped
EIA923_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        (DATE '2017-06-01', 1, 'NG', 'gas', 'CT', 999.0, 'final'),
        (DATE '2024-06-01', 1, 'NG', 'gas', 'CT', 100.0, 'final'),
        (DATE '2024-06-01', 2, 'NUC', 'nuclear', 'ST', 500.0, 'final')
    ) t(report_date, plant_id_eia, energy_source_code, fuel_type_code_pudl,
        prime_mover_code, net_generation_mwh, data_maturity)
"""

# A few BAs: a western one, an eastern retired generation-only one, and a
# foreign one with no interconnect value (kept with a blank)
BAA_CODES_FIXTURE_SQL = """
    SELECT * FROM (VALUES
        ('CISO', 'California ISO', 'desc', 'CAL', 'California', 'PST',
         CAST(NULL AS DATE), FALSE, 'western'),
        ('GLHB', 'Gridliance', 'desc', 'MIDW', 'Midwest', 'CST',
         DATE '2022-09-01', TRUE, 'eastern'),
        ('AESO', 'Alberta ESO', 'desc', 'CAN', 'Canada', 'MST',
         CAST(NULL AS DATE), FALSE, CAST(NULL AS VARCHAR)),
        -- The BAs the other fixtures use, so that default runs are
        -- coverage-clean
        ('Zone1', 'Zone 1', 'desc', 'Region1', 'Region One', 'PST',
         CAST(NULL AS DATE), FALSE, 'Interconnect1'),
        ('Zone2', 'Zone 2', 'desc', 'Region1', 'Region One', 'PST',
         CAST(NULL AS DATE), FALSE, 'Interconnect1')
    ) t(code, label, description, balancing_authority_region_code_eia,
        balancing_authority_region_name_eia, report_timezone,
        balancing_authority_retirement_date, is_generation_only,
        interconnect_code_eia)
"""


class TestPudlToGridPathRawData(unittest.TestCase):
    """
    Test the EIA860 generator conversion against small parquet fixtures (no
    PUDL download needed).
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        for filename, fixture_sql in [
            ("core_eia860__scd_generators", GENERATORS_FIXTURE_SQL),
            ("core_eia860__scd_plants", PLANTS_FIXTURE_SQL),
            ("core_eia__entity_generators", ENTITY_GENERATORS_FIXTURE_SQL),
            ("core_eia860__scd_generators_solar", SOLAR_FIXTURE_SQL),
            ("core_eia860m__changelog_generators", EIA860M_FIXTURE_SQL),
            (
                "core_eiaaeo__yearly_projected_fuel_cost_in_electric_sector" "_by_type",
                EIAAEO_FIXTURE_SQL,
            ),
            ("core_eia930__hourly_interchange", EIA930_FIXTURE_SQL),
            (
                "core_eia930__hourly_net_generation_by_energy_source",
                EIA930_NET_GEN_FIXTURE_SQL,
            ),
            (
                "core_eia930__hourly_operations",
                EIA930_OPERATIONS_FIXTURE_SQL,
            ),
            (
                "out_eia923__monthly_generation_fuel_combined",
                EIA923_FIXTURE_SQL,
            ),
            ("core_eia__codes_balancing_authorities", BAA_CODES_FIXTURE_SQL),
        ]:
            parquet_path = os.path.join(cls.tmp_dir.name, f"{filename}.parquet")
            duckdb.sql(f"COPY ({fixture_sql}) TO '{parquet_path}' (FORMAT PARQUET)")

    def get_generators_csv(self, report_date, annual_detail_report_date=None):
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        get_eia_generator_data_from_pudl_parquet(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            report_date=report_date,
            pudl_version="v-test",
            annual_detail_report_date=annual_detail_report_date,
            quiet=True,
        )

        df = pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia860_generators.csv"),
            dtype={"generator_id": str},
        )

        return df.sort_values(["plant_id_eia", "generator_id"])

    def test_determine_eia860_report_date_defaults_to_latest(self):
        self.assertEqual(
            determine_eia860_report_date(
                pudl_download_directory=self.tmp_dir.name, eia860_report_date=None
            ),
            "2025-01-01",
        )

    def test_determine_eia860_report_date_explicit_passthrough(self):
        self.assertEqual(
            determine_eia860_report_date(
                pudl_download_directory=self.tmp_dir.name,
                eia860_report_date="2024-01-01",
            ),
            "2024-01-01",
        )

    def test_determine_eia860_report_date_bogus_raises(self):
        # A report date with no rows would yield an empty generator CSV,
        # so it fails loudly instead
        with self.assertRaises(ValueError):
            determine_eia860_report_date(
                pudl_download_directory=self.tmp_dir.name,
                eia860_report_date="2019-01-01",
            )

    def test_generator_csv_with_default_report_date(self):
        # With the default (latest) report date, we get the 2025 data —
        # ALL of it (the uprated plant 1 generator, the retired plant 2
        # generator, and the new plant 3 battery): status filtering happens
        # downstream, not at the convert stage
        report_date = determine_eia860_report_date(
            pudl_download_directory=self.tmp_dir.name, eia860_report_date=None
        )
        df = self.get_generators_csv(report_date=report_date)

        self.assertEqual(
            df[["plant_id_eia", "generator_id", "capacity_mw"]].values.tolist(),
            [[1, "1", 150.0], [2, "1", 40.0], [3, "B1", 20.0]],
        )
        self.assertEqual(df["version_num"].unique().tolist(), ["v-test"])
        # The vintage travels with the data (downstream steps default their
        # EIA860M as-of date to it)
        self.assertEqual(df["report_date"].unique().tolist(), ["2025-01-01"])
        self.assertEqual(
            df["balancing_authority_code_eia"].tolist(), ["Zone1", "Zone1", "Zone2"]
        )
        # The generator-type/ownership/sector columns (aggregation
        # dimensions) pass through from the generators and plants tables
        self.assertEqual(
            df["technology_description"].tolist(),
            [
                "Natural Gas Fired Combustion Turbine",
                "Natural Gas Steam Turbine",
                "Batteries",
            ],
        )
        self.assertEqual(df["fuel_type_code_pudl"].tolist(), ["gas", "gas", "other"])
        self.assertEqual(
            df[["energy_source_code_2", "minimum_load_mw"]].iloc[0].tolist(),
            ["DFO", 50.0],
        )
        self.assertEqual(df["can_switch_oil_gas"].tolist(), [True, False, False])
        self.assertEqual(
            df["sector_name_eia"].tolist(),
            ["Electric Utility", "Electric Utility", "IPP Non-CHP"],
        )
        self.assertEqual(df["ferc_cogen_status"].tolist(), [False, True, False])
        self.assertEqual(df["utility_id_eia"].tolist(), [101, 102, 103])
        # The entity-table columns (operating date, CHP flag) join per
        # generator; plant 3 is not in the entity table, so they are NULL
        self.assertEqual(
            df["generator_operating_date"].tolist()[:2],
            ["2005-07-01", "1985-03-01"],
        )
        self.assertTrue(pd.isna(df["generator_operating_date"].iloc[2]))
        self.assertEqual(
            df["associated_combined_heat_power"].tolist()[:2], [False, True]
        )
        self.assertTrue(pd.isna(df["associated_combined_heat_power"].iloc[2]))
        # The planned retirement date passes through (the default fleet
        # filter downstream excludes on it)
        self.assertEqual(df["planned_generator_retirement_date"].iloc[0], "2027-06-01")
        self.assertTrue(df["planned_generator_retirement_date"].iloc[1:].isna().all())

    def test_generator_csv_with_explicit_report_date(self):
        # The 2024 data predates the uprate and the plant 3 battery
        df = self.get_generators_csv(report_date="2024-01-01")

        self.assertEqual(
            df[["plant_id_eia", "generator_id", "capacity_mw"]].values.tolist(),
            [[1, "1", 100.0], [2, "1", 40.0]],
        )

    def test_generator_csv_with_annual_detail_backfill(self):
        # The fleet comes from the 2025 vintage while the annual-form-only
        # columns come from the pinned 2024 one — the combination a fresh
        # (EIA860M-derived) vintage needs, since those columns are NULL
        # there. The fixture gives plant 1 DIFFERENT annual values at the
        # two vintages, so the source of each column is unambiguous.
        df = self.get_generators_csv(
            report_date="2025-01-01", annual_detail_report_date="2024-01-01"
        )

        # Fleet and always-populated columns: the 2025 vintage (uprated
        # plant 1, and the plant 3 battery that does not exist in 2024)
        self.assertEqual(
            df[["plant_id_eia", "generator_id", "capacity_mw"]].values.tolist(),
            [[1, "1", 150.0], [2, "1", 40.0], [3, "B1", 20.0]],
        )
        self.assertEqual(df["report_date"].unique().tolist(), ["2025-01-01"])

        # Annual-form-only columns: the 2024 values (45.0/'RFO', not the
        # 2025 50.0/'DFO'), generator-level and plant-level alike
        self.assertEqual(df["minimum_load_mw"].iloc[0], 45.0)
        self.assertEqual(df["energy_source_code_2"].iloc[0], "RFO")
        self.assertEqual(df["sector_id_eia"].tolist()[:2], [7, 7])
        # ... while sector_name_eia is NOT annual-only and stays fresh
        self.assertEqual(
            df["sector_name_eia"].tolist(),
            ["Electric Utility", "Electric Utility", "IPP Non-CHP"],
        )

        # The plant 3 battery is absent from the 2024 vintage, so it keeps
        # NULLs for every annual-only column rather than dropping out
        for column in ANNUAL_ONLY_GENERATOR_COLUMNS + ANNUAL_ONLY_PLANT_COLUMNS:
            self.assertTrue(pd.isna(df[column].iloc[2]), msg=column)

    def test_generator_csv_annual_detail_bogus_date_raises(self):
        # A detail vintage with no rows would silently NULL every
        # annual-only column, so it fails loudly instead
        with self.assertRaises(ValueError):
            self.get_generators_csv(
                report_date="2025-01-01", annual_detail_report_date="2019-01-01"
            )

    def get_eia860m_csv(self, latest_only):
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        get_eia860m_generator_data_from_pudl_parquet(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            pudl_version="v-test",
            latest_only=latest_only,
            quiet=True,
        )

        return pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia860m_generators.csv"),
            dtype={"generator_id": str},
        )

    def test_eia860m_csv_latest_only(self):
        # The default: one row per generator — its latest changelog entry —
        # with no status filtering at the convert stage (plant 2's latest
        # row is its retirement entry)
        df = self.get_eia860m_csv(latest_only=True)

        self.assertEqual(
            df[["plant_id_eia", "report_date", "operational_status"]].values.tolist(),
            [[1, "2025-06-01", "existing"], [2, "2023-01-01", "retired"]],
        )
        # The 860M type/sector columns pass through too
        self.assertEqual(
            df["technology_description"].tolist(),
            [
                "Natural Gas Fired Combustion Turbine",
                "Natural Gas Steam Turbine",
            ],
        )
        self.assertEqual(df["fuel_type_code_pudl"].unique().tolist(), ["gas"])
        self.assertEqual(df["sector_id_eia"].unique().tolist(), [1])
        self.assertEqual(
            df["planned_generator_retirement_date"].tolist()[0], "2030-12-01"
        )
        self.assertTrue(pd.isna(df["planned_generator_retirement_date"].iloc[1]))

    def test_eia860m_csv_full_changelog(self):
        # With latest_only off, the complete changelog comes through: plant
        # 1's pre-uprate and latest rows, and plant 2's pre-retirement and
        # retirement rows
        df = self.get_eia860m_csv(latest_only=False)

        self.assertEqual(
            df[df["plant_id_eia"] == 1]["capacity_mw"].tolist(), [100.0, 150.0]
        )
        self.assertEqual(
            df[df["plant_id_eia"] == 2]["operational_status"].tolist(),
            ["existing", "retired"],
        )

    def test_eia_baa_codes_csv(self):
        # The BA map comes through as-is (all BAs — retired,
        # generation-only, and foreign ones too), with friendly column
        # names: baa = the PUDL 'code' column, region = the EIA930 region,
        # interconnect kept for filtering (blank where the source has no
        # value, e.g. AESO)
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        get_eia_baa_codes_from_pudl_parquet(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            quiet=True,
        )

        df = pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia_baa_codes.csv"),
            dtype=str,
            keep_default_na=False,
        )
        self.assertEqual(
            df.columns.tolist(),
            [
                "baa",
                "region",
                "region_name",
                "interconnect",
                "retirement_date",
                "is_generation_only",
                "timezone",
            ],
        )
        self.assertEqual(
            df[["baa", "region", "interconnect", "retirement_date"]].values.tolist(),
            [
                ["AESO", "CAN", "", ""],
                ["CISO", "CAL", "western", ""],
                ["GLHB", "MIDW", "eastern", "2022-09-01"],
                ["Zone1", "Region1", "Interconnect1", ""],
                ["Zone2", "Region1", "Interconnect1", ""],
            ],
        )

    def test_warn_on_baa_coverage(self):
        # A purpose-built inconsistent download dir: the map knows only
        # Zone1, the interchange references ZoneNew, and one non-retired
        # generator has no BA at all — all three findings must be warned
        # about and recorded in the metadata trail
        download_dir = tempfile.mkdtemp(dir=self.tmp_dir.name)
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        fixtures = {
            "core_eia__codes_balancing_authorities": """
                SELECT 'Zone1' AS code
            """,
            "core_eia930__hourly_interchange": """
                SELECT * FROM (VALUES
                    ('Zone1', 'ZoneNew'), ('ZoneNew', 'Zone1')
                ) t(balancing_authority_code_eia,
                    balancing_authority_code_adjacent_eia)
            """,
            "core_eia860__scd_generators": """
                SELECT * FROM (VALUES
                    (1, '1', DATE '2025-01-01', 'existing', 100.0),
                    (2, '1', DATE '2025-01-01', 'existing', 40.0),
                    (3, '1', DATE '2025-01-01', 'retired', 500.0)
                ) t(plant_id_eia, generator_id, report_date,
                    operational_status, capacity_mw)
            """,
            "core_eia860__scd_plants": """
                SELECT * FROM (VALUES
                    (1, DATE '2025-01-01', 'Zone1'),
                    (2, DATE '2025-01-01', CAST(NULL AS VARCHAR)),
                    (3, DATE '2025-01-01', CAST(NULL AS VARCHAR))
                ) t(plant_id_eia, report_date, balancing_authority_code_eia)
            """,
        }
        for filename, fixture_sql in fixtures.items():
            duckdb.sql(
                f"COPY ({fixture_sql}) TO "
                f"'{os.path.join(download_dir, filename)}.parquet' "
                f"(FORMAT PARQUET)"
            )

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            warn_on_baa_coverage(
                raw_data_directory=raw_data_directory,
                pudl_download_directory=download_dir,
                eia860_report_date="2025-01-01",
            )

        self.assertIn("ZoneNew", captured.getvalue())
        metadata = pd.read_csv(
            os.path.join(raw_data_directory, "data_metadata.csv"), dtype=str
        )
        warnings_rows = metadata[metadata["output_file"] == "run_warnings"]
        settings = dict(zip(warnings_rows["setting"], warnings_rows["value"]))
        self.assertEqual(settings["eia930_baas_missing_from_map"], "ZoneNew")
        # Only the NON-RETIRED null-BA unit counts (plant 2, 40 MW)
        self.assertEqual(
            settings["eia860_null_baa_generators"], "1 non-retired units (40 MW)"
        )
        self.assertNotIn("eia860_baas_missing_from_map", settings)

    def test_generator_csv_metadata_records_resolved_report_date(self):
        # The metadata trail must record the report date actually used,
        # not the (dynamic) default
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        report_date = determine_eia860_report_date(
            pudl_download_directory=self.tmp_dir.name, eia860_report_date=None
        )
        get_eia_generator_data_from_pudl_parquet(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            report_date=report_date,
            pudl_version="v-test",
            quiet=True,
        )

        metadata = pd.read_csv(
            os.path.join(raw_data_directory, "data_metadata.csv"), dtype=str
        )
        self.assertEqual(
            metadata.columns.tolist(),
            ["timestamp", "script", "output_file", "setting", "value"],
        )
        self.assertEqual(
            metadata["output_file"].unique().tolist(),
            ["pudl_eia860_generators.csv"],
        )
        settings = dict(zip(metadata["setting"], metadata["value"]))
        self.assertEqual(settings["eia860_report_date"], "2025-01-01")
        self.assertEqual(settings["pudl_version"], "v-test")
        self.assertIn("gridpath_version", settings)

    def test_determine_pudl_version_from_download_metadata(self):
        # Defaults to the version most recently recorded in the download
        # directory's metadata trail
        download_dir = tempfile.mkdtemp(dir=self.tmp_dir.name)
        log_data_metadata(
            directory=download_dir,
            script="download_data_from_pudl",
            output_file="a.parquet",
            settings={"pudl_version": "v-old"},
        )
        log_data_metadata(
            directory=download_dir,
            script="download_data_from_pudl",
            output_file="b.parquet",
            settings={"pudl_version": "v-new"},
        )

        self.assertEqual(
            determine_pudl_version(
                pudl_download_directory=download_dir, pudl_version=None
            ),
            "v-new",
        )

    def test_determine_pudl_version_per_source_file(self):
        # With source_file given, each file resolves to ITS latest version,
        # even when the directory holds files from different releases
        download_dir = tempfile.mkdtemp(dir=self.tmp_dir.name)
        log_data_metadata(
            directory=download_dir,
            script="download_data_from_pudl",
            output_file="a.parquet",
            settings={"pudl_version": "v-old"},
        )
        log_data_metadata(
            directory=download_dir,
            script="download_data_from_pudl",
            output_file="b.parquet",
            settings={"pudl_version": "v-new"},
        )

        self.assertEqual(
            determine_pudl_version(
                pudl_download_directory=download_dir,
                pudl_version=None,
                source_file="a.parquet",
            ),
            "v-old",
        )
        self.assertEqual(
            determine_pudl_version(
                pudl_download_directory=download_dir,
                pudl_version=None,
                source_file="b.parquet",
            ),
            "v-new",
        )
        # A file with no metadata entry resolves to unknown
        self.assertEqual(
            determine_pudl_version(
                pudl_download_directory=download_dir,
                pudl_version=None,
                source_file="never_downloaded.parquet",
            ),
            "unknown",
        )

    def test_determine_pudl_version_ignores_run_arguments_rows(self):
        # The download step's run_arguments entries also carry a
        # pudl_version setting (empty when defaulted); they must not shadow
        # the per-file entries
        download_dir = tempfile.mkdtemp(dir=self.tmp_dir.name)
        log_data_metadata(
            directory=download_dir,
            script="download_data_from_pudl",
            output_file="a.parquet",
            settings={"pudl_version": "v-file"},
        )
        log_data_metadata(
            directory=download_dir,
            script="download_data_from_pudl",
            output_file="run_arguments",
            settings={"pudl_version": ""},
        )

        for source_file in [None, "a.parquet"]:
            self.assertEqual(
                determine_pudl_version(
                    pudl_download_directory=download_dir,
                    pudl_version=None,
                    source_file=source_file,
                ),
                "v-file",
            )

    def test_determine_pudl_version_without_metadata_is_unknown(self):
        download_dir = tempfile.mkdtemp(dir=self.tmp_dir.name)

        self.assertEqual(
            determine_pudl_version(
                pudl_download_directory=download_dir, pudl_version=None
            ),
            "unknown",
        )

    def test_determine_pudl_version_explicit_passthrough(self):
        self.assertEqual(
            determine_pudl_version(
                pudl_download_directory=self.tmp_dir.name,
                pudl_version="v-explicit",
            ),
            "v-explicit",
        )

    def test_main_records_run_arguments_and_download_metadata(self):
        # End-to-end run of main() against the parquet fixtures: all five
        # raw CSVs are written, and the metadata trail holds the run
        # arguments, the resolved per-file settings, AND a copy of the
        # download-stage metadata of the source data
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)

        # Simulate the download step having recorded its metadata (a
        # single-release download of both generator source files)
        for source_file in [
            "core_eia860__scd_generators.parquet",
            "core_eia860m__changelog_generators.parquet",
        ]:
            log_data_metadata(
                directory=self.tmp_dir.name,
                script="download_data_from_pudl",
                output_file=source_file,
                settings={"pudl_version": "v-fixture", "source_url": "http://x"},
            )

        pudl_to_gridpath_raw_data_main(
            [
                "--pudl_download_directory",
                self.tmp_dir.name,
                "--raw_data_directory",
                raw_data_directory,
                "--quiet",
            ]
        )

        for f in [
            "pudl_eia860_generators.csv",
            "pudl_eia860m_generators.csv",
            "pudl_eia_baa_codes.csv",
            "pudl_eiaaeo_fuel_prices.csv",
            "pudl_eia930_hourly_interchange.csv",
            "pudl_eia930_net_generation_by_fuel.csv",
            "pudl_eia923_plant_fuel_generation.csv",
        ]:
            self.assertTrue(os.path.exists(os.path.join(raw_data_directory, f)))

        metadata = pd.read_csv(
            os.path.join(raw_data_directory, "data_metadata.csv"),
            dtype=str,
            keep_default_na=False,
        )

        # The run arguments as given (report date defaulted, so empty here)
        run_args = metadata[metadata["output_file"] == "run_arguments"]
        run_args_settings = dict(zip(run_args["setting"], run_args["value"]))
        self.assertEqual(run_args_settings["eia860_report_date"], "")
        self.assertEqual(run_args_settings["raw_data_directory"], raw_data_directory)
        self.assertEqual(run_args_settings["quiet"], "True")

        # The copied download-stage metadata of the source data
        download_rows = metadata[metadata["script"] == "download_data_from_pudl"]
        download_settings = dict(zip(download_rows["setting"], download_rows["value"]))
        self.assertEqual(download_settings["pudl_version"], "v-fixture")

        # The resolved report date in the per-file entry, and the PUDL
        # version resolved from the download-stage metadata
        generators_rows = metadata[
            metadata["output_file"] == "pudl_eia860_generators.csv"
        ]
        generators_settings = dict(
            zip(generators_rows["setting"], generators_rows["value"])
        )
        self.assertEqual(generators_settings["eia860_report_date"], "2025-01-01")
        self.assertEqual(generators_settings["pudl_version"], "v-fixture")

        # ... which is also what gets stamped into the generators CSVs
        # (per source file: the 860M CSV resolves from ITS source file's
        # metadata entry)
        for f in ["pudl_eia860_generators.csv", "pudl_eia860m_generators.csv"]:
            csv_df = pd.read_csv(os.path.join(raw_data_directory, f))
            self.assertEqual(csv_df["version_num"].unique().tolist(), ["v-fixture"])

        # A single-release download directory: no mixed-version warning
        self.assertNotIn("run_warnings", metadata["output_file"].tolist())

        # The 860M default is latest-only: plant 1's pre-uprate history row
        # is not in the CSV, just its latest (150 MW) entry
        eia860m_csv = pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia860m_generators.csv")
        )
        self.assertEqual(
            eia860m_csv[eia860m_csv["plant_id_eia"] == 1]["capacity_mw"].tolist(),
            [150.0],
        )

    def test_main_full_changelog_flag(self):
        # With --eia860m_full_changelog, plant 1's whole history (pre-uprate
        # and latest rows) makes it into the CSV
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)

        pudl_to_gridpath_raw_data_main(
            [
                "--pudl_download_directory",
                self.tmp_dir.name,
                "--raw_data_directory",
                raw_data_directory,
                "--eia860m_full_changelog",
                "--quiet",
            ]
        )

        eia860m_csv = pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia860m_generators.csv")
        )
        self.assertEqual(
            eia860m_csv[eia860m_csv["plant_id_eia"] == 1]["capacity_mw"].tolist(),
            [100.0, 150.0],
        )

    def test_eia930_net_generation_csv(self):
        # Hourly generation aggregates to monthly per BA and energy source;
        # the 08:00 UTC row is 00:00 PST = hour ending 24 of May 31, so it
        # lands in May; the overlapping subcategory rows pass through as
        # published (consumers filter to the main categories)
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        convert_eia930_net_generation_to_csv(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            quiet=True,
        )

        df = pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia930_net_generation_by_fuel.csv")
        )
        self.assertEqual(
            df.columns.tolist(),
            [
                "balancing_authority_code_eia",
                "year",
                "month",
                "generation_energy_source",
                "net_generation_reported_mwh",
                "net_generation_adjusted_mwh",
                "net_generation_imputed_eia_mwh",
            ],
        )
        self.assertEqual(
            df[
                [
                    "balancing_authority_code_eia",
                    "year",
                    "month",
                    "generation_energy_source",
                    "net_generation_reported_mwh",
                    "net_generation_adjusted_mwh",
                ]
            ].values.tolist(),
            [
                ["Zone1", 2024, 5, "gas", 100.0, 100.0],
                ["Zone1", 2024, 6, "gas", 80.0, 75.0],
                ["Zone1", 2024, 6, "wind", 10.0, 10.0],
                ["Zone1", 2024, 6, "wind_wo_integrated_battery_storage", 10.0, 10.0],
                ["Zone2", 2024, 6, "coal", 300.0, 290.0],
            ],
        )

    def test_eia930_operations_csv(self):
        # Hourly operations aggregate to monthly per BA on the same PST
        # hour-ending clock (the 08:00 UTC row lands in May). Each column is
        # summed twice: over every hour, and over only those hours where all
        # three identity columns are reported.
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        convert_eia930_operations_to_csv(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            quiet=True,
        )

        df = pd.read_csv(os.path.join(raw_data_directory, "pudl_eia930_operations.csv"))
        self.assertEqual(
            df.columns.tolist(),
            [
                "balancing_authority_code_eia",
                "year",
                "month",
                "net_generation_reported_mwh",
                "interchange_reported_mwh",
                "demand_reported_mwh",
                "demand_adjusted_mwh",
                "net_generation_complete_hours_mwh",
                "interchange_complete_hours_mwh",
                "demand_complete_hours_mwh",
                "hours",
                "hours_net_generation_reported",
                "hours_interchange_reported",
                "hours_demand_reported",
                "hours_complete",
            ],
        )
        self.assertEqual(
            df.values.tolist(),
            [
                # May: the single 08:00 UTC hour
                [
                    "Zone1",
                    2024,
                    5,
                    100.0,
                    30.0,
                    70.0,
                    70.0,
                    100.0,
                    30.0,
                    70.0,
                    1,
                    1,
                    1,
                    1,
                    1,
                ],
                [
                    "Zone1",
                    2024,
                    6,
                    500.0,
                    110.0,
                    390.0,
                    395.0,
                    500.0,
                    110.0,
                    390.0,
                    2,
                    2,
                    2,
                    2,
                    2,
                ],
                # Zone2's second hour has no interchange: it is in the
                # all-hours sums and out of the complete-hours ones
                [
                    "Zone2",
                    2024,
                    6,
                    900.0,
                    100.0,
                    680.0,
                    680.0,
                    400.0,
                    100.0,
                    300.0,
                    2,
                    2,
                    1,
                    2,
                    1,
                ],
            ],
        )

        # The identity closes on the complete-hours basis for both BAs, and
        # would appear to miss by 120 MWh for Zone2 on the all-hours basis
        zone2 = df[df["balancing_authority_code_eia"] == "Zone2"].iloc[0]
        self.assertEqual(
            zone2["net_generation_complete_hours_mwh"]
            - zone2["interchange_complete_hours_mwh"]
            - zone2["demand_complete_hours_mwh"],
            0.0,
        )
        self.assertEqual(
            zone2["net_generation_reported_mwh"]
            - zone2["interchange_reported_mwh"]
            - zone2["demand_reported_mwh"],
            120.0,
        )

    def test_eia923_generation_fuel_csv(self):
        # The default start year (2018) drops the 2017 row; everything else
        # passes through as published
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        convert_eia923_generation_fuel_to_csv(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            start_year=2018,
            quiet=True,
        )

        df = pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia923_plant_fuel_generation.csv")
        )
        self.assertEqual(
            df[
                [
                    "plant_id_eia",
                    "report_date",
                    "energy_source_code",
                    "net_generation_mwh",
                ]
            ].values.tolist(),
            [[1, "2024-06-01", "NG", 100.0], [2, "2024-06-01", "NUC", 500.0]],
        )

        metadata = pd.read_csv(
            os.path.join(raw_data_directory, "data_metadata.csv"), dtype=str
        )
        settings = dict(zip(metadata["setting"], metadata["value"]))
        self.assertEqual(settings["eia923_start_year"], "2018")

    def test_eia923_generation_fuel_csv_start_year(self):
        # An earlier explicit start year keeps the 2017 row
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        convert_eia923_generation_fuel_to_csv(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            start_year=2017,
            quiet=True,
        )

        df = pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia923_plant_fuel_generation.csv")
        )
        self.assertEqual(len(df), 3)
        self.assertEqual(df["report_date"].iloc[0], "2017-06-01")

    def get_solar_csv(self, solar_report_date=None):
        raw_data_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        get_eia860_solar_data_from_pudl_parquet(
            raw_data_directory=raw_data_directory,
            pudl_download_directory=self.tmp_dir.name,
            solar_report_date=solar_report_date,
            pudl_version="v-test",
            quiet=True,
        )
        return pd.read_csv(
            os.path.join(raw_data_directory, "pudl_eia860_solar.csv"),
            dtype={"generator_id": str},
        )

    def test_solar_defaults_to_latest_vintage(self):
        # The 2025 vintage has one row: unit 1-1, net-metered there
        df = self.get_solar_csv()
        self.assertEqual(df["report_date"].unique().tolist(), ["2025-01-01"])
        self.assertEqual(len(df), 1)
        self.assertEqual(int(df["uses_net_metering_agreement"].iloc[0]), 1)

    def test_solar_pinned_vintage(self):
        # The 2024 vintage: unit 1-1 not yet net-metered, unit 5-PV flagged
        df = self.get_solar_csv(solar_report_date="2024-01-01")
        self.assertEqual(len(df), 2)
        df = df.set_index(["plant_id_eia", "generator_id"])
        self.assertEqual(int(df.loc[(1, "1"), "uses_net_metering_agreement"]), 0)
        self.assertEqual(int(df.loc[(5, "PV"), "uses_net_metering_agreement"]), 1)
        self.assertEqual(float(df.loc[(5, "PV"), "net_metering_capacity_mwdc"]), 2.5)

    def test_solar_bad_vintage_raises(self):
        with self.assertRaisesRegex(ValueError, "eia860_solar_report_date"):
            self.get_solar_csv(solar_report_date="2026-06-15")

    def test_solar_missing_parquet_raises(self):
        empty_download_dir = tempfile.mkdtemp(dir=self.tmp_dir.name)
        with self.assertRaisesRegex(FileNotFoundError, "gridpath_get_pudl_data"):
            get_eia860_solar_data_from_pudl_parquet(
                raw_data_directory=tempfile.mkdtemp(dir=self.tmp_dir.name),
                pudl_download_directory=empty_download_dir,
                solar_report_date=None,
                pudl_version="v-test",
                quiet=True,
            )

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
