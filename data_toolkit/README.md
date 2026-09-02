## GridPath Data Toolkit

This is a pre-release of the GridPath Data Toolkit. The Toolkit includes 
previously available functionality from the GridPath RA Data Toolkit that 
generates GridPath input CSV files for use in resource adequacy studies, 
including weather-dependent load profiles as well as wind and solar profiles,
generator availabilities, and hydro conditions. New functionality takes 
advantage of the public data available in the PUDL database maintained by 
Catalyst Cooperative.

GridPath can currently utilize the following open datasets available from PUDL:
* **Form EIA-860**: generator-level specific information about existing and 
planned generators
* **Form EIA-930**: hourly operating data about the high-voltage bulk electric 
  power grid in the Lower 48 states collected from the electricity balancing authorities (BAs) that operate the grid
* **EIA AEO** *Table 54 (Electric Power Projections by Electricity Market 
  Module Region)*: fuel price forecasts
* **GridPath RA Toolkit** variable generation profiles created for the 2026 
  Western RA Study: these include hourly wind profiles by WECC BA based on 
  assumed 2026 wind buildout for weather years 2007-2014 and hourly solar 
  profiles by WECC BA based on assumed 2026 buildout (as of 2021) for weather 
  years 1998-2019

## Usage
### Download data from PUDL

```bash
gridpath_get_pudl_data
```
Downloads data to *./pudl_download* by default.
This will download the *pudl.sqlite* database as well as the RA Toolkit 
wind and solar profiles Parquet file, and the EIA930 hourly interchange 
data Parquet file. See *--help* menu for options. Note these are relatively 
large files and the download process may take a few minutes depending on 
your internet speed.

### Get subset of raw data for GridPath from downloaded PUDL data

```bash
gridpath_pudl_to_gridpath_raw
```
Gets subset of the downloaded PUDL data and converts it to GridPath raw data format.
This will create the following files in the user-specified raw data directory:
* pudl_eia860_generators.csv
* pudl_eia930_hourly_interchange.csv
* pudl_eiaaeo_fuel_prices.csv
* pudl_ra_toolkit_var_profiles.csv

### Process the data with the GridPath Data Toolkit

```bash
gridpath_run_data_toolkit --settings_csv PATH/TO/SETTINGS
```

See the *Using the GridPath Data Toolkit* section of the GridPath documentation.
