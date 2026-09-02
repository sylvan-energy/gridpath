"""
The **GridPath RA Toolkit** package generates GridPath scenario inputs for
resource-adequacy-style stochastic modeling: temporal scenarios built from
weather draws, load profiles, variable generation profiles,
weather-dependent generator derates, hydro conditions, and thermal-outage
availability iterations — each in synchronous (historical weather years
used directly) or Monte Carlo (draws assembled from weather bins) flavors
where applicable. It works off its own raw data database (created from
``ra_toolkit/raw_data_db_schema.sql`` and loaded with the RA Toolkit's
``load_raw_data`` step), separate from the GridPath Data Toolkit's raw
database, and its steps run from their own settings CSV via the
``gridpath_run_ra_toolkit`` command (see :mod:`data_toolkit` for the Data
Toolkit's counterpart).

Not to be confused with the `GridPath RA Toolkit
<https://gridlab.org/gridpathratoolkit/>`__ *datasets*, developed to
support the 2026 Western US resource adequacy study — those are input
data (one possible source for this package's raw tables, provided by the
user via the ``load_raw_data`` manifest), not this software package.
"""
