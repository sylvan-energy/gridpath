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

Using the GridPath Data Toolkit
###############################

The various functionalities available in the GridPath Data Toolkit can be
accessed via the ``gridpath_run_data_toolkit`` command. See the ``--help``
menu for the available individual Toolkit steps. You may run individual steps
only or list the steps you want to run with their respective arguments in a
settings file you can point to with the ``--settings_csv`` argument.
Descriptions of the individual steps available in the Toolkit are below.

The steps that generate stochastic, resource-adequacy-style inputs —
temporal scenarios from weather draws, synchronous or Monte Carlo load,
variable generation, and generator weather-derate profiles, hydro
conditions, and thermal-outage availability iterations — are part of the
GridPath RA Toolkit package and are documented on the :doc:`ra_toolkit`
page. They run from the RA Toolkit's own ``gridpath_run_ra_toolkit``
command and settings CSV, against the RA Toolkit's own raw data database.

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

**************
Project Inputs
**************

.. automodule:: data_toolkit.project.portfolios.eia860_to_project_portfolio_input_csvs
.. automodule:: data_toolkit.project.load_zones.eia860_to_project_load_zone_input_csvs
.. automodule:: data_toolkit.project.availability.eia860_to_project_availability_input_csvs
.. automodule:: data_toolkit.project.capacity_specified.eia860_to_project_specified_capacity_input_csvs
.. automodule:: data_toolkit.project.fixed_cost.eia860_to_project_fixed_cost_input_csvs
.. automodule:: data_toolkit.project.opchar.eia860_to_project_opchar_input_csvs
.. automodule:: data_toolkit.project.opchar.fuels.eia860_to_project_fuel_input_csvs
.. automodule:: data_toolkit.project.opchar.heat_rates.eia860_to_project_heat_rate_input_csvs


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
