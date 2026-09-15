# Running the GridPath RA Toolkit End-to-End Pipeline

This guide walks through the complete process of running a resource adequacy
(RA) study using GridPath with the RA Toolkit data. The pipeline downloads
public energy data, processes it into GridPath's input format, builds a
scenario database, and solves a multi-iteration optimization that produces
reliability metrics (LOLE, LOLH, EUE).

The e2e pipeline creates two scenarios:

- **ra_toolkit_e2e_monte_carlo** — stochastic weather draws with Monte Carlo
  availability iterations
- **ra_toolkit_e2e_sync** — synchronized weather years (2007-2020) convolved
  with hydro years and availability iterations (28 subproblems total)

## Data Flow Diagram

```
  PUDL (Zenodo)                          GridLab RA Toolkit (Google Drive)
       |                                            |
       v                                            v
  gridpath_get_pudl_data                 gridpath_get_ra_toolkit_data_raw
       |                                            |
       v                                            v
  gridpath_pudl_to_gridpath_raw              (already in CSV format)
       |                                            |
       v                                            v
  ./raw_data/                                ./raw_data/
    pudl_eia860_generators.csv                 ra_toolkit_load.csv
    pudl_eiaaeo_fuel_prices.csv                ra_toolkit_hydro.csv
    pudl_ra_toolkit_var_profiles.csv
    pudl_eia930_hourly_interchange.csv
              \                                /
               \                              /
                v                            v
        files_to_import.csv (manifest)
        links raw_data/ files + user_defined_*.csv configs
        into a unified raw data set
                        |
                        v
            gridpath_run_data_toolkit
            (reads ra_toolkit_e2e_settings_sample.csv)
                        |
                        v
            db/csvs_ra_toolkit_e2e/   (691 CSV files)
              temporal/        — timepoints, horizons, iterations
              project/         — portfolios, capacity, opchar, profiles,
              |                  hydro, availability
              transmission/    — portfolios, capacity, opchar
              system_load/     — hourly load by zone
              fuels/           — fuel chars and prices
              scenarios.csv    — scenario definitions
                        |
                        v
            gridpath_create_database  →  ra_toolkit_e2e.db (empty schema)
            gridpath_load_csvs        →  ra_toolkit_e2e.db (populated)
            gridpath_load_scenarios   →  ra_toolkit_e2e.db (scenarios registered)
                        |
                        v
            gridpath_run_e2e --scenario ra_toolkit_e2e_sync --solver cbc
                        |
                        v
            Results:
              Per-subproblem dispatch and costs
              Reliability metrics: LOLE, LOLH, EUE
              Unserved energy location and timing
```

## Prerequisites

- **GridPath** installed in a conda/mamba environment with all dependencies
- **Python 3.11+** with pandas, pyomo, and solver interfaces
- **Solver**: CBC (open-source, included with Pyomo) or a commercial solver
  (Gurobi, CPLEX) for faster solves
- **Disk space**: ~10 GB (PUDL download ~4 GB, raw data ~2 GB, scenario CSVs
  ~2 GB, database ~2 GB)
- **RAM**: 2+ GB per subproblem during solve (CBC); less with commercial
  solvers
- **Internet access** for steps 1 and 3 (data downloads)

## Step-by-Step Commands

All commands should be run from the GridPath repository root directory unless
otherwise noted.

---

### Step 1: Download PUDL Data

```bash
gridpath_get_pudl_data
```

| | |
|---|---|
| **Inputs** | Internet connection; Zenodo record IDs (defaults built in) |
| **Outputs** | `./pudl_download/pudl.sqlite` (~3.5 GB) |
| | `./pudl_download/out_gridpathratoolkit__hourly_available_capacity_factor.parquet` |
| | `./pudl_download/core_eia930__hourly_interchange.parquet` |
| **Notes** | Downloads from Zenodo. Use `--pudl_download_directory` to change location. Can skip individual downloads with `--skip_pudl_sqlite_download`, `--skip_ra_toolkit_profiles_download`, `--skip_eia930_hourly_interchange_download`. |

**What this provides:**
- EIA-860 generator inventory (capacity, fuel type, location, status)
- EIA-930 hourly interchange between balancing authorities
- EIA AEO fuel price forecasts
- RA Toolkit wind/solar capacity factor profiles (as Parquet)

---

### Step 2: Extract PUDL Data to Raw CSVs

```bash
gridpath_pudl_to_gridpath_raw
```

| | |
|---|---|
| **Inputs** | `./pudl_download/pudl.sqlite` |
| | `./pudl_download/out_gridpathratoolkit__hourly_available_capacity_factor.parquet` |
| | `./pudl_download/core_eia930__hourly_interchange.parquet` |
| **Outputs** | `./raw_data/pudl_eia860_generators.csv` |
| | `./raw_data/pudl_eiaaeo_fuel_prices.csv` |
| | `./raw_data/pudl_ra_toolkit_var_profiles.csv` |
| | `./raw_data/pudl_eia930_hourly_interchange.csv` |
| **Notes** | Queries pudl.sqlite and converts Parquet files to CSV. Default EIA-860 report date is 2024-01-01. Use `--eia860_report_date` to change. Will prompt before overwriting existing files. |

