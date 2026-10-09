# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

"""

**Relevant tables:**

+---------------------------+-----------------------------------------------------+
|key column                 |:code:`hydro_operational_chars_scenario_id`          |
+---------------------------+-----------------------------------------------------+
|:code:`subscenario_` table |:code:`subscenarios_project_hydro_operational_chars` |
+---------------------------+-----------------------------------------------------+
|:code:`input_` table       |:code:`inputs_project_hydro_operational_chars`       |
+---------------------------+-----------------------------------------------------+

Hydro generators in GridPath require that average power, minimum power, and
maximum power be specified for the project for each *balancing
type*/*horizon* in which it can exist in a GridPath model. These inputs are in
the :code:`inputs_project_hydro_operational_chars`
for each project, balancing type, and horizon, while the names and
descriptions of the characteristis each project can be assigned are in the
:code:`subscenarios_project_hydro_operational_chars`. These two tables
are linked to each other and to the :code:`inputs_project_operational_chars`
via the :code:`hydro_operational_chars_scenario_id` key column. The
:code:`inputs_project_hydro_operational_chars` table can contain data
for projects and horizons that are not included in a particular GridPath
scenario: GridPath will select the subset of projects and horizons based
on the scenarios project portfolio and temporal subscenarios.

On the built-in :code:`subproblem_period_month_circular` and
:code:`subproblem_period_month_linear` balancing types (horizon =
:code:`period * 100 + month`), data can also be given per month of year: a
row with :code:`horizon` 1-12 supplies that month in every period that has no
row for its own horizon, so a pattern that repeats every year needs 12 rows,
and years that differ need rows only for their own horizons (e.g.
:code:`202405`). This applies to all horizon-indexed operating
characteristics (hydro operational characteristics, hydro budget allocation,
energy horizon shaping, energy slice horizon shaping, and load component
shift bounds), but not to projects that use a horizon map for the input,
which read only the horizons the map points to. Projects of operational
types whose per-horizon inputs are required (:code:`gen_hydro`,
:code:`gen_hydro_must_take`, :code:`energy_hrz_shaping`, and
:code:`energy_slice_hrz_shaping`) must have rows for at least one horizon
of the temporal scenario, or getting the scenario inputs fails with an
error.

See the :code:`2horizons_w_hydro_w_month_of_year_inputs` example, which
gives Hydro's inputs per month of year (with one explicit row overriding
month 2) and produces the same scenario as :code:`2horizons_w_hydro`.

"""

if __name__ == "__main__":
    print(__doc__)
