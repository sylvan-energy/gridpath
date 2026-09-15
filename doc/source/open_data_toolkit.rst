#####################
GridPath Data Toolkit
#####################

.. automodule:: open_data_toolkit

The steps that generate stochastic, resource-adequacy-style inputs —
temporal scenarios from weather draws, synchronous or Monte Carlo load,
variable generation, and generator weather-derate profiles, hydro
conditions, and thermal-outage availability iterations — are part of the
GridPath RA Toolkit package and are documented on the :doc:`ra_toolkit`
page. They run from the RA Toolkit's own ``gridpath_run_ra_toolkit``
command and settings CSV, against the RA Toolkit's own raw data database.

.. _data-toolkit-workflow-section-ref:

The Data Toolkit Workflow
#########################

Turning raw public data into GridPath scenario inputs is a sequence of
steps in three phases:

1. **Obtain the raw data** with the standalone download and convert
   commands: ``gridpath_get_pudl_data`` (and optionally
   ``gridpath_get_eia930a_data``) downloads the source datasets, and
   ``gridpath_pudl_to_gridpath_raw`` converts them to the GridPath raw
   CSV format, selecting the data vintages to use.
2. **Build the raw data database**: create it from the Data Toolkit's
   schema, load the raw CSVs (plus your ``user_defined_*`` mapping CSVs)
   with the ``load_raw_data`` step, and patch the balancing-authority map
   (``patch_eia_baa_codes``, and ``apply_custom_zones`` if you define
   your own zones).
3. **Generate the GridPath input CSVs**: decide the study scope, fleet,
   and aggregation settings, list the input-generating steps with those
   settings in a settings CSV, and run it with
   ``gridpath_run_data_toolkit``. The resulting CSVs are then ported
   into a GridPath scenario database like any other GridPath CSV inputs
   (see :ref:`building-the-database-section-ref`).

The steps of phases 2 and 3 can all run from the same settings CSV in one
``gridpath_run_data_toolkit`` invocation — steps run in the order they
first appear in the file — or one at a time with its ``--single_step``
argument. The subsections below walk through the workflow in order; the
sections after them are the reference documentation for the individual
steps.

Note that the Data Toolkit generates a *subset* of the inputs a GridPath
scenario needs — most notably, temporal scenarios and load profiles are
not derived from these datasets and must come from elsewhere (provided
directly by the user, or generated with the :doc:`ra_toolkit`).

*********************
Download the Raw Data
*********************

``gridpath_get_pudl_data`` downloads the PUDL-published tables the
Toolkit uses (EIA860/EIA860M generators, the EIA balancing-authority
map, EIA930 hourly operations data, EIA AEO fuel price projections, and
several data-quality reconciliation tables) as per-table Parquet files
from a versioned PUDL release. ``gridpath_get_eia930a_data`` additionally
downloads EIA's annual generator-to-balancing-authority inventory (the
EIA-930A workbook), which the project steps use by default to place each
generator in the BA that actually operates it. See
:mod:`open_data_toolkit.raw_data.pudl.download_data_from_pudl` and
:mod:`open_data_toolkit.raw_data.eia930a` below for the details, including the
``data_metadata.csv`` trail each run leaves in its output directory.

*************************************
Convert the Raw Data to GridPath CSVs
*************************************

``gridpath_pudl_to_gridpath_raw`` queries the downloaded Parquet files
into the GridPath raw data CSVs. This step selects data *vintages* only
— most importantly the EIA860 report date (``eia860_report_date``,
defaulting to the latest available — normally PUDL's reconstruction of
the in-progress report year from EIA860M rather than an as-filed annual
survey) — and deliberately does no other filtering: choices about
operational status, region, and so on happen downstream in the
input-generating steps, so the raw database holds the data as published.
See :mod:`open_data_toolkit.raw_data.pudl.pudl_to_gridpath_raw_data` below
for the vintage-selection details and the resulting files.

Note that the download and convert commands ask for confirmation before
overwriting existing outputs — for headless runs, make sure the output
files are absent.

*************************************
Create and Load the Raw Data Database
*************************************

Create the raw data database from the Data Toolkit's own schema (a
separate database from any GridPath scenario database):

>>> gridpath_run_data_toolkit --single_step create_database --database PATH/TO/RAW/DB --db_schema PATH/TO/GRIDPATH/open_data_toolkit/raw_data_db_schema.sql --omit_data

