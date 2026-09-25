#################################
GridPath Functionality - Advanced
#################################

This section contains the advanced documentation that is automatically generated
from the documentation within each GridPath module.


******************
Core Functionality
******************

This chapter describes GridPath's basic functionality if no optional
features are included.

Temporal Setup
==============

gridpath.temporal
-----------------
.. automodule:: gridpath.temporal.__init__

gridpath.temporal.operations
----------------------------
.. automodule:: gridpath.temporal.operations.__init__

gridpath.temporal.operations.timepoints
---------------------------------------

Refer :ref:`timepoints-sub-section-ref`.

.. currentmodule:: gridpath.temporal.operations.timepoints
.. autofunction:: add_model_components

gridpath.temporal.operations.horizons
-------------------------------------

Refer :ref:`horizons-sub-section-ref`.

.. currentmodule:: gridpath.temporal.operations.horizons
.. autofunction:: add_model_components

gridpath.temporal.investment
----------------------------
.. automodule:: gridpath.temporal.investment.__init__

gridpath.temporal.investment.periods
------------------------------------

Refer :ref:`periods-sub-section-ref`.

.. currentmodule:: gridpath.temporal.investment.periods
.. autofunction:: add_model_components


Geographic Setup
================
.. automodule:: gridpath.geography.__init__

gridpath.geography.load_zones
-----------------------------
.. automodule:: gridpath.geography.load_zones
    :members: add_model_components

Projects
========

gridpath.project.__init__
-------------------------
.. automodule:: gridpath.project.__init__
    :members: add_model_components

Project Capacity
----------------

gridpath.project.capacity
^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.__init__

gridpath.project.capacity.capacity
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity
    :members: add_model_components

gridpath.project.capacity.costs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.costs
    :members: add_model_components

gridpath.project.capacity.capacity_types
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.__init__

gridpath.project.capacity.capacity_types.gen_spec
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.gen_spec.add_model_components

gridpath.project.capacity.capacity_types.gen_new_lin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.gen_new_lin.add_model_components

gridpath.project.capacity.capacity_types.gen_new_bin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.gen_new_bin.add_model_components

gridpath.project.capacity.capacity_types.gen_ret_lin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.gen_ret_lin.add_model_components

gridpath.project.capacity.capacity_types.gen_ret_bin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.gen_ret_bin.add_model_components

gridpath.project.capacity.capacity_types.stor_spec
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.stor_spec.add_model_components

gridpath.project.capacity.capacity_types.stor_new_lin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.stor_new_lin.add_model_components

gridpath.project.capacity.capacity_types.stor_new_bin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.stor_new_bin.add_model_components

gridpath.project.capacity.capacity_types.gen_stor_hyb_spec
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.gen_stor_hyb_spec.add_model_components

gridpath.project.capacity.capacity_types.dr_new
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.capacity.capacity_types.dr_new.add_model_components

Project Availability
--------------------

gridpath.project.availability.availability
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.availability.availability

gridpath.project.availability.availability_types.exogenous
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.availability.availability_types.exogenous.add_model_components

gridpath.project.availability.availability_types.binary
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.availability.availability_types.binary.add_model_components

gridpath.project.availability.availability_types.continuous
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.availability.availability_types.continuous.add_model_components

Project Operations
------------------

gridpath.project.operations
^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.__init__

gridpath.project.operations.power
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.power
    :members: add_model_components

gridpath.project.operations.costs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.costs
    :members: add_model_components

gridpath.project.operations.carbon_emissions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.carbon_emissions
    :members: add_model_components

gridpath.project.operations.carbon_tax
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.carbon_tax
    :members: add_model_components

gridpath.project.operations.fuel_burn
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.fuel_burn
    :members: add_model_components

gridpath.project.operations.cycle_select
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.cycle_select
    :members: add_model_components

gridpath.project.operations.supplemental_firing
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.supplemental_firing
    :members: add_model_components

gridpath.project.operations.energy_target_contributions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.energy_target_contributions
    :members: add_model_components

gridpath.project.operations.performance_standard
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.performance_standard
    :members: add_model_components

gridpath.project.operations.cap_factor_limits
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.cap_factor_limits
    :members: add_model_components

