#####################
GridPath Data Toolkit
#####################

.. automodule:: data_toolkit

Obtaining Raw Data
##################

****
PUDL
****
.. automodule:: data_toolkit.raw_data.pudl

Download Datasets
*****************
.. automodule:: data_toolkit.raw_data.pudl.download_data_from_pudl

Convert to GridPath Raw Format
******************************
.. automodule:: data_toolkit.raw_data.pudl.pudl_to_gridpath_raw_data

*******************
GridPath RA Toolkit
*******************
.. automodule:: data_toolkit.raw_data.ra_toolkit
.. automodule:: data_toolkit.raw_data.ra_toolkit.get_ra_toolkit_data


Using the GridPath Data Toolkit
###############################

The various functionalities available in the GridPath Data Toolkit can be
accessed via the ``gridpath_run_data_toolkit`` command. See the ``--help``
menu for the available individual Toolkit steps. You may run individual steps
only or list the steps you want to run with their respective arguments in a
settings file you can point to with the ``--settings_csv`` argument.
Descriptions of the individual steps available in the Toolkit are below.

******************************
Building the Raw Data Database
******************************

The first step in using the GridPath Data Toolkit is to create a raw data
database. You may do so with the following command:

>>> gridpath_run_data_toolkit --single_step create_database --database PATH/TO/RAW/DB --db_schema PATH/TO/GRIDPATH/data_toolkit/raw_data_db_schema.sql --omit_data


****************
Loading Raw Data
****************

.. automodule:: data_toolkit.load_raw_data


****************
Load Zone Inputs
****************

.. automodule:: data_toolkit.system.eia930_load_zone_input_csvs

***************
Temporal Inputs
***************

.. automodule:: data_toolkit.temporal.create_monte_carlo_weather_draws
.. automodule:: data_toolkit.temporal.create_temporal_scenarios

***********
Load Inputs
***********

.. automodule:: data_toolkit.system.create_sync_load_input_csvs
.. automodule:: data_toolkit.system.create_monte_carlo_load_input_csvs

**************
Project Inputs
**************

.. automodule:: data_toolkit.project.portfolios.eia860_to_project_portfolio_input_csvs
.. automodule:: data_toolkit.project.load_zones.eia860_to_project_load_zone_input_csvs
.. automodule:: data_toolkit.project.availability.eia860_to_project_availability_input_csvs
.. automodule:: data_toolkit.project.availability.outages.create_availability_iteration_input_csvs
.. automodule:: data_toolkit.project.availability.weather_derates.create_sync_gen_weather_derate_input_csvs
.. automodule:: data_toolkit.project.availability.weather_derates.create_monte_carlo_gen_weather_derate_input_csvs
.. automodule:: data_toolkit.project.capacity_specified.eia860_to_project_specified_capacity_input_csvs
.. automodule:: data_toolkit.project.fixed_cost.eia860_to_project_fixed_cost_input_csvs
.. automodule:: data_toolkit.project.opchar.eia860_to_project_opchar_input_csvs
.. automodule:: data_toolkit.project.opchar.fuels.eia860_to_project_fuel_input_csvs
.. automodule:: data_toolkit.project.opchar.heat_rates.eia860_to_project_heat_rate_input_csvs
.. automodule:: data_toolkit.project.opchar.var_profiles.create_sync_var_gen_input_csvs
.. automodule:: data_toolkit.project.opchar.var_profiles.create_monte_carlo_var_gen_input_csvs
.. automodule:: data_toolkit.project.opchar.hydro.create_hydro_iteration_input_csvs


***********
Fuel Inputs
***********
.. automodule:: data_toolkit.fuels.eiaaeo_to_fuel_chars_input_csvs
.. automodule:: data_toolkit.fuels.eiaaeo_fuel_price_input_csvs


*******************
Transmission Inputs
*******************

.. automodule:: data_toolkit.transmission.portfolios.eia930_to_transmission_portfolio_input_csvs
.. automodule:: data_toolkit.transmission.load_zones.eia930_to_transmission_load_zone_input_csvs
.. automodule:: data_toolkit.transmission.availability.eia930_to_transmission_availability_input_csvs
.. automodule:: data_toolkit.transmission.capacity_specified.eia930_to_transmission_specified_capacity_input_csvs
.. automodule:: data_toolkit.transmission.opchar.eia930_to_transmission_opchar_input_csvs
