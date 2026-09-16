-- noinspection SqlNoDataSourceInspectionForFile

-- Copyright 2016-2024 Blue Marble Analytics LLC.
-- Copyright 2026 Sylvan Energy Analytics LLC.
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

--------------------------------------------------------------------------------
-------- METADATA --------
--------------------------------------------------------------------------------

-- Database metadata: the GridPath version used to create the database
-- (single-row table)
DROP TABLE IF EXISTS db_metadata;
CREATE TABLE db_metadata
(
    gridpath_version VARCHAR(64)
);

--------------------------------------------------------------------------------
-------- RAW DATA --------
--------------------------------------------------------------------------------
-- TODO: add timestamps?


DROP TABLE IF EXISTS raw_data_eiaaeo_fuel_prices;
CREATE TABLE raw_data_eiaaeo_fuel_prices
(
    report_year                             INTEGER,
    electricity_market_module_region_eiaaeo TEXT,
    model_case_eiaaeo                       TEXT,
    projection_year                         INTEGER,
    fuel_type_eiaaeo                        TEXT,
    fuel_cost_per_mmbtu                     FLOAT,
    fuel_cost_real_per_mmbtu_eiaaeo         FLOAT,
    real_cost_basis_year                    INTEGER,
    PRIMARY KEY (report_year, electricity_market_module_region_eiaaeo,
                 model_case_eiaaeo, projection_year, fuel_type_eiaaeo)
);


-- Note some columns are only reported on the full annual EIA860 form and
-- are NULL when the data comes from a monthly_update vintage (the latest
-- report_date rows, which are EIA860M-derived): energy_source_code_2,
-- can_burn_multiple_fuels, can_cofire_fuels, can_switch_oil_gas,
-- carbon_capture, time_cold_shutdown_full_load_code, minimum_load_mw,
-- ownership_code, sector_id_eia (though sector_name_eia IS populated
-- there), ferc_cogen_status, primary_purpose_id_naics.
-- generator_operating_date and associated_combined_heat_power come from
-- the static core_eia__entity_generators table (joined per generator).
DROP TABLE IF EXISTS raw_data_eia860_generators;
CREATE TABLE raw_data_eia860_generators
(
    version_num                              TEXT,
    report_date                              DATETIME,
    plant_id_eia                             INTEGER,
    generator_id                             TEXT,
    operational_status_code                  TEXT,
    operational_status                       TEXT,
    balancing_authority_code_eia             TEXT,
    capacity_mw                              REAL,
    summer_capacity_mw                       REAL,
    winter_capacity_mw                       REAL,
    minimum_load_mw                          REAL,
    energy_storage_capacity_mwh              REAL,
    prime_mover_code                         TEXT,
    energy_source_code_1                     TEXT,
    energy_source_code_2                     TEXT,
    fuel_type_code_pudl                      TEXT,
    technology_description                   TEXT,
    can_burn_multiple_fuels                  INTEGER,
    can_cofire_fuels                         INTEGER,
    can_switch_oil_gas                       INTEGER,
    carbon_capture                           INTEGER,
    time_cold_shutdown_full_load_code        TEXT,
    ownership_code                           TEXT,
    utility_id_eia                           INTEGER,
    sector_id_eia                            INTEGER,
    sector_name_eia                          TEXT,
    ferc_cogen_status                        INTEGER,
    primary_purpose_id_naics                 INTEGER,
    associated_combined_heat_power           INTEGER,
    generator_operating_date                 DATETIME,
    current_planned_generator_operating_date DATETIME,
    generator_retirement_date                DATETIME,
    planned_generator_retirement_date        DATETIME,
    PRIMARY KEY (version_num, report_date, plant_id_eia, generator_id)
);

-- EIA860M generator changelog: one row per generator per change, valid from
-- report_date until valid_until_date; monthly updates, fresher than the
-- annual EIA860 data
DROP TABLE IF EXISTS raw_data_eia860m_generators;
CREATE TABLE raw_data_eia860m_generators
(
    version_num                              TEXT,
    report_date                              DATETIME,
    valid_until_date                         DATETIME,
    plant_id_eia                             INTEGER,
    generator_id                             TEXT,
    operational_status_code                  TEXT,
    operational_status                       TEXT,
    balancing_authority_code_eia             TEXT,
    capacity_mw                              REAL,
    summer_capacity_mw                       REAL,
    winter_capacity_mw                       REAL,
    energy_storage_capacity_mwh              REAL,
    prime_mover_code                         TEXT,
    energy_source_code_1                     TEXT,
    fuel_type_code_pudl                      TEXT,
    technology_description                   TEXT,
    sector_id_eia                            INTEGER,
    generator_operating_date                 DATETIME,
    current_planned_generator_operating_date DATETIME,
    generator_retirement_date                DATETIME,
    planned_generator_retirement_date        DATETIME,
    PRIMARY KEY (version_num, report_date, plant_id_eia, generator_id)
);

