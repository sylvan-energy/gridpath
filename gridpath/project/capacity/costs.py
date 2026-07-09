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
The **gridpath.project.capacity.costs** module is a project-level
module that adds to the formulation components that describe the
capacity-related costs of projects (e.g. investment capital costs and fixed
O&M costs).
"""

import csv
import os.path
from pyomo.environ import Set, Expression, value

from db.common_functions import spin_on_database_lock
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.auxiliary.auxiliary import (
    get_required_subtype_modules,
    join_sets,
)
from gridpath.project.capacity.common_functions import (
    load_project_capacity_type_modules,
)
from gridpath.project import PROJECT_PERIOD_DF
from gridpath.auxiliary.dynamic_components import capacity_type_financial_period_sets
import gridpath.project.capacity.capacity_types as cap_type_init


def add_model_components(
    m,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    The following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Capacity_Cost_in_Period`                                       |
    | | *Defined Over*: :code:`PRJ_OPR_PRDS`                                  |
    |                                                                         |
    | This expression describe each project's capacity-related costs for each |
    | operational period, based on its capacity_type. For the purpose, call   |
    | the *capacity_cost_rule* method from the respective capacity-type       |
    | module. If the subproblem is less than a full year (e.g. in production- |
    | cost mode with 365 daily subproblems), the costs are scaled down        |
    | proportionally.                                                         |
    +-------------------------------------------------------------------------+

    """

    # Dynamic Inputs
    ###########################################################################

    required_capacity_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="capacity_type",
    )

    imported_capacity_modules = load_project_capacity_type_modules(
        required_capacity_modules
    )

    # Sets
    ###########################################################################

    m.PRJ_FIN_PRDS = Set(
        dimen=2,
        within=m.PROJECTS * m.PERIODS,
        initialize=lambda mod: join_sets(
            mod,
            getattr(d, capacity_type_financial_period_sets),
        ),
    )  # assumes capacity types model components are already added!

    # Expressions
    ###########################################################################

    def capacity_cost_rule(mod, prj, prd):
        """
        Get capacity capital cost for each generator's respective capacity module.
        These are applied in every financial period.

        Note that capacity cost inputs and calculations in the modules are on
        a period basis. Therefore, if the period spans subproblems (the main
        example of this would be specified capacity in, say, a production-cost
        scenario with multiple subproblems), we adjust the capacity costs down
        accordingly.
        """
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "capacity_cost_rule"):
            capacity_cost = imported_capacity_modules[cap_type].capacity_cost_rule(
                mod, prj, prd
            )
        else:
            capacity_cost = cap_type_init.capacity_cost_rule(mod, prj, prd)

        return (
            capacity_cost
            * mod.hours_in_subproblem_period[prd]
            / mod.hours_in_period_timepoints[prd]
        )

    m.Capacity_Cost_in_Period = Expression(m.PRJ_FIN_PRDS, rule=capacity_cost_rule)

    def energy_cost_rule(mod, prj, prd):
        """
        Get energy cost for each project's respective capacity module.
        These are applied in every financial period.

        Note that energy cost inputs and calculations in the modules are on
        a period basis. Therefore, if the period spans subproblems (the main
        example of this would be specified capacity in, say, a production-cost
        scenario with multiple subproblems), we adjust the capacity costs down
        accordingly.
        """
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "energy_cost_rule"):
            energy_cost = imported_capacity_modules[cap_type].energy_cost_rule(
                mod, prj, prd
            )
        else:
            energy_cost = cap_type_init.energy_cost_rule(mod, prj, prd)

        return (
            energy_cost
            * mod.hours_in_subproblem_period[prd]
            / mod.hours_in_period_timepoints[prd]
        )

    m.Energy_Cost_in_Period = Expression(m.PRJ_FIN_PRDS, rule=energy_cost_rule)

    def fixed_cost_rule(mod, prj, prd):
        """
        Get fixed cost for each generator's respective capacity module. These are
        applied in every operational period.

        Existing project costs are here only (i.e., we exclude ongoing sunk
        capital cost payments).

        New projects can have capacity/energy costs in addition to the fixed
        costs here.

        Note that fixed cost inputs and calculations in the modules are on
        a period basis. Therefore, if the period spans subproblems (the main
        example of this would be specified capacity in, say, a production-cost
        scenario with multiple subproblems), we adjust the fixed costs down
        accordingly.
        """
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "fixed_cost_rule"):
            fixed_cost = imported_capacity_modules[cap_type].fixed_cost_rule(
                mod, prj, prd
            )
        else:
            fixed_cost = cap_type_init.fixed_cost_rule(mod, prj, prd)

        return (
            fixed_cost
            * mod.hours_in_subproblem_period[prd]
            / mod.hours_in_period_timepoints[prd]
        )

    m.Fixed_Cost_in_Period = Expression(m.PRJ_OPR_PRDS, rule=fixed_cost_rule)


