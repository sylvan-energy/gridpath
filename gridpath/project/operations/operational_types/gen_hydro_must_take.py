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
This operational type describes the operations of hydro generation
projects and is like the *gen_hydro* operational type except that the power
output is must-take, i.e. curtailment is not allowed. Negative output is
allowed, i.e. this module can be used to model pumping.

"""

import csv
import os.path
from pyomo.environ import (
    Var,
    Set,
    Param,
    Constraint,
    Expression,
    NonNegativeReals,
    PercentFraction,
    value,
    Reals,
)
import warnings

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import headroom_variables, footroom_variables
from gridpath.project.operations.reserves.reserve_aggregation import (
    headroom_provision_rule,
    footroom_provision_rule,
)
from gridpath.project.common_functions import (
    check_if_boundary_type_and_first_timepoint,
    check_if_first_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_optype_model_data,
    load_hydro_opchars,
    write_tab_file_model_inputs,
    check_for_tmps_to_link,
    validate_opchars,
    validate_hydro_opchars,
    get_prj_temporal_index_opr_inputs_from_db,
    BT_HRZ_INDEX_QUERY_PARAMS,
)
from gridpath.common_functions import create_results_df


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
    | | :code:`GEN_HYDRO_MUST_TAKE`                                           |
    |                                                                         |
    | The set of generators of the :code:`gen_hydro_must_take` operational    |
    | type.                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS`                               |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_hydro_must_take`  |
    | operational type and their operational horizons.                        |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_HYDRO_MUST_TAKE_OPR_TMPS`                                  |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_hydro_must_take`  |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_HYDRO_MUST_TAKE_LINKED_TMPS`                               |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_hydro_must_take`  |
    | operational type and their linked timepoints.                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_hydro_must_take_max_power_fraction`                        |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS`               |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The project's maximum power output in each operational horizon as a     |
    | fraction of its available capacity.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`gen_hydro_must_take_min_power_fraction`                        |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS`               |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The project's minimum power output in each operational horizon as a     |
    | fraction of its available capacity.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`gen_hydro_must_take_average_power_fraction`                    |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS`               |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The project's avarage power output in each operational horizon as a     |
    | fraction of its available capacity. This can be interpreted as the      |
    | project's average capacity factor or plant load factor.                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_hydro_must_take_ramp_up_when_on_rate`                      |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE`                           |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`inf`                                                |
    |                                                                         |
    | The project's upward ramp rate limit during operations, defined as a    |
    | fraction of its capacity per minute.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_hydro_must_take_ramp_down_when_on_rate`                    |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE`                           |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`inf`                                                |
    |                                                                         |
    | The project's downward ramp rate limit during operations, defined as a  |
    | fraction of its capacity per minute.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_hydro_must_take_aux_consumption_frac_capacity`             |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE`                           |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of capacity. This would be          |
    | incurred in all timepoints when capacity is available.                  |
    +-------------------------------------------------------------------------+
    | | :code:`gen_hydro_must_take_aux_consumption_frac_power`                |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE`                           |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of gross power output.              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Linked Input Params                                                     |
    +=========================================================================+
    | | :code:`gen_hydro_must_take_linked_power`                              |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_LINKED_TMPS`               |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The project's power provision in the linked timepoints.                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_hydro_must_take_linked_upwards_reserves`                   |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_LINKED_TMPS`               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's upward reserve provision in the linked timepoints.        |
    +-------------------------------------------------------------------------+
    | | :code:`gen_hydro_must_take_linked_downwards_reserves`                 |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_LINKED_TMPS`               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's downward reserve provision in the linked timepoints.      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenHydroMustTake_Gross_Power_MW`                               |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_TMPS`                  |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | Power provision in MW from this project in each timepoint in which the  |
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`GenHydroMustTake_Auxiliary_Consumption_MW`                     |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_TMPS`                  |
    |                                                                         |
    | The project's auxiliary consumption (power consumed on-site and not     |
    | sent to the grid) in each timepoint.                                    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Power                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenHydroMustTake_Max_Power_Constraint`                         |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS`               |
    |                                                                         |
    | Limits the power plus upward reserves based on the                      |
    | :code:`gen_hydro_must_take_max_power_fraction` and the available        |
    | capacity.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`GenHydroMustTake_Min_Power_Constraint`                         |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS`               |
    |                                                                         |
    | Power provision minus downward reserves should exceed a certain level   |
    | based on the :code:`gen_hydro_must_take_min_power_fraction` and the     |
    | available capacity.                                                     |
    +-------------------------------------------------------------------------+
    | | :code:`GenHydroMustTake_Energy_Budget_Constraint`                     |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS`               |
    |                                                                         |
    | The project's average capacity factor in each operational horizon,      |
    | should match the specified                                              |
    | :code:`gen_hydro_must_take_average_power_fraction`.                     |
    +-------------------------------------------------------------------------+
    | Ramps                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenHydroMustTake_Ramp_Up_Constraint`                           |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_TMPS`                  |
    |                                                                         |
    | Limits the allowed project upward ramp based on the                     |
    | :code:`gen_hydro_must_take_ramp_up_when_on_rate`.                       |
    +-------------------------------------------------------------------------+
    | | :code:`GenHydroMustTake_Ramp_Down_Constraint`                         |
    | | *Defined over*: :code:`GEN_HYDRO_MUST_TAKE_OPR_TMPS`                  |
    |                                                                         |
    | Limits the allowed project downward ramp based on the                   |
    | :code:`gen_hydro_must_take_ramp_down_when_on_rate`.                     |
    +-------------------------------------------------------------------------+

    """
    # Sets
    ###########################################################################

    m.GEN_HYDRO_MUST_TAKE = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_hydro_must_take"
        ),
    )

    m.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS = Set(dimen=3)

    m.GEN_HYDRO_MUST_TAKE_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.GEN_HYDRO_MUST_TAKE,
        ),
    )

    m.GEN_HYDRO_MUST_TAKE_OPR_PRDS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_PRDS",
            index=0,
            membership_set=mod.GEN_HYDRO_MUST_TAKE,
        ),
    )

    m.GEN_HYDRO_MUST_TAKE_LINKED_TMPS = Set(dimen=2)

    # Required Params
    ###########################################################################

    m.gen_hydro_must_take_max_power_fraction = Param(
        m.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS, within=Reals
    )

    m.gen_hydro_must_take_min_power_fraction = Param(
        m.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS, within=Reals
    )

    m.gen_hydro_must_take_average_power_fraction = Param(
        m.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS, within=Reals
    )

    # Optional Params
    ###########################################################################

    m.gen_hydro_must_take_ramp_up_when_on_rate = Param(
        m.GEN_HYDRO_MUST_TAKE, within=NonNegativeReals, default=float("inf")
    )

    m.gen_hydro_must_take_ramp_down_when_on_rate = Param(
        m.GEN_HYDRO_MUST_TAKE, within=NonNegativeReals, default=float("inf")
    )

    m.gen_hydro_must_take_ramp_up_when_on_rate_monthly_adjustment = Param(
        m.GEN_HYDRO_MUST_TAKE_OPR_PRDS, m.MONTHS, within=NonNegativeReals, default=1
    )

    m.gen_hydro_must_take_ramp_down_when_on_rate_monthly_adjustment = Param(
        m.GEN_HYDRO_MUST_TAKE_OPR_PRDS, m.MONTHS, within=NonNegativeReals, default=1
    )

    m.gen_hydro_must_take_aux_consumption_frac_capacity = Param(
        m.GEN_HYDRO_MUST_TAKE, within=PercentFraction, default=0
    )

    m.gen_hydro_must_take_aux_consumption_frac_power = Param(
        m.GEN_HYDRO_MUST_TAKE, within=PercentFraction, default=0
    )

    # Linked Params
    ###########################################################################

    m.gen_hydro_must_take_linked_power = Param(
        m.GEN_HYDRO_MUST_TAKE_LINKED_TMPS, within=Reals
    )

    m.gen_hydro_must_take_linked_upwards_reserves = Param(
        m.GEN_HYDRO_MUST_TAKE_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_hydro_must_take_linked_downwards_reserves = Param(
        m.GEN_HYDRO_MUST_TAKE_LINKED_TMPS, within=NonNegativeReals
    )

    # Variables
    ###########################################################################

    m.GenHydroMustTake_Gross_Power_MW = Var(
        m.GEN_HYDRO_MUST_TAKE_OPR_TMPS, within=Reals
    )

    # Expressions
    ###########################################################################

    def upwards_reserve_rule(mod, g, tmp):
        return headroom_provision_rule(d, mod, g, tmp)

    m.GenHydroMustTake_Upwards_Reserves_MW = Expression(
        m.GEN_HYDRO_MUST_TAKE_OPR_TMPS, rule=upwards_reserve_rule
    )

    def downwards_reserve_rule(mod, g, tmp):
        return footroom_provision_rule(d, mod, g, tmp)

    m.GenHydroMustTake_Downwards_Reserves_MW = Expression(
        m.GEN_HYDRO_MUST_TAKE_OPR_TMPS, rule=downwards_reserve_rule
    )

    def auxiliary_consumption_rule(mod, g, tmp):
        """
        **Expression Name**: GenHydroMustTake_Auxiliary_Consumption_MW
        **Defined Over**: GEN_HYDRO_MUST_TAKE_OPR_TMPS
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * mod.gen_hydro_must_take_aux_consumption_frac_capacity[g]
            + mod.GenHydroMustTake_Gross_Power_MW[g, tmp]
            * mod.gen_hydro_must_take_aux_consumption_frac_power[g]
        )

    m.GenHydroMustTake_Auxiliary_Consumption_MW = Expression(
        m.GEN_HYDRO_MUST_TAKE_OPR_TMPS, rule=auxiliary_consumption_rule
    )

    # Constraints
    ###########################################################################

    m.GenHydroMustTake_Max_Power_Constraint = Constraint(
        m.GEN_HYDRO_MUST_TAKE_OPR_TMPS, rule=max_power_rule
    )

    m.GenHydroMustTake_Min_Power_Constraint = Constraint(
        m.GEN_HYDRO_MUST_TAKE_OPR_TMPS, rule=min_power_rule
    )

    m.GenHydroMustTake_Energy_Budget_Constraint = Constraint(
        m.GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS, rule=energy_budget_rule
    )

    m.GenHydroMustTake_Ramp_Up_Constraint = Constraint(
        m.GEN_HYDRO_MUST_TAKE_OPR_TMPS, rule=ramp_up_rule
    )

    m.GenHydroMustTake_Ramp_Down_Constraint = Constraint(
        m.GEN_HYDRO_MUST_TAKE_OPR_TMPS, rule=ramp_down_rule
    )


# Constraint Formulation Rules
###############################################################################


def max_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenHydroMustTake_Max_Power_Constraint
    **Enforced Over**: GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS

    Power plus upward reserves shall not exceed the maximum power output.
    The maximum power output (fraction) is a user input that is specified
    by horizon. If the unit is unavailable, it will be further de-rated.

    Example: The maximum power is 90% of the installed capacity in horizon
    1, which represents a winter week. If the installed capacity during the
    timepoint (period) of interest (which can be a user input or a decision
    variable, depending on the capacity type) is 1,000 MW and the project is
    fully available, the project's maximum power output is 900 MW.
    """
    return (
        mod.GenHydroMustTake_Gross_Power_MW[g, tmp]
        + mod.GenHydroMustTake_Upwards_Reserves_MW[g, tmp]
        <= mod.gen_hydro_must_take_max_power_fraction[
            g,
            mod.balancing_type_project[g],
            mod.horizon[tmp, mod.balancing_type_project[g]],
        ]
        * mod.Capacity_MW[g, mod.period[tmp]]
        * mod.Availability_Derate[g, tmp]
    )


def min_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenHydroMustTake_Min_Power_Constraint
    **Enforced Over**: GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS

    Power minus downward reserves must exceed the minimum power output.
    The minimum power output (fraction) is a user input that is specified
    by horizon. If the unit is unavailable, it will be further de-rated.

    Example: The minimum power is 30% of the installed capacity in horizon
    1, which represents a winter week. If the installed capacity during the
    timepoint (period) of interest (which can be a user input or a decision
    variable, depending on the capacity type) is 1,000 MW and the project is
    fully available, the project's minimum power output is 300 MW.
    """
    return (
        mod.GenHydroMustTake_Gross_Power_MW[g, tmp]
        - mod.GenHydroMustTake_Downwards_Reserves_MW[g, tmp]
        >= mod.gen_hydro_must_take_min_power_fraction[
            g,
            mod.balancing_type_project[g],
            mod.horizon[tmp, mod.balancing_type_project[g]],
        ]
        * mod.Capacity_MW[g, mod.period[tmp]]
        * mod.Availability_Derate[g, tmp]
    )


def energy_budget_rule(mod, g, bt, h):
    """
    **Constraint Name**: GenHydroMustTake_Energy_Budget_Constraint
    **Enforced Over**: GEN_HYDRO_MUST_TAKE_OPR_BT_HRZS

    The sum of hydro energy output within a horizon must match the horizon's
    hydro energy budget. The budget is calculated by multiplying the
    user-specified average power fraction (i.e. the average capacity factor)
    for that horizon with the product of the matching period's installed
    capacity (which can be a user input or a decision variable, depending on
    the capacity type), the number of hours in that horizon, and any
    availability derates if applicable.

    WARNING: If there are any availability derates, this means the effective
    average power fraction (and associated energy budget) will be lower than
    the user-specified input!

    Example: The average power fraction is 50% of the installed capacity in
    horizon 1, which represents a winter week. If the installed capacity
    during the period of interest is 1,000 MW, there are 168 hours in
    the horizon (1 week), and the unit is fully available, the hydro budget
    for this horizon is 0.5 * 1,000 MW * 168 h = 84,000 MWh.
    If the unit were unavailable for half of the timepoints in that horizon,
    the budget would be half, i.e. 42,000 MWh, even though the average power
    fraction is the same!
    """
    return sum(
        mod.GenHydroMustTake_Gross_Power_MW[g, tmp] * mod.hrs_in_tmp[tmp]
        for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
    ) == sum(
        mod.gen_hydro_must_take_average_power_fraction[g, bt, h]
        * mod.Capacity_MW[g, mod.period[tmp]]
        * mod.Availability_Derate[g, tmp]
        * mod.hrs_in_tmp[tmp]
        for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
    )


def ramp_up_rule(mod, g, tmp):
    """
    **Constraint Name**: GenHydroMustTake_Ramp_Up_Constraint
    **Enforced Over**: GEN_HYDRO_MUST_TAKE_OPR_TMPS

    Difference between power generation of consecutive timepoints, adjusted
    for reserve provision in current and previous timepoint, has to obey
    ramp up rate limits.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_power = mod.gen_hydro_must_take_linked_power[g, 0]
            prev_tmp_downwards_reserves = (
                mod.gen_hydro_must_take_linked_downwards_reserves[g, 0]
            )
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_power = mod.GenHydroMustTake_Gross_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_downwards_reserves = mod.GenHydroMustTake_Downwards_Reserves_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]

        if mod.gen_hydro_must_take_ramp_up_when_on_rate[g] == float("inf"):
            return Constraint.Skip
        else:
            return (
                mod.GenHydroMustTake_Gross_Power_MW[g, tmp]
                + mod.GenHydroMustTake_Upwards_Reserves_MW[g, tmp]
            ) - (
                prev_tmp_power - prev_tmp_downwards_reserves
            ) <= mod.gen_hydro_must_take_ramp_up_when_on_rate[
                g
            ] * mod.gen_hydro_must_take_ramp_up_when_on_rate_monthly_adjustment[
                g, mod.period[tmp], mod.month[tmp]
            ] * 60 * prev_tmp_hrs_in_tmp * mod.Capacity_MW[
                g, mod.period[tmp]
            ] * mod.Availability_Derate[
                g, tmp
            ]


