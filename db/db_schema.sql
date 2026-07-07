-- noinspection SqlNoDataSourceInspectionForFile

-- Copyright 2016-2024 Blue Marble Analytics LLC.
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

-- A description of the database schema structure is in db.__init__

-----------------
-- -- MODEL -- --
-----------------

-- Implemented horizon boundary types
DROP TABLE IF EXISTS mod_horizon_boundary_types;
CREATE TABLE mod_horizon_boundary_types
(
    horizon_boundary_type VARCHAR(16) PRIMARY KEY,
    description           VARCHAR(128)
);

-- Months
DROP TABLE IF EXISTS mod_months;
CREATE TABLE mod_months
(
    month       INTEGER PRIMARY KEY,
    description VARCHAR(16)
);

-- Implemented capacity types
DROP TABLE IF EXISTS mod_capacity_types;
CREATE TABLE mod_capacity_types
(
    capacity_type VARCHAR(32) PRIMARY KEY,
    description   VARCHAR(128)
);

-- Implemented availability types
DROP TABLE IF EXISTS mod_availability_types;
CREATE TABLE mod_availability_types
(
    availability_type VARCHAR(32) PRIMARY KEY,
    description       VARCHAR(128)
);

-- Implemented operational types
DROP TABLE IF EXISTS mod_operational_types;
CREATE TABLE mod_operational_types
(
    operational_type VARCHAR(32) PRIMARY KEY,
    description      VARCHAR(128)
);

-- Implemented reserve types
DROP TABLE IF EXISTS mod_reserve_types;
CREATE TABLE mod_reserve_types
(
    reserve_type VARCHAR(32) PRIMARY KEY,
    description  VARCHAR(128)
);

-- Implemented transmission operational types
DROP TABLE IF EXISTS mod_tx_operational_types;
CREATE TABLE mod_tx_operational_types
(
    operational_type VARCHAR(32) PRIMARY KEY,
    description      VARCHAR(128)
);

-- Implemented transmission capacity types
DROP TABLE IF EXISTS mod_tx_capacity_types;
CREATE TABLE mod_tx_capacity_types
(
    capacity_type VARCHAR(32) PRIMARY KEY,
    description   VARCHAR(128)
);

-- Implemented transmission availability types
DROP TABLE IF EXISTS mod_tx_availability_types;
CREATE TABLE mod_tx_availability_types
(
    availability_type VARCHAR(32) PRIMARY KEY,
    description       VARCHAR(128)
);

-- Implemented prm types
DROP TABLE IF EXISTS mod_prm_types;
CREATE TABLE mod_prm_types
(
    prm_type    VARCHAR(32) PRIMARY KEY,
    description VARCHAR(128)
);

-- Invalid combinations of capacity type and operational type
DROP TABLE IF EXISTS mod_capacity_and_operational_type_invalid_combos;
CREATE TABLE mod_capacity_and_operational_type_invalid_combos
(
    capacity_type    VARCHAR(32),
    operational_type VARCHAR(32),
    PRIMARY KEY (capacity_type, operational_type),
    FOREIGN KEY (capacity_type) REFERENCES mod_capacity_types (capacity_type),
    FOREIGN KEY (operational_type) REFERENCES mod_operational_types
        (operational_type)
);

-- Invalid combinations of tx capacity type and tx operational type
DROP TABLE IF EXISTS mod_tx_capacity_and_tx_operational_type_invalid_combos;
CREATE TABLE mod_tx_capacity_and_tx_operational_type_invalid_combos
(
    capacity_type    VARCHAR(32),
    operational_type VARCHAR(32),
    PRIMARY KEY (capacity_type, operational_type),
    FOREIGN KEY (capacity_type) REFERENCES mod_tx_capacity_types (capacity_type),
    FOREIGN KEY (operational_type) REFERENCES mod_tx_operational_types
        (operational_type)
);

DROP TABLE IF EXISTS mod_feature_subscenarios;
CREATE TABLE mod_feature_subscenarios
(
    feature        VARCHAR(32),
    subscenario_id VARCHAR(32),
    PRIMARY KEY (feature, subscenario_id),
    FOREIGN KEY (feature) REFERENCES mod_features (feature)
);

-- Features
DROP TABLE IF EXISTS mod_features;
CREATE TABLE mod_features
(
    feature     VARCHAR(32) PRIMARY KEY,
    description VARCHAR(128)
);

-- Scenario validation status types
DROP TABLE IF EXISTS mod_validation_status_types;
CREATE TABLE mod_validation_status_types
(
    validation_status_id   INTEGER PRIMARY KEY,
    validation_status_name VARCHAR(32) UNIQUE
);

-- Units of measurements and their abbreviations
-- Core units will be populated with defaults but can be changed by the user
-- Secondary units are derived from the core units
DROP TABLE IF EXISTS mod_units;
CREATE TABLE mod_units
(
    metric                 VARCHAR(32) PRIMARY KEY,
    type                   VARCHAR(32), -- 'core' or 'secondary'
    numerator_core_units   VARCHAR(32),
    denominator_core_units VARCHAR(32),
    unit                   VARCHAR(32), -- this will be derived for secondary units
    description            VARCHAR(128)
);

-- Run status types
DROP TABLE IF EXISTS mod_run_status_types;
CREATE TABLE mod_run_status_types
(
    run_status_id   INTEGER PRIMARY KEY,
    run_status_name VARCHAR(32) UNIQUE
);


--------------------
-- -- STATUS -- --
--------------------

-- Validation Results
DROP TABLE IF EXISTS status_validation;
CREATE TABLE status_validation
(
    scenario_id     INTEGER,
    subproblem_id   INTEGER,
    stage_id        INTEGER,
    gridpath_module VARCHAR(64),
    db_table        VARCHAR(64),
    severity        VARCHAR(32),
    description     VARCHAR(64),
    time_stamp      TEXT, -- ISO8601 String
    FOREIGN KEY (scenario_id) REFERENCES scenarios (scenario_id)
);

-- Scenario results: objective function, solver status
DROP TABLE IF EXISTS results_scenario;
CREATE TABLE results_scenario
(
    scenario_id                  INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    objective_function_value     FLOAT,
    solver_termination_condition VARCHAR(128),
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id,
                 stage_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios (scenario_id)
);


-------------------------------------------------------------------------------
---- SUBSCENARIOS AND INPUTS -----
-------------------------------------------------------------------------------

--------------------
-- -- TEMPORAL -- --
--------------------

-- Temporal Scenarios
DROP TABLE IF EXISTS subscenarios_temporal;
CREATE TABLE subscenarios_temporal
(
    temporal_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 VARCHAR(32),
    description          VARCHAR(128)
);


-- Weather, hydro, and availability iterations
DROP TABLE IF EXISTS inputs_temporal_iterations;
CREATE TABLE inputs_temporal_iterations
(
    temporal_scenario_id   INTEGER,
    weather_iteration      INTEGER NOT NULL,
    hydro_iteration        INTEGER NOT NULL,
    availability_iteration INTEGER NOT NULL,
    PRIMARY KEY (temporal_scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration,
                 availability_iteration),
    FOREIGN KEY (temporal_scenario_id) REFERENCES subscenarios_temporal
        (temporal_scenario_id)
);

-- Subproblems
DROP TABLE IF EXISTS inputs_temporal_subproblems;
CREATE TABLE inputs_temporal_subproblems
(
    temporal_scenario_id INTEGER,
    subproblem_id        INTEGER NOT NULL,
    PRIMARY KEY (temporal_scenario_id, subproblem_id),
    FOREIGN KEY (temporal_scenario_id) REFERENCES subscenarios_temporal
        (temporal_scenario_id)
);

-- Stages (within subproblems)
DROP TABLE IF EXISTS inputs_temporal_subproblems_stages;
CREATE TABLE inputs_temporal_subproblems_stages
(
    temporal_scenario_id INTEGER,
    subproblem_id        INTEGER NOT NULL,
    stage_id             INTEGER NOT NULL,
    PRIMARY KEY (temporal_scenario_id, subproblem_id, stage_id),
    FOREIGN KEY (temporal_scenario_id) REFERENCES subscenarios_temporal
        (temporal_scenario_id),
    -- Make sure subproblem exists in this temporal_scenario_id
    FOREIGN KEY (temporal_scenario_id, subproblem_id) REFERENCES
        inputs_temporal_subproblems (temporal_scenario_id, subproblem_id)
);

-- Periods
-- These have to be the same for each subproblem
DROP TABLE IF EXISTS inputs_temporal_periods;
CREATE TABLE inputs_temporal_periods
(
    temporal_scenario_id INTEGER,
    period               INTEGER,
    discount_factor      FLOAT,
    period_start_year    FLOAT,
    period_end_year      FLOAT, -- exclusive, i.e. if 2030, last day is 2029-12-31
    prev_period          INTEGER,
    PRIMARY KEY (temporal_scenario_id, period),
    FOREIGN KEY (temporal_scenario_id) REFERENCES subscenarios_temporal
        (temporal_scenario_id)
);

-- Superperiods (combinations of periods)
DROP TABLE IF EXISTS inputs_temporal_superperiods;
CREATE TABLE inputs_temporal_superperiods
(
    temporal_scenario_id INTEGER,
    superperiod          INTEGER,
    period               INTEGER,
    PRIMARY KEY (temporal_scenario_id, superperiod, period),
    FOREIGN KEY (temporal_scenario_id) REFERENCES subscenarios_temporal
        (temporal_scenario_id)
);

-- Timepoints
-- Note on linked timepoints: the user can designate timepoints from the last
-- horizon of the subproblem to be linked to the first horizon of the next
-- subproblem -- it is up to the user to ensure that only the last horizon
-- of a subproblem and the first horizon of the next subproblem are linked
-- like this
-- Linked timepoints should be non-positive integers, ordered, and the most
-- recent linked timepoint should be 0, i.e. the linked timepoint indexed 0
-- will be the previous timepoint for the first timepoint of the first
-- horizon of the next subproblem. The previous timepoint for linked
-- timepoint 0 will be -1, and so on.
-- If linked timepoints are specified for a subproblem, GP will use those as
-- the previous timepoints for the first horizon of the next subproblem
-- (subproblem_id + 1) BUT ONLY IF the first horizon of the next subproblem has
-- a 'linked' boundary
-- The spinup_or_lookahead is not NULL, as we rely on 0s downstream
-- There is a unique key on timepoint/spinup_or_lookahead, as some functionality
--  requires unique timepoint IDs, but we want to allow for the same
--  timepoint IDs to be duplicated if they are spinup/lookahead timepoints
DROP TABLE IF EXISTS inputs_temporal;
CREATE TABLE inputs_temporal
(
    temporal_scenario_id         INTEGER,
    subproblem_id                INTEGER NOT NULL,
    stage_id                     INTEGER NOT NULL,
    timepoint                    INTEGER NOT NULL,
    period                       INTEGER NOT NULL,
    number_of_hours_in_timepoint INTEGER NOT NULL,
    timepoint_weight             FLOAT   NOT NULL,
    previous_stage_timepoint_map INTEGER,
    spinup_or_lookahead          INTEGER NOT NULL,
    linked_timepoint             INTEGER, -- should be non-positive
    year                         INTEGER,
    month                        INTEGER,
    day_of_month                 INTEGER,
    hour_of_day                  FLOAT,   -- FLOAT to accommodate subhourly timepoints
    timestamp                    DATETIME,
    PRIMARY KEY (temporal_scenario_id, subproblem_id, stage_id, timepoint),
    UNIQUE (temporal_scenario_id, stage_id, timepoint, spinup_or_lookahead),
    FOREIGN KEY (temporal_scenario_id) REFERENCES subscenarios_temporal
        (temporal_scenario_id),
    -- Make sure period exists in this temporal_scenario_id
    FOREIGN KEY (temporal_scenario_id, period)
        REFERENCES inputs_temporal_periods (temporal_scenario_id, period),
    -- Month must be 1-12
    FOREIGN KEY (month) REFERENCES mod_months (month)
);

-- Composite index for temporal lookups
CREATE INDEX idx_temporal_scenario_subproblem_stage
    ON inputs_temporal (temporal_scenario_id, subproblem_id, stage_id,
                        timepoint);


-- Horizons (with balancing types)
-- How timepoints are organized for operational-decision purposes
-- Each timepoint can belong to more than one balancing_type-horizon (e.g.
-- it can be on day 1 of the year, in week 1 of the year, in month 1 of the
-- year, etc.)
-- The balancing_type-horizons can be different by subproblem (e.g. one
-- subproblem can be a week and have days as horizons and another one
-- can be a week and have the week as horizon), but will have to be same for
-- each stage of a subproblem
-- Balancing_type-horizons within
DROP TABLE IF EXISTS inputs_temporal_horizons;
CREATE TABLE inputs_temporal_horizons
(
    temporal_scenario_id   INTEGER     NOT NULL,
    balancing_type_horizon VARCHAR(32) NOT NULL,
    horizon                INTEGER     NOT NULL,
    boundary               VARCHAR(16) NOT NULL,
    PRIMARY KEY (temporal_scenario_id, balancing_type_horizon, horizon),
    FOREIGN KEY (temporal_scenario_id) REFERENCES subscenarios_temporal
        (temporal_scenario_id),
    -- Make sure boundary type is correct
    FOREIGN KEY (boundary) REFERENCES mod_horizon_boundary_types
        (horizon_boundary_type)
);


-- This table is auxiliary for 1) readability and 2) populating the
-- inputs_temporal_horizon_timepoints table if we're using the CSV-to-DB
-- functionality
DROP TABLE IF EXISTS inputs_temporal_horizon_timepoints_start_end;
CREATE TABLE inputs_temporal_horizon_timepoints_start_end
(
    temporal_scenario_id          INTEGER     NOT NULL,
    stage_id                      INTEGER     NOT NULL,
    balancing_type_horizon        VARCHAR(32) NOT NULL,
    horizon                       INTEGER     NOT NULL,
    tmp_start                     INTEGER     NOT NULL,
    tmp_start_spinup_or_lookahead INTEGER     NOT NULL DEFAULT 0,
    tmp_end                       INTEGER     NOT NULL,
    tmp_end_spinup_or_lookahead   INTEGER     NOT NULL DEFAULT 0,
    PRIMARY KEY (temporal_scenario_id, stage_id, balancing_type_horizon,
                 horizon, tmp_start, tmp_start_spinup_or_lookahead,
                 tmp_end, tmp_end_spinup_or_lookahead),
    FOREIGN KEY (temporal_scenario_id) REFERENCES subscenarios_temporal
        (temporal_scenario_id),
    -- Make sure we have the right balancing_type-horizons
    FOREIGN KEY (temporal_scenario_id, balancing_type_horizon, horizon)
        REFERENCES inputs_temporal_horizons (temporal_scenario_id,
                                             balancing_type_horizon, horizon),
    -- Make sure the start and end timepoints exist in the main timepoints table
    FOREIGN KEY (temporal_scenario_id, stage_id, tmp_start,
                 tmp_start_spinup_or_lookahead)
        REFERENCES inputs_temporal (temporal_scenario_id, stage_id, timepoint,
                                    spinup_or_lookahead),
    FOREIGN KEY (temporal_scenario_id, stage_id, tmp_end,
                 tmp_end_spinup_or_lookahead)
        REFERENCES inputs_temporal (temporal_scenario_id, stage_id, timepoint,
                                    spinup_or_lookahead)
);

-- This table is what GridPath uses to get inputs
DROP TABLE IF EXISTS inputs_temporal_horizon_timepoints;
CREATE TABLE inputs_temporal_horizon_timepoints
(
    temporal_scenario_id   INTEGER     NOT NULL,
    subproblem_id          INTEGER     NOT NULL,
    stage_id               INTEGER     NOT NULL,
    timepoint              INTEGER     NOT NULL,
    balancing_type_horizon VARCHAR(32) NOT NULL,
    horizon                INTEGER     NOT NULL,
    PRIMARY KEY (temporal_scenario_id, subproblem_id, stage_id, timepoint,
                 balancing_type_horizon, horizon),
    FOREIGN KEY (temporal_scenario_id)
        REFERENCES subscenarios_temporal (temporal_scenario_id),
    -- Make sure these are the same timepoints as in the main timepoints table
    FOREIGN KEY (temporal_scenario_id, subproblem_id, stage_id, timepoint)
        REFERENCES inputs_temporal (temporal_scenario_id,
                                    subproblem_id, stage_id, timepoint),
    -- Make sure horizons exist in this temporal_scenario_id and subproblem_id
    FOREIGN KEY (temporal_scenario_id, balancing_type_horizon, horizon)
        REFERENCES inputs_temporal_horizons (temporal_scenario_id,
                                             balancing_type_horizon, horizon)
);

-- Index for horizon timepoints lookups
CREATE INDEX idx_horizon_temporal_scenario_subproblem_stage
    ON inputs_temporal_horizon_timepoints (temporal_scenario_id, subproblem_id, stage_id);


---------------------
-- -- GEOGRAPHY -- --
---------------------

-- Load zones
-- This is the unit at which load is met in the model
-- This table defines the load zone "portfolio"
DROP TABLE IF EXISTS subscenarios_geography_load_zones;
CREATE TABLE subscenarios_geography_load_zones
(
    load_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  VARCHAR(32),
    description           VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_load_zones;
CREATE TABLE inputs_geography_load_zones
(
    load_zone_scenario_id INTEGER,
    load_zone             VARCHAR(32),
    PRIMARY KEY (load_zone_scenario_id, load_zone),
    FOREIGN KEY (load_zone_scenario_id) REFERENCES
        subscenarios_geography_load_zones (load_zone_scenario_id)
);

-- Load balance
-- This table defines various load balance parameters for each load zone (e.g.,
-- if unserved energy is allowed, at what cost, etc.)
DROP TABLE IF EXISTS subscenarios_geography_load_balance;
CREATE TABLE subscenarios_geography_load_balance
(
    load_balance_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     VARCHAR(32),
    description              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_load_balance;
CREATE TABLE inputs_geography_load_balance
(
    load_balance_scenario_id            INTEGER,
    load_zone                           VARCHAR(32),
    allow_overgeneration                INTEGER,
    overgeneration_penalty_per_mw       FLOAT,
    allow_unserved_energy               INTEGER,
    unserved_energy_penalty_per_mwh     FLOAT,
    unserved_energy_limit_mwh           FLOAT, -- limit on the total USE
    max_unserved_load_penalty_per_mw    FLOAT,
    max_unserved_load_limit_mw          FLOAT, -- limit on the max unserved load
    avg_unserved_load_penalty_per_mwa   FLOAT,
    export_penalty_cost_per_mwh         FLOAT,
    unserved_energy_stats_threshold_mw  FLOAT, -- defaults to 0
    PRIMARY KEY (load_balance_scenario_id, load_zone),
    FOREIGN KEY (load_balance_scenario_id) REFERENCES
        subscenarios_geography_load_balance (load_balance_scenario_id)
);


-- Reserves
-- This is the unit at which reserves are met at the model; it can be
-- different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_lf_reserves_up_bas;
CREATE TABLE subscenarios_geography_lf_reserves_up_bas
(
    lf_reserves_up_ba_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                          VARCHAR(32),
    description                   VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_lf_reserves_up_bas;
CREATE TABLE inputs_geography_lf_reserves_up_bas
(
    lf_reserves_up_ba_scenario_id INTEGER,
    lf_reserves_up_ba             VARCHAR(32),
    allow_violation               INTEGER,
    violation_penalty_per_mw      FLOAT,
    reserve_to_energy_adjustment  FLOAT,
    PRIMARY KEY (lf_reserves_up_ba_scenario_id, lf_reserves_up_ba),
    FOREIGN KEY (lf_reserves_up_ba_scenario_id) REFERENCES
        subscenarios_geography_lf_reserves_up_bas (lf_reserves_up_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_geography_lf_reserves_down_bas;
CREATE TABLE subscenarios_geography_lf_reserves_down_bas
(
    lf_reserves_down_ba_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                            VARCHAR(32),
    description                     VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_lf_reserves_down_bas;
CREATE TABLE inputs_geography_lf_reserves_down_bas
(
    lf_reserves_down_ba_scenario_id INTEGER,
    lf_reserves_down_ba             VARCHAR(32),
    allow_violation                 INTEGER,
    violation_penalty_per_mw        FLOAT,
    reserve_to_energy_adjustment    FLOAT,
    PRIMARY KEY (lf_reserves_down_ba_scenario_id, lf_reserves_down_ba),
    FOREIGN KEY (lf_reserves_down_ba_scenario_id) REFERENCES
        subscenarios_geography_lf_reserves_down_bas (lf_reserves_down_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_geography_regulation_up_bas;
CREATE TABLE subscenarios_geography_regulation_up_bas
(
    regulation_up_ba_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                         VARCHAR(32),
    description                  VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_regulation_up_bas;
CREATE TABLE inputs_geography_regulation_up_bas
(
    regulation_up_ba_scenario_id INTEGER,
    regulation_up_ba             VARCHAR(32),
    allow_violation              INTEGER,
    violation_penalty_per_mw     FLOAT,
    reserve_to_energy_adjustment FLOAT,
    PRIMARY KEY (regulation_up_ba_scenario_id, regulation_up_ba),
    FOREIGN KEY (regulation_up_ba_scenario_id) REFERENCES
        subscenarios_geography_regulation_up_bas (regulation_up_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_geography_regulation_down_bas;
CREATE TABLE subscenarios_geography_regulation_down_bas
(
    regulation_down_ba_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                           VARCHAR(32),
    description                    VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_regulation_down_bas;
CREATE TABLE inputs_geography_regulation_down_bas
(
    regulation_down_ba_scenario_id INTEGER,
    regulation_down_ba             VARCHAR(32),
    allow_violation                INTEGER,
    violation_penalty_per_mw       FLOAT,
    reserve_to_energy_adjustment   FLOAT,
    PRIMARY KEY (regulation_down_ba_scenario_id, regulation_down_ba),
    FOREIGN KEY (regulation_down_ba_scenario_id) REFERENCES
        subscenarios_geography_regulation_down_bas (regulation_down_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_geography_frequency_response_bas;
CREATE TABLE subscenarios_geography_frequency_response_bas
(
    frequency_response_ba_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                              VARCHAR(32),
    description                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_frequency_response_bas;
CREATE TABLE inputs_geography_frequency_response_bas
(
    frequency_response_ba_scenario_id INTEGER,
    frequency_response_ba             VARCHAR(32),
    allow_violation                   INTEGER,
    violation_penalty_per_mw          FLOAT,
    reserve_to_energy_adjustment      FLOAT,
    PRIMARY KEY (frequency_response_ba_scenario_id, frequency_response_ba),
    FOREIGN KEY (frequency_response_ba_scenario_id) REFERENCES
        subscenarios_geography_frequency_response_bas
            (frequency_response_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_geography_spinning_reserves_bas;
CREATE TABLE subscenarios_geography_spinning_reserves_bas
(
    spinning_reserves_ba_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                             VARCHAR(32),
    description                      VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_spinning_reserves_bas;
CREATE TABLE inputs_geography_spinning_reserves_bas
(
    spinning_reserves_ba_scenario_id INTEGER,
    spinning_reserves_ba             VARCHAR(32),
    allow_violation                  INTEGER,
    violation_penalty_per_mw         FLOAT,
    reserve_to_energy_adjustment     FLOAT,
    PRIMARY KEY (spinning_reserves_ba_scenario_id, spinning_reserves_ba),
    FOREIGN KEY (spinning_reserves_ba_scenario_id) REFERENCES
        subscenarios_geography_spinning_reserves_bas (spinning_reserves_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_geography_inertia_reserves_bas;
CREATE TABLE subscenarios_geography_inertia_reserves_bas
(
    inertia_reserves_ba_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                            VARCHAR(32),
    description                     VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_inertia_reserves_bas;
CREATE TABLE inputs_geography_inertia_reserves_bas
(
    inertia_reserves_ba_scenario_id INTEGER,
    inertia_reserves_ba             VARCHAR(32),
    allow_violation                 INTEGER,
    violation_penalty_per_mws       FLOAT,
    PRIMARY KEY (inertia_reserves_ba_scenario_id, inertia_reserves_ba),
    FOREIGN KEY (inertia_reserves_ba_scenario_id) REFERENCES
        subscenarios_geography_inertia_reserves_bas (inertia_reserves_ba_scenario_id)
);

-- Energy target
-- This is the unit at which energy target requirements are met in the model; it can be
-- different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_energy_target_zones;
CREATE TABLE subscenarios_geography_energy_target_zones
(
    energy_target_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                           VARCHAR(32),
    description                    VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_energy_target_zones;
CREATE TABLE inputs_geography_energy_target_zones
(
    energy_target_zone_scenario_id INTEGER,
    energy_target_zone             VARCHAR(32),
    allow_violation                INTEGER DEFAULT 0, -- constraint is hard by default
    violation_penalty_per_mwh      FLOAT   DEFAULT 0,
    PRIMARY KEY (energy_target_zone_scenario_id, energy_target_zone),
    FOREIGN KEY (energy_target_zone_scenario_id) REFERENCES
        subscenarios_geography_energy_target_zones (energy_target_zone_scenario_id)
);

-- Instantaneous penetration

DROP TABLE IF EXISTS subscenarios_geography_instantaneous_penetration_zones;
CREATE TABLE subscenarios_geography_instantaneous_penetration_zones
(
    instantaneous_penetration_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                       VARCHAR(32),
    description                                VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_instantaneous_penetration_zones;
CREATE TABLE inputs_geography_instantaneous_penetration_zones
(
    instantaneous_penetration_zone_scenario_id INTEGER,
    instantaneous_penetration_zone             VARCHAR(32),
    allow_violation_min_penetration            INTEGER DEFAULT 0, -- constraint is hard by default
    violation_penalty_min_penetration_per_mwh  FLOAT   DEFAULT 0,
    allow_violation_max_penetration            INTEGER DEFAULT 0, -- constraint is hard by default
    violation_penalty_max_penetration_per_mwh  FLOAT   DEFAULT 0,
    PRIMARY KEY (instantaneous_penetration_zone_scenario_id,
                 instantaneous_penetration_zone),
    FOREIGN KEY (instantaneous_penetration_zone_scenario_id) REFERENCES
        subscenarios_geography_instantaneous_penetration_zones (instantaneous_penetration_zone_scenario_id)
);

-- Transmission target
-- This is the unit at which transmission target requirements are met in the model; it can be
-- different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_transmission_target_zones;
CREATE TABLE subscenarios_geography_transmission_target_zones
(
    transmission_target_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                 VARCHAR(32),
    description                          VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_transmission_target_zones;
CREATE TABLE inputs_geography_transmission_target_zones
(
    transmission_target_zone_scenario_id INTEGER,
    transmission_target_zone             VARCHAR(32),
    allow_violation                      INTEGER DEFAULT 0, -- constraint is hard by default
    violation_penalty_per_mwh            FLOAT   DEFAULT 0,
    PRIMARY KEY (transmission_target_zone_scenario_id,
                 transmission_target_zone),
    FOREIGN KEY (transmission_target_zone_scenario_id) REFERENCES
        subscenarios_geography_transmission_target_zones (transmission_target_zone_scenario_id)
);

-- Carbon cap
-- This is the unit at which the carbon cap is applied in the model; it can be
-- different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_carbon_cap_zones;
CREATE TABLE subscenarios_geography_carbon_cap_zones
(
    carbon_cap_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        VARCHAR(32),
    description                 VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_carbon_cap_zones;
CREATE TABLE inputs_geography_carbon_cap_zones
(
    carbon_cap_zone_scenario_id    INTEGER,
    carbon_cap_zone                VARCHAR(32),
    allow_violation                INTEGER DEFAULT 0, -- constraint is hard by default
    violation_penalty_per_emission FLOAT   DEFAULT 0,
    PRIMARY KEY (carbon_cap_zone_scenario_id, carbon_cap_zone),
    FOREIGN KEY (carbon_cap_zone_scenario_id) REFERENCES
        subscenarios_geography_carbon_cap_zones (carbon_cap_zone_scenario_id)
);

-- Carbon tax
-- This is the unit at which the carbon tax is applied in the model; it can be
-- different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_carbon_tax_zones;
CREATE TABLE subscenarios_geography_carbon_tax_zones
(
    carbon_tax_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        VARCHAR(32),
    description                 VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_carbon_tax_zones;
CREATE TABLE inputs_geography_carbon_tax_zones
(
    carbon_tax_zone_scenario_id INTEGER,
    carbon_tax_zone             VARCHAR(32),
    PRIMARY KEY (carbon_tax_zone_scenario_id, carbon_tax_zone),
    FOREIGN KEY (carbon_tax_zone_scenario_id) REFERENCES
        subscenarios_geography_carbon_tax_zones (carbon_tax_zone_scenario_id)
);

-- Performance standard
-- This is the unit at which the performance standard is applied in the model; it can be
-- different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_performance_standard_zones;
CREATE TABLE subscenarios_geography_performance_standard_zones
(
    performance_standard_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                  VARCHAR(32),
    description                           VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_performance_standard_zones;
CREATE TABLE inputs_geography_performance_standard_zones
(
    performance_standard_zone_scenario_id INTEGER,
    performance_standard_zone             VARCHAR(32),
    energy_allow_violation                INTEGER DEFAULT 0, -- constraint is hard by default
    energy_violation_penalty_per_emission FLOAT   DEFAULT 0,
    power_allow_violation                 INTEGER DEFAULT 0, -- constraint is hard by default
    power_violation_penalty_per_emission  FLOAT   DEFAULT 0,
    PRIMARY KEY (performance_standard_zone_scenario_id,
                 performance_standard_zone),
    FOREIGN KEY (performance_standard_zone_scenario_id) REFERENCES
        subscenarios_geography_performance_standard_zones (performance_standard_zone_scenario_id)
);

-- Carbon credits
-- This is the unit at which the carbon credits are traded; it can be different
-- from the load zones
DROP TABLE IF EXISTS subscenarios_geography_carbon_credits_zones;
CREATE TABLE subscenarios_geography_carbon_credits_zones
(
    carbon_credits_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                            VARCHAR(32),
    description                     VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_carbon_credits_zones;
CREATE TABLE inputs_geography_carbon_credits_zones
(
    carbon_credits_zone_scenario_id INTEGER,
    carbon_credits_zone             VARCHAR(32),
    PRIMARY KEY (carbon_credits_zone_scenario_id, carbon_credits_zone),
    FOREIGN KEY (carbon_credits_zone_scenario_id) REFERENCES
        subscenarios_geography_carbon_credits_zones (carbon_credits_zone_scenario_id)
);

-- Carbon cap zone <--> carbon credit zone mapping
DROP TABLE IF EXISTS subscenarios_system_carbon_cap_zones_carbon_credits_zones;
CREATE TABLE subscenarios_system_carbon_cap_zones_carbon_credits_zones
(
    carbon_cap_zones_carbon_credits_zones_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                              VARCHAR(32),
    description                                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_carbon_cap_zones_carbon_credits_zones;
CREATE TABLE inputs_system_carbon_cap_zones_carbon_credits_zones
(
    carbon_cap_zones_carbon_credits_zones_scenario_id INTEGER,
    carbon_cap_zone                                   VARCHAR(32),
    carbon_credits_zone                               VARCHAR(32),
    PRIMARY KEY (carbon_cap_zones_carbon_credits_zones_scenario_id,
                 carbon_cap_zone, carbon_credits_zone),
    FOREIGN KEY (carbon_cap_zones_carbon_credits_zones_scenario_id) REFERENCES
        subscenarios_system_carbon_cap_zones_carbon_credits_zones
            (carbon_cap_zones_carbon_credits_zones_scenario_id)
);

-- Performance standard zone <--> carbon credit zone mapping
DROP TABLE IF EXISTS subscenarios_system_performance_standard_zones_carbon_credits_zones;
CREATE TABLE subscenarios_system_performance_standard_zones_carbon_credits_zones
(
    performance_standard_zones_carbon_credits_zones_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                                        VARCHAR(32),
    description                                                 VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_performance_standard_zones_carbon_credits_zones;
CREATE TABLE inputs_system_performance_standard_zones_carbon_credits_zones
(
    performance_standard_zones_carbon_credits_zones_scenario_id INTEGER,
    performance_standard_zone                                   VARCHAR(32),
    carbon_credits_zone                                         VARCHAR(32),
    PRIMARY KEY (performance_standard_zones_carbon_credits_zones_scenario_id,
                 performance_standard_zone, carbon_credits_zone),
    FOREIGN KEY (performance_standard_zones_carbon_credits_zones_scenario_id) REFERENCES
        subscenarios_system_performance_standard_zones_carbon_credits_zones
            (performance_standard_zones_carbon_credits_zones_scenario_id)
);

-- Carbon tax zone <--> carbon credit zone mapping
DROP TABLE IF EXISTS subscenarios_system_carbon_tax_zones_carbon_credits_zones;
CREATE TABLE subscenarios_system_carbon_tax_zones_carbon_credits_zones
(
    carbon_tax_zones_carbon_credits_zones_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                              VARCHAR(32),
    description                                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_carbon_tax_zones_carbon_credits_zones;
CREATE TABLE inputs_system_carbon_tax_zones_carbon_credits_zones
(
    carbon_tax_zones_carbon_credits_zones_scenario_id INTEGER,
    carbon_tax_zone                                   VARCHAR(32),
    carbon_credits_zone                               VARCHAR(32),
    PRIMARY KEY (carbon_tax_zones_carbon_credits_zones_scenario_id,
                 carbon_tax_zone, carbon_credits_zone),
    FOREIGN KEY (carbon_tax_zones_carbon_credits_zones_scenario_id) REFERENCES
        subscenarios_system_carbon_tax_zones_carbon_credits_zones
            (carbon_tax_zones_carbon_credits_zones_scenario_id)
);

-- Carbon credit prices (price at which can sell to other sectors)
DROP TABLE IF EXISTS subscenarios_system_carbon_credits_params;
CREATE TABLE subscenarios_system_carbon_credits_params
(
    carbon_credits_params_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                              VARCHAR(32),
    description                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_carbon_credits_params;
CREATE TABLE inputs_system_carbon_credits_params
(
    carbon_credits_params_scenario_id    INTEGER,
    carbon_credits_zone                  VARCHAR(32),
    period                               INTEGER,
    allow_carbon_credits_infinite_demand INTEGER DEFAULT 0, -- constraint is hard by default
    carbon_credits_demand_tco2           FLOAT,
    carbon_credits_demand_price          FLOAT,
    allow_carbon_credits_infinite_supply INTEGER DEFAULT 0, -- constraint is hard by default
    carbon_credits_supply_tco2           FLOAT,
    carbon_credits_supply_price          FLOAT,
    PRIMARY KEY (carbon_credits_params_scenario_id, carbon_credits_zone,
                 period),
    FOREIGN KEY (carbon_credits_params_scenario_id) REFERENCES
        subscenarios_system_carbon_credits_params (carbon_credits_params_scenario_id)
);

-- Generic policy
-- TODO: add a generic policy list subscenario

-- This is the unit at which the policy is applied in the model
DROP TABLE IF EXISTS subscenarios_geography_policy_zones;
CREATE TABLE subscenarios_geography_policy_zones
(
    policy_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    VARCHAR(32),
    description             VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_policy_zones;
CREATE TABLE inputs_geography_policy_zones
(
    policy_zone_scenario_id    INTEGER,
    policy_name                TEXT,
    policy_zone                TEXT,
    allow_violation            INTEGER DEFAULT 0, -- constraint is hard by default
    violation_penalty_per_unit FLOAT   DEFAULT 0,
    PRIMARY KEY (policy_zone_scenario_id, policy_name, policy_zone),
    FOREIGN KEY (policy_zone_scenario_id) REFERENCES
        subscenarios_geography_policy_zones (policy_zone_scenario_id)
);


-- PRM
-- This is the unit at which PRM requirements are met in the model; it can be
-- different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_prm_zones;
CREATE TABLE subscenarios_geography_prm_zones
(
    prm_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 VARCHAR(32),
    description          VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_prm_zones;
CREATE TABLE inputs_geography_prm_zones
(
    prm_zone_scenario_id     INTEGER,
    prm_zone                 VARCHAR(32),
    allow_violation          INTEGER DEFAULT 0, -- constraint is hard by default
    violation_penalty_per_mw FLOAT   DEFAULT 0,
    PRIMARY KEY (prm_zone_scenario_id, prm_zone),
    FOREIGN KEY (prm_zone_scenario_id) REFERENCES
        subscenarios_geography_prm_zones (prm_zone_scenario_id)
);

-- Local capacity
-- This is the unit at which local capacity requirements are met in the model;
-- it can be different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_local_capacity_zones;
CREATE TABLE subscenarios_geography_local_capacity_zones
(
    local_capacity_zone_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                            VARCHAR(32),
    description                     VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_local_capacity_zones;
CREATE TABLE inputs_geography_local_capacity_zones
(
    local_capacity_zone_scenario_id INTEGER,
    local_capacity_zone             VARCHAR(32),
    allow_violation                 INTEGER DEFAULT 0, -- constraint is hard by default
    violation_penalty_per_mw        FLOAT   DEFAULT 0,
    PRIMARY KEY (local_capacity_zone_scenario_id, local_capacity_zone),
    FOREIGN KEY (local_capacity_zone_scenario_id) REFERENCES
        subscenarios_geography_local_capacity_zones (local_capacity_zone_scenario_id)
);


-- Market hubs
-- This is the unit at which prices are specified in the model;
-- it can be different from the load zones
DROP TABLE IF EXISTS subscenarios_geography_markets;
CREATE TABLE subscenarios_geography_markets
(
    market_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name               VARCHAR(32),
    description        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_markets;
CREATE TABLE inputs_geography_markets
(
    market_scenario_id INTEGER,
    market             VARCHAR(32),
    PRIMARY KEY (market_scenario_id, market),
    FOREIGN KEY (market_scenario_id) REFERENCES
        subscenarios_geography_markets (market_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_market_prices;
CREATE TABLE subscenarios_market_prices
(
    market_price_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     VARCHAR(32),
    description              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_market_prices;
CREATE TABLE inputs_market_prices
(
    market_price_scenario_id         INTEGER,
    market                           TEXT,
    market_price_profile_scenario_id INTEGER,
    varies_by_weather_iteration      INTEGER,
    varies_by_hydro_iteration        INTEGER,
    PRIMARY KEY (market_price_scenario_id, market,
                 market_price_profile_scenario_id),
    FOREIGN KEY (market_price_scenario_id) REFERENCES
        subscenarios_market_prices (market_price_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_market_price_profiles;
CREATE TABLE subscenarios_market_price_profiles
(
    market                           TEXT,
    market_price_profile_scenario_id INTEGER,
    name                             VARCHAR(32),
    description                      VARCHAR(128),
    PRIMARY KEY (market, market_price_profile_scenario_id)
);

DROP TABLE IF EXISTS inputs_market_price_profiles;
CREATE TABLE inputs_market_price_profiles
(
    market                           TEXT,
    market_price_profile_scenario_id INTEGER,
    weather_iteration                INTEGER NOT NULL,
    hydro_iteration                  INTEGER NOT NULL,
    stage_id                         INTEGER,
    timepoint                        INTEGER,
    market_price                     FLOAT,
    PRIMARY KEY (market, market_price_profile_scenario_id, weather_iteration,
                 hydro_iteration, stage_id, timepoint)
);

DROP TABLE IF EXISTS subscenarios_market_volume;
CREATE TABLE subscenarios_market_volume
(
    market_volume_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                      VARCHAR(32),
    description               VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_market_volume;
CREATE TABLE inputs_market_volume
(
    market_volume_scenario_id         INTEGER,
    market                            TEXT,
    market_volume_profile_scenario_id INTEGER,
    varies_by_weather_iteration       INTEGER,
    varies_by_hydro_iteration         INTEGER,
    PRIMARY KEY (market_volume_scenario_id, market,
                 market_volume_profile_scenario_id),
    FOREIGN KEY (market_volume_scenario_id) REFERENCES
        subscenarios_market_volume (market_volume_scenario_id)
);


DROP TABLE IF EXISTS subscenarios_market_volume_profiles;
CREATE TABLE subscenarios_market_volume_profiles
(
    market                            TEXT,
    market_volume_profile_scenario_id INTEGER,
    name                              VARCHAR(32),
    description                       VARCHAR(128),
    PRIMARY KEY (market, market_volume_profile_scenario_id)
);

DROP TABLE IF EXISTS inputs_market_volume_profiles;
CREATE TABLE inputs_market_volume_profiles
(
    market                            VARCHAR(32),
    market_volume_profile_scenario_id INTEGER,
    weather_iteration                 INTEGER,
    hydro_iteration                   INTEGER,
    stage_id                          INTEGER,
    timepoint                         INTEGER,
    max_market_sales                  FLOAT,
    max_market_purchases              FLOAT,
    max_final_market_sales            FLOAT,
    max_final_market_purchases        FLOAT,
    PRIMARY KEY (market, market_volume_profile_scenario_id,
                 weather_iteration, hydro_iteration, stage_id,
                 timepoint),
    FOREIGN KEY (market, market_volume_profile_scenario_id) REFERENCES
        subscenarios_market_volume_profiles
            (market, market_volume_profile_scenario_id)
);

-- Total limits over all markets
-- By tmp
DROP TABLE IF EXISTS subscenarios_market_volume_totals_in_tmp;
CREATE TABLE subscenarios_market_volume_totals_in_tmp
(
    market_volume_total_in_tmp_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

-- These are limits applied to the sum of participation all markets in
-- the respective timepoint
-- Totals in tmp are assumed to vary by weather iteration
DROP TABLE IF EXISTS inputs_market_volume_totals_in_tmp;
CREATE TABLE inputs_market_volume_totals_in_tmp
(
    market_volume_total_in_tmp_scenario_id INTEGER,
    weather_iteration                      INTEGER,
    timepoint                              FLOAT,
    max_total_net_market_purchases_in_tmp  FLOAT,
    max_total_net_market_sales_in_tmp      FLOAT,
    PRIMARY KEY (market_volume_total_in_tmp_scenario_id, weather_iteration,
                 timepoint),
    FOREIGN KEY (market_volume_total_in_tmp_scenario_id) REFERENCES
        subscenarios_market_volume_totals_in_tmp (market_volume_total_in_tmp_scenario_id)
);

-- By prd
DROP TABLE IF EXISTS subscenarios_market_volume_totals_in_prd;
CREATE TABLE subscenarios_market_volume_totals_in_prd
(
    market_volume_total_in_prd_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

-- These are limits applied to the sum of participation all markets in
-- the respective timepoint
DROP TABLE IF EXISTS inputs_market_volume_totals_in_prd;
CREATE TABLE inputs_market_volume_totals_in_prd
(
    market_volume_total_in_prd_scenario_id                   INTEGER,
    period                                                   FLOAT,
    max_total_net_market_purchases_in_prd                    FLOAT,
    max_total_net_market_sales_in_prd                        FLOAT,
    max_total_net_market_sales_in_prd_include_storage_losses INTEGER, -- Based on 'stor' operational type
    PRIMARY KEY (market_volume_total_in_prd_scenario_id, period),
    FOREIGN KEY (market_volume_total_in_prd_scenario_id) REFERENCES
        subscenarios_market_volume_totals_in_prd (market_volume_total_in_prd_scenario_id)
);

-- Fuel balancing areas
DROP TABLE IF EXISTS subscenarios_geography_fuel_burn_limit_balancing_areas;
CREATE TABLE subscenarios_geography_fuel_burn_limit_balancing_areas
(
    fuel_burn_limit_ba_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                           VARCHAR(32),
    description                    VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_fuel_burn_limit_balancing_areas;
CREATE TABLE inputs_geography_fuel_burn_limit_balancing_areas
(
    fuel_burn_limit_ba_scenario_id          INTEGER,
    fuel_burn_limit_ba                      VARCHAR(32),
    min_allow_violation                     INTEGER DEFAULT 0, -- constraint is hard by default
    min_violation_penalty_per_unit          FLOAT   DEFAULT 0,
    max_allow_violation                     INTEGER DEFAULT 0, -- constraint is hard by default
    max_violation_penalty_per_unit          FLOAT   DEFAULT 0,
    relative_max_allow_violation            INTEGER DEFAULT 0, -- constraint is hard by default
    relative_max_violation_penalty_per_unit FLOAT   DEFAULT 0,
    PRIMARY KEY (fuel_burn_limit_ba_scenario_id, fuel_burn_limit_ba),
    FOREIGN KEY (fuel_burn_limit_ba_scenario_id) REFERENCES
        subscenarios_geography_fuel_burn_limit_balancing_areas (fuel_burn_limit_ba_scenario_id)
);


-- Water system
DROP TABLE IF EXISTS subscenarios_system_water_system_params;
CREATE TABLE subscenarios_system_water_system_params
(
    water_system_params_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                            VARCHAR(32),
    description                     VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_water_system_params;
CREATE TABLE inputs_system_water_system_params
(
    water_system_params_scenario_id INTEGER PRIMARY KEY,
    water_system_balancing_type     TEXT,
    theoretical_power_coefficient   FLOAT,
    FOREIGN KEY (water_system_params_scenario_id) REFERENCES
        subscenarios_system_water_system_params (water_system_params_scenario_id)
);

-- Water network
DROP TABLE IF EXISTS subscenarios_geography_water_network;
CREATE TABLE subscenarios_geography_water_network
(
    water_network_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                      VARCHAR(32),
    description               VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_geography_water_network;
CREATE TABLE inputs_geography_water_network
(
    water_network_scenario_id            INTEGER,
    water_link                           TEXT,
    water_node_from                      TEXT,
    water_node_to                        TEXT,
    water_link_flow_transport_time_hours FLOAT,
    PRIMARY KEY (water_network_scenario_id, water_link),
    FOREIGN KEY (water_network_scenario_id) REFERENCES
        subscenarios_geography_water_network (water_network_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_system_water_node_reservoirs;
CREATE TABLE subscenarios_system_water_node_reservoirs
(
    water_node_reservoir_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                             VARCHAR(32),
    description                      VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_water_node_reservoirs;
CREATE TABLE inputs_system_water_node_reservoirs
(
    water_node_reservoir_scenario_id        INTEGER,
    water_node                              TEXT,
    max_powerhouse_release_vol_unit_per_sec FLOAT,
    max_spill_vol_unit_per_sec              FLOAT,
    max_total_outflow_vol_unit_per_sec      FLOAT,
    target_volume_scenario_id               INTEGER,
    target_release_scenario_id              INTEGER,
    allow_target_release_violation          INTEGER,
    target_release_violation_cost           FLOAT,
    minimum_volume_volumeunit               FLOAT,
    maximum_volume_volumeunit               FLOAT,
    allow_min_volume_violation              INTEGER,
    min_volume_violation_cost               FLOAT,
    allow_max_volume_violation              INTEGER,
    max_volume_violation_cost               INTEGER,
    volume_hrz_bounds_scenario_id           INTEGER,
    evaporation_coefficient                 FLOAT,
    elevation_type                          TEXT,
    constant_elevation                      FLOAT,
    exogenous_elevation_id                  INTEGER,
    volume_to_elevation_curve_id            INTEGER,
    PRIMARY KEY (water_node_reservoir_scenario_id, water_node),
    FOREIGN KEY (water_node_reservoir_scenario_id) REFERENCES
        subscenarios_system_water_node_reservoirs (water_node_reservoir_scenario_id),
    FOREIGN KEY (water_node, target_volume_scenario_id) REFERENCES
        subscenarios_system_water_node_reservoirs_target_volumes
            (water_node, target_volume_scenario_id),
    FOREIGN KEY (water_node, target_release_scenario_id) REFERENCES
        subscenarios_system_water_node_reservoirs_target_releases
            (water_node, target_release_scenario_id),
    FOREIGN KEY (water_node, volume_hrz_bounds_scenario_id) REFERENCES
        subscenarios_system_water_node_reservoirs_volume_horizon_bounds
            (water_node, volume_hrz_bounds_scenario_id)
--     FOREIGN KEY (reservoir, evaporation_coefficient_scenario_id) REFERENCES
--         subscenarios_system_water_node_reservoirs_evaporaton_coefficient
--             (reservoir, evaporation_coefficient_scenario_id)
);


DROP TABLE IF EXISTS
    subscenarios_system_water_node_reservoir_exogenous_elevations;
CREATE TABLE subscenarios_system_water_node_reservoir_exogenous_elevations
(
    water_node             VARCHAR(32),
    exogenous_elevation_id INTEGER,
    name                   VARCHAR(32),
    description            VARCHAR(128),
    PRIMARY KEY (water_node, exogenous_elevation_id)
);

DROP TABLE IF EXISTS
    inputs_system_water_node_reservoir_exogenous_elevations;
CREATE TABLE inputs_system_water_node_reservoir_exogenous_elevations
(
    water_node                    VARCHAR(64),
    exogenous_elevation_id        INTEGER,
    hydro_iteration               INTEGER DEFAULT 0 NOT NULL,
    timepoint                     INTEGER,
    reservoir_exogenous_elevation INTEGER,
    PRIMARY KEY (water_node, exogenous_elevation_id, timepoint,
                 hydro_iteration),
    FOREIGN KEY (water_node, exogenous_elevation_id) REFERENCES
        subscenarios_system_water_node_reservoir_exogenous_elevations
            (water_node, exogenous_elevation_id)
);

DROP TABLE IF EXISTS
    subscenarios_system_water_node_reservoir_volume_to_elevation_curves;
CREATE TABLE subscenarios_system_water_node_reservoir_volume_to_elevation_curves
(
    water_node                   VARCHAR(32),
    volume_to_elevation_curve_id INTEGER,
    name                         VARCHAR(32),
    description                  VARCHAR(128),
    PRIMARY KEY (water_node, volume_to_elevation_curve_id)
);

DROP TABLE IF EXISTS
    inputs_system_water_node_reservoir_volume_to_elevation_curves;
CREATE TABLE inputs_system_water_node_reservoir_volume_to_elevation_curves
(
    water_node                    VARCHAR(64),
    volume_to_elevation_curve_id  INTEGER,
    segment                       INTEGER,
    volume_to_elevation_slope     FLOAT,
    volume_to_elevation_intercept FLOAT,
    PRIMARY KEY (water_node, volume_to_elevation_curve_id, segment),
    FOREIGN KEY (water_node, volume_to_elevation_curve_id) REFERENCES
        subscenarios_system_water_node_reservoir_volume_to_elevation_curves
            (water_node, volume_to_elevation_curve_id)
);

DROP TABLE IF EXISTS subscenarios_system_water_node_reservoirs_target_volumes;
CREATE TABLE subscenarios_system_water_node_reservoirs_target_volumes
(
    water_node                TEXT,
    target_volume_scenario_id INTEGER,
    name                      VARCHAR(32),
    description               VARCHAR(128),
    PRIMARY KEY (water_node, target_volume_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_water_node_reservoirs_target_volumes;
CREATE TABLE inputs_system_water_node_reservoirs_target_volumes
(
    water_node                       TEXT,
    target_volume_scenario_id        INTEGER,
    hydro_iteration                  INTEGER DEFAULT 0 NOT NULL,
    timepoint                        FLOAT,
    reservoir_target_starting_volume DECIMAL,
    reservoir_target_ending_volume   DECIMAL,
    PRIMARY KEY (water_node, target_volume_scenario_id, timepoint,
                 hydro_iteration),
    FOREIGN KEY (water_node, target_volume_scenario_id) REFERENCES
        subscenarios_system_water_node_reservoirs_target_volumes
            (water_node, target_volume_scenario_id)
);


DROP TABLE IF EXISTS subscenarios_system_water_node_reservoirs_target_releases;
CREATE TABLE subscenarios_system_water_node_reservoirs_target_releases
(
    water_node                 TEXT,
    target_release_scenario_id INTEGER,
    name                       VARCHAR(32),
    description                VARCHAR(128),
    PRIMARY KEY (water_node, target_release_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_water_node_reservoirs_target_releases;
CREATE TABLE inputs_system_water_node_reservoirs_target_releases
(
    water_node                                        TEXT,
    target_release_scenario_id                        INTEGER,
    hydro_iteration                                   INTEGER DEFAULT 0 NOT NULL,
    balancing_type                                    TEXT,
    horizon                                           INTEGER,
    reservoir_target_release_avg_flow_volunit_per_sec DECIMAL,
    PRIMARY KEY (water_node, target_release_scenario_id, hydro_iteration,
                 balancing_type, horizon),
    FOREIGN KEY (water_node, target_release_scenario_id) REFERENCES
        subscenarios_system_water_node_reservoirs_target_releases
            (water_node, target_release_scenario_id)
);


DROP TABLE IF EXISTS
    subscenarios_system_water_node_reservoirs_volume_horizon_bounds;
CREATE TABLE subscenarios_system_water_node_reservoirs_volume_horizon_bounds
(
    water_node                    TEXT,
    volume_hrz_bounds_scenario_id INTEGER,
    name                          VARCHAR(32),
    description                   VARCHAR(128),
    PRIMARY KEY (water_node, volume_hrz_bounds_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_water_node_reservoirs_volume_horizon_bounds;
CREATE TABLE inputs_system_water_node_reservoirs_volume_horizon_bounds
(
    water_node                    TEXT,
    volume_hrz_bounds_scenario_id INTEGER,
    balancing_type                TEXT,
    horizon                       INTEGER,
    minimum_volume_volumeunit     DECIMAL,
    maximum_volume_volumeunit     DECIMAL,
    PRIMARY KEY (water_node, volume_hrz_bounds_scenario_id,
                 balancing_type, horizon),
    FOREIGN KEY (water_node, volume_hrz_bounds_scenario_id) REFERENCES
        subscenarios_system_water_node_reservoirs_volume_horizon_bounds
            (water_node, volume_hrz_bounds_scenario_id)
);



-- DROP TABLE IF EXISTS subscenarios_system_water_node_reservoirs_maximum_elevation;
-- CREATE TABLE subscenarios_system_water_node_reservoirs_maximum_elevation
-- (
--     reservoir                     TEXT,
--     maximum_elevation_scenario_id INTEGER,
--     name                          VARCHAR(32),
--     description                   VARCHAR(128)
-- );
--
-- DROP TABLE IF EXISTS inputs_system_water_node_reservoirs_maximum_elevation;
-- CREATE TABLE inputs_system_water_node_reservoirs_maximum_elevation
-- (
--     reservoir                       TEXT,
--     maximum_elevation_scenario_id   INTEGER,
--     timepoint                       FLOAT,
--     maximum_volume_volumeunit FLOAT,
--     PRIMARY KEY (reservoir, maximum_elevation_scenario_id)
-- );
--
-- DROP TABLE IF EXISTS subscenarios_system_water_node_reservoirs_evaporaton_coefficient;
-- CREATE TABLE subscenarios_system_water_node_reservoirs_evaporaton_coefficient
-- (
--     reservoir                     TEXT,
--     evaporation_coefficient_scenario_id INTEGER,
--     name                          VARCHAR(32),
--     description                   VARCHAR(128)
-- );
--
-- DROP TABLE IF EXISTS inputs_system_water_node_reservoirs_evaporaton_coefficient;
-- CREATE TABLE inputs_system_water_node_reservoirs_evaporaton_coefficient
-- (
--     reservoir                           TEXT,
--     evaporation_coefficient_scenario_id INTEGER,
--     month                               FLOAT,
--     evaporation_coefficient             FLOAT,
--     PRIMARY KEY (reservoir, evaporation_coefficient_scenario_id)
-- );

-- Water flows
DROP TABLE IF EXISTS subscenarios_system_water_flows;
CREATE TABLE subscenarios_system_water_flows
(
    water_flow_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   VARCHAR(32),
    description            VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_water_flows;
CREATE TABLE inputs_system_water_flows
(
    water_flow_scenario_id                       INTEGER,
    water_link                                   TEXT,
    default_min_flow_vol_per_sec                 FLOAT,
    allow_water_link_min_flow_violation          INTEGER,
    min_flow_violation_penalty_cost              FLOAT,
    allow_water_link_max_flow_violation          INTEGER,
    max_flow_violation_penalty_cost              FLOAT,
    allow_water_link_hrz_min_flow_violation      INTEGER,
    hrz_min_flow_violation_penalty_cost_per_hour FLOAT,
    allow_water_link_hrz_max_flow_violation      INTEGER,
    hrz_max_flow_violation_penalty_cost_per_hour FLOAT,
    water_flow_timepoint_bounds_scenario_id      INTEGER,
    water_flow_horizon_bounds_scenario_id        INTEGER,
    water_flow_ramp_limit_scenario_id            INTEGER,
    PRIMARY KEY (water_flow_scenario_id, water_link),
    FOREIGN KEY (water_flow_scenario_id) REFERENCES
        subscenarios_system_water_flows (water_flow_scenario_id)
);


DROP TABLE IF EXISTS subscenarios_system_water_flows_timepoint_bounds;
CREATE TABLE subscenarios_system_water_flows_timepoint_bounds
(
    water_link                              TEXT,
    water_flow_timepoint_bounds_scenario_id INTEGER,
    name                                    VARCHAR(32),
    description                             VARCHAR(128),
    PRIMARY KEY (water_link, water_flow_timepoint_bounds_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_water_flows_timepoint_bounds;
CREATE TABLE inputs_system_water_flows_timepoint_bounds
(
    water_link                              TEXT,
    water_flow_timepoint_bounds_scenario_id INTEGER,
    timepoint                               FLOAT,
    min_tmp_flow_vol_per_second             FLOAT,
    max_tmp_flow_vol_per_second             FLOAT,
    PRIMARY KEY (water_link, water_flow_timepoint_bounds_scenario_id,
                 timepoint),
    FOREIGN KEY (water_link, water_flow_timepoint_bounds_scenario_id) REFERENCES
        subscenarios_system_water_flows_timepoint_bounds
            (water_link, water_flow_timepoint_bounds_scenario_id)
);


DROP TABLE IF EXISTS subscenarios_system_water_flows_horizon_bounds;
CREATE TABLE subscenarios_system_water_flows_horizon_bounds
(
    water_link                            TEXT,
    water_flow_horizon_bounds_scenario_id INTEGER,
    name                                  VARCHAR(32),
    description                           VARCHAR(128),
    PRIMARY KEY (water_link, water_flow_horizon_bounds_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_water_flows_horizon_bounds;
CREATE TABLE inputs_system_water_flows_horizon_bounds
(
    water_link                               TEXT,
    water_flow_horizon_bounds_scenario_id    INTEGER,
    balancing_type                           TEXT,
    horizon                                  INTEGER,
    min_bt_hrz_flow_avg_vol_per_second       FLOAT,
    max_bt_hrz_flow_avg_vol_per_second       FLOAT,
    threshold_side_stream_avg_vol_per_second FLOAT,
    PRIMARY KEY (water_link, water_flow_horizon_bounds_scenario_id,
                 balancing_type, horizon),
    FOREIGN KEY (water_link, water_flow_horizon_bounds_scenario_id) REFERENCES
        subscenarios_system_water_flows_horizon_bounds
            (water_link, water_flow_horizon_bounds_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_system_water_flows_horizon_bounds_upstream_node_map;
CREATE TABLE subscenarios_system_water_flows_horizon_bounds_upstream_node_map
(
    water_link                            TEXT,
    water_flow_horizon_bounds_scenario_id INTEGER,
    name                                  VARCHAR(32),
    description                           VARCHAR(128),
    PRIMARY KEY (water_link, water_flow_horizon_bounds_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_water_flows_horizon_bounds_upstream_node_map;
CREATE TABLE inputs_system_water_flows_horizon_bounds_upstream_node_map
(
    water_link                            TEXT,
    water_flow_horizon_bounds_scenario_id INTEGER,
    upstream_water_node                   TEXT,
    PRIMARY KEY (water_link, water_flow_horizon_bounds_scenario_id,
                 upstream_water_node),
    FOREIGN KEY (water_link, water_flow_horizon_bounds_scenario_id) REFERENCES
        subscenarios_system_water_flows_horizon_bounds
            (water_link, water_flow_horizon_bounds_scenario_id)
);

-- Water flow ramp limits
DROP TABLE IF EXISTS subscenarios_system_water_flow_ramp_limits;
CREATE TABLE subscenarios_system_water_flow_ramp_limits
(
    water_link                        TEXT,
    water_flow_ramp_limit_scenario_id INTEGER,
    name                              VARCHAR(32),
    description                       VARCHAR(128),
    PRIMARY KEY (water_link, water_flow_ramp_limit_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_water_flow_ramp_limits;
CREATE TABLE inputs_system_water_flow_ramp_limits
(
    water_link                        TEXT,
    water_flow_ramp_limit_scenario_id INTEGER,
    ramp_limit_name                   TEXT,
    ramp_limit_up_or_down             INTEGER, -- 1 for upramp, -1 for downramp
    ramp_limit_n_hours                FLOAT,
    PRIMARY KEY (water_link, water_flow_ramp_limit_scenario_id,
                 ramp_limit_name),
    FOREIGN KEY (water_link, water_flow_ramp_limit_scenario_id) REFERENCES
        subscenarios_system_water_flow_ramp_limits
            (water_link, water_flow_ramp_limit_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_system_water_flow_ramp_limit_bt_hrz_values;
CREATE TABLE subscenarios_system_water_flow_ramp_limit_bt_hrz_values
(
    water_link                        TEXT,
    water_flow_ramp_limit_scenario_id INTEGER,
    name                              VARCHAR(32),
    description                       VARCHAR(128),
    PRIMARY KEY (water_link, water_flow_ramp_limit_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_water_flow_ramp_limit_bt_hrz_values;
CREATE TABLE inputs_system_water_flow_ramp_limit_bt_hrz_values
(
    water_link                        TEXT,
    water_flow_ramp_limit_scenario_id INTEGER,
    ramp_limit_name                   TEXT,
    balancing_type                    TEXT,
    horizon                           INTEGER,
    allowed_flow_delta_vol_per_sec    FLOAT,
    PRIMARY KEY (water_link, water_flow_ramp_limit_scenario_id,
                 ramp_limit_name, balancing_type, horizon),
    FOREIGN KEY (water_link, water_flow_ramp_limit_scenario_id) REFERENCES
        subscenarios_system_water_flow_ramp_limits
            (water_link, water_flow_ramp_limit_scenario_id)
);

-- Water nodes
DROP TABLE IF EXISTS subscenarios_system_water_inflows;
CREATE TABLE subscenarios_system_water_inflows
(
    water_inflow_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     VARCHAR(32),
    description              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_water_inflows;
CREATE TABLE inputs_system_water_inflows
(
    water_inflow_scenario_id                INTEGER,
    water_node                              TEXT,
    hydro_iteration                         INTEGER DEFAULT 0 NOT NULL,
    timepoint                               FLOAT,
    exogenous_water_inflow_rate_vol_per_sec TEXT,
    PRIMARY KEY (water_inflow_scenario_id, water_node, timepoint,
                 hydro_iteration),
    FOREIGN KEY (water_inflow_scenario_id) REFERENCES
        subscenarios_system_water_inflows (water_inflow_scenario_id)
);

-- water_powerhouses
DROP TABLE IF EXISTS subscenarios_system_water_powerhouses;
CREATE TABLE subscenarios_system_water_powerhouses
(
    water_powerhouse_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                         VARCHAR(32),
    description                  VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_water_powerhouses;
CREATE TABLE inputs_system_water_powerhouses
(
    water_powerhouse_scenario_id INTEGER,
    powerhouse                   TEXT,
    powerhouse_water_node        TEXT,
    tailwater_elevation          FLOAT,
    headloss_factor              FLOAT,
    turbine_efficiency           FLOAT,
    PRIMARY KEY (water_powerhouse_scenario_id, powerhouse),
    FOREIGN KEY (water_powerhouse_scenario_id) REFERENCES
        subscenarios_system_water_powerhouses (water_powerhouse_scenario_id)
);


-------------------
-- -- PROJECT -- --
-------------------

-- -- Capacity -- --

-- Project portfolios
-- Subsets of projects allowed in a scenario: includes both specified and
-- potential projects
DROP TABLE IF EXISTS subscenarios_project_portfolios;
CREATE TABLE subscenarios_project_portfolios
(
    project_portfolio_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                          VARCHAR(32),
    description                   VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_portfolios;
CREATE TABLE inputs_project_portfolios
(
    project_portfolio_scenario_id INTEGER,
    project                       VARCHAR(64),
    specified                     INTEGER,
    new_build                     INTEGER,
    capacity_type                 VARCHAR(32),
    PRIMARY KEY (project_portfolio_scenario_id, project),
    FOREIGN KEY (project_portfolio_scenario_id) REFERENCES
        subscenarios_project_portfolios (project_portfolio_scenario_id),
    FOREIGN KEY (capacity_type) REFERENCES mod_capacity_types (capacity_type)
);

-- Index for filtering by project_portfolio_scenario_id in inputs_project_portfolios
CREATE INDEX idx_project_portfolios_scenario
    ON inputs_project_portfolios (project_portfolio_scenario_id);

-- Existing project capacity and fixed costs
-- The capacity and fixed costs of 'specified' projects, i.e. exogenously
-- specified capacity that is not a variable in the model
-- Retirement can be allowed, in which case the fixed cost will determine
-- whether the economics of retirement are favorable
DROP TABLE IF EXISTS subscenarios_project_specified_capacity;
CREATE TABLE subscenarios_project_specified_capacity
(
    project_specified_capacity_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_specified_capacity;
CREATE TABLE inputs_project_specified_capacity
(
    project_specified_capacity_scenario_id   INTEGER,
    project                                  VARCHAR(64),
    period                                   INTEGER,
    specified_capacity_mw                    FLOAT, -- grid-facing nameplate capacity
    specified_energy_mwh                     FLOAT, -- energy available for shaping in period
    shaping_capacity_mw                      FLOAT, -- for energy products
    hyb_gen_specified_capacity_mw            FLOAT, -- e.g. CAES turbine capacity
    hyb_stor_specified_capacity_mw           FLOAT, -- e.g. battery tightly-coupled with PV
    specified_stor_capacity_mwh              FLOAT, -- storage energy capacity
    fuel_production_capacity_fuelunitperhour FLOAT, -- fuel production capacity (e.g. electrolyzer)
    fuel_release_capacity_fuelunitperhour    FLOAT, -- fuel release capacity
    fuel_storage_capacity_fuelunit           FLOAT, -- fuel storage capacity
    PRIMARY KEY (project_specified_capacity_scenario_id, project, period),
    FOREIGN KEY (project_specified_capacity_scenario_id) REFERENCES
        subscenarios_project_specified_capacity (project_specified_capacity_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_specified_fixed_cost;
CREATE TABLE subscenarios_project_specified_fixed_cost
(
    project_specified_fixed_cost_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                     VARCHAR(32),
    description                              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_specified_fixed_cost;
CREATE TABLE inputs_project_specified_fixed_cost
(
    project_specified_fixed_cost_scenario_id                   INTEGER,
    project                                                    VARCHAR(64),
    period                                                     INTEGER,
    fixed_cost_per_mw_yr                                       FLOAT,
    fixed_cost_per_energy_mwh_yr                               FLOAT,
    fixed_cost_per_shaping_mw_yr                               FLOAT, -- for energy products
    hyb_gen_fixed_cost_per_mw_yr                               FLOAT,
    hyb_stor_fixed_cost_per_mw_yr                              FLOAT,
    fixed_cost_per_stor_mwh_yr                                 FLOAT,
    fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr FLOAT,
    fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr    FLOAT,
    fuel_storage_capacity_fixed_cost_per_fuelunit_yr           FLOAT,
    PRIMARY KEY (project_specified_fixed_cost_scenario_id, project, period),
    FOREIGN KEY (project_specified_fixed_cost_scenario_id) REFERENCES
        subscenarios_project_specified_fixed_cost
            (project_specified_fixed_cost_scenario_id)
);

-- New project capital costs and potential
-- The annualized all-in cost of potential new project (capital + fixed o&m
-- with financing)
-- In each 'period,' the minimum build required and maximum build allowed
-- can also be specified
DROP TABLE IF EXISTS subscenarios_project_new_cost;
CREATE TABLE subscenarios_project_new_cost
(
    project_new_cost_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                         VARCHAR(32),
    description                  VARCHAR(128)
);

-- Annual fixed O&M costs are incurred in each operational year
-- Capital costs are incurred in each year of the financial lifetime
DROP TABLE IF EXISTS inputs_project_new_cost;
CREATE TABLE inputs_project_new_cost
(
    project_new_cost_scenario_id                               INTEGER,
    project                                                    VARCHAR(64),
    vintage                                                    INTEGER,
    operational_lifetime_yrs                                   FLOAT,
    fixed_cost_per_mw_yr                                       FLOAT,
    fixed_cost_per_energy_mwh_yr                               FLOAT,
    fixed_cost_per_stor_mwh_yr                                 FLOAT,
    fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr FLOAT,
    fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr    FLOAT,
    fuel_storage_capacity_fixed_cost_per_fuelunit_yr           FLOAT,
    financial_lifetime_yrs                                     FLOAT,
    annualized_real_cost_per_mw_yr                             FLOAT,
    annualized_real_cost_per_energy_mwh_yr                     FLOAT,
    annualized_real_cost_per_stor_mwh_yr                       FLOAT,
    fuel_production_capacity_cost_per_fuelunitperhour_yr       FLOAT, -- annualized fuel prod cost
    fuel_release_capacity_cost_per_fuelunitperhour_yr          FLOAT, -- annualized fuel release cost
    fuel_storage_capacity_cost_per_fuelunit_yr                 FLOAT, -- annualized fuel storage cost
    supply_curve_scenario_id                                   INTEGER,
    PRIMARY KEY (project_new_cost_scenario_id, project, vintage),
    FOREIGN KEY (project_new_cost_scenario_id) REFERENCES
        subscenarios_project_new_cost (project_new_cost_scenario_id)
);

-- New project binary build size
DROP TABLE IF EXISTS subscenarios_project_new_binary_build_size;
CREATE TABLE subscenarios_project_new_binary_build_size
(
    project_new_binary_build_size_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                      VARCHAR(32),
    description                               VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_new_binary_build_size;
CREATE TABLE inputs_project_new_binary_build_size
(
    project_new_binary_build_size_scenario_id INTEGER,
    project                                   VARCHAR(64),
    binary_build_size_mw                      FLOAT,
    binary_build_size_mwh                     FLOAT,
    PRIMARY KEY (project_new_binary_build_size_scenario_id, project),
    FOREIGN KEY (project_new_binary_build_size_scenario_id) REFERENCES
        subscenarios_project_new_binary_build_size
            (project_new_binary_build_size_scenario_id)
);

-- Shiftable load supply curve
DROP TABLE IF EXISTS inputs_project_shiftable_load_supply_curve;
CREATE TABLE inputs_project_shiftable_load_supply_curve
(
    supply_curve_scenario_id INTEGER,
    project                  VARCHAR(64),
    supply_curve_point       INTEGER,
    supply_curve_slope       FLOAT,
    supply_curve_intercept   FLOAT,
    PRIMARY KEY (supply_curve_scenario_id, project, supply_curve_point)
);

DROP TABLE IF EXISTS subscenarios_project_new_potential;
CREATE TABLE subscenarios_project_new_potential
(
    project_new_potential_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                              VARCHAR(32),
    description                       VARCHAR(128)
);

-- Projects with no min or max build requirements can be included here with
-- NULL values or excluded from this table
DROP TABLE IF EXISTS inputs_project_new_potential;
CREATE TABLE inputs_project_new_potential
(
    project_new_potential_scenario_id INTEGER,
    project                           VARCHAR(64),
    period                            INTEGER,
    min_new_build_power               FLOAT,
    max_new_build_power               FLOAT,
    min_capacity_power                FLOAT,
    max_capacity_power                FLOAT,
    min_new_build_stor_energy         FLOAT,
    max_new_build_stor_energy         FLOAT,
    min_capacity_stor_energy          FLOAT,
    max_capacity_stor_energy          FLOAT,
    min_new_procured_energy           FLOAT,
    max_new_procured_energy           FLOAT,
    min_total_procured_energy         FLOAT,
    max_total_procured_energy         FLOAT,
    PRIMARY KEY (project_new_potential_scenario_id, project, period),
    FOREIGN KEY (project_new_potential_scenario_id) REFERENCES
        subscenarios_project_new_potential (project_new_potential_scenario_id)
);


-- Group capacity requirements
-- Requirements
DROP TABLE IF EXISTS subscenarios_project_capacity_group_requirements;
CREATE TABLE subscenarios_project_capacity_group_requirements
(
    project_capacity_group_requirement_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                           VARCHAR(32),
    description                                    VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_capacity_group_requirements;
CREATE TABLE inputs_project_capacity_group_requirements
(
    project_capacity_group_requirement_scenario_id INTEGER,
    capacity_group                                 VARCHAR(64),
    period                                         INTEGER,
    capacity_group_new_capacity_min                FLOAT,
    capacity_group_new_capacity_max                FLOAT,
    capacity_group_total_capacity_min              FLOAT,
    capacity_group_total_capacity_max              FLOAT,
    energy_group_new_energy_min                    FLOAT, -- applies to energy projects only
    energy_group_new_energy_max                    FLOAT, -- applies to energy projects only
    energy_group_total_energy_min                  FLOAT, -- applies to energy projects only
    energy_group_total_energy_max                  FLOAT, -- applies to energy projects only
    PRIMARY KEY (project_capacity_group_requirement_scenario_id,
                 capacity_group, period),
    FOREIGN KEY (project_capacity_group_requirement_scenario_id) REFERENCES
        subscenarios_project_capacity_group_requirements
            (project_capacity_group_requirement_scenario_id)
);

-- Relative capacity requirements
DROP TABLE IF EXISTS subscenarios_project_relative_capacity_requirements;
CREATE TABLE subscenarios_project_relative_capacity_requirements
(
    project_relative_capacity_requirement_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                              VARCHAR(32),
    description                                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_relative_capacity_requirements;
CREATE TABLE inputs_project_relative_capacity_requirements
(
    project_relative_capacity_requirement_scenario_id INTEGER,
    project                                           VARCHAR(64),
    period                                            INTEGER,
    prj_for_lim_map_id                                INTEGER,
    min_relative_capacity_limit_new                   FLOAT,
    max_relative_capacity_limit_new                   FLOAT,
    min_relative_capacity_limit_total                 FLOAT,
    max_relative_capacity_limit_total                 FLOAT,
    PRIMARY KEY (project_relative_capacity_requirement_scenario_id, project,
                 period, prj_for_lim_map_id),
    FOREIGN KEY (project_relative_capacity_requirement_scenario_id) REFERENCES
        subscenarios_project_relative_capacity_requirements
            (project_relative_capacity_requirement_scenario_id),
    FOREIGN KEY (project, prj_for_lim_map_id) REFERENCES
        subscenarios_project_relative_capacity_requirements_map
            (project, prj_for_lim_map_id)
);

DROP TABLE IF EXISTS subscenarios_project_relative_capacity_requirements_map;
CREATE TABLE subscenarios_project_relative_capacity_requirements_map
(
    project            VARCHAR(64),
    prj_for_lim_map_id INTEGER,
    name               VARCHAR(32),
    description        VARCHAR(128),
    PRIMARY KEY (project, prj_for_lim_map_id)
);

DROP TABLE IF EXISTS inputs_project_relative_capacity_requirements_map;
CREATE TABLE inputs_project_relative_capacity_requirements_map
(
    project            VARCHAR(64),
    prj_for_lim_map_id INTEGER,
    project_for_limits VARCHAR(64),
    PRIMARY KEY (project, prj_for_lim_map_id, project_for_limits)
);


-- Group project mapping
DROP TABLE IF EXISTS subscenarios_project_capacity_groups;
CREATE TABLE subscenarios_project_capacity_groups
(
    project_capacity_group_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                               VARCHAR(32),
    description                        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_capacity_groups;
CREATE TABLE inputs_project_capacity_groups
(
    project_capacity_group_scenario_id INTEGER,
    capacity_group                     VARCHAR(64),
    project                            VARCHAR(64),
    PRIMARY KEY (project_capacity_group_scenario_id, capacity_group, project),
    FOREIGN KEY (project_capacity_group_scenario_id) REFERENCES
        subscenarios_project_capacity_groups (project_capacity_group_scenario_id)
);


-- -- Operations -- --

-- Project operational characteristics
-- These vary by operational type
-- Generators that do not have certain characteristics (e.g. hydro does not
-- have a heat rate) should be included with NULL values in these columns
-- For variable generators, specify a variable_generator_profile_scenario_id
-- For hydro generators (curtailable or nonocurtailable), specify a
-- hydro_operational_chars_scenario_id
DROP TABLE IF EXISTS subscenarios_project_operational_chars;
CREATE TABLE subscenarios_project_operational_chars
(
    project_operational_chars_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                  VARCHAR(32),
    description                           VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_operational_chars;
CREATE TABLE inputs_project_operational_chars
(
    project_operational_chars_scenario_id                 INTEGER,
    project                                               VARCHAR(64),
    technology                                            VARCHAR(32),
    operational_type                                      VARCHAR(32),
    balancing_type_project                                VARCHAR(32),
    load_modifier_flag                                    INTEGER,
    distribution_loss_adjustment_factor                   FLOAT,
    variable_om_cost_per_mwh                              FLOAT,   -- simple variable O&M
    variable_om_cost_by_period_scenario_id                INTEGER, -- determines by period simple variable O&M
    variable_om_cost_by_timepoint_scenario_id             INTEGER, -- determines by tmp simple variable O&M
    project_fuel_scenario_id                              INTEGER,
    heat_rate_curves_scenario_id                          INTEGER, -- determined heat rate curve
    variable_om_curves_scenario_id                        INTEGER, -- determined variable O&M curve
    startup_chars_scenario_id                             INTEGER, -- determines startup ramp chars
    min_stable_level_fraction                             FLOAT,
    unit_size_mw                                          FLOAT,
    startup_cost_per_mw                                   FLOAT,
    shutdown_cost_per_mw                                  FLOAT,
    startup_fuel_mmbtu_per_mw                             FLOAT,
    startup_plus_ramp_up_rate                             FLOAT,   -- Not used for gen_commit_lin/bin!
    shutdown_plus_ramp_down_rate                          FLOAT,
    ramp_up_when_on_rate                                  FLOAT,   -- frac capacity per min
    ramp_up_when_on_rate_monthly_adjustment_scenario_id   INTEGER,
    ramp_down_when_on_rate                                FLOAT,   -- frac capacity per min
    ramp_down_when_on_rate_monthly_adjustment_scenario_id INTEGER,
    ramp_up_violation_penalty                             FLOAT,   -- leave NULL for hard constraints
    ramp_down_violation_penalty                           FLOAT,   -- leave NULL for hard constraints
    bt_hrz_ramp_up_rate_limit_scenario_id                 INTEGER,
    bt_hrz_ramp_down_rate_limit_scenario_id               INTEGER,
    total_ramp_up_limit_scenario_id                       INTEGER,
    total_ramp_down_limit_scenario_id                     INTEGER,
    ramp_tuning_cost_per_mw                               FLOAT,
    min_up_time_hours                                     INTEGER,
    min_up_time_violation_penalty                         FLOAT,   -- leave NULL for hard constraint
    min_down_time_hours                                   INTEGER,
    min_down_time_violation_penalty                       FLOAT,   -- leave NULL for hard constraint
    cycle_selection_scenario_id                           INTEGER,
    supplemental_firing_scenario_id                       INTEGER,
    allow_startup_shutdown_power                          INTEGER, -- defaults to 0 in the model if not specified
    storage_efficiency                                    FLOAT,   -- hourly losses from storage; default 1 (no losses)
    charging_efficiency                                   FLOAT,
    discharging_efficiency                                FLOAT,
    charging_capacity_multiplier                          FLOAT,   -- default 1 in model if not specified
    discharging_capacity_multiplier                       FLOAT,   -- default 1 in model if not specified
    soc_penalty_cost_per_energyunit                       FLOAT,
    soc_last_tmp_penalty_cost_per_energyunit              FLOAT,
    max_losses_in_hrz_frac_stor_energy_capacity           FLOAT,
    flex_load_static_profile_scenario_id                  INTEGER,
    minimum_duration_hours                                FLOAT,
    maximum_duration_hours                                FLOAT,
    aux_consumption_frac_capacity                         FLOAT,
    aux_consumption_frac_power                            FLOAT,
    last_commitment_stage                                 INTEGER,
    n_startup_limit_scenario_id                           INTEGER,
    variable_generator_profile_scenario_id                INTEGER, -- determines var profiles
    cap_factor_default                                    FLOAT,
    curtailment_cost_scenario_id                          INTEGER,
    hydro_operational_chars_scenario_id                   INTEGER, -- determines hydro MWa, min, max
    energy_profile_scenario_id                            INTEGER,
    energy_hrz_shaping_scenario_id                        INTEGER,
    energy_slice_hrz_shaping_scenario_id                  INTEGER,
    base_net_requirement_scenario_id                      INTEGER,
    peak_deviation_demand_charge_scenario_id              INTEGER,
    lf_reserves_up_derate                                 FLOAT,
    lf_reserves_down_derate                               FLOAT,
    regulation_up_derate                                  FLOAT,
    regulation_down_derate                                FLOAT,
    frequency_response_derate                             FLOAT,
    spinning_reserves_derate                              FLOAT,
    inertia_reserves_derate                               FLOAT,
    lf_reserves_up_ramp_rate                              FLOAT,
    lf_reserves_down_ramp_rate                            FLOAT,
    regulation_up_ramp_rate                               FLOAT,
    regulation_down_ramp_rate                             FLOAT,
    frequency_response_ramp_rate                          FLOAT,
    spinning_reserves_ramp_rate                           FLOAT,
    inertia_constant_sec                                  FLOAT,
    powerunithour_per_fuelunit                            FLOAT,
    cap_factor_limits_scenario_id                         INTEGER,
    partial_availability_threshold                        FLOAT,
    stor_exog_state_of_charge_scenario_id                 INTEGER, -- determines storage SOC
    nonfuel_carbon_emissions_per_mwh                      FLOAT,
    powerhouse                                            TEXT,
    generator_efficiency                                  FLOAT,
    linked_load_component                                 TEXT,
    load_modifier_profile_scenario_id                     INTEGER,
    load_component_shift_bounds_scenario_id               INTEGER,
    efficiency_factor                                     FLOAT,
    energy_requirement_factor                             FLOAT,
    losses_factor_in_energy_target                        FLOAT,
    losses_factor_curtailment                             FLOAT,
    upward_reserves_to_soc_depletion                      FLOAT,
    PRIMARY KEY (project_operational_chars_scenario_id, project),
    FOREIGN KEY (project_operational_chars_scenario_id) REFERENCES
        subscenarios_project_operational_chars (project_operational_chars_scenario_id),
-- Ensure operational characteristics for fuels, variable, hydro and heat rates exist
    FOREIGN KEY (project, variable_om_cost_by_period_scenario_id) REFERENCES
        subscenarios_project_variable_om_cost_by_period
            (project, variable_om_cost_by_period_scenario_id),
    FOREIGN KEY (project, variable_om_cost_by_timepoint_scenario_id) REFERENCES
        subscenarios_project_variable_om_cost_by_timepoint
            (project, variable_om_cost_by_timepoint_scenario_id),
    FOREIGN KEY (project, project_fuel_scenario_id) REFERENCES
        subscenarios_project_fuels
            (project, project_fuel_scenario_id),
    FOREIGN KEY (project, heat_rate_curves_scenario_id) REFERENCES
        subscenarios_project_heat_rate_curves
            (project, heat_rate_curves_scenario_id),
    FOREIGN KEY (project, variable_om_curves_scenario_id) REFERENCES
        subscenarios_project_variable_om_curves
            (project, variable_om_curves_scenario_id),
    FOREIGN KEY (project, cycle_selection_scenario_id) REFERENCES
        subscenarios_project_cycle_selection
            (project, cycle_selection_scenario_id),
    FOREIGN KEY (project, supplemental_firing_scenario_id) REFERENCES
        subscenarios_project_supplemental_firing
            (project, supplemental_firing_scenario_id),
    FOREIGN KEY (project, n_startup_limit_scenario_id) REFERENCES
        subscenarios_project_n_startup_limits
            (project, n_startup_limit_scenario_id),
    FOREIGN KEY (project, flex_load_static_profile_scenario_id) REFERENCES
        subscenarios_project_flex_load_static_profiles
            (project, flex_load_static_profile_scenario_id),
    FOREIGN KEY (project, variable_generator_profile_scenario_id) REFERENCES
        subscenarios_project_variable_generator_profiles
            (project, variable_generator_profile_scenario_id),
    FOREIGN KEY (project, curtailment_cost_scenario_id) REFERENCES
        subscenarios_project_curtailment_cost
            (project, curtailment_cost_scenario_id),
    FOREIGN KEY (project, stor_exog_state_of_charge_scenario_id) REFERENCES
        subscenarios_project_stor_exog_state_of_charge
            (project, stor_exog_state_of_charge_scenario_id),
    FOREIGN KEY (project, hydro_operational_chars_scenario_id) REFERENCES
        subscenarios_project_hydro_operational_chars
            (project, hydro_operational_chars_scenario_id),
    FOREIGN KEY (project, energy_profile_scenario_id) REFERENCES
        subscenarios_project_energy_profiles
            (project, energy_profile_scenario_id),
    FOREIGN KEY (project, energy_hrz_shaping_scenario_id) REFERENCES
        subscenarios_project_energy_hrz_shaping
            (project, energy_hrz_shaping_scenario_id),
    FOREIGN KEY (project, energy_slice_hrz_shaping_scenario_id) REFERENCES
        subscenarios_project_energy_slice_hrz_shaping
            (project, energy_slice_hrz_shaping_scenario_id),
    FOREIGN KEY (project, base_net_requirement_scenario_id) REFERENCES
        subscenarios_project_base_net_requirements
            (project, base_net_requirement_scenario_id),
    FOREIGN KEY (project, peak_deviation_demand_charge_scenario_id) REFERENCES
        subscenarios_project_peak_deviation_demand_charges
            (project, peak_deviation_demand_charge_scenario_id),
    FOREIGN KEY (project, cap_factor_limits_scenario_id) REFERENCES
        subscenarios_project_cap_factor_limits (project, cap_factor_limits_scenario_id),
    FOREIGN KEY (project, bt_hrz_ramp_up_rate_limit_scenario_id) REFERENCES
        subscenarios_project_bt_hrz_ramp_up_rate_limits (
                                                         project,
                                                         bt_hrz_ramp_up_rate_limit_scenario_id
            ),
    FOREIGN KEY (project, bt_hrz_ramp_down_rate_limit_scenario_id) REFERENCES
        subscenarios_project_bt_hrz_ramp_down_rate_limits (
                                                           project,
                                                           bt_hrz_ramp_down_rate_limit_scenario_id
            ),
    FOREIGN KEY (project, total_ramp_up_limit_scenario_id) REFERENCES
        subscenarios_project_total_ramp_up_limits (project, total_ramp_up_limit_scenario_id),
    FOREIGN KEY (project, total_ramp_down_limit_scenario_id) REFERENCES
        subscenarios_project_total_ramp_down_limits
            (project, total_ramp_down_limit_scenario_id),
    FOREIGN KEY (project, load_modifier_profile_scenario_id) REFERENCES
        subscenarios_project_load_modifier_profiles (project,
                                                     load_modifier_profile_scenario_id),
    FOREIGN KEY (operational_type) REFERENCES mod_operational_types
        (operational_type)
);

-- Index for filtering operational_type in inputs_project_operational_chars
CREATE INDEX idx_operational_chars_scenario_optype
    ON inputs_project_operational_chars (project_operational_chars_scenario_id,
                                         operational_type);


-- Variable O&M by period
DROP TABLE IF EXISTS subscenarios_project_variable_om_cost_by_period;
CREATE TABLE subscenarios_project_variable_om_cost_by_period
(
    project                                VARCHAR(32),
    variable_om_cost_by_period_scenario_id INTEGER,
    name                                   VARCHAR(32),
    description                            VARCHAR(128),
    PRIMARY KEY (project, variable_om_cost_by_period_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_variable_om_cost_by_period;
CREATE TABLE inputs_project_variable_om_cost_by_period
(
    project                                VARCHAR(64),
    variable_om_cost_by_period_scenario_id INTEGER,
    period                                 INTEGER, -- 0 means it's the same for all periods
    variable_om_cost_by_period             FLOAT,
    PRIMARY KEY (project, variable_om_cost_by_period_scenario_id, period),
    FOREIGN KEY (project, variable_om_cost_by_period_scenario_id) REFERENCES
        subscenarios_project_variable_om_cost_by_period (project,
                                                         variable_om_cost_by_period_scenario_id)
);

-- Variable O&M by timepoint
DROP TABLE IF EXISTS subscenarios_project_variable_om_cost_by_timepoint;
CREATE TABLE subscenarios_project_variable_om_cost_by_timepoint
(
    project                                   VARCHAR(32),
    variable_om_cost_by_timepoint_scenario_id INTEGER,
    name                                      VARCHAR(32),
    description                               VARCHAR(128),
    PRIMARY KEY (project, variable_om_cost_by_timepoint_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_variable_om_cost_by_timepoint;
CREATE TABLE inputs_project_variable_om_cost_by_timepoint
(
    project                                   VARCHAR(64),
    variable_om_cost_by_timepoint_scenario_id INTEGER,
    weather_iteration                         INTEGER,
    hydro_iteration                           INTEGER,
    timepoint                                 INTEGER,
    variable_om_cost_by_timepoint             FLOAT,
    PRIMARY KEY (project, variable_om_cost_by_timepoint_scenario_id,
                 weather_iteration, hydro_iteration, timepoint),
    FOREIGN KEY (project, variable_om_cost_by_timepoint_scenario_id)
        REFERENCES subscenarios_project_variable_om_cost_by_timepoint (
                                                                       project,
                                                                       variable_om_cost_by_timepoint_scenario_id
            )
);

DROP TABLE IF EXISTS inputs_project_variable_om_cost_by_timepoint_iterations;
CREATE TABLE inputs_project_variable_om_cost_by_timepoint_iterations
(
    project                                   VARCHAR(64),
    variable_om_cost_by_timepoint_scenario_id INTEGER,
    varies_by_weather_iteration               INTEGER,
    varies_by_hydro_iteration                 INTEGER,
    PRIMARY KEY (project, variable_om_cost_by_timepoint_scenario_id,
                 varies_by_weather_iteration, varies_by_hydro_iteration)
);

-- Project fuels
DROP TABLE IF EXISTS subscenarios_project_fuels;
CREATE TABLE subscenarios_project_fuels
(
    project                  VARCHAR(64),
    project_fuel_scenario_id INTEGER,
    name                     VARCHAR(32),
    description              VARCHAR(128),
    PRIMARY KEY (project, project_fuel_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_fuels;
CREATE TABLE inputs_project_fuels
(
    project                    VARCHAR(64),
    project_fuel_scenario_id   INTEGER,
    fuel                       VARCHAR(64),
    min_fraction_in_fuel_blend FLOAT DEFAULT 0,
    max_fraction_in_fuel_blend FLOAT DEFAULT 1,
    PRIMARY KEY (project, project_fuel_scenario_id, fuel),
    FOREIGN KEY (project, project_fuel_scenario_id) REFERENCES
        subscenarios_project_fuels (project, project_fuel_scenario_id)
);

-- Heat rate curves
-- TODO: see comments variable profiles
DROP TABLE IF EXISTS subscenarios_project_heat_rate_curves;
CREATE TABLE subscenarios_project_heat_rate_curves
(
    project                      VARCHAR(32),
    heat_rate_curves_scenario_id INTEGER,
    name                         VARCHAR(32),
    description                  VARCHAR(128),
    PRIMARY KEY (project, heat_rate_curves_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_heat_rate_curves;
CREATE TABLE inputs_project_heat_rate_curves
(
    project                         VARCHAR(64),
    heat_rate_curves_scenario_id    INTEGER,
    period                          INTEGER, -- 0 means it's the same for all periods
    load_point_fraction             FLOAT,
    average_heat_rate_mmbtu_per_mwh FLOAT,
    PRIMARY KEY (project, heat_rate_curves_scenario_id, period,
                 load_point_fraction),
    FOREIGN KEY (project, heat_rate_curves_scenario_id) REFERENCES
        subscenarios_project_heat_rate_curves (project, heat_rate_curves_scenario_id)
);

-- Variable O&M curves
-- TODO: see comments variable profiles
DROP TABLE IF EXISTS subscenarios_project_variable_om_curves;
CREATE TABLE subscenarios_project_variable_om_curves
(
    project                        VARCHAR(32),
    variable_om_curves_scenario_id INTEGER,
    name                           VARCHAR(32),
    description                    VARCHAR(128),
    PRIMARY KEY (project, variable_om_curves_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_variable_om_curves;
CREATE TABLE inputs_project_variable_om_curves
(
    project                          VARCHAR(64),
    variable_om_curves_scenario_id   INTEGER,
    period                           INTEGER, -- 0 means it's the same for all periods
    load_point_fraction              FLOAT,
    average_variable_om_cost_per_mwh FLOAT,
    PRIMARY KEY (project, variable_om_curves_scenario_id, period,
                 load_point_fraction),
    FOREIGN KEY (project, variable_om_curves_scenario_id) REFERENCES
        subscenarios_project_variable_om_curves (project,
                                                 variable_om_curves_scenario_id)
);

-- Startup characteristics
-- TODO: see comments variable profiles
DROP TABLE IF EXISTS subscenarios_project_startup_chars;
CREATE TABLE subscenarios_project_startup_chars
(
    project                   VARCHAR(32),
    startup_chars_scenario_id INTEGER,
    name                      VARCHAR(32),
    description               VARCHAR(128),
    PRIMARY KEY (project, startup_chars_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_startup_chars;
CREATE TABLE inputs_project_startup_chars
(
    project                   VARCHAR(64),
    startup_chars_scenario_id INTEGER,
    down_time_cutoff_hours    FLOAT,
    startup_plus_ramp_up_rate FLOAT,
    startup_cost_per_mw       FLOAT,
    PRIMARY KEY (project, startup_chars_scenario_id, down_time_cutoff_hours),
    FOREIGN KEY (project, startup_chars_scenario_id) REFERENCES
        subscenarios_project_startup_chars (project, startup_chars_scenario_id)
);

-- Cycle selection (e.g. plants that can operate in simple cycle or combined cycle mode)
DROP TABLE IF EXISTS subscenarios_project_cycle_selection;
CREATE TABLE subscenarios_project_cycle_selection
(
    project                     VARCHAR(32),
    cycle_selection_scenario_id INTEGER,
    name                        VARCHAR(32),
    description                 VARCHAR(128),
    PRIMARY KEY (project, cycle_selection_scenario_id)
);

-- If project is on, cycle_selection_project must be off
DROP TABLE IF EXISTS inputs_project_cycle_selection;
CREATE TABLE inputs_project_cycle_selection
(
    project                     VARCHAR(64),
    cycle_selection_scenario_id INTEGER,
    cycle_selection_project     VARCHAR(64),
    PRIMARY KEY (project, cycle_selection_scenario_id, cycle_selection_project),
    FOREIGN KEY (project, cycle_selection_scenario_id) REFERENCES
        subscenarios_project_cycle_selection (project, cycle_selection_scenario_id)
);


-- Supplemental firing
DROP TABLE IF EXISTS subscenarios_project_supplemental_firing;
CREATE TABLE subscenarios_project_supplemental_firing
(
    project                         VARCHAR(32),
    supplemental_firing_scenario_id INTEGER,
    name                            VARCHAR(32),
    description                     VARCHAR(128),
    PRIMARY KEY (project, supplemental_firing_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_supplemental_firing;
CREATE TABLE inputs_project_supplemental_firing
(
    project                         VARCHAR(64),
    supplemental_firing_scenario_id INTEGER,
    supplemental_firing_project     VARCHAR(64),
    PRIMARY KEY (project, supplemental_firing_scenario_id,
                 supplemental_firing_project),
    FOREIGN KEY (project, supplemental_firing_scenario_id) REFERENCES
        subscenarios_project_supplemental_firing (project, supplemental_firing_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_n_startup_limits;
CREATE TABLE subscenarios_project_n_startup_limits
(
    project                     VARCHAR(32),
    n_startup_limit_scenario_id INTEGER,
    name                        VARCHAR(32),
    description                 VARCHAR(128),
    PRIMARY KEY (project, n_startup_limit_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_n_startup_limits;
CREATE TABLE inputs_project_n_startup_limits
(
    project                     VARCHAR(64),
    n_startup_limit_scenario_id INTEGER,
    balancing_type_horizon      VARCHAR(32),
    horizon                     INTEGER,
    max_n_startups              FLOAT,
    PRIMARY KEY (project, n_startup_limit_scenario_id, balancing_type_horizon,
                 horizon),
    FOREIGN KEY (project, n_startup_limit_scenario_id) REFERENCES
        subscenarios_project_startup_chars (project, startup_chars_scenario_id)
);

-- Flex load static profiles
-- The profiles by end use before shifting
DROP TABLE IF EXISTS subscenarios_project_flex_load_static_profiles;
CREATE TABLE subscenarios_project_flex_load_static_profiles
(
    project                              VARCHAR(64),
    flex_load_static_profile_scenario_id INTEGER,
    name                                 VARCHAR(32),
    description                          VARCHAR(128),
    PRIMARY KEY (project, flex_load_static_profile_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_flex_load_static_profiles;
CREATE TABLE inputs_project_flex_load_static_profiles
(
    project                              VARCHAR(64),
    flex_load_static_profile_scenario_id INTEGER,
    stage_id                             INTEGER,
    timepoint                            INTEGER,
    static_load_mw                       FLOAT,
    maximum_stored_energy_mwh            FLOAT,
    PRIMARY KEY (project, flex_load_static_profile_scenario_id, stage_id,
                 timepoint),
    FOREIGN KEY (project, flex_load_static_profile_scenario_id) REFERENCES
        subscenarios_project_flex_load_static_profiles
            (project, flex_load_static_profile_scenario_id)
);


-- Variable generator profiles
-- TODO: this is not exactly a subscenario, as a variable profile will be
-- assigned to variable projects in the project_operational_chars table and
-- be passed to scenarios via the project_operational_chars_scenario_id
-- perhaps a better name is needed for this table

DROP TABLE IF EXISTS subscenarios_project_variable_generator_profiles;
CREATE TABLE subscenarios_project_variable_generator_profiles
(
    project                                VARCHAR(64),
    variable_generator_profile_scenario_id INTEGER,
    name                                   VARCHAR(32),
    description                            VARCHAR(128),
    PRIMARY KEY (project, variable_generator_profile_scenario_id)
);

-- Variable generator profiles by weather year and stage
-- (Subproblem is omitted, as timepoints in a temporal scenario ID must be
-- unique -- they can then be subdivided into different subproblems for other
-- temporal scenario IDs)
DROP TABLE IF EXISTS inputs_project_variable_generator_profiles;
CREATE TABLE inputs_project_variable_generator_profiles
(
    project                                VARCHAR(64),
    variable_generator_profile_scenario_id INTEGER,
    weather_iteration                      INTEGER,
    hydro_iteration                        INTEGER,
    stage_id                               INTEGER,
    timepoint                              INTEGER,
    cap_factor                             FLOAT,
    PRIMARY KEY (project, variable_generator_profile_scenario_id,
                 weather_iteration, hydro_iteration, stage_id, timepoint),
    FOREIGN KEY (project, variable_generator_profile_scenario_id) REFERENCES
        subscenarios_project_variable_generator_profiles
            (project, variable_generator_profile_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_variable_generator_profiles_iterations;
CREATE TABLE inputs_project_variable_generator_profiles_iterations
(
    project                                TEXT,
    variable_generator_profile_scenario_id INTEGER,
    varies_by_weather_iteration            INTEGER,
    varies_by_hydro_iteration              INTEGER,
    PRIMARY KEY (project, variable_generator_profile_scenario_id)
);

-- Variable O&M by period
DROP TABLE IF EXISTS subscenarios_project_curtailment_cost;
CREATE TABLE subscenarios_project_curtailment_cost
(
    project                      VARCHAR(32),
    curtailment_cost_scenario_id INTEGER,
    name                         VARCHAR(32),
    description                  VARCHAR(128),
    PRIMARY KEY (project, curtailment_cost_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_curtailment_cost;
CREATE TABLE inputs_project_curtailment_cost
(
    project                            VARCHAR(64),
    curtailment_cost_scenario_id       INTEGER,
    period                             INTEGER, -- 0 means it's the same for all periods
    curtailment_cost_per_powerunithour FLOAT,
    PRIMARY KEY (project, curtailment_cost_scenario_id, period),
    FOREIGN KEY (project, curtailment_cost_scenario_id) REFERENCES
        subscenarios_project_curtailment_cost (project, curtailment_cost_scenario_id)
);

-- Hydro operational characteristics
DROP TABLE IF EXISTS subscenarios_project_hydro_operational_chars;
CREATE TABLE subscenarios_project_hydro_operational_chars
(
    project                             VARCHAR(64),
    hydro_operational_chars_scenario_id INTEGER,
    name                                VARCHAR(32),
    description                         VARCHAR(128),
    PRIMARY KEY (project, hydro_operational_chars_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_hydro_operational_chars;
CREATE TABLE inputs_project_hydro_operational_chars
(
    project                             VARCHAR(64),
    hydro_operational_chars_scenario_id INTEGER,
    weather_iteration                   INTEGER,
    hydro_iteration                     INTEGER DEFAULT 0 NOT NULL,
    stage_id                            INTEGER,
    balancing_type_project              VARCHAR(64),
    horizon                             INTEGER,
    average_power_fraction              FLOAT,
    min_power_fraction                  FLOAT,
    max_power_fraction                  FLOAT,
    PRIMARY KEY (project, hydro_operational_chars_scenario_id,
                 weather_iteration, hydro_iteration, stage_id,
                 balancing_type_project, horizon),
    FOREIGN KEY (project, hydro_operational_chars_scenario_id) REFERENCES
        subscenarios_project_hydro_operational_chars
            (project, hydro_operational_chars_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_hydro_operational_chars_iterations;
CREATE TABLE inputs_project_hydro_operational_chars_iterations
(
    project                             TEXT,
    hydro_operational_chars_scenario_id INTEGER,
    varies_by_weather_iteration         INTEGER,
    varies_by_hydro_iteration           INTEGER,
    PRIMARY KEY (project, hydro_operational_chars_scenario_id)
);

-- Energy profiles
DROP TABLE IF EXISTS subscenarios_project_energy_profiles;
CREATE TABLE subscenarios_project_energy_profiles
(
    project                    VARCHAR(64),
    energy_profile_scenario_id INTEGER,
    name                       VARCHAR(32),
    description                VARCHAR(128),
    PRIMARY KEY (project, energy_profile_scenario_id)
);

-- Energy profiles by weather year and stage
-- (Subproblem is omitted, as timepoints in a temporal scenario ID must be
-- unique -- they can then be subdivided into different subproblems for other
-- temporal scenario IDs)
DROP TABLE IF EXISTS inputs_project_energy_profiles;
CREATE TABLE inputs_project_energy_profiles
(
    project                    VARCHAR(64),
    energy_profile_scenario_id INTEGER,
    weather_iteration          INTEGER,
    hydro_iteration            INTEGER,
    stage_id                   INTEGER,
    timepoint                  INTEGER,
    energy_fraction            FLOAT,
    PRIMARY KEY (project, energy_profile_scenario_id,
                 weather_iteration, hydro_iteration, stage_id, timepoint),
    FOREIGN KEY (project, energy_profile_scenario_id) REFERENCES
        subscenarios_project_energy_profiles
            (project, energy_profile_scenario_id)
);

DROP TABLE IF EXISTS
    subscenarios_project_energy_profiles_iterations;
CREATE TABLE subscenarios_project_energy_profiles_iterations
(
    project                    VARCHAR(64),
    energy_profile_scenario_id INTEGER,
    name                       VARCHAR(32),
    description                VARCHAR(128),
    PRIMARY KEY (project, energy_profile_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_energy_profiles_iterations;
CREATE TABLE inputs_project_energy_profiles_iterations
(
    project                     TEXT,
    energy_profile_scenario_id  INTEGER,
    varies_by_weather_iteration INTEGER,
    varies_by_hydro_iteration   INTEGER,
    PRIMARY KEY (project, energy_profile_scenario_id)
);


-- Energy horizon shaping params
DROP TABLE IF EXISTS subscenarios_project_energy_hrz_shaping;
CREATE TABLE subscenarios_project_energy_hrz_shaping
(
    project                        VARCHAR(64),
    energy_hrz_shaping_scenario_id INTEGER,
    name                           VARCHAR(32),
    description                    VARCHAR(128),
    PRIMARY KEY (project, energy_hrz_shaping_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_energy_hrz_shaping;
CREATE TABLE inputs_project_energy_hrz_shaping
(
    project                        VARCHAR(64),
    energy_hrz_shaping_scenario_id INTEGER,
    weather_iteration              INTEGER,
    hydro_iteration                INTEGER,
    stage_id                       INTEGER,
    balancing_type_project         TEXT,
    horizon                        INTEGER,
    hrz_energy_fraction            FLOAT,
    min_power                      FLOAT,
    max_power                      FLOAT,
    PRIMARY KEY (project, energy_hrz_shaping_scenario_id,
                 weather_iteration, hydro_iteration, stage_id,
                 balancing_type_project, horizon),
    FOREIGN KEY (project, energy_hrz_shaping_scenario_id) REFERENCES
        subscenarios_project_energy_hrz_shaping
            (project, energy_hrz_shaping_scenario_id)
);

DROP TABLE IF EXISTS
    subscenarios_project_energy_hrz_shaping_iterations;
CREATE TABLE subscenarios_project_energy_hrz_shaping_iterations
(
    project                        VARCHAR(64),
    energy_hrz_shaping_scenario_id INTEGER,
    name                           VARCHAR(32),
    description                    VARCHAR(128),
    PRIMARY KEY (project, energy_hrz_shaping_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_energy_hrz_shaping_iterations;
CREATE TABLE inputs_project_energy_hrz_shaping_iterations
(
    project                        TEXT,
    energy_hrz_shaping_scenario_id INTEGER,
    varies_by_weather_iteration    INTEGER,
    varies_by_hydro_iteration      INTEGER,
    PRIMARY KEY (project, energy_hrz_shaping_scenario_id)
);


-- Energy slice horizon shaping params
DROP TABLE IF EXISTS subscenarios_project_energy_slice_hrz_shaping;
CREATE TABLE subscenarios_project_energy_slice_hrz_shaping
(
    project                              VARCHAR(64),
    energy_slice_hrz_shaping_scenario_id INTEGER,
    name                                 VARCHAR(32),
    description                          VARCHAR(128),
    PRIMARY KEY (project, energy_slice_hrz_shaping_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_energy_slice_hrz_shaping;
CREATE TABLE inputs_project_energy_slice_hrz_shaping
(
    project                              VARCHAR(64),
    energy_slice_hrz_shaping_scenario_id INTEGER,
    weather_iteration                    INTEGER,
    hydro_iteration                      INTEGER,
    stage_id                             INTEGER,
    balancing_type_project               TEXT,
    horizon                              INTEGER,
    hrz_energy                           FLOAT,
    min_power                            FLOAT,
    max_power                            FLOAT,
    PRIMARY KEY (project, energy_slice_hrz_shaping_scenario_id,
                 weather_iteration, hydro_iteration, stage_id,
                 balancing_type_project, horizon),
    FOREIGN KEY (project, energy_slice_hrz_shaping_scenario_id) REFERENCES
        subscenarios_project_energy_slice_hrz_shaping
            (project, energy_slice_hrz_shaping_scenario_id)
);

DROP TABLE IF EXISTS
    subscenarios_project_energy_slice_hrz_shaping_iterations;
CREATE TABLE subscenarios_project_energy_slice_hrz_shaping_iterations
(
    project                              VARCHAR(64),
    energy_slice_hrz_shaping_scenario_id INTEGER,
    name                                 VARCHAR(32),
    description                          VARCHAR(128),
    PRIMARY KEY (project, energy_slice_hrz_shaping_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_energy_slice_hrz_shaping_iterations;
CREATE TABLE inputs_project_energy_slice_hrz_shaping_iterations
(
    project                              TEXT,
    energy_slice_hrz_shaping_scenario_id INTEGER,
    varies_by_weather_iteration          INTEGER,
    varies_by_hydro_iteration            INTEGER,
    PRIMARY KEY (project, energy_slice_hrz_shaping_scenario_id)
);

-- Demand charge (peak deviation from average by month)
DROP TABLE IF EXISTS subscenarios_project_peak_deviation_demand_charges;
CREATE TABLE subscenarios_project_peak_deviation_demand_charges
(
    project                                  VARCHAR(64),
    peak_deviation_demand_charge_scenario_id INTEGER,
    name                                     VARCHAR(32),
    description                              VARCHAR(128),
    PRIMARY KEY (project, peak_deviation_demand_charge_scenario_id)
);

-- Doesn't vary by weather and hydro iteration for now
DROP TABLE IF EXISTS inputs_project_peak_deviation_demand_charges;
CREATE TABLE inputs_project_peak_deviation_demand_charges
(
    project                                  VARCHAR(64),
    peak_deviation_demand_charge_scenario_id INTEGER,
    period                                   FLOAT,
    month                                    INTEGER,
    peak_deviation_demand_charge_per_mw      FLOAT,
    PRIMARY KEY (project, peak_deviation_demand_charge_scenario_id, period,
                 month),
    FOREIGN KEY (project, peak_deviation_demand_charge_scenario_id) REFERENCES
        subscenarios_project_peak_deviation_demand_charges
            (project, peak_deviation_demand_charge_scenario_id)
);

-- Load following energy product
DROP TABLE IF EXISTS subscenarios_project_base_net_requirements;
CREATE TABLE subscenarios_project_base_net_requirements
(
    project                          VARCHAR(64),
    base_net_requirement_scenario_id INTEGER,
    name                             VARCHAR(32),
    description                      VARCHAR(128),
    PRIMARY KEY (project, base_net_requirement_scenario_id)
);

-- Doesn't vary by weather and hydro iteration for now
DROP TABLE IF EXISTS inputs_project_base_net_requirements;
CREATE TABLE inputs_project_base_net_requirements
(
    project                          VARCHAR(64),
    base_net_requirement_scenario_id INTEGER,
    period                           FLOAT,
    base_net_requirement_mwh         FLOAT,
    PRIMARY KEY (project, base_net_requirement_scenario_id, period),
    FOREIGN KEY (project, base_net_requirement_scenario_id) REFERENCES
        subscenarios_project_base_net_requirements
            (project, base_net_requirement_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_load_modifier_profiles;
CREATE TABLE subscenarios_project_load_modifier_profiles
(
    project                           VARCHAR(64),
    load_modifier_profile_scenario_id INTEGER,
    name                              VARCHAR(32),
    description                       VARCHAR(128),
    PRIMARY KEY (project, load_modifier_profile_scenario_id)
);

-- Variable generator profiles by weather year and stage
-- (Subproblem is omitted, as timepoints in a temporal scenario ID must be
-- unique -- they can then be subdivided into different subproblems for other
-- temporal scenario IDs)
DROP TABLE IF EXISTS inputs_project_load_modifier_profiles;
CREATE TABLE inputs_project_load_modifier_profiles
(
    project                           VARCHAR(64),
    load_modifier_profile_scenario_id INTEGER,
    weather_iteration                 INTEGER,
    hydro_iteration                   INTEGER,
    stage_id                          INTEGER,
    timepoint                         INTEGER,
    fraction                          FLOAT,
    PRIMARY KEY (project, load_modifier_profile_scenario_id,
                 weather_iteration, hydro_iteration, stage_id, timepoint),
    FOREIGN KEY (project, load_modifier_profile_scenario_id) REFERENCES
        subscenarios_project_load_modifier_profiles
            (project, load_modifier_profile_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_load_modifier_profiles_iterations;
CREATE TABLE inputs_project_load_modifier_profiles_iterations
(
    project                           TEXT,
    load_modifier_profile_scenario_id INTEGER,
    varies_by_weather_iteration       INTEGER,
    varies_by_hydro_iteration         INTEGER,
    PRIMARY KEY (project, load_modifier_profile_scenario_id)
);


-- Hydro operational characteristics
DROP TABLE IF EXISTS subscenarios_project_load_component_shift_bounds;
CREATE TABLE subscenarios_project_load_component_shift_bounds
(
    project                                 VARCHAR(64),
    load_component_shift_bounds_scenario_id INTEGER,
    name                                    VARCHAR(32),
    description                             VARCHAR(128),
    PRIMARY KEY (project, load_component_shift_bounds_scenario_id)
);


DROP TABLE IF EXISTS inputs_project_load_component_shift_bounds;
CREATE TABLE inputs_project_load_component_shift_bounds
(
    project                                 VARCHAR(64),
    load_component_shift_bounds_scenario_id INTEGER,
    weather_iteration                       INTEGER,
    hydro_iteration                         INTEGER,
    balancing_type_project                  VARCHAR(64), -- does not need to
    -- match project balancing type; column like this for legacy reasons
    horizon                                 INTEGER,
    min_load_mw                             FLOAT,
    max_load_mw                             FLOAT,
    PRIMARY KEY (project, load_component_shift_bounds_scenario_id,
                 weather_iteration, hydro_iteration,
                 balancing_type_project, horizon),
    FOREIGN KEY (project, load_component_shift_bounds_scenario_id) REFERENCES
        subscenarios_project_load_component_shift_bounds
            (project, load_component_shift_bounds_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_load_component_shift_bounds_iterations;
CREATE TABLE inputs_project_load_component_shift_bounds_iterations
(
    project                                 VARCHAR(64),
    load_component_shift_bounds_scenario_id INTEGER,
    varies_by_weather_iteration             INTEGER,
    varies_by_hydro_iteration               INTEGER,
    PRIMARY KEY (project, load_component_shift_bounds_scenario_id)
);


-- Storage exogenously specified state of charge
DROP TABLE IF EXISTS subscenarios_project_stor_exog_state_of_charge;
CREATE TABLE subscenarios_project_stor_exog_state_of_charge
(
    project                               VARCHAR(64),
    stor_exog_state_of_charge_scenario_id INTEGER,
    name                                  VARCHAR(32),
    description                           VARCHAR(128),
    PRIMARY KEY (project, stor_exog_state_of_charge_scenario_id)
);

-- TODO: probably need to add subproblem id to other tables also
DROP TABLE IF EXISTS inputs_project_stor_exog_state_of_charge;
CREATE TABLE inputs_project_stor_exog_state_of_charge
(
    project                               VARCHAR(64),
    stor_exog_state_of_charge_scenario_id INTEGER,
    weather_iteration                     INTEGER,
    hydro_iteration                       INTEGER,
    stage_id                              INTEGER,
    timepoint                             INTEGER,
    exog_state_of_charge_mwh              FLOAT,
    PRIMARY KEY (project, stor_exog_state_of_charge_scenario_id,
                 weather_iteration, hydro_iteration, stage_id, timepoint),
    FOREIGN KEY (project, stor_exog_state_of_charge_scenario_id) REFERENCES
        subscenarios_project_stor_exog_state_of_charge
            (project, stor_exog_state_of_charge_scenario_id)
);

DROP TABLE IF EXISTS
    subscenarios_project_stor_exog_state_of_charge_iterations;
CREATE TABLE subscenarios_project_stor_exog_state_of_charge_iterations
(
    project                               VARCHAR(64),
    stor_exog_state_of_charge_scenario_id INTEGER,
    name                                  VARCHAR(32),
    description                           VARCHAR(128),
    PRIMARY KEY (project, stor_exog_state_of_charge_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_stor_exog_state_of_charge_iterations;
CREATE TABLE inputs_project_stor_exog_state_of_charge_iterations
(
    project                               TEXT,
    stor_exog_state_of_charge_scenario_id INTEGER,
    varies_by_weather_iteration           INTEGER,
    varies_by_hydro_iteration             INTEGER,
    PRIMARY KEY (project, stor_exog_state_of_charge_scenario_id)
);

-- Cap factor limits
DROP TABLE IF EXISTS subscenarios_project_cap_factor_limits;
CREATE TABLE subscenarios_project_cap_factor_limits
(
    project                       VARCHAR(64),
    cap_factor_limits_scenario_id INTEGER,
    name                          VARCHAR(32),
    description                   VARCHAR(128),
    PRIMARY KEY (project, cap_factor_limits_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_cap_factor_limits;
CREATE TABLE inputs_project_cap_factor_limits
(
    project                       VARCHAR(64),
    cap_factor_limits_scenario_id INTEGER,
    balancing_type_horizon        VARCHAR(64),
    horizon                       INTEGER,
    min_cap_factor                FLOAT,
    max_cap_factor                FLOAT,
    PRIMARY KEY (project, cap_factor_limits_scenario_id, balancing_type_horizon,
                 horizon),
    FOREIGN KEY (project, cap_factor_limits_scenario_id) REFERENCES
        subscenarios_project_cap_factor_limits (project, cap_factor_limits_scenario_id)
);

-- Group capacity requirements
-- Requirements
DROP TABLE IF EXISTS subscenarios_project_power_output_group_requirements;
CREATE TABLE subscenarios_project_power_output_group_requirements
(
    project_power_output_group_requirement_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                               VARCHAR(32),
    description                                        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_power_output_group_requirements;
CREATE TABLE inputs_project_power_output_group_requirements
(
    project_power_output_group_requirement_scenario_id INTEGER,
    power_output_group                                 VARCHAR(64),
    period                                             INTEGER,
    power_output_group_total_power_min                 FLOAT,
    power_output_group_total_power_max                 FLOAT,
    PRIMARY KEY (project_power_output_group_requirement_scenario_id,
                 power_output_group, period),
    FOREIGN KEY (project_power_output_group_requirement_scenario_id) REFERENCES
        subscenarios_project_power_output_group_requirements
            (project_power_output_group_requirement_scenario_id)
);

-- Group project mapping
DROP TABLE IF EXISTS subscenarios_project_power_output_groups;
CREATE TABLE subscenarios_project_power_output_groups
(
    project_power_output_group_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_power_output_groups;
CREATE TABLE inputs_project_power_output_groups
(
    project_power_output_group_scenario_id INTEGER,
    power_output_group                     VARCHAR(64),
    project                                VARCHAR(64),
    PRIMARY KEY (project_power_output_group_scenario_id, power_output_group,
                 project),
    FOREIGN KEY (project_power_output_group_scenario_id) REFERENCES
        subscenarios_project_power_output_groups (project_power_output_group_scenario_id)
);

-- Bt-hrz ramp up rate limits
DROP TABLE IF EXISTS subscenarios_project_bt_hrz_ramp_up_rate_limits;
CREATE TABLE subscenarios_project_bt_hrz_ramp_up_rate_limits
(
    project                               VARCHAR(64),
    bt_hrz_ramp_up_rate_limit_scenario_id INTEGER,
    name                                  VARCHAR(32),
    description                           VARCHAR(128),
    PRIMARY KEY (project, bt_hrz_ramp_up_rate_limit_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_bt_hrz_ramp_up_rate_limits;
CREATE TABLE inputs_project_bt_hrz_ramp_up_rate_limits
(
    project                               VARCHAR(64),
    bt_hrz_ramp_up_rate_limit_scenario_id INTEGER,
    balancing_type                        INTEGER,
    horizon                               FLOAT,
    ramp_up_rate_limit_mw_per_hour        FLOAT,
    PRIMARY KEY (project, bt_hrz_ramp_up_rate_limit_scenario_id,
                 balancing_type, horizon),
    FOREIGN KEY (project, bt_hrz_ramp_up_rate_limit_scenario_id) REFERENCES
        subscenarios_project_bt_hrz_ramp_up_rate_limits
            (project, bt_hrz_ramp_up_rate_limit_scenario_id)
);

-- Bt-hrz ramp down rate limits
DROP TABLE IF EXISTS subscenarios_project_bt_hrz_ramp_down_rate_limits;
CREATE TABLE subscenarios_project_bt_hrz_ramp_down_rate_limits
(
    project                                 VARCHAR(64),
    bt_hrz_ramp_down_rate_limit_scenario_id INTEGER,
    name                                    VARCHAR(32),
    description                             VARCHAR(128),
    PRIMARY KEY (project, bt_hrz_ramp_down_rate_limit_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_bt_hrz_ramp_down_rate_limits;
CREATE TABLE inputs_project_bt_hrz_ramp_down_rate_limits
(
    project                                 VARCHAR(64),
    bt_hrz_ramp_down_rate_limit_scenario_id INTEGER,
    balancing_type                          INTEGER,
    horizon                                 FLOAT,
    ramp_down_rate_limit_mw_per_hour        FLOAT,
    PRIMARY KEY (project, bt_hrz_ramp_down_rate_limit_scenario_id,
                 balancing_type, horizon),
    FOREIGN KEY (project, bt_hrz_ramp_down_rate_limit_scenario_id) REFERENCES
        subscenarios_project_bt_hrz_ramp_down_rate_limits
            (project, bt_hrz_ramp_down_rate_limit_scenario_id)
);

-- Total ramp up limits
DROP TABLE IF EXISTS subscenarios_project_total_ramp_up_limits;
CREATE TABLE subscenarios_project_total_ramp_up_limits
(
    project                         VARCHAR(64),
    total_ramp_up_limit_scenario_id INTEGER,
    name                            VARCHAR(32),
    description                     VARCHAR(128),
    PRIMARY KEY (project, total_ramp_up_limit_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_total_ramp_up_limits;
CREATE TABLE inputs_project_total_ramp_up_limits
(
    project                         VARCHAR(64),
    total_ramp_up_limit_scenario_id INTEGER,
    balancing_type                  INTEGER,
    horizon                         FLOAT,
    total_ramp_up_limit_mw          FLOAT,
    PRIMARY KEY (project, total_ramp_up_limit_scenario_id,
                 balancing_type, horizon),
    FOREIGN KEY (project, total_ramp_up_limit_scenario_id) REFERENCES
        subscenarios_project_total_ramp_up_limits
            (project, total_ramp_up_limit_scenario_id)
);

-- Total ramp down limits
DROP TABLE IF EXISTS subscenarios_project_total_ramp_down_limits;
CREATE TABLE subscenarios_project_total_ramp_down_limits
(
    project                           VARCHAR(64),
    total_ramp_down_limit_scenario_id INTEGER,
    name                              VARCHAR(32),
    description                       VARCHAR(128),
    PRIMARY KEY (project, total_ramp_down_limit_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_total_ramp_down_limits;
CREATE TABLE inputs_project_total_ramp_down_limits
(
    project                           VARCHAR(64),
    total_ramp_down_limit_scenario_id INTEGER,
    balancing_type                    INTEGER,
    horizon                           FLOAT,
    total_ramp_down_limit_mw          FLOAT,
    PRIMARY KEY (project, total_ramp_down_limit_scenario_id,
                 balancing_type, horizon),
    FOREIGN KEY (project, total_ramp_down_limit_scenario_id) REFERENCES
        subscenarios_project_total_ramp_down_limits
            (project, total_ramp_down_limit_scenario_id)
);

-- Demand charge (peak deviation from average by month)
DROP TABLE IF EXISTS
    subscenarios_project_ramp_up_when_on_rate_monthly_adjustments;
CREATE TABLE subscenarios_project_ramp_up_when_on_rate_monthly_adjustments
(
    project                                             VARCHAR(64),
    ramp_up_when_on_rate_monthly_adjustment_scenario_id INTEGER,
    name                                                VARCHAR(32),
    description                                         VARCHAR(128),
    PRIMARY KEY (project,
                 ramp_up_when_on_rate_monthly_adjustment_scenario_id)
);

-- Doesn't vary by weather and hydro iteration for now
DROP TABLE IF EXISTS inputs_project_ramp_up_when_on_rate_monthly_adjustments;
CREATE TABLE inputs_project_ramp_up_when_on_rate_monthly_adjustments
(
    project                                             VARCHAR(64),
    ramp_up_when_on_rate_monthly_adjustment_scenario_id INTEGER,
    period                                              INTEGER,
    month                                               INTEGER,
    monthly_adjustment                                  FLOAT,
    PRIMARY KEY (project,
                 ramp_up_when_on_rate_monthly_adjustment_scenario_id,
                 period, month),
    FOREIGN KEY (project,
                 ramp_up_when_on_rate_monthly_adjustment_scenario_id) REFERENCES
        subscenarios_project_ramp_up_when_on_rate_monthly_adjustments
            (project, ramp_up_when_on_rate_monthly_adjustment_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_ramp_down_when_on_rate_monthly_adjustments;
CREATE TABLE subscenarios_project_ramp_down_when_on_rate_monthly_adjustments
(
    project                                               VARCHAR(64),
    ramp_down_when_on_rate_monthly_adjustment_scenario_id INTEGER,
    name                                                  VARCHAR(32),
    description                                           VARCHAR(128),
    PRIMARY KEY (project,
                 ramp_down_when_on_rate_monthly_adjustment_scenario_id)
);

-- Doesn't vary by weather and hydro iteration for now
DROP TABLE IF EXISTS inputs_project_ramp_down_when_on_rate_monthly_adjustments;
CREATE TABLE inputs_project_ramp_down_when_on_rate_monthly_adjustments
(
    project                                               VARCHAR(64),
    ramp_down_when_on_rate_monthly_adjustment_scenario_id INTEGER,
    period                                                INTEGER,
    month                                                 INTEGER,
    monthly_adjustment                                    FLOAT,
    PRIMARY KEY (project,
                 ramp_down_when_on_rate_monthly_adjustment_scenario_id,
                 period, month),
    FOREIGN KEY (project,
                 ramp_down_when_on_rate_monthly_adjustment_scenario_id) REFERENCES
        subscenarios_project_ramp_down_when_on_rate_monthly_adjustments
            (project,
             ramp_down_when_on_rate_monthly_adjustment_scenario_id)
);


-- Project availability (e.g. due to planned outages/availability)
-- Subscenarios
DROP TABLE IF EXISTS subscenarios_project_availability;
CREATE TABLE subscenarios_project_availability
(
    project_availability_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                             VARCHAR(32),
    description                      VARCHAR(128)
);

-- Define availability type and IDs for type characteristics
-- TODO: implement check that there are exogenous IDs only for exogenous
--  types and endogenous IDs only for endogenous types
DROP TABLE IF EXISTS inputs_project_availability;
CREATE TABLE inputs_project_availability
(
    project_availability_scenario_id                      INTEGER,
    project                                               VARCHAR(64),
    availability_type                                     VARCHAR(32),
    exogenous_availability_independent_scenario_id        INTEGER,
    exogenous_availability_weather_scenario_id            INTEGER,
    exogenous_availability_independent_bt_hrz_scenario_id INTEGER,
    exogenous_availability_weather_bt_hrz_scenario_id     INTEGER,
    exogenous_availability_monthly_scenario_id            INTEGER,
    endogenous_availability_scenario_id                   INTEGER,
    PRIMARY KEY (project_availability_scenario_id, project, availability_type)
);

DROP TABLE IF EXISTS subscenarios_project_availability_exogenous_independent;
CREATE TABLE subscenarios_project_availability_exogenous_independent
(
    project                                        VARCHAR(64),
    exogenous_availability_independent_scenario_id INTEGER,
    name                                           VARCHAR(32),
    description                                    VARCHAR(128),
    PRIMARY KEY (project, exogenous_availability_independent_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_availability_exogenous_independent;
CREATE TABLE inputs_project_availability_exogenous_independent
(
    project                                        VARCHAR(64),
    exogenous_availability_independent_scenario_id INTEGER,
    availability_iteration                         INTEGER,
    stage_id                                       INTEGER,
    timepoint                                      INTEGER,
    availability_derate_independent                FLOAT, -- for hybrids, this is the gen av
    hyb_stor_cap_availability_derate_independent   FLOAT,
    PRIMARY KEY (project, exogenous_availability_independent_scenario_id,
                 availability_iteration, stage_id, timepoint),
    FOREIGN KEY (project, exogenous_availability_independent_scenario_id)
        REFERENCES subscenarios_project_availability_exogenous_independent
            (project, exogenous_availability_independent_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_availability_exogenous_weather;
CREATE TABLE subscenarios_project_availability_exogenous_weather
(
    project                                    VARCHAR(64),
    exogenous_availability_weather_scenario_id INTEGER,
    name                                       VARCHAR(32),
    description                                VARCHAR(128),
    PRIMARY KEY (project, exogenous_availability_weather_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_availability_exogenous_weather;
CREATE TABLE inputs_project_availability_exogenous_weather
(
    project                                    VARCHAR(64),
    exogenous_availability_weather_scenario_id INTEGER,
    weather_iteration                          INTEGER,
    stage_id                                   INTEGER,
    timepoint                                  INTEGER,
    availability_derate_weather                FLOAT,
    PRIMARY KEY (project, exogenous_availability_weather_scenario_id,
                 weather_iteration, stage_id, timepoint),
    FOREIGN KEY (project, exogenous_availability_weather_scenario_id)
        REFERENCES subscenarios_project_availability_exogenous_weather
            (project, exogenous_availability_weather_scenario_id)
);


DROP TABLE IF EXISTS subscenarios_project_availability_exogenous_independent_bt_hrz;
CREATE TABLE subscenarios_project_availability_exogenous_independent_bt_hrz
(
    project                                               VARCHAR(64),
    exogenous_availability_independent_bt_hrz_scenario_id INTEGER,
    name                                                  VARCHAR(32),
    description                                           VARCHAR(128),
    PRIMARY KEY (project, exogenous_availability_independent_bt_hrz_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_availability_exogenous_independent_bt_hrz;
CREATE TABLE inputs_project_availability_exogenous_independent_bt_hrz
(
    project                                               VARCHAR(64),
    exogenous_availability_independent_bt_hrz_scenario_id INTEGER,
    availability_iteration                                INTEGER,
    stage_id                                              INTEGER,
    balancing_type_project                                TEXT,
    horizon                                               INTEGER,
    availability_derate_independent_bt_hrz                FLOAT,
    PRIMARY KEY (project, exogenous_availability_independent_bt_hrz_scenario_id,
                 availability_iteration, stage_id, balancing_type_project,
                 horizon),
    FOREIGN KEY (project, exogenous_availability_independent_bt_hrz_scenario_id)
        REFERENCES subscenarios_project_availability_exogenous_independent_bt_hrz
            (project, exogenous_availability_independent_bt_hrz_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_availability_exogenous_weather_bt_hrz;
CREATE TABLE subscenarios_project_availability_exogenous_weather_bt_hrz
(
    project                                           VARCHAR(64),
    exogenous_availability_weather_bt_hrz_scenario_id INTEGER,
    name                                              VARCHAR(32),
    description                                       VARCHAR(128),
    PRIMARY KEY (project, exogenous_availability_weather_bt_hrz_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_availability_exogenous_weather_bt_hrz;
CREATE TABLE inputs_project_availability_exogenous_weather_bt_hrz
(
    project                                           VARCHAR(64),
    exogenous_availability_weather_bt_hrz_scenario_id INTEGER,
    weather_iteration                                 INTEGER,
    stage_id                                          INTEGER,
    balancing_type_project                            TEXT,
    horizon                                           INTEGER,
    availability_derate_weather_bt_hrz                FLOAT,
    PRIMARY KEY (project, exogenous_availability_weather_bt_hrz_scenario_id,
                 weather_iteration, stage_id, balancing_type_project, horizon),
    FOREIGN KEY (project, exogenous_availability_weather_bt_hrz_scenario_id)
        REFERENCES subscenarios_project_availability_exogenous_weather_bt_hrz
            (project, exogenous_availability_weather_bt_hrz_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_availability_exogenous_monthly;
CREATE TABLE subscenarios_project_availability_exogenous_monthly
(
    project                                    VARCHAR(64),
    exogenous_availability_monthly_scenario_id INTEGER,
    name                                       VARCHAR(32),
    description                                VARCHAR(128),
    PRIMARY KEY (project, exogenous_availability_monthly_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_availability_exogenous_monthly;
CREATE TABLE inputs_project_availability_exogenous_monthly
(
    project                                    VARCHAR(64),
    exogenous_availability_monthly_scenario_id INTEGER,
    month                                      INTEGER,
    availability_derate_monthly                FLOAT,
    PRIMARY KEY (project, exogenous_availability_monthly_scenario_id,
                 month),
    FOREIGN KEY (project, exogenous_availability_monthly_scenario_id)
        REFERENCES subscenarios_project_availability_exogenous_monthly
            (project, exogenous_availability_monthly_scenario_id)
);


DROP TABLE IF EXISTS subscenarios_project_availability_endogenous;
CREATE TABLE subscenarios_project_availability_endogenous
(
    project                             VARCHAR(64),
    endogenous_availability_scenario_id INTEGER,
    name                                VARCHAR(32),
    description                         VARCHAR(128),
    PRIMARY KEY (project, endogenous_availability_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_availability_endogenous;
CREATE TABLE inputs_project_availability_endogenous
(
    project                                    VARCHAR(64),
    endogenous_availability_scenario_id        INTEGER,
    unavailable_hours_per_period               FLOAT,
    unavailable_hours_per_period_require_exact FLOAT,
    unavailable_hours_per_event_min            FLOAT,
    available_hours_between_events_min         FLOAT,
    PRIMARY KEY (project, endogenous_availability_scenario_id),
    FOREIGN KEY (project, endogenous_availability_scenario_id)
        REFERENCES subscenarios_project_availability_endogenous
            (project, endogenous_availability_scenario_id)
);


-- Project load zones
-- Where projects are modeled to be physically located
-- Depends on the load_zone_scenario_id, i.e. how geography is modeled
-- (project can be in one zone if modeling a single zone, but a different
-- zone if modeling several zones, etc.)
DROP TABLE IF EXISTS subscenarios_project_load_zones;
CREATE TABLE subscenarios_project_load_zones
(
    project_load_zone_scenario_id INTEGER PRIMARY KEY,
    name                          VARCHAR(32),
    description                   VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_load_zones;
CREATE TABLE inputs_project_load_zones
(
    project_load_zone_scenario_id INTEGER,
    project                       VARCHAR(64),
    load_zone                     VARCHAR(32),
    PRIMARY KEY (project_load_zone_scenario_id, project),
    FOREIGN KEY (project_load_zone_scenario_id) REFERENCES
        subscenarios_project_load_zones (project_load_zone_scenario_id)
);

-- Project BAs
-- Which projects can contribute to a reserve requirement
-- Depends on how reserve balancing area are specified (xyz_ba_scenario_id)
-- This table can included all project with NULLs for projects not
-- contributing or just the contributing projects
DROP TABLE IF EXISTS subscenarios_project_lf_reserves_up_bas;
CREATE TABLE subscenarios_project_lf_reserves_up_bas
(
    project_lf_reserves_up_ba_scenario_id INTEGER PRIMARY KEY,
    name                                  VARCHAR(32),
    description                           VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_lf_reserves_up_bas;
CREATE TABLE inputs_project_lf_reserves_up_bas
(
    project_lf_reserves_up_ba_scenario_id INTEGER,
    project                               VARCHAR(64),
    lf_reserves_up_ba                     VARCHAR(32),
    PRIMARY KEY (project_lf_reserves_up_ba_scenario_id, project),
    FOREIGN KEY (project_lf_reserves_up_ba_scenario_id)
        REFERENCES subscenarios_project_lf_reserves_up_bas
            (project_lf_reserves_up_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_lf_reserves_down_bas;
CREATE TABLE subscenarios_project_lf_reserves_down_bas
(
    project_lf_reserves_down_ba_scenario_id INTEGER PRIMARY KEY,
    name                                    VARCHAR(32),
    description                             VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_lf_reserves_down_bas;
CREATE TABLE inputs_project_lf_reserves_down_bas
(
    project_lf_reserves_down_ba_scenario_id INTEGER,
    project                                 VARCHAR(64),
    lf_reserves_down_ba                     VARCHAR(32),
    PRIMARY KEY (project_lf_reserves_down_ba_scenario_id, project),
    FOREIGN KEY (project_lf_reserves_down_ba_scenario_id)
        REFERENCES subscenarios_project_lf_reserves_down_bas
            (project_lf_reserves_down_ba_scenario_id)
);


DROP TABLE IF EXISTS subscenarios_project_regulation_up_bas;
CREATE TABLE subscenarios_project_regulation_up_bas
(
    project_regulation_up_ba_scenario_id INTEGER PRIMARY KEY,
    name                                 VARCHAR(32),
    description                          VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_regulation_up_bas;
CREATE TABLE inputs_project_regulation_up_bas
(
    project_regulation_up_ba_scenario_id INTEGER,
    project                              VARCHAR(64),
    regulation_up_ba                     VARCHAR(32),
    PRIMARY KEY (project_regulation_up_ba_scenario_id, project),
    FOREIGN KEY (project_regulation_up_ba_scenario_id)
        REFERENCES subscenarios_project_regulation_up_bas
            (project_regulation_up_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_regulation_down_bas;
CREATE TABLE subscenarios_project_regulation_down_bas
(
    project_regulation_down_ba_scenario_id INTEGER PRIMARY KEY,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_regulation_down_bas;
CREATE TABLE inputs_project_regulation_down_bas
(
    project_regulation_down_ba_scenario_id INTEGER,
    project                                VARCHAR(64),
    regulation_down_ba                     VARCHAR(32),
    PRIMARY KEY (project_regulation_down_ba_scenario_id, project),
    FOREIGN KEY (project_regulation_down_ba_scenario_id)
        REFERENCES subscenarios_project_regulation_down_bas
            (project_regulation_down_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_frequency_response_bas;
CREATE TABLE subscenarios_project_frequency_response_bas
(
    project_frequency_response_ba_scenario_id INTEGER PRIMARY KEY,
    name                                      VARCHAR(32),
    description                               VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_frequency_response_bas;
CREATE TABLE inputs_project_frequency_response_bas
(
    project_frequency_response_ba_scenario_id INTEGER,
    project                                   VARCHAR(64),
    frequency_response_ba                     VARCHAR(32),
    contribute_to_partial                     INTEGER,
    PRIMARY KEY (project_frequency_response_ba_scenario_id, project),
    FOREIGN KEY (project_frequency_response_ba_scenario_id)
        REFERENCES subscenarios_project_frequency_response_bas
            (project_frequency_response_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_spinning_reserves_bas;
CREATE TABLE subscenarios_project_spinning_reserves_bas
(
    project_spinning_reserves_ba_scenario_id INTEGER PRIMARY KEY,
    name                                     VARCHAR(32),
    description                              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_spinning_reserves_bas;
CREATE TABLE inputs_project_spinning_reserves_bas
(
    project_spinning_reserves_ba_scenario_id INTEGER,
    project                                  VARCHAR(64),
    spinning_reserves_ba                     VARCHAR(32),
    PRIMARY KEY (project_spinning_reserves_ba_scenario_id, project),
    FOREIGN KEY (project_spinning_reserves_ba_scenario_id)
        REFERENCES subscenarios_project_spinning_reserves_bas
            (project_spinning_reserves_ba_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_inertia_reserves_bas;
CREATE TABLE subscenarios_project_inertia_reserves_bas
(
    project_inertia_reserves_ba_scenario_id INTEGER PRIMARY KEY,
    name                                    VARCHAR(32),
    description                             VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_inertia_reserves_bas;
CREATE TABLE inputs_project_inertia_reserves_bas
(
    project_inertia_reserves_ba_scenario_id INTEGER,
    project                                 VARCHAR(64),
    inertia_reserves_ba                     VARCHAR(32),
    PRIMARY KEY (project_inertia_reserves_ba_scenario_id, project),
    FOREIGN KEY (project_inertia_reserves_ba_scenario_id)
        REFERENCES subscenarios_project_inertia_reserves_bas
            (project_inertia_reserves_ba_scenario_id)
);

-- Project energy target zones
-- Which projects can contribute to energy target requirements
-- Depends on how energy target zones are specified
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects
DROP TABLE IF EXISTS subscenarios_project_energy_target_zones;
CREATE TABLE subscenarios_project_energy_target_zones
(
    project_energy_target_zone_scenario_id INTEGER PRIMARY KEY,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_energy_target_zones;
CREATE TABLE inputs_project_energy_target_zones
(
    project_energy_target_zone_scenario_id INTEGER,
    project                                VARCHAR(64),
    energy_target_zone                     VARCHAR(32),
    PRIMARY KEY (project_energy_target_zone_scenario_id, project),
    FOREIGN KEY (project_energy_target_zone_scenario_id) REFERENCES
        subscenarios_project_energy_target_zones (project_energy_target_zone_scenario_id)
);

-- Project instantaneous penetration zones
-- Which projects are constrained by the instantaneous penetration rules
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects
DROP TABLE IF EXISTS subscenarios_project_instantaneous_penetration_zones;
CREATE TABLE subscenarios_project_instantaneous_penetration_zones
(
    project_instantaneous_penetration_zone_scenario_id INTEGER PRIMARY KEY,
    name                                               VARCHAR(32),
    description                                        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_instantaneous_penetration_zones;
CREATE TABLE inputs_project_instantaneous_penetration_zones
(
    project_instantaneous_penetration_zone_scenario_id INTEGER,
    project                                            VARCHAR(64),
    instantaneous_penetration_zone                     VARCHAR(32),
    PRIMARY KEY (project_instantaneous_penetration_zone_scenario_id, project),
    FOREIGN KEY (project_instantaneous_penetration_zone_scenario_id) REFERENCES
        subscenarios_project_instantaneous_penetration_zones (project_instantaneous_penetration_zone_scenario_id)
);

-- Tx line transmission target zones
-- Which tx lines can contribute to transmission target requirements
-- Depends on how transmission target zones are specified
-- This table can include all tx line with NULLs for tx lines not
-- contributing or just the contributing tx lines
DROP TABLE IF EXISTS subscenarios_tx_line_transmission_target_zones;
CREATE TABLE subscenarios_tx_line_transmission_target_zones
(
    tx_line_transmission_target_zone_scenario_id INTEGER PRIMARY KEY,
    name                                         VARCHAR(32),
    description                                  VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_tx_line_transmission_target_zones;
CREATE TABLE inputs_tx_line_transmission_target_zones
(
    tx_line_transmission_target_zone_scenario_id INTEGER,
    transmission_line                            VARCHAR(64),
    transmission_target_zone                     VARCHAR(32),
    contributes_net_flow_to_tx_target            INTEGER, -- defaults to 0 in model
    PRIMARY KEY (tx_line_transmission_target_zone_scenario_id,
                 transmission_line),
    FOREIGN KEY (tx_line_transmission_target_zone_scenario_id) REFERENCES
        subscenarios_tx_line_transmission_target_zones (tx_line_transmission_target_zone_scenario_id)
);

-- Project carbon cap zones
-- Which projects count toward the carbon cap
-- Depends on carbon cap zone geography
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects
-- Projects can contribute to multiple carbon cap zones
DROP TABLE IF EXISTS subscenarios_project_carbon_cap_zones;
CREATE TABLE subscenarios_project_carbon_cap_zones
(
    project_carbon_cap_zone_scenario_id INTEGER PRIMARY KEY,
    name                                VARCHAR(32),
    description                         VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_carbon_cap_zones;
CREATE TABLE inputs_project_carbon_cap_zones
(
    project_carbon_cap_zone_scenario_id INTEGER,
    project                             VARCHAR(64),
    carbon_cap_zone                     VARCHAR(32),
    PRIMARY KEY (project_carbon_cap_zone_scenario_id, project, carbon_cap_zone),
    FOREIGN KEY (project_carbon_cap_zone_scenario_id) REFERENCES
        subscenarios_project_carbon_cap_zones (project_carbon_cap_zone_scenario_id)
);

-- Project carbon tax zones
-- Which projects are subject to the carbon tax
-- Depends on carbon tax zone geography
-- This table can include all projects with NULLS for projects not
-- contributing or just the contributing projects
DROP TABLE IF EXISTS subscenarios_project_carbon_tax_zones;
CREATE TABLE subscenarios_project_carbon_tax_zones
(
    project_carbon_tax_zone_scenario_id INTEGER PRIMARY KEY,
    name                                VARCHAR(32),
    description                         VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_carbon_tax_zones;
CREATE TABLE inputs_project_carbon_tax_zones
(
    project_carbon_tax_zone_scenario_id INTEGER,
    project                             VARCHAR(64),
    carbon_tax_zone                     VARCHAR(32),
    PRIMARY KEY (project_carbon_tax_zone_scenario_id, project),
    FOREIGN KEY (project_carbon_tax_zone_scenario_id) REFERENCES
        subscenarios_project_carbon_tax_zones (project_carbon_tax_zone_scenario_id)
);

-- Project carbon tax allowance
DROP TABLE IF EXISTS subscenarios_project_carbon_tax_allowance;
CREATE TABLE subscenarios_project_carbon_tax_allowance
(
    project_carbon_tax_allowance_scenario_id INTEGER PRIMARY KEY,
    name                                     VARCHAR(32),
    description                              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_carbon_tax_allowance;
CREATE TABLE inputs_project_carbon_tax_allowance
(
    project_carbon_tax_allowance_scenario_id INTEGER,
    project                                  VARCHAR(64),
    period                                   INTEGER,
    fuel_group                               VARCHAR(32),
    carbon_tax_allowance_tco2_per_mwh        FLOAT,
    PRIMARY KEY (project_carbon_tax_allowance_scenario_id, project, period,
                 fuel_group),
    FOREIGN KEY (project_carbon_tax_allowance_scenario_id) REFERENCES
        subscenarios_project_carbon_tax_allowance (project_carbon_tax_allowance_scenario_id)
);

-- Project carbon credits
DROP TABLE IF EXISTS subscenarios_project_carbon_credits;
CREATE TABLE subscenarios_project_carbon_credits
(
    project_carbon_credits_scenario_id INTEGER PRIMARY KEY,
    name                               VARCHAR(32),
    description                        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_carbon_credits;
CREATE TABLE inputs_project_carbon_credits
(
    project_carbon_credits_scenario_id          INTEGER,
    project                                     VARCHAR(64),
    period                                      INTEGER,
    intensity_threshold_emissions_toCO2_per_MWh FLOAT,
    absolute_threshold_emissions_toCO2          FLOAT,
    PRIMARY KEY (project_carbon_credits_scenario_id, project, period),
    FOREIGN KEY (project_carbon_credits_scenario_id) REFERENCES
        subscenarios_project_carbon_credits (project_carbon_credits_scenario_id)
);

-- Project performance standard zones
-- Which projects count toward the performance standard
-- Depends on performance standard zone geography
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects
-- Projects can contribute to multiple performance standard zones
DROP TABLE IF EXISTS subscenarios_project_performance_standard_zones;
CREATE TABLE subscenarios_project_performance_standard_zones
(
    project_performance_standard_zone_scenario_id INTEGER PRIMARY KEY,
    name                                          VARCHAR(32),
    description                                   VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_performance_standard_zones;
CREATE TABLE inputs_project_performance_standard_zones
(
    project_performance_standard_zone_scenario_id INTEGER,
    project                                       VARCHAR(64),
    performance_standard_zone                     VARCHAR(32),
    PRIMARY KEY (project_performance_standard_zone_scenario_id, project,
                 performance_standard_zone),
    FOREIGN KEY (project_performance_standard_zone_scenario_id) REFERENCES
        subscenarios_project_performance_standard_zones (project_performance_standard_zone_scenario_id)
);

-- Project carbon credits generation zones
-- Which projects can generate credits in which carbon credits zone
-- Can only do so in one zone for now
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects
DROP TABLE IF EXISTS subscenarios_project_carbon_credits_generation_zones;
CREATE TABLE subscenarios_project_carbon_credits_generation_zones
(
    project_carbon_credits_generation_zone_scenario_id INTEGER PRIMARY KEY,
    name                                               VARCHAR(32),
    description                                        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_carbon_credits_generation_zones;
CREATE TABLE inputs_project_carbon_credits_generation_zones
(
    project_carbon_credits_generation_zone_scenario_id INTEGER,
    project                                            VARCHAR(64),
    carbon_credits_zone                                VARCHAR(32),
    PRIMARY KEY (project_carbon_credits_generation_zone_scenario_id, project,
                 carbon_credits_zone),
    FOREIGN KEY (project_carbon_credits_generation_zone_scenario_id) REFERENCES
        subscenarios_project_carbon_credits_generation_zones (project_carbon_credits_generation_zone_scenario_id)
);

-- Project carbon credits purchase zones
-- Which projects can purchase credits in which carbon credits zone
-- Can only do so in one zone for now
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects
-- Projects can purchase from multiple carbon credits zones
DROP TABLE IF EXISTS subscenarios_project_carbon_credits_purchase_zones;
CREATE TABLE subscenarios_project_carbon_credits_purchase_zones
(
    project_carbon_credits_purchase_zone_scenario_id INTEGER PRIMARY KEY,
    name                                             VARCHAR(32),
    description                                      VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_carbon_credits_purchase_zones;
CREATE TABLE inputs_project_carbon_credits_purchase_zones
(
    project_carbon_credits_purchase_zone_scenario_id INTEGER,
    project                                          VARCHAR(64),
    carbon_credits_zone                              VARCHAR(32),
    PRIMARY KEY (project_carbon_credits_purchase_zone_scenario_id, project,
                 carbon_credits_zone),
    FOREIGN KEY (project_carbon_credits_purchase_zone_scenario_id) REFERENCES
        subscenarios_project_carbon_credits_purchase_zones (project_carbon_credits_purchase_zone_scenario_id)
);

-- Project carbon credits purchase limits
-- Maximum or minimum percentage of project emissions which can be accounted for using carbon credits each period
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects
DROP TABLE IF EXISTS subscenarios_project_carbon_credits_purchase_limits;
CREATE TABLE subscenarios_project_carbon_credits_purchase_limits
(
    project_carbon_credits_purchase_limits_scenario_id INTEGER PRIMARY KEY,
    name                                               VARCHAR(32),
    description                                        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_carbon_credits_purchase_limits;
CREATE TABLE inputs_project_carbon_credits_purchase_limits
(
    project_carbon_credits_purchase_limits_scenario_id INTEGER,
    project                                            VARCHAR(64),
    period                                             FLOAT,
    purchase_credit_min_fraction                       FLOAT,
    purchase_credit_max_fraction                       FLOAT,
    PRIMARY KEY (project_carbon_credits_purchase_limits_scenario_id, project,
                 period),
    FOREIGN KEY (project_carbon_credits_purchase_limits_scenario_id) REFERENCES
        subscenarios_project_carbon_credits_purchase_limits (project_carbon_credits_purchase_limits_scenario_id)
);

-- Project fuel burn limit balancing areas
-- Which projects contribute to the fuel BA limit
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects
DROP TABLE IF EXISTS subscenarios_project_fuel_burn_limit_balancing_areas;
CREATE TABLE subscenarios_project_fuel_burn_limit_balancing_areas
(
    project_fuel_burn_limit_ba_scenario_id INTEGER PRIMARY KEY,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_fuel_burn_limit_balancing_areas;
CREATE TABLE inputs_project_fuel_burn_limit_balancing_areas
(
    project_fuel_burn_limit_ba_scenario_id INTEGER,
    project                                VARCHAR(64),
    fuel_burn_limit_ba                     VARCHAR(32),
    PRIMARY KEY (project_fuel_burn_limit_ba_scenario_id, project,
                 fuel_burn_limit_ba),
    FOREIGN KEY (project_fuel_burn_limit_ba_scenario_id) REFERENCES
        subscenarios_project_fuel_burn_limit_balancing_areas (project_fuel_burn_limit_ba_scenario_id)
);

-- Fuel fuel burn limit balancing areas
-- Which fuel contribute to the fuel BA limit
-- This table can include all fuels with NULLs for fuels not
-- contributing or just the contributing fuels
DROP TABLE IF EXISTS subscenarios_fuel_fuel_burn_limit_balancing_areas;
CREATE TABLE subscenarios_fuel_fuel_burn_limit_balancing_areas
(
    fuel_fuel_burn_limit_ba_scenario_id INTEGER PRIMARY KEY,
    name                                VARCHAR(32),
    description                         VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_fuel_fuel_burn_limit_balancing_areas;
CREATE TABLE inputs_fuel_fuel_burn_limit_balancing_areas
(
    fuel_fuel_burn_limit_ba_scenario_id INTEGER,
    fuel                                VARCHAR(64),
    fuel_burn_limit_ba                  VARCHAR(32),
    PRIMARY KEY (fuel_fuel_burn_limit_ba_scenario_id, fuel, fuel_burn_limit_ba),
    FOREIGN KEY (fuel_fuel_burn_limit_ba_scenario_id) REFERENCES
        subscenarios_fuel_fuel_burn_limit_balancing_areas (fuel_fuel_burn_limit_ba_scenario_id)
);

-- Project PRM zones
-- Which projects can contribute to PRM requirements
-- Depends on how PRM zones are specified
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects

DROP TABLE IF EXISTS subscenarios_project_prm_zones;
CREATE TABLE subscenarios_project_prm_zones
(
    project_prm_zone_scenario_id INTEGER PRIMARY KEY,
    name                         VARCHAR(32),
    description                  VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_prm_zones;
CREATE TABLE inputs_project_prm_zones
(
    project_prm_zone_scenario_id INTEGER,
    project                      VARCHAR(64),
    prm_zone                     VARCHAR(32),
    PRIMARY KEY (project_prm_zone_scenario_id, project),
    FOREIGN KEY (project_prm_zone_scenario_id) REFERENCES
        subscenarios_project_prm_zones (project_prm_zone_scenario_id)
);

-- Transmission PRM zones capacity transfer links
-- Also, which transmission lines can are part of those links

DROP TABLE IF EXISTS subscenarios_transmission_prm_capacity_transfers;
CREATE TABLE subscenarios_transmission_prm_capacity_transfers
(
    prm_capacity_transfer_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                              VARCHAR(32),
    description                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_prm_capacity_transfers;
CREATE TABLE inputs_transmission_prm_capacity_transfers
(
    prm_capacity_transfer_scenario_id INTEGER,
    prm_zone                          VARCHAR(32), -- "from" zone
    prm_capacity_transfer_zone        VARCHAR(32), -- "to" zone,
    allow_elcc_surface_transfers      INTEGER,     -- defaults to 0, only enable this if you know
-- what you are doing
    PRIMARY KEY (prm_capacity_transfer_scenario_id, prm_zone,
                 prm_capacity_transfer_zone),
    FOREIGN KEY (prm_capacity_transfer_scenario_id) REFERENCES
        subscenarios_transmission_prm_capacity_transfers (prm_capacity_transfer_scenario_id)
);

-- Param limits
DROP TABLE IF EXISTS subscenarios_transmission_prm_capacity_transfer_params;
CREATE TABLE subscenarios_transmission_prm_capacity_transfer_params
(
    prm_capacity_transfer_params_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                     VARCHAR(32),
    description                              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_prm_capacity_transfer_params;
CREATE TABLE inputs_transmission_prm_capacity_transfer_params
(
    prm_capacity_transfer_params_scenario_id INTEGER,
    prm_zone                                 VARCHAR(32), -- "from" zone
    prm_capacity_transfer_zone               VARCHAR(32), -- "to" zone,
    period                                   INTEGER,
    min_transfer_powerunit                   FLOAT,
    max_transfer_powerunit                   FLOAT,
    capacity_transfer_cost_per_powerunit_yr  FLOAT,
    PRIMARY KEY (prm_capacity_transfer_params_scenario_id, prm_zone,
                 prm_capacity_transfer_zone, period),
    FOREIGN KEY (prm_capacity_transfer_params_scenario_id) REFERENCES
        subscenarios_transmission_prm_capacity_transfer_params (prm_capacity_transfer_params_scenario_id)
);

-- Transmission line aggregations for limits
DROP TABLE IF EXISTS subscenarios_transmission_prm_zones;
CREATE TABLE subscenarios_transmission_prm_zones
(
    transmission_prm_zone_scenario_id INTEGER PRIMARY KEY,
    name                              VARCHAR(32),
    description                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_prm_zones;
CREATE TABLE inputs_transmission_prm_zones
(
    transmission_prm_zone_scenario_id INTEGER,
    transmission_line                 VARCHAR(64),
    prm_zone_from                     VARCHAR(32),
    prm_zone_to                       VARCHAR(32),
    PRIMARY KEY (transmission_prm_zone_scenario_id, transmission_line),
    FOREIGN KEY (transmission_prm_zone_scenario_id) REFERENCES
        subscenarios_transmission_prm_zones (transmission_prm_zone_scenario_id)
);

-- Project capacity contribution characteristics (simple ELCC treatment or
-- treatment via an ELCC surface
DROP TABLE IF EXISTS subscenarios_project_elcc_chars;
CREATE TABLE subscenarios_project_elcc_chars
(
    project_elcc_chars_scenario_id INTEGER PRIMARY KEY,
    name                           VARCHAR(32),
    description                    VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_elcc_chars;
CREATE TABLE inputs_project_elcc_chars
(
    project_elcc_chars_scenario_id              INTEGER,
    project                                     VARCHAR(64),
    prm_type                                    VARCHAR(32), -- to model 'energy_only" PRM type, select energy_only feature
    min_duration_for_full_capacity_credit_hours FLOAT,
    project_elcc_simple_scenario_id             INTEGER,
    project_deliverability_scenario_id          INTEGER CHECK (
        project_deliverability_scenario_id IS NULL OR
        prm_type = 'energy_only_allowed'
        ),                                                   -- can be NULL; otherwise ensure projects with group are energy_only_allowed
    PRIMARY KEY (project_elcc_chars_scenario_id, project),
    FOREIGN KEY (prm_type) REFERENCES mod_prm_types (prm_type),
    FOREIGN KEY (project_elcc_chars_scenario_id) REFERENCES
        subscenarios_project_elcc_chars (project_elcc_chars_scenario_id)
);

-- Simple ELCC chars
DROP TABLE IF EXISTS subscenarios_project_elcc_simple;
CREATE TABLE subscenarios_project_elcc_simple
(
    project                         VARCHAR(32),
    project_elcc_simple_scenario_id INTEGER,
    name                            VARCHAR(32),
    description                     VARCHAR(128),
    PRIMARY KEY (project, project_elcc_simple_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_elcc_simple;
CREATE TABLE inputs_project_elcc_simple
(
    project                         VARCHAR(64),
    project_elcc_simple_scenario_id INTEGER,
    period                          FLOAT,
    elcc_simple_fraction            FLOAT,
    PRIMARY KEY (project, project_elcc_simple_scenario_id, period),
    FOREIGN KEY (project, project_elcc_simple_scenario_id) REFERENCES
        subscenarios_project_elcc_simple (project, project_elcc_simple_scenario_id)
);

-- Deliverability chars
DROP TABLE IF EXISTS subscenarios_project_deliverability;
CREATE TABLE subscenarios_project_deliverability
(
    project                            VARCHAR(32),
    project_deliverability_scenario_id INTEGER,
    name                               VARCHAR(32),
    description                        VARCHAR(128),
    PRIMARY KEY (project, project_deliverability_scenario_id)
);


DROP TABLE IF EXISTS inputs_project_deliverability;
CREATE TABLE inputs_project_deliverability
(
    project                            VARCHAR(64),
    project_deliverability_scenario_id INTEGER,
    deliverability_group               VARCHAR(64), -- can be NULL; otherwise ensure projects with group are energy_only_allowed
    PRIMARY KEY (project, project_deliverability_scenario_id,
                 deliverability_group),
    FOREIGN KEY (project, project_deliverability_scenario_id) REFERENCES
        subscenarios_project_deliverability (project, project_deliverability_scenario_id)
);

-- ELCC surface
-- Depends on how PRM zones are defined
DROP TABLE IF EXISTS subscenarios_system_prm_zone_elcc_surface;
CREATE TABLE subscenarios_system_prm_zone_elcc_surface
(
    elcc_surface_scenario_id INTEGER PRIMARY KEY,
    name                     VARCHAR(32),
    description              VARCHAR(128)
);

-- ELCC surface intercept by PRM zone, period, and facet
DROP TABLE IF EXISTS inputs_system_prm_zone_elcc_surface;
CREATE TABLE inputs_system_prm_zone_elcc_surface
(
    elcc_surface_scenario_id INTEGER,
    elcc_surface_name        VARCHAR(32),
    prm_zone                 VARCHAR(32),
    period                   INTEGER,
    facet                    INTEGER,
    elcc_surface_intercept   FLOAT,
    PRIMARY KEY (elcc_surface_scenario_id, elcc_surface_name, prm_zone, period,
                 facet),
    FOREIGN KEY (elcc_surface_scenario_id) REFERENCES
        subscenarios_system_prm_zone_elcc_surface (elcc_surface_scenario_id)
);

-- Peak and annual load for ELCC surface by PRM zone and period
DROP TABLE IF EXISTS inputs_system_prm_zone_elcc_surface_prm_load;
CREATE TABLE inputs_system_prm_zone_elcc_surface_prm_load
(
    elcc_surface_scenario_id INTEGER,
    elcc_surface_name        VARCHAR(32),
    prm_zone                 VARCHAR(32),
    period                   INTEGER,
    prm_peak_load_mw         FLOAT,
    prm_annual_load_mwh      FLOAT,
    PRIMARY KEY (elcc_surface_scenario_id, elcc_surface_name, prm_zone, period),
    FOREIGN KEY (elcc_surface_scenario_id) REFERENCES
        subscenarios_system_prm_zone_elcc_surface (elcc_surface_scenario_id)
);

-- ELCC coefficients by project, period, and facet
DROP TABLE IF EXISTS inputs_project_elcc_surface;
CREATE TABLE inputs_project_elcc_surface
(
    elcc_surface_scenario_id INTEGER,
    elcc_surface_name        VARCHAR(32),
    project                  VARCHAR(64),
    period                   INTEGER,
    facet                    INTEGER,
    elcc_surface_coefficient FLOAT,
    PRIMARY KEY (elcc_surface_scenario_id, elcc_surface_name, project, period,
                 facet)
);

-- Project cap factors for the ELCC surface
DROP TABLE IF EXISTS inputs_project_elcc_surface_cap_factors;
CREATE TABLE inputs_project_elcc_surface_cap_factors
(
    elcc_surface_scenario_id INTEGER,
    elcc_surface_name        VARCHAR(32),
    project                  VARCHAR(64),
    elcc_surface_cap_factor  FLOAT,
    PRIMARY KEY (elcc_surface_scenario_id, elcc_surface_name, project)
);

-- Deliverability parameters
DROP TABLE IF EXISTS subscenarios_project_prm_deliverability_costs;
CREATE TABLE subscenarios_project_prm_deliverability_costs
(
    prm_deliverability_cost_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                VARCHAR(32),
    description                         VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_prm_deliverability_costs;
CREATE TABLE inputs_project_prm_deliverability_costs
(
    prm_deliverability_cost_scenario_id INTEGER,
    deliverability_group                VARCHAR(64),
    vintage                             FLOAT,
    lifetime_yrs                        FLOAT,
    deliverability_cost_per_mw_yr       FLOAT,
    PRIMARY KEY (prm_deliverability_cost_scenario_id, deliverability_group,
                 vintage),
    FOREIGN KEY (prm_deliverability_cost_scenario_id) REFERENCES
        subscenarios_project_prm_deliverability_costs
            (prm_deliverability_cost_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_prm_deliverability_existing;
CREATE TABLE subscenarios_project_prm_deliverability_existing
(
    prm_deliverability_existing_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                    VARCHAR(32),
    description                             VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_prm_deliverability_existing;
CREATE TABLE inputs_project_prm_deliverability_existing
(
    prm_deliverability_existing_scenario_id INTEGER,
    deliverability_group                    VARCHAR(64),
    period                                  FLOAT,
    constraint_type                         VARCHAR(16) CHECK (
        constraint_type = 'total'
            OR constraint_type = 'deliverable'
            OR constraint_type = 'energy_only'
        ),
    peak_designation                        VARCHAR(16),
    existing_deliverability_mw              FLOAT,
    PRIMARY KEY (prm_deliverability_existing_scenario_id, deliverability_group,
                 period,
                 constraint_type, peak_designation),
    FOREIGN KEY (prm_deliverability_existing_scenario_id) REFERENCES
        subscenarios_project_prm_deliverability_existing
            (prm_deliverability_existing_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_prm_deliverability_potential;
CREATE TABLE subscenarios_project_prm_deliverability_potential
(
    prm_deliverability_potential_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                     VARCHAR(32),
    description                              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_prm_deliverability_potential;
CREATE TABLE inputs_project_prm_deliverability_potential
(
    prm_deliverability_potential_scenario_id INTEGER,
    deliverability_group                     VARCHAR(64),
    period                                   FLOAT,
    deliverable_capacity_limit_cumulative_mw FLOAT,
    PRIMARY KEY (prm_deliverability_potential_scenario_id, deliverability_group,
                 period),
    FOREIGN KEY (prm_deliverability_potential_scenario_id) REFERENCES
        subscenarios_project_prm_deliverability_potential
            (prm_deliverability_potential_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_prm_deliverability_multipliers;
CREATE TABLE subscenarios_project_prm_deliverability_multipliers
(
    project_prm_deliverability_multipliers_scenario_id INTEGER PRIMARY KEY,
    name                                               VARCHAR(32),
    description                                        VARCHAR(128)
);

CREATE TABLE inputs_project_prm_deliverability_multipliers
(
    project_prm_deliverability_multipliers_scenario_id INTEGER,
    project                                            VARCHAR(64),
    constraint_type                                    VARCHAR(16) CHECK (
        constraint_type = 'total'
            OR constraint_type = 'deliverable'
            OR constraint_type = 'energy_only'
        ),
    peak_designation                                   VARCHAR(16),
    multiplier                                         FLOAT,
    PRIMARY KEY (project_prm_deliverability_multipliers_scenario_id, project,
                 constraint_type, peak_designation),
    FOREIGN KEY (project_prm_deliverability_multipliers_scenario_id) REFERENCES
        subscenarios_project_prm_deliverability_multipliers
            (project_prm_deliverability_multipliers_scenario_id)
);


-- Project local capacity zones and chars
-- Which projects can contribute to local capacity requirements
-- Depends on how local capacity zones are specified
-- This table can include all project with NULLs for projects not
-- contributing or just the contributing projects

DROP TABLE IF EXISTS subscenarios_project_local_capacity_zones;
CREATE TABLE subscenarios_project_local_capacity_zones
(
    project_local_capacity_zone_scenario_id INTEGER PRIMARY KEY,
    name                                    VARCHAR(32),
    description                             VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_local_capacity_zones;
CREATE TABLE inputs_project_local_capacity_zones
(
    project_local_capacity_zone_scenario_id INTEGER,
    project                                 VARCHAR(64),
    local_capacity_zone                     VARCHAR(32),
    PRIMARY KEY (project_local_capacity_zone_scenario_id, project),
    FOREIGN KEY (project_local_capacity_zone_scenario_id) REFERENCES
        subscenarios_project_local_capacity_zones
            (project_local_capacity_zone_scenario_id)
);

-- Project capacity contribution characteristics
DROP TABLE IF EXISTS subscenarios_project_local_capacity_chars;
CREATE TABLE subscenarios_project_local_capacity_chars
(
    project_local_capacity_chars_scenario_id INTEGER PRIMARY KEY,
    name                                     VARCHAR(32),
    description                              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_local_capacity_chars;
CREATE TABLE inputs_project_local_capacity_chars
(
    project_local_capacity_chars_scenario_id    INTEGER,
    project                                     VARCHAR(64),
    local_capacity_fraction                     FLOAT,
    min_duration_for_full_capacity_credit_hours FLOAT,
    PRIMARY KEY (project_local_capacity_chars_scenario_id, project),
    FOREIGN KEY (project_local_capacity_chars_scenario_id) REFERENCES
        subscenarios_project_local_capacity_chars
            (project_local_capacity_chars_scenario_id)
);

-- Fuels
DROP TABLE IF EXISTS subscenarios_fuels;
CREATE TABLE subscenarios_fuels
(
    fuel_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name             VARCHAR(32),
    description      VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_fuels;
CREATE TABLE inputs_fuels
(
    fuel_scenario_id             INTEGER,
    fuel                         VARCHAR(32),
    co2_intensity_tons_per_mmbtu FLOAT,
    fuel_group                   VARCHAR(32),
    PRIMARY KEY (fuel_scenario_id, fuel),
    FOREIGN KEY (fuel_scenario_id) REFERENCES subscenarios_fuels
        (fuel_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_fuel_prices;
CREATE TABLE subscenarios_fuel_prices
(
    fuel_price_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   VARCHAR(32),
    description            VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_fuel_prices;
CREATE TABLE inputs_fuel_prices
(
    fuel_price_scenario_id INTEGER,
    fuel                   VARCHAR(32),
    period                 INTEGER,
    month                  INTEGER,
    fuel_price_per_mmbtu   FLOAT,
    PRIMARY KEY (fuel_price_scenario_id, fuel, period, month),
    FOREIGN KEY (fuel_price_scenario_id) REFERENCES
        subscenarios_fuel_prices (fuel_price_scenario_id)
);


------------------
-- TRANSMISSION --
------------------

-- Transmission portfolios
DROP TABLE IF EXISTS subscenarios_transmission_portfolios;
CREATE TABLE subscenarios_transmission_portfolios
(
    transmission_portfolio_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                               VARCHAR(32),
    description                        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_portfolios;
CREATE TABLE inputs_transmission_portfolios
(
    transmission_portfolio_scenario_id INTEGER,
    transmission_line                  VARCHAR(64),
    capacity_type                      VARCHAR(32),
    PRIMARY KEY (transmission_portfolio_scenario_id, transmission_line),
    FOREIGN KEY (transmission_portfolio_scenario_id) REFERENCES
        subscenarios_transmission_portfolios
            (transmission_portfolio_scenario_id),
    FOREIGN KEY (capacity_type) REFERENCES mod_tx_capacity_types
        (capacity_type)
);

-- Transmission geography
-- Load zones
DROP TABLE IF EXISTS subscenarios_transmission_load_zones;
CREATE TABLE subscenarios_transmission_load_zones
(
    transmission_load_zone_scenario_id INTEGER PRIMARY KEY,
    name                               VARCHAR(32),
    description                        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_load_zones;
CREATE TABLE inputs_transmission_load_zones
(
    transmission_load_zone_scenario_id INTEGER,
    transmission_line                  VARCHAR(64),
    load_zone_from                     VARCHAR(32),
    load_zone_to                       VARCHAR(32),
    PRIMARY KEY (transmission_load_zone_scenario_id, transmission_line),
    FOREIGN KEY (transmission_load_zone_scenario_id) REFERENCES
        subscenarios_transmission_load_zones (transmission_load_zone_scenario_id)
);

-- Carbon cap zones
-- This is needed if the carbon cap module is enabled and we want to track
-- emission imports
DROP TABLE IF EXISTS subscenarios_transmission_carbon_cap_zones;
CREATE TABLE subscenarios_transmission_carbon_cap_zones
(
    transmission_carbon_cap_zone_scenario_id INTEGER PRIMARY KEY,
    name                                     VARCHAR(32),
    description                              VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_carbon_cap_zones;
CREATE TABLE inputs_transmission_carbon_cap_zones
(
    transmission_carbon_cap_zone_scenario_id INTEGER,
    transmission_line                        VARCHAR(64),
    carbon_cap_zone                          VARCHAR(32),
    import_direction                         VARCHAR(8),
    tmp_import_emissions_scenario_id         INTEGER, -- determines timepoint emissions scenario
    tx_co2_intensity_tons_per_mwh            FLOAT,
    PRIMARY KEY (transmission_carbon_cap_zone_scenario_id, transmission_line),
    FOREIGN KEY (transmission_carbon_cap_zone_scenario_id) REFERENCES
        subscenarios_transmission_carbon_cap_zones
            (transmission_carbon_cap_zone_scenario_id)

);

DROP TABLE IF EXISTS subscenarios_transmission_carbon_cap_timepoint_emissions;
CREATE TABLE subscenarios_transmission_carbon_cap_timepoint_emissions
(
    transmission_line                VARCHAR(64),
    tmp_import_emissions_scenario_id INTEGER,
    name                             VARCHAR(32),
    description                      VARCHAR(128),
    PRIMARY KEY (transmission_line, tmp_import_emissions_scenario_id)
);

DROP TABLE IF EXISTS inputs_transmission_carbon_cap_timepoint_emissions;
CREATE TABLE inputs_transmission_carbon_cap_timepoint_emissions
(
    transmission_line                    VARCHAR(64),
    tmp_import_emissions_scenario_id     INTEGER,
    timepoint                            INTEGER,
    tx_co2_intensity_tons_per_mwh_hourly FLOAT,
    PRIMARY KEY (transmission_line, tmp_import_emissions_scenario_id,
                 timepoint),
    FOREIGN KEY (transmission_line, tmp_import_emissions_scenario_id) REFERENCES
        subscenarios_transmission_carbon_cap_timepoint_emissions
            (transmission_line, tmp_import_emissions_scenario_id)
);

-- Existing transmission capacity
DROP TABLE IF EXISTS subscenarios_transmission_specified_capacity;
CREATE TABLE subscenarios_transmission_specified_capacity
(
    transmission_specified_capacity_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                        VARCHAR(32),
    description                                 VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_specified_capacity;
CREATE TABLE inputs_transmission_specified_capacity
(
    transmission_specified_capacity_scenario_id INTEGER,
    transmission_line                           VARCHAR(64),
    period                                      INTEGER,
    min_mw                                      FLOAT,
    max_mw                                      FLOAT,
    fixed_cost_per_mw_yr                        FLOAT, -- multiplied by the mean of the absolute
-- values of min and max flow
    PRIMARY KEY (transmission_specified_capacity_scenario_id, transmission_line,
                 period),
    FOREIGN KEY (transmission_specified_capacity_scenario_id) REFERENCES
        subscenarios_transmission_specified_capacity
            (transmission_specified_capacity_scenario_id)
);

-- New transmission cost
DROP TABLE IF EXISTS subscenarios_transmission_new_cost;
CREATE TABLE subscenarios_transmission_new_cost
(
    transmission_new_cost_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                              VARCHAR(32),
    description                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_new_cost;
CREATE TABLE inputs_transmission_new_cost
(
    transmission_new_cost_scenario_id INTEGER,
    transmission_line                 VARCHAR(64),
    vintage                           INTEGER,
    tx_operational_lifetime_yrs       FLOAT,
    tx_fixed_cost_per_mw_yr           FLOAT,
    tx_financial_lifetime_yrs         FLOAT,
    tx_annualized_real_cost_per_mw_yr FLOAT,
    PRIMARY KEY (transmission_new_cost_scenario_id, transmission_line,
                 vintage),
    FOREIGN KEY (transmission_new_cost_scenario_id) REFERENCES
        subscenarios_transmission_new_cost
            (transmission_new_cost_scenario_id)
);

-- Transmission new potential
DROP TABLE IF EXISTS subscenarios_transmission_new_potential;
CREATE TABLE subscenarios_transmission_new_potential
(
    transmission_new_potential_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

-- Transmission lines with no min or max build requirements can be included here with
-- NULL values or excluded from this table
DROP TABLE IF EXISTS inputs_transmission_new_potential;
CREATE TABLE inputs_transmission_new_potential
(
    transmission_new_potential_scenario_id INTEGER,
    transmission_line                      VARCHAR(64),
    period                                 INTEGER,
    min_cumulative_new_build_mw            FLOAT,
    max_cumulative_new_build_mw            FLOAT,
    PRIMARY KEY (transmission_new_potential_scenario_id, transmission_line,
                 period),
    FOREIGN KEY (transmission_new_potential_scenario_id) REFERENCES
        subscenarios_transmission_new_potential (transmission_new_potential_scenario_id)
);

-- Transmission availability (e.g. due to planned outages/availability)
-- Subscenarios
DROP TABLE IF EXISTS subscenarios_transmission_availability;
CREATE TABLE subscenarios_transmission_availability
(
    transmission_availability_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                  VARCHAR(32),
    description                           VARCHAR(128)
);

-- Define availability type and IDs for type characteristics
-- TODO: implement check that there are exogenous IDs only for exogenous
--  types and endogenous IDs only for endogenous types
DROP TABLE IF EXISTS inputs_transmission_availability;
CREATE TABLE inputs_transmission_availability
(
    transmission_availability_scenario_id INTEGER,
    transmission_line                     VARCHAR(64),
    availability_type                     VARCHAR(32),
    exogenous_availability_scenario_id    INTEGER,
    endogenous_availability_scenario_id   INTEGER,
    PRIMARY KEY (transmission_availability_scenario_id, transmission_line,
                 availability_type)
);

DROP TABLE IF EXISTS subscenarios_transmission_availability_exogenous;
CREATE TABLE subscenarios_transmission_availability_exogenous
(
    transmission_line                  VARCHAR(64),
    exogenous_availability_scenario_id INTEGER,
    name                               VARCHAR(32),
    description                        VARCHAR(128),
    PRIMARY KEY (transmission_line, exogenous_availability_scenario_id)
);

DROP TABLE IF EXISTS inputs_transmission_availability_exogenous;
CREATE TABLE inputs_transmission_availability_exogenous
(
    transmission_line                  VARCHAR(64),
    exogenous_availability_scenario_id INTEGER,
    stage_id                           INTEGER,
    timepoint                          INTEGER CHECK (
        (timepoint = 0 AND month > 0)
            or (timepoint > 0 AND month = 0)
        ), -- use 0 for monthly availability
    month                              INTEGER CHECK (
        (timepoint = 0 AND month > 0)
            or (timepoint > 0 AND month = 0)
        ), -- use 0 for timepoint-level availability
    availability_derate                FLOAT,
    PRIMARY KEY (transmission_line, exogenous_availability_scenario_id,
                 stage_id,
                 timepoint, month),
    FOREIGN KEY (transmission_line, exogenous_availability_scenario_id)
        REFERENCES subscenarios_transmission_availability_exogenous
            (transmission_line, exogenous_availability_scenario_id)
);

-- Transmission flow
DROP TABLE IF EXISTS subscenarios_transmission_flow;
CREATE TABLE subscenarios_transmission_flow
(
    transmission_flow_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                          VARCHAR(32),
    description                   VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_flow;
CREATE TABLE inputs_transmission_flow
(
    transmission_flow_scenario_id INTEGER,
    transmission_line             VARCHAR(64),
    stage_id                      INTEGER,
    timepoint                     INTEGER,
    min_flow_mw                   FLOAT,
    max_flow_mw                   FLOAT,
    PRIMARY KEY (transmission_flow_scenario_id, transmission_line, stage_id,
                 timepoint),
    FOREIGN KEY (transmission_flow_scenario_id) REFERENCES
        subscenarios_transmission_flow (transmission_flow_scenario_id)
);


-- Operational characteristics
DROP TABLE IF EXISTS subscenarios_transmission_operational_chars;
CREATE TABLE subscenarios_transmission_operational_chars
(
    transmission_operational_chars_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                       VARCHAR(32),
    description                                VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_operational_chars;
CREATE TABLE inputs_transmission_operational_chars
(
    transmission_operational_chars_scenario_id INTEGER,
    transmission_line                          VARCHAR(64),
    operational_type                           VARCHAR(32),
    tx_simple_loss_factor                      FLOAT,
    losses_tuning_cost_per_mw                  FLOAT,
    reactance_ohms                             FLOAT,
    tx_curtailment_cost_scenario_id            INTEGER,
    tx_losses_factor_curtailment               FLOAT,
    PRIMARY KEY (transmission_operational_chars_scenario_id, transmission_line),
    FOREIGN KEY (transmission_operational_chars_scenario_id) REFERENCES
        subscenarios_transmission_operational_chars
            (transmission_operational_chars_scenario_id),
    FOREIGN KEY (operational_type) REFERENCES mod_tx_operational_types
        (operational_type),
    FOREIGN KEY (transmission_line, tx_curtailment_cost_scenario_id) REFERENCES
        subscenarios_transmission_curtailment_cost
            (transmission_line, tx_curtailment_cost_scenario_id)
);

-- Curtailment cost (applied to transmission losses)
DROP TABLE IF EXISTS subscenarios_transmission_curtailment_cost;
CREATE TABLE subscenarios_transmission_curtailment_cost
(
    transmission_line               VARCHAR(64),
    tx_curtailment_cost_scenario_id INTEGER,
    name                             VARCHAR(32),
    description                      VARCHAR(128),
    PRIMARY KEY (transmission_line, tx_curtailment_cost_scenario_id)
);

DROP TABLE IF EXISTS inputs_transmission_curtailment_cost;
CREATE TABLE inputs_transmission_curtailment_cost
(
    transmission_line                     VARCHAR(64),
    tx_curtailment_cost_scenario_id       INTEGER,
    period                                 INTEGER, -- 0 means it's the same for all periods
    tx_curtailment_cost_per_powerunithour FLOAT,
    PRIMARY KEY (transmission_line, tx_curtailment_cost_scenario_id, period),
    FOREIGN KEY (transmission_line, tx_curtailment_cost_scenario_id) REFERENCES
        subscenarios_transmission_curtailment_cost
            (transmission_line, tx_curtailment_cost_scenario_id)
);

-- Hurdle rates
DROP TABLE IF EXISTS subscenarios_transmission_hurdle_rates;
CREATE TABLE subscenarios_transmission_hurdle_rates
(
    transmission_hurdle_rate_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                 VARCHAR(32),
    description                          VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_hurdle_rates;
CREATE TABLE inputs_transmission_hurdle_rates
(
    transmission_hurdle_rate_scenario_id   INTEGER,
    transmission_line                      VARCHAR(64),
    period                                 INTEGER,
    hurdle_rate_positive_direction_per_mwh FLOAT,
    hurdle_rate_negative_direction_per_mwh FLOAT,
    PRIMARY KEY (transmission_hurdle_rate_scenario_id, transmission_line,
                 period),
    FOREIGN KEY (transmission_hurdle_rate_scenario_id) REFERENCES
        subscenarios_transmission_hurdle_rates (transmission_hurdle_rate_scenario_id)
);

-- Hurdle rates
DROP TABLE IF EXISTS subscenarios_transmission_hurdle_rates_by_timepoint;
CREATE TABLE subscenarios_transmission_hurdle_rates_by_timepoint
(
    transmission_hurdle_rate_by_timepoint_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                              VARCHAR(32),
    description                                       VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_hurdle_rates_by_timepoint;
CREATE TABLE inputs_transmission_hurdle_rates_by_timepoint
(
    transmission_hurdle_rate_by_timepoint_scenario_id   INTEGER,
    transmission_line                                   VARCHAR(64),
    timepoint                                           INTEGER,
    hurdle_rate_by_timepoint_positive_direction_per_mwh FLOAT,
    hurdle_rate_by_timepoint_negative_direction_per_mwh FLOAT,
    PRIMARY KEY (transmission_hurdle_rate_by_timepoint_scenario_id,
                 transmission_line,
                 timepoint),
    FOREIGN KEY (transmission_hurdle_rate_by_timepoint_scenario_id) REFERENCES
        subscenarios_transmission_hurdle_rates_by_timepoint (transmission_hurdle_rate_by_timepoint_scenario_id)
);

-- Group capacity requirements
-- Requirements
DROP TABLE IF EXISTS subscenarios_transmission_capacity_group_requirements;
CREATE TABLE subscenarios_transmission_capacity_group_requirements
(
    transmission_capacity_group_requirement_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                                VARCHAR(32),
    description                                         VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_capacity_group_requirements;
CREATE TABLE inputs_transmission_capacity_group_requirements
(
    transmission_capacity_group_requirement_scenario_id INTEGER,
    transmission_capacity_group                         VARCHAR(64),
    period                                              INTEGER,
    transmission_capacity_group_new_capacity_min        FLOAT,
    transmission_capacity_group_new_capacity_max        FLOAT,
    PRIMARY KEY (transmission_capacity_group_requirement_scenario_id,
                 transmission_capacity_group, period),
    FOREIGN KEY (transmission_capacity_group_requirement_scenario_id) REFERENCES
        subscenarios_transmission_capacity_group_requirements
            (transmission_capacity_group_requirement_scenario_id)
);


-- Group transmission lines mapping
DROP TABLE IF EXISTS subscenarios_transmission_capacity_groups;
CREATE TABLE subscenarios_transmission_capacity_groups
(
    transmission_capacity_group_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                    VARCHAR(32),
    description                             VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_capacity_groups;
CREATE TABLE inputs_transmission_capacity_groups
(
    transmission_capacity_group_scenario_id INTEGER,
    transmission_capacity_group             VARCHAR(64),
    transmission_line                       VARCHAR(64),
    PRIMARY KEY (transmission_capacity_group_scenario_id,
                 transmission_capacity_group, transmission_line),
    FOREIGN KEY (transmission_capacity_group_scenario_id) REFERENCES
        subscenarios_transmission_capacity_groups (transmission_capacity_group_scenario_id)
);

-- Simultaneous flows
-- Limits on net flows on groups of lines (e.g. all lines connected to a zone)
DROP TABLE IF EXISTS subscenarios_transmission_simultaneous_flow_limits;
CREATE TABLE subscenarios_transmission_simultaneous_flow_limits
(
    transmission_simultaneous_flow_limit_scenario_id INTEGER
        PRIMARY KEY AUTOINCREMENT,
    name                                             VARCHAR(32),
    description                                      VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_simultaneous_flow_limits;
CREATE TABLE inputs_transmission_simultaneous_flow_limits
(
    transmission_simultaneous_flow_limit_scenario_id INTEGER,
    transmission_simultaneous_flow_limit             VARCHAR(64),
    period                                           INTEGER,
    max_flow_mw                                      FLOAT,
    PRIMARY KEY (transmission_simultaneous_flow_limit_scenario_id,
                 transmission_simultaneous_flow_limit, period),
    FOREIGN KEY (transmission_simultaneous_flow_limit_scenario_id) REFERENCES
        subscenarios_transmission_simultaneous_flow_limits
            (transmission_simultaneous_flow_limit_scenario_id)
);


DROP TABLE IF EXISTS
    subscenarios_transmission_simultaneous_flow_limit_line_groups;
CREATE TABLE subscenarios_transmission_simultaneous_flow_limit_line_groups
(
    transmission_simultaneous_flow_limit_line_group_scenario_id INTEGER PRIMARY KEY
        AUTOINCREMENT,
    name                                                        VARCHAR(32),
    description                                                 VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_simultaneous_flow_limit_line_groups;
CREATE TABLE inputs_transmission_simultaneous_flow_limit_line_groups
(
    transmission_simultaneous_flow_limit_line_group_scenario_id INTEGER,
    transmission_simultaneous_flow_limit                        VARCHAR(64),
    transmission_line                                           VARCHAR(64),
    simultaneous_flow_coefficient                               INTEGER,
    PRIMARY KEY (transmission_simultaneous_flow_limit_line_group_scenario_id,
                 transmission_simultaneous_flow_limit, transmission_line),
    FOREIGN KEY (transmission_simultaneous_flow_limit_line_group_scenario_id)
        REFERENCES subscenarios_transmission_simultaneous_flow_limit_line_groups
            (transmission_simultaneous_flow_limit_line_group_scenario_id)
);


------------------
-- -- SYSTEM -- --
------------------

-- -- Load balance -- --
DROP TABLE IF EXISTS subscenarios_system_load;
CREATE TABLE subscenarios_system_load
(
    load_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name             VARCHAR(32),
    description      VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_load;
CREATE TABLE inputs_system_load
(
    load_scenario_id            INTEGER,
    load_components_scenario_id INTEGER,
    load_levels_scenario_id     INTEGER,
    PRIMARY KEY (load_scenario_id, load_components_scenario_id,
                 load_levels_scenario_id),
    FOREIGN KEY (load_scenario_id) REFERENCES subscenarios_system_load
        (load_scenario_id)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and load_zone_scenario_id
DROP TABLE IF EXISTS subscenarios_system_load_components;
CREATE TABLE subscenarios_system_load_components
(
    load_components_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        VARCHAR(32),
    description                 VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_load_components;
CREATE TABLE inputs_system_load_components
(
    load_components_scenario_id                        INTEGER,
    load_zone                                          VARCHAR(32),
    load_component                                     TEXT,
    load_level_default                                 FLOAT, -- defaults to infinity in model
    load_component_distribution_loss_adjustment_factor FLOAT, --default to 0 in model
    PRIMARY KEY (load_components_scenario_id, load_zone, load_component)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and load_zone_scenario_id
DROP TABLE IF EXISTS subscenarios_system_load_levels;
CREATE TABLE subscenarios_system_load_levels
(
    load_levels_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    VARCHAR(32),
    description             VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_load_levels;
CREATE TABLE inputs_system_load_levels
(
    load_levels_scenario_id INTEGER,
    load_zone               VARCHAR(32),
    weather_iteration       INTEGER,
    stage_id                INTEGER,
    timepoint               INTEGER,
    load_component          TEXT,
    load_mw                 FLOAT,
    PRIMARY KEY (load_levels_scenario_id, load_zone, weather_iteration,
                 stage_id,
                 timepoint, load_component)
);


-- Markets
-- Load zone markets
DROP TABLE IF EXISTS subscenarios_load_zone_markets;
CREATE TABLE subscenarios_load_zone_markets
(
    load_zone_market_scenario_id INTEGER PRIMARY KEY,
    name                         VARCHAR(32),
    description                  VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_load_zone_markets;
CREATE TABLE inputs_load_zone_markets
(
    load_zone_market_scenario_id INTEGER,
    load_zone                    VARCHAR(64),
    market                       VARCHAR(32),
    final_participation_stage    INTEGER, -- can leave NULL, defaults to 1 in model
    PRIMARY KEY (load_zone_market_scenario_id, load_zone, market),
    FOREIGN KEY (load_zone_market_scenario_id)
        REFERENCES subscenarios_load_zone_markets (load_zone_market_scenario_id)
);


-- -- Reserves -- --

-- LF reserves up
DROP TABLE IF EXISTS subscenarios_system_lf_reserves_up;
CREATE TABLE subscenarios_system_lf_reserves_up
(
    lf_reserves_up_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                       VARCHAR(32),
    description                VARCHAR(128)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and reserves_scenario_id
DROP TABLE IF EXISTS inputs_system_lf_reserves_up;
CREATE TABLE inputs_system_lf_reserves_up
(
    lf_reserves_up_scenario_id INTEGER,
    lf_reserves_up_ba          VARCHAR(32),
    stage_id                   INTEGER,
    timepoint                  INTEGER,
    lf_reserves_up_mw          FLOAT,
    PRIMARY KEY (lf_reserves_up_scenario_id, lf_reserves_up_ba, stage_id,
                 timepoint),
    FOREIGN KEY (lf_reserves_up_scenario_id) REFERENCES
        subscenarios_system_lf_reserves_up (lf_reserves_up_scenario_id)
);

-- The requirement may be specified as percent of load, in which case we also
-- need to specify which load, i.e. specify a mapping between the reserve BA
-- and the load zones whose load should be part of the requirement
-- calculation (mapping should be one-to-many)
-- Note that the by-timepoint requirement and the percent requirement are additive
DROP TABLE IF EXISTS inputs_system_lf_reserves_up_percent;
CREATE TABLE inputs_system_lf_reserves_up_percent
(
    lf_reserves_up_scenario_id INTEGER,
    lf_reserves_up_ba          VARCHAR(32),
    stage_id                   INTEGER,
    percent_load_req           FLOAT,
    PRIMARY KEY (lf_reserves_up_scenario_id, lf_reserves_up_ba, stage_id)
);

DROP TABLE IF EXISTS inputs_system_lf_reserves_up_percent_lz_map;
CREATE TABLE inputs_system_lf_reserves_up_percent_lz_map
(
    lf_reserves_up_scenario_id INTEGER,
    lf_reserves_up_ba          VARCHAR(32),
    load_zone                  VARCHAR(32),
    PRIMARY KEY (lf_reserves_up_scenario_id, lf_reserves_up_ba, load_zone)
);

-- Projects can also contribute to the requirement, specified as percent of their
-- power output in a timepoint or a percentage of their capacity
-- Note this is additive to the by-timepoint and percent requirements
DROP TABLE IF EXISTS inputs_system_lf_reserves_up_project;
CREATE TABLE inputs_system_lf_reserves_up_project
(
    lf_reserves_up_scenario_id INTEGER,
    lf_reserves_up_ba          VARCHAR(32),
    stage_id                   INTEGER,
    project                    VARCHAR(64),
    percent_power_req          FLOAT,
    percent_capacity_req       FLOAT,
    PRIMARY KEY (lf_reserves_up_scenario_id, lf_reserves_up_ba, stage_id,
                 project)
);

-- LF reserves down
DROP TABLE IF EXISTS subscenarios_system_lf_reserves_down;
CREATE TABLE subscenarios_system_lf_reserves_down
(
    lf_reserves_down_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                         VARCHAR(32),
    description                  VARCHAR(128)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and reserves_scenario_id
DROP TABLE IF EXISTS inputs_system_lf_reserves_down;
CREATE TABLE inputs_system_lf_reserves_down
(
    lf_reserves_down_scenario_id INTEGER,
    lf_reserves_down_ba          VARCHAR(32),
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    lf_reserves_down_mw          FLOAT,
    PRIMARY KEY (lf_reserves_down_scenario_id, lf_reserves_down_ba, stage_id,
                 timepoint),
    FOREIGN KEY (lf_reserves_down_scenario_id) REFERENCES
        subscenarios_system_lf_reserves_down (lf_reserves_down_scenario_id)
);

-- The requirement may be specified as percent of load, in which case we also
-- need to specify which load, i.e. specify a mapping between the reserve BA
-- and the load zones whose load should be part of the requirement
-- calculation (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_lf_reserves_down_percent;
CREATE TABLE inputs_system_lf_reserves_down_percent
(
    lf_reserves_down_scenario_id INTEGER,
    lf_reserves_down_ba          VARCHAR(32),
    stage_id                     INTEGER,
    percent_load_req             FLOAT,
    PRIMARY KEY (lf_reserves_down_scenario_id, lf_reserves_down_ba, stage_id)
);

DROP TABLE IF EXISTS inputs_system_lf_reserves_down_percent_lz_map;
CREATE TABLE inputs_system_lf_reserves_down_percent_lz_map
(
    lf_reserves_down_scenario_id INTEGER,
    lf_reserves_down_ba          VARCHAR(32),
    load_zone                    VARCHAR(32),
    PRIMARY KEY (lf_reserves_down_scenario_id, lf_reserves_down_ba, load_zone)
);

-- Projects can also contribute to the requirement, specified as percent of their
-- power output in a timepoint or a percentage of their capacity
-- Note this is additive to the by-timepoint and percent requirements
DROP TABLE IF EXISTS inputs_system_lf_reserves_down_project;
CREATE TABLE inputs_system_lf_reserves_down_project
(
    lf_reserves_down_scenario_id INTEGER,
    lf_reserves_down_ba          VARCHAR(32),
    stage_id                     INTEGER,
    project                      VARCHAR(64),
    percent_power_req            FLOAT,
    percent_capacity_req         FLOAT,
    PRIMARY KEY (lf_reserves_down_scenario_id, lf_reserves_down_ba, stage_id,
                 project)
);

-- Regulation up
DROP TABLE IF EXISTS subscenarios_system_regulation_up;
CREATE TABLE subscenarios_system_regulation_up
(
    regulation_up_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                      VARCHAR(32),
    description               VARCHAR(128)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and reserves_scenario_id
DROP TABLE IF EXISTS inputs_system_regulation_up;
CREATE TABLE inputs_system_regulation_up
(
    regulation_up_scenario_id INTEGER,
    regulation_up_ba          VARCHAR(32),
    stage_id                  INTEGER,
    timepoint                 INTEGER,
    regulation_up_mw          FLOAT,
    PRIMARY KEY (regulation_up_scenario_id, regulation_up_ba, stage_id,
                 timepoint),
    FOREIGN KEY (regulation_up_scenario_id) REFERENCES
        subscenarios_system_regulation_up (regulation_up_scenario_id)
);

-- The requirement may be specified as percent of load, in which case we also
-- need to specify which load, i.e. specify a mapping between the reserve BA
-- and the load zones whose load should be part of the requirement
-- calculation (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_regulation_down_percent;
CREATE TABLE inputs_system_regulation_down_percent
(
    regulation_down_scenario_id INTEGER,
    regulation_down_ba          VARCHAR(32),
    stage_id                    INTEGER,
    percent_load_req            FLOAT,
    PRIMARY KEY (regulation_down_scenario_id, regulation_down_ba, stage_id)
);

DROP TABLE IF EXISTS inputs_system_regulation_down_percent_lz_map;
CREATE TABLE inputs_system_regulation_down_percent_lz_map
(
    regulation_down_scenario_id INTEGER,
    regulation_down_ba          VARCHAR(32),
    load_zone                   VARCHAR(32),
    PRIMARY KEY (regulation_down_scenario_id, regulation_down_ba, load_zone)
);

-- Projects can also contribute to the requirement, specified as percent of their
-- power output in a timepoint or a percentage of their capacity
-- Note this is additive to the by-timepoint and percent requirements
DROP TABLE IF EXISTS inputs_system_regulation_down_project;
CREATE TABLE inputs_system_regulation_down_project
(
    regulation_down_scenario_id INTEGER,
    regulation_down_ba          VARCHAR(32),
    stage_id                    INTEGER,
    project                     VARCHAR(64),
    percent_power_req           FLOAT,
    percent_capacity_req        FLOAT,
    PRIMARY KEY (regulation_down_scenario_id, regulation_down_ba, stage_id,
                 project)
);

-- Regulation down
DROP TABLE IF EXISTS subscenarios_system_regulation_down;
CREATE TABLE subscenarios_system_regulation_down
(
    regulation_down_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        VARCHAR(32),
    description                 VARCHAR(128)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and reserves_scenario_id
DROP TABLE IF EXISTS inputs_system_regulation_down;
CREATE TABLE inputs_system_regulation_down
(
    regulation_down_scenario_id INTEGER,
    regulation_down_ba          VARCHAR(32),
    stage_id                    INTEGER,
    timepoint                   INTEGER,
    regulation_down_mw          FLOAT,
    PRIMARY KEY (regulation_down_scenario_id, regulation_down_ba, stage_id,
                 timepoint),
    FOREIGN KEY (regulation_down_scenario_id) REFERENCES
        subscenarios_system_regulation_down (regulation_down_scenario_id)
);

-- The requirement may be specified as percent of load, in which case we also
-- need to specify which load, i.e. specify a mapping between the reserve BA
-- and the load zones whose load should be part of the requirement
-- calculation (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_regulation_up_percent;
CREATE TABLE inputs_system_regulation_up_percent
(
    regulation_up_scenario_id INTEGER,
    regulation_up_ba          VARCHAR(32),
    stage_id                  INTEGER,
    percent_load_req          FLOAT,
    PRIMARY KEY (regulation_up_scenario_id, regulation_up_ba, stage_id)
);

DROP TABLE IF EXISTS inputs_system_regulation_up_percent_lz_map;
CREATE TABLE inputs_system_regulation_up_percent_lz_map
(
    regulation_up_scenario_id INTEGER,
    regulation_up_ba          VARCHAR(32),
    load_zone                 VARCHAR(32),
    PRIMARY KEY (regulation_up_scenario_id, regulation_up_ba, load_zone)
);

-- Projects can also contribute to the requirement, specified as percent of their
-- power output in a timepoint or a percentage of their capacity
-- Note this is additive to the by-timepoint and percent requirements
DROP TABLE IF EXISTS inputs_system_regulation_up_project;
CREATE TABLE inputs_system_regulation_up_project
(
    regulation_up_scenario_id INTEGER,
    regulation_up_ba          VARCHAR(32),
    stage_id                  INTEGER,
    project                   VARCHAR(64),
    percent_power_req         FLOAT,
    percent_capacity_req      FLOAT,
    PRIMARY KEY (regulation_up_scenario_id, regulation_up_ba, stage_id, project)
);


-- Frequency response
DROP TABLE IF EXISTS subscenarios_system_frequency_response;
CREATE TABLE subscenarios_system_frequency_response
(
    frequency_response_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                           VARCHAR(32),
    description                    VARCHAR(128)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and reserves_scenario_id
DROP TABLE IF EXISTS inputs_system_frequency_response;
CREATE TABLE inputs_system_frequency_response
(
    frequency_response_scenario_id INTEGER,
    frequency_response_ba          VARCHAR(32),
    stage_id                       INTEGER,
    timepoint                      INTEGER,
    frequency_response_mw          FLOAT,
    frequency_response_partial_mw  FLOAT,
    PRIMARY KEY (frequency_response_scenario_id, frequency_response_ba,
                 stage_id,
                 timepoint),
    FOREIGN KEY (frequency_response_scenario_id) REFERENCES
        subscenarios_system_frequency_response (frequency_response_scenario_id)
);

-- The requirement may be specified as percent of load, in which case we also
-- need to specify which load, i.e. specify a mapping between the reserve BA
-- and the load zones whose load should be part of the requirement
-- calculation (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_frequency_response_percent;
CREATE TABLE inputs_system_frequency_response_percent
(
    frequency_response_scenario_id INTEGER,
    frequency_response_ba          VARCHAR(32),
    stage_id                       INTEGER,
    percent_load_req               FLOAT,
    PRIMARY KEY (frequency_response_scenario_id, frequency_response_ba,
                 stage_id)
);

DROP TABLE IF EXISTS inputs_system_frequency_response_percent_lz_map;
CREATE TABLE inputs_system_frequency_response_percent_lz_map
(
    frequency_response_scenario_id INTEGER,
    frequency_response_ba          VARCHAR(32),
    load_zone                      VARCHAR(32),
    PRIMARY KEY (frequency_response_scenario_id, frequency_response_ba,
                 load_zone)
);

-- Projects can also contribute to the requirement, specified as percent of their
-- power output in a timepoint or a percentage of their capacity
-- Note this is additive to the by-timepoint and percent requirements
DROP TABLE IF EXISTS inputs_system_frequency_response_project;
CREATE TABLE inputs_system_frequency_response_project
(
    frequency_response_scenario_id INTEGER,
    frequency_response_ba          VARCHAR(32),
    stage_id                       INTEGER,
    project                        VARCHAR(64),
    percent_power_req              FLOAT,
    percent_capacity_req           FLOAT,
    PRIMARY KEY (frequency_response_scenario_id, frequency_response_ba,
                 stage_id, project)
);

-- Spinning reserves
DROP TABLE IF EXISTS subscenarios_system_spinning_reserves;
CREATE TABLE subscenarios_system_spinning_reserves
(
    spinning_reserves_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                          VARCHAR(32),
    description                   VARCHAR(128)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and reserves_scenario_id
DROP TABLE IF EXISTS inputs_system_spinning_reserves;
CREATE TABLE inputs_system_spinning_reserves
(
    spinning_reserves_scenario_id INTEGER,
    spinning_reserves_ba          VARCHAR(32),
    stage_id                      INTEGER,
    timepoint                     INTEGER,
    spinning_reserves_mw          FLOAT,
    PRIMARY KEY (spinning_reserves_scenario_id, spinning_reserves_ba, stage_id,
                 timepoint),
    FOREIGN KEY (spinning_reserves_scenario_id) REFERENCES
        subscenarios_system_spinning_reserves (spinning_reserves_scenario_id)
);

-- The requirement may be specified as percent of load, in which case we also
-- need to specify which load, i.e. specify a mapping between the reserve BA
-- and the load zones whose load should be part of the requirement
-- calculation (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_spinning_reserves_percent;
CREATE TABLE inputs_system_spinning_reserves_percent
(
    spinning_reserves_scenario_id INTEGER,
    spinning_reserves_ba          VARCHAR(32),
    stage_id                      INTEGER,
    percent_load_req              FLOAT,
    PRIMARY KEY (spinning_reserves_scenario_id, spinning_reserves_ba, stage_id)
);

DROP TABLE IF EXISTS inputs_system_spinning_reserves_percent_lz_map;
CREATE TABLE inputs_system_spinning_reserves_percent_lz_map
(
    spinning_reserves_scenario_id INTEGER,
    spinning_reserves_ba          VARCHAR(32),
    load_zone                     VARCHAR(32),
    PRIMARY KEY (spinning_reserves_scenario_id, spinning_reserves_ba, load_zone)
);

-- Projects can also contribute to the requirement, specified as percent of their
-- power output in a timepoint or a percentage of their capacity
-- Note this is additive to the by-timepoint and percent requirements
DROP TABLE IF EXISTS inputs_system_spinning_reserves_project;
CREATE TABLE inputs_system_spinning_reserves_project
(
    spinning_reserves_scenario_id INTEGER,
    spinning_reserves_ba          VARCHAR(32),
    stage_id                      INTEGER,
    project                       VARCHAR(64),
    percent_power_req             FLOAT,
    percent_capacity_req          FLOAT,
    PRIMARY KEY (spinning_reserves_scenario_id, spinning_reserves_ba, stage_id,
                 project)
);


-- inertia reserves
DROP TABLE IF EXISTS subscenarios_system_inertia_reserves;
CREATE TABLE subscenarios_system_inertia_reserves
(
    inertia_reserves_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                         VARCHAR(32),
    description                  VARCHAR(128)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and reserves_scenario_id
DROP TABLE IF EXISTS inputs_system_inertia_reserves;
CREATE TABLE inputs_system_inertia_reserves
(
    inertia_reserves_scenario_id INTEGER,
    inertia_reserves_ba          VARCHAR(32),
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    inertia_reserves_mws         FLOAT,
    PRIMARY KEY (inertia_reserves_scenario_id, inertia_reserves_ba, stage_id,
                 timepoint),
    FOREIGN KEY (inertia_reserves_scenario_id) REFERENCES
        subscenarios_system_inertia_reserves (inertia_reserves_scenario_id)
);

-- The requirement may be specified as percent of load, in which case we also
-- need to specify which load, i.e. specify a mapping between the reserve BA
-- and the load zones whose load should be part of the requirement
-- calculation (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_inertia_reserves_percent;
CREATE TABLE inputs_system_inertia_reserves_percent
(
    inertia_reserves_scenario_id INTEGER,
    inertia_reserves_ba          VARCHAR(32),
    stage_id                     INTEGER,
    percent_load_req             FLOAT,
    PRIMARY KEY (inertia_reserves_scenario_id, inertia_reserves_ba, stage_id)
);

DROP TABLE IF EXISTS inputs_system_inertia_reserves_percent_lz_map;
CREATE TABLE inputs_system_inertia_reserves_percent_lz_map
(
    inertia_reserves_scenario_id INTEGER,
    inertia_reserves_ba          VARCHAR(32),
    load_zone                    VARCHAR(32),
    PRIMARY KEY (inertia_reserves_scenario_id, inertia_reserves_ba, load_zone)
);

-- Projects can also contribute to the requirement, specified as percent of their
-- power output in a timepoint or a percentage of their capacity
-- Note this is additive to the by-timepoint and percent requirements
DROP TABLE IF EXISTS inputs_system_inertia_reserves_project;
CREATE TABLE inputs_system_inertia_reserves_project
(
    inertia_reserves_scenario_id INTEGER,
    inertia_reserves_ba          VARCHAR(32),
    stage_id                     INTEGER,
    project                      VARCHAR(64),
    percent_power_req            FLOAT,
    percent_capacity_req         FLOAT,
    PRIMARY KEY (inertia_reserves_scenario_id, inertia_reserves_ba, stage_id,
                 project)
);

DROP TABLE IF EXISTS inputs_system_inertia_reserves_param;
CREATE TABLE inputs_system_inertia_reserves_param
(
    inertia_reserves_scenario_id INTEGER,
    inertia_reserves_ba          VARCHAR(32),
    base_system_frequecy_hz      FLOAT,
    maximum_rocof_hz_per_s       FLOAT,
    PRIMARY KEY (inertia_reserves_scenario_id, inertia_reserves_ba)
);


-- -- Policy -- --

-- Energy target requirements
-- By period
DROP TABLE IF EXISTS subscenarios_system_period_energy_targets;
CREATE TABLE subscenarios_system_period_energy_targets
(
    period_energy_target_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                             VARCHAR(32),
    description                      VARCHAR(128)
);

-- Can include periods and zones other than the ones in a scenario, as correct
-- periods and zones will be pulled depending on temporal_scenario_id and
-- energy_target_zone_scenario_id
DROP TABLE IF EXISTS inputs_system_period_energy_targets;
CREATE TABLE inputs_system_period_energy_targets
(
    period_energy_target_scenario_id INTEGER,
    energy_target_zone               VARCHAR(32),
    subproblem_id                    INTEGER,
    stage_id                         INTEGER,
    period                           INTEGER,
    energy_target_mwh                FLOAT,
    energy_target_fraction           FLOAT,
    PRIMARY KEY (period_energy_target_scenario_id, energy_target_zone,
                 subproblem_id, stage_id, period)
);

-- If the energy target is specified as percentage of load, we need to also
-- specify which load, i.e. specify a mapping between the energy target zone
-- and the load zones whose load should be part of the target calculation
-- (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_period_energy_target_load_zone_map;
CREATE TABLE inputs_system_period_energy_target_load_zone_map
(
    period_energy_target_scenario_id INTEGER,
    energy_target_zone               VARCHAR(32),
    load_zone                        VARCHAR(64),
    PRIMARY KEY (period_energy_target_scenario_id, energy_target_zone,
                 load_zone)
);

-- By horizon
DROP TABLE IF EXISTS subscenarios_system_horizon_energy_targets;
CREATE TABLE subscenarios_system_horizon_energy_targets
(
    horizon_energy_target_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                              VARCHAR(32),
    description                       VARCHAR(128)
);

-- Can include periods and zones other than the ones in a scenario, as correct
-- periods and zones will be pulled depending on temporal_scenario_id and
-- energy_target_zone_scenario_id
DROP TABLE IF EXISTS inputs_system_horizon_energy_targets;
CREATE TABLE inputs_system_horizon_energy_targets
(
    horizon_energy_target_scenario_id INTEGER,
    energy_target_zone                VARCHAR(32),
    subproblem_id                     INTEGER,
    stage_id                          INTEGER,
    balancing_type_horizon            VARCHAR(64),
    horizon                           INTEGER,
    energy_target_mwh                 FLOAT,
    energy_target_fraction            FLOAT,
    PRIMARY KEY (horizon_energy_target_scenario_id, energy_target_zone,
                 subproblem_id, stage_id, balancing_type_horizon, horizon)
);

-- If the energy target is specified as percentage of load, we need to also
-- specify which load, i.e. specify a mapping between the energy target zone
-- and the load zones whose load should be part of the target calculation
-- (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_horizon_energy_target_load_zone_map;
CREATE TABLE inputs_system_horizon_energy_target_load_zone_map
(
    horizon_energy_target_scenario_id INTEGER,
    energy_target_zone                VARCHAR(32),
    load_zone                         VARCHAR(64),
    PRIMARY KEY (horizon_energy_target_scenario_id, energy_target_zone,
                 load_zone)
);

-- Instantaneous penetration
DROP TABLE IF EXISTS subscenarios_system_instantaneous_penetration;
CREATE TABLE subscenarios_system_instantaneous_penetration
(
    instantaneous_penetration_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                  VARCHAR(32),
    description                           VARCHAR(128)
);

-- Can include timepoints and zones other than the ones in a scenario, as
-- correct timepoints and zones will be pulled depending on
-- temporal_scenario_id and instantaneous_penetration_scenario_id
DROP TABLE IF EXISTS inputs_system_instantaneous_penetration;
CREATE TABLE inputs_system_instantaneous_penetration
(
    instantaneous_penetration_scenario_id INTEGER,
    instantaneous_penetration_zone        VARCHAR(32),
    stage_id                              INTEGER,
    timepoint                             INTEGER,
    min_instantaneous_penetration_mw      FLOAT,
    max_instantaneous_penetration_mw      FLOAT,
    PRIMARY KEY (instantaneous_penetration_scenario_id,
                 instantaneous_penetration_zone, stage_id,
                 timepoint),
    FOREIGN KEY (instantaneous_penetration_scenario_id) REFERENCES
        subscenarios_system_instantaneous_penetration (instantaneous_penetration_scenario_id)
);

-- The requirement may be specified as percent of load, in which case we also
-- need to specify which load, i.e. specify a mapping between the instantaneous_penetration_zone
-- and the load zones whose load should be part of the requirement
-- calculation (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_instantaneous_penetration_percent;
CREATE TABLE inputs_system_instantaneous_penetration_percent
(
    instantaneous_penetration_scenario_id INTEGER,
    instantaneous_penetration_zone        VARCHAR(32),
    stage_id                              INTEGER,
    min_percent_load                      FLOAT,
    max_percent_load                      FLOAT,
    PRIMARY KEY (instantaneous_penetration_scenario_id,
                 instantaneous_penetration_zone, stage_id)
);

DROP TABLE IF EXISTS inputs_system_instantaneous_penetration_percent_lz_map;
CREATE TABLE inputs_system_instantaneous_penetration_percent_lz_map
(
    instantaneous_penetration_scenario_id INTEGER,
    instantaneous_penetration_zone        VARCHAR(32),
    load_zone                             VARCHAR(32),
    PRIMARY KEY (instantaneous_penetration_scenario_id,
                 instantaneous_penetration_zone, load_zone)
);

-- Projects can also contribute to the requirement, specified as percent of their
-- power output in a timepoint or a percentage of their capacity
-- Note this is additive to the by-timepoint and percent requirements
DROP TABLE IF EXISTS inputs_system_instantaneous_penetration_project;
CREATE TABLE inputs_system_instantaneous_penetration_project
(
    instantaneous_penetration_scenario_id INTEGER,
    instantaneous_penetration_zone        VARCHAR(32),
    stage_id                              INTEGER,
    project                               VARCHAR(64),
    min_ratio_power_req                   FLOAT,
    min_ratio_capacity_req                FLOAT,
    max_ratio_power_req                   FLOAT,
    max_ratio_capacity_req                FLOAT,
    PRIMARY KEY (instantaneous_penetration_scenario_id,
                 instantaneous_penetration_zone, stage_id,
                 project)
);

-- Transmission target requirements
-- By period
DROP TABLE IF EXISTS subscenarios_system_transmission_targets;
CREATE TABLE subscenarios_system_transmission_targets
(
    transmission_target_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                            VARCHAR(32),
    description                     VARCHAR(128)
);

-- Can include bt-horizons and zones other than the ones in a scenario, as
-- correct bt-horizons and zones will be pulled depending on the
-- temporal_scenario_id and transmission_target_zone_scenario_id
DROP TABLE IF EXISTS inputs_system_transmission_targets;
CREATE TABLE inputs_system_transmission_targets
(
    transmission_target_scenario_id     INTEGER,
    transmission_target_zone            VARCHAR(32),
    subproblem_id                       INTEGER,
    stage_id                            INTEGER,
    balancing_type                      VARCHAR(32),
    horizon                             INTEGER,
    transmission_target_pos_dir_min_mwh FLOAT,
    transmission_target_pos_dir_max_mwh FLOAT,
    transmission_target_neg_dir_min_mwh FLOAT,
    transmission_target_neg_dir_max_mwh FLOAT,
    PRIMARY KEY (transmission_target_scenario_id, transmission_target_zone,
                 subproblem_id, stage_id, balancing_type, horizon)
);

-- Carbon cap
DROP TABLE IF EXISTS subscenarios_system_carbon_cap_targets;
CREATE TABLE subscenarios_system_carbon_cap_targets
(
    carbon_cap_target_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                          VARCHAR(32),
    description                   VARCHAR(128)
);

-- Can include periods and zones other than the ones in a scenario, as correct
-- periods and zones will be pulled depending on temporal_scenario_id and
-- carbon_cap_zone_scenario_id
DROP TABLE IF EXISTS inputs_system_carbon_cap_targets;
CREATE TABLE inputs_system_carbon_cap_targets
(
    carbon_cap_target_scenario_id INTEGER,
    carbon_cap_zone               VARCHAR(32),
    period                        INTEGER,
    subproblem_id                 INTEGER,
    stage_id                      INTEGER,
    carbon_cap                    FLOAT,
    PRIMARY KEY (carbon_cap_target_scenario_id, carbon_cap_zone, period,
                 subproblem_id, stage_id),
    FOREIGN KEY (carbon_cap_target_scenario_id) REFERENCES
        subscenarios_system_carbon_cap_targets (carbon_cap_target_scenario_id)
);

-- Carbon tax
DROP TABLE IF EXISTS subscenarios_system_carbon_tax;
CREATE TABLE subscenarios_system_carbon_tax
(
    carbon_tax_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   VARCHAR(32),
    description            VARCHAR(128)
);

-- Can include periods and zones other than the ones in a scenario, as correct
-- periods and zones will be pulled depending on temporal_scenario_id and
-- carbon_tax_zone_scenario_id
DROP TABLE IF EXISTS inputs_system_carbon_tax;
CREATE TABLE inputs_system_carbon_tax
(
    carbon_tax_scenario_id INTEGER,
    carbon_tax_zone        VARCHAR(32),
    period                 INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    carbon_tax             FLOAT,
    PRIMARY KEY (carbon_tax_scenario_id, carbon_tax_zone, period,
                 subproblem_id, stage_id),
    FOREIGN KEY (carbon_tax_scenario_id) REFERENCES
        subscenarios_system_carbon_tax (carbon_tax_scenario_id)
);

-- Performance standard
DROP TABLE IF EXISTS subscenarios_system_performance_standard;
CREATE TABLE subscenarios_system_performance_standard
(
    performance_standard_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                             VARCHAR(32),
    description                      VARCHAR(128)
);

-- Can include periods and zones other than the ones in a scenario, as correct
-- periods and zones will be pulled depending on temporal_scenario_id and
-- performance_standard_zone_scenario_id
DROP TABLE IF EXISTS inputs_system_performance_standard;
CREATE TABLE inputs_system_performance_standard
(
    performance_standard_scenario_id  INTEGER,
    performance_standard_zone         VARCHAR(32),
    period                            INTEGER,
    subproblem_id                     INTEGER,
    stage_id                          INTEGER,
    performance_standard_tco2_per_mwh FLOAT,
    performance_standard_tco2_per_mw  FLOAT,
    PRIMARY KEY (performance_standard_scenario_id, performance_standard_zone,
                 period,
                 subproblem_id, stage_id),
    FOREIGN KEY (performance_standard_scenario_id) REFERENCES
        subscenarios_system_performance_standard (performance_standard_scenario_id)
);

-- Generic policy
DROP TABLE IF EXISTS subscenarios_system_policy_requirements;
CREATE TABLE subscenarios_system_policy_requirements
(
    policy_requirement_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                           VARCHAR(32),
    description                    VARCHAR(128)
);

-- Can include bt-horizons and zones other than the ones in a scenario, as
-- correct temporal index and zones will be pulled depending on
-- temporal_scenario_id and policy_requirement_scenario_id
DROP TABLE IF EXISTS inputs_system_policy_requirements;
CREATE TABLE inputs_system_policy_requirements
(
    policy_requirement_scenario_id  INTEGER,
    policy_name                     TEXT,
    policy_zone                     TEXT,
    subproblem_id                   INTEGER,
    stage_id                        INTEGER,
    balancing_type_horizon          VARCHAR(64),
    horizon                         INTEGER,
    policy_requirement              FLOAT,
    policy_requirement_f_load_coeff FLOAT,
    PRIMARY KEY (policy_requirement_scenario_id, policy_name, policy_zone,
                 subproblem_id, stage_id, balancing_type_horizon, horizon)
);

DROP TABLE IF EXISTS inputs_system_policy_month_hour_requirements;
CREATE TABLE inputs_system_policy_month_hour_requirements
(
    policy_requirement_scenario_id INTEGER,
    policy_name                    TEXT,
    policy_zone                    TEXT,
    period                         INTEGER,
    policy_month                   INTEGER,
    policy_hour                    INTEGER,
    policy_requirement             FLOAT,
    PRIMARY KEY (policy_requirement_scenario_id, policy_name, policy_zone,
                 period, policy_month, policy_hour)
);

-- If the policy requirement is specified as a function of load, we need to also
-- specify which load, i.e. specify a mapping between the policy zone
-- and the load zones whose load should be part of the requirement calculation
-- (mapping should be one-to-many)
DROP TABLE IF EXISTS inputs_system_policy_requirements_load_zone_map;
CREATE TABLE inputs_system_policy_requirements_load_zone_map
(
    policy_requirement_scenario_id INTEGER,
    policy_name                    TEXT,
    policy_zone                    TEXT,
    load_zone                      TEXT,
    PRIMARY KEY (policy_requirement_scenario_id, policy_name, policy_zone,
                 load_zone)
);

-- Project, policy, zones
-- Which projects count toward which policies and "zones"
-- Projects are allowed to contribute to more than one policy and to
-- different zones within the same policy
DROP TABLE IF EXISTS subscenarios_project_policy_zones;
CREATE TABLE subscenarios_project_policy_zones
(
    project_policy_zone_scenario_id INTEGER PRIMARY KEY,
    name                            VARCHAR(32),
    description                     VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_project_policy_zones;
CREATE TABLE inputs_project_policy_zones
(
    project_policy_zone_scenario_id INTEGER,
    project                         TEXT,
    policy_name                     TEXT,
    policy_zone                     TEXT,
    compliance_type                 TEXT,
    f_slope                         FLOAT, -- frac power in tmp
    f_intercept                     FLOAT, -- frac capacity in tmp
    exceedance_values_scenario_id   INTEGER,
    sod_stor_rte                    FLOAT,
    PRIMARY KEY (project_policy_zone_scenario_id, project, policy_name,
                 policy_zone),
    FOREIGN KEY (project_policy_zone_scenario_id) REFERENCES
        subscenarios_project_policy_zones (project_policy_zone_scenario_id)
);

-- Transmission lines, policy, policy_zones
-- Which transmission lines count toward which policies and "zones" (e.g.
-- via their losses to avoid "delivering" policy-eligible energy via Tx losses)
DROP TABLE IF EXISTS subscenarios_transmission_policy_zones;
CREATE TABLE subscenarios_transmission_policy_zones
(
    transmission_policy_zone_scenario_id INTEGER PRIMARY KEY,
    name                                 VARCHAR(32),
    description                          VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_transmission_policy_zones;
CREATE TABLE inputs_transmission_policy_zones
(
    transmission_policy_zone_scenario_id INTEGER,
    transmission_line                    TEXT,
    policy_name                          TEXT,
    policy_zone                          TEXT,
    compliance_type                      TEXT,
    PRIMARY KEY (transmission_policy_zone_scenario_id, transmission_line,
                 policy_name, policy_zone),
    FOREIGN KEY (transmission_policy_zone_scenario_id) REFERENCES
        subscenarios_transmission_policy_zones
            (transmission_policy_zone_scenario_id)
);

DROP TABLE IF EXISTS subscenarios_project_policy_exceedance_values;
CREATE TABLE subscenarios_project_policy_exceedance_values
(
    project                       TEXT,
    exceedance_values_scenario_id INTEGER,
    name                          VARCHAR(32),
    description                   VARCHAR(128),
    PRIMARY KEY (project, exceedance_values_scenario_id)
);

DROP TABLE IF EXISTS inputs_project_policy_exceedance_values;
CREATE TABLE inputs_project_policy_exceedance_values
(
    project                       TEXT,
    exceedance_values_scenario_id INTEGER,
    period                        INTEGER,
    policy_month                  INTEGER,
    policy_hour                   INTEGER,
    cap_fac                       FLOAT,
    PRIMARY KEY (project, exceedance_values_scenario_id, period, policy_month,
                 policy_hour),
    FOREIGN KEY (project, exceedance_values_scenario_id) REFERENCES
        subscenarios_project_policy_exceedance_values (project, exceedance_values_scenario_id)
);


-- PRM requirements
DROP TABLE IF EXISTS subscenarios_system_prm_requirement;
CREATE TABLE subscenarios_system_prm_requirement
(
    prm_requirement_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        VARCHAR(32),
    description                 VARCHAR(128)
);

-- Can include periods and zones other than the ones in a scenario, as correct
-- periods and zones will be pulled depending on temporal_scenario_id and
-- prm_zone_scenario_id
DROP TABLE IF EXISTS inputs_system_prm_requirement;
CREATE TABLE inputs_system_prm_requirement
(
    prm_requirement_scenario_id INTEGER,
    prm_zone                    VARCHAR(32),
    period                      INTEGER,
    prm_requirement_mw          FLOAT,
    prm_peak_load_mw            FLOAT, -- for ELCC surface
    prm_annual_load_mwh         FLOAT, -- for ELCC surface
    PRIMARY KEY (prm_requirement_scenario_id, prm_zone, period)
);

-- Local capacity requirements
DROP TABLE IF EXISTS subscenarios_system_local_capacity_requirement;
CREATE TABLE subscenarios_system_local_capacity_requirement
(
    local_capacity_requirement_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                                   VARCHAR(32),
    description                            VARCHAR(128)
);

-- Can include periods and zones other than the ones in a scenario, as correct
-- periods and zones will be pulled depending on temporal_scenario_id and
-- local_capacity_zone_scenario_id
DROP TABLE IF EXISTS inputs_system_local_capacity_requirement;
CREATE TABLE inputs_system_local_capacity_requirement
(
    local_capacity_requirement_scenario_id INTEGER,
    local_capacity_zone                    VARCHAR(32),
    period                                 INTEGER,
    local_capacity_requirement_mw          FLOAT,
    PRIMARY KEY (local_capacity_requirement_scenario_id, local_capacity_zone,
                 period)
);

-- Fuel burn limits
DROP TABLE IF EXISTS subscenarios_system_fuel_burn_limits;
CREATE TABLE subscenarios_system_fuel_burn_limits
(
    fuel_burn_limit_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        VARCHAR(32),
    description                 VARCHAR(128)
);

-- Can include horizons and BAs other than the ones in a scenario, as correct
-- horizons and zones will be pulled depending on temporal_scenario_id and
-- fuel_burn_limit_ba_scenario_id
DROP TABLE IF EXISTS inputs_system_fuel_burn_limits;
CREATE TABLE inputs_system_fuel_burn_limits
(
    fuel_burn_limit_scenario_id                INTEGER,
    fuel_burn_limit_ba                         VARCHAR(32),
    subproblem_id                              INTEGER,
    stage_id                                   INTEGER,
    balancing_type_horizon                     VARCHAR(64),
    horizon                                    INTEGER,
    fuel_burn_min_unit                         FLOAT,
    fuel_burn_max_unit                         FLOAT,
    relative_fuel_burn_max_ba                  VARCHAR(32),
    fraction_of_relative_fuel_burn_max_fuel_ba FLOAT,
    PRIMARY KEY (fuel_burn_limit_scenario_id, fuel_burn_limit_ba,
                 subproblem_id, stage_id, balancing_type_horizon, horizon)
);

-- Subsidies (e.g., ITC)
DROP TABLE IF EXISTS subscenarios_system_subsidies;
CREATE TABLE subscenarios_system_subsidies
(
    subsidy_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name                VARCHAR(32),
    description         VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_system_system_subsides;
CREATE TABLE inputs_system_subsidies
(
    subsidy_scenario_id INTEGER,
    program             VARCHAR(32),
    superperiod         INTEGER,
    program_budget      FLOAT,
    PRIMARY KEY (subsidy_scenario_id, program, superperiod),
    FOREIGN KEY (subsidy_scenario_id) REFERENCES
        subscenarios_system_subsidies (subsidy_scenario_id)
);

DROP TABLE IF EXISTS inputs_system_subsidies_projects;
CREATE TABLE inputs_system_subsidies_projects
(
    subsidy_scenario_id    INTEGER,
    program                VARCHAR(32),
    project_or_tx          VARCHAR(64),
    vintage                INTEGER,
    is_tx                  INTEGER,
    annual_payment_subsidy FLOAT,
    PRIMARY KEY (subsidy_scenario_id, program, project_or_tx, vintage),
    FOREIGN KEY (subsidy_scenario_id) REFERENCES
        subscenarios_system_subsidies (subsidy_scenario_id)
);

-- Case tuning
-- We can apply additional costs in the model to prevent degeneracy
-- Currently this includes:
-- 1) Carbon Imports (see objective.transmission.carbon_imports_tuning_costs
-- module; prevents the carbon imports expression from being set above actual
-- flow x intensity in situations when the carbon cap is non-binding)
-- 2) Ramps (see project.operations.tuning_costs module; applies to
-- hydro and storage operational types only and prevents erratic-looking
-- dispatch for these zero-variable-cost resources in case of degeneracy)
-- 3) Dynamic ELCC (see objective.reliability.prm
-- .dynamic_elcc_tuning_penalties module; ensures that the dynamic ELCC is set
-- to the maximum available in
-- case the PRM constraint is non-binding.
DROP TABLE IF EXISTS subscenarios_tuning;
CREATE TABLE subscenarios_tuning
(
    tuning_scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name               VARCHAR(32),
    description        VARCHAR(128)
);

DROP TABLE IF EXISTS inputs_tuning;
CREATE TABLE inputs_tuning
(
    tuning_scenario_id                INTEGER PRIMARY KEY,
    import_carbon_tuning_cost_per_ton DOUBLE,
    ramp_tuning_cost_per_mw           DOUBLE, -- applies to hydro and storage only
    dynamic_elcc_tuning_cost_per_mw   DOUBLE,
    FOREIGN KEY (tuning_scenario_id) REFERENCES subscenarios_tuning
        (tuning_scenario_id)
);

---------------------
-- -- SCENARIOS -- --
---------------------
DROP TABLE IF EXISTS scenarios;
CREATE TABLE scenarios
(
    scenario_id                                                 INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_name                                               VARCHAR(64) UNIQUE,
    scenario_description                                        VARCHAR(256),
    validation_status_id                                        INTEGER        DEFAULT 0, -- status is 0 on scenario creation
    queue_order_id                                              INTEGER UNIQUE DEFAULT NULL,
    run_status_id                                               INTEGER        DEFAULT 0, -- status is 0 on scenario creation
    run_process_id                                              INTEGER        DEFAULT NULL,
    run_start_time                                              TIME,
    run_end_time                                                TIME,
    of_transmission                                             INTEGER,
    of_transmission_hurdle_rates                                INTEGER,
    of_transmission_hurdle_rates_by_timepoint                   INTEGER,
    of_simultaneous_flow_limits                                 INTEGER,
    of_lf_reserves_up                                           INTEGER,
    of_lf_reserves_down                                         INTEGER,
    of_regulation_up                                            INTEGER,
    of_regulation_down                                          INTEGER,
    of_frequency_response                                       INTEGER,
    of_spinning_reserves                                        INTEGER,
    of_inertia_reserves                                         INTEGER,
    of_period_energy_target                                     INTEGER,
    of_horizon_energy_target                                    INTEGER,
    of_transmission_target                                      INTEGER,
    of_instantaneous_penetration                                INTEGER,
    of_carbon_cap                                               INTEGER,
    of_track_carbon_imports                                     INTEGER,
    of_carbon_tax                                               INTEGER,
    of_performance_standard                                     INTEGER,
    of_carbon_credits                                           INTEGER,
    of_fuel_burn_limit                                          INTEGER,
    of_subsidies                                                INTEGER,
    of_prm                                                      INTEGER,
    of_capacity_transfers                                       INTEGER,
    of_deliverability                                           INTEGER,
    of_elcc_surface                                             INTEGER,
    of_local_capacity                                           INTEGER,
    of_markets                                                  INTEGER,
    of_water                                                    INTEGER,
    of_tuning                                                   INTEGER,
    of_policy                                                   INTEGER,
    temporal_scenario_id                                        INTEGER,
    load_zone_scenario_id                                       INTEGER,
    load_balance_scenario_id                                    INTEGER,
    lf_reserves_up_ba_scenario_id                               INTEGER,
    lf_reserves_down_ba_scenario_id                             INTEGER,
    regulation_up_ba_scenario_id                                INTEGER,
    regulation_down_ba_scenario_id                              INTEGER,
    frequency_response_ba_scenario_id                           INTEGER,
    spinning_reserves_ba_scenario_id                            INTEGER,
    inertia_reserves_ba_scenario_id                             INTEGER,
    energy_target_zone_scenario_id                              INTEGER,
    instantaneous_penetration_zone_scenario_id                  INTEGER,
    transmission_target_zone_scenario_id                        INTEGER,
    carbon_cap_zone_scenario_id                                 INTEGER,
    carbon_tax_zone_scenario_id                                 INTEGER,
    performance_standard_zone_scenario_id                       INTEGER,
    carbon_credits_zone_scenario_id                             INTEGER,
    carbon_cap_zones_carbon_credits_zones_scenario_id           INTEGER,
    performance_standard_zones_carbon_credits_zones_scenario_id INTEGER,
    carbon_tax_zones_carbon_credits_zones_scenario_id           INTEGER,
    carbon_credits_params_scenario_id                           INTEGER,
    fuel_burn_limit_ba_scenario_id                              INTEGER,
    policy_zone_scenario_id                                     INTEGER,
    prm_zone_scenario_id                                        INTEGER,
    local_capacity_zone_scenario_id                             INTEGER,
    market_scenario_id                                          INTEGER,
    water_system_params_scenario_id                             INTEGER,
    water_network_scenario_id                                   INTEGER,
    project_portfolio_scenario_id                               INTEGER,
    project_operational_chars_scenario_id                       INTEGER,
    project_availability_scenario_id                            INTEGER,
    fuel_scenario_id                                            INTEGER,
    project_load_zone_scenario_id                               INTEGER,
    project_lf_reserves_up_ba_scenario_id                       INTEGER,
    project_lf_reserves_down_ba_scenario_id                     INTEGER,
    project_regulation_up_ba_scenario_id                        INTEGER,
    project_regulation_down_ba_scenario_id                      INTEGER,
    project_frequency_response_ba_scenario_id                   INTEGER,
    project_spinning_reserves_ba_scenario_id                    INTEGER,
    project_inertia_reserves_ba_scenario_id                     INTEGER,
    project_energy_target_zone_scenario_id                      INTEGER,
    project_instantaneous_penetration_zone_scenario_id          INTEGER,
    tx_line_transmission_target_zone_scenario_id                INTEGER,
    project_carbon_cap_zone_scenario_id                         INTEGER,
    project_carbon_tax_zone_scenario_id                         INTEGER,
    project_carbon_tax_allowance_scenario_id                    INTEGER,
    project_performance_standard_zone_scenario_id               INTEGER,
    project_carbon_credits_generation_zone_scenario_id          INTEGER,
    project_carbon_credits_purchase_zone_scenario_id            INTEGER,
    project_carbon_credits_purchase_limits_scenario_id          INTEGER,
    project_carbon_credits_scenario_id                          INTEGER,
    project_fuel_burn_limit_ba_scenario_id                      INTEGER,
    fuel_fuel_burn_limit_ba_scenario_id                         INTEGER,
    project_policy_zone_scenario_id                             INTEGER,
    transmission_policy_zone_scenario_id                        INTEGER,
    project_prm_zone_scenario_id                                INTEGER,
    prm_capacity_transfer_scenario_id                           INTEGER,
    prm_capacity_transfer_params_scenario_id                    INTEGER,
    transmission_prm_zone_scenario_id                           INTEGER,
    project_elcc_chars_scenario_id                              INTEGER,
    prm_deliverability_cost_scenario_id                         INTEGER,
    prm_deliverability_existing_scenario_id                     INTEGER,
    prm_deliverability_potential_scenario_id                    INTEGER,
    project_prm_deliverability_multipliers_scenario_id          INTEGER,
    project_local_capacity_zone_scenario_id                     INTEGER,
    project_local_capacity_chars_scenario_id                    INTEGER,
    load_zone_market_scenario_id                                INTEGER,
    project_specified_capacity_scenario_id                      INTEGER,
    project_specified_fixed_cost_scenario_id                    INTEGER,
    fuel_price_scenario_id                                      INTEGER,
    project_new_cost_scenario_id                                INTEGER,
    project_new_potential_scenario_id                           INTEGER,
    project_new_binary_build_size_scenario_id                   INTEGER,
    project_capacity_group_requirement_scenario_id              INTEGER,
    project_relative_capacity_requirement_scenario_id           INTEGER,
    project_capacity_group_scenario_id                          INTEGER,
    project_power_output_group_requirement_scenario_id          INTEGER,
    project_power_output_group_scenario_id                      INTEGER,
    transmission_portfolio_scenario_id                          INTEGER,
    transmission_load_zone_scenario_id                          INTEGER,
    transmission_specified_capacity_scenario_id                 INTEGER,
    transmission_new_cost_scenario_id                           INTEGER,
    transmission_availability_scenario_id                       INTEGER,
    transmission_operational_chars_scenario_id                  INTEGER,
    transmission_hurdle_rate_scenario_id                        INTEGER,
    transmission_hurdle_rate_by_timepoint_scenario_id           INTEGER,
    transmission_new_potential_scenario_id                      INTEGER,
    transmission_flow_scenario_id                               INTEGER,
    transmission_capacity_group_requirement_scenario_id         INTEGER,
    transmission_capacity_group_scenario_id                     INTEGER,
    transmission_carbon_cap_zone_scenario_id                    INTEGER,
    transmission_simultaneous_flow_limit_scenario_id            INTEGER,
    transmission_simultaneous_flow_limit_line_group_scenario_id INTEGER,
    load_scenario_id                                            INTEGER,
    lf_reserves_up_scenario_id                                  INTEGER,
    lf_reserves_down_scenario_id                                INTEGER,
    regulation_up_scenario_id                                   INTEGER,
    regulation_down_scenario_id                                 INTEGER,
    frequency_response_scenario_id                              INTEGER,
    spinning_reserves_scenario_id                               INTEGER,
    inertia_reserves_scenario_id                                INTEGER,
    period_energy_target_scenario_id                            INTEGER,
    horizon_energy_target_scenario_id                           INTEGER,
    instantaneous_penetration_scenario_id                       INTEGER,
    transmission_target_scenario_id                             INTEGER,
    carbon_cap_target_scenario_id                               INTEGER,
    carbon_tax_scenario_id                                      INTEGER,
    performance_standard_scenario_id                            INTEGER,
    fuel_burn_limit_scenario_id                                 INTEGER,
    subsidy_scenario_id                                         INTEGER,
    policy_requirement_scenario_id                              INTEGER,
    prm_requirement_scenario_id                                 INTEGER,
    local_capacity_requirement_scenario_id                      INTEGER,
    elcc_surface_scenario_id                                    INTEGER,
    market_price_scenario_id                                    INTEGER,
    market_volume_scenario_id                                   INTEGER,
    market_volume_total_in_tmp_scenario_id                      INTEGER,
    market_volume_total_in_prd_scenario_id                      INTEGER,
    water_node_reservoir_scenario_id                            INTEGER,
    water_flow_scenario_id                                      INTEGER,
    water_inflow_scenario_id                                    INTEGER,
    water_powerhouse_scenario_id                                INTEGER,
    tuning_scenario_id                                          INTEGER,
    solver_options_id                                           INTEGER,
    FOREIGN KEY (validation_status_id) REFERENCES
        mod_validation_status_types (validation_status_id),
    FOREIGN KEY (run_status_id) REFERENCES mod_run_status_types (run_status_id),
    FOREIGN KEY (temporal_scenario_id) REFERENCES
        subscenarios_temporal (temporal_scenario_id),
    FOREIGN KEY (load_zone_scenario_id) REFERENCES
        subscenarios_geography_load_zones (load_zone_scenario_id),
    FOREIGN KEY (load_balance_scenario_id) REFERENCES
        subscenarios_geography_load_balance (load_balance_scenario_id),
    FOREIGN KEY (lf_reserves_up_ba_scenario_id) REFERENCES
        subscenarios_geography_lf_reserves_up_bas (lf_reserves_up_ba_scenario_id),
    FOREIGN KEY (lf_reserves_down_ba_scenario_id) REFERENCES
        subscenarios_geography_lf_reserves_down_bas (lf_reserves_down_ba_scenario_id),
    FOREIGN KEY (regulation_up_ba_scenario_id) REFERENCES
        subscenarios_geography_regulation_up_bas (regulation_up_ba_scenario_id),
    FOREIGN KEY (regulation_down_ba_scenario_id) REFERENCES
        subscenarios_geography_regulation_down_bas (regulation_down_ba_scenario_id),
    FOREIGN KEY (frequency_response_ba_scenario_id) REFERENCES
        subscenarios_geography_frequency_response_bas
            (frequency_response_ba_scenario_id),
    FOREIGN KEY (spinning_reserves_ba_scenario_id) REFERENCES
        subscenarios_geography_spinning_reserves_bas (spinning_reserves_ba_scenario_id),
    FOREIGN KEY (inertia_reserves_ba_scenario_id) REFERENCES
        subscenarios_geography_inertia_reserves_bas (inertia_reserves_ba_scenario_id),
    FOREIGN KEY (energy_target_zone_scenario_id) REFERENCES
        subscenarios_geography_energy_target_zones (energy_target_zone_scenario_id),
    FOREIGN KEY (instantaneous_penetration_zone_scenario_id) REFERENCES
        subscenarios_geography_instantaneous_penetration_zones (instantaneous_penetration_zone_scenario_id),
    FOREIGN KEY (transmission_target_zone_scenario_id) REFERENCES
        subscenarios_geography_transmission_target_zones (transmission_target_zone_scenario_id),
    FOREIGN KEY (carbon_cap_zone_scenario_id) REFERENCES
        subscenarios_geography_carbon_cap_zones (carbon_cap_zone_scenario_id),
    FOREIGN KEY (carbon_tax_zone_scenario_id) REFERENCES
        subscenarios_geography_carbon_tax_zones (carbon_tax_zone_scenario_id),
    FOREIGN KEY (performance_standard_zone_scenario_id) REFERENCES
        subscenarios_geography_performance_standard_zones (performance_standard_zone_scenario_id),
    FOREIGN KEY (carbon_credits_zone_scenario_id) REFERENCES
        subscenarios_geography_carbon_credits_zones (carbon_credits_zone_scenario_id),
    FOREIGN KEY (carbon_cap_zones_carbon_credits_zones_scenario_id) REFERENCES
        subscenarios_system_carbon_cap_zones_carbon_credits_zones
            (carbon_cap_zones_carbon_credits_zones_scenario_id),
    FOREIGN KEY (performance_standard_zones_carbon_credits_zones_scenario_id) REFERENCES
        subscenarios_system_performance_standard_zones_carbon_credits_zones
            (performance_standard_zones_carbon_credits_zones_scenario_id),
    FOREIGN KEY (carbon_tax_zones_carbon_credits_zones_scenario_id) REFERENCES
        subscenarios_system_carbon_tax_zones_carbon_credits_zones
            (carbon_tax_zones_carbon_credits_zones_scenario_id),
    FOREIGN KEY (carbon_credits_params_scenario_id) REFERENCES
        subscenarios_system_carbon_credits_params
            (carbon_credits_params_scenario_id),
    FOREIGN KEY (fuel_burn_limit_ba_scenario_id) REFERENCES
        subscenarios_geography_fuel_burn_limit_balancing_areas
            (fuel_burn_limit_ba_scenario_id),
    FOREIGN KEY (policy_zone_scenario_id) REFERENCES
        subscenarios_geography_policy_zones (policy_zone_scenario_id),
    FOREIGN KEY (prm_zone_scenario_id) REFERENCES
        subscenarios_geography_prm_zones (prm_zone_scenario_id),
    FOREIGN KEY (local_capacity_zone_scenario_id) REFERENCES
        subscenarios_geography_local_capacity_zones (local_capacity_zone_scenario_id),
    FOREIGN KEY (market_scenario_id) REFERENCES
        subscenarios_geography_markets (market_scenario_id),
    FOREIGN KEY (water_system_params_scenario_id) REFERENCES
        subscenarios_system_water_system_params (water_system_params_scenario_id),
    FOREIGN KEY (water_network_scenario_id) REFERENCES
        subscenarios_geography_water_network (water_network_scenario_id),
    FOREIGN KEY (project_portfolio_scenario_id) REFERENCES
        subscenarios_project_portfolios (project_portfolio_scenario_id),
    FOREIGN KEY (project_operational_chars_scenario_id) REFERENCES
        subscenarios_project_operational_chars (project_operational_chars_scenario_id),
    FOREIGN KEY (project_availability_scenario_id) REFERENCES
        subscenarios_project_availability (project_availability_scenario_id),
    FOREIGN KEY (fuel_scenario_id) REFERENCES
        subscenarios_fuels (fuel_scenario_id),
    FOREIGN KEY (fuel_price_scenario_id) REFERENCES
        subscenarios_fuel_prices (fuel_price_scenario_id),
    FOREIGN KEY (project_load_zone_scenario_id) REFERENCES
        subscenarios_project_load_zones (project_load_zone_scenario_id),
    FOREIGN KEY (project_lf_reserves_up_ba_scenario_id) REFERENCES
        subscenarios_project_lf_reserves_up_bas
            (project_lf_reserves_up_ba_scenario_id),
    FOREIGN KEY (project_lf_reserves_down_ba_scenario_id) REFERENCES
        subscenarios_project_lf_reserves_down_bas
            (project_lf_reserves_down_ba_scenario_id),
    FOREIGN KEY (project_regulation_up_ba_scenario_id) REFERENCES
        subscenarios_project_regulation_up_bas
            (project_regulation_up_ba_scenario_id),
    FOREIGN KEY (project_regulation_down_ba_scenario_id) REFERENCES
        subscenarios_project_regulation_down_bas
            (project_regulation_down_ba_scenario_id),
    FOREIGN KEY (project_frequency_response_ba_scenario_id) REFERENCES
        subscenarios_project_frequency_response_bas
            (project_frequency_response_ba_scenario_id),
    FOREIGN KEY (project_spinning_reserves_ba_scenario_id) REFERENCES
        subscenarios_project_spinning_reserves_bas
            (project_spinning_reserves_ba_scenario_id),
    FOREIGN KEY (project_inertia_reserves_ba_scenario_id) REFERENCES
        subscenarios_project_inertia_reserves_bas
            (project_inertia_reserves_ba_scenario_id),
    FOREIGN KEY (project_energy_target_zone_scenario_id) REFERENCES
        subscenarios_project_energy_target_zones
            (project_energy_target_zone_scenario_id),
    FOREIGN KEY (project_instantaneous_penetration_zone_scenario_id) REFERENCES
        subscenarios_project_instantaneous_penetration_zones
            (project_instantaneous_penetration_zone_scenario_id),
    FOREIGN KEY (tx_line_transmission_target_zone_scenario_id) REFERENCES
        subscenarios_tx_line_transmission_target_zones
            (tx_line_transmission_target_zone_scenario_id),
    FOREIGN KEY (project_carbon_cap_zone_scenario_id) REFERENCES
        subscenarios_project_carbon_cap_zones
            (project_carbon_cap_zone_scenario_id),
    FOREIGN KEY (project_carbon_tax_zone_scenario_id) REFERENCES
        subscenarios_project_carbon_tax_zones
            (project_carbon_tax_zone_scenario_id),
    FOREIGN KEY (project_carbon_tax_allowance_scenario_id) REFERENCES
        subscenarios_project_carbon_tax_allowance
            (project_carbon_tax_allowance_scenario_id),
    FOREIGN KEY (project_performance_standard_zone_scenario_id) REFERENCES
        subscenarios_project_performance_standard_zones
            (project_performance_standard_zone_scenario_id),
    FOREIGN KEY (project_carbon_credits_generation_zone_scenario_id) REFERENCES
        subscenarios_project_carbon_credits_generation_zones
            (project_carbon_credits_generation_zone_scenario_id),
    FOREIGN KEY (project_carbon_credits_purchase_zone_scenario_id) REFERENCES
        subscenarios_project_carbon_credits_purchase_zones
            (project_carbon_credits_purchase_zone_scenario_id),
    FOREIGN KEY (project_carbon_credits_purchase_limits_scenario_id) REFERENCES
        subscenarios_project_carbon_credits_purchase_limits
            (project_carbon_credits_purchase_limits_scenario_id),
    FOREIGN KEY (project_carbon_credits_scenario_id) REFERENCES
        subscenarios_project_carbon_credits
            (project_carbon_credits_scenario_id),
    FOREIGN KEY (project_fuel_burn_limit_ba_scenario_id) REFERENCES
        subscenarios_project_fuel_burn_limit_balancing_areas
            (project_fuel_burn_limit_ba_scenario_id),
    FOREIGN KEY (fuel_fuel_burn_limit_ba_scenario_id) REFERENCES
        subscenarios_fuel_fuel_burn_limit_balancing_areas
            (fuel_fuel_burn_limit_ba_scenario_id),
    FOREIGN KEY (project_policy_zone_scenario_id) REFERENCES
        subscenarios_project_policy_zones (project_policy_zone_scenario_id),
    FOREIGN KEY (transmission_policy_zone_scenario_id) REFERENCES
        subscenarios_transmission_policy_zones
            (transmission_policy_zone_scenario_id),
    FOREIGN KEY (project_prm_zone_scenario_id) REFERENCES
        subscenarios_project_prm_zones (project_prm_zone_scenario_id),
    FOREIGN KEY (transmission_prm_zone_scenario_id) REFERENCES
        subscenarios_transmission_prm_zones (transmission_prm_zone_scenario_id),
    FOREIGN KEY (project_elcc_chars_scenario_id) REFERENCES
        subscenarios_project_elcc_chars (project_elcc_chars_scenario_id),
    FOREIGN KEY (prm_deliverability_cost_scenario_id) REFERENCES
        subscenarios_project_prm_deliverability_costs (prm_deliverability_cost_scenario_id),
    FOREIGN KEY (prm_deliverability_existing_scenario_id) REFERENCES
        subscenarios_project_prm_deliverability_existing
            (prm_deliverability_existing_scenario_id),
    FOREIGN KEY (prm_deliverability_potential_scenario_id) REFERENCES
        subscenarios_project_prm_deliverability_potential
            (prm_deliverability_potential_scenario_id),
    FOREIGN KEY (project_prm_deliverability_multipliers_scenario_id) REFERENCES
        subscenarios_project_prm_deliverability_multipliers
            (project_prm_deliverability_multipliers_scenario_id),
    FOREIGN KEY (project_local_capacity_zone_scenario_id) REFERENCES
        subscenarios_project_local_capacity_zones
            (project_local_capacity_zone_scenario_id),
    FOREIGN KEY (project_local_capacity_chars_scenario_id) REFERENCES
        subscenarios_project_local_capacity_chars
            (project_local_capacity_chars_scenario_id),
    FOREIGN KEY (load_zone_market_scenario_id) REFERENCES
        subscenarios_load_zone_markets (load_zone_market_scenario_id),
    FOREIGN KEY (project_specified_capacity_scenario_id) REFERENCES
        subscenarios_project_specified_capacity
            (project_specified_capacity_scenario_id),
    FOREIGN KEY (project_specified_fixed_cost_scenario_id) REFERENCES
        subscenarios_project_specified_fixed_cost
            (project_specified_fixed_cost_scenario_id),
    FOREIGN KEY (project_new_cost_scenario_id) REFERENCES
        subscenarios_project_new_cost (project_new_cost_scenario_id),
    FOREIGN KEY (project_new_potential_scenario_id) REFERENCES
        subscenarios_project_new_potential (project_new_potential_scenario_id),
    FOREIGN KEY (project_new_binary_build_size_scenario_id) REFERENCES
        subscenarios_project_new_binary_build_size
            (project_new_binary_build_size_scenario_id),
    FOREIGN KEY (project_capacity_group_scenario_id) REFERENCES
        subscenarios_project_capacity_groups
            (project_capacity_group_scenario_id),
    FOREIGN KEY (project_capacity_group_requirement_scenario_id) REFERENCES
        subscenarios_project_capacity_group_requirements
            (project_capacity_group_requirement_scenario_id),
    FOREIGN KEY (project_relative_capacity_requirement_scenario_id) REFERENCES
        subscenarios_project_relative_capacity_requirements
            (project_relative_capacity_requirement_scenario_id),
    FOREIGN KEY (project_power_output_group_requirement_scenario_id) REFERENCES
        subscenarios_project_power_output_group_requirements
            (project_power_output_group_requirement_scenario_id),
    FOREIGN KEY (project_power_output_group_scenario_id) REFERENCES
        subscenarios_project_power_output_groups
            (project_power_output_group_scenario_id),
    FOREIGN KEY (transmission_portfolio_scenario_id) REFERENCES
        subscenarios_transmission_portfolios (transmission_portfolio_scenario_id),
    FOREIGN KEY (transmission_load_zone_scenario_id)
        REFERENCES subscenarios_transmission_load_zones
            (transmission_load_zone_scenario_id),
    FOREIGN KEY (transmission_specified_capacity_scenario_id) REFERENCES
        subscenarios_transmission_specified_capacity
            (transmission_specified_capacity_scenario_id),
    FOREIGN KEY (transmission_new_cost_scenario_id) REFERENCES
        subscenarios_transmission_new_cost
            (transmission_new_cost_scenario_id),
    FOREIGN KEY (transmission_availability_scenario_id) REFERENCES
        subscenarios_transmission_availability
            (transmission_availability_scenario_id),
    FOREIGN KEY (transmission_operational_chars_scenario_id) REFERENCES
        subscenarios_transmission_operational_chars
            (transmission_operational_chars_scenario_id),
    FOREIGN KEY (transmission_hurdle_rate_scenario_id) REFERENCES
        subscenarios_transmission_hurdle_rates
            (transmission_hurdle_rate_scenario_id),
    FOREIGN KEY (transmission_hurdle_rate_by_timepoint_scenario_id) REFERENCES
        subscenarios_transmission_hurdle_rates_by_timepoint
            (transmission_hurdle_rate_by_timepoint_scenario_id),
    FOREIGN KEY (transmission_new_potential_scenario_id) REFERENCES
        subscenarios_transmission_new_potential (transmission_new_potential_scenario_id),
    FOREIGN KEY (transmission_flow_scenario_id) REFERENCES
        subscenarios_transmission_flow (transmission_flow_scenario_id),
    FOREIGN KEY (transmission_capacity_group_scenario_id) REFERENCES
        subscenarios_transmission_capacity_groups
            (transmission_capacity_group_scenario_id),
    FOREIGN KEY (transmission_capacity_group_requirement_scenario_id) REFERENCES
        subscenarios_transmission_capacity_group_requirements
            (transmission_capacity_group_requirement_scenario_id),
    FOREIGN KEY (transmission_carbon_cap_zone_scenario_id)
        REFERENCES subscenarios_transmission_carbon_cap_zones
            (transmission_carbon_cap_zone_scenario_id),
    FOREIGN KEY (transmission_simultaneous_flow_limit_scenario_id)
        REFERENCES subscenarios_transmission_simultaneous_flow_limits
            (transmission_simultaneous_flow_limit_scenario_id),
    FOREIGN KEY (transmission_simultaneous_flow_limit_line_group_scenario_id)
        REFERENCES subscenarios_transmission_simultaneous_flow_limit_line_groups
            (transmission_simultaneous_flow_limit_line_group_scenario_id),
    FOREIGN KEY (load_scenario_id) REFERENCES
        subscenarios_system_load (load_scenario_id),
    FOREIGN KEY (lf_reserves_up_scenario_id) REFERENCES
        subscenarios_system_lf_reserves_up (lf_reserves_up_scenario_id),
    FOREIGN KEY (lf_reserves_down_scenario_id) REFERENCES
        subscenarios_system_lf_reserves_down (lf_reserves_down_scenario_id),
    FOREIGN KEY (regulation_up_scenario_id) REFERENCES
        subscenarios_system_regulation_up (regulation_up_scenario_id),
    FOREIGN KEY (regulation_down_scenario_id) REFERENCES
        subscenarios_system_regulation_down (regulation_down_scenario_id),
    FOREIGN KEY (spinning_reserves_scenario_id) REFERENCES
        subscenarios_system_spinning_reserves (spinning_reserves_scenario_id),
    FOREIGN KEY (inertia_reserves_scenario_id) REFERENCES
        subscenarios_system_inertia_reserves (inertia_reserves_scenario_id),
    FOREIGN KEY (frequency_response_scenario_id) REFERENCES
        subscenarios_system_frequency_response (frequency_response_scenario_id),
    FOREIGN KEY (period_energy_target_scenario_id) REFERENCES
        subscenarios_system_period_energy_targets
            (period_energy_target_scenario_id),
    FOREIGN KEY (horizon_energy_target_scenario_id) REFERENCES
        subscenarios_system_horizon_energy_targets
            (horizon_energy_target_scenario_id),
    FOREIGN KEY (policy_requirement_scenario_id) REFERENCES
        subscenarios_system_policy_requirements
            (policy_requirement_scenario_id),
    FOREIGN KEY (transmission_target_scenario_id) REFERENCES
        subscenarios_system_transmission_targets
            (transmission_target_scenario_id),
    FOREIGN KEY (instantaneous_penetration_scenario_id) REFERENCES
        subscenarios_system_instantaneous_penetration
            (instantaneous_penetration_scenario_id),
    FOREIGN KEY (carbon_cap_target_scenario_id) REFERENCES
        subscenarios_system_carbon_cap_targets (carbon_cap_target_scenario_id),
    FOREIGN KEY (carbon_tax_scenario_id) REFERENCES
        subscenarios_system_carbon_tax (carbon_tax_scenario_id),
    FOREIGN KEY (performance_standard_scenario_id) REFERENCES
        subscenarios_system_performance_standard (performance_standard_scenario_id),
    FOREIGN KEY (fuel_burn_limit_scenario_id) REFERENCES
        subscenarios_system_fuel_burn_limits (fuel_burn_limit_scenario_id),
    FOREIGN KEY (prm_requirement_scenario_id) REFERENCES
        subscenarios_system_prm_requirement (prm_requirement_scenario_id),
    FOREIGN KEY (prm_capacity_transfer_scenario_id) REFERENCES
        subscenarios_transmission_prm_capacity_transfers (prm_capacity_transfer_scenario_id),
    FOREIGN KEY (prm_capacity_transfer_params_scenario_id) REFERENCES
        subscenarios_transmission_prm_capacity_transfer_params
            (prm_capacity_transfer_params_scenario_id),
    FOREIGN KEY (elcc_surface_scenario_id) REFERENCES
        subscenarios_system_prm_zone_elcc_surface (elcc_surface_scenario_id),
    FOREIGN KEY (local_capacity_requirement_scenario_id) REFERENCES
        subscenarios_system_local_capacity_requirement
            (local_capacity_requirement_scenario_id),
    FOREIGN KEY (market_price_scenario_id) REFERENCES
        subscenarios_market_prices (market_price_scenario_id),
    FOREIGN KEY (market_volume_scenario_id) REFERENCES
        subscenarios_market_volume (market_volume_scenario_id),
    FOREIGN KEY (market_volume_total_in_tmp_scenario_id) REFERENCES
        subscenarios_market_volume_totals_in_tmp
            (market_volume_total_in_tmp_scenario_id),
    FOREIGN KEY (market_volume_total_in_prd_scenario_id) REFERENCES
        subscenarios_market_volume_totals_in_prd
            (market_volume_total_in_prd_scenario_id),
    FOREIGN KEY (water_node_reservoir_scenario_id) REFERENCES
        subscenarios_system_water_node_reservoirs (water_node_reservoir_scenario_id),
    FOREIGN KEY (water_flow_scenario_id) REFERENCES
        subscenarios_system_water_flows (water_flow_scenario_id),
    FOREIGN KEY (water_inflow_scenario_id) REFERENCES
        subscenarios_system_water_inflows (water_inflow_scenario_id),
    FOREIGN KEY (water_powerhouse_scenario_id) REFERENCES
        subscenarios_system_water_powerhouses (water_powerhouse_scenario_id),
    FOREIGN KEY (tuning_scenario_id) REFERENCES
        subscenarios_tuning (tuning_scenario_id),
    FOREIGN KEY (solver_options_id)
        REFERENCES subscenarios_options_solver (solver_options_id)
);

--------------------------
-- -- DATA INTEGRITY -- --
--------------------------

-- Allowed combinations of subscenario IDs -- some should not be used together

-- Project portfolio scenario, reserves scenario

-- Load scenario, energy target scenario, PV BTM scenario

-- Project op char scenario, load_zone scenario, reserves BA scenario, energy target
-- zone scenario, carbon cap scenario

-- Sim Tx flow limits, sim Tx flow limit groups, Tx lines

-- Project operational chars ID and fuel ID


-------------------
-- -- RESULTS -- --
-------------------

-- TODO: project can belong to more than one energy target zone, so this
--  doesn't make sense this way; need to rethink these columns
DROP TABLE IF EXISTS results_project_period;
CREATE TABLE results_project_period
(
    scenario_id                            INTEGER,
    project                                VARCHAR(64),
    period                                 INTEGER,
    weather_iteration                      INTEGER,
    hydro_iteration                        INTEGER,
    availability_iteration                 INTEGER,
    subproblem_id                          INTEGER,
    stage_id                               INTEGER,
    capacity_type                          VARCHAR(64),
    availability_type                      VARCHAR(64),
    operational_type                       VARCHAR(64),
    technology                             VARCHAR(32),
    load_modifier_flag                     INTEGER,
    distribution_loss_adjustment_factor    FLOAT,
    load_zone                              VARCHAR(32),
    energy_target_zone                     VARCHAR(32),
    instantaneous_penetration_zone         VARCHAR(32),
    carbon_cap_zone                        VARCHAR(32),
    capacity_mw                            FLOAT,
    energy_mwh                             FLOAT,
    hyb_gen_capacity_mw                    FLOAT,
    hyb_stor_capacity_mw                   FLOAT,
    stor_energy_capacity_mwh               FLOAT,
    fuel_prod_capacity_fuelunitperhour     FLOAT,
    fuel_rel_capacity_fuelunitperhour      FLOAT,
    fuel_stor_capacity_fuelunit            FLOAT,
    new_build_mw                           FLOAT,
    new_build_stor_mwh                     FLOAT,
    new_build_energy_mwh                   FLOAT,
    new_build_binary                       INTEGER,
    retired_mw                             FLOAT,
    retired_binary                         INTEGER,
    new_fuel_prod_capacity_fuelunitperhour FLOAT,
    new_fuel_rel_capacity_fuelunitperhour  FLOAT,
    new_fuel_stor_capacity_fuelunit        FLOAT,
    hours_in_period_timepoints             FLOAT,
    hours_in_subproblem_period             FLOAT,
    capacity_cost                          FLOAT,
    capacity_cost_wo_spinup_or_lookahead   FLOAT,
    fixed_cost                             FLOAT,
    min_build_power_dual                   FLOAT,
    max_build_power_dual                   FLOAT,
    min_total_power_dual                   FLOAT,
    max_total_power_dual                   FLOAT,
    min_build_stor_energy_dual             FLOAT,
    max_build_stor_energy_dual             FLOAT,
    min_total_stor_energy_dual             FLOAT,
    max_total_stor_energy_dual             FLOAT,
    min_build_energy_dual                  FLOAT,
    max_build_energy_dual                  FLOAT,
    min_total_energy_dual                  FLOAT,
    max_total_energy_dual                  FLOAT,
    carbon_credits_zone                    VARCHAR(32),
    carbon_credits_generated_tCO2          FLOAT,
    carbon_credits_purchased_tCO2          FLOAT,
    PRIMARY KEY (scenario_id, project, weather_iteration, hydro_iteration,
                 availability_iteration, period, subproblem_id, stage_id)
);

DROP TABLE IF EXISTS results_project_group_capacity;
CREATE TABLE results_project_group_capacity
(
    scenario_id                            INTEGER,
    weather_iteration                      INTEGER,
    hydro_iteration                        INTEGER,
    availability_iteration                 INTEGER,
    subproblem_id                          INTEGER,
    stage_id                               INTEGER,
    capacity_group                         VARCHAR(64),
    period                                 INTEGER,
    group_new_capacity                     FLOAT,
    group_total_capacity                   FLOAT,
    capacity_group_new_capacity_min        FLOAT,
    capacity_group_new_capacity_max        FLOAT,
    capacity_group_total_capacity_min      FLOAT,
    capacity_group_total_capacity_max      FLOAT,
    capacity_group_new_max_dual            FLOAT,
    capacity_group_new_min_dual            FLOAT,
    capacity_group_total_max_dual          FLOAT,
    capacity_group_total_min_dual          FLOAT,
    capacity_group_new_max_marginal_cost   FLOAT,
    capacity_group_new_min_marginal_cost   FLOAT,
    capacity_group_total_max_marginal_cost FLOAT,
    capacity_group_total_min_marginal_cost FLOAT,
    group_new_energy                       FLOAT,
    group_total_energy                     FLOAT,
    energy_group_new_energy_min            FLOAT,
    energy_group_new_energy_max            FLOAT,
    energy_group_total_energy_min          FLOAT,
    energy_group_total_energy_max          FLOAT,
    energy_group_new_max_dual              FLOAT,
    energy_group_new_min_dual              FLOAT,
    energy_group_total_max_dual            FLOAT,
    energy_group_total_min_dual            FLOAT,
    energy_group_new_max_marginal_cost     FLOAT,
    energy_group_new_min_marginal_cost     FLOAT,
    energy_group_total_max_marginal_cost   FLOAT,
    energy_group_total_min_marginal_cost   FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id,
                 capacity_group, period)
);


DROP TABLE IF EXISTS results_project_timepoint;
CREATE TABLE results_project_timepoint
(
    scenario_id                                     INTEGER,
    project                                         VARCHAR(64),
    weather_iteration                               INTEGER,
    hydro_iteration                                 INTEGER,
    availability_iteration                          INTEGER,
    timepoint                                       INTEGER,
    period                                          INTEGER,
    subproblem_id                                   INTEGER,
    stage_id                                        INTEGER,
    capacity_type                                   VARCHAR(64),
    availability_type                               VARCHAR(64),
    operational_type                                VARCHAR(64),
    balancing_type                                  VARCHAR(64),
    horizon                                         INTEGER,
    timepoint_weight                                FLOAT,
    number_of_hours_in_timepoint                    FLOAT,
    spinup_or_lookahead                             INTEGER,
    load_zone                                       VARCHAR(32),
    carbon_cap_zone                                 VARCHAR(32),
    technology                                      VARCHAR(32),
    load_modifier_flag                              INTEGER,
    distribution_loss_adjustment_factor             FLOAT,
    capacity_mw                                     FLOAT,
    project_power_mw                                FLOAT, -- project-level
    power_mw                                        FLOAT, -- bulk-system-level
    scheduled_curtailment_mw                        FLOAT,
    subhourly_curtailment_mw                        FLOAT,
    subhourly_energy_delivered_mw                   FLOAT,
    total_curtailment_mw                            FLOAT,
    committed_mw                                    FLOAT,
    committed_units                                 FLOAT,
    started_units                                   FLOAT,
    stopped_units                                   FLOAT,
    synced_units                                    FLOAT,
    active_startup_type                             FLOAT,
    auxiliary_consumption_mw                        FLOAT,
    gross_power_mw                                  FLOAT,
    net_power_mw                                    FLOAT,
    ramp_up_violation                               FLOAT,
    ramp_up_dual                                    FLOAT,
    ramp_down_violation                             FLOAT,
    ramp_down_dual                                  FLOAT,
    min_up_time_violation                           FLOAT,
    min_up_time_dual                                FLOAT,
    min_down_time_violation                         FLOAT,
    min_down_time_dual                              FLOAT,
    starting_energy_mwh                             FLOAT,
    charge_mw                                       FLOAT,
    discharge_mw                                    FLOAT,
    static_load_mw                                  FLOAT,
    flex_load_mw                                    FLOAT,
    hyb_storage_charge_mw                           FLOAT,
    hyb_storage_discharge_mw                        FLOAT,
    fuel_in_storage_fuelunit                        FLOAT,
    produce_fuel_fuelunitperhour                    FLOAT,
    release_fuel_fuelunitperhour                    FLOAT,
    fuel_prod_power_consumption_powerunit           FLOAT,
    variable_om_cost                                FLOAT,
    fuel_cost                                       FLOAT,
    startup_cost                                    FLOAT,
    shutdown_cost                                   FLOAT,
    operational_violation_cost                      FLOAT,
    curtailment_cost                                FLOAT,
    soc_penalty_cost                                FLOAT,
    soc_last_tmp_penalty_cost                       FLOAT,
    carbon_emissions_tons                           FLOAT,
    energy_target_zone                              VARCHAR(32),
    scheduled_energy_target_energy_mw               FLOAT,
    subhourly_energy_target_energy_delivered_mw     FLOAT,
    instantaneous_penetration_zone                  VARCHAR(32),
    instantaneous_penetration_power_mw              FLOAT,
    spinning_reserves_ba                            VARCHAR(32),
    spinning_reserves_reserve_provision_mw          FLOAT,
    lf_reserves_down_ba                             VARCHAR(32),
    lf_reserves_down_reserve_provision_mw           FLOAT,
    lf_reserves_up_ba                               VARCHAR(32),
    lf_reserves_up_reserve_provision_mw             FLOAT,
    regulation_down_ba                              VARCHAR(32),
    regulation_down_reserve_provision_mw            FLOAT,
    regulation_up_ba                                VARCHAR(32),
    regulation_up_reserve_provision_mw              FLOAT,
    frequency_response_ba                           VARCHAR(32),
    frequency_response_reserve_provision_mw         FLOAT,
    frequency_response_partial_reserve_provision_mw FLOAT,
    inertia_reserves_ba                             VARCHAR(32),
    inertia_reserves_reserve_provision_mws          FLOAT,
    availability_derate                             FLOAT,
    unavailability_decision                         FLOAT,
    start_unavailability                            FLOAT,
    stop_unavailability                             FLOAT,
    PRIMARY KEY (scenario_id, project, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, timepoint)
);


DROP TABLE IF EXISTS results_project_policy_zone_timepoint;
CREATE TABLE results_project_policy_zone_timepoint
(
    scenario_id            INTEGER,
    project                VARCHAR(64),
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    policy_name            TEXT,
    policy_zone            TEXT,
    timepoint              INTEGER,
    timepoint_weight       FLOAT,
    hours_in_timepoint     FLOAT,
    period                 INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    policy_contribution    FLOAT,
    PRIMARY KEY (scenario_id, project, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id,
                 policy_name, policy_zone, timepoint)
);

DROP TABLE IF EXISTS results_transmission_policy_zone_timepoint;
CREATE TABLE results_transmission_policy_zone_timepoint
(
    scenario_id            INTEGER,
    transmission_line      VARCHAR(64),
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    policy_name            TEXT,
    policy_zone            TEXT,
    timepoint              INTEGER,
    timepoint_weight       FLOAT,
    hours_in_timepoint     FLOAT,
    period                 INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    policy_contribution    FLOAT,
    PRIMARY KEY (scenario_id, transmission_line, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, policy_name, policy_zone, timepoint)
);

DROP TABLE IF EXISTS results_project_curtailment_variable_periodagg;
CREATE TABLE results_project_curtailment_variable_periodagg
(
    scenario_id                  INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    period                       INTEGER,
    timepoint                    INTEGER,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    month                        INTEGER,
    hour_of_day                  FLOAT,
    load_zone                    VARCHAR(32),
    scheduled_curtailment_mw     FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, timepoint,
                 load_zone)
);

DROP TABLE IF EXISTS results_project_curtailment_hydro_periodagg;
CREATE TABLE results_project_curtailment_hydro_periodagg
(
    scenario_id                  INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    period                       INTEGER,
    timepoint                    INTEGER,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    month                        INTEGER,
    hour_of_day                  FLOAT,
    load_zone                    VARCHAR(32),
    scheduled_curtailment_mw     FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, timepoint,
                 load_zone)
);

DROP TABLE IF EXISTS results_project_cap_factor_limits;
CREATE TABLE results_project_cap_factor_limits
(
    scenario_id            INTEGER,
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    project                VARCHAR(64),
    balancing_type_horizon VARCHAR(64),
    horizon                INTEGER,
    min_cap_factor         FLOAT,
    max_cap_factor         FLOAT,
    actual_power_provision_mwh,
    possible_power_provision_mwh,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, project,
                 balancing_type_horizon, horizon)
);

DROP TABLE IF EXISTS results_project_carbon_tax_allowance;
CREATE TABLE results_project_carbon_tax_allowance
(
    scenario_id                                          INTEGER,
    weather_iteration                                    INTEGER,
    hydro_iteration                                      INTEGER,
    availability_iteration                               INTEGER,
    subproblem_id                                        INTEGER,
    stage_id                                             INTEGER,
    project                                              VARCHAR(64),
    fuel_group                                           VARCHAR(64),
    timepoint                                            INTEGER,
    period                                               INTEGER,
    horizon                                              INTEGER,
    timepoint_weight                                     FLOAT,
    number_of_hours_in_timepoint                         FLOAT,
    carbon_tax_zone                                      VARCHAR(64),
    carbon_tax_allowance_tco2_per_mwh                    FLOAT,
    carbon_tax_allowance_average_heat_rate_mmbtu_per_mwh FLOAT,
    opr_fuel_burn_by_fuel_group_mmbtu                    FLOAT,
    carbon_tax_allowance_tons                            FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, project,
                 fuel_group, timepoint)
);

DROP TABLE IF EXISTS results_project_dispatch_by_technology;
CREATE TABLE results_project_dispatch_by_technology
(
    scenario_id                  INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    period                       INTEGER,
    timepoint                    INTEGER,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    load_zone                    VARCHAR(32),
    technology                   VARCHAR(32),
    power_mw                     FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, timepoint,
                 load_zone, technology)
);

DROP TABLE IF EXISTS results_project_dispatch_by_technology_period;
CREATE TABLE results_project_dispatch_by_technology_period
(
    scenario_id            INTEGER,
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    period                 INTEGER,
    load_zone              VARCHAR(32),
    technology             VARCHAR(32),
    spinup_or_lookahead    INTEGER,
    energy_mwh             FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, period,
                 load_zone, technology, spinup_or_lookahead)
);

DROP TABLE IF EXISTS results_project_deliverability;
CREATE TABLE results_project_deliverability
(
    scenario_id             INTEGER,
    project                 VARCHAR(64),
    period                  INTEGER,
    weather_iteration       INTEGER,
    hydro_iteration         INTEGER,
    availability_iteration  INTEGER,
    subproblem_id           INTEGER,
    stage_id                INTEGER,
    prm_zone                VARCHAR(32),
    technology              VARCHAR(32),
    load_zone               VARCHAR(32),
    energy_target_zone      VARCHAR(32),
    carbon_cap_zone         VARCHAR(32),
    capacity_mw             FLOAT,
    deliverable_capacity_mw FLOAT,
    energy_only_capacity_mw FLOAT,
    PRIMARY KEY (scenario_id, project, period, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id)
);

DROP TABLE IF EXISTS
    results_project_deliverability_groups;
CREATE TABLE results_project_deliverability_groups
(
    scenario_id                              INTEGER,
    weather_iteration                        INTEGER,
    hydro_iteration                          INTEGER,
    availability_iteration                   INTEGER,
    subproblem_id                            INTEGER,
    stage_id                                 INTEGER,
    deliverability_group                     VARCHAR(64),
    period                                   INTEGER,
    deliverable_capacity_built_in_period_mw  FLOAT,
    cumulative_added_deliverable_capacity_mw FLOAT,
    deliverability_annual_cost_in_period     FLOAT,
    PRIMARY KEY (scenario_id, deliverability_group, period,
                 weather_iteration, hydro_iteration, availability_iteration,
                 subproblem_id, stage_id)
);

-- Deliverable capacity costs - Aggregated
-- (and broken out by spinup_or_lookahead; fraction sums up to 1 between the
-- spinup_or_lookahead and the non-spinup_or_lookahead timepoints)
DROP TABLE IF EXISTS
    results_project_deliverability_groups_agg;
CREATE TABLE results_project_deliverability_groups_agg
(
    scenario_id                     INTEGER,
    weather_iteration               INTEGER,
    hydro_iteration                 INTEGER,
    availability_iteration          INTEGER,
    subproblem_id                   INTEGER,
    stage_id                        INTEGER,
    period                          INTEGER,
    spinup_or_lookahead             INTEGER,
    fraction_of_hours_in_subproblem FLOAT,
    deliverable_capacity_cost       FLOAT,
    PRIMARY KEY (scenario_id, period, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id,
                 spinup_or_lookahead)
);

DROP TABLE IF EXISTS results_project_elcc_simple;
CREATE TABLE results_project_elcc_simple
(
    scenario_id               INTEGER,
    project                   VARCHAR(64),
    period                    INTEGER,
    weather_iteration         INTEGER,
    hydro_iteration           INTEGER,
    availability_iteration    INTEGER,
    subproblem_id             INTEGER,
    stage_id                  INTEGER,
    prm_zone                  VARCHAR(32),
    technology                VARCHAR(32),
    load_zone                 VARCHAR(32),
    energy_target_zone        VARCHAR(32),
    carbon_cap_zone           VARCHAR(32),
    capacity_mw               FLOAT,
    elcc_eligible_capacity_mw FLOAT,
    energy_only_capacity_mw   FLOAT,
    elcc_simple_fraction      FLOAT,
    elcc_mw                   FLOAT,
    PRIMARY KEY (scenario_id, project, period, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id)
);

DROP TABLE IF EXISTS results_project_elcc_surface;
CREATE TABLE results_project_elcc_surface
(
    scenario_id               INTEGER,
    project                   VARCHAR(64),
    period                    INTEGER,
    weather_iteration         INTEGER,
    hydro_iteration           INTEGER,
    availability_iteration    INTEGER,
    subproblem_id             INTEGER,
    stage_id                  INTEGER,
    elcc_surface_name         VARCHAR(32),
    prm_zone                  VARCHAR(32),
    facet                     INTEGER,
    technology                VARCHAR(32),
    load_zone                 VARCHAR(32),
    energy_target_zone        VARCHAR(32),
    carbon_cap_zone           VARCHAR(32),
    capacity_mw               FLOAT,
    elcc_eligible_capacity_mw FLOAT,
    energy_only_capacity_mw   FLOAT,
    elcc_surface_coefficient  FLOAT,
    elcc_mw                   FLOAT,
    PRIMARY KEY (scenario_id, project, period, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id, facet)
);

-- Local capacity
DROP TABLE IF EXISTS results_project_local_capacity;
CREATE TABLE results_project_local_capacity
(
    scenario_id                    INTEGER,
    project                        VARCHAR(64),
    period                         INTEGER,
    weather_iteration              INTEGER,
    hydro_iteration                INTEGER,
    availability_iteration         INTEGER,
    subproblem_id                  INTEGER,
    stage_id                       INTEGER,
    local_capacity_zone            VARCHAR(32),
    technology                     VARCHAR(32),
    load_zone                      VARCHAR(32),
    energy_target_zone             VARCHAR(32),
    carbon_cap_zone                VARCHAR(32),
    capacity_mw                    FLOAT,
    local_capacity_fraction        FLOAT,
    local_capacity_contribution_mw FLOAT,
    PRIMARY KEY (scenario_id, project, period, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id)
);

-- Capacity costs - Aggregated
-- (and broken out by spinup_or_lookahead; fraction sums up to 1 between the
-- spinup_or_lookahead and the non-spinup_or_lookahead timepoints)
DROP TABLE IF EXISTS results_project_costs_capacity_agg;
CREATE TABLE results_project_costs_capacity_agg
(
    scenario_id                     INTEGER,
    load_zone                       VARCHAR(64),
    period                          INTEGER,
    weather_iteration               INTEGER,
    hydro_iteration                 INTEGER,
    availability_iteration          INTEGER,
    subproblem_id                   INTEGER,
    stage_id                        INTEGER,
    spinup_or_lookahead             INTEGER,
    fraction_of_hours_in_subproblem FLOAT,
    capacity_cost                   FLOAT,
    PRIMARY KEY (scenario_id, load_zone, period, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id, spinup_or_lookahead)
);

-- Operational Costs - Aggregated
-- By timepoint costs are in the results_project_timepoint table
DROP TABLE IF EXISTS results_project_costs_operations_agg;
CREATE TABLE results_project_costs_operations_agg
(
    scenario_id            INTEGER,
    load_zone              VARCHAR(64),
    period                 INTEGER,
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    spinup_or_lookahead    INTEGER,
    variable_om_cost       FLOAT,
    fuel_cost              FLOAT,
    startup_cost           FLOAT,
    shutdown_cost          FLOAT,
    PRIMARY KEY (scenario_id, load_zone, period, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id, spinup_or_lookahead)
);

DROP TABLE IF EXISTS results_project_fuel_burn;
CREATE TABLE results_project_fuel_burn
(
    scenario_id                  INTEGER,
    project                      VARCHAR(64),
    period                       INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    balancing_type_project       VARCHAR(64),
    horizon                      INTEGER,
    timepoint                    INTEGER,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    load_zone                    VARCHAR(32),
    energy_target_zone           VARCHAR(32),
    carbon_cap_zone              VARCHAR(32),
    technology                   VARCHAR(32),
    fuel                         VARCHAR(32),
    operations_fuel_burn_mmbtu   FLOAT,
    startup_fuel_burn_mmbtu      FLOAT,
    total_fuel_burn_mmbtu        FLOAT,
    fuel_contribution_fuelunit   FLOAT,
    net_fuel_burn_fuelunit       FLOAT,
    PRIMARY KEY (scenario_id, project, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, timepoint,
                 fuel)
);

DROP TABLE IF EXISTS results_project_carbon_emissions_by_technology_period;
CREATE TABLE results_project_carbon_emissions_by_technology_period
(
    scenario_id            INTEGER,
    period                 INTEGER,
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    load_zone              VARCHAR(32),
    technology             VARCHAR(32),
    spinup_or_lookahead    INTEGER,
    carbon_emissions_tons  FLOAT,
    PRIMARY KEY (scenario_id, period, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, load_zone,
                 technology, spinup_or_lookahead)
);


DROP TABLE IF EXISTS results_project_period_summary;
CREATE TABLE results_project_period_summary
(
    scenario_id                        INTEGER,
    project                            VARCHAR(64),
    period                             INTEGER,
    weather_iteration                  INTEGER,
    hydro_iteration                    INTEGER,
    availability_iteration             INTEGER,
    subproblem_id                      INTEGER,
    stage_id                           INTEGER,
    capacity_type                      VARCHAR(64),
    operational_type                   VARCHAR(64),
    technology                         VARCHAR(32),
    load_zone                          VARCHAR(32),
    total_delivered_bulk_power_mwh     FLOAT,
    cap_factor_equivalent              FLOAT,
    capacity_mw                        FLOAT,
    energy_mwh                         FLOAT,
    hyb_gen_capacity_mw                FLOAT,
    hyb_stor_capacity_mw               FLOAT,
    stor_energy_capacity_mwh           FLOAT,
    fuel_prod_capacity_fuelunitperhour FLOAT,
    fuel_rel_capacity_fuelunitperhour  FLOAT,
    fuel_stor_capacity_fuelunit        FLOAT,
    PRIMARY KEY (scenario_id, project, period, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id)
);

DROP TABLE IF EXISTS results_transmission_period;
CREATE TABLE results_transmission_period
(
    scenario_id                          INTEGER,
    transmission_line                    VARCHAR(64),
    period                               INTEGER,
    weather_iteration                    INTEGER,
    hydro_iteration                      INTEGER,
    availability_iteration               INTEGER,
    subproblem_id                        INTEGER,
    stage_id                             INTEGER,
    tx_capacity_type                     VARCHAR(16),
    tx_availability_type                 VARCHAR(16),
    tx_operational_type                  VARCHAR(16),
    load_zone_from                       VARCHAR(32),
    load_zone_to                         VARCHAR(32),
    min_mw                               FLOAT,
    max_mw                               FLOAT,
    new_build_capacity_mw                FLOAT,
    hours_in_period_timepoints           FLOAT,
    hours_in_subproblem_period           FLOAT,
    capacity_cost                        FLOAT,
    fixed_cost                           FLOAT,
    capacity_cost_wo_spinup_or_lookahead FLOAT,
    PRIMARY KEY (scenario_id, transmission_line, period, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id)
);


DROP TABLE IF EXISTS results_transmission_group_capacity;
CREATE TABLE results_transmission_group_capacity
(
    scenario_id                                  INTEGER,
    weather_iteration                            INTEGER,
    hydro_iteration                              INTEGER,
    availability_iteration                       INTEGER,
    subproblem_id                                INTEGER,
    stage_id                                     INTEGER,
    transmission_capacity_group                  VARCHAR(64),
    period                                       INTEGER,
    group_new_capacity                           FLOAT,
    transmission_capacity_group_new_capacity_min FLOAT,
    transmission_capacity_group_new_capacity_max FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id,
                 transmission_capacity_group, period)
);


-- Tx Capacity costs - Aggregated by "to_zone" load_zone
-- (and broken out by spinup_or_lookahead; fraction sums up to 1 between the
-- spinup_or_lookahead and the non-spinup_or_lookahead timepoints)
DROP TABLE IF EXISTS results_transmission_costs_capacity_agg;
CREATE TABLE results_transmission_costs_capacity_agg
(
    scenario_id                     INTEGER,
    load_zone                       VARCHAR(64),
    period                          INTEGER,
    weather_iteration               INTEGER,
    hydro_iteration                 INTEGER,
    availability_iteration          INTEGER,
    subproblem_id                   INTEGER,
    stage_id                        INTEGER,
    spinup_or_lookahead             INTEGER,
    fraction_of_hours_in_subproblem FLOAT,
    capacity_cost                   FLOAT,
    PRIMARY KEY (scenario_id, load_zone, period, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id, spinup_or_lookahead)
);

DROP TABLE IF EXISTS results_transmission_timepoint;
CREATE TABLE results_transmission_timepoint
(
    scenario_id                                      INTEGER,
    weather_iteration                                INTEGER,
    hydro_iteration                                  INTEGER,
    availability_iteration                           INTEGER,
    subproblem_id                                    INTEGER,
    stage_id                                         INTEGER,
    transmission_line                                VARCHAR(64),
    timepoint                                        INTEGER,
    period                                           INTEGER,
    timepoint_weight                                 FLOAT,
    number_of_hours_in_timepoint                     FLOAT,
    spinup_or_lookahead                              INTEGER,
    tx_capacity_type                                 VARCHAR(16),
    tx_availability_type                             VARCHAR(16),
    tx_operational_type                              VARCHAR(16),
    load_zone_from                                   VARCHAR(64),
    load_zone_to                                     VARCHAR(64),
    transmission_flow_mw                             FLOAT,
    transmission_losses_lz_from                      FLOAT,
    transmission_losses_lz_to                        FLOAT,
    hurdle_cost_positive_direction                   FLOAT,
    hurdle_cost_negative_direction                   FLOAT,
    hurdle_cost_by_timepoint_positive_direction      FLOAT,
    hurdle_cost_by_timepoint_negative_direction      FLOAT,
    transmission_target_zone                         VARCHAR(32),
    transmission_target_energy_positive_direction_mw FLOAT,
    transmission_target_energy_negative_direction_mw FLOAT,
    carbon_emission_imports_tons                     FLOAT,
    carbon_emission_imports_tons_degen               FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id,
                 transmission_line, timepoint)
);

DROP TABLE IF EXISTS results_transmission_imports_exports_agg;
CREATE TABLE results_transmission_imports_exports_agg
(
    scenario_id            INTEGER,
    load_zone              VARCHAR(64),
    period                 INTEGER,
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    spinup_or_lookahead    INTEGER,
    imports                FLOAT,
    exports                FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, period,
                 load_zone, spinup_or_lookahead)
);

-- Transmission Costs - Aggregated
DROP TABLE IF EXISTS results_transmission_hurdle_costs_agg;
CREATE TABLE results_transmission_hurdle_costs_agg
(
    scenario_id            INTEGER,
    load_zone              VARCHAR(64),
    period                 INTEGER,
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    spinup_or_lookahead    INTEGER,
    tx_hurdle_cost         FLOAT,
    PRIMARY KEY (scenario_id, load_zone, period, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id, spinup_or_lookahead)
);
-- Transmission Costs - Aggregated
DROP TABLE IF EXISTS results_transmission_hurdle_costs_by_timepoint_agg;
CREATE TABLE results_transmission_hurdle_costs_by_timepoint_agg
(
    scenario_id                 INTEGER,
    load_zone                   VARCHAR(64),
    timepoint                   INTEGER,
    weather_iteration           INTEGER,
    hydro_iteration             INTEGER,
    availability_iteration      INTEGER,
    subproblem_id               INTEGER,
    stage_id                    INTEGER,
    spinup_or_lookahead         INTEGER,
    tx_hurdle_cost_by_timepoint FLOAT,
    PRIMARY KEY (scenario_id, load_zone, timepoint, weather_iteration,
                 hydro_iteration, subproblem_id, stage_id, spinup_or_lookahead)
);


-- Simultaneous flows
DROP TABLE IF EXISTS results_transmission_simultaneous_flows;
CREATE TABLE results_transmission_simultaneous_flows
(
    scenario_id                          INTEGER,
    transmission_simultaneous_flow_limit VARCHAR(64),
    weather_iteration                    INTEGER,
    hydro_iteration                      INTEGER,
    availability_iteration               INTEGER,
    subproblem_id                        INTEGER,
    stage_id                             INTEGER,
    timepoint                            INTEGER,
    timepoint_weight                     FLOAT,
    period                               FLOAT,
    simultaneous_flow_mw                 FLOAT,
    dual                                 FLOAT,
    PRIMARY KEY (scenario_id, transmission_simultaneous_flow_limit,
                 weather_iteration, hydro_iteration, availability_iteration,
                 subproblem_id, stage_id, timepoint)
);

DROP TABLE IF EXISTS results_system_load_zone_timepoint;
CREATE TABLE results_system_load_zone_timepoint
(
    scenario_id                       INTEGER,
    weather_iteration                 INTEGER,
    hydro_iteration                   INTEGER,
    availability_iteration            INTEGER,
    subproblem_id                     INTEGER,
    stage_id                          INTEGER,
    load_zone                         VARCHAR(32),
    timepoint                         INTEGER,
    period                            INTEGER,
    discount_factor                   FLOAT,
    number_years_represented          FLOAT,
    timepoint_weight                  FLOAT,
    number_of_hours_in_timepoint      FLOAT,
    spinup_or_lookahead               INTEGER,
    static_load_mw                    FLOAT,
    load_modifier_power_mw            FLOAT,
    load_modifier_adjusted_load_mw    FLOAT,
    total_power_mw                    FLOAT,
    net_imports_mw                    FLOAT,
    net_market_purchases_mw           FLOAT,
    overgeneration_mw                 FLOAT,
    unserved_energy_mw                FLOAT,
    load_balance_dual                 FLOAT,
    load_balance_marginal_cost_per_mw FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, load_zone,
                 timepoint)
);

DROP TABLE IF EXISTS results_system_load_zone_period_load_summary;
CREATE TABLE results_system_load_zone_period_load_summary
(
    scenario_id            INTEGER,
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    load_zone              VARCHAR(32),
    period                 INTEGER,
    total_static_load_mwh  FLOAT,
    max_static_load_mw     FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, load_zone,
                 period)
);

DROP TABLE IF EXISTS results_system_load_zone_timepoint_loss_of_load_summary;
CREATE TABLE results_system_load_zone_timepoint_loss_of_load_summary
(
    scenario_id                        INTEGER,
    weather_iteration                  INTEGER,
    hydro_iteration                    INTEGER,
    availability_iteration             INTEGER,
    subproblem_id                      INTEGER,
    stage_id                           INTEGER,
    load_zone                          VARCHAR(32),
    timepoint                          INTEGER,
    period                             INTEGER,
    month                              INTEGER,
    day_of_month                       INTEGER,
    hour_of_day                        INTEGER,
    timepoint_weight                   FLOAT,
    number_of_hours_in_timepoint       FLOAT,
    spinup_or_lookahead                INTEGER,
    static_load_mw                     FLOAT,
    unserved_energy_stats_threshold_mw FLOAT,
    unserved_energy_mw                 FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, load_zone,
                 timepoint)
);

DROP TABLE IF EXISTS results_system_timepoint_loss_of_load_summary;
CREATE TABLE results_system_timepoint_loss_of_load_summary
(
    scenario_id                  INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    period                       INTEGER,
    month                        INTEGER,
    day_of_month                 INTEGER,
    hour_of_day                  INTEGER,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    static_load_mw               FLOAT,
    unserved_energy_mw           FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id,
                 timepoint)
);

DROP TABLE IF EXISTS
    results_system_days_loss_of_load_summary;
CREATE TABLE results_system_days_loss_of_load_summary
(
    scenario_id              INTEGER,
    weather_iteration        INTEGER,
    hydro_iteration          INTEGER,
    availability_iteration   INTEGER,
    subproblem_id            INTEGER,
    stage_id                 INTEGER,
    period                   INTEGER,
    month                    INTEGER,
    day_of_month             INTEGER,
    max_unserved_energy_mw   FLOAT,
    total_unserved_energy_mw FLOAT,
    duration_hours           FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, period,
                 month, day_of_month)
);

DROP TABLE IF EXISTS results_system_loss_of_load_metrics_summary;
CREATE TABLE results_system_loss_of_load_metrics_summary
(
    scenario_id                 INTEGER PRIMARY KEY,
    LOLH_hrs_per_year           FLOAT,
    EUE_MWh_per_year            FLOAT,
    LOLE_days_per_year          FLOAT,
    LOLP_year_fraction_of_years FLOAT
);

DROP TABLE IF EXISTS results_system_loss_of_load_month_hour_metrics_summary;
CREATE TABLE results_system_loss_of_load_month_hour_metrics_summary
(
    scenario_id INTEGER,
    month       INTEGER,
    hour_of_day INTEGER,
    LOLH        FLOAT,
    EUE         FLOAT,
    PRIMARY KEY (scenario_id, month, hour_of_day)
);

DROP TABLE IF EXISTS results_system_loss_of_load_metrics_convergence_summary;
CREATE TABLE results_system_loss_of_load_metrics_convergence_summary
(
    scenario_id                 INTEGER,
    n_years                     INTEGER,
    LOLH_hrs_per_year           FLOAT,
    EUE_MWh_per_year            FLOAT,
    LOLE_days_per_year          FLOAT,
    LOLP_year_fraction_of_years FLOAT,
    PRIMARY KEY (scenario_id, n_years)
);

DROP TABLE IF EXISTS results_system_market_participation;
CREATE TABLE results_system_market_participation
(
    scenario_id                  INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    load_zone                    VARCHAR(32),
    market                       VARCHAR(32),
    timepoint                    INTEGER,
    period                       INTEGER,
    discount_factor              FLOAT,
    number_years_represented     FLOAT,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    sell_power                   FLOAT,
    buy_power                    FLOAT,
    net_buy_power                FLOAT,
    final_sell_power             FLOAT,
    final_buy_power              FLOAT,
    final_net_buy_power          FLOAT,
    PRIMARY KEY (scenario_id, load_zone, market, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, timepoint)
);


DROP TABLE IF EXISTS results_system_market_summary;
CREATE TABLE results_system_market_summary
(
    scenario_id            INTEGER,
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    load_zone              VARCHAR(32),
    market                 VARCHAR(32),
    period                 INTEGER,
    month                  INTEGER,
    purchases_mwh          FLOAT,
    sales_mwh              FLOAT,
    costs                  FLOAT,
    revenue                FLOAT,
    PRIMARY KEY (scenario_id, load_zone, market, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, period, month)
);

DROP TABLE IF EXISTS results_system_lf_reserves_up;
CREATE TABLE results_system_lf_reserves_up
(
    scenario_id                  INTEGER,
    lf_reserves_up_ba            VARCHAR(32),
    period                       INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    discount_factor              FLOAT,
    number_years_represented     FLOAT,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    reserve_requirement_mw       FLOAT,
    reserve_provision_mw         FLOAT,
    reserve_violation_mw         FLOAT,
    dual                         FLOAT,
    marginal_price_per_mw        FLOAT,
    PRIMARY KEY (scenario_id, lf_reserves_up_ba, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, timepoint)
);

DROP TABLE IF EXISTS results_system_lf_reserves_down;
CREATE TABLE results_system_lf_reserves_down
(
    scenario_id                  INTEGER,
    lf_reserves_down_ba          VARCHAR(32),
    period                       INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    discount_factor              FLOAT,
    number_years_represented     FLOAT,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    reserve_requirement_mw       FLOAT,
    reserve_provision_mw         FLOAT,
    reserve_violation_mw         FLOAT,
    dual                         FLOAT,
    marginal_price_per_mw        FLOAT,
    PRIMARY KEY (scenario_id, lf_reserves_down_ba, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, timepoint)
);

DROP TABLE IF EXISTS results_system_regulation_up;
CREATE TABLE results_system_regulation_up
(
    scenario_id                  INTEGER,
    regulation_up_ba             VARCHAR(32),
    period                       INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    discount_factor              FLOAT,
    number_years_represented     FLOAT,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    reserve_requirement_mw       FLOAT,
    reserve_provision_mw         FLOAT,
    reserve_violation_mw         FLOAT,
    dual                         FLOAT,
    marginal_price_per_mw        FLOAT,
    PRIMARY KEY (scenario_id, regulation_up_ba, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, timepoint)
);

DROP TABLE IF EXISTS results_system_regulation_down;
CREATE TABLE results_system_regulation_down
(
    scenario_id                  INTEGER,
    regulation_down_ba           VARCHAR(32),
    period                       INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    discount_factor              FLOAT,
    number_years_represented     FLOAT,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    reserve_requirement_mw       FLOAT,
    reserve_provision_mw         FLOAT,
    reserve_violation_mw         FLOAT,
    dual                         FLOAT,
    marginal_price_per_mw        FLOAT,
    PRIMARY KEY (scenario_id, regulation_down_ba, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, timepoint)
);

DROP TABLE IF EXISTS results_system_frequency_response;
CREATE TABLE results_system_frequency_response
(
    scenario_id                  INTEGER,
    frequency_response_ba        VARCHAR(32),
    period                       INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    discount_factor              FLOAT,
    number_years_represented     FLOAT,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    reserve_requirement_mw       FLOAT,
    reserve_provision_mw         FLOAT,
    reserve_violation_mw         FLOAT,
    dual                         FLOAT,
    marginal_price_per_mw        FLOAT,
    PRIMARY KEY (scenario_id, frequency_response_ba, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, timepoint)
);

-- TODO: frequency_response_partial_ba is the same as frequency_response_ba
-- _partial included to simplify results import
DROP TABLE IF EXISTS results_system_frequency_response_partial;
CREATE TABLE results_system_frequency_response_partial
(
    scenario_id                   INTEGER,
    frequency_response_partial_ba VARCHAR(32),
    period                        INTEGER,
    weather_iteration             INTEGER,
    hydro_iteration               INTEGER,
    availability_iteration        INTEGER,
    subproblem_id                 INTEGER,
    stage_id                      INTEGER,
    timepoint                     INTEGER,
    discount_factor               FLOAT,
    number_years_represented      FLOAT,
    timepoint_weight              FLOAT,
    number_of_hours_in_timepoint  FLOAT,
    spinup_or_lookahead           INTEGER,
    reserve_requirement_mw        FLOAT,
    reserve_provision_mw          FLOAT,
    reserve_violation_mw          FLOAT,
    dual                          FLOAT,
    marginal_price_per_mw         FLOAT,
    PRIMARY KEY (scenario_id, frequency_response_partial_ba,
                 weather_iteration, hydro_iteration, availability_iteration,
                 subproblem_id, stage_id, timepoint)
);

DROP TABLE IF EXISTS results_system_spinning_reserves;
CREATE TABLE results_system_spinning_reserves
(
    scenario_id                  INTEGER,
    spinning_reserves_ba         VARCHAR(32),
    period                       INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    discount_factor              FLOAT,
    number_years_represented     FLOAT,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    reserve_requirement_mw       FLOAT,
    reserve_provision_mw         FLOAT,
    reserve_violation_mw         FLOAT,
    dual                         FLOAT,
    marginal_price_per_mw        FLOAT,
    PRIMARY KEY (scenario_id, spinning_reserves_ba, weather_iteration,
                 hydro_iteration, availability_iteration,
                 subproblem_id, stage_id, timepoint)
);

DROP TABLE IF EXISTS results_system_inertia_reserves;
CREATE TABLE results_system_inertia_reserves
(
    scenario_id                  INTEGER,
    inertia_reserves_ba          VARCHAR(32),
    period                       INTEGER,
    weather_iteration            INTEGER,
    hydro_iteration              INTEGER,
    availability_iteration       INTEGER,
    subproblem_id                INTEGER,
    stage_id                     INTEGER,
    timepoint                    INTEGER,
    discount_factor              FLOAT,
    number_years_represented     FLOAT,
    timepoint_weight             FLOAT,
    number_of_hours_in_timepoint FLOAT,
    spinup_or_lookahead          INTEGER,
    reserve_requirement_mws      FLOAT,
    reserve_provision_mws        FLOAT,
    reserve_violation_mws        FLOAT,
    dual                         FLOAT,
    marginal_price_per_mws       FLOAT,
    PRIMARY KEY (scenario_id, inertia_reserves_ba, weather_iteration,
                 hydro_iteration, availability_iteration,
                 subproblem_id, stage_id, timepoint)
);

-- Carbon emissions
DROP TABLE IF EXISTS results_system_carbon_cap;
CREATE TABLE results_system_carbon_cap
(
    scenario_id                           INTEGER,
    carbon_cap_zone                       VARCHAR(64),
    period                                INTEGER,
    weather_iteration                     INTEGER,
    hydro_iteration                       INTEGER,
    availability_iteration                INTEGER,
    subproblem_id                         INTEGER,
    stage_id                              INTEGER,
    discount_factor                       FLOAT,
    number_years_represented              FLOAT,
    carbon_cap_target                     FLOAT,
    project_emissions                     FLOAT,
    project_credits                       FLOAT,
    import_emissions                      FLOAT,
    credit_purchases                      FLOAT,
    total_emissions                       FLOAT,
    total_credits                         FLOAT,
    carbon_cap_overage                    FLOAT,
    import_emissions_degen                FLOAT,
    total_emissions_degen                 FLOAT,
    dual                                  FLOAT,
    carbon_cap_marginal_cost_per_emission FLOAT,
    PRIMARY KEY (scenario_id, carbon_cap_zone, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, period)
);

-- Carbon tax emissions
DROP TABLE IF EXISTS results_system_carbon_tax;
CREATE TABLE results_system_carbon_tax
(
    scenario_id                     INTEGER,
    carbon_tax_zone                 VARCHAR(64),
    period                          INTEGER,
    weather_iteration               INTEGER,
    hydro_iteration                 INTEGER,
    availability_iteration          INTEGER,
    subproblem_id                   INTEGER,
    stage_id                        INTEGER,
    discount_factor                 FLOAT,
    number_years_represented        FLOAT,
    project_emissions               FLOAT,
    project_credits                 FLOAT,
    carbon_tax_per_ton              FLOAT,
    total_carbon_emissions_tons     FLOAT,
    total_carbon_tax_allowance_tons FLOAT,
    total_carbon_tax_cost           FLOAT,
    dual                            FLOAT,
    PRIMARY KEY (scenario_id, carbon_tax_zone, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, period)
);

-- Performance standard
DROP TABLE IF EXISTS results_system_performance_standard;
CREATE TABLE results_system_performance_standard
(
    scenario_id                                 INTEGER,
    performance_standard_zone                   VARCHAR(64),
    period                                      INTEGER,
    weather_iteration                           INTEGER,
    hydro_iteration                             INTEGER,
    availability_iteration                      INTEGER,
    subproblem_id                               INTEGER,
    stage_id                                    INTEGER,
    discount_factor                             FLOAT,
    number_years_represented                    FLOAT,
    performance_standard_tco2_per_mwh           FLOAT,
    performance_standard_tco2_per_mw            FLOAT,
    performance_standard_project_emissions_tco2 FLOAT,
    project_credits                             FLOAT,
    performance_standard_project_energy_mwh     FLOAT,
    performance_standard_project_capacity_mw    FLOAT,
    performance_standard_energy_overage_tco2    FLOAT,
    performance_standard_power_overage_tco2     FLOAT,
    PRIMARY KEY (scenario_id, performance_standard_zone,
                 weather_iteration, hydro_iteration, availability_iteration,
                 subproblem_id, stage_id, period)
);


DROP TABLE IF EXISTS results_system_carbon_credits;
CREATE TABLE results_system_carbon_credits
(
    scenario_id                    INTEGER,
    carbon_credits_zone            VARCHAR(64),
    period                         INTEGER,
    weather_iteration              INTEGER,
    hydro_iteration                INTEGER,
    availability_iteration         INTEGER,
    subproblem_id                  INTEGER,
    stage_id                       INTEGER,
    discount_factor                FLOAT,
    number_years_represented       FLOAT,
    project_generated_credits      FLOAT,
    project_purchased_credits      FLOAT,
    total_generated_carbon_credits FLOAT,
    total_purchased_carbon_credits FLOAT,
    sell_credits                   FLOAT,
    buy_credits                    FLOAT,
    PRIMARY KEY (scenario_id, carbon_credits_zone, weather_iteration,
                 hydro_iteration, availability_iteration,
                 subproblem_id, stage_id, period)
);

-- Energy target balance
DROP TABLE IF EXISTS results_system_period_energy_target;
CREATE TABLE results_system_period_energy_target
(
    scenario_id                                INTEGER,
    energy_target_zone                         VARCHAR(64),
    weather_iteration                          INTEGER,
    hydro_iteration                            INTEGER,
    availability_iteration                     INTEGER,
    subproblem_id                              INTEGER,
    stage_id                                   INTEGER,
    period                                     INTEGER,
    discount_factor                            FLOAT,
    number_years_represented                   FLOAT,
    energy_target_mwh                          FLOAT,
    delivered_energy_target_energy_mwh         FLOAT,
    curtailed_energy_target_energy_mwh         FLOAT,
    total_energy_target_energy_mwh             FLOAT,
    fraction_of_energy_target_met              FLOAT,
    fraction_of_energy_target_energy_curtailed FLOAT,
    energy_target_shortage_mwh                 FLOAT,
    dual                                       FLOAT,
    energy_target_marginal_cost_per_mwh        FLOAT,
    PRIMARY KEY (scenario_id, energy_target_zone, period,
                 weather_iteration, hydro_iteration, availability_iteration,
                 subproblem_id, stage_id)
);

DROP TABLE IF EXISTS results_system_horizon_energy_target;
CREATE TABLE results_system_horizon_energy_target
(
    scenario_id                                INTEGER,
    energy_target_zone                         VARCHAR(64),
    weather_iteration                          INTEGER,
    hydro_iteration                            INTEGER,
    availability_iteration                     INTEGER,
    subproblem_id                              INTEGER,
    stage_id                                   INTEGER,
    balancing_type_horizon                     VARCHAR(64),
    horizon                                    INTEGER,
    energy_target_mwh                          FLOAT,
    delivered_energy_target_energy_mwh         FLOAT,
    curtailed_energy_target_energy_mwh         FLOAT,
    total_energy_target_energy_mwh             FLOAT,
    fraction_of_energy_target_met              FLOAT,
    fraction_of_energy_target_energy_curtailed FLOAT,
    energy_target_shortage_mwh                 FLOAT,
    dual                                       FLOAT,
    PRIMARY KEY (scenario_id, energy_target_zone, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, balancing_type_horizon, horizon)
);

-- instantaneous penetration
DROP TABLE IF EXISTS results_system_instantaneous_penetration;
CREATE TABLE results_system_instantaneous_penetration
(
    scenario_id                                         INTEGER,
    instantaneous_penetration_zone                      VARCHAR(64),
    period                                              INTEGER,
    timepoint                                           INTEGER,
    weather_iteration                                   INTEGER,
    hydro_iteration                                     INTEGER,
    availability_iteration                              INTEGER,
    subproblem_id                                       INTEGER,
    stage_id                                            INTEGER,
    discount_factor                                     FLOAT,
    number_years_represented                            FLOAT,
    timepoint_weight                                    FLOAT,
    number_of_hours_in_timepoint                        FLOAT,
    min_instantaneous_penetration_mwh                   FLOAT,
    max_instantaneous_penetration_mwh                   FLOAT,
    total_instantaneous_penetration_energy_mwh          FLOAT,
    instantaneous_penetration_shortage_mwh              FLOAT,
    instantaneous_penetration_overage_mwh               FLOAT,
    instantaneous_penetration_violation_mwh             FLOAT,
    dual_instantaneous_penetration_min                  FLOAT,
    instantaneous_penetration_min_marginal_price_per_mw FLOAT,
    dual_instantaneous_penetration_max                  FLOAT,
    instantaneous_penetration_max_marginal_price_per_mw FLOAT,
    PRIMARY KEY (scenario_id, instantaneous_penetration_zone,
                 weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id,
                 stage_id, timepoint)
);

-- Transmission target balance
DROP TABLE IF EXISTS results_system_transmission_targets;
CREATE TABLE results_system_transmission_targets
(
    scenario_id                                     INTEGER,
    transmission_target_zone                        VARCHAR(64),
    weather_iteration                               INTEGER,
    hydro_iteration                                 INTEGER,
    availability_iteration                          INTEGER,
    subproblem_id                                   INTEGER,
    stage_id                                        INTEGER,
    balancing_type                                  VARCHAR(32),
    horizon                                         INTEGER,
    hrz_objective_coefficient                       FLOAT,
    total_transmission_target_energy_pos_dir_mwh    FLOAT,
    transmission_target_pos_dir_min_mwh             FLOAT,
    fraction_of_transmission_target_pos_dir_min_met FLOAT,
    transmission_target_shortage_pos_dir_min_mwh    FLOAT,
    transmission_target_pos_dir_max_mwh             FLOAT,
    fraction_of_transmission_target_pos_dir_max_met FLOAT,
    transmission_target_overage_pos_dir_max_mwh     FLOAT,
    total_transmission_target_energy_neg_dir_mwh    FLOAT,
    transmission_target_neg_dir_min_mwh             FLOAT,
    fraction_of_transmission_target_neg_dir_min_met FLOAT,
    transmission_target_shortage_neg_dir_min_mwh    FLOAT,
    transmission_target_neg_dir_max_mwh             FLOAT,
    fraction_of_transmission_target_neg_dir_max_met FLOAT,
    transmission_target_overage_neg_dir_min_mwh     FLOAT,
    PRIMARY KEY (scenario_id, transmission_target_zone,
                 weather_iteration, hydro_iteration, availability_iteration,
                 subproblem_id, stage_id, balancing_type, horizon)
);

-- Fuel burn limits
DROP TABLE IF EXISTS results_system_fuel_burn_limits;
CREATE TABLE results_system_fuel_burn_limits
(
    scenario_id                                    INTEGER,
    weather_iteration                              INTEGER,
    hydro_iteration                                INTEGER,
    availability_iteration                         INTEGER,
    subproblem_id                                  INTEGER,
    stage_id                                       INTEGER,
    balancing_type                                 VARCHAR(64),
    horizon                                        INTEGER,
    number_years_represented                       FLOAT, -- based on period of last horizon timepoint
    discount_factor                                FLOAT, -- based on period of last horizon timepoint
    fuel_burn_limit_ba                             VARCHAR(32),
    fuel_burn_min_unit                             FLOAT,
    fuel_burn_max_unit                             FLOAT,
    relative_fuel_burn_max_ba                      FLOAT,
    fraction_of_relative_fuel_burn_max_fuel_ba     FLOAT,
    total_fuel_burn_unit                           FLOAT,
    fuel_burn_min_abs_shortage_unit,
    fuel_burn_max_abs_overage_unit                 FLOAT,
    abs_min_dual                                   FLOAT,
    abs_min_fuel_burn_limit_marginal_cost_per_unit FLOAT,
    abs_max_dual                                   FLOAT,
    abs_max_fuel_burn_limit_marginal_cost_per_unit FLOAT,
    fuel_burn_max_rel_overage_unit                 FLOAT,
    rel_dual                                       FLOAT,
    rel_fuel_burn_limit_marginal_cost_per_unit     FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id,
                 balancing_type, horizon, fuel_burn_limit_ba)
);

-- Generic policy
DROP TABLE IF EXISTS results_system_policy_requirements;
CREATE TABLE results_system_policy_requirements
(
    scenario_id                               INTEGER,
    policy_name                               TEXT,
    policy_zone                               TEXT,
    weather_iteration                         INTEGER,
    hydro_iteration                           INTEGER,
    availability_iteration                    INTEGER,
    subproblem_id                             INTEGER,
    stage_id                                  INTEGER,
    balancing_type_horizon                    VARCHAR(64),
    horizon                                   INTEGER,
    policy_requirement                        FLOAT,
    pre_load_modifier_load_in_hrz             FLOAT,
    post_load_modifier_load_in_hrz            FLOAT,
    policy_requirement_calculated_in_horizon  FLOAT,
    policy_requirement_shortage               FLOAT,
    dual                                      FLOAT,
    policy_requirement_marginal_cost_per_unit FLOAT,
    PRIMARY KEY (scenario_id, policy_name, policy_zone, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, balancing_type_horizon, horizon)
);



DROP TABLE IF EXISTS results_project_policy_month_hour_contributions;
CREATE TABLE results_project_policy_month_hour_contributions
(
    scenario_id            INTEGER,
    project                VARCHAR(64),
    weather_iteration      INTEGER,
    hydro_iteration        INTEGER,
    availability_iteration INTEGER,
    policy_name            TEXT,
    policy_zone            TEXT,
    period                 INTEGER,
    policy_month           INTEGER,
    policy_hour            INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    contribution_mw        FLOAT,
    PRIMARY KEY (scenario_id, project, weather_iteration, hydro_iteration,
                 availability_iteration, policy_name, policy_zone, period,
                 policy_month, policy_hour, subproblem_id, stage_id)
);

DROP TABLE IF EXISTS results_system_month_hour_policy_requirements;
CREATE TABLE results_system_month_hour_policy_requirements
(
    scenario_id                   INTEGER,
    policy_name                   TEXT,
    policy_zone                   TEXT,
    weather_iteration             INTEGER,
    hydro_iteration               INTEGER,
    availability_iteration        INTEGER,
    subproblem_id                 INTEGER,
    stage_id                      INTEGER,
    period                        INTEGER,
    policy_month                  INTEGER,
    policy_hour                   INTEGER,
    policy_month_hour_requirement FLOAT,
    PRIMARY KEY (scenario_id, policy_name, policy_zone, weather_iteration,
                 hydro_iteration, availability_iteration, subproblem_id,
                 stage_id, period, policy_month, policy_hour)
);

-- PRM balance
DROP TABLE IF EXISTS results_system_prm;
CREATE TABLE results_system_prm
(
    scenario_id                               INTEGER,
    prm_zone                                  VARCHAR(64),
    period                                    INTEGER,
    weather_iteration                         INTEGER,
    hydro_iteration                           INTEGER,
    availability_iteration                    INTEGER,
    subproblem_id                             INTEGER,
    stage_id                                  INTEGER,
    discount_factor                           FLOAT,
    number_years_represented                  FLOAT,
    prm_requirement_mw                        FLOAT,
    elcc_simple_mw                            FLOAT,
    capacity_contribution_transferred_from_mw FLOAT,
    capacity_contribution_transferred_to_mw   FLOAT,
    elcc_surface_mw                           FLOAT,
    elcc_total_mw                             FLOAT,
    prm_shortage_mw                           FLOAT,
    dual                                      FLOAT,
    prm_marginal_cost_per_mw                  FLOAT,
    PRIMARY KEY (scenario_id, prm_zone, period, weather_iteration,
                 hydro_iteration, availability_iteration,
                 subproblem_id, stage_id)
);

DROP TABLE IF EXISTS results_system_prm_elcc_surfaces;
CREATE TABLE results_system_prm_elcc_surfaces
(
    scenario_id            INTEGER,
    elcc_surface_name      VARCHAR(32),
    prm_zone               VARCHAR(64),
    period                 INTEGER,
    weather_iteration      INTEGER,
    availability_iteration INTEGER,
    hydro_iteration        INTEGER,
    subproblem_id          INTEGER,
    stage_id               INTEGER,
    elcc_surface_mw        FLOAT,
    dual                   FLOAT,
    PRIMARY KEY (scenario_id, elcc_surface_name, prm_zone, period,
                 weather_iteration, hydro_iteration, availability_iteration,
                 subproblem_id, stage_id)
);

DROP TABLE IF EXISTS results_system_capacity_transfers;
CREATE TABLE results_system_capacity_transfers
(
    scenario_id                             INTEGER,
    weather_iteration                       INTEGER,
    hydro_iteration                         INTEGER,
    availability_iteration                  INTEGER,
    subproblem_id                           INTEGER,
    stage_id                                INTEGER,
    prm_zone_from                           VARCHAR(64),
    prm_zone_to                             VARCHAR(64),
    period                                  INTEGER,
    capacity_transfer_mw                    FLOAT,
    capacity_transfer_cost_per_yr_in_period FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id,
                 prm_zone_to, prm_zone_from, period)
);

-- Local capacity balance
DROP TABLE IF EXISTS results_system_local_capacity;
CREATE TABLE results_system_local_capacity
(
    scenario_id                         INTEGER,
    local_capacity_zone                 VARCHAR(64),
    period                              INTEGER,
    weather_iteration                   INTEGER,
    hydro_iteration                     INTEGER,
    availability_iteration              INTEGER,
    subproblem_id                       INTEGER,
    stage_id                            INTEGER,
    discount_factor                     FLOAT,
    number_years_represented            FLOAT,
    local_capacity_requirement_mw       FLOAT,
    project_contribution_mw             FLOAT,
    local_capacity_provision_mw         FLOAT,
    local_capacity_shortage_mw          FLOAT,
    dual                                FLOAT,
    local_capacity_marginal_cost_per_mw FLOAT,
    PRIMARY KEY (scenario_id, local_capacity_zone, period,
                 weather_iteration, hydro_iteration, availability_iteration,
                 subproblem_id, stage_id)
);

-- RA
DROP TABLE IF EXISTS results_system_ra;


-- Water system
DROP TABLE IF EXISTS results_system_water_link_timepoint;
CREATE TABLE results_system_water_link_timepoint
(
    scenario_id                          INTEGER,
    weather_iteration                    INTEGER,
    hydro_iteration                      INTEGER,
    availability_iteration               INTEGER,
    subproblem_id                        INTEGER,
    stage_id                             INTEGER,
    water_link                           VARCHAR(32),
    departure_timepoint                  INTEGER,
    arrival_timepoint                    INTEGER,
    water_flow_vol_per_sec               FLOAT,
    water_flow_min_violation_vol_per_sec FLOAT,
    water_flow_max_violation_vol_per_sec FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, water_link,
                 departure_timepoint)
);

DROP TABLE IF EXISTS results_system_water_node_timepoint;
CREATE TABLE results_system_water_node_timepoint
(
    scenario_id                                    INTEGER,
    weather_iteration                              INTEGER,
    hydro_iteration                                INTEGER,
    availability_iteration                         INTEGER,
    subproblem_id                                  INTEGER,
    stage_id                                       INTEGER,
    water_node                                     VARCHAR(32),
    timepoint                                      INTEGER,
    starting_elevation                             FLOAT,
    starting_volume                                FLOAT,
    min_volume_violation                           FLOAT,
    max_volume_violation                           FLOAT,
    exogenous_water_inflow_rate_vol_per_sec        FLOAT,
    endogenous_water_inflow_rate_vol_per_sec       FLOAT,
    gross_water_inflow_rate_vol_per_sec            FLOAT,
    discharge_water_to_powerhouse_rate_vol_per_sec FLOAT,
    spill_water_rate_vol_per_sec                   FLOAT,
    evap_losses_NOT_IMPLEMENTED                    FLOAT,
    gross_water_outflow_rate_vol_per_sec           FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, water_node,
                 timepoint)
);

DROP TABLE IF EXISTS results_system_water_powerhouse_timepoint;
CREATE TABLE results_system_water_powerhouse_timepoint
(
    scenario_id                                    INTEGER,
    weather_iteration                              INTEGER,
    hydro_iteration                                INTEGER,
    availability_iteration                         INTEGER,
    subproblem_id                                  INTEGER,
    stage_id                                       INTEGER,
    powerhouse                                     VARCHAR(32),
    timepoint                                      INTEGER,
    water_node                                     VARCHAR(32),
    gross_head                                     FLOAT,
    net_head                                       FLOAT,
    water_discharge_to_powerhouse_rate_vol_per_sec FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id, powerhouse,
                 timepoint)
);

-- Total Costs
DROP TABLE IF EXISTS results_system_costs;
CREATE TABLE results_system_costs
(
    scenario_id                                             INTEGER,
--period INTEGER,
    weather_iteration                                       INTEGER,
    hydro_iteration                                         INTEGER,
    availability_iteration                                  INTEGER,
    subproblem_id                                           INTEGER,
    stage_id                                                INTEGER,
    Total_Capacity_Costs                                    FLOAT,
    Total_Energy_Costs                                      FLOAT,
    Total_Fixed_Costs                                       FLOAT,
    Total_Tx_Capacity_Costs                                 FLOAT,
    Total_Tx_Fixed_Costs                                    FLOAT,
    Total_PRM_Deliverability_Group_Costs                    FLOAT,
    Total_Variable_OM_Cost                                  FLOAT,
    Total_Fuel_Cost                                         FLOAT,
    Total_Startup_Cost                                      FLOAT,
    Total_Shutdown_Cost                                     FLOAT,
    Total_Operational_Violation_Cost                        FLOAT,
    Total_Curtailment_Cost                                  FLOAT,
    Total_Hurdle_Cost                                       FLOAT,
    Total_Load_Balance_Penalty_Costs                        FLOAT,
    Frequency_Response_Penalty_Costs                        FLOAT,
    Frequency_Response_Partial_Penalty_Costs                FLOAT,
    LF_Reserves_Down_Penalty_Costs                          FLOAT,
    LF_Reserves_Up_Penalty_Costs                            FLOAT,
    Regulation_Down_Penalty_Costs                           FLOAT,
    Regulation_Up_Penalty_Costs                             FLOAT,
    Spinning_Reserves_Penalty_Costs                         FLOAT,
    Inertia_Reserves_Penalty_Costs                          FLOAT,
    Total_PRM_Shortage_Penalty_Costs                        FLOAT,
    Total_Local_Capacity_Shortage_Penalty_Costs             FLOAT,
    Total_Carbon_Cap_Balance_Penalty_Costs                  FLOAT,
    Total_Carbon_Tax_Cost                                   FLOAT,
    Total_Performance_Standard_Energy_Balance_Penalty_Costs FLOAT,
    Total_Performance_Standard_Power_Balance_Penalty_Costs  FLOAT,
    Total_Period_Energy_Target_Balance_Penalty_Costs        FLOAT,
    Total_Horizon_Energy_Target_Balance_Penalty_Costs       FLOAT,
    Total_Instantaneous_Penetration_Balance_Penalty_Costs   FLOAT,
    Total_Transmission_Target_Balance_Penalty_Costs         FLOAT,
    Total_Dynamic_ELCC_Tuning_Cost                          FLOAT,
    Total_Import_Carbon_Tuning_Cost                         FLOAT,
    Total_Market_Net_Cost                                   FLOAT,
    Total_Export_Penalty_Cost                               FLOAT,
    Total_Tx_Simple_Losses_Penalty_Cost                     FLOAT,
    Total_Tx_Curtailment_Cost                               FLOAT,
    Total_Horizon_Fuel_Burn_Min_Abs_Penalty_Costs           FLOAT,
    Total_Horizon_Fuel_Burn_Max_Abs_Penalty_Costs           FLOAT,
    Total_Horizon_Fuel_Burn_Max_Rel_Penalty_Costs           FLOAT,
    Total_SOC_Penalty_Cost                                  FLOAT,
    Total_SOC_Penalty_Last_Tmp_Cost                         FLOAT,
    Total_Subsidies                                         FLOAT,
    Total_Capacity_Transfer_Costs                           FLOAT,
    Total_Carbon_Credit_Revenue                             FLOAT,
    Total_Carbon_Credit_Costs                               FLOAT,
    Total_Peak_Deviation_Monthly_Demand_Charge_Cost         FLOAT,
    Total_Policy_Target_Balance_Penalty_Costs               FLOAT,
    Total_Min_Flow_Violation_Penalty_Cost                   FLOAT,
    Total_Max_Flow_Violation_Penalty_Cost                   FLOAT,
    Total_Release_Violation_Penalty_Cost                    FLOAT,
    Total_Min_Water_Storage_Violation_Penalty_Cost          FLOAT,
    Total_Max_Water_Storage_Violation_Penalty_Cost          FLOAT,
    Total_Hrz_Min_Flow_Violation_Penalty_Cost               FLOAT,
    Total_Hrz_Max_Flow_Violation_Penalty_Cost               FLOAT,
    Total_Ramp_Tuning_Cost                                  FLOAT,
    PRIMARY KEY (scenario_id, weather_iteration, hydro_iteration,
                 availability_iteration, subproblem_id, stage_id)
);

---------------
--- OPTIONS ---
---------------

DROP TABLE IF EXISTS subscenarios_options_solver;
CREATE TABLE subscenarios_options_solver
(
    solver_options_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name              VARCHAR(32),
    description       VARCHAR(128)
);

-- Note that with shell solvers such as GAMS and AMPL, you also need to specify
-- "solver" as a solver_option_name and give it the appropriate value depending on
-- which solver you want to use (e.g. CPLEX, Gurobi) in order to pass options to that
-- solver
-- Currently, only GAMS is supported; AMPL may work
DROP TABLE IF EXISTS inputs_options_solver;
CREATE TABLE inputs_options_solver
(
    solver_options_id   INTEGER,
    solver_name         VARCHAR(32),
    solver_option_name  VARCHAR(32),
    solver_option_value FLOAT,
    PRIMARY KEY (solver_options_id, solver_name, solver_option_name),
    FOREIGN KEY (solver_options_id)
        REFERENCES subscenarios_options_solver (solver_options_id)
);

-- Views
DROP VIEW IF EXISTS scenarios_view;
CREATE VIEW scenarios_view
AS
SELECT scenario_id,
       scenario_name,
       scenario_description,
       (SELECT validation_status_name
        FROM mod_validation_status_types
        WHERE validation_status_id =
              scenarios.validation_status_id)                                        as validation_status,
       (SELECT run_status_name
        FROM mod_run_status_types
        WHERE run_status_id = scenarios.run_status_id)                               as run_status,
       CASE WHEN of_transmission THEN 'yes' ELSE 'no' END                            AS feature_transmission,
       CASE WHEN of_transmission_hurdle_rates = 1 THEN 'yes' ELSE 'no' END
                                                                                     AS feature_transmission_hurdle_rates,
       CASE
           WHEN of_transmission_hurdle_rates_by_timepoint = 1 THEN 'yes'
           ELSE 'no' END
                                                                                     AS feature_transmission_hurdle_rates_by_timepoint,
       CASE WHEN of_simultaneous_flow_limits THEN 'yes' ELSE 'no' END
                                                                                     AS feature_simultaneous_flow_limits,
       CASE WHEN of_lf_reserves_up THEN 'yes' ELSE 'no' END
                                                                                     AS feature_load_following_up,
       CASE WHEN of_lf_reserves_down THEN 'yes' ELSE 'no' END
                                                                                     AS feature_load_following_down,
       CASE WHEN of_regulation_up THEN 'yes' ELSE 'no' END
                                                                                     AS feature_regulation_up,
       CASE WHEN of_regulation_down THEN 'yes' ELSE 'no' END
                                                                                     AS feature_regulation_down,
       CASE WHEN of_frequency_response THEN 'yes' ELSE 'no' END
                                                                                     AS feature_frequency_response,
       CASE WHEN of_spinning_reserves THEN 'yes' ELSE 'no' END
                                                                                     AS feature_spinning_reserves,
       CASE WHEN of_inertia_reserves THEN 'yes' ELSE 'no' END
                                                                                     AS feature_inertia_reserves,
       CASE WHEN of_period_energy_target THEN 'yes' ELSE 'no' END                    AS
                                                                                        feature_period_energy_target,
       CASE WHEN of_carbon_cap THEN 'yes' ELSE 'no' END
                                                                                     AS feature_carbon_cap,
       CASE WHEN of_track_carbon_imports THEN 'yes' ELSE 'no' END
                                                                                     AS feature_track_carbon_imports,
       CASE WHEN of_prm THEN 'yes' ELSE 'no' END                                     AS feature_prm,
       CASE WHEN of_elcc_surface THEN 'yes' ELSE 'no' END
                                                                                     AS feature_elcc_surface,
       CASE WHEN of_local_capacity THEN 'yes' ELSE 'no' END
                                                                                     AS feature_local_capacity,
       CASE WHEN of_tuning THEN 'yes' ELSE 'no' END
                                                                                     AS feature_tuning,
       (SELECT name
        FROM subscenarios_temporal
        WHERE temporal_scenario_id =
              scenarios.temporal_scenario_id)                                        AS temporal,
       (SELECT name
        FROM subscenarios_geography_load_zones
        WHERE load_zone_scenario_id =
              scenarios.load_zone_scenario_id)                                       AS geography_load_zones,
       (SELECT name
        FROM subscenarios_geography_load_balance
        WHERE load_balance_scenario_id =
              scenarios.load_balance_scenario_id)                                    AS geography_load_balance,
       (SELECT name
        FROM subscenarios_geography_lf_reserves_up_bas
        WHERE lf_reserves_up_ba_scenario_id =
              scenarios.lf_reserves_up_ba_scenario_id)                               AS geography_lf_up_bas,
       (SELECT name
        FROM subscenarios_geography_lf_reserves_down_bas
        WHERE lf_reserves_down_ba_scenario_id =
              scenarios.lf_reserves_down_ba_scenario_id)                             AS geography_lf_down_bas,
       (SELECT name
        FROM subscenarios_geography_regulation_up_bas
        WHERE regulation_up_ba_scenario_id =
              scenarios.regulation_up_ba_scenario_id)                                AS geography_reg_up_bas,
       (SELECT name
        FROM subscenarios_geography_regulation_down_bas
        WHERE regulation_down_ba_scenario_id =
              scenarios.regulation_down_ba_scenario_id)                              AS geography_reg_down_bas,
       (SELECT name
        FROM subscenarios_geography_spinning_reserves_bas
        WHERE spinning_reserves_ba_scenario_id =
              scenarios.spinning_reserves_ba_scenario_id)                            AS geography_spin_bas,
       (SELECT name
        FROM subscenarios_geography_inertia_reserves_bas
        WHERE inertia_reserves_ba_scenario_id =
              scenarios.inertia_reserves_ba_scenario_id)                             AS geography_iner_bas,
       (SELECT name
        FROM subscenarios_geography_frequency_response_bas
        WHERE frequency_response_ba_scenario_id =
              scenarios.frequency_response_ba_scenario_id)                           AS geography_freq_resp_bas,
       (SELECT name
        FROM subscenarios_geography_energy_target_zones
        WHERE energy_target_zone_scenario_id =
              scenarios.energy_target_zone_scenario_id)                              AS geography_energy_target_areas,
       (SELECT name
        FROM subscenarios_geography_instantaneous_penetration_zones
        WHERE instantaneous_penetration_zone_scenario_id =
              scenarios.instantaneous_penetration_zone_scenario_id)                  AS geography_instantaneous_penetration_zones,
       (SELECT name
        FROM subscenarios_geography_transmission_target_zones
        WHERE transmission_target_zone_scenario_id =
              scenarios.transmission_target_zone_scenario_id)                        AS geography_transmission_target_zones,
       (SELECT name
        FROM subscenarios_geography_carbon_cap_zones
        WHERE carbon_cap_zone_scenario_id =
              scenarios.carbon_cap_zone_scenario_id)                                 AS carbon_cap_areas,
       (SELECT name
        FROM subscenarios_geography_carbon_tax_zones
        WHERE carbon_tax_zone_scenario_id =
              scenarios.carbon_tax_zone_scenario_id)                                 AS geography_carbon_tax_zones,
       (SELECT name
        FROM subscenarios_geography_performance_standard_zones
        WHERE performance_standard_zone_scenario_id =
              scenarios.performance_standard_zone_scenario_id)                       AS geography_performance_standard_zones,
       (SELECT name
        FROM subscenarios_geography_carbon_credits_zones
        WHERE carbon_credits_zone_scenario_id =
              scenarios.carbon_credits_zone_scenario_id)                             AS geography_carbon_credits_zones,
       (SELECT name
        FROM subscenarios_system_carbon_cap_zones_carbon_credits_zones
        WHERE carbon_cap_zones_carbon_credits_zones_scenario_id =
              scenarios.carbon_cap_zones_carbon_credits_zones_scenario_id)           AS carbon_cap_zones_carbon_credits_zones,
       (SELECT name
        FROM subscenarios_system_performance_standard_zones_carbon_credits_zones
        WHERE performance_standard_zones_carbon_credits_zones_scenario_id =
              scenarios.performance_standard_zones_carbon_credits_zones_scenario_id) AS performance_standard_zones_carbon_credits_zones,
       (SELECT name
        FROM subscenarios_system_carbon_tax_zones_carbon_credits_zones
        WHERE carbon_tax_zones_carbon_credits_zones_scenario_id =
              scenarios.carbon_tax_zones_carbon_credits_zones_scenario_id)           AS carbon_tax_zones_carbon_credits_zones,
       (SELECT name
        FROM subscenarios_system_carbon_credits_params
        WHERE carbon_credits_params_scenario_id =
              scenarios.carbon_credits_params_scenario_id)                           AS carbon_credits_params,
       (SELECT name
        FROM subscenarios_geography_fuel_burn_limit_balancing_areas
        WHERE fuel_burn_limit_ba_scenario_id =
              scenarios.fuel_burn_limit_ba_scenario_id)                              AS geography_fuel_burn_limit_bas,
       (SELECT name
        FROM subscenarios_geography_policy_zones
        WHERE policy_zone_scenario_id =
              scenarios.policy_zone_scenario_id)                                     AS geography_policy_zones,
       (SELECT name
        FROM subscenarios_geography_prm_zones
        WHERE prm_zone_scenario_id =
              scenarios.prm_zone_scenario_id)                                        AS prm_areas,
       (SELECT name
        FROM subscenarios_geography_local_capacity_zones
        WHERE local_capacity_zone_scenario_id =
              scenarios.local_capacity_zone_scenario_id)                             AS local_capacity_areas,
       (SELECT name
        FROM subscenarios_geography_markets
        WHERE market_scenario_id =
              scenarios.market_scenario_id)                                          AS markets,
       (SELECT name
        FROM subscenarios_system_water_system_params
        WHERE water_system_params_scenario_id =
              scenarios.water_system_params_scenario_id)                             AS water_system_params,
       (SELECT name
        FROM subscenarios_geography_water_network
        WHERE water_network_scenario_id =
              scenarios.water_network_scenario_id)                                   AS water_network,
       (SELECT name
        FROM subscenarios_project_portfolios
        WHERE project_portfolio_scenario_id =
              scenarios.project_portfolio_scenario_id)                               AS project_portfolio,
       (SELECT name
        FROM subscenarios_project_operational_chars
        WHERE project_operational_chars_scenario_id =
              scenarios.project_operational_chars_scenario_id)                       AS project_operating_chars,
       (SELECT name
        FROM subscenarios_project_availability
        WHERE project_availability_scenario_id =
              scenarios.project_availability_scenario_id)                            AS project_availability,
       (SELECT name
        FROM subscenarios_fuels
        WHERE fuel_scenario_id = scenarios.fuel_scenario_id)                         AS project_fuels,
       (SELECT name
        FROM subscenarios_fuel_prices
        WHERE fuel_price_scenario_id =
              scenarios.fuel_price_scenario_id)                                      AS fuel_prices,
       (SELECT name
        FROM subscenarios_project_load_zones
        WHERE project_load_zone_scenario_id =
              scenarios.project_load_zone_scenario_id)                               AS project_load_zones,
       (SELECT name
        FROM subscenarios_project_lf_reserves_up_bas
        WHERE project_lf_reserves_up_ba_scenario_id =
              scenarios.project_lf_reserves_up_ba_scenario_id)                       AS project_lf_up_bas,
       (SELECT name
        FROM subscenarios_project_lf_reserves_down_bas
        WHERE project_lf_reserves_down_ba_scenario_id =
              scenarios.project_lf_reserves_down_ba_scenario_id)                     AS project_lf_down_bas,
       (SELECT name
        FROM subscenarios_project_regulation_up_bas
        WHERE project_regulation_up_ba_scenario_id =
              scenarios.project_regulation_up_ba_scenario_id)                        AS project_reg_up_bas,
       (SELECT name
        FROM subscenarios_project_regulation_down_bas
        WHERE project_regulation_down_ba_scenario_id =
              scenarios.project_regulation_down_ba_scenario_id)                      AS project_reg_down_bas,
       (SELECT name
        FROM subscenarios_project_spinning_reserves_bas
        WHERE project_spinning_reserves_ba_scenario_id =
              scenarios.project_spinning_reserves_ba_scenario_id)                    AS project_spin_bas,
       (SELECT name
        FROM subscenarios_project_inertia_reserves_bas
        WHERE project_inertia_reserves_ba_scenario_id =
              scenarios.project_inertia_reserves_ba_scenario_id)                     AS project_iner_bas,
       (SELECT name
        FROM subscenarios_project_frequency_response_bas
        WHERE project_frequency_response_ba_scenario_id =
              scenarios.project_frequency_response_ba_scenario_id)                   AS project_freq_resp_bas,
       (SELECT name
        FROM subscenarios_project_energy_target_zones
        WHERE project_energy_target_zone_scenario_id =
              scenarios.project_energy_target_zone_scenario_id)                      AS project_energy_target_areas,
       (SELECT name
        FROM subscenarios_project_instantaneous_penetration_zones
        WHERE project_instantaneous_penetration_zone_scenario_id =
              scenarios.project_instantaneous_penetration_zone_scenario_id)          AS project_instantaneous_penetration_zones,
       (SELECT name
        FROM subscenarios_tx_line_transmission_target_zones
        WHERE tx_line_transmission_target_zone_scenario_id =
              scenarios.tx_line_transmission_target_zone_scenario_id)                AS tx_line_transmission_target_zones,
       (SELECT name
        FROM subscenarios_project_carbon_cap_zones
        WHERE project_carbon_cap_zone_scenario_id =
              scenarios.project_carbon_cap_zone_scenario_id)                         AS project_carbon_cap_areas,
       (SELECT name
        FROM subscenarios_project_carbon_tax_zones
        WHERE project_carbon_tax_zone_scenario_id =
              scenarios.project_carbon_tax_zone_scenario_id)                         AS project_carbon_tax_zones,
       (SELECT name
        FROM subscenarios_project_carbon_tax_allowance
        WHERE project_carbon_tax_allowance_scenario_id =
              scenarios.project_carbon_tax_allowance_scenario_id)                    AS project_carbon_tax_allowance,
       (SELECT name
        FROM subscenarios_project_performance_standard_zones
        WHERE project_performance_standard_zone_scenario_id =
              scenarios.project_performance_standard_zone_scenario_id)               AS project_performance_standard_zones,
       (SELECT name
        FROM subscenarios_project_carbon_credits_generation_zones
        WHERE project_carbon_credits_generation_zone_scenario_id =
              scenarios.project_carbon_credits_generation_zone_scenario_id)          AS project_carbon_credits_generation_zones,
       (SELECT name
        FROM subscenarios_project_carbon_credits_purchase_zones
        WHERE project_carbon_credits_purchase_zone_scenario_id =
              scenarios.project_carbon_credits_purchase_zone_scenario_id)            AS project_carbon_credits_purchase_zones,
       (SELECT name
        FROM subscenarios_project_carbon_credits_purchase_limits
        WHERE project_carbon_credits_purchase_limits_scenario_id =
              scenarios.project_carbon_credits_purchase_limits_scenario_id)          AS project_carbon_credits_purchase_limits,
       (SELECT name
        FROM subscenarios_project_carbon_credits
        WHERE project_carbon_credits_scenario_id =
              scenarios.project_carbon_credits_scenario_id)                          AS project_carbon_credits,
       (SELECT name
        FROM subscenarios_project_fuel_burn_limit_balancing_areas
        WHERE project_fuel_burn_limit_ba_scenario_id =
              scenarios.project_fuel_burn_limit_ba_scenario_id)                      AS project_fuel_burn_limit_bas,
       (SELECT name
        FROM subscenarios_fuel_fuel_burn_limit_balancing_areas
        WHERE fuel_fuel_burn_limit_ba_scenario_id =
              scenarios.fuel_fuel_burn_limit_ba_scenario_id)                         AS fuel_fuel_burn_limit_bas,
       (SELECT name
        FROM subscenarios_project_policy_zones
        WHERE project_policy_zone_scenario_id =
              scenarios.project_policy_zone_scenario_id)                             AS project_policy_zones,
       (SELECT name
        FROM subscenarios_transmission_policy_zones
        WHERE transmission_policy_zone_scenario_id =
              scenarios.transmission_policy_zone_scenario_id)                        AS transmission_policy_zones,
       (SELECT name
        FROM subscenarios_project_prm_zones
        WHERE project_prm_zone_scenario_id =
              scenarios.project_prm_zone_scenario_id)                                AS project_prm_areas,
       (SELECT name
        FROM subscenarios_transmission_prm_capacity_transfers
        WHERE prm_capacity_transfer_scenario_id =
              scenarios.prm_capacity_transfer_scenario_id)                           AS prm_capacity_transfers,
       (SELECT name
        FROM subscenarios_transmission_prm_capacity_transfer_params
        WHERE prm_capacity_transfer_params_scenario_id =
              scenarios.prm_capacity_transfer_params_scenario_id)                    AS prm_capacity_transfer_params,
       (SELECT name
        FROM subscenarios_transmission_prm_zones
        WHERE transmission_prm_zone_scenario_id =
              scenarios.transmission_prm_zone_scenario_id)                           AS transmission_prm_zones,
       (SELECT name
        FROM subscenarios_project_elcc_chars
        WHERE project_elcc_chars_scenario_id =
              scenarios.project_elcc_chars_scenario_id)                              AS project_elcc_chars,
       (SELECT name
        FROM subscenarios_project_prm_deliverability_costs
        WHERE prm_deliverability_cost_scenario_id =
              scenarios.prm_deliverability_cost_scenario_id)                         AS project_prm_deliverability_costs,
       (SELECT name
        FROM subscenarios_project_prm_deliverability_existing
        WHERE prm_deliverability_existing_scenario_id =
              scenarios.prm_deliverability_existing_scenario_id)                     AS prm_deliverability_existing,
       (SELECT name
        FROM subscenarios_project_prm_deliverability_potential
        WHERE prm_deliverability_potential_scenario_id =
              scenarios.prm_deliverability_potential_scenario_id)                    AS prm_deliverability_potential,
       (SELECT name
        FROM subscenarios_project_prm_deliverability_multipliers
        WHERE project_prm_deliverability_multipliers_scenario_id =
              scenarios.project_prm_deliverability_multipliers_scenario_id)          AS project_prm_deliverability_multipliers,
       (SELECT name
        FROM subscenarios_project_local_capacity_zones
        WHERE project_local_capacity_zone_scenario_id =
              scenarios.project_local_capacity_zone_scenario_id)                     AS project_local_capacity_areas,
       (SELECT name
        FROM subscenarios_project_local_capacity_chars
        WHERE project_local_capacity_chars_scenario_id =
              scenarios.project_local_capacity_chars_scenario_id)                    AS project_local_capacity_chars,
       (SELECT name
        FROM subscenarios_load_zone_markets
        WHERE load_zone_market_scenario_id =
              scenarios.load_zone_market_scenario_id)                                AS load_zone_markets,
       (SELECT name
        FROM subscenarios_project_specified_capacity
        WHERE project_specified_capacity_scenario_id =
              scenarios.project_specified_capacity_scenario_id)                      AS project_specified_capacity,
       (SELECT name
        FROM subscenarios_project_specified_fixed_cost
        WHERE project_specified_fixed_cost_scenario_id =
              scenarios.project_specified_fixed_cost_scenario_id)                    AS project_specified_fixed_cost,
       (SELECT name
        FROM subscenarios_project_new_cost
        WHERE project_new_cost_scenario_id =
              scenarios.project_new_cost_scenario_id)                                AS project_new_cost,
       (SELECT name
        FROM subscenarios_project_new_potential
        WHERE project_new_potential_scenario_id =
              scenarios.project_new_potential_scenario_id)                           AS project_new_potential,
       (SELECT name
        FROM subscenarios_project_new_binary_build_size
        WHERE project_new_binary_build_size_scenario_id =
              scenarios.project_new_binary_build_size_scenario_id)                   AS project_new_binary_build_size,
       (SELECT name
        FROM subscenarios_project_capacity_group_requirements
        WHERE project_capacity_group_requirement_scenario_id =
              scenarios.project_capacity_group_requirement_scenario_id)              AS project_capacity_group_requirements,
       (SELECT name
        FROM subscenarios_project_relative_capacity_requirements
        WHERE project_relative_capacity_requirement_scenario_id =
              scenarios.project_relative_capacity_requirement_scenario_id)           AS project_relative_capacity_requirements,
       (SELECT name
        FROM subscenarios_project_capacity_groups
        WHERE project_capacity_group_scenario_id =
              scenarios.project_capacity_group_scenario_id)                          AS project_capacity_groups,
       (SELECT name
        FROM subscenarios_transmission_portfolios
        WHERE transmission_portfolio_scenario_id =
              scenarios.transmission_portfolio_scenario_id)                          AS transmission_portfolio,
       (SELECT name
        FROM subscenarios_transmission_load_zones
        WHERE transmission_load_zone_scenario_id =
              scenarios.transmission_load_zone_scenario_id)                          AS transmission_load_zones,
       (SELECT name
        FROM subscenarios_transmission_specified_capacity
        WHERE transmission_specified_capacity_scenario_id =
              scenarios.transmission_specified_capacity_scenario_id)
                                                                                     AS transmission_specified_capacity,
       (SELECT name
        FROM subscenarios_transmission_new_cost
        WHERE transmission_new_cost_scenario_id =
              scenarios.transmission_new_cost_scenario_id)
                                                                                     AS transmission_new_cost,
       (SELECT name
        FROM subscenarios_transmission_operational_chars
        WHERE transmission_operational_chars_scenario_id =
              scenarios.transmission_operational_chars_scenario_id)
                                                                                     AS transmission_operational_chars,
       (SELECT name
        FROM subscenarios_transmission_hurdle_rates
        WHERE transmission_hurdle_rate_scenario_id =
              scenarios.transmission_hurdle_rate_scenario_id)                        AS transmission_hurdle_rates,
       (SELECT name
        FROM subscenarios_transmission_hurdle_rates_by_timepoint
        WHERE transmission_hurdle_rate_by_timepoint_scenario_id =
              scenarios.transmission_hurdle_rate_by_timepoint_scenario_id)           AS transmission_hurdle_rates_by_timepoint,
       (SELECT name
        FROM subscenarios_transmission_new_potential
        WHERE transmission_new_potential_scenario_id =
              scenarios.transmission_new_potential_scenario_id)                      AS transmission_new_potential,
       (SELECT name
        FROM subscenarios_transmission_availability
        WHERE transmission_availability_scenario_id =
              scenarios.transmission_availability_scenario_id)                       AS transmission_availability,
       (SELECT name
        FROM subscenarios_transmission_flow
        WHERE transmission_flow_scenario_id =
              scenarios.transmission_flow_scenario_id)                               AS transmission_flow,
       (SELECT name
        FROM subscenarios_transmission_capacity_group_requirements
        WHERE transmission_capacity_group_requirement_scenario_id =
              scenarios.transmission_capacity_group_requirement_scenario_id)         AS transmission_capacity_group_requirements,
       (SELECT name
        FROM subscenarios_transmission_capacity_groups
        WHERE transmission_capacity_group_scenario_id =
              scenarios.transmission_capacity_group_scenario_id)                     AS transmission_capacity_groups,
       (SELECT name
        FROM subscenarios_transmission_carbon_cap_zones
        WHERE transmission_carbon_cap_zone_scenario_id =
              scenarios.transmission_carbon_cap_zone_scenario_id)
                                                                                     AS transmission_carbon_cap_zones,
       (SELECT name
        FROM subscenarios_transmission_simultaneous_flow_limits
        WHERE transmission_simultaneous_flow_limit_scenario_id =
              scenarios.transmission_simultaneous_flow_limit_scenario_id)
                                                                                     AS transmission_simultaneous_flow_limits,
       (SELECT name
        FROM subscenarios_transmission_simultaneous_flow_limit_line_groups
        WHERE transmission_simultaneous_flow_limit_line_group_scenario_id =
              scenarios.transmission_simultaneous_flow_limit_line_group_scenario_id) AS
                                                                                        transmission_simultaneous_flow_limit_line_groups,
       (SELECT name
        FROM subscenarios_system_load
        WHERE load_scenario_id = scenarios.load_scenario_id)                         AS load_profile,
       (SELECT name
        FROM subscenarios_system_lf_reserves_up
        WHERE lf_reserves_up_scenario_id =
              scenarios.lf_reserves_up_scenario_id)                                  AS load_following_reserves_up_profile,
       (SELECT name
        FROM subscenarios_system_lf_reserves_down
        WHERE lf_reserves_down_scenario_id =
              scenarios.lf_reserves_down_scenario_id)
                                                                                     AS load_following_reserves_down_profile,
       (SELECT name
        FROM subscenarios_system_regulation_up
        WHERE regulation_up_scenario_id =
              scenarios.regulation_up_scenario_id)                                   AS regulation_up_profile,
       (SELECT name
        FROM subscenarios_system_regulation_down
        WHERE regulation_down_scenario_id =
              scenarios.regulation_down_scenario_id)                                 AS regulation_down_profile,
       (SELECT name
        FROM subscenarios_system_spinning_reserves
        WHERE spinning_reserves_scenario_id =
              scenarios.spinning_reserves_scenario_id)                               AS spinning_reserves_profile,
       (SELECT name
        FROM subscenarios_system_inertia_reserves
        WHERE inertia_reserves_scenario_id =
              scenarios.inertia_reserves_scenario_id)                                AS inertia_reserves_profile,
       (SELECT name
        FROM subscenarios_system_frequency_response
        WHERE frequency_response_scenario_id =
              scenarios.frequency_response_scenario_id)                              AS frequency_response_profile,
       (SELECT name
        FROM subscenarios_system_period_energy_targets
        WHERE period_energy_target_scenario_id =
              scenarios.period_energy_target_scenario_id)                            AS period_energy_target,
       (SELECT name
        FROM subscenarios_system_horizon_energy_targets
        WHERE horizon_energy_target_scenario_id =
              scenarios.horizon_energy_target_scenario_id)                           AS horizon_energy_target,
       (SELECT name
        FROM subscenarios_system_instantaneous_penetration
        WHERE instantaneous_penetration_scenario_id =
              scenarios.instantaneous_penetration_scenario_id)                       AS instantaneous_penetration,
       (SELECT name
        FROM subscenarios_system_transmission_targets
        WHERE transmission_target_scenario_id =
              scenarios.transmission_target_scenario_id)                             AS transmission_target,
       (SELECT name
        FROM subscenarios_system_carbon_cap_targets
        WHERE carbon_cap_target_scenario_id =
              scenarios.carbon_cap_target_scenario_id)                               AS carbon_cap,
       (SELECT name
        FROM subscenarios_system_carbon_tax
        WHERE carbon_tax_scenario_id =
              scenarios.carbon_tax_scenario_id)                                      AS carbon_tax,
       (SELECT name
        FROM subscenarios_system_performance_standard
        WHERE performance_standard_scenario_id =
              scenarios.performance_standard_scenario_id)                            AS performance_standard,
       (SELECT name
        FROM subscenarios_system_fuel_burn_limits
        WHERE fuel_burn_limit_scenario_id =
              scenarios.fuel_burn_limit_scenario_id)                                 AS fuel_burn_limits,
       (SELECT name
        FROM subscenarios_system_subsidies
        WHERE subsidy_scenario_id =
              scenarios.subsidy_scenario_id)                                         AS subsidies,
       (SELECT name
        FROM subscenarios_system_policy_requirements
        WHERE policy_requirement_scenario_id =
              scenarios.policy_requirement_scenario_id)                              AS policy_requirements,
       (SELECT name
        FROM subscenarios_system_prm_requirement
        WHERE prm_requirement_scenario_id =
              scenarios.prm_requirement_scenario_id)                                 AS prm_requirement,
       (SELECT name
        FROM subscenarios_system_prm_zone_elcc_surface
        WHERE elcc_surface_scenario_id =
              scenarios.elcc_surface_scenario_id)                                    AS elcc_surface,
       (SELECT name
        FROM subscenarios_system_local_capacity_requirement
        WHERE local_capacity_requirement_scenario_id =
              scenarios.local_capacity_requirement_scenario_id)
                                                                                     AS local_capacity_requirement,
       (SELECT name
        FROM subscenarios_market_prices
        WHERE market_price_scenario_id =
              scenarios.market_price_scenario_id)                                    AS market_prices,
       (SELECT name
        FROM subscenarios_market_volume
        WHERE market_volume_scenario_id =
              scenarios.market_volume_scenario_id)                                   AS market_volume,
       (SELECT name
        FROM subscenarios_market_volume_totals_in_tmp
        WHERE market_volume_total_in_tmp_scenario_id =
              scenarios.market_volume_total_in_tmp_scenario_id)                      AS market_volume_totals_in_tmp,
       (SELECT name
        FROM subscenarios_market_volume_totals_in_prd
        WHERE market_volume_total_in_prd_scenario_id =
              scenarios.market_volume_total_in_prd_scenario_id)                      AS market_volume_totals_in_prd,
       (SELECT name
        FROM subscenarios_system_water_node_reservoirs
        WHERE water_node_reservoir_scenario_id =
              scenarios.water_node_reservoir_scenario_id)                            AS water_node_reservoirs,
       (SELECT name
        FROM subscenarios_system_water_flows
        WHERE water_flow_scenario_id =
              scenarios.water_flow_scenario_id)                                      AS water_flows,
       (SELECT name
        FROM subscenarios_system_water_inflows
        WHERE water_inflow_scenario_id =
              scenarios.water_inflow_scenario_id)                                    AS water_inflows,
       (SELECT name
        FROM subscenarios_system_water_powerhouses
        WHERE water_powerhouse_scenario_id =
              scenarios.water_powerhouse_scenario_id)                                AS water_powerhouses,
       (SELECT name
        FROM subscenarios_tuning
        WHERE tuning_scenario_id =
              scenarios.tuning_scenario_id)                                          AS tuning,
       (SELECT name
        FROM subscenarios_options_solver
        WHERE solver_options_id = scenarios.solver_options_id)                       as solver
FROM scenarios;


-- This view combines the project portfolios and operational characteristics
-- table since we often need both, e.g. get the projects in the active
-- portfolio of operational type X.
-- TODO: refactor existing queries that could also use this view
DROP VIEW IF EXISTS project_portfolio_opchars;
CREATE VIEW project_portfolio_opchars AS
SELECT *
FROM inputs_project_portfolios
         LEFT OUTER JOIN
     inputs_project_operational_chars
     USING (project)
;

DROP VIEW IF EXISTS transmission_portfolio_opchars;
CREATE VIEW transmission_portfolio_opchars AS
SELECT *
FROM inputs_transmission_portfolios
         LEFT OUTER JOIN
     inputs_transmission_operational_chars
     USING (transmission_line)
;


-- This view shows the possible operational periods for new projects, based on
-- the available vintages and their lifetime. E.g. a project available in
-- vintage 2020 with a lifetime of 30 years will have the 2020 through 2049
-- as possible operational periods.
-- We use recursive CTE to calculate this, see e.g.
-- https://stackoverflow.com/questions/45104717/sql-to-generate-a-number
-- between-range-specified-by-columns
-- Note: the renaming of the columns ("AS period" is not strictly necessary
-- since the UNION ALL statement doesn't read the column names
DROP VIEW IF EXISTS project_new_operational_periods;
CREATE VIEW project_new_operational_periods AS
WITH main_data (project, project_new_cost_scenario_id, period, highrange)
         AS (SELECT project,
                    project_new_cost_scenario_id,
                    vintage                            AS period,
                    vintage + operational_lifetime_yrs AS highrange
             FROM inputs_project_new_cost
             UNION ALL
             SELECT project,
                    project_new_cost_scenario_id,
                    period + 1 AS period,
                    highrange
             FROM main_data
             WHERE period < highrange - 1)
SELECT distinct project_new_cost_scenario_id, project, period
FROM main_data
;


DROP VIEW IF EXISTS transmission_new_operational_periods;
CREATE VIEW transmission_new_operational_periods AS
WITH main_data (transmission_line, transmission_new_cost_scenario_id, period,
                highrange)
         AS (SELECT transmission_line,
                    transmission_new_cost_scenario_id,
                    vintage                               AS period,
                    vintage + tx_operational_lifetime_yrs AS highrange
             FROM inputs_transmission_new_cost
             UNION ALL
             SELECT transmission_line,
                    transmission_new_cost_scenario_id,
                    period + 1 AS period,
                    highrange
             FROM main_data
             WHERE period < highrange - 1)
SELECT distinct transmission_new_cost_scenario_id, transmission_line, period
FROM main_data
;

-- This view shows the possible operational periods for new and specified
-- projects, based on the available vintage and lifetime and/or the specified
-- capacity periods, as well as the actual modeled periods.
DROP VIEW IF EXISTS project_operational_periods;
CREATE VIEW project_operational_periods AS
SELECT DISTINCT project_specified_capacity_scenario_id,
                project_new_cost_scenario_id,
                temporal_scenario_id,
                project,
                period
FROM (
         -- Get operational periods of specified projects
         SELECT project_specified_capacity_scenario_id,
                NULL AS project_new_cost_scenario_id,
                project,
                period
         FROM inputs_project_specified_capacity
         -- Add operational periods of new projects
         UNION ALL
         SELECT NULL AS project_specified_capacity_scenario_id,
                project_new_cost_scenario_id,
                project,
                period
         FROM project_new_operational_periods) AS all_operational_project_periods
         -- Combine with study periods from each temporal_scenario_id
         INNER JOIN
     (SELECT temporal_scenario_id, period
      FROM inputs_temporal_periods) as relevant_periods_tbl
     USING (period)
;


-- This view shows the possible operational periods for new and specified
-- transmission, based on the available vintage and lifetime and/or the
-- specified capacity periods, as well as the actual modeled periods.
DROP VIEW IF EXISTS transmission_operational_periods;
CREATE VIEW transmission_operational_periods AS
SELECT DISTINCT transmission_specified_capacity_scenario_id,
                transmission_new_cost_scenario_id,
                temporal_scenario_id,
                transmission_line,
                period
FROM (
         -- Get operational periods of specified projects
         SELECT transmission_specified_capacity_scenario_id,
                NULL AS transmission_new_cost_scenario_id,
                transmission_line,
                period
         FROM inputs_transmission_specified_capacity
         -- Add operational periods of new projects
         UNION ALL
         SELECT NULL AS transmission_specified_capacity_scenario_id,
                transmission_new_cost_scenario_id,
                transmission_line,
                period
         FROM transmission_new_operational_periods) AS all_operational_project_periods
         -- Combine with study periods from each temporal_scenario_id
         INNER JOIN
     (SELECT temporal_scenario_id, period
      FROM inputs_temporal_periods) as relevant_periods_tbl
     USING (period)
;

-- This view shows the periods and the respective horizons within each period
-- for each balancing_type, based on the timepoint-to-horizon mapping and the
-- timepoint-to-period mapping.
DROP VIEW IF EXISTS periods_horizons;
CREATE VIEW periods_horizons AS
SELECT DISTINCT temporal_scenario_id,
                stage_id,
                balancing_type_horizon,
                period,
                horizon
FROM inputs_temporal
         INNER JOIN
     inputs_temporal_horizon_timepoints
     USING (temporal_scenario_id, stage_id, timepoint)
;

-- This view shows the possible operational horizons for each project based
-- based on its operational periods (see project_operational_periods), its
-- balancing type, and the periods-horizons mapping for that balancing type
-- (see periods_horizons). It also includes the operational type and the
-- hydro_operational_chars_scenario_id, since these are useful to slice out
-- operational types of interest (namely hydro) and join the hydro inputs,
-- which are indexed by project-horizon.
DROP VIEW IF EXISTS project_operational_horizons;
CREATE VIEW project_operational_horizons AS
SELECT project_portfolio_scenario_id,
       project_operational_chars_scenario_id,
       project_specified_capacity_scenario_id,
       project_new_cost_scenario_id,
       temporal_scenario_id,
       operational_type,
       hydro_operational_chars_scenario_id,
       stage_id,
       project,
       balancing_type_project,
       horizon
-- Get all projects in the portfolio (with their opchars)
FROM project_portfolio_opchars
-- Add all the periods horizons for the matching balancing type
         LEFT OUTER JOIN
     periods_horizons
     ON (project_portfolio_opchars.balancing_type_project
         = periods_horizons.balancing_type_horizon)
-- Only select horizons from the actual operational periods
         INNER JOIN
     project_operational_periods
     USING (temporal_scenario_id, project, period)
;

-- This view shows the possible operational timepoints for each project based
-- based on its operational periods (see project_operational_periods), and
-- the timepoints in the temporal subscenario (see inputs_temporal). It also
-- includes the operational type and the
-- variable_generator_profile_scenario_id, since these are useful to slice out
-- operational types of interest (namely variale generators) and join the
-- variable generator inputs which are indexed by project-timepoint.
DROP VIEW IF EXISTS project_operational_timepoints;
CREATE VIEW project_operational_timepoints AS
SELECT project_portfolio_scenario_id,
       project_operational_chars_scenario_id,
       project_specified_capacity_scenario_id,
       project_new_cost_scenario_id,
       temporal_scenario_id,
       operational_type,
       variable_generator_profile_scenario_id,
       energy_profile_scenario_id,
       energy_hrz_shaping_scenario_id,
       energy_slice_hrz_shaping_scenario_id,
       base_net_requirement_scenario_id,
       stor_exog_state_of_charge_scenario_id,
       flex_load_static_profile_scenario_id,
       subproblem_id,
       stage_id,
       project,
       timepoint
-- Get all projects in the portfolio (with their opchars)
FROM project_portfolio_opchars
-- Add all the timepoints
         CROSS JOIN
     inputs_temporal
-- Only select timepoints from the actual operational periods
         INNER JOIN
     project_operational_periods
     USING (temporal_scenario_id, project, period)
;

DROP VIEW IF EXISTS transmission_operational_timepoints;
CREATE VIEW transmission_operational_timepoints AS
SELECT transmission_portfolio_scenario_id,
       transmission_operational_chars_scenario_id,
       transmission_specified_capacity_scenario_id,
       transmission_new_cost_scenario_id,
       temporal_scenario_id,
       operational_type,
       subproblem_id,
       stage_id,
       transmission_line,
       timepoint
-- Get all transmissions in the portfolio (with their opchars)
FROM transmission_portfolio_opchars
-- Add all the timepoints
         CROSS JOIN
     inputs_temporal
-- Only select timepoints from the actual operational periods
         INNER JOIN
     transmission_operational_periods
     USING (temporal_scenario_id, transmission_line, period)
;

-- ratio of hrs that are (not) spinup/lookahead in each period-subproblem-stage
DROP VIEW IF EXISTS spinup_or_lookahead_ratios;
CREATE VIEW spinup_or_lookahead_ratios AS
SELECT scenario_id,
       subproblem_id,
       stage_id,
       period,
       spinup_or_lookahead,
       n_weighted_hours / n_total_hours AS fraction_of_hours_in_subproblem

FROM (SELECT scenario_id,
             subproblem_id,
             stage_id,
             period,
             spinup_or_lookahead,
             SUM(number_of_hours_in_timepoint * timepoint_weight) AS n_weighted_hours
      FROM inputs_temporal
               INNER JOIN
           (SELECT scenario_id, temporal_scenario_id FROM scenarios) as scen_tbl
           USING (temporal_scenario_id)
      GROUP BY scenario_id, subproblem_id, stage_id, period,
               spinup_or_lookahead) AS weighted_hrs_tbl

         INNER JOIN (SELECT scenario_id,
                            subproblem_id,
                            stage_id,
                            period,
                            SUM(number_of_hours_in_timepoint * timepoint_weight) AS n_total_hours
                     FROM inputs_temporal
                              INNER JOIN
                          (SELECT scenario_id, temporal_scenario_id
                           FROM scenarios) as scen_tbl
                          USING (temporal_scenario_id)
                     GROUP BY scenario_id, subproblem_id, stage_id,
                              period) AS total_tbl
                    USING (scenario_id, subproblem_id, stage_id, period)
;


-- Costs by load zone (for tx: by destination load zone)
-- Note: does not include tx deliverability costs, tuning costs and
-- violation penalties
DROP VIEW IF EXISTS results_costs_by_period_load_zone;
CREATE VIEW results_costs_by_period_load_zone AS
SELECT a.scenario_id,
       a.subproblem_id,
       a.stage_id,
       a.period,
       a.load_zone,
       a.spinup_or_lookahead,
       capacity_cost,
       variable_om_cost,
       fuel_cost,
       startup_cost,
       shutdown_cost,
       tx_capacity_cost,
       tx_hurdle_cost
FROM results_project_costs_capacity_agg AS a

         LEFT JOIN
     results_project_costs_operations_agg as b
     ON (a.scenario_id = b.scenario_id
         AND a.subproblem_id = b.subproblem_id
         AND a.stage_id = b.stage_id
         AND a.period = b.period
         AND a.load_zone = b.load_zone
         AND
         COALESCE(a.spinup_or_lookahead, 0) = COALESCE(b.spinup_or_lookahead, 0)
         )

         LEFT JOIN

     (SELECT scenario_id,
             load_zone,
             period,
             subproblem_id,
             stage_id,
             spinup_or_lookahead,
             capacity_cost AS tx_capacity_cost
      FROM results_transmission_costs_capacity_agg) AS c
     ON (a.scenario_id = c.scenario_id
         AND a.subproblem_id = c.subproblem_id
         AND a.stage_id = c.stage_id
         AND a.period = c.period
         AND a.load_zone = c.load_zone
         AND
         COALESCE(a.spinup_or_lookahead, 0) = COALESCE(c.spinup_or_lookahead, 0)
         )

         LEFT JOIN
     results_transmission_hurdle_costs_agg as d
     ON (a.scenario_id = d.scenario_id
         AND a.subproblem_id = d.subproblem_id
         AND a.stage_id = d.stage_id
         AND a.period = d.period
         AND a.load_zone = d.load_zone
         AND
         COALESCE(a.spinup_or_lookahead, 0) = COALESCE(d.spinup_or_lookahead, 0)
         )
;


-- Costs by period (not including tuning costs and violation penalties)
DROP VIEW IF EXISTS results_costs_by_period;
CREATE VIEW results_costs_by_period AS
SELECT a.scenario_id,
       a.subproblem_id,
       a.stage_id,
       a.period,
       a.spinup_or_lookahead,
       capacity_cost,
       variable_om_cost,
       fuel_cost,
       startup_cost,
       shutdown_cost,
       tx_capacity_cost,
       tx_hurdle_cost,
       deliverable_capacity_cost
FROM (SELECT scenario_id,
             subproblem_id,
             stage_id,
             period,
             spinup_or_lookahead,
             SUM(capacity_cost)    AS capacity_cost,
             SUM(variable_om_cost) AS variable_om_cost,
             SUM(fuel_cost)        AS fuel_cost,
             SUM(startup_cost)     AS startup_cost,
             SUM(shutdown_cost)    AS shutdown_cost,
             SUM(tx_capacity_cost) AS tx_capacity_cost,
             SUM(tx_hurdle_cost)   AS tx_hurdle_cost
      FROM results_costs_by_period_load_zone
      GROUP BY scenario_id, subproblem_id, stage_id, period,
               spinup_or_lookahead) AS a

         LEFT JOIN
     results_project_deliverability_groups_agg as b
     ON (a.scenario_id = b.scenario_id
         AND a.subproblem_id = b.subproblem_id
         AND a.stage_id = b.stage_id
         AND a.period = b.period
         AND a.spinup_or_lookahead = b.spinup_or_lookahead
         )
;

-------------------------------------------------------------------------------
------------------------------ User Interface ---------------------------------
-------------------------------------------------------------------------------

-- Tables for scenario-detail and scenario-new
-- TODO: is the ui_table_id needed?
DROP TABLE IF EXISTS ui_scenario_detail_table_metadata;
CREATE TABLE ui_scenario_detail_table_metadata
(
    ui_table_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    include          INTEGER,
    ui_table         VARCHAR(32) UNIQUE,
    ui_table_caption VARCHAR(64)
);

DROP TABLE IF EXISTS ui_scenario_detail_table_row_metadata;
CREATE TABLE ui_scenario_detail_table_row_metadata
(
    ui_table                              VARCHAR(32),
    ui_table_row                          VARCHAR(32),
    include                               INTEGER,
    ui_row_caption                        VARCHAR(64),
    ui_row_db_scenarios_view_column       VARCHAR(64),
    ui_row_db_subscenario_table           VARCHAR(128),
    ui_row_db_subscenario_table_id_column VARCHAR(128),
    ui_row_db_input_table                 VARCHAR(128),
    PRIMARY KEY (ui_table, ui_table_row),
    FOREIGN KEY (ui_table) REFERENCES ui_scenario_detail_table_metadata (ui_table)
);

-- Tables for scenario-results
DROP TABLE IF EXISTS ui_scenario_results_table_metadata;
CREATE TABLE ui_scenario_results_table_metadata
(
    results_table VARCHAR(64),
    include       INTEGER,
    caption       VARCHAR(64)
);

DROP TABLE IF EXISTS ui_scenario_results_plot_metadata;
CREATE TABLE ui_scenario_results_plot_metadata
(
    results_plot                                VARCHAR(64) PRIMARY KEY,
    include                                     INTEGER,
    caption                                     VARCHAR(64),
    load_zone_form_control                      INTEGER, -- select
    energy_target_zone_form_control             INTEGER, -- select
    instantaneous_penetration_zone_form_control INTEGER, -- select
    carbon_cap_zone_form_control                INTEGER, -- select
    period_form_control                         INTEGER, -- select
    horizon_form_control                        INTEGER, -- input
    start_timepoint_form_control                INTEGER, -- input
    end_timepoint_form_control                  INTEGER, -- input
    subproblem_form_control                     INTEGER, -- select
    stage_form_control                          INTEGER, -- select
    project_form_control                        INTEGER, -- select
    commit_project_form_control                 INTEGER  -- select
);

---------------------
--- VISUALIZATION ---
---------------------

-- Technology colors and plotting order
DROP TABLE IF EXISTS viz_technologies;
CREATE TABLE viz_technologies
(
    technology     VARCHAR(32),
    color          VARCHAR(32),
    plotting_order INTEGER UNIQUE,
    PRIMARY KEY (technology)
);