gridpath.project.operations.tuning_costs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.tuning_costs
    :members: add_model_components

gridpath.project.capacity.operational_types.gen_simple
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_simple.add_model_components

gridpath.project.capacity.operational_types.gen_must_run
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_must_run.add_model_components

gridpath.project.capacity.operational_types.gen_simple_strike_price
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_simple_strike_price.add_model_components

gridpath.project.capacity.operational_types.gen_always_on
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_always_on.add_model_components

gridpath.project.capacity.operational_types.gen_commit_bin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_commit_bin.add_model_components

gridpath.project.capacity.operational_types.gen_commit_lin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_commit_lin.add_model_components

gridpath.project.capacity.operational_types.gen_commit_unit_common
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_commit_unit_common.add_model_components

gridpath.project.capacity.operational_types.gen_commit_cap
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_commit_cap.add_model_components

gridpath.project.capacity.operational_types.gen_hydro
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_hydro.add_model_components

gridpath.project.capacity.operational_types.gen_hydro_must_take
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_hydro_must_take.add_model_components

gridpath.project.capacity.operational_types.gen_var
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_var.add_model_components

gridpath.project.capacity.operational_types.gen_var_must_take
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_var_must_take.add_model_components

gridpath.project.capacity.operational_types.stor
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.stor.add_model_components

gridpath.project.capacity.operational_types.gen_var_stor_hyb
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.gen_var_stor_hyb.add_model_components

gridpath.project.capacity.operational_types.dr
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.dr.add_model_components

gridpath.project.capacity.operational_types.dispatchable_load
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.project.operations.operational_types.dispatchable_load.add_model_components

Load Balance
============

gridpath.system.load_balance.static_load_requirement
----------------------------------------------------
.. automodule:: gridpath.system.load_balance.static_load_requirement
    :members: add_model_components

gridpath.system.load_balance.aggregate_project_power
----------------------------------------------------
.. automodule:: gridpath.system.load_balance.aggregate_project_power
    :members: add_model_components

gridpath.system.load_balance.load_balance
-----------------------------------------

Refer :ref:`load-balance-section-ref`.

.. currentmodule:: gridpath.system.load_balance.load_balance
.. autofunction:: add_model_components


Objective Function
==================
.. automodule:: gridpath.objective.__init__

.. automodule:: gridpath.objective.project.__init__

.. automodule:: gridpath.objective.system.__init__

gridpath.objective.project.aggregate_capacity_costs
---------------------------------------------------
.. automodule:: gridpath.objective.project.aggregate_capacity_costs
    :members: add_model_components

gridpath.objective.project.aggregate_operational_costs
------------------------------------------------------
.. automodule:: gridpath.objective.project.aggregate_operational_costs
    :members: add_model_components

gridpath.objective.system.aggregate_load_balance_penalties
----------------------------------------------------------
.. automodule:: gridpath.objective.system.aggregate_load_balance_penalties
    :members: add_model_components

gridpath.objective.max_npv
---------------------------------

Refer :ref:`objective-section-ref`.

.. currentmodule:: gridpath.objective.max_npv
.. autofunction:: add_model_components



**********************
Advanced Functionality
**********************

This section describes GridPath's advanced functionality that can be included
by selecting optional features.

Multi-Stage
============
.. automodule:: gridpath.project.operations.fix_commitment
    :members: add_model_components, fix_variables, export_pass_through_inputs


Transmission
============

gridpath.transmission
---------------------
.. automodule:: gridpath.transmission.__init__

gridpath.transmission.capacity.capacity_types
---------------------------------------------
.. automodule:: gridpath.transmission.capacity.capacity_types

gridpath.transmission.capacity.capacity_types.tx_spec
-----------------------------------------------------
.. automodule:: gridpath.transmission.capacity.capacity_types.tx_spec.add_model_components

gridpath.transmission.capacity.capacity_types.tx_new_lin
---------------------------------------------------------
.. automodule:: gridpath.transmission.capacity.capacity_types.tx_new_lin.add_model_components

gridpath.transmission.capacity.capacity
---------------------------------------
.. automodule:: gridpath.transmission.capacity.capacity

gridpath.transmission.operations.operational_types
--------------------------------------------------
.. automodule:: gridpath.transmission.operations.operational_types

