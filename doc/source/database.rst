########
Database
########

This chapter describes the following:

* :ref:`building-the-database-section-ref`: instructions on how to build the
  database
* :ref:`db-structure-section-ref`: the structure of the database and its
  associated tables
* :ref:`gridpath-input-data-section-ref`: details on the various types of input data that can be loaded into the database
* :ref:`database-testing-section-ref`: instructions on how to validate the database inputs


.. _building-the-database-section-ref:

Building the Database
#####################

*********************
Creating the Database
*********************

.. automodule:: db.create_database

***********************
Populating the Database
***********************

Example Input Data
******************
For the purposes of this section, you may use the example CSV files provided
in the :code:`gridpath/db/csvs_test_examples` folder. Please ensure that you
download the CSV files from the same version of GridPath that you are using,
as the database structure may change between versions. Find your version of
GridPath `here <https://github.com/blue-marble/gridpath/releases>`_, download the
source code for your version, and copy the contents of the
:code:`gridpath/db/csvs_test_examples` folder to your local machine. You can
then point the GridPath database-building tools to this directory
(PATH/DO/DB). See the :ref:`db-structure-section-ref` and
:ref:`gridpath-input-data-section-ref` for an explanation of the database
structure and its tables.

Loading Input Data
******************

.. automodule:: db.utilities.port_csvs_to_db

Creating Scenarios
******************

.. automodule:: db.utilities.scenario

.. _db-structure-section-ref:

Database Structure
##################

The database consists of a set of tables that store input data for GridPath
scenarios. Each table has a specific structure and set of required and
optional fields. The database also contains tables that store metadata about the
scenarios, such as the list of subscenarios that make up a scenario and the
features that are enabled for a scenario.

.. automodule:: db.doc

.. _gridpath-input-data-section-ref:

GridPath Input Data
###################

A minimal set of inputs for a GridPath scenario would generally includes
temporal inputs, load zone inputs, system load inputs, a project portfolio 
and load zones, and project operating characteristics. You can look for the 
inputs labeled as
*core* in the csv_structure.csv file in *db/csvs_test_examples*.

***************
Temporal Inputs
***************

.. automodule:: db.csvs_test_examples.temporal.doc

****************
Load Zone Inputs
****************

.. automodule:: db.csvs_test_examples.system_load.load_zones.doc

***********
System Load
***********

.. automodule:: db.csvs_test_examples.system_load.system_load.doc

**************
Project Inputs
**************

Generator and storage resources in GridPath are called *projects*. Each
project can be assigned different characteristics depending on the scenario,
whether its geographic location, ability to contribute to reserve or policy
requirements, its capacity and operating characteristics. You can optionally
import all projects that may be part of a scenario in the
:code:`inputs_project_all` table of the GridPath database.

.. _project-geography-section-ref:

Project Geography
*****************

.. automodule:: db.csvs_test_examples.project.load_zones.doc


.. _project-portfolio-section-ref:

Project Portfolio
*****************

.. automodule:: db.csvs_test_examples.project.portfolios.doc


Specified Projects
******************

.. _specified-project-capacity-section-ref:


========
Capacity
========

.. automodule:: db.csvs_test_examples.project.capacity.specified_capacity.doc

.. _specified-project-fixed-cost-section-ref:

===========
Fixed Costs
===========

.. automodule:: db.csvs_test_examples.project.capacity.specified_fixed_cost.doc

New Projects
************

=============
Capital Costs
=============

.. automodule:: db.csvs_test_examples.project.capacity.new_cost.doc

.. _new-project-potential-section-ref:

=========
Potential
=========

.. automodule:: db.csvs_test_examples.project.capacity.new_potential.doc


Project Availability
********************

=========
Exogenous
=========

.. automodule:: db.csvs_test_examples.project.availability.exogenous_independent.doc

==========
Endogenous
==========

.. automodule:: db.csvs_test_examples.project.availability.endogenous.doc


Project Operational Characteristics
***********************************

.. automodule:: db.csvs_test_examples.project.opchar.doc

==========
Heat Rates
==========

.. automodule:: db.csvs_test_examples.project.opchar.heat_rate_curves.doc

===========================
Variable Generator Profiles 
===========================

.. automodule:: db.csvs_test_examples.project.opchar.variable_generator_profiles.doc

=================================
Hydro Operational Characteristics 
=================================

.. automodule:: db.csvs_test_examples.project.opchar.hydro_operational_chars.doc

=====================
Opchar Timepoint Maps
=====================

.. automodule:: db.csvs_test_examples.project.opchar.timepoint_maps.doc

===================
Opchar Horizon Maps
===================

.. automodule:: db.csvs_test_examples.project.opchar.horizon_maps.doc

*******************
Transmission Inputs
*******************

Optional inputs needed if transmission feature is enabled for a scenario.

Transmission Portfolio
**********************

.. automodule:: db.csvs_test_examples.transmission.portfolios.doc

Transmission Topography
***********************

.. automodule:: db.csvs_test_examples.transmission.load_zones.doc

Specified Transmission
**********************

========
Capacity
========

.. automodule:: db.csvs_test_examples.transmission.capacity.specified_capacity.doc

New Transmission
****************

=============
Capital Costs
=============

.. automodule:: db.csvs_test_examples.transmission.capacity.new_cost.doc

Transmission Operational Characteristics
****************************************

.. automodule:: db.csvs_test_examples.transmission.opchar.doc


***********
Fuel Inputs
***********

Fuel Characteristics
********************

.. automodule:: db.csvs_test_examples.fuels.fuel_chars.doc


