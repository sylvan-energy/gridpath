# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.
# Copyright 2026 Sylvan Energy Analytics LLC.

"""

**Relevant tables:**

+-------------------------------+-----------------------------------------------+
|:code:`scenarios` table column |:code:`market_volume_scenario_id`              |
+-------------------------------+-----------------------------------------------+
|:code:`scenario` table feature |:code:`of_markets`                             |
+-------------------------------+-----------------------------------------------+
|:code:`subscenario_` table     |:code:`subscenarios_market_volume`             |
+-------------------------------+-----------------------------------------------+
|:code:`input_` tables          |:code:`inputs_market_volume`                   |
+-------------------------------+-----------------------------------------------+

Each market group is mapped to a volume profile at each temporal resolution it
is limited at. The profiles themselves live in the
:code:`volume_profiles`, :code:`volume_hrz_profiles` and
:code:`volume_prd_profiles` subdirectories, keyed by market group.

"""

if __name__ == "__main__":
    print(__doc__)
