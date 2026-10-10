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

Each row is a market group and a :code:`basis`: :code:`net` limits the
group's net position, :code:`gross` its total sales and total purchases
counted separately, and a group may have a row of each. A row maps the group
to a volume profile at each temporal resolution it is limited at, and may
carry flat timepoint- and period-level limits (the
:code:`default_*` columns) that need no profile. The profiles themselves live
in the :code:`volume_tmp_profiles`, :code:`volume_hrz_profiles`,
:code:`volume_hrz_to_tmp_profiles` and :code:`volume_prd_profiles`
subdirectories, keyed by market group; their rows override the flat limits
column by column. The horizon-to-timepoint profiles give timepoint-level
limits (MW) by horizon, applied in every timepoint of the horizon.

On the built-in :code:`subproblem_period_month_*` and
:code:`subproblem_period_day_*` balancing types, the horizon and
horizon-to-timepoint profiles also accept month-of-year rows (:code:`horizon`
1-12) and day-of-year rows (:code:`horizon` :code:`month * 100 +
day_of_month`), which supply that month or date in every period without an
explicit row; see
the :code:`test_markets_w_hrz_to_tmp_month_of_year_limits` example.

"""

if __name__ == "__main__":
    print(__doc__)
