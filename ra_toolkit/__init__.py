"""
The **GridPath RA Toolkit** package generates GridPath scenario inputs for
resource-adequacy-style stochastic modeling: temporal scenarios built from
weather draws, load profiles, variable generation profiles,
weather-dependent generator derates, hydro conditions, and thermal-outage
availability iterations — each in synchronous (historical weather years
used directly) or Monte Carlo (draws assembled from weather bins) flavors
where applicable. It works off the raw data database built with the
GridPath Data Toolkit (see :mod:`data_toolkit`), and its steps run from
the same ``gridpath_run_data_toolkit`` settings CSV as the Data Toolkit
steps.

Not to be confused with the `GridPath RA Toolkit
<https://gridlab.org/gridpathratoolkit/>`__ *datasets*, developed to
support the 2026 Western US resource adequacy study — those are input
data this package (and PUDL) can download, not this software package.
"""
