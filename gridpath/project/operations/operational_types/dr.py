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
.. note:: THIS MODULE IS DEPRECATED
This operational type describes a demand response (DR) project that can
shift load across timepoints, e.g. a building pre-cooling program or an
electric vehicle smart-charging program. There are two operational variables
in each timepoint: one for shifting load up (adding load) and another for
shifting load down (subtracting load). These cannot exceed the power capacity
of the project and must meet an energy balance constraint on each horizon.
Efficiency losses are not currently implemented.

"""

from pyomo.environ import Var, Set, Param, Constraint, NonNegativeReals

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    validate_opchars,
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
    | | :code:`DR`                                                            |
    |                                                                         |
    | The set of projects of the :code:`dr` operational type.                 |
    +-------------------------------------------------------------------------+
    | | :code:`DR_OPR_TMPS`                                                   |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`dr`                     |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`DR_OPR_HRZS`                                                   |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`dr`                     |
    | operational type and their operational horizons.                        |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`DR_Shift_Up_MW`                                                |
    | | *Defined over*: :code:`DR_OPR_TMPS`                                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Load added (in MW) in each operational timepoint.                       |
    +-------------------------------------------------------------------------+
    | | :code:`DR_Shift_Down_MW`                                              |
    | | *Defined over*: :code:`DR_OPR_TMPS`                                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Load removed (in MW) in each operational timepoint.                     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`DR_Max_Shift_Up_Constraint`                                    |
    | | *Defined over*: :code:`DR_OPR_TMPS`                                   |
    |                                                                         |
    | Limits the added load to the available power capacity.                  |
    +-------------------------------------------------------------------------+
    | | :code:`DR_Max_Shift_Down_Constraint`                                  |
    | | *Defined over*: :code:`DR_OPR_TMPS`                                   |
    |                                                                         |
    | Limits the removed load to the available power capacity.                |
    +-------------------------------------------------------------------------+
    | | :code:`DR_Energy_Balance_Constraint`                                  |
    | | *Defined over*: :code:`DR_OPR_HRZS`                                   |
    |                                                                         |
    | Ensures no energy losses or gains when shifting load within the horizon.|
    +-------------------------------------------------------------------------+
    | | :code:`DR_Energy_Budget_Constraint`                                   |
    | | *Defined˚ over*: :code:`DR_OPR_HRZS`                                  |
    |                                                                         |
    | Total energy that can be shifted on each horizon should be less than    |
    | or equal to budget.                                                     |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.DR = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "dr"
        ),
    )

    m.DR_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.DR
        ),
    )

    m.DR_OPR_HRZS = Set(
        dimen=2,
        initialize=lambda mod: list(
            set(
                (g, mod.horizon[tmp, mod.balancing_type_project[g]])
                for (g, tmp) in mod.PRJ_OPR_TMPS
                if g in mod.DR
            )
        ),
    )

    # Variables
    ###########################################################################

    m.DR_Shift_Up_MW = Var(m.DR_OPR_TMPS, within=NonNegativeReals)

    m.DR_Shift_Down_MW = Var(m.DR_OPR_TMPS, within=NonNegativeReals)

    # Constraints
    ###########################################################################

    m.DR_Max_Shift_Up_Constraint = Constraint(m.DR_OPR_TMPS, rule=max_shift_up_rule)

    m.DR_Max_Shift_Down_Constraint = Constraint(m.DR_OPR_TMPS, rule=max_shift_down_rule)

    m.DR_Energy_Balance_Constraint = Constraint(m.DR_OPR_HRZS, rule=energy_balance_rule)

    m.DR_Energy_Budget_Constraint = Constraint(m.DR_OPR_HRZS, rule=energy_budget_rule)


# Constraint Formulation Rules
###############################################################################


def max_shift_up_rule(mod, p, tmp):
    """
    **Constraint Name**: DR_Max_Shift_Up_Constraint
    **Enforced Over**: DR_OPR_TMPS

    Limits the added load to the available power capacity.
    """
    return (
        mod.DR_Shift_Up_MW[p, tmp]
        <= mod.Capacity_MW[p, mod.period[tmp]] * mod.Availability_Derate[p, tmp]
    )


def max_shift_down_rule(mod, p, tmp):
    """
    **Constraint Name**: DR_Max_Shift_Down_Constraint
    **Enforced Over**: DR_OPR_TMPS

    Limits the removed load to the available power capacity.
    """
    return (
        mod.DR_Shift_Down_MW[p, tmp]
        <= mod.Capacity_MW[p, mod.period[tmp]] * mod.Availability_Derate[p, tmp]
    )


def energy_balance_rule(mod, p, h):
    """
    **Constraint Name**: DR_Energy_Balance_Constraint
    **Enforced Over**: DR_OPR_HRZS

    The sum of all shifted load up is equal to the sum of all shifted load
    down within an horizon, i.e. there are no energy losses or gains.
    """
    return sum(
        mod.DR_Shift_Up_MW[p, tmp]
        for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[mod.balancing_type_project[p], h]
    ) == sum(
        mod.DR_Shift_Down_MW[p, tmp]
        for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[mod.balancing_type_project[p], h]
    )


def energy_budget_rule(mod, p, h):
    """
    **Constraint Name**: DR_Energy_Budget_Constraint
    **Enforced Over**: DR_OPR_HRZS

    Total energy that can be shifted on each horizon should be less than or
    equal to budget.

    Get the period for the total capacity from the first timepoint of the
    horizon.
    """
    return (
        sum(
            mod.DR_Shift_Up_MW[p, tmp] * mod.hrs_in_tmp[tmp]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[mod.balancing_type_project[p], h]
        )
        <= mod.Energy_Storage_Capacity_MWh[
            p, mod.period[mod.first_hrz_tmp[mod.balancing_type_project[p], h]]
        ]
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, p, tmp):
    """
    Provided power to the system is the load shifted down minus the load
    shifted up.
    """
    return mod.DR_Shift_Down_MW[p, tmp] - mod.DR_Shift_Up_MW[p, tmp]


def power_delta_rule(mod, p, tmp):
    """
    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint.
    """
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[p]
    ) and (
        check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[p],
            boundary_type="linear",
        )
        or check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[p],
            boundary_type="linked",
        )
    ):
        pass
    else:
        return (mod.DR_Shift_Up_MW[p, tmp] - mod.DR_Shift_Down_MW[p, tmp]) - (
            mod.DR_Shift_Up_MW[p, mod.prev_tmp[tmp, mod.balancing_type_project[p]]]
            - mod.DR_Shift_Down_MW[p, mod.prev_tmp[tmp, mod.balancing_type_project[p]]]
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

    # Validate operational chars table inputs
    validate_opchars(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "dr",
    )
