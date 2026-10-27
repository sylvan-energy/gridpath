# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

"""

**Relevant tables:**

+------------------------------+-----------------------------------------------------+
|:code:`scenarios` table column|:code:`inertia_reserves_scenario_id`                 |
+------------------------------+-----------------------------------------------------+
|:code:`scenario` table feature|:code:`of_inertia_reserves`                          |
+------------------------------+-----------------------------------------------------+
|:code:`subscenario_` table    |:code:`subscenarios_system_inertia_reserves`         |
+------------------------------+-----------------------------------------------------+
|:code:`input_` tables         |:code:`inputs_system_inertia_reserves`               |
+------------------------------+-----------------------------------------------------+
|                              |:code:`inputs_system_inertia_reserves_percent`       |
+------------------------------+-----------------------------------------------------+
|                              |:code:`inputs_system_inertia_reserves_percent_lz_map`|
+------------------------------+-----------------------------------------------------+
|                              |:code:`inputs_system_inertia_reserves_project`       |
+------------------------------+-----------------------------------------------------+
|                              |:code:`inputs_system_inertia_reserves_param`         |
+------------------------------+-----------------------------------------------------+
|:code:`iterations` table      |:code:`inputs_system_inertia_reserves_iterations`    |
+------------------------------+-----------------------------------------------------+

The by-timepoint requirement (:code:`inputs_system_inertia_reserves`) is keyed
by :code:`weather_iteration`. A BA whose requirement does not vary by weather
iteration (the default) carries it at weather iteration 0. A BA whose
requirement does, e.g. one computed from each weather draw's load and renewable
output, says so in the sibling :code:`req_iterations` directory, in a file
named like the requirement subscenario (:code:`<id>_<name>.csv`) that holds a
:code:`varies_by_weather_iteration` flag per BA
(:code:`inputs_system_inertia_reserves_iterations`). Each scenario iteration
then reads the BA's rows at its own weather iteration. Validation reports rows
at a non-zero weather iteration of a BA not flagged to vary by it, which are
never read, and flagged BAs with no rows at the run's weather iteration, whose
requirement would otherwise be 0. The percent-of-load requirement needs no
weather key: it applies to each weather iteration's own load.

The percent-of-load requirement
(:code:`inputs_system_inertia_reserves_percent`) applies to the load listed for
the BA in :code:`inputs_system_inertia_reserves_percent_lz_map`. A row with an
empty :code:`load_component` includes the load zone's whole load, net of load
modifiers. A row naming a load component includes only that load component's
static load, adjusted for its distribution losses; load modifiers are not
netted out of it, including :code:`load_component_modifier` projects linked to
that load component. Validation reports load components that are not among the
scenario's load components for the load zone, and load zones included both
whole and by load component, which would count those load components twice.

"""

if __name__ == "__main__":
    print(__doc__)