def ramp_down_rule(mod, g, tmp):
    """
    **Constraint Name**: GenHydroMustTake_Ramp_Down_Constraint
    **Enforced Over**: GEN_HYDRO_MUST_TAKE_OPR_TMPS

    Difference between power generation of consecutive timepoints, adjusted
    for reserve provision in current and previous timepoint, has to obey
    ramp down rate limits.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_power = mod.gen_hydro_must_take_linked_power[g, 0]
            prev_tmp_upwards_reserves = mod.gen_hydro_must_take_linked_upwards_reserves[
                g, 0
            ]
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_power = mod.GenHydroMustTake_Gross_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_upwards_reserves = mod.GenHydroMustTake_Upwards_Reserves_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]

        if mod.gen_hydro_must_take_ramp_down_when_on_rate[g] == float("inf"):
            return Constraint.Skip
        else:
            return (
                mod.GenHydroMustTake_Gross_Power_MW[g, tmp]
                - mod.GenHydroMustTake_Downwards_Reserves_MW[g, tmp]
            ) - (
                prev_tmp_power + prev_tmp_upwards_reserves
            ) >= -mod.gen_hydro_must_take_ramp_down_when_on_rate[
                g
            ] * mod.gen_hydro_must_take_ramp_down_when_on_rate_monthly_adjustment[
                g, mod.period[tmp], mod.month[tmp]
            ] * 60 * prev_tmp_hrs_in_tmp * mod.Capacity_MW[
                g, mod.period[tmp]
            ] * mod.Availability_Derate[
                g, tmp
            ]


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp):
    """
    Power provision from must-take hydro.
    """
    return (
        mod.GenHydroMustTake_Gross_Power_MW[g, tmp]
        - mod.GenHydroMustTake_Auxiliary_Consumption_MW[g, tmp]
    )


def power_delta_rule(mod, g, tmp):
    """
    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint.
    """
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[g]
    ) and (
        check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linear",
        )
        or check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        )
    ):
        pass
    else:
        return (
            mod.GenHydroMustTake_Gross_Power_MW[g, tmp]
            - mod.GenHydroMustTake_Gross_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        )


def capacity_providing_inertia_rule(mod, g, tmp):
    """
    Capacity providing inertia for GEN_hydro_water project is set to be
    equal to the capacity engaged (This is assumed to be sum of the power
    output and the headroom available or the sum of the capacity of the
    engaged turbines)
    """
    return (
        mod.GenHydroMustTake_Gross_Power_MW[g, tmp]
        + mod.GenHydroMustTake_Upwards_Reserves_MW[g, tmp]
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

    :param m:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """

    # Determine list of projects load params from projects.tab (optional
    # ramp rates)
    projects = load_optype_model_data(
        mod=m,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="gen_hydro_must_take",
    )

    # Load hydro operational data from hydro-specific input files
    load_hydro_opchars(
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="gen_hydro_must_take",
        projects=projects,
    )

    # Ramp up monthly adjustments
    ramp_up_monthly_adjustments_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "gen_hydro_must_take_ramp_up_rate_monthly_adjustments.tab",
    )
    if os.path.exists(ramp_up_monthly_adjustments_filename):
        data_portal.load(
            filename=ramp_up_monthly_adjustments_filename,
            param=m.gen_hydro_must_take_ramp_up_when_on_rate_monthly_adjustment,
        )

    # Ramp down monthly adjustments
    ramp_down_monthly_adjustments_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "gen_hydro_must_take_ramp_down_rate_monthly_adjustments.tab",
    )
    if os.path.exists(ramp_down_monthly_adjustments_filename):
        data_portal.load(
            filename=ramp_down_monthly_adjustments_filename,
            param=m.gen_hydro_must_take_ramp_down_when_on_rate_monthly_adjustment,
        )

    # Linked timepoint params
    linked_inputs_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "gen_hydro_must_take_linked_timepoint_params.tab",
    )
    if os.path.exists(linked_inputs_filename):
        data_portal.load(
            filename=linked_inputs_filename,
            index=m.GEN_HYDRO_MUST_TAKE_LINKED_TMPS,
            param=(
                m.gen_hydro_must_take_linked_power,
                m.gen_hydro_must_take_linked_upwards_reserves,
                m.gen_hydro_must_take_linked_downwards_reserves,
            ),
        )