---

### Step 3: Download RA Toolkit Load and Hydro Data

```bash
gridpath_get_ra_toolkit_data_raw
```

| | |
|---|---|
| **Inputs** | Internet connection (Google Drive) |
| **Outputs** | `./raw_data/ra_toolkit_load.csv` (~5.3 MB) |
| | `./raw_data/ra_toolkit_hydro.csv` (~435 KB) |
| **Notes** | These two datasets are not available through PUDL. They were created by the GridLab RA Toolkit study team. |

**What these provide:**
- **Load**: Projected 2026 hourly load profiles for WECC balancing areas across
  weather years 2006-2020 (forward-projected, not historical actuals)
- **Hydro**: Monthly hydro energy, Pmin, and Pmax as power fractions for WECC
  BA-aggregated hydro projects, years 2001-2020

---

### Step 4: Run the Data Toolkit

```bash
cd db
gridpath_run_data_toolkit --settings_csv ../data_toolkit/ra_toolkit_e2e_settings_sample.csv
```

| | |
|---|---|
| **Inputs** | `ra_toolkit_e2e_settings_sample.csv` (settings file) |
| | `./raw_data/` (6 data files from steps 2-3) |
| | `csvs_test_examples/raw_data_ra_toolkit_e2e/` (14 user-defined config files + `files_to_import.csv`) |
| **Outputs** | `./ra_toolkit_e2e.db` (intermediate data toolkit database) |
| | `./csvs_ra_toolkit_e2e/` (691 CSV files organized by subscenario) |
| **Notes** | This is the longest step. Runs ~26 sub-steps sequentially. Variable generation profile creation is parallelizable (`n_parallel_projects` setting). To run a single sub-step: `gridpath_run_data_toolkit --settings_csv ... --single_step <step_name>`. |

