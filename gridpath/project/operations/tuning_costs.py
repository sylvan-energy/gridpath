# Copyright 2016-2025 Blue Marble Analytics LLC.
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
Operational tuning costs that prevent erratic dispatch in case of degeneracy.
Tuning costs can be applied to hydro up and down ramps (gen_hydro
and gen_hydro_must_take operational types) and to storage up-ramps (
stor operational type) in order to force smoother dispatch.
"""

import csv
import os.path
from pyomo.environ import Param, Set, Var, Expression, Constraint, NonNegativeReals

from gridpath.auxiliary.auxiliary import get_required_subtype_modules
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.project.operations.common_functions import load_operational_type_modules
from gridpath.project.common_functions import check_if_boundary_type_and_first_timepoint


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
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Ramp_Up_Tuning_Cost`                                           |
    | | *Defined over*: :code:`PRJ_OPR_TMPS`                                  |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | This variable represents the total upward ramping tuning cost for each  |
    | project in each operational timepoint.                                  |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Up_Tuning_Cost`                                           |
    | | *Defined over*: :code:`PRJ_OPR_TMPS`                                  |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | This variable represents the total downwward ramping tuning cost for    |
    | each project in each operational timepoint.                             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Ramp_Expression`                                               |
    | | *Defined over*: :code:`PRJ_OPR_TMPS`                                  |
    |                                                                         |
    | This expression pulls the ramping expression from the appropriate       |
    | operational type module. It represents the difference in power output   |
    | (in MW) between 2 timepoints; i.e. a positive number means upward ramp  |
    | and a negative number means downward ramp. For simplicity, we only look |
    | at the difference in power setpoints, i.e. ignore the effect of         |
    | providing any reserves.                                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Ramp_Up_Tuning_Cost_Constraint`                                |
    | | *Defined over*: :code:`PRJ_OPR_TMPS`                                  |
    |                                                                         |
    | Sets the upward ramping tuning cost to be equal to the ramp expression  |
    | times the tuning cost (for the appropriate operational types only).     |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Down_Tuning_Cost_Constraint`                              |
    | | *Defined over*: :code:`PRJ_OPR_TMPS`                                  |
    |                                                                         |
    | Sets the downward ramping tuning cost to be equal to the ramp           |
    | expression times the tuning cost (for the appropriate operational types |
    | only).                                                                  |
    +-------------------------------------------------------------------------+

    """

    # Dynamic Inputs
    ###########################################################################

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

    # Sets
    ###########################################################################

    # The tuning cost components are only needed for projects with a
    # nonzero ramp tuning cost, so define them over those projects'
    # operational timepoints only, not all of PRJ_OPR_TMPS
    m.TUNING_COST_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=tuning_cost_prj_opr_tmps_init,
    )

    # Expressions
    ###########################################################################

    # Resolve each op type's power delta rule once, not per index
    power_delta_rule_by_op_type = {
        op_m: imported_operational_modules[op_m].power_delta_rule
        for op_m in required_operational_modules
    }

    def ramp_rule(mod, g, tmp):
        return power_delta_rule_by_op_type[mod.operational_type[g]](mod, g, tmp)

    m.Ramp_Expression = Expression(m.TUNING_COST_PRJ_OPR_TMPS, rule=ramp_rule)

    # Variables
    ###########################################################################

    m.Ramp_Up_Tuning_Cost = Var(m.TUNING_COST_PRJ_OPR_TMPS, within=NonNegativeReals)

    m.Ramp_Down_Tuning_Cost = Var(m.TUNING_COST_PRJ_OPR_TMPS, within=NonNegativeReals)

    # Constraints
    ###########################################################################

    m.Ramp_Up_Tuning_Cost_Constraint = Constraint(
        m.TUNING_COST_PRJ_OPR_TMPS, rule=ramp_up_rule
    )

    m.Ramp_Down_Tuning_Cost_Constraint = Constraint(
        m.TUNING_COST_PRJ_OPR_TMPS, rule=ramp_down_rule
    )


# Set Rules
###############################################################################


def tuning_cost_prj_opr_tmps_init(mod):
    """
    Projects with a nonzero ramp tuning cost and their operational
    timepoints (mirrors how PRJ_OPR_TMPS is constructed).
    """
    tuning_cost_prjs = [
        prj for prj in mod.PROJECTS if mod.ramp_tuning_cost_per_mw[prj] != 0
    ]

    return [
        (prj, tmp)
        for prj in tuning_cost_prjs
        for prd in mod.OPR_PRDS_BY_PRJ[prj]
        for tmp in mod.TMPS_IN_PRD[prd]
    ]


# Constraint Rules
###############################################################################


def ramp_up_rule(mod, prj, tmp):
    """
    **Constraint Name**: Ramp_Up_Tuning_Cost_Constraint
    **Enforced Over**: PRJ_OPR_TMPS
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[prj],
        boundary_type="linear",
    ):
        return Constraint.Skip
    elif mod.ramp_tuning_cost_per_mw[prj] == 0:
        return Constraint.Skip
    else:
        return (
            mod.Ramp_Up_Tuning_Cost[prj, tmp]
            >= mod.Ramp_Expression[prj, tmp] * mod.ramp_tuning_cost_per_mw[prj]
        )


def ramp_down_rule(mod, prj, tmp):
    """
    **Constraint Name**: Ramp_Down_Tuning_Cost_Constraint
    **Enforced Over**: PRJ_OPR_TMPS
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[prj],
        boundary_type="linear",
    ):
        return Constraint.Skip
    elif mod.ramp_tuning_cost_per_mw[prj] == 0:
        return Constraint.Skip
    else:
        return (
            mod.Ramp_Down_Tuning_Cost[prj, tmp]
            >= mod.Ramp_Expression[prj, tmp] * -mod.ramp_tuning_cost_per_mw[prj]
        )


# Validation
###############################################################################


def validate_inputs(
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
    Get inputs from database and validate the inputs
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    # ramp_tuning_cost = get_inputs_from_database(
    #     scenario_id, subscenarios, subproblem, stage, conn)

    # do stuff here to validate inputs
