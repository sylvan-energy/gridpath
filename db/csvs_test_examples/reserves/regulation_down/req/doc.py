# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

"""

**Relevant tables:**

+------------------------------+----------------------------------------------------+
|:code:`scenarios` table column|:code:`regulation_down_scenario_id`                 |
+------------------------------+----------------------------------------------------+
|:code:`scenario` table feature|:code:`of_regulation_down`                          |
+------------------------------+----------------------------------------------------+
|:code:`subscenario_` table    |:code:`subscenarios_system_regulation_down`         |
+------------------------------+----------------------------------------------------+
|:code:`input_` tables         |:code:`inputs_system_regulation_down`               |
+------------------------------+----------------------------------------------------+
|                              |:code:`inputs_system_regulation_down_percent`       |
+------------------------------+----------------------------------------------------+
|                              |:code:`inputs_system_regulation_down_percent_lz_map`|
+------------------------------+----------------------------------------------------+
|                              |:code:`inputs_system_regulation_down_project`       |
+------------------------------+----------------------------------------------------+
|:code:`iterations` table      |:code:`inputs_system_regulation_down_iterations`    |
+------------------------------+----------------------------------------------------+

The by-timepoint requirement (:code:`inputs_system_regulation_down`) is keyed
by :code:`weather_iteration`. A BA whose requirement does not vary by weather
iteration (the default) carries it at weather iteration 0. A BA whose
requirement does, e.g. one computed from each weather draw's load and renewable
output, says so in the sibling :code:`req_iterations` directory, in a file
named like the requirement subscenario (:code:`<id>_<name>.csv`) that holds a
:code:`varies_by_weather_iteration` flag per BA
(:code:`inputs_system_regulation_down_iterations`). Each scenario iteration
then reads the BA's rows at its own weather iteration. Validation reports rows
at a non-zero weather iteration of a BA not flagged to vary by it, which are
never read, and flagged BAs with no rows at the run's weather iteration, whose
requirement would otherwise be 0. The percent-of-load requirement needs no
weather key: it applies to each weather iteration's own load.

"""

if __name__ == "__main__":
    print(__doc__)