Then load the raw CSVs with the ``load_raw_data`` step (see
:mod:`open_data_toolkit.load_raw_data` below), which reads a
``files_to_import.csv`` manifest mapping each CSV to its database table.
Besides the converted PUDL/EIA files, the manifest is also how you load
the ``user_defined_*`` mapping tables — the tables that encode your
study's interpretation of the raw data, which you provide as CSVs:

* ``user_defined_eia_gridpath_key`` — maps each EIA prime mover/energy
  source combination to a GridPath operational type, capacity type, and
  technology, and optionally to an aggregate-project name (see the
  aggregation settings below); a unit whose combination has no row here
  is not included in the fleet;
* ``user_defined_project_fuel_region_key`` and
  ``user_defined_eiaaeo_region_key`` — assign projects to fuel regions
  and fuel regions to EIA AEO fuel-price regions (the two vocabularies
  must match for the generated fuels to get prices);
* ``user_defined_heat_rate_curve`` and
  ``user_defined_generic_fuel_intensities`` — heat-rate curve shapes and
  fuel carbon intensities;
* ``user_defined_baa_overrides`` — optional manual generator-to-BA
  assignment overrides, taking precedence over both EIA-930A and EIA-860
  (empty by default);
* ``user_defined_unit_overrides`` — optional per-unit manual overrides
  for the project steps: force a unit into or out of the fleet, carve a
  plant into its own aggregate project, or override its load zone (empty
  by default; see :mod:`open_data_toolkit.project.fleet.unit_overrides`).

.. warning:: Loads append. Re-running ``load_raw_data`` for a file that
    is already loaded duplicates its rows, and loading a second EIA860
    vintage duplicates every generator (no downstream step filters on
    the report date — aggregated capacities would silently double).
    Load each file once into a given database; to start over, recreate
    the database.

Right after loading, patch the balancing-authority map with the
``patch_eia_baa_codes`` step: it fills documented gaps in the source BA
map that would otherwise silently drop real generators and interchange
links from zone-filtered outputs (see
:mod:`open_data_toolkit.raw_data.patch_eia_baa_codes` below; reruns are
no-ops). If you plan to use your own load-zone definitions (the
``custom`` load-zone level below), also run the ``apply_custom_zones``
step (:mod:`open_data_toolkit.raw_data.apply_custom_zones`) to record your
BA-to-zone mapping in the map. Both must run before any of the
zone-consuming input-generating steps.

**********************************************
Choose the Study Scope, Fleet, and Aggregation
**********************************************

The input-generating steps share a set of settings that together decide
what gets modeled. They apply, in order:

1. **Where** (geographic scope) — ``footprint`` filters the raw data to
   the balancing authorities in the study footprint: an EIA930 region, an
   interconnect (the default is ``western``), or ``all`` (no filter).
   Run ``gridpath_list_footprint_options`` to see the accepted values
   (see :mod:`open_data_toolkit.list_footprint_options` below).
   ``load_zone_level`` then sets the model's spatial resolution *within*
   that footprint: one load zone per balancing authority (``baa``, the
   default), per EIA930 region (``region``), per interconnect
   (``interconnect``), per user-defined zone (``custom``, see
   ``apply_custom_zones`` above), or a single zone for the whole
   footprint (``all``). Projects, system load zones, and the
   transmission topology (one line per zone pair, built from the
   observed interchange) all follow this setting. ``ba_source`` selects
   which dataset places each generator in its BA — the EIA-930A
   operational inventory (the default, if loaded) or the EIA-860
   survey-reported assignment.
2. **What** (fleet selection) — ``study_year`` anchors the fleet: units
   operating and not retiring before the study year, plus
   not-yet-operational units expected online by it — minus units with a
   filed PLANNED retirement date before the study year's end. The
   ``planned_inclusion``, ``inactive_inclusion``, ``include_retired``,
   ``include_planned_retirements``, ``include_btm_plants``, and
   ``include_net_metered`` settings
   widen or narrow this default window (how speculative a planned unit
   to admit; whether to count standby/out-of-service units, retired
   units, units planning to retire, and behind-the-meter units). The
   full narrative of these settings is in the
   :mod:`portfolio step's documentation
   <open_data_toolkit.project.portfolios.eia860_to_project_portfolio_input_csvs>`
   below.
