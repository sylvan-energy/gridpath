###################
GridPath RA Toolkit
###################

.. automodule:: ra_toolkit

Obtaining Raw Data
##################

.. automodule:: ra_toolkit.raw_data
.. automodule:: ra_toolkit.raw_data.get_ra_toolkit_data


Using the GridPath RA Toolkit
#############################

RA Toolkit steps run from the same ``gridpath_run_data_toolkit`` command —
and, if desired, the same settings CSV — as the GridPath Data Toolkit
steps (see :doc:`data_toolkit`). They work off the raw data database built
with the Data Toolkit: create it and load the RA-related raw data (system
load, unit-level variable generation and availability profiles, hydro
conditions, unit availability parameters, and the user-defined weather
bins and unit mappings) with the Data Toolkit's ``create_database`` and
``load_raw_data`` steps before running the steps below.

Note that the RA Toolkit steps take their project names from user-provided
mapping tables (e.g. ``raw_data_var_project_units``,
``user_defined_load_zone_units``) rather than from the Data Toolkit's
EIA860-based project selection. When combining RA Toolkit inputs with
Data-Toolkit-generated project inputs in one scenario, those mappings must
use the same project and load zone names the Data Toolkit run generated.

***************
Temporal Inputs
***************

.. automodule:: ra_toolkit.temporal.create_monte_carlo_weather_draws
.. automodule:: ra_toolkit.temporal.create_temporal_scenarios

***********
Load Inputs
***********

.. automodule:: ra_toolkit.load.create_sync_load_input_csvs
.. automodule:: ra_toolkit.load.create_monte_carlo_load_input_csvs

**************
Project Inputs
**************

.. automodule:: ra_toolkit.project.stochastic
.. automodule:: ra_toolkit.project.opchar.var_profiles.create_sync_var_gen_input_csvs
.. automodule:: ra_toolkit.project.opchar.var_profiles.create_monte_carlo_var_gen_input_csvs
.. automodule:: ra_toolkit.project.availability.weather_derates.create_sync_gen_weather_derate_input_csvs
.. automodule:: ra_toolkit.project.availability.weather_derates.create_monte_carlo_gen_weather_derate_input_csvs
.. automodule:: ra_toolkit.project.availability.outages.create_availability_iteration_input_csvs
.. automodule:: ra_toolkit.project.opchar.hydro.create_hydro_iteration_input_csvs