-- Per-generator solar detail from the EIA860 solar supplement (from
-- pudl_eia860_solar.csv): the net-metering flags behind the project
-- steps' net-metered exclusion (include_net_metered setting). The solar
-- supplement is annual-form-only — the convert step pins one (by default
-- the latest annual) vintage, typically a report year behind a
-- monthly_update fleet, so newer solar units are absent and therefore
-- unflagged. An EMPTY table makes the exclusion a no-op (the steps warn
-- loudly); fleet_filters.py mirrors this DDL as CREATE TABLE IF NOT
-- EXISTS so pre-existing raw databases get the table on first use —
-- keep the two in sync.
DROP TABLE IF EXISTS raw_data_eia860_solar;
CREATE TABLE raw_data_eia860_solar
(
    version_num                          TEXT,
    report_date                          DATETIME,
    plant_id_eia                         INTEGER,
    generator_id                         TEXT,
    uses_net_metering_agreement          INTEGER,
    net_metering_capacity_mwdc           REAL,
    uses_virtual_net_metering_agreement  INTEGER,
    virtual_net_metering_capacity_mwdc   REAL,
    PRIMARY KEY (version_num, report_date, plant_id_eia, generator_id)
);

-- Per-battery detail from the EIA860 energy-storage supplement (from
-- pudl_eia860_energy_storage.csv): the direct-support pairing links and
-- coupling flags behind the project steps' hybrid-component pairing (the
-- 'hybrid' aggregation dimension and the fleet audit's hybrid columns),
-- plus the charge/discharge power ratings. Like the solar supplement it
-- is annual-form-only — the convert step pins one (by default the latest
-- annual) vintage, so newer batteries are absent (pairing then falls
-- back to plant co-location for them); the coupling flags and support
-- links are only populated from the 2023 vintage on. An EMPTY table
-- degrades pairing to plant co-location only (the steps warn loudly when
-- the hybrid dimension is in use); fleet_filters.py mirrors this DDL as
-- CREATE TABLE IF NOT EXISTS so pre-existing raw databases get the table
-- on first use — keep the two in sync.
DROP TABLE IF EXISTS raw_data_eia860_energy_storage;
CREATE TABLE raw_data_eia860_energy_storage
(
    version_num                          TEXT,
    report_date                          DATETIME,
    plant_id_eia                         INTEGER,
    generator_id                         TEXT,
    max_charge_rate_mw                   REAL,
    max_discharge_rate_mw                REAL,
    is_ac_coupled                        INTEGER,
    is_dc_coupled                        INTEGER,
    is_dc_coupled_tightly                INTEGER,
    is_independent                       INTEGER,
    is_direct_support                    INTEGER,
    plant_id_eia_direct_support_1        INTEGER,
    generator_id_direct_support_1        TEXT,
    plant_id_eia_direct_support_2        INTEGER,
    generator_id_direct_support_2        TEXT,
    plant_id_eia_direct_support_3        INTEGER,
    generator_id_direct_support_3        TEXT,
    PRIMARY KEY (version_num, report_date, plant_id_eia, generator_id)
);

DROP TABLE IF EXISTS raw_data_eia930_hourly_interchange;
CREATE TABLE raw_data_eia930_hourly_interchange
(
    datetime_utc                          DATETIME,
    balancing_authority_code_eia          TEXT,
    balancing_authority_code_adjacent_eia TEXT,
    interchange_reported_mwh              FLOAT,
    datetime_pst_he                       DATETIME,
    year                                  INTEGER,
    month                                 INTEGER,
    day_of_month                          INTEGER,
    hour_of_day                           INTEGER,
    PRIMARY KEY (balancing_authority_code_eia,
                 balancing_authority_code_adjacent_eia,
                 datetime_pst_he)
);

-- EIA930 net generation by BA and energy source, aggregated to MONTHLY
-- totals at the convert stage (see
-- pudl_to_gridpath_raw_data.convert_eia930_net_generation_to_csv). The
-- energy-source vocabulary is as published by EIA, INCLUDING overlapping
-- subcategories (e.g. wind_wo_integrated_battery_storage alongside wind,
-- hydro_excluding_pumped_storage alongside hydro) — consumers must filter
-- to the main categories to avoid double counting.
DROP TABLE IF EXISTS raw_data_eia930_net_generation_by_fuel;
CREATE TABLE raw_data_eia930_net_generation_by_fuel
(
    balancing_authority_code_eia   TEXT,
    year                           INTEGER,
    month                          INTEGER,
    generation_energy_source       TEXT,
    net_generation_reported_mwh    FLOAT,
    net_generation_adjusted_mwh    FLOAT,
    net_generation_imputed_eia_mwh FLOAT,
    PRIMARY KEY (balancing_authority_code_eia, year, month,
                 generation_energy_source)
);