gridpath.transmission.operations.operational_types.tx_simple
------------------------------------------------------------
.. automodule:: gridpath.transmission.operations.operational_types.tx_simple.add_model_components

gridpath.transmission.operations.operational_types.tx_dcopf
-----------------------------------------------------------
.. automodule:: gridpath.transmission.operations.operational_types.tx_dcopf.add_model_components

gridpath.transmission.operations.operations
-------------------------------------------
.. automodule:: gridpath.transmission.operations.operations

gridpath.system.load_balance.aggregate_transmission_power
---------------------------------------------------------
.. automodule:: gridpath.system.load_balance.aggregate_transmission_power

Transmission Hurdle Rates
-------------------------
If the transmission hurdle rates feature is enabled, the following modules
are also included:

gridpath.transmission.operations.hurdle_costs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.transmission.operations.hurdle_costs

gridpath.objective.transmission.aggregate_hurdle_costs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. automodule:: gridpath.objective.transmission.aggregate_hurdle_costs


Operating Reserves
==================
GridPath can model operating reserve requirements and provision. Reserves
currently modeled (none, any, or all can be selected, as they are additive
in the model) include regulation up and down, spinning reserves,
load-following up and down, frequency response, and inertia reserves.

The treatment of operating reserves is standardized. It requires defining
the reserve balancing areas with their associated parameters and setting
the reserve requirements by balancing area and timepoint; we must
also assign a balancing area to each project that can provide the reserve;
the model then takes care of creating the appropriate project-level
reserve-provision variables, aggregates the provision of reserves, and
ensures that total provision of the reserve and the reserve requirement are
balanced (or that penalties are applied if not).

Modules from each reserve feature call on standardized methods included in
other GridPath modules. The standard methods are included in the following
modules:

gridpath.project.operations.reserves.reserve_provision
------------------------------------------------------

.. automodule:: gridpath.project.operations.reserves.reserve_provision
    :members: generic_record_dynamic_components


Reliability
===========
GridPath currently includes the ability to require that a planning reserve
requirement be met. Projects can contribute toward the reserve requirement via a
simple fraction of their installed capacity or an "ELCC surface" that takes into
account declining marginal contributions and/or portfolio effects with other projects.
GridPath can also account for "deliverability," i.e., lower capacity contributions
due to transmission limits.

gridpath.project.reliability.prm.prm_simple
-------------------------------------------

.. automodule:: gridpath.project.reliability.prm.prm_simple

gridpath.project.reliability.prm.elcc_surface
---------------------------------------------

.. automodule:: gridpath.project.reliability.prm.elcc_surface

gridpath.system.reliability.prm.elcc_surface
--------------------------------------------

.. automodule:: gridpath.system.reliability.prm.elcc_surface

Policy
======

GridPath includes the ability to model certain policies, e.g. a renewable
portfolio standard requiring that a certain percentage of demand be met with
renewable resources, and a carbon cap, requiring that total emissions be
below a certain level.

gridpath.system.policy.carbon_cap
--------------------------------------------

.. automodule:: gridpath.system.policy.carbon_cap


gridpath.system.policy.carbon_tax
--------------------------------------------

.. automodule:: gridpath.system.policy.carbon_tax

gridpath.system.policy.energy_targets.horizon_energy_target
-----------------------------------------------------------

.. automodule:: gridpath.system.policy.energy_targets.horizon_energy_target

gridpath.system.policy.fuel_burn_limits.fuel_burn_limits
--------------------------------------------------------

.. automodule:: gridpath.system.policy.fuel_burn_limits.fuel_burn_limits

gridpath.system.policy.performance_standard.performance_standard
----------------------------------------------------------------

.. automodule:: gridpath.system.policy.performance_standard.performance_standard


Markets
=======

GridPath can model market participation of a project or a set of projects. A price
stream is required and projects are assumed to be price-takers. The market volume can
be constrained. In multi-stage modeling, the transactions from the previous stages
can be fixed in the following stages.

gridpath.system.markets.prices
-------------------------------------

.. automodule:: gridpath.system.markets.prices

gridpath.system.markets.volume
-------------------------------------

.. automodule:: gridpath.system.markets.volume
