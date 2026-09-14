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
    energy_storage_capacity_mwh              REAL,
    prime_mover_code                         TEXT,
    energy_source_code_1                     TEXT,
    current_planned_generator_operating_date DATETIME,
    generator_retirement_date                DATETIME,
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

--------------------------------------------------------------------------------
-- Auxiliary user-defined data (maps, etc.)
--------------------------------------------------------------------------------


DROP TABLE IF EXISTS user_defined_eiaaeo_region_key;
CREATE TABLE user_defined_eiaaeo_region_key
(
    electricity_market_module_region_eiaaeo TEXT PRIMARY KEY,
    region                                  TEXT,
    fuel_region                             TEXT
);

DROP TABLE IF EXISTS user_defined_baa_key;
CREATE TABLE user_defined_baa_key
(
    baa         TEXT PRIMARY KEY,
    region      TEXT,
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
