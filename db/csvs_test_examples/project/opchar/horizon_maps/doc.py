# Copyright 2026 Sylvan Energy Analytics LLC. All rights reserved.

"""

**Relevant tables:**

+---------------------------+----------------------------------------------------+
|key column                 |:code:`opchar_horizon_map_scenario_id`              |
+---------------------------+----------------------------------------------------+
|:code:`subscenario_` table |:code:`subscenarios_project_opchar_horizon_map`     |
+---------------------------+----------------------------------------------------+
|:code:`input_` table       |:code:`inputs_project_opchar_horizon_map`           |
+---------------------------+----------------------------------------------------+

The horizon-indexed analog of the opchar timepoint maps (see the
*Opchar Timepoint Maps* section): each row maps a model
:code:`balancing_type_horizon`-:code:`horizon` to the :code:`data_horizon`
at which to read horizon-indexed operating characteristics data (e.g.,
hydro operational characteristics). Horizons not listed in a map read data
at the horizon itself. Projects opt in per input type via the
:code:`*_hrz_map_scenario_id` columns of
:code:`inputs_project_operational_chars`, e.g.,
:code:`hydro_operational_chars_hrz_map_scenario_id`.

See the :code:`single_stage_prod_cost_linked_subproblems_w_hydro_w_hrz_map`
example: Hydro's operational characteristics are specified for the first
day horizon only and repeated for the other horizons via a map, producing
the same scenario as
:code:`single_stage_prod_cost_linked_subproblems_w_hydro`.

"""

if __name__ == "__main__":
    print(__doc__)
