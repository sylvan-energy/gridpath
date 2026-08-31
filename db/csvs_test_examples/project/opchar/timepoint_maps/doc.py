# Copyright 2026 Sylvan Energy Analytics LLC. All rights reserved.

"""

**Relevant tables:**

+---------------------------+----------------------------------------------------+
|key column                 |:code:`opchar_timepoint_map_scenario_id`            |
+---------------------------+----------------------------------------------------+
|:code:`subscenario_` table |:code:`subscenarios_project_opchar_timepoint_map`   |
+---------------------------+----------------------------------------------------+
|:code:`input_` table       |:code:`inputs_project_opchar_timepoint_map`         |
+---------------------------+----------------------------------------------------+

Timepoint-indexed operating characteristics (e.g., variable generator
profiles) must normally be specified for every *timepoint* in a scenario,
even when the data simply repeats (e.g., the same profile in every future
period). An *opchar timepoint map* lets a project point such an input at
data stored under other timepoints instead: each row maps a model
:code:`timepoint` to the :code:`data_timepoint` at which to read the data.
Timepoints not listed in a map read data at the timepoint itself, and
many-to-one maps are allowed (e.g., every timepoint of a period mapped to
the timepoints of a single representative day).

Maps are project-agnostic, named, and reusable. Projects opt in per input
type via the map columns of :code:`inputs_project_operational_chars` that
sit next to the respective data subscenario columns, e.g.,
:code:`variable_generator_profile_tmp_map_scenario_id` next to
:code:`variable_generator_profile_scenario_id`; a NULL map column means the
data must cover all model timepoints directly, as before. For a mapped
model timepoint, the data at the map's :code:`data_timepoint` governs even
if data is also stored at the model timepoint itself.

See the :code:`2periods_new_build_w_var_profile_tmp_map` example: Wind's
profile is specified for the 2020 timepoints only and repeated in 2030 via
a map, producing the same scenario as :code:`2periods_new_build`.

"""

if __name__ == "__main__":
    print(__doc__)
