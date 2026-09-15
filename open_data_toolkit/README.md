## GridPath Data Toolkit

The GridPath Data Toolkit downloads public datasets and processes them into
GridPath input CSV files, taking advantage of the public data available in
the PUDL database maintained by Catalyst Cooperative.

GridPath can currently utilize the following open datasets:
* **Form EIA-860** (via PUDL): generator-level specific information about 
  existing and planned generators, including the EIA-860M monthly updates
* **Form EIA-930** (via PUDL): hourly operating data about the high-voltage 
  bulk electric power grid in the Lower 48 states collected from the 
  electricity balancing authorities (BAs) that operate the grid
* **EIA AEO** *Table 54 (Electric Power Projections by Electricity Market
  Module Region)* (via PUDL): fuel price forecasts
* **EIA-930A**: EIA's annual inventory of the generators each balancing
  authority operates (downloaded from EIA directly)

## Usage

The full workflow — download, convert, build the raw data database, choose
the study footprint, fleet, and aggregation settings, and generate the
GridPath input CSVs — is documented in the *GridPath Data Toolkit* chapter
of the GridPath documentation (see *The Data Toolkit Workflow* section,
built from `doc/`). In brief:

### Download data

```bash
gridpath_get_pudl_data
gridpath_get_eia930a_data
```

Downloads the per-table Parquet files for the PUDL tables GridPath uses
(to *./pudl_download* by default) and the EIA-930A generator inventory
workbook. See the *--help* menus for options. Note some of these are
relatively large files and the download process may take a few minutes
depending on your internet speed.

### Get subset of raw data for GridPath from downloaded PUDL data

```bash
gridpath_pudl_to_gridpath_raw
```

Gets a subset of the downloaded PUDL data — selecting which data vintages
to use — and converts it to the GridPath raw data CSV format.

### Process the data with the GridPath Data Toolkit

```bash
gridpath_run_data_toolkit --settings_csv PATH/TO/SETTINGS
```

Runs the steps listed in the settings CSV: building and loading the raw
data database, then generating GridPath input CSVs for the chosen
footprint, study year, and level of project aggregation.
