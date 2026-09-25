# Copyright 2026 Sylvan Energy Analytics LLC.

"""

**Relevant tables:**

+-------------------------------+-----------------------------------------------+
|:code:`scenarios` table column |:code:`market_group_scenario_id`               |
+-------------------------------+-----------------------------------------------+
|:code:`scenario` table feature |:code:`of_markets`                             |
+-------------------------------+-----------------------------------------------+
|:code:`subscenario_` table     |:code:`subscenarios_market_groups`             |
+-------------------------------+-----------------------------------------------+
|:code:`input_` tables          |:code:`inputs_market_groups`                   |
+-------------------------------+-----------------------------------------------+

The groups of markets that market volume limits apply to. A group of one
limits a single market and a group of all of them is a system-wide limit;
groups may overlap. Each group is narrowed to the markets of the scenario's
:code:`market_scenario_id`.

"""

if __name__ == "__main__":
    print(__doc__)