Fuel Prices
***********

.. automodule:: db.csvs_test_examples.fuels.fuel_prices.doc

********
Reserves
********

Regulation Up
*************

===============
Balancing Areas
===============

.. automodule:: db.csvs_test_examples.reserves.regulation_up.geography_regulation_up_bas.doc

=====================
Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.reserves.regulation_up.project_regulation_up_bas.doc

===========
Requirement
===========

.. automodule:: db.csvs_test_examples.reserves.regulation_up.req.doc

Regulation Down
***************

===============
Balancing Areas
===============

.. automodule:: db.csvs_test_examples.reserves.regulation_down.geography_regulation_down_bas.doc

=====================
Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.reserves.regulation_down.project_regulation_down_bas.doc

===========
Requirement
===========

.. automodule:: db.csvs_test_examples.reserves.regulation_down.req.doc


Spinning Reserves
*****************

===============
Balancing Areas
===============

.. automodule:: db.csvs_test_examples.reserves.spinning_reserves.geography_spinning_reserves_bas.doc


=====================
Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.reserves.spinning_reserves.project_spinning_reserves_bas.doc


===========
Requirement
===========

.. automodule:: db.csvs_test_examples.reserves.spinning_reserves.req.doc


Inertia Reserves
****************

===============
Balancing Areas
===============

.. automodule:: db.csvs_test_examples.reserves.inertia_reserves.geography_inertia_reserves_bas.doc


=====================
Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.reserves.inertia_reserves.project_inertia_reserves_bas.doc


===========
Requirement
===========

.. automodule:: db.csvs_test_examples.reserves.inertia_reserves.req.doc


Load-Following Reserves Up
**************************

===============
Balancing Areas
===============

.. automodule:: db.csvs_test_examples.reserves.lf_reserves_up.geography_lf_reserves_up_bas.doc

=====================
Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.reserves.lf_reserves_up.project_lf_reserves_up_bas.doc

===========
Requirement
===========

.. automodule:: db.csvs_test_examples.reserves.lf_reserves_up.req.doc


Load-Following Reserves Down
****************************

===============
Balancing Areas
===============

.. automodule:: db.csvs_test_examples.reserves.lf_reserves_down.geography_lf_reserves_down_bas.doc

=====================
Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.reserves.lf_reserves_down.project_lf_reserves_down_bas.doc

===========
Requirement
===========

.. automodule:: db.csvs_test_examples.reserves.lf_reserves_down.req.doc



Frequency Response Reserves
***************************

===============
Balancing Areas
===============

.. automodule:: db.csvs_test_examples.reserves.frequency_response.geography_frequency_response_bas.doc

=====================
Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.reserves.frequency_response.project_frequency_response_bas.doc

===========
Requirement
===========

.. automodule:: db.csvs_test_examples.reserves.frequency_response.req.doc



Policy 
******

========================================================
Energy Targets, e.g. Renewables Portfolio Standard (RPS)
========================================================

Policy Zones
============

.. automodule:: db.csvs_test_examples.policy.energy_targets.zones.doc

Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.policy.energy_targets.project_zones.doc

Target
======

.. automodule:: db.csvs_test_examples.policy.energy_targets.period_targets.doc

==========
Carbon Cap
==========

Policy Zones
============

.. automodule:: db.csvs_test_examples.policy.carbon_cap.geography_carbon_cap_zones.doc

Contributing Projects
=====================

.. automodule:: db.csvs_test_examples.policy.carbon_cap.project_carbon_cap_zones.doc

Target
======

.. automodule:: db.csvs_test_examples.policy.carbon_cap.system_carbon_cap_targets.doc

.. _database-testing-section-ref:

Database Input Validation
#########################

Once you have built the database with a set of scenarios and associated inputs,
you can test the inputs for a given scenario by running the inputs validation
suite. This suite will extract the inputs for the scenario of interest and
check whether the inputs are valid. A few examples of invalid inputs are:

 - required inputs are missing
 - inputs are the wrong datatype or not in the expected range
 - inputs are inconsistent with a related set of inputs
 - inputs are provided but not used

After the validation is finished, any encountered input validations are dumped
into the :code:`status_validation` table. This table contains the following
columns:

 - :code:`scenario_id`: the scenario ID of the scenario that is validated.
 - :code:`subproblem_id`: the subproblem ID of the subproblem that is
   validated (the validation suite validates each subproblem separately).
 - :code:`stage_id`: the stage ID of the stage that is validated (the
   validation suite validates each stage separately).
 - :code:`gridpath_module`: the GridPath module that returned the validation
   error.
 - :code:`related_subscenario`: the subscenario that is related to the
   validation error.
 - :code:`related_database_table`: the database table that likely contains
   the validation error.
 - :code:`issue_severity`: the severity of the validation error. "High"
   means the model won't be able to run. "Mid" means the model might run, but
   the results will likely be unexpected. "Low" means the model should run and
   the results are likely as expected, but there are some inconsistencies
   between the inputs.
 - :code:`issue_type`: a short description of the type of validation error.
 - :code:`issue_description`: a detailed description of the validation error.
 - :code:`timestamp`: lists the exact time when the validation error
   encountered.

To run the validation suite from the command line, navigate to the
:code:`gridpath/gridpath` folder and type::

    validate_inputs.py --scenario SCENARIO_NAME --database PATH/TO/DATABASE



Note that the input validation suite is not exhaustive and does not catch
every possible input error. As we continue to develop and use GridPath, we
expect that the set of validation tests will expand and cover more and more
of the common input errors.