-- EIA930 monthly per-BA net generation, interchange and demand, aggregated
-- from the hourly operations table. EIA derives demand as net generation
-- minus net interchange, so the three columns should satisfy that identity;
-- the *_complete_hours_mwh columns sum each one over only those hours where
-- all three are reported (hours_complete), which is the only basis on which
-- the residual (generation - interchange - demand) is meaningful, e.g. for
-- flagging BAs whose own three reported columns do not add up.
DROP TABLE IF EXISTS raw_data_eia930_operations;
CREATE TABLE raw_data_eia930_operations
(
    balancing_authority_code_eia       TEXT,
    year                               INTEGER,
    month                              INTEGER,
    net_generation_reported_mwh        FLOAT,
    interchange_reported_mwh           FLOAT,
    demand_reported_mwh                FLOAT,
    demand_adjusted_mwh                FLOAT,
    net_generation_complete_hours_mwh  FLOAT,
    interchange_complete_hours_mwh     FLOAT,
    demand_complete_hours_mwh          FLOAT,
    hours                              INTEGER,
    hours_net_generation_reported      INTEGER,
    hours_interchange_reported         INTEGER,
    hours_demand_reported              INTEGER,
    hours_complete                     INTEGER,
    PRIMARY KEY (balancing_authority_code_eia, year, month)
);

-- EIA923 monthly plant-level generation actuals by energy source and prime
-- mover (PUDL's combined generation-fuel table, which includes nuclear
-- plants), useful for reconciling the EIA930 BA-reported generation
-- against plant-level actuals
DROP TABLE IF EXISTS raw_data_eia923_plant_fuel_generation;
CREATE TABLE raw_data_eia923_plant_fuel_generation
(
    plant_id_eia        INTEGER,
    report_date         DATETIME,
    energy_source_code  TEXT,
    fuel_type_code_pudl TEXT,
    prime_mover_code    TEXT,
    net_generation_mwh  FLOAT,
    data_maturity       TEXT,
    PRIMARY KEY (plant_id_eia, report_date, energy_source_code,
                 prime_mover_code)
);

-- EIA-930A Annual Balancing Authority Generator Inventory: the
-- authoritative plant/generator -> operational-BA crosswalk (reconciles
-- EIA-860 survey-reported BA assignments with EIA-930 operational
-- boundaries). One row per generator per schedule: 2 = operating,
-- 3 = planned, 4 = pseudo-tie / dynamically scheduled (see
-- reported_on_schedule_2 and pseudo_tie_bas). plant_id_eia/generator_id
-- are the validated EIA-860 IDs; the *_eia930a columns hold the BA's
-- reported IDs where no exact EIA-860 match exists.
DROP TABLE IF EXISTS raw_data_eia930a_generators;
CREATE TABLE raw_data_eia930a_generators
(
    data_year                     INTEGER,
    ba                            TEXT,
    schedule                      INTEGER,
    plant_name                    TEXT,
    plant_id_eia                  INTEGER,
    generator_id                  TEXT,
    plant_id_eia930a              TEXT,
    generator_id_eia930a          TEXT,
    technology                    TEXT,
    nameplate_capacity_mw         REAL,
    state                         TEXT,
    county                        TEXT,
    latitude                      REAL,
    longitude                     REAL,
    operation_year                INTEGER,
    operation_month               INTEGER,
    reported_on_schedule_2        TEXT,
    pseudo_tie_bas                TEXT,
    nameplate_capacity_mw_eia930a REAL,
    state_eia930a                 TEXT,
    county_eia930a                TEXT
);

-- The EIA balancing-authority map (PUDL's
-- core_eia__codes_balancing_authorities table): baa is the BA code (the
-- PUDL 'code' column), region is the EIA930 region
-- (balancing_authority_region_code_eia; used as the study-scope --footprint
-- filter), interconnect is interconnect_code_eia (kept for filtering by
-- interconnection)
DROP TABLE IF EXISTS raw_data_eia_baa_codes;
CREATE TABLE raw_data_eia_baa_codes
(
    baa                TEXT PRIMARY KEY,
    region             TEXT,
    region_name        TEXT,
    interconnect       TEXT,
    retirement_date    DATETIME,
    is_generation_only INTEGER,
    timezone           TEXT,
    -- User-defined zone for the 'custom' load-zone level; populated by
    -- gridpath_apply_custom_zones (which also adds this column to raw
    -- databases created before it existed). NULL = the BA has no custom
    -- zone and is excluded at that level.
    custom_zone        TEXT
);

--------------------------------------------------------------------------------
-- Auxiliary user-defined data (maps, etc.)
--------------------------------------------------------------------------------

