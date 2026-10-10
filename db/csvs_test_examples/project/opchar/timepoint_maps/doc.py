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

The built-in *calendar-hour* map, with the reserved
:code:`opchar_timepoint_map_scenario_id` 0 (which the database schema
creates, with no rows in :code:`inputs_project_opchar_timepoint_map`),
reads each timepoint's data at its calendar hour,
:code:`month * 10000 + day_of_month * 100 + hour_of_day` from the
temporal inputs: e.g. hour 7 of 3 June reads the data at timepoint 60307.
Data stored once for the hours of a year (8,760 rows for an hourly year)
then serves every period of any temporal scenario, whatever its timepoint
numbering; use the hour convention (0-23 or 1-24) of the temporal
scenarios. Every timepoint needs a month, day of month, and whole-hour
:code:`hour_of_day`, or validation and the input writing fail. February 29
timepoints read the data at :code:`229HH`.

With any timepoint map, every operational timepoint of a mapped project
must find data at the timepoint it reads: mapped timepoints don't fall back
to their own data, and validation and the input writing report the
timepoints without data (e.g. February 29 timepoints when the calendar-hour
data has no :code:`229HH` rows). See the
:code:`2periods_new_build_w_var_profile_calendar_hour_map` example, the
same scenario as :code:`2periods_new_build` with Wind's profile stored at
calendar hours 10101 and 10102.

"""

if __name__ == "__main__":
    print(__doc__)