See [Data Toolkit Sub-Steps](#data-toolkit-sub-steps) below for the full list.

---

### Step 5: Create the Scenario Database

```bash
gridpath_create_database --database ./ra_toolkit_e2e.db
```

| | |
|---|---|
| **Inputs** | Database schema (built into GridPath) |
| **Outputs** | `./ra_toolkit_e2e.db` (empty database with schema) |
| **Notes** | Creates a fresh SQLite database with all GridPath tables. This is the *scenario* database (distinct from the data toolkit's intermediate database). |

---

### Step 6: Load CSVs into the Database

```bash
gridpath_load_csvs --database ./ra_toolkit_e2e.db --csv_location ./csvs_ra_toolkit_e2e
```

| | |
|---|---|
| **Inputs** | `./ra_toolkit_e2e.db` (empty database from step 5) |
| | `./csvs_ra_toolkit_e2e/` (691 CSV files from step 4) |
| | `./csvs_ra_toolkit_e2e/csv_structure.csv` (defines import mapping) |
| **Outputs** | `./ra_toolkit_e2e.db` (populated with all subscenario data) |
| **Notes** | Loads all temporal, project, transmission, load, and fuel data into the database. The `csv_structure.csv` file controls which CSVs map to which database tables. |

---

### Step 7: Load Scenarios

```bash
gridpath_load_scenarios --database ./ra_toolkit_e2e.db --csv_path ./csvs_ra_toolkit_e2e/scenarios.csv
```

| | |
|---|---|
| **Inputs** | `./ra_toolkit_e2e.db` (populated database from step 6) |
| | `./csvs_ra_toolkit_e2e/scenarios.csv` |
| **Outputs** | Two scenarios registered in the `scenarios` table |
| **Notes** | `scenarios.csv` defines which subscenario IDs to combine for each scenario. This step is separate from `gridpath_load_csvs` and must be run after it. |

**Scenarios created:**

| Scenario | Temporal ID | Description |
|---|---|---|
| `ra_toolkit_e2e_monte_carlo` | 17 | Stochastic weather draws |
| `ra_toolkit_e2e_sync` | 26 | Synchronized 28-subproblem run |

---

### Step 8: Run End-to-End

```bash
gridpath_run_e2e --database ./ra_toolkit_e2e.db --scenario ra_toolkit_e2e_sync --solver cbc
```

| | |
|---|---|
| **Inputs** | `./ra_toolkit_e2e.db` (database with scenarios loaded) |
| **Outputs** | `./scenarios/ra_toolkit_e2e_sync/` (results directory) |
| | Results imported back into `ra_toolkit_e2e.db` |
| **Notes** | Runs four phases: get_inputs, run_scenario, import_results, process_results. Each subproblem takes ~15-20 minutes with CBC (model build + solve). 28 subproblems total. Use `--solver gurobi` or `--solver cplex` for significantly faster solves. |

**E2E phases:**
1. **get_inputs** — extracts scenario inputs from the database into per-subproblem CSV directories
2. **run_scenario** — builds and solves the Pyomo optimization model for each subproblem
3. **import_results** — loads solution values back into the database
4. **process_results** — computes summary statistics (LOLE, LOLH, EUE)

---

## Required Files Inventory

Before running step 4 (data toolkit), the following files must be in place.

### PUDL-Derived Files (from steps 1-2)

Located in `./raw_data/`:

| File | Source | Database Table |
|---|---|---|
| `pudl_eia860_generators.csv` | EIA-860 via pudl.sqlite | `raw_data_eia860_generators` |
| `pudl_eiaaeo_fuel_prices.csv` | EIA AEO via pudl.sqlite | `raw_data_eiaaeo_fuel_prices` |
| `pudl_ra_toolkit_var_profiles.csv` | RA Toolkit Parquet via PUDL | `raw_data_project_variable_profiles` |
| `pudl_eia930_hourly_interchange.csv` | EIA-930 Parquet via PUDL | `raw_data_eia930_hourly_interchange` |

### RA Toolkit Files (from step 3)

Located in `./raw_data/`:

| File | Source | Database Table |
|---|---|---|
| `ra_toolkit_load.csv` | GridLab RA Toolkit (Google Drive) | `raw_data_system_load` |
| `ra_toolkit_hydro.csv` | GridLab RA Toolkit (Google Drive) | `raw_data_project_hydro_opchars_by_year_month` |

### User-Defined Configuration Files

Located in `db/csvs_test_examples/raw_data_ra_toolkit_e2e/`:

These files are included in the GridPath repository and define how raw data
maps to GridPath's modeling framework.

| File | Purpose |
|---|---|
| `files_to_import.csv` | Manifest linking all raw data files to database tables |
| `scenarios.csv` | Scenario definitions (subscenario ID combinations) — copied to output directory for `gridpath_load_scenarios` |
| `geographies/user_defined_baa_key.csv` | Balancing area mapping and naming |
| `project/user_defined_eia_gridpath_key.csv` | EIA prime mover/fuel to GridPath operational type mapping |
| `project/user_defined_heat_rate_curve.csv` | Generic heat rate curves by technology |
| `project/var_profiles/user_defined_var_project_units.csv` | Variable generation project unit definitions |
| `project/hydro/user_defined_hydro_years.csv` | Hydro year definitions for iteration draws |
| `project/hydro/user_defined_bt_horizons.csv` | Balancing type horizon definitions (day, week, month, year) |
| `load/user_defined_load_zone_units.csv` | Load zone unit names and mappings |
| `fuels/user_defined_generic_fuel_intensities.csv` | Default fuel emission intensities |
| `fuels/user_defined_eiaaeo_region_key.csv` | EIA AEO region to GridPath fuel mapping |
| `availability/user_defined_unit_availability_params.csv` | Forced outage rates and MTTR by technology |
| `availability/user_defined_weather_derates.csv` | Temperature-dependent capacity derates |
| `weather/user_defined_data_availability.csv` | Which weather years have data for each profile type |
| `weather/user_defined_monte_carlo_timeseries.csv` | Monte Carlo draw configuration |
| `weather/user_defined_monte_carlo_weather_bins.csv` | Weather bin definitions for stochastic draws |
| `temporal/temporal_scenarios.csv` | Temporal scenario definitions (base CSVs, iterations) |
| `temporal/iterations/iterations_sync_full.csv` | 28-subproblem iteration definitions (14 weather × 2 hydro years) |
| `temporal/base_csvs/ra_toolkit_full/` | Base temporal CSVs with day + month horizons for the full sync scenario |

---

## Data Toolkit Sub-Steps

The data toolkit (`gridpath_run_data_toolkit`) executes the following sub-steps
in order, as configured in `ra_toolkit_e2e_settings_sample.csv`:

| Step | Sub-Step | What It Produces |
|---|---|---|
| **Database** | `create_database` | Intermediate data toolkit database (`ra_toolkit_e2e.db`) |
| | `load_raw_data` | Loads all files from `files_to_import.csv` into the database |
| **Load** | `eia930_load_zone_input_csvs` | Load zone definitions with penalty costs |
| | `create_sync_load_input_csvs` | Synchronous hourly load profiles by zone |
| | `create_monte_carlo_load_input_csvs` | Stochastic load profiles |
| **Weather** | `create_monte_carlo_weather_draws` | Weather year draws for Monte Carlo iterations |
| | `create_temporal_scenarios` | Temporal scenario CSVs (timepoints, horizons, iterations) |
| **Project portfolio** | `eia860_to_project_portfolio_input_csvs` | Project list with capacity types |
| | `eia860_to_project_load_zone_input_csvs` | Project-to-load-zone assignments |
| | `eia860_to_project_specified_capacity_input_csvs` | Specified capacity by project and period |
| | `eia860_to_project_fixed_cost_input_csvs` | Fixed O&M costs by project |
| **Project opchar** | `eia860_to_project_opchar_input_csvs` | Operational characteristics (min stable level, ramp rates, etc.) |
| | `eia860_to_project_fuel_input_csvs` | Fuel type assignments |
| | `eia860_to_project_heat_rate_input_csvs` | Heat rate curves |
| **Variable gen** | `create_sync_var_gen_input_csvs` | Synchronous wind/solar profiles (by weather year) |
| | `create_monte_carlo_var_gen_input_csvs` | Stochastic wind/solar profiles |
| | `create_sync_gen_weather_derate_input_csvs` | Synchronous temperature derates |
| | `create_monte_carlo_gen_weather_derate_input_csvs` | Stochastic temperature derates |
| **Availability** | `eia860_to_project_availability_input_csvs` | Base availability parameters |
| | `create_availability_iteration_input_csvs` | Monte Carlo unit outage draws |
| **Hydro** | `create_hydro_iteration_input_csvs` | Monthly hydro energy budgets (min/avg/max power fractions) |
| **Transmission** | `eia930_to_transmission_portfolio_input_csvs` | Transmission line inventory |
| | `eia930_to_transmission_load_zone_input_csvs` | Transmission zone connections |
| | `eia930_to_transmission_specified_capacity_input_csvs` | Line transfer capacities |
| | `eia930_to_transmission_availability_input_csvs` | Line availability |
| | `eia930_to_transmission_opchar_input_csvs` | Line operational characteristics |
| **Fuels** | `eiaaeo_to_fuel_chars_input_csvs` | Fuel characteristics and emission rates |
| | `eiaaeo_fuel_price_input_csvs` | Fuel price forecasts |

---

## Key Configuration Files

### `data_toolkit/ra_toolkit_e2e_settings_sample.csv`

The master settings file that controls the data toolkit. Each row specifies a
script name, a setting name, and its value. Format:

```
script,setting,value,script_true_false_arg,reverse_default_behavior
```

Key settings include database paths, output directories, scenario IDs and
names, parallelism (`n_parallel_projects`), and the `hydro_balancing_type`
parameter (`month` for this experiment).

### `db/csvs_test_examples/raw_data_ra_toolkit_e2e/files_to_import.csv`

The manifest file that bridges external data sources with user-defined
configuration. Each row maps a CSV file to a database table:

```
import,filename,table
1,../../../raw_data/pudl_eia860_generators.csv,raw_data_eia860_generators
1,./project/user_defined_eia_gridpath_key.csv,user_defined_eia_gridpath_key
...
```

Files prefixed with `../../../raw_data/` are PUDL-derived or RA Toolkit
downloads. Files prefixed with `./` are user-defined configurations included in
the repository.

### `db/csvs_ra_toolkit_e2e/scenarios.csv`

Defines which subscenario IDs to combine for each named scenario. The file uses
a transposed format where each column after the first is a scenario:

```
optional_feature_or_subscenarios,ra_toolkit_e2e_monte_carlo,ra_toolkit_e2e_sync
temporal_scenario_id,17,26
load_scenario_id,6,6
project_portfolio_scenario_id,23,23
...
```

---

## Experiment Configuration

The `ra_toolkit_e2e_sync` scenario is configured as follows:

- **Study year**: 2026
- **Temporal resolution**: 8,760 hourly timepoints per subproblem
- **Subproblems**: 28 total
  - 14 weather years (2007-2020) x 2 hydro years (2015 driest, 2019 wettest)
  - Each subproblem has a unique availability iteration (Monte Carlo outage
    draw)
  - Weather year 2006 is excluded due to missing wind profile data
- **Horizons**: 365 day horizons + 12 month horizons (both circular)
- **Hydro balancing**: Monthly (hydro energy budgets enforced per calendar
  month, not per day)
- **Projects**: ~249 total (thermal, hydro, wind, solar, storage) aggregated
  to the balancing authority level
- **Transmission**: Inter-BA transfer lines with specified capacities
- **Load zones**: WECC balancing authorities

### Reliability Metrics

After all 28 subproblems solve, GridPath computes:

- **LOLE** (Loss of Load Expectation) — expected days per year with any
  unserved energy
- **LOLH** (Loss of Load Hours) — expected hours per year with unserved energy
- **EUE** (Expected Unserved Energy) — expected MWh per year of unserved load
- **LOLP** (Loss of Load Probability) — fraction of subproblems with any
  unserved energy
