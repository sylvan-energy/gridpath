# Copyright 2016-2023 Blue Marble Analytics LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
\n
**Relevant tables:**

+-------------------------------+----------------------------------------------+
|:code:`scenarios` table column |:code:`temporal_scenario_id`                  |
+-------------------------------+----------------------------------------------+
|:code:`scenario` table feature |N/A                                           |
+-------------------------------+----------------------------------------------+
|:code:`subscenario_` table     |:code:`subscenarios_temporal_timepoints`      |
+-------------------------------+----------------------------------------------+
|:code:`input_` tables          |- :code:`inputs_temporal`                     |
|                               |- :code:`inputs_temporal_horizons`            |
|                               |- :code:`inputs_temporal_horizon_timepoints`  |
|                               |- :code:`inputs_temporal_periods`             |
|                               |- :code:`inputs_temporal_subproblems`         |
|                               |- :code:`inputs_temporal_subproblem_stages`   |
+-------------------------------+----------------------------------------------+

The first step in building the GridPath database is to determine the
temporal span and resolution of the scenarios to be run. See the
:ref:`temporal-setup-section-ref` for a detailed description of the types
of temporal inputs in GridPath.

The user must decide on temporal resolution and span, i.e. timepoints
(e.g. hourly, 4-hourly, 15-minute, etc.) and how the *timepoints* are
connected to each other in an optimization: 1) what the *horizon(s)* is (are),
e.g. we can see as far ahead as one day, one week, or a full 8760 in making
operational decisions and 2) what *period* a timepoint belongs to, with a
period being the time when investment decisions are made, so depending on a
period a different set of resources is available in a particular timepoint.
In addition, the user has to specify whether all timepoints are optimized
concurrently, or if they are split into *subproblems* (e.g. the full year is
solved a week at a time in a production-cost scenario). Finally, the
temporal inputs also define whether the scenario will have *stages*, i.e.
whether some results from one stage will be fixed and fed into a subsequent
stage with some inputs also potentially changed.

The subscenarios table has the :code:`temporal_scenario_id` column as its
primary key. This ID refers to a particular set of *timepoints* and how they
are linked into *horizons*, *periods*, *subproblems*, and *stages*. For
example, we could be running production cost for 2020 (the *period* simply a
year in this case with no investment decisions), but optimize each day
individually in one scenario (the *subproblem* is the day) and a week at a
time in another scenario (the *subproblem* is a week). We have the same
timepoints in both of those scenarios but they are linked differently into
*subproblems*, so these will be two different :code:`temporal_scenario_id`’s.
Another example might be to use the same sample of “representative” days to
optimize investment and dispatch between 2021 and 2050, but group the days
depending on what year they belong to (30 *periods* = higher resolution on
investment decisions) in one scenario and what decade they belong to in
another scenario (3 *periods* = lower resolution on investment decisions). In
this case we would have the same timepoints and horizons (as well as a single
subproblem and a single stage), but they would be grouped differently into
periods, so, again, we’d need two different :code:`temporal_scenario_id`’s.

Descriptions of the relevant tables are below:

The :code:`subscenarios_temporal_timepoints` contains the IDs, names, and
descriptions of the temporal scenarios to be available to the user. This
table must be populated before data for the respective
:code:`temporal_scenario_id` can be imported into the input tables.

The :code:`inputs_temporal`: for a given temporal scenario, the
timepoints along with their horizon and period as well as the “resolution”
of each timepoint (is it an hour, a 4-hour chunk, 15-minute chunk, etc.)

The :code:`inputs_temporal_subproblems` tables contains the subproblems for
each :code:`temporal_scenario_id` (usually used in production-cost modeling,
set to 1 in capacity-expansion scenarios with a single subproblem).

The :code:`inputs_temporal_subproblems_stages` table contains the information
about whether there are stages within each subproblem. Stages must be given
an ID and can optionally be given a name.

The :code:`inputs_temporal_periods` table contains the information about the
investment periods in the respective :code:`temporal_scenario_id` along with
the data for the discount factor to be applied to the period and the number of
years it represents (e.g. we can use 2030 to represent the 10-year period
between 2025 and 2034). For stochastic problems, the optional
:code:`prev_period` and :code:`probability` columns arrange the periods into a
scenario tree: periods sharing a :code:`prev_period` are alternative futures,
and their probabilities (of reaching each period) must sum to the probability
of the previous period.

The :code:`inputs_temporal_horizons` table contains information about the
*horizons* within a :code:`temporal_scenario_id` along their balancing type,
period, and boundary ('circular' if the last timepoint of the horizon is
used as the previous timepoint for the first timepoint of the horizon and
'linear' if we ignore the previous timepoint for the first timepoint of the
horizon).

The :code:`inputs_temporal` table contains information about the
timepoints within each :code:`temporal_scenario_id`, :code:`subproblem_id`, and
:code:`stage_id`, including the period of the timepoint, its 'resolution' (the
number of hours in the timepoint), its weight (the number of timepoints not
explicitly modeled that this timepoint represents), the ID of the timepoint
from the previous stage that this timepoint maps to (if any), whether this
timepoint is part of a spinup or lookahead, the month of this timepoint, and
the hour of day of this timepoint. Timepoint IDs must be unique.

The :code:`inputs_temporal_horizon_timepoints` table describes how timeponts
are organized into horizons for each temporal_scenario_id, subproblem_id, and
stage_id. A timepoint can belong to more than one horizon if those horizons
are of different balancing types (e.g. the same horizon can belong to a
'day' horizon, a 'week' horizon, a 'month' horizons, and a 'year' horizon).

A scenario's temporal setup is selected via the :code:`temporal_scenario_id`
column of the :code:`scenarios` table.

"""

import os.path
import webbrowser

import docutils.core

if __name__ == "__main__":
    html = docutils.core.publish_string(source=__doc__, writer_name="html")

    Html_file = open("html.html", "w")
    Html_file.write(html.decode("utf-8"))
    Html_file.close()

    webbrowser.open("file://" + os.path.join(os.getcwd(), "html.html"))