3. **As what** (aggregation) — by default every generator is its own
   GridPath project, named ``<plant_id_eia>__<generator_id>``. The
   ``project_aggregation`` setting instead groups units into aggregate
   projects at the technology-load-zone level — for every technology
   (``all``) or only for technologies given an ``agg_project`` name in
   ``user_defined_eia_gridpath_key`` (``agg_project_keyed``, e.g.
   aggregate wind/solar/hydro and keep thermal units individual). The
   ``aggregation_dimensions`` setting splits aggregates finer by named
   unit characteristics (EIA technology description, vintage decade,
   storage duration, operational status), and the ``aggregation_level``
   setting aggregates at a finer geographic level than the load zones
   (e.g. per-BA projects assigned to custom zones) — again see the
   portfolio step's documentation for details.

Individual units can be pinned past all three stages with the optional
``user_defined_unit_overrides`` table — force a unit into or out of the
fleet, carve a plant into its own aggregate project, or override its
load zone (see :mod:`open_data_toolkit.project.fleet.unit_overrides`).

Because these settings decide which units become which projects, every
project-level step must run with the SAME values — a portfolio
aggregated one way and capacities another do not describe the same
fleet, and nothing downstream reconciles them. All the project steps
declare these settings through one shared helper, so their names,
defaults, and meanings are identical wherever they appear, and
``gridpath_run_data_toolkit`` cross-checks that the values in the
settings CSV agree (its ``--check_settings_consistency`` argument:
``warn`` by default, ``error``, or ``off`` for a settings file that
deliberately mixes, e.g. to build alternative subscenarios).

To see exactly what a given combination of settings selects before (or
after) generating inputs, run the ``fleet_audit`` step with the same
settings: it reports, unit by unit, each stage's decision — resolved BA
and load zone, each filter passed or failed, final project name — plus
a units-and-MW waterfall of what each stage excluded (see
:mod:`open_data_toolkit.project.fleet.fleet_audit` below).

********************************
Generate the GridPath Input CSVs
********************************

List the steps to run, with their settings, in a settings CSV with
columns ``script``, ``setting``, ``value``, ``script_true_false_arg``,
``reverse_default_behavior`` — one row per setting, grouped by step;
steps run in the order they first appear. Regular rows are passed to the
step as ``--<setting> <value>``. For a boolean flag, set
``script_true_false_arg`` to 1 and leave ``value`` empty: the bare
``--<setting>`` flag is passed if ``reverse_default_behavior`` is 1 and
omitted if 0. For example:

.. code-block:: text

    script,setting,value,script_true_false_arg,reverse_default_behavior
    create_database,database,./open_data_raw.db,,
    create_database,db_schema,PATH/TO/GRIDPATH/open_data_toolkit/raw_data_db_schema.sql,,
    create_database,omit_data,,1,1
    load_raw_data,csv_location,./raw_data,,
    load_raw_data,database,./open_data_raw.db,,
    patch_eia_baa_codes,database,./open_data_raw.db,,
    eia930_load_zone_input_csvs,database,./open_data_raw.db,,
    eia930_load_zone_input_csvs,footprint,western,,
    eia930_load_zone_input_csvs,load_zone_level,baa,,
    ...
    eia860_to_project_portfolio_input_csvs,database,./open_data_raw.db,,
    eia860_to_project_portfolio_input_csvs,study_year,2026,,
    eia860_to_project_portfolio_input_csvs,footprint,western,,
    eia860_to_project_portfolio_input_csvs,load_zone_level,baa,,
    eia860_to_project_portfolio_input_csvs,project_aggregation,agg_project_keyed,,
    eia860_to_project_portfolio_input_csvs,aggregation_dimensions,"technology_description,vintage_decade",,
    eia860_to_project_portfolio_input_csvs,output_directory,./csvs_open_data/project/portfolios,,
    ...

Then:

>>> gridpath_run_data_toolkit --settings_csv PATH/TO/SETTINGS/CSV

The available steps (the ``script`` vocabulary, also the
``--single_step`` choices in the ``--help`` menu) are documented in the
sections below. The database-building steps must come first, in the
order given in the previous subsections; the input-generating steps are
then independent of each other, except that ``manual_adjustments`` — the
post-processing step that patches gaps in the generated CSVs (see
:mod:`open_data_toolkit.project.manual_adjustments` below) — must run LAST.

