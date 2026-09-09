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
Minimum and maximum new and total capacity by period and project group.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Set, Param, Constraint, NonNegativeReals, Expression, value

from gridpath.auxiliary.auxiliary import get_required_subtype_modules
from gridpath.common_functions import duals_wrapper, none_dual_type_error_wrapper
from gridpath.project.capacity.common_functions import (
    load_project_capacity_type_modules,
)
from gridpath.auxiliary.db_interface import import_csv, directories_to_db_values
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
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`CAPACITY_GROUP_PERIODS`                                        |
    |                                                                         |
    | A two-dimensional set of group-period combinations for which there may  |
    | be group capacity requirements.                                         |
    +-------------------------------------------------------------------------+
    | | :code:`CAPACITY_GROUPS`                                               |
    |                                                                         |
    | The groups of projects for which there may be group capacity            |
    | requirements.                                                           |
    +-------------------------------------------------------------------------+
    | | :code:`PROJECTS_IN_CAPACITY_GROUP`                                    |
    |                                                                         |
    | The list of projects by capacity group.                                 |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`capacity_group_new_capacity_min`                               |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The minimum amount of capacity (in MW) that must be built at projects   |
    | in this group in a given period.                                        |
    +-------------------------------------------------------------------------+
    | | :code:`capacity_group_new_capacity_max`                               |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`inf`                                                |
    |                                                                         |
    | The maximum amount of capacity (in MW) that may be built at projects    |
    | in this group in a given period.                                        |
    +-------------------------------------------------------------------------+
    | | :code:`capacity_group_total_capacity_min`                             |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The minimum amount of capacity (in MW) that must exist at projects      |
    | in this group in a given period.                                        |
    +-------------------------------------------------------------------------+
    | | :code:`capacity_group_total_capacity_max`                             |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`inf`                                                |
    |                                                                         |
    | The maximum amount of capacity (in MW) that may exist at projects       |
    | in this group in a given period.                                        |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Group_New_Capacity_in_Period`                                  |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    |                                                                         |
    | The new capacity built at projects in this group in this period.        |
    +-------------------------------------------------------------------------+
    | | :code:`Group_Total_Capacity_in_Period`                                |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    |                                                                         |
    | The new capacity of at projects in this group in this period.           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Max_Group_Capacity_Build_in_Period_Constraint`                          |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    |                                                                         |
    | Limits the amount of new build in each group in each period.            |
    +-------------------------------------------------------------------------+
    | | :code:`Min_Group_Capacity_Build_in_Period_Constraint`                          |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    |                                                                         |
    | Requires a certain amount of new build in each group in each period.    |
    +-------------------------------------------------------------------------+
    | | :code:`Max_Group_Total_Capacity_in_Period_Constraint`                      |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    |                                                                         |
    | Limits the total amount of capacity in each group in each period        |
    +-------------------------------------------------------------------------+
    | | :code:`Min_Group_Capacity_Build_in_Period_Constraint`                          |
    | | *Defined over*: :code:`CAPACITY_GROUP_PERIODS`                        |
    |                                                                         |
    | Requires a certain amount of capacity in each group in each period.     |
    +-------------------------------------------------------------------------+

    """

    # Sets
    m.CAPACITY_GROUP_PERIODS = Set(dimen=2)

    m.CAPACITY_GROUPS = Set(
        initialize=lambda mod: sorted(
            list(set([g for (g, p) in mod.CAPACITY_GROUP_PERIODS]))
        )
    )

    m.PROJECTS_IN_CAPACITY_GROUP = Set(m.CAPACITY_GROUPS, within=m.PROJECTS)

    # Params
    m.capacity_group_new_capacity_min = Param(
        m.CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=0
    )
    m.capacity_group_new_capacity_max = Param(
        m.CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=float("inf")
    )
    m.capacity_group_total_capacity_min = Param(
        m.CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=0
    )
    m.capacity_group_total_capacity_max = Param(
        m.CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=float("inf")
    )

    m.energy_group_new_energy_min = Param(
        m.CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=0
    )
    m.energy_group_new_energy_max = Param(
        m.CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=float("inf")
    )
    m.energy_group_total_energy_min = Param(
        m.CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=0
    )
    m.energy_group_total_energy_max = Param(
        m.CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=float("inf")
    )

    # Import needed capacity type modules
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

    # Get the new and total capacity/energy in the group for the respective
    # expressions
    def new_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        # The capacity type modules check if this period is a "vintage" for
        # this project and return 0 if not
        if hasattr(imported_capacity_modules[cap_type], "new_capacity_rule"):
            return imported_capacity_modules[cap_type].new_capacity_rule(mod, prj, prd)
        else:
            return cap_type_init.new_capacity_rule(mod, prj, prd)

    def new_energy_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        # The capacity type modules check if this period is a "vintage" for
        # this project and return 0 if not
        if hasattr(imported_capacity_modules[cap_type], "new_energy_rule"):
            return imported_capacity_modules[cap_type].new_energy_rule(mod, prj, prd)
        else:
            return cap_type_init.new_energy_rule(mod, prj, prd)

    def total_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        # Return the capacity type's capacity rule if the project is
        # operational in this timepoint; otherwise, return 0
        if prd not in mod.OPR_PRDS_BY_PRJ[prj]:
            return 0
        else:
            if hasattr(imported_capacity_modules[cap_type], "capacity_rule"):
                return imported_capacity_modules[cap_type].capacity_rule(mod, prj, prd)
            else:
                return cap_type_init.capacity_rule(mod, prj, prd)

    def total_energy_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        # Return the capacity type's energy rule if the project is
        # operational in this timepoint; otherwise, return 0
        if prd not in mod.OPR_PRDS_BY_PRJ[prj]:
            return 0
        else:
            if hasattr(imported_capacity_modules[cap_type], "energy_rule"):
                return imported_capacity_modules[cap_type].energy_rule(mod, prj, prd)
            else:
                return cap_type_init.energy_rule(mod, prj, prd)

    # Expressions
    def group_new_capacity_rule(mod, grp, prd):
        return sum(
            new_capacity_rule(mod, prj, prd)
            for prj in mod.PROJECTS_IN_CAPACITY_GROUP[grp]
        )

    m.Group_New_Capacity_in_Period = Expression(
        m.CAPACITY_GROUP_PERIODS, rule=group_new_capacity_rule
    )

    def group_new_energy_rule(mod, grp, prd):
        return sum(
            new_energy_rule(mod, prj, prd)
            for prj in mod.PROJECTS_IN_CAPACITY_GROUP[grp]
        )

    m.Group_New_Energy_in_Period = Expression(
        m.CAPACITY_GROUP_PERIODS, rule=group_new_energy_rule
    )

    def group_total_capacity_rule(mod, grp, prd):
        return sum(
            total_capacity_rule(mod, prj, prd)
            for prj in mod.PROJECTS_IN_CAPACITY_GROUP[grp]
        )

    m.Group_Total_Capacity_in_Period = Expression(
        m.CAPACITY_GROUP_PERIODS, rule=group_total_capacity_rule
    )

    def group_total_energy_rule(mod, grp, prd):
        return sum(
            total_energy_rule(mod, prj, prd)
            for prj in mod.PROJECTS_IN_CAPACITY_GROUP[grp]
        )

    m.Group_Total_Energy_in_Period = Expression(
        m.CAPACITY_GROUP_PERIODS, rule=group_total_energy_rule
    )

    # Constraints
    # Capacity build
    # Limit the min and max amount of new build in a group-period
    m.Max_Group_Capacity_Build_in_Period_Constraint = Constraint(
        m.CAPACITY_GROUP_PERIODS, rule=new_capacity_max_rule
    )

    m.Min_Group_Capacity_Build_in_Period_Constraint = Constraint(
        m.CAPACITY_GROUP_PERIODS, rule=new_capacity_min_rule
    )

    # Limit the min and max amount of total capacity in a group-period
    m.Max_Group_Total_Capacity_in_Period_Constraint = Constraint(
        m.CAPACITY_GROUP_PERIODS, rule=total_capacity_max_rule
    )

    m.Min_Group_Total_Capacity_in_Period_Constraint = Constraint(
        m.CAPACITY_GROUP_PERIODS, rule=total_capacity_min_rule
    )

    # Energy procured
    # Limit the min and max amount of new build in a group-period
    m.Max_Group_Energy_Build_in_Period_Constraint = Constraint(
        m.CAPACITY_GROUP_PERIODS, rule=new_energy_max_rule
    )

    m.Min_Group_Energy__Build_in_Period_Constraint = Constraint(
        m.CAPACITY_GROUP_PERIODS, rule=new_energy_min_rule
    )

    # Limit the min and max amount of total energy in a group-period
    m.Max_Group_Total_Energy_in_Period_Constraint = Constraint(
        m.CAPACITY_GROUP_PERIODS, rule=total_energy_max_rule
    )

    m.Min_Group_Total_Energy_in_Period_Constraint = Constraint(
        m.CAPACITY_GROUP_PERIODS, rule=total_energy_min_rule
    )


# Constraint Formulation Rules
###############################################################################
def new_capacity_max_rule(mod, grp, prd):
    if mod.capacity_group_new_capacity_max[grp, prd] == float("inf"):
        return Constraint.Feasible
    else:
        return (
            mod.Group_New_Capacity_in_Period[grp, prd]
            <= mod.capacity_group_new_capacity_max[grp, prd]
        )


def new_capacity_min_rule(mod, grp, prd):
    if mod.capacity_group_new_capacity_min[grp, prd] == 0:
        return Constraint.Feasible
    else:
        return (
            mod.Group_New_Capacity_in_Period[grp, prd]
            >= mod.capacity_group_new_capacity_min[grp, prd]
        )


def total_capacity_max_rule(mod, grp, prd):
    if mod.capacity_group_total_capacity_max[grp, prd] == float("inf"):
        return Constraint.Feasible
    else:
        return (
            mod.Group_Total_Capacity_in_Period[grp, prd]
            <= mod.capacity_group_total_capacity_max[grp, prd]
        )


def total_capacity_min_rule(mod, grp, prd):
    if mod.capacity_group_total_capacity_min[grp, prd] == 0:
        return Constraint.Feasible
    else:
        return (
            mod.Group_Total_Capacity_in_Period[grp, prd]
            >= mod.capacity_group_total_capacity_min[grp, prd]
        )


# Energy procurement (for energy products only; does not limit output from
# other capacity types)


def new_energy_max_rule(mod, grp, prd):
    if mod.capacity_group_new_capacity_max[grp, prd] == float("inf"):
        return Constraint.Feasible
    else:
        return (
            mod.Group_New_Energy_in_Period[grp, prd]
            <= mod.energy_group_new_energy_max[grp, prd]
        )


def new_energy_min_rule(mod, grp, prd):
    if mod.energy_group_new_energy_min[grp, prd] == 0:
        return Constraint.Feasible
    else:
        return (
            mod.Group_New_Energy_in_Period[grp, prd]
            >= mod.energy_group_new_energy_min[grp, prd]
        )


def total_energy_max_rule(mod, grp, prd):
    if mod.energy_group_total_energy_max[grp, prd] == float("inf"):
        return Constraint.Feasible
    else:
        return (
            mod.Group_Total_Energy_in_Period[grp, prd]
            <= mod.energy_group_total_energy_max[grp, prd]
        )


def total_energy_min_rule(mod, grp, prd):
    if mod.energy_group_total_energy_min[grp, prd] == 0:
        return Constraint.Feasible
    else:
        return (
            mod.Group_Total_Energy_in_Period[grp, prd]
            >= mod.energy_group_total_energy_min[grp, prd]
        )


# Input-Output
###############################################################################


def load_model_data(
    m,
    d,
    data_portal,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """ """
    # Only load data if the input files were written; otehrwise, we won't
    # initialize the components in this module

    req_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "capacity_group_requirements.tab",
    )
    if os.path.exists(req_file):
        data_portal.load(
            filename=req_file,
            index=m.CAPACITY_GROUP_PERIODS,
            param=(
                m.capacity_group_new_capacity_min,
                m.capacity_group_new_capacity_max,
                m.capacity_group_total_capacity_min,
                m.capacity_group_total_capacity_max,
                m.energy_group_new_energy_min,
                m.energy_group_new_energy_max,
                m.energy_group_total_energy_min,
                m.energy_group_total_energy_max,
            ),
        )

    prj_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "capacity_group_projects.tab",
    )
    if os.path.exists(prj_file):
        proj_groups_df = pd.read_csv(prj_file, delimiter="\t")
        proj_groups_dict = {
            g: v["project"].tolist()
            for g, v in proj_groups_df.groupby("capacity_group")
        }
        data_portal.data()["PROJECTS_IN_CAPACITY_GROUP"] = proj_groups_dict


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
    """ """
    req_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "capacity_group_requirements.tab",
    )
    prj_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "capacity_group_projects.tab",
    )

    if os.path.exists(req_file) and os.path.exists(prj_file):
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "results",
                "project_group_capacity.csv",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "capacity_group",
                    "period",
                    "group_new_capacity",
                    "group_total_capacity",
                    "capacity_group_new_capacity_min",
                    "capacity_group_new_capacity_max",
                    "capacity_group_total_capacity_min",
                    "capacity_group_total_capacity_max",
                    "capacity_group_new_max_dual",
                    "capacity_group_new_min_dual",
                    "capacity_group_total_max_dual",
                    "capacity_group_total_min_dual",
                    "capacity_group_new_max_marginal_cost",
                    "capacity_group_new_min_marginal_cost",
                    "capacity_group_total_max_marginal_cost",
                    "capacity_group_total_min_marginal_cost",
                    "group_new_energy",
                    "group_total_energy",
                    "energy_group_new_energy_min",
                    "energy_group_new_energy_max",
                    "energy_group_total_energy_min",
                    "energy_group_total_energy_max",
                    "energy_group_new_max_dual",
                    "energy_group_new_min_dual",
                    "energy_group_total_max_dual",
                    "energy_group_total_min_dual",
                    "energy_group_new_max_marginal_cost",
                    "energy_group_new_min_marginal_cost",
                    "energy_group_total_max_marginal_cost",
                    "energy_group_total_min_marginal_cost",
                ]
            )

            for grp, prd in sorted(m.CAPACITY_GROUP_PERIODS):
                writer.writerow(
                    [
                        grp,
                        prd,
                        value(m.Group_New_Capacity_in_Period[grp, prd]),
                        value(m.Group_Total_Capacity_in_Period[grp, prd]),
                        m.capacity_group_new_capacity_min[grp, prd],
                        m.capacity_group_new_capacity_max[grp, prd],
                        m.capacity_group_total_capacity_min[grp, prd],
                        m.capacity_group_total_capacity_max[grp, prd],
                        (
                            duals_wrapper(
                                m,
                                getattr(
                                    m, "Max_Group_Capacity_Build_in_Period_Constraint"
                                )[grp, prd],
                            )
                            if (grp, prd)
                            in [
                                idx
                                for idx in getattr(
                                    m, "Max_Group_Capacity_Build_in_Period_Constraint"
                                )
                            ]
                            else None
                        ),
                        (
                            duals_wrapper(
                                m,
                                getattr(
                                    m, "Min_Group_Capacity_Build_in_Period_Constraint"
                                )[grp, prd],
                            )
                            if (grp, prd)
                            in [
                                idx
                                for idx in getattr(
                                    m, "Min_Group_Capacity_Build_in_Period_Constraint"
                                )
                            ]
                            else None
                        ),
                        (
                            duals_wrapper(
                                m,
                                (
                                    getattr(
                                        m,
                                        "Max_Group_Total_Capacity_in_Period_Constraint",
                                    )[grp, prd]
                                    if (grp, prd)
                                    in [
                                        idx
                                        for idx in getattr(
                                            m,
                                            "Max_Group_Total_Capacity_in_Period_Constraint",
                                        )
                                    ]
                                    else None
                                ),
                                duals_wrapper(
                                    m,
                                    getattr(
                                        m,
                                        "Min_Group_Total_Capacity_in_Period_Constraint",
                                    )[grp, prd],
                                ),
                            )
                            if (grp, prd)
                            in [
                                idx
                                for idx in getattr(
                                    m, "Min_Group_Total_Capacity_in_Period_Constraint"
                                )
                            ]
                            else None
                        ),
                        (
                            none_dual_type_error_wrapper(
                                duals_wrapper(
                                    m,
                                    getattr(
                                        m,
                                        "Max_Group_Capacity_Build_in_Period_Constraint",
                                    )[grp, prd],
                                ),
                                m.period_objective_coefficient[prd],
                            )
                            if (grp, prd)
                            in [
                                idx
                                for idx in getattr(
                                    m, "Max_Group_Capacity_Build_in_Period_Constraint"
                                )
                            ]
                            else None
                        ),
                        (
                            none_dual_type_error_wrapper(
                                duals_wrapper(
                                    m,
                                    getattr(
                                        m,
                                        "Min_Group_Capacity_Build_in_Period_Constraint",
                                    )[grp, prd],
                                ),
                                m.period_objective_coefficient[prd],
                            )
                            if (grp, prd)
                            in [
                                idx
                                for idx in getattr(
                                    m, "Min_Group_Capacity_Build_in_Period_Constraint"
                                )
                            ]
                            else None
                        ),
                        (
                            none_dual_type_error_wrapper(
                                duals_wrapper(
                                    m,
                                    getattr(
                                        m,
                                        "Max_Group_Total_Capacity_in_Period_Constraint",
                                    )[grp, prd],
                                ),
                                m.period_objective_coefficient[prd],
                            )
                            if (grp, prd)
                            in [
                                idx
                                for idx in getattr(
                                    m, "Max_Group_Total_Capacity_in_Period_Constraint"
                                )
                            ]
                            else None
                        ),
                        (
                            none_dual_type_error_wrapper(
                                duals_wrapper(
                                    m,
                                    getattr(
                                        m,
                                        "Min_Group_Total_Capacity_in_Period_Constraint",
                                    )[grp, prd],
                                ),
                                m.period_objective_coefficient[prd],
                            )
                            if (grp, prd)
                            in [
                                idx
                                for idx in getattr(
                                    m, "Min_Group_Total_Capacity_in_Period_Constraint"
                                )
                            ]
                            else None
                        ),
                    ]
                )


# Database
###############################################################################


def get_inputs_from_database(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
):
    """
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    c1 = conn.cursor()
    cap_grp_reqs = c1.execute("""
        SELECT capacity_group, period,
        capacity_group_new_capacity_min, capacity_group_new_capacity_max,
        capacity_group_total_capacity_min, capacity_group_total_capacity_max,
        energy_group_new_energy_min, energy_group_new_energy_max,
        energy_group_total_energy_min, energy_group_total_energy_max
        FROM inputs_project_capacity_group_requirements
        WHERE project_capacity_group_requirement_scenario_id = {}
        """.format(subscenarios.PROJECT_CAPACITY_GROUP_REQUIREMENT_SCENARIO_ID))

    c2 = conn.cursor()
    cap_grp_prj = c2.execute(
        """
        SELECT capacity_group, project
        FROM inputs_project_capacity_groups
        WHERE project_capacity_group_scenario_id = {prj_cap_group_sid}
        AND project in (
            SELECT DISTINCT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {prj_portfolio_sid}
            )
        """.format(
            prj_cap_group_sid=subscenarios.PROJECT_CAPACITY_GROUP_SCENARIO_ID,
            prj_portfolio_sid=subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    return cap_grp_reqs, cap_grp_prj


def write_model_inputs(
    scenario_directory,
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
):
    """ """

    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )

    cap_grp_reqs, cap_grp_prj = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # Write the input files only if a subscenario is specified
    if subscenarios.PROJECT_CAPACITY_GROUP_REQUIREMENT_SCENARIO_ID != "NULL":
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "capacity_group_requirements.tab",
            ),
            "w",
            newline="",
        ) as req_file:
            writer = csv.writer(req_file, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(
                [
                    "capacity_group",
                    "period",
                    "capacity_group_new_capacity_min",
                    "capacity_group_new_capacity_max",
                    "capacity_group_total_capacity_min",
                    "capacity_group_total_capacity_max",
                    "energy_group_new_energy_min",
                    "energy_group_new_energy_max",
                    "energy_group_total_energy_min",
                    "energy_group_total_energy_max",
                ]
            )

            for row in cap_grp_reqs:
                replace_nulls = ["." if i is None else i for i in row]
                writer.writerow(replace_nulls)

    if subscenarios.PROJECT_CAPACITY_GROUP_SCENARIO_ID != "NULL":
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "capacity_group_projects.tab",
            ),
            "w",
            newline="",
        ) as prj_file:
            writer = csv.writer(prj_file, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(["capacity_group", "project"])

            for row in cap_grp_prj:
                writer.writerow(row)


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
    which_results = "project_group_capacity"
    # Import only if a results-file was exported
    results_file = os.path.join(results_directory, f"{which_results}.csv")
    if os.path.exists(results_file):
        import_csv(
            conn=db,
            cursor=c,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            quiet=quiet,
            results_directory=results_directory,
            which_results=which_results,
        )
