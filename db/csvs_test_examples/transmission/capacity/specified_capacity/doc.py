# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

"""
Relevant tables:

+--------------------------------+----------------------------------------------------+
|:code:`scenarios` table column  |:code:`transmission_specified_capacity_scenario_id` |
+--------------------------------+----------------------------------------------------+
|:code:`scenarios` table feature |:code:`of_transmission`                             |
+--------------------------------+----------------------------------------------------+
|:code:`subscenario_` table      |:code:`subscenarios_transmission_specified_capacity`|
+--------------------------------+----------------------------------------------------+
|:code:`input_` tables           |:code:`inputs_transmission_specified_capacity`      |
+--------------------------------+----------------------------------------------------+

A line is available in the periods for which it has a capacity row. A line
with the same capacity in every period can instead be given with a single
:code:`period = 0` row, which applies to every period (see
:code:`gridpath.auxiliary.period_wildcards`); a line with a
:code:`period = 0` row can have no rows for other periods. See the
:code:`2periods_new_build_2zones_transmission_w_period_wildcards` example.

"""

if __name__ == "__main__":
    print(__doc__)
