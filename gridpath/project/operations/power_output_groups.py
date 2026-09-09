# Copyright 2026 Sylvan Energy Analytics LLC.
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
Minimum and maximum total power output by period and project group.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Set, Param, Constraint, NonNegativeReals, Expression, value

from gridpath.auxiliary.auxiliary import get_required_subtype_modules
from gridpath.common_functions import duals_wrapper, none_dual_type_error_wrapper
from gridpath.project.operations.common_functions import (
    load_operational_type_modules,
)
from gridpath.auxiliary.db_interface import import_csv, directories_to_db_values
import gridpath.project.operations.operational_types as optype_init
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)


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
    | | :code:`POWER_OUTPUT_GROUP_PERIODS`                                    |
    |                                                                         |
    | A two-dimensional set of group-period combinations for which there may  |
    | be group power output requirements.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`POWER_OUTPUT_GROUPS`                                           |
    |                                                                         |
    | The groups of projects for which there may be group power output        |
    | requirements.                                                           |
    +-------------------------------------------------------------------------+
    | | :code:`POWER_OUTPUT_GROUP_TMPS`                                       |
    |                                                                         |
    | A two-dimensional set of group-timepoint combinations for which power   |
    | output constraints are enforced.                                        |
    +-------------------------------------------------------------------------+
    | | :code:`PROJECTS_IN_POWER_OUTPUT_GROUP`                                |
    |                                                                         |
    | The list of projects by power output group.                             |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`power_output_group_power_output_min`                           |
    | | *Defined over*: :code:`POWER_OUTPUT_GROUP_PERIODS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The minimum amount of power (in MW) that projects in a group can       |
    | produce in any timepoint in a certain period.                           |
    +-------------------------------------------------------------------------+
    | | :code:`power_output_group_power_output_max`                           |
    | | *Defined over*: :code:`POWER_OUTPUT_GROUP_PERIODS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`inf`                                                |
    |                                                                         |
    | The maximum amount of power (in MW) that projects in a group can       |
    | produce in any timepoint in a certain period.                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Group_Total_Power_in_Tmp`                                     |
    | | *Defined over*: :code:`POWER_OUTPUT_GROUP_TMPS`                      |
    |                                                                         |
    | Total power output from the group in a timepoint.                       |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Max_Group_Total_Power_in_Tmp_Constraint`                      |
    | | *Defined over*: :code:`POWER_OUTPUT_GROUP_TMPS`                      |
    |                                                                         |
    | Limits the maximum amount of power output from each group in each      |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`Min_Group_Total_Power_in_Tmp_Constraint`                      |
    | | *Defined over*: :code:`POWER_OUTPUT_GROUP_TMPS`                      |
    |                                                                         |
    | Limits the minimum amount of power output from each group in each      |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+

    """

    # Sets
    m.POWER_OUTPUT_GROUP_PERIODS = Set(dimen=2)

    m.POWER_OUTPUT_GROUPS = Set(
        initialize=lambda mod: sorted(
            list(set([g for (g, p) in mod.POWER_OUTPUT_GROUP_PERIODS]))
        )
    )

    m.POWER_OUTPUT_GROUP_TMPS = Set(
        dimen=2,
        initialize=lambda mod: [
            (g, tmp)
            for (g, prd) in (mod.POWER_OUTPUT_GROUP_PERIODS)
            for tmp in mod.TMPS_IN_PRD[prd]
        ],
    )

    m.PROJECTS_IN_POWER_OUTPUT_GROUP = Set(m.POWER_OUTPUT_GROUPS, within=m.PROJECTS)

    # Params
    m.power_output_group_power_output_min = Param(
        m.POWER_OUTPUT_GROUP_PERIODS, within=NonNegativeReals, default=0
    )
    m.power_output_group_power_output_max = Param(
        m.POWER_OUTPUT_GROUP_PERIODS, within=NonNegativeReals, default=float("inf")
    )

    # Import needed capacity type modules
    required_operational_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="operational_type",
    )

    imported_operational_modules = load_operational_type_modules(
        required_operational_modules
    )

    def power_output_rule(mod, prj, tmp):
        optype = mod.operational_type[prj]
        # Return the capacity type's capacity rule if the project is
        # operational in this timepoint; otherwise, return 0
        if (prj, tmp) not in mod.PRJ_OPR_TMPS:
            return 0
        else:
            if hasattr(imported_operational_modules[optype], "power_provision_rule"):
                return imported_operational_modules[optype].power_provision_rule(
                    mod, prj, tmp
                )
            else:
                return optype_init.power_provision_rule(mod, prj, tmp)

    # Expressions
    def group_power_output_rule(mod, grp, tmp):
        return sum(
            power_output_rule(mod, prj, tmp)
            for prj in mod.PROJECTS_IN_POWER_OUTPUT_GROUP[grp]
        )

    m.Group_Total_Power_in_Tmp = Expression(
        m.POWER_OUTPUT_GROUP_TMPS, rule=group_power_output_rule
    )

    # Constraints
    # Capacity build
    # Limit the min and max amount of total capacity in a group-tmp
    m.Max_Group_Total_Power_in_Tmp_Constraint = Constraint(
        m.POWER_OUTPUT_GROUP_TMPS, rule=power_output_max_rule
    )

    m.Min_Group_Total_Power_in_Tmp_Constraint = Constraint(
        m.POWER_OUTPUT_GROUP_TMPS, rule=power_output_min_rule
    )


# Constraint Formulation Rules
###############################################################################


def power_output_max_rule(mod, grp, tmp):
    if mod.power_output_group_power_output_max[grp, mod.period[tmp]] == float("inf"):
        return Constraint.Feasible
    else:
        return (
            mod.Group_Total_Power_in_Tmp[grp, tmp]
            <= mod.power_output_group_power_output_max[grp, mod.period[tmp]]
        )


def power_output_min_rule(mod, grp, tmp):
    if mod.power_output_group_power_output_min[grp, mod.period[tmp]] == float("-inf"):
        return Constraint.Feasible
    else:
        return (
            mod.Group_Total_Power_in_Tmp[grp, tmp]
            >= mod.power_output_group_power_output_min[grp, mod.period[tmp]]
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
    """
    Load power output group data from tab files.
    """
    # Only load data if the input files were written; otherwise, we won't
    # initialize the components in this module

    req_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "power_output_group_requirements.tab",
    )
    if os.path.exists(req_file):
        data_portal.load(
            filename=req_file,
            index=m.POWER_OUTPUT_GROUP_PERIODS,
            param=(
                m.power_output_group_power_output_min,
                m.power_output_group_power_output_max,
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
        "power_output_group_projects.tab",
    )
    if os.path.exists(prj_file):
        proj_groups_df = pd.read_csv(prj_file, delimiter="\t")
        proj_groups_dict = {
            g: v["project"].tolist()
            for g, v in proj_groups_df.groupby("power_output_group")
        }
        data_portal.data()["PROJECTS_IN_POWER_OUTPUT_GROUP"] = proj_groups_dict


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
    pwr_grp_reqs = c1.execute("""
        SELECT power_output_group, period,
        power_output_group_total_power_min, power_output_group_total_power_max
        FROM inputs_project_power_output_group_requirements
        WHERE project_power_output_group_requirement_scenario_id = {}
        """.format(subscenarios.PROJECT_POWER_OUTPUT_GROUP_REQUIREMENT_SCENARIO_ID))

    c2 = conn.cursor()
    pwr_grp_prj = c2.execute(
        """
        SELECT power_output_group, project
        FROM inputs_project_power_output_groups
        WHERE project_power_output_group_scenario_id = {prj_cap_group_sid}
        AND project in (
            SELECT DISTINCT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {prj_portfolio_sid}
            )
        """.format(
            prj_cap_group_sid=subscenarios.PROJECT_POWER_OUTPUT_GROUP_SCENARIO_ID,
            prj_portfolio_sid=subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    return pwr_grp_reqs, pwr_grp_prj


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
    """
    Write power output group model inputs from database to tab files.
    """

    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )

    pwr_grp_reqs, pwr_grp_prj = get_inputs_from_database(
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
    if subscenarios.PROJECT_POWER_OUTPUT_GROUP_REQUIREMENT_SCENARIO_ID != "NULL":
        write_tab_file_model_inputs(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            fname="power_output_group_requirements.tab",
            data=pwr_grp_reqs,
            replace_nulls=True,
        )

    if subscenarios.PROJECT_POWER_OUTPUT_GROUP_SCENARIO_ID != "NULL":
        write_tab_file_model_inputs(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            fname="power_output_group_projects.tab",
            data=pwr_grp_prj,
        )
