# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

"""

**Relevant tables:**

+--------------------------------+------------------------------------------------+
|:code:`scenarios` table column  |:code:`project_specified_capacity_scenario_id`  |
+--------------------------------+------------------------------------------------+
|:code:`scenarios` table feature |N/A                                             |
+--------------------------------+------------------------------------------------+
|:code:`subscenario_` table      |:code:`subscenarios_project_specified_capacity` |
+--------------------------------+------------------------------------------------+
|:code:`input_` tables           |:code:`inputs_project_specified_capacity`       |
+--------------------------------+------------------------------------------------+

If the project portfolio includes project of the capacity types
:code:`gen_spec`, :code:`gen_ret_bin`, :code:`gen_ret_lin`, or
:code:`stor_spec`, the user must select that amount of project capacity that
the optimization should see as given (i.e. specified) in every period as
well as the associated fixed O&M costs (see
:ref:`specified-project-fixed-cost-section-ref`). Project
capacities are in the :code:`inputs_project_specified_capacity` table. For
:code:`gen_` capacity types, this table contains the project's power rating
and for :code:`stor_spec` it also contains the storage project's energy rating.

The primary key of this table includes the
:code:`project_specified_capacity_scenario_id`, the project name, and the
period. Note that this table can include projects that are not in the
user’s portfolio: the utilities that pull the scenario data look at the
scenario’s portfolio, pull the projects with the “specified” capacity types
from that, and then get the capacity for only those projects (and for the
periods selected based on the scenario's temporal setting). A new
:code:`project_specified_capacity_scenario_id` would be needed if a user wanted
to change the available capacity of even only a single project in a single
period (and all other project-year-capacity data points would need to be
re-inserted in the table under the new
:code:`project_specified_capacity_scenario_id`).

A project is operational in the periods for which it has a capacity row, so
leaving periods out models a project that retires, or comes online, within
the study horizon. A project with the same capacity in every period can
instead be given with a single :code:`period = 0` row, which applies to every
period (see :code:`gridpath.auxiliary.period_wildcards`); a project with a
:code:`period = 0` row can have no rows for other periods, so a project
that retires or comes online needs its periods given explicitly. See the
:code:`2periods_gen_lin_econ_retirement_w_period_wildcards` example.

"""