def add_to_prj_tmp_results(mod):
    results_columns = [
        "gross_power_mw",
        "auxiliary_consumption_mw",
    ]
    data = [
        [
            prj,
            tmp,
            value(mod.GenHydroMustTake_Gross_Power_MW[prj, tmp]),
            value(mod.GenHydroMustTake_Auxiliary_Consumption_MW[prj, tmp]),
        ]
        for (prj, tmp) in mod.GEN_HYDRO_MUST_TAKE_OPR_TMPS
    ]

    optype_dispatch_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    return results_columns, optype_dispatch_df


def export_results(
    mod,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param mod:
    :param d:
    :return:
    """

    # Dispatch results added to project_timepoint.csv via add_to_prj_tmp_results()

    # If there's a linked_subproblems_map CSV file, check which of the
    # current subproblem TMPS we should export results for to link to the
    # next subproblem
    tmps_to_link, tmp_linked_tmp_dict = check_for_tmps_to_link(
        scenario_directory=scenario_directory, subproblem=subproblem, stage=stage
    )

    # If the list of timepoints to link is not empty, write the linked
    # timepoint results for this module in the next subproblem's input
    # directory
    if tmps_to_link:
        next_subproblem = str(int(subproblem) + 1)

        # Export params by project and timepoint
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                next_subproblem,
                stage,
                "inputs",
                "gen_hydro_must_take_linked_timepoint_params.tab",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(
                [
                    "project",
                    "linked_timepoint",
                    "linked_provide_power",
                    "linked_upward_reserves",
                    "linked_downward_reserves",
                ]
            )
            for p, tmp in sorted(mod.GEN_HYDRO_MUST_TAKE_OPR_TMPS):
                if tmp in tmps_to_link:
                    writer.writerow(
                        [
                            p,
                            tmp_linked_tmp_dict[tmp],
                            max(value(mod.GenHydroMustTake_Gross_Power_MW[p, tmp]), 0),
                            max(
                                value(mod.GenHydroMustTake_Upwards_Reserves_MW[p, tmp]),
                                0,
                            ),
                            max(
                                value(
                                    mod.GenHydroMustTake_Downwards_Reserves_MW[p, tmp]
                                ),
                                0,
                            ),
                        ]
                    )


# Database
###############################################################################


def get_model_inputs_from_database(
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
    :return: cursor object with query results
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

    prj_bt_hrz_data = get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=subscenarios,
        weather_iteration=db_weather_iteration,
        hydro_iteration=db_hydro_iteration,
        availability_iteration=db_availability_iteration,
        subproblem=db_subproblem,
        stage=db_stage,
        conn=conn,
        op_type="gen_hydro_must_take",
        table="inputs_project_hydro_operational_chars",
        subscenario_id_column="hydro_operational_chars_scenario_id",
        data_column="average_power_fraction, min_power_fraction, max_power_fraction",
        opr_index_dict=BT_HRZ_INDEX_QUERY_PARAMS,
    )

    ramp_up_monthly_adjustments_sql = f"""
        SELECT project, period, month, monthly_adjustment
            FROM inputs_project_ramp_up_when_on_rate_monthly_adjustments
            WHERE 1=1
            AND project IN (
                SELECT project
                FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = 
                {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )
            AND (period, month) in (
                 SELECT DISTINCT period, month
                 FROM inputs_temporal
                 WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                 AND subproblem_id = {db_subproblem}
                 AND stage_id = {db_stage}
             )
            AND (project, ramp_up_when_on_rate_monthly_adjustment_scenario_id) in (
                SELECT project, ramp_up_when_on_rate_monthly_adjustment_scenario_id
                FROM inputs_project_operational_chars
                WHERE project_operational_chars_scenario_id = 
                {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
            )
            ;
            """

    ramp_up_adjustments_c = conn.cursor()
    ramp_up_monthly_adjustments = ramp_up_adjustments_c.execute(
        ramp_up_monthly_adjustments_sql
    )

    ramp_down_monthly_adjustments_sql = f"""
        SELECT project, period, month, monthly_adjustment
            FROM inputs_project_ramp_down_when_on_rate_monthly_adjustments
            WHERE 1=1
            AND project IN (
                SELECT project
                FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = 
                {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )
            AND (period, month) in (
                 SELECT DISTINCT period, month
                 FROM inputs_temporal
                 WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                 AND subproblem_id = {db_subproblem}
                 AND stage_id = {db_stage}
             )
            AND (project, ramp_down_when_on_rate_monthly_adjustment_scenario_id) in (
                SELECT project, ramp_down_when_on_rate_monthly_adjustment_scenario_id
                FROM inputs_project_operational_chars
                WHERE project_operational_chars_scenario_id = 
                {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
            )
            ;
            """

    ramp_down_adjustments_c = conn.cursor()
    ramp_down_monthly_adjustments = ramp_down_adjustments_c.execute(
        ramp_down_monthly_adjustments_sql
    )

    return prj_bt_hrz_data, ramp_up_monthly_adjustments, ramp_down_monthly_adjustments


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
    Get inputs from database and write out the model input
    hydro_conventional_horizon_params.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    (
        prj_bt_hrz_data,
        ramp_up_monthly_adjustments,
        ramp_down_monthly_adjustments,
    ) = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )
    bt_hrz_chars_fname = "hydro_conventional_horizon_params.tab"

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        bt_hrz_chars_fname,
        prj_bt_hrz_data,
    )

    ramp_up_monthly_adjustments_fname = (
        "gen_hydro_must_take_ramp_up_rate_monthly_adjustments.tab"
    )
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        ramp_up_monthly_adjustments_fname,
        ramp_up_monthly_adjustments,
    )

    ramp_down_monthly_adjustments_fname = (
        "gen_hydro_must_take_ramp_down_rate_monthly_adjustments.tab"
    )
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        ramp_down_monthly_adjustments_fname,
        ramp_down_monthly_adjustments,
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
        "gen_hydro_must_take",
    )

    # Validate hydro opchars input table
    hydro_opchar_fraction_error = validate_hydro_opchars(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "gen_hydro_must_take",
    )

    if hydro_opchar_fraction_error:
        warnings.warn("""
            Found hydro min, max, or average that are <0 or >1. This is 
            allowed but this warning is here to make sure it is intended.
            """)
