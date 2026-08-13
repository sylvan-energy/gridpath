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
GridPath's objective function consists of modularized components. This
modularity allows for different objective functions to be defined. Here, we
discuss the objective of maximizing the net present value of revenues minus
costs.

Its most basic version includes the aggregated project capacity costs and
aggregated project operational costs, and any load-balance penalties
incurred (i.e. the aggregated unserved energy and/or overgeneration costs).

Other standard objective function components include:

    * aggregated transmission line capacity investment costs
    * aggregated transmission operational costs (hurdle rates)
    * aggregated reserve violation penalties

GridPath also can include custom objective function components that may not
be standard for all systems. Examples currently include:

    * local capacity shortage penalties
    * planning reserve margin costs
    * various tuning costs

Market costs and revenues may also be included.

GridPath can include costs on carbon emissions, so certain formulations can
interpreted as minimizing emissions.

All revenue and costs are in net present value terms, with a user-specified
discount factor applied depending on the period.
"""

import csv
import pandas as pd
import sqlite3
import numpy as np
import os


from pyomo.environ import Expression, Objective, maximize, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.db_interface import get_results_table_iteration_keys
from gridpath.auxiliary.dynamic_components import cost_components, revenue_components


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
    r"""
    :param m: the Pyomo abstract model object we are adding components to
    :param d: the DynamicComponents class object we will get components from

    At this point, all relevant modules should have added cost components to
    *d.total_cost_components*. We sum them all up here. With the minimum set
    of functionality, the objective function will be as follows:

    :math:`minimize:` \n

    :math:`Total\_Capacity\_Costs + Total\_Variable\_OM\_Cost +
    Total\_Fuel\_Cost + Total\_Load\_Balance\_Penalty\_Costs`

    """

    # Aggregate all revenue
    def total_revenue_rule(mod):
        return sum(getattr(mod, c) for c in getattr(d, revenue_components))

    m.Total_Revenue = m.Expression(initialize=total_revenue_rule)

    # Aggregate all costs
    def total_cost_rule(mod):
        return sum(getattr(mod, c) for c in getattr(d, cost_components))

    m.Total_Cost = m.Expression(initialize=total_cost_rule)

    # NPV
    def npv_rule(mod):
        return total_revenue_rule(mod) - total_cost_rule(mod)

    m.NPV = Objective(rule=npv_rule, sense=maximize)


# Input-Output
###############################################################################


def export_summary_results(
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
    Export objective function cost components
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    The Pyomo abstract model
    :param d:
    Dynamic components
    :return:
    Nothing
    """
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "npv.csv",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f)
        components = getattr(d, revenue_components) + getattr(d, cost_components)
        writer.writerow(components)
        writer.writerow((value(getattr(m, c)) for c in components))


# Database
###############################################################################


def import_results_into_database(
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    c,
    db,
    results_directory,
    quiet,
):
    """
    :param scenario_id:
    :param c:
    :param db:
    :param results_directory:
    :param quiet:
    :return:
    """
    # TODO: change this to say NPV and have negatives for the cost
    #  components or flag revenue and cost components
    if not quiet:
        print("results system cost")

    df = pd.read_csv(os.path.join(results_directory, "npv.csv"))
    df["scenario_id"] = scenario_id
    (
        df["weather_iteration"],
        df["hydro_iteration"],
        df["availability_iteration"],
        df["subproblem_id"],
        df["stage_id"],
    ) = get_results_table_iteration_keys(
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
    )
    results = df.to_records(index=False)

    # Register numpy types with sqlite, so that they are properly inserted
    # from pandas dataframes
    # https://stackoverflow.com/questions/38753737/inserting-numpy-integer-types-into-sqlite-with-python3
    sqlite3.register_adapter(np.int64, lambda val: int(val))
    sqlite3.register_adapter(np.float64, lambda val: float(val))

    insert_sql = """
        INSERT INTO results_system_costs
        ({})
        VALUES ({});
        """.format(", ".join(df.columns), ", ".join(["?"] * (len(df.columns))))
    spin_on_database_lock(conn=db, cursor=c, sql=insert_sql, data=results)
