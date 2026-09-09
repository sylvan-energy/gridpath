# Copyright 2026 Sylvan Energy Analytics LLC. All rights reserved.

"""

**Relevant tables:**

+---------------------------+-----------------------------------------------------+
|key column                 |:code:`hydro_budget_allocation_scenario_id`          |
+---------------------------+-----------------------------------------------------+
|:code:`subscenario_` table |:code:`subscenarios_project_hydro_budget_allocation` |
+---------------------------+-----------------------------------------------------+
|:code:`input_` table       |:code:`inputs_project_hydro_budget_allocation`       |
+---------------------------+-----------------------------------------------------+

Hydro generators (the :code:`gen_hydro` and :code:`gen_hydro_must_take`
operational types) must produce their energy budget in each horizon of their
balancing type (see the hydro operational characteristics). Optionally, the
allocation of that budget *within* the horizon can be limited: for each
*sub-horizon* -- a horizon of another balancing type in the temporal scenario
whose timepoints all fall within one of the project's horizons, e.g. each
half of a month for a project with monthly budgets -- the user can specify the
minimum and/or maximum share of the parent horizon's energy budget that
must/may be produced in that sub-horizon (e.g. no less than 45% and no more
than 55% of the monthly budget in each half of the month). A NULL limit is not
enforced.

These inputs are in the :code:`inputs_project_hydro_budget_allocation` table
for each project, sub-horizon balancing type, and sub-horizon, while the
names and descriptions of the limits each project can be assigned are in the
:code:`subscenarios_project_hydro_budget_allocation` table. These two tables
are linked to each other and to the :code:`inputs_project_operational_chars`
table via the :code:`hydro_budget_allocation_scenario_id` key column. Like the
other horizon-indexed operational characteristics, the limits can vary by
weather and hydro iteration (see the :code:`iterations` sub-directory) and can
be pointed at data stored under other horizons via an opchar horizon map
(the :code:`hydro_budget_allocation_hrz_map_scenario_id` column), so that,
e.g., the same shares can be specified once and applied to every month. The
table can contain data for projects and horizons that are not included in a
particular GridPath scenario: GridPath will select the subset of projects and
sub-horizons based on the scenario's project portfolio and temporal
subscenarios.

"""

if __name__ == "__main__":
    print(__doc__)