# Input-Output
###############################################################################


def export_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    m,
    d,
):
    """
    Export operations results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    results_columns1 = [
        "capacity_cost",
    ]
    data1 = [
        [
            prj,
            prd,
            value(m.Capacity_Cost_in_Period[prj, prd]),
        ]
        for (prj, prd) in m.PRJ_FIN_PRDS
    ]

    cost_df1 = create_results_df(
        index_columns=["project", "period"],
        results_columns=results_columns1,
        data=data1,
    )

    update_results_df(getattr(d, PROJECT_PERIOD_DF), cost_df1)

    results_columns2 = [
        "hours_in_period_timepoints",
        "hours_in_subproblem_period",
        "fixed_cost",
    ]
    data2 = [
        [
            prj,
            prd,
            m.hours_in_period_timepoints[prd],
            m.hours_in_subproblem_period[prd],
            value(m.Fixed_Cost_in_Period[prj, prd]),
        ]
        for (prj, prd) in m.PRJ_OPR_PRDS
    ]

    cost_df2 = create_results_df(
        index_columns=["project", "period"],
        results_columns=results_columns2,
        data=data2,
    )

    update_results_df(getattr(d, PROJECT_PERIOD_DF), cost_df2)


# Database
###############################################################################


def process_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate capacity costs by load zone, and break out into
    spinup_or_lookahead.
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate capacity costs by load zone")

    # Delete old resulst
    del_sql = """
        DELETE FROM results_project_costs_capacity_agg 
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Insert new results
    agg_sql = """
        INSERT INTO results_project_costs_capacity_agg
        (scenario_id, load_zone, period, subproblem_id, stage_id,
        spinup_or_lookahead, fraction_of_hours_in_subproblem, capacity_cost)
        
        SELECT scenario_id, load_zone, period, subproblem_id, stage_id,
        spinup_or_lookahead, fraction_of_hours_in_subproblem,
        (capacity_cost * fraction_of_hours_in_subproblem) AS capacity_cost
        FROM spinup_or_lookahead_ratios
        
        -- Add load_zones
        LEFT JOIN
        (SELECT scenario_id, load_zone
        FROM inputs_geography_load_zones
        INNER JOIN
        (SELECT scenario_id, load_zone_scenario_id FROM scenarios
        WHERE scenario_id = ?) AS scen_tbl
        USING (load_zone_scenario_id)
        ) AS lz_tbl
        USING (scenario_id)

        -- Now that we have all scenario_id, subproblem_id, stage_id, period, 
        -- load_zone, and spinup_or_lookahead combinations add the capacity 
        -- costs which will be derated by the fraction_of_hours_in_subproblem
        INNER JOIN
        (SELECT scenario_id, subproblem_id, stage_id, period, load_zone,
        SUM(capacity_cost) AS capacity_cost
        FROM results_project_period
        GROUP BY scenario_id, subproblem_id, stage_id, period, load_zone
        ) AS cap_table
        USING (scenario_id, subproblem_id, stage_id, period, load_zone)
        ;"""

    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )
