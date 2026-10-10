# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

"""

**Relevant tables:**

+--------------------------------+--------------------------------------------------+
|:code:`scenarios` table column  |:code:`project_specified_fixed_cost_scenario_id`  |
+--------------------------------+--------------------------------------------------+
|:code:`scenarios` table feature |N/A                                               |
+--------------------------------+--------------------------------------------------+
|:code:`subscenario_` table      |:code:`subscenarios_project_specified_fixed_cost` |
+--------------------------------+--------------------------------------------------+
|:code:`input_` tables           |:code:`inputs_project_specified_fixed_cost`       |
+--------------------------------+--------------------------------------------------+

If the project portfolio includes project of the capacity types
:code:`gen_spec`, :code:`gen_ret_bin`, :code:`gen_ret_lin`, or
:code:`stor_spec`, the user must select the fixed O&M costs associated with
the specified project capacity in every period. These can be varied by
scenario via the :code:`project_specified_fixed_cost_scenario_id` subscenario.

The treatment for specified project fixed cost inputs is similar to that for
their capacity (see :ref:`specified-project-capacity-section-ref`): fixed
costs are read for the periods in which the project has specified capacity.
Like the capacity, fixed costs can be given for every period at once with
:code:`period = 0` rows (see :code:`gridpath.auxiliary.period_wildcards`),
independently of whether the capacity is; see the
:code:`2periods_gen_lin_econ_retirement_w_period_wildcards` example.

"""

if __name__ == "__main__":
    print(__doc__)
