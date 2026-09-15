## GridPath RA Toolkit

The GridPath RA Toolkit generates GridPath scenario inputs for resource
adequacy studies: temporal scenarios built from weather draws, load
profiles, variable generation profiles, weather-dependent generator
derates, hydro conditions, and thermal-outage availability iterations —
in synchronous (historical weather years used directly) or Monte Carlo
(draws assembled from weather bins) flavors where applicable.

Its steps run from the same `gridpath_run_data_toolkit` command — and, if
desired, the same settings CSV — as the GridPath Data Toolkit steps (see
*open_data_toolkit/README.md*), and work off the raw data database built with
the Data Toolkit's `create_database` and `load_raw_data` steps.

Not to be confused with the [GridPath RA Toolkit
datasets](https://gridlab.org/gridpathratoolkit/) developed in 2021 for the 2026
Western US resource adequacy study — those are input data, not this
software package.

### Generate the input CSVs

```bash
gridpath_run_data_toolkit --settings_csv PATH/TO/SETTINGS
```

See the *GridPath RA Toolkit* section of the GridPath documentation for
the available steps and their settings.