.. note:: Steps parse only the settings they know and silently ignore
    the rest, so a typo'd setting name does not error — the step's
    default quietly applies instead. This is what the orchestrator's
    settings-consistency check (see the previous subsection) exists to
    catch for the settings that must agree across steps; spot-check any
    other setting you are not sure took effect (each step's accepted
    settings are listed in its documentation below and in the
    corresponding command's ``--help`` menu).

Each step writes standard GridPath subscenario input CSVs — named
``<subscenario_id>_<subscenario_name>.csv`` per its ``*_scenario_id``
and ``*_scenario_name`` settings — into its ``output_directory``.

***************************
Build the GridPath Database
***************************

The generated CSVs are ordinary GridPath CSV inputs: point the
database-building utilities at the directory layout the steps wrote
(registered in a ``csv_structure.csv`` file) to load them into a
GridPath scenario database, define scenarios, and run them. See
:ref:`building-the-database-section-ref` for that part of the process.

Obtaining Raw Data
##################

****
PUDL
****
.. automodule:: open_data_toolkit.raw_data.pudl

Download Datasets
*****************
.. automodule:: open_data_toolkit.raw_data.pudl.download_data_from_pudl

Convert to GridPath Raw Format
******************************
.. automodule:: open_data_toolkit.raw_data.pudl.pudl_to_gridpath_raw_data

********
EIA-930A
********
.. automodule:: open_data_toolkit.raw_data.eia930a

Setting Up the Raw Data Database
################################

****************
Loading Raw Data
****************

.. automodule:: open_data_toolkit.load_raw_data


******************
BA Map Adjustments
******************

.. automodule:: open_data_toolkit.raw_data.patch_eia_baa_codes
.. automodule:: open_data_toolkit.raw_data.apply_custom_zones


*****************
Footprint Options
*****************

.. automodule:: open_data_toolkit.list_footprint_options


Generating Input CSVs
#####################

****************
Load Zone Inputs
****************

.. automodule:: open_data_toolkit.system.eia930_load_zone_input_csvs

**************
Project Inputs
**************

The project-level steps below share the scope, fleet-selection, and
aggregation settings described in
:ref:`data-toolkit-workflow-section-ref` and must be run with consistent
values so they generate inputs for the same set of projects (the
orchestrator cross-checks this by default, and the fleet-audit step
reports what the settings selected). The
:mod:`open_data_toolkit.project.fleet` package documentation below describes
the four-stage pipeline these steps compose; the portfolio step's
documentation carries the full narrative of the individual settings.

The EIA860-based project steps all read whichever EIA860 data
vintage was loaded into the raw database (the ``eia860_report_date``
chosen at convert time). Note that the latest available vintage — the
convert step's default — is normally PUDL's reconstruction of the
in-progress report year from EIA860M rather than an as-filed annual
survey: fresher than any filed vintage, but with the annual-form-only
columns NULL. The portfolio module below documents what that means and
when to pin an as-filed vintage instead.

.. automodule:: open_data_toolkit.project.fleet
.. automodule:: open_data_toolkit.project.fleet.unit_overrides
.. automodule:: open_data_toolkit.project.fleet.fleet_audit
.. automodule:: open_data_toolkit.project.portfolios.eia860_to_project_portfolio_input_csvs
.. automodule:: open_data_toolkit.project.load_zones.eia860_to_project_load_zone_input_csvs
.. automodule:: open_data_toolkit.project.availability.eia860_to_project_availability_input_csvs
.. automodule:: open_data_toolkit.project.capacity_specified.eia860_to_project_specified_capacity_input_csvs
.. automodule:: open_data_toolkit.project.capacity_specified.eia860m_to_project_specified_capacity_input_csvs
.. automodule:: open_data_toolkit.project.fixed_cost.eia860_to_project_fixed_cost_input_csvs
.. automodule:: open_data_toolkit.project.opchar.eia860_to_project_opchar_input_csvs
.. automodule:: open_data_toolkit.project.opchar.fuels.eia860_to_project_fuel_input_csvs
.. automodule:: open_data_toolkit.project.opchar.heat_rates.eia860_to_project_heat_rate_input_csvs
.. automodule:: open_data_toolkit.project.manual_adjustments


***********
Fuel Inputs
***********
.. automodule:: open_data_toolkit.fuels.eiaaeo_to_fuel_chars_input_csvs
.. automodule:: open_data_toolkit.fuels.eiaaeo_fuel_price_input_csvs


*******************
Transmission Inputs
*******************

.. automodule:: open_data_toolkit.transmission.portfolios.eia930_to_transmission_portfolio_input_csvs
.. automodule:: open_data_toolkit.transmission.load_zones.eia930_to_transmission_load_zone_input_csvs
.. automodule:: open_data_toolkit.transmission.availability.eia930_to_transmission_availability_input_csvs
.. automodule:: open_data_toolkit.transmission.capacity_specified.eia930_to_transmission_specified_capacity_input_csvs
.. automodule:: open_data_toolkit.transmission.opchar.eia930_to_transmission_opchar_input_csvs
