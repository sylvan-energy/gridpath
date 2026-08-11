# RA Toolkit E2E: Change Log

## Data Toolkit Code Changes

### `hydro_balancing_type` parameter — new feature

Added a `--hydro_balancing_type` (`-hydro_bt`) parameter to two data toolkit
scripts, allowing users to control the balancing type used for hydro projects
(e.g., `day`, `week`, `month`).

**`data_toolkit/project/opchar/hydro/create_hydro_iteration_input_csvs.py`**
- Added `--hydro_balancing_type` argument to argparse
- When specified, filters the balancing type-horizon pairs from
  `user_defined_balancing_type_horizons` to only the requested type
- When not specified (default `None`), all balancing types are included —
  preserving existing behavior
- Threaded through `calculate_from_project_year_month_data()`, the
  multiprocessing pool wrapper, and `main()`

**`data_toolkit/project/opchar/eia860_to_project_opchar_input_csvs.py`**
- Added `--hydro_balancing_type` argument to argparse
- When specified, overrides the `balancing_type_project` column for hydro
  projects in the generated opchar CSV (e.g., setting all hydro to `month`
  instead of the default from `gridpath_balancing_type` in the key table)
- Threaded through `get_project_opchar()` and `main()`

### Pandas 2.x compatibility fix

**`data_toolkit/raw_data/pudl/pudl_to_gridpath_raw_data.py`**
- Added `.astype("int64")` casts when populating `year`, `month`,
  `day_of_month`, `hour_of_day` columns in both
  `convert_ra_toolkit_profiles_to_csv()` and
  `convert_eia930_hourly_interchange_to_csv()`
- Fixes `LossySetitemError` on pandas 2.x when overwriting these columns with
  hour-starting values

### Project aggregation to BA level

**`data_toolkit/project/project_data_filters_common.py`**
- Added `AGG_FILTER_STR = "agg_project IS NOT NULL"` for filtering to
  aggregatable projects

**`data_toolkit/project/portfolios/eia860_to_project_portfolio_input_csvs.py`**
- Changed from mixed disaggregated/aggregated project naming to all BA-level
  aggregation using `AGG_PROJECT_NAME_STR`
- Removed the separate UNION for variable gen and hydro; all projects now use
  the same aggregation path with `GROUP BY project`

**`data_toolkit/project/opchar/eia860_to_project_opchar_input_csvs.py`**
- Changed non-variable, non-hydro projects from disaggregated
  (`plant_id__generator_id`) to BA-aggregated naming, matching the portfolio
  change
- Added `GROUP BY project` to the non-variable gen query

**`data_toolkit/project/availability/eia860_to_project_availability_input_csvs.py`**
**`data_toolkit/project/capacity_specified/eia860_to_project_specified_capacity_input_csvs.py`**
**`data_toolkit/project/fixed_cost/eia860_to_project_fixed_cost_input_csvs.py`**
**`data_toolkit/project/load_zones/eia860_to_project_load_zone_input_csvs.py`**
- Updated to use BA-aggregated project naming consistent with the portfolio and
  opchar changes

**`data_toolkit/manual_adjustments.py`**
- Changed `add_battery_durations()` from disaggregated to BA-aggregated project
  naming (`DISAGG_PROJECT_NAME_STR` → `AGG_PROJECT_NAME_STR`), with
  `GROUP BY project`, consistent with the portfolio/opchar aggregation changes

**`data_toolkit/open_data_toolkit_settings_sample.csv`**
- Updated to 5-column format
  (`script,setting,value,script_true_false_arg,reverse_default_behavior`)

## New Files

### E2E settings file

**`data_toolkit/ra_toolkit_e2e_settings_sample.csv`** (new)
- Data toolkit settings file for the RA Toolkit e2e experiment
- Includes `hydro_balancing_type,month` entries for both
  `create_hydro_iteration_input_csvs` and
  `eia860_to_project_opchar_input_csvs`

### E2E scenario CSV directory

**`db/csvs_ra_toolkit_e2e/`** (new, 691 files)

All files in this directory are new. No existing test example CSVs were
modified.

**`scenarios.csv`**
- Defines two scenarios: `ra_toolkit_e2e_monte_carlo` (temporal ID 17) and
  `ra_toolkit_e2e_sync` (temporal ID 26)

**`temporal/26_ra_toolkit_full/`** (new temporal scenario, ID 26 to avoid
conflict with existing ID 19 in `csvs_test_examples`)
- `iterations.csv` — 28 subproblems: 14 weather years (2007–2020) × 2 hydro
  years (2015 driest, 2019 wettest), each with a unique availability iteration
  1–28
- `horizon_params.csv` — 365 day horizons + 12 month horizons (both with
  `circular` boundary type)
- `horizon_timepoints.csv` — day-to-timepoint and month-to-timepoint mappings
  for all 8,760 hours
- `structure.csv`, `period_params.csv`, `superperiods.csv` — standard temporal
  structure for single-period 2026 study year

**`project/opchar/1_ra_toolkit_e2e.csv`**
- `balancing_type_project` set to `month` for all 24 `gen_hydro_must_take`
  projects

**`project/opchar/hydro_operational_chars/`** — 37 hydro opchar CSVs
- 24 active projects regenerated with month-only rows:
  `0,{hydro_year},1,month,{1-12},{avg},{min},{max}`
- 13 sub-BA projects (CIPV, CISC, CISD, IPFE, IPMV, IPTV, PAID, PAUT, PAWY,
  SPPC, etc.) retain original daily format but are not in the project portfolio
  and not used by the optimizer
- Plus corresponding iteration metadata CSVs in `iterations/`

**`project/availability/exogenous_independent/`** — 179 availability CSVs
- Each file: 262,801 lines (header + 28 availability iterations × 8,760
  timepoints)
- Generated via Monte Carlo unit outage simulation

### `.gitignore`
- Added `claude_chat.py` and `claude_history.json`