-- OPTIONAL manual generator -> balancing-authority overrides, applied with
-- higher precedence than both the EIA-930A operational assignment and the
-- EIA-860 survey answer (see get_generators_table_str in
-- project_data_filters_common.py). Use for units whose EIA-930A Schedule 2
-- claim is demonstrably contradicted by the hourly EIA-930 data — e.g.
-- units another BA telemeters, or a plant EIA-930A splits across BAs
-- because only some of its units matched an EIA-860 ID. An EMPTY table
-- (the default) leaves the assignment exactly as the source data has it.
-- generator_id '*' overrides every generator at the plant; a
-- generator-specific row wins over a '*' row for the same plant. The
-- reason column is free text, for documenting the evidence.
DROP TABLE IF EXISTS user_defined_baa_overrides;
CREATE TABLE user_defined_baa_overrides
(
    plant_id_eia                 INTEGER,
    generator_id                 TEXT,
    balancing_authority_code_eia TEXT,
    reason                       TEXT,
    PRIMARY KEY (plant_id_eia, generator_id)
);


-- OPTIONAL per-unit manual overrides for the EIA860(M)-based project
-- steps (see open_data_toolkit/project/fleet/unit_overrides.py, which
-- mirrors this DDL as CREATE TABLE IF NOT EXISTS so pre-existing raw
-- databases get the table on first use — keep the two in sync). An
-- EMPTY table (the default) is a no-op. One row per plant/generator
-- (generator_id '*' = every generator at the plant; a generator-specific
-- row wins over a '*' row, per column), with three independent nullable
-- override columns: include (1 = force into the fleet, bypassing the
-- characteristic filters; 0 = force out; NULL = no membership override),
-- aggregation (replaces the geographic token in the unit's aggregate
-- project name — a per-plant carve-out), and load_zone (replaces the
-- unit's map-derived project load zone; must use the study's load-zone
-- vocabulary). The reason column is free text, for documenting the
-- evidence.
DROP TABLE IF EXISTS user_defined_unit_overrides;
CREATE TABLE user_defined_unit_overrides
(
    plant_id_eia INTEGER,
    generator_id TEXT,
    include      INTEGER,
    aggregation  TEXT,
    load_zone    TEXT,
    reason       TEXT,
    PRIMARY KEY (plant_id_eia, generator_id)
);


DROP TABLE IF EXISTS user_defined_eiaaeo_region_key;
CREATE TABLE user_defined_eiaaeo_region_key
(
    electricity_market_module_region_eiaaeo TEXT PRIMARY KEY,
    region                                  TEXT,
    fuel_region                             TEXT
);

-- Maps each project (by its GridPath project name, e.g.
-- <plant_id_eia>__<generator_id>) to the fuel region used to construct its
-- fuel name (<generic_fuel>_<fuel_region>); the fuel-region vocabulary must
-- match user_defined_eiaaeo_region_key's, which defines the fuels' prices
-- and characteristics
DROP TABLE IF EXISTS user_defined_project_fuel_region_key;
CREATE TABLE user_defined_project_fuel_region_key
(
    project     TEXT PRIMARY KEY,
    fuel_region TEXT
);

DROP TABLE IF EXISTS user_defined_eia_gridpath_key;
CREATE TABLE user_defined_eia_gridpath_key
(
    prime_mover_code                 TEXT,
    prime_mover_label                TEXT,
    energy_source_code               TEXT,
    energy_source_label              TEXT,
    fuel_type_eiaaeo                 TEXT,
    gridpath_generic_fuel            TEXT,
    aeo_prices                       INTEGER,
    gridpath_capacity_type           TEXT,
    gridpath_operational_type        TEXT,
    gridpath_technology              TEXT,
    gridpath_balancing_type          TEXT,
    default_variable_om_cost_per_mwh FLOAT,
    default_storage_efficiency       FLOAT,
    default_charging_efficiency      FLOAT,
    default_discharging_efficiency   FLOAT,
    heat_rate_mmbtu_per_mwh          FLOAT,
    min_load_fraction                FLOAT,
    heat_rate_source                 TEXT,
    agg_project                      TEXT,
    PRIMARY KEY (prime_mover_code, energy_source_code)
);


DROP TABLE IF EXISTS user_defined_heat_rate_curve;
CREATE TABLE user_defined_heat_rate_curve
(
    load_point_fraction           FLOAT PRIMARY KEY,
    average_heat_rate_coefficient FLOAT
);

DROP TABLE IF EXISTS user_defined_generic_fuel_intensities;
CREATE TABLE user_defined_generic_fuel_intensities
(
    gridpath_generic_fuel                    TEXT PRIMARY KEY,
    co2_intensity_emissionsunit_per_fuelunit FLOAT,
    units                                    TEXT,
    source                                   TEXT
);
