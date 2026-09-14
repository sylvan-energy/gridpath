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

-- The GridPath RA Toolkit's raw-data database schema: the historical
-- weather-dependent timeseries (load, variable generation, availability),
-- hydro conditions, unit availability parameters, and the user-defined
-- mappings and weather bins the RA Toolkit steps work from, plus the
-- auxiliary tables the Monte Carlo weather-draw steps write. This is a
-- SEPARATE database from the GridPath Data Toolkit's raw database
-- (data_toolkit/raw_data_db_schema.sql): create it with
-- gridpath_create_database --db_schema pointing at this file and load it
-- with the RA Toolkit's own load_raw_data step.

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

DROP TABLE IF EXISTS raw_data_system_load;
CREATE TABLE raw_data_system_load
(
    year         INTEGER,
    month        INTEGER,
    day_of_month INTEGER,
    day_type     INTEGER,
    hour_of_day  INTEGER,
    unit         VARCHAR(64),
    value        FLOAT,
    PRIMARY KEY (year, month, day_of_month, hour_of_day, unit)
);

DROP TABLE IF EXISTS raw_data_var_profiles;
CREATE TABLE raw_data_var_profiles
(
    year         INTEGER,
    month        INTEGER,
    day_of_month INTEGER,
    day_type     INTEGER,
    hour_of_day  INTEGER,
    unit         VARCHAR(64),
    value        FLOAT,
    PRIMARY KEY (year, month, day_of_month, hour_of_day, unit)
);

DROP TABLE IF EXISTS raw_data_availability_profiles;
CREATE TABLE raw_data_availability_profiles
(
    year         INTEGER,
    month        INTEGER,
    day_of_month INTEGER,
    day_type     INTEGER,
    hour_of_day  INTEGER,
    unit         VARCHAR(64),
    value        FLOAT,
    PRIMARY KEY (year, month, day_of_month, hour_of_day, unit)
);

DROP TABLE IF EXISTS raw_data_project_hydro_opchars_by_year_month;
CREATE TABLE raw_data_project_hydro_opchars_by_year_month
(
    project                VARCHAR(64),
    hydro_year             INTEGER,
    month                  INTEGER,
    average_power_fraction FLOAT,
    min_power_fraction     FLOAT,
    max_power_fraction     FLOAT,
    PRIMARY KEY (project, hydro_year, month)
);

DROP TABLE IF EXISTS raw_data_var_project_units;
CREATE TABLE raw_data_var_project_units
(
    unit            VARCHAR(32),
    project         VARCHAR(32),
    unit_weight     FLOAT,
    timeseries_name VARCHAR(32),
    PRIMARY KEY (unit, project)
);

DROP TABLE IF EXISTS raw_data_hydro_years;
CREATE TABLE raw_data_hydro_years
(
    year      INTEGER,
    month     INTEGER,
    hydro_bin INTEGER,
    PRIMARY KEY (year, month)
);

DROP TABLE IF EXISTS raw_data_unit_availability_params;
CREATE TABLE raw_data_unit_availability_params
(
    unit            TEXT PRIMARY KEY,
    project         TEXT,
    unit_weight     DECIMAL,
    n_units         INTEGER,
    unit_fo_model   TEXT,
    unit_for        DECIMAL,
    unit_mttr       DECIMAL,
    timeseries_name VARCHAR(32),
    hybrid_stor     INTEGER
);

--------------------------------------------------------------------------------
-- Auxiliary user-defined data (maps, etc.)
--------------------------------------------------------------------------------

DROP TABLE IF EXISTS user_defined_load_zone_units;
CREATE TABLE user_defined_load_zone_units
(
    unit            TEXT,
    load_zone       TEXT,
    unit_weight     DECIMAL,
    timeseries_name VARCHAR(32),
    PRIMARY KEY (unit, load_zone)
);

DROP TABLE IF EXISTS user_defined_balancing_type_horizons;
CREATE TABLE user_defined_balancing_type_horizons
(
    balancing_type            VARCHAR(32),
    horizon                   INTEGER,
    hour_ending_of_year_start INTEGER,
    hour_ending_of_year_end   INTEGER,
    PRIMARY KEY (balancing_type, horizon)
);

DROP TABLE IF EXISTS user_defined_weather_bins;
CREATE TABLE user_defined_weather_bins
(
    weather_bins_id INTEGER,
    year            INTEGER,
    month           INTEGER,
    day_of_month    INTEGER,
    day_type        INTEGER,
    weather_bin     INTEGER,
    PRIMARY KEY (weather_bins_id, year, month, day_of_month, day_type)
);

DROP TABLE IF EXISTS user_defined_data_availability;
CREATE TABLE user_defined_data_availability
(
    timeseries_name VARCHAR(32),
    year            INTEGER,
    PRIMARY KEY (timeseries_name, year)
);

DROP TABLE IF EXISTS user_defined_monte_carlo_timeseries;
CREATE TABLE user_defined_monte_carlo_timeseries
(
    timeseries_name    VARCHAR(32),
    consider_day_types INTEGER,
    timeseries_type    VARCHAR(32) CHECK (
        timeseries_type IN ('load', 'var_profiles', 'availability')
        ),
    initial_seed       INTEGER,
    PRIMARY KEY (timeseries_name)
);

--------------------------------------------------------------------------------
-- Auxiliary tables written by the Monte Carlo weather-draw steps
--------------------------------------------------------------------------------

DROP TABLE IF EXISTS aux_weather_draws_info;
CREATE TABLE aux_weather_draws_info
(
    weather_bins_id  INTEGER,
    weather_draws_id INTEGER,
    seed             INTEGER,
    n_iterations     INTEGER,
    PRIMARY KEY (weather_bins_id, weather_draws_id)
);

DROP TABLE IF EXISTS aux_weather_iterations;
CREATE TABLE aux_weather_iterations
(
    weather_bins_id   INTEGER,
    weather_draws_id  INTEGER,
    weather_iteration INTEGER,
    draw_number       INTEGER,
    study_date        DATE,
    month             INTEGER,
    day_type          INTEGER,
    weather_day_bin   INTEGER,
    PRIMARY KEY (weather_bins_id, weather_draws_id,
                 weather_iteration, draw_number,
                 month, day_type, weather_day_bin)
);

CREATE INDEX idx_draws_it_n
    ON aux_weather_iterations (weather_draws_id, weather_iteration,
                               draw_number);
