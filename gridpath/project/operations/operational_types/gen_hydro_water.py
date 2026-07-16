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
This operational type describes the operations of hydro generation projects.
These projects can vary power output between a minimum and maximum level
specified for each horizon, and must produce a pre-specified amount of
energy on each horizon when they are available, some of which may be
curtailed. Negative output is allowed, i.e. this module can be used to model
pumping. The curtailable hydro projects can be allowed to provide upward
and/or downward reserves. Ramp rate limits can optionally be enforced.

Costs for this operational type include variable O&M costs.

"""

import os.path
from pyomo.environ import (
    Var,
    Set,
    Param,
    Constraint,
    Expression,
    NonNegativeReals,
    value,
    Reals,
    Any,
    PercentFraction,
)

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
    check_if_first_timepoint,
    check_boundary_type,
    check_if_boundary_type_and_first_timepoint,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_optype_model_data,
    check_for_tmps_to_link,
    write_tab_file_model_inputs,
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
    """ """
    # Sets
    ###########################################################################

    m.GEN_HYDRO_WATER = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_hydro_water"
        ),
    )

    m.GEN_HYDRO_WATER_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.GEN_HYDRO_WATER,
        ),
    )

    m.GEN_HYDRO_WATER_LINKED_TMPS = Set(dimen=2)

    # Required Params
    ###########################################################################

    m.gen_hydro_water_powerhouse = Param(m.GEN_HYDRO_WATER, within=m.POWERHOUSES)

    # Generator efficiency is a constant here, but is actually a function of
    # power output
    m.gen_hydro_water_generator_efficiency = Param(
        m.GEN_HYDRO_WATER, within=NonNegativeReals
    )

    # Optional Sets/Params
    ###########################################################################

    m.gen_hydro_water_ramp_up_when_on_rate = Param(
        m.GEN_HYDRO_WATER, within=PercentFraction, default=1
    )

    m.gen_hydro_water_ramp_down_when_on_rate = Param(
        m.GEN_HYDRO_WATER, within=PercentFraction, default=1
    )

    # Ramp rate limits by horizon timpepoint
    # This rate is in MW/hour
    m.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_UP_RATE_LIMITS = Set(
        dimen=3, within=m.GEN_HYDRO_WATER * m.BLN_TYPE_HRZS
    )
    m.gen_hydro_water_bt_hrz_ramp_up_limit_mw_per_hour = Param(
        m.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_UP_RATE_LIMITS, within=NonNegativeReals
    )

    m.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_DOWN_RATE_LIMITS = Set(
        dimen=3, within=m.GEN_HYDRO_WATER * m.BLN_TYPE_HRZS
    )
    m.gen_hydro_water_bt_hrz_ramp_down_limit_mw_per_hour = Param(
        m.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_DOWN_RATE_LIMITS, within=NonNegativeReals
    )

    def hrz_ramp_rate_up_by_tmp_init(mod):
        """
        BT-hrz value assigned to each timepoint in the BT-hrz
        Rate is adjusted for the duration of the timepoint
        """
        tmp_ramp_rate_dict = {}
        for prj, bt, hrz in mod.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_UP_RATE_LIMITS:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                tmp_ramp_rate_dict[(prj, tmp)] = (
                    mod.gen_hydro_water_bt_hrz_ramp_up_limit_mw_per_hour[prj, bt, hrz]
                    * mod.hrs_in_tmp[tmp]
                )

        return tmp_ramp_rate_dict

    m.gen_hydro_water_bt_hrz_ramp_up_limit_mw_per_tmp = Param(
        m.GEN_HYDRO_WATER_OPR_TMPS,
        within=NonNegativeReals,
        initialize=hrz_ramp_rate_up_by_tmp_init,
        default=float("inf"),
    )

    def hrz_ramp_rate_down_by_tmp_init(mod):
        """
        BT-hrz value assigned to each timepoint in the BT-hrz
        Rate is adjusted for the duration of the timepoint
        """
        tmp_ramp_rate_dict = {}
        for prj, bt, hrz in mod.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_DOWN_RATE_LIMITS:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                tmp_ramp_rate_dict[(prj, tmp)] = (
                    mod.gen_hydro_water_bt_hrz_ramp_down_limit_mw_per_hour[prj, bt, hrz]
                    * mod.hrs_in_tmp[tmp]
                )

        return tmp_ramp_rate_dict

    m.gen_hydro_water_bt_hrz_ramp_down_limit_mw_per_tmp = Param(
        m.GEN_HYDRO_WATER_OPR_TMPS,
        within=NonNegativeReals,
        initialize=hrz_ramp_rate_down_by_tmp_init,
        default=float("inf"),
    )

    m.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_UP_LIMITS = Set(
        dimen=3, within=m.GEN_HYDRO_WATER * m.BLN_TYPE_HRZS
    )

    m.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_DOWN_LIMITS = Set(
        dimen=3, within=m.GEN_HYDRO_WATER * m.BLN_TYPE_HRZS
    )

    m.gen_hydro_water_total_ramp_up_limit_mw = Param(
        m.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_UP_LIMITS, within=NonNegativeReals
    )

    m.gen_hydro_water_total_ramp_down_limit_mw = Param(
        m.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_DOWN_LIMITS, within=NonNegativeReals
    )

    # Index the ramp components only where ramp limit data exist: every
    # index of a Var/Constraint costs rule-call time and per-object memory
    # even if the component can never bind there

    def bt_hrz_ramp_up_limit_prj_opr_tmps_init(mod):
        prj_tmps = []
        seen = set()
        for prj, bt, hrz in mod.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_UP_RATE_LIMITS:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (prj, tmp) not in seen and (
                    prj,
                    tmp,
                ) in mod.GEN_HYDRO_WATER_OPR_TMPS:
                    seen.add((prj, tmp))
                    prj_tmps.append((prj, tmp))

        return prj_tmps

    m.GEN_HYDRO_WATER_BT_HRZ_RAMP_UP_LIMIT_PRJ_OPR_TMPS = Set(
        dimen=2, initialize=bt_hrz_ramp_up_limit_prj_opr_tmps_init
    )

    def bt_hrz_ramp_down_limit_prj_opr_tmps_init(mod):
        prj_tmps = []
        seen = set()
        for prj, bt, hrz in mod.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_DOWN_RATE_LIMITS:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (prj, tmp) not in seen and (
                    prj,
                    tmp,
                ) in mod.GEN_HYDRO_WATER_OPR_TMPS:
                    seen.add((prj, tmp))
                    prj_tmps.append((prj, tmp))

        return prj_tmps

    m.GEN_HYDRO_WATER_BT_HRZ_RAMP_DOWN_LIMIT_PRJ_OPR_TMPS = Set(
        dimen=2, initialize=bt_hrz_ramp_down_limit_prj_opr_tmps_init
    )

    def total_ramp_up_limit_prj_opr_tmps_init(mod):
        prjs = {
            prj for (prj, bt, hrz) in mod.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_UP_LIMITS
        }
        return [
            (prj, tmp) for (prj, tmp) in mod.GEN_HYDRO_WATER_OPR_TMPS if prj in prjs
        ]

    m.GEN_HYDRO_WATER_TOTAL_RAMP_UP_LIMIT_PRJ_OPR_TMPS = Set(
        dimen=2, initialize=total_ramp_up_limit_prj_opr_tmps_init
    )

    def total_ramp_down_limit_prj_opr_tmps_init(mod):
        prjs = {
            prj
            for (prj, bt, hrz) in mod.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_DOWN_LIMITS
        }
        return [
            (prj, tmp) for (prj, tmp) in mod.GEN_HYDRO_WATER_OPR_TMPS if prj in prjs
        ]

    m.GEN_HYDRO_WATER_TOTAL_RAMP_DOWN_LIMIT_PRJ_OPR_TMPS = Set(
        dimen=2, initialize=total_ramp_down_limit_prj_opr_tmps_init
    )

    # Linked Params
    ###########################################################################

    m.gen_hydro_water_linked_power = Param(m.GEN_HYDRO_WATER_LINKED_TMPS, within=Reals)

    m.gen_hydro_water_linked_curtailment = Param(
        m.GEN_HYDRO_WATER_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_hydro_water_linked_upwards_reserves = Param(
        m.GEN_HYDRO_WATER_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_hydro_water_linked_downwards_reserves = Param(
        m.GEN_HYDRO_WATER_LINKED_TMPS, within=NonNegativeReals
    )

    # Variables
    ###########################################################################

    m.GenHydroWater_Power_MW = Var(m.GEN_HYDRO_WATER_OPR_TMPS, within=Reals)

    m.GenHydroWater_Ramp_Up_MW = Var(
        m.GEN_HYDRO_WATER_TOTAL_RAMP_UP_LIMIT_PRJ_OPR_TMPS,
        within=NonNegativeReals,
        initialize=0,
    )

    m.GenHydroWater_Ramp_Down_MW = Var(
        m.GEN_HYDRO_WATER_TOTAL_RAMP_DOWN_LIMIT_PRJ_OPR_TMPS,
        within=NonNegativeReals,
        initialize=0,
    )

    # Expressions
    ###########################################################################

    def upwards_reserve_rule(mod, g, tmp):
        return headroom_provision_rule(d, mod, g, tmp)

    m.GenHydroWater_Upwards_Reserves_MW = Expression(
        m.GEN_HYDRO_WATER_OPR_TMPS, rule=upwards_reserve_rule
    )

    def downwards_reserve_rule(mod, g, tmp):
        return footroom_provision_rule(d, mod, g, tmp)

    m.GenHydroWater_Downwards_Reserves_MW = Expression(
        m.GEN_HYDRO_WATER_OPR_TMPS, rule=downwards_reserve_rule
    )

    # Constraints
    ###########################################################################

    m.Powerhouse_Based_Power_Constraint = Constraint(
        m.GEN_HYDRO_WATER_OPR_TMPS, rule=enforce_powerhouse_based_power_output
    )
    m.GenHydroWater_Max_Power_Constraint = Constraint(
        m.GEN_HYDRO_WATER_OPR_TMPS, rule=max_power_rule
    )

    m.GenHydroWater_Min_Power_Constraint = Constraint(
        m.GEN_HYDRO_WATER_OPR_TMPS, rule=min_power_rule
    )

    m.GenHydroWater_Ramp_Up_Constraint = Constraint(
        m.GEN_HYDRO_WATER_OPR_TMPS, rule=enforce_ramp_up_constraint_rule
    )

    m.GenHydroWater_Ramp_Down_Constraint = Constraint(
        m.GEN_HYDRO_WATER_OPR_TMPS, rule=enforce_ramp_down_constraint_rule
    )

    m.GenHydroWater_Ramp_Up_Variable_Constraint = Constraint(
        m.GEN_HYDRO_WATER_TOTAL_RAMP_UP_LIMIT_PRJ_OPR_TMPS,
        rule=ramp_up_variable_constraint_rule,
    )

    m.GenHydroWater_Ramp_Down_Variable_Constraint = Constraint(
        m.GEN_HYDRO_WATER_TOTAL_RAMP_DOWN_LIMIT_PRJ_OPR_TMPS,
        rule=ramp_down_variable_constraint_rule,
    )

    m.GenHydroWater_BT_Hrz_Ramp_Up_Rate_Constraint = Constraint(
        m.GEN_HYDRO_WATER_BT_HRZ_RAMP_UP_LIMIT_PRJ_OPR_TMPS,
        rule=enforce_bt_hrz_ramp_up_rate_constraint_rule,
    )

    m.GenHydroWater_BT_Hrz_Ramp_Down_Rate_Constraint = Constraint(
        m.GEN_HYDRO_WATER_BT_HRZ_RAMP_DOWN_LIMIT_PRJ_OPR_TMPS,
        rule=enforce_bt_hrz_ramp_down_rate_constraint_rule,
    )

    m.GenHydroWater_Total_Ramp_Up_Constraint = Constraint(
        m.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_UP_LIMITS,
        rule=total_ramp_up_constraint_rule,
    )

    m.GenHydroWater_Total_Ramp_Down_Constraint = Constraint(
        m.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_DOWN_LIMITS,
        rule=total_ramp_down_constraint_rule,
    )


# Constraint Formulation Rules
###############################################################################


def max_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenHydroWater_Max_Power_Constraint
    **Enforced Over**: GEN_HYDRO_WATER_OPR_BT_HRZS

    Power plus upward reserves shall not exceed the generator available
    capacity.

    """
    return (
        mod.GenHydroWater_Power_MW[g, tmp]
        + mod.GenHydroWater_Upwards_Reserves_MW[g, tmp]
        <= mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
    )


def min_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenHydroWater_Min_Power_Constraint
    **Enforced Over**: GEN_HYDRO_WATER_OPR_BT_HRZS

    Can't provide more downward reserves than current power provision.
    """
    return (
        mod.GenHydroWater_Downwards_Reserves_MW[g, tmp]
        <= mod.GenHydroWater_Power_MW[g, tmp]
    )


def enforce_powerhouse_based_power_output(mod, g, tmp):
    return (
        mod.GenHydroWater_Power_MW[g, tmp]
        == mod.Powerhouse_Output_by_Generator[mod.gen_hydro_water_powerhouse[g], g, tmp]
        * mod.gen_hydro_water_generator_efficiency[g]
    )


def enforce_ramp_up_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: GenHydroWater_Ramp_Up_Constraint
    **Enforced Over**: GEN_HYDRO_WATER_OPR_TMPS

    Difference between power generation of consecutive timepoints, adjusted
    for reserve provision in current and previous timepoint, has to obey
    ramp up rate limits.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    balancing_type = mod.balancing_type_project[g]
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=balancing_type,
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=balancing_type,
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_power = mod.gen_hydro_water_linked_power[g, 0]
            prev_tmp_downwards_reserves = mod.gen_hydro_water_linked_downwards_reserves[
                g, 0
            ]
        else:
            prev_tmp = mod.prev_tmp[tmp, balancing_type]
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[prev_tmp]
            prev_tmp_power = mod.GenHydroWater_Power_MW[g, prev_tmp]
            prev_tmp_downwards_reserves = mod.GenHydroWater_Downwards_Reserves_MW[
                g, prev_tmp
            ]
        # If you can ramp up the total project's capacity within the
        # previous timepoint, skip the constraint (it won't bind)
        ramp_up_rate = mod.gen_hydro_water_ramp_up_when_on_rate[g]
        if ramp_up_rate * 60 * prev_tmp_hrs_in_tmp >= 1:
            return Constraint.Skip
        else:
            return (
                mod.GenHydroWater_Power_MW[g, tmp]
                + mod.GenHydroWater_Upwards_Reserves_MW[g, tmp]
            ) - (
                prev_tmp_power - prev_tmp_downwards_reserves
            ) <= ramp_up_rate * 60 * prev_tmp_hrs_in_tmp * mod.Capacity_MW[
                g, mod.period[tmp]
            ] * mod.Availability_Derate[
                g, tmp
            ]


def enforce_bt_hrz_ramp_up_rate_constraint_rule(mod, g, tmp):
    """ """
    # Check the skip conditions before doing any other work: no constraint
    # for timepoints without a specified limit (the default is infinity)
    if mod.gen_hydro_water_bt_hrz_ramp_up_limit_mw_per_tmp[g, tmp] == float("inf"):
        return Constraint.Skip
    balancing_type = mod.balancing_type_project[g]
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=balancing_type,
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=balancing_type,
            boundary_type="linked",
        ):
            raise UserWarning(
                "GridPath WARNING: linked horizons not "
                "implemented for gen_hydro_water"
            )
        else:
            prev_tmp = mod.prev_tmp[tmp, balancing_type]
            prev_tmp_power = mod.GenHydroWater_Power_MW[g, prev_tmp]
            prev_tmp_downwards_reserves = mod.GenHydroWater_Downwards_Reserves_MW[
                g, prev_tmp
            ]

        return (
            mod.GenHydroWater_Power_MW[g, tmp]
            + mod.GenHydroWater_Upwards_Reserves_MW[g, tmp]
        ) - (
            prev_tmp_power - prev_tmp_downwards_reserves
        ) <= mod.gen_hydro_water_bt_hrz_ramp_up_limit_mw_per_tmp[
            g, prev_tmp
        ]


def enforce_bt_hrz_ramp_down_rate_constraint_rule(mod, g, tmp):
    """ """
    # Check the skip conditions before doing any other work: no constraint
    # for timepoints without a specified limit (the default is infinity)
    if mod.gen_hydro_water_bt_hrz_ramp_down_limit_mw_per_tmp[g, tmp] == float("inf"):
        return Constraint.Skip
    balancing_type = mod.balancing_type_project[g]
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=balancing_type,
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=balancing_type,
            boundary_type="linked",
        ):
            raise UserWarning(
                "GridPath WARNING: linked horizons not "
                "implemented for gen_hydro_water"
            )
        else:
            prev_tmp = mod.prev_tmp[tmp, balancing_type]
            prev_tmp_power = mod.GenHydroWater_Power_MW[g, prev_tmp]
            prev_tmp_upwards_reserves = mod.GenHydroWater_Upwards_Reserves_MW[
                g, prev_tmp
            ]

        return (prev_tmp_power + prev_tmp_upwards_reserves) - (
            mod.GenHydroWater_Power_MW[g, tmp]
            - mod.GenHydroWater_Downwards_Reserves_MW[g, tmp]
        ) <= mod.gen_hydro_water_bt_hrz_ramp_down_limit_mw_per_tmp[g, prev_tmp]


def enforce_ramp_down_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: GenHydroWater_Ramp_Down_Constraint
    **Enforced Over**: GEN_HYDRO_WATER_OPR_TMPS

    Difference between power generation of consecutive timepoints, adjusted
    for reserve provision in current and previous timepoint, has to obey
    ramp down rate limits.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    balancing_type = mod.balancing_type_project[g]
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=balancing_type,
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=balancing_type,
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_power = mod.gen_hydro_water_linked_power[g, 0]
            prev_tmp_upwards_reserves = mod.gen_hydro_water_linked_upwards_reserves[
                g, 0
            ]
        else:
            prev_tmp = mod.prev_tmp[tmp, balancing_type]
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[prev_tmp]
            prev_tmp_power = mod.GenHydroWater_Power_MW[g, prev_tmp]
            prev_tmp_upwards_reserves = mod.GenHydroWater_Upwards_Reserves_MW[
                g, prev_tmp
            ]
        # If you can ramp down the total project's capacity within the
        # previous timepoint, skip the constraint (it won't bind)
        ramp_down_rate = mod.gen_hydro_water_ramp_down_when_on_rate[g]
        if ramp_down_rate * 60 * prev_tmp_hrs_in_tmp >= 1:
            return Constraint.Skip
        else:
            return (
                mod.GenHydroWater_Power_MW[g, tmp]
                - mod.GenHydroWater_Downwards_Reserves_MW[g, tmp]
            ) - (
                prev_tmp_power + prev_tmp_upwards_reserves
            ) >= -ramp_down_rate * 60 * prev_tmp_hrs_in_tmp * mod.Capacity_MW[
                g, mod.period[tmp]
            ] * mod.Availability_Derate[
                g, tmp
            ]


def ramp_up_variable_constraint_rule(mod, g, tmp):
    """ """
    balancing_type = mod.balancing_type_project[g]
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=balancing_type,
        boundary_type="linear",
    ):
        return Constraint.Skip
    elif check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=balancing_type,
        boundary_type="linked",
    ):
        # TODO: not implemented
        raise UserWarning(
            "WARNING: linked horizons not impelmented for " "gen_hydro_water!!!"
        )
    else:
        return (
            mod.GenHydroWater_Ramp_Up_MW[g, tmp]
            >= mod.GenHydroWater_Power_MW[g, tmp]
            - mod.GenHydroWater_Power_MW[g, mod.prev_tmp[tmp, balancing_type]]
        )


def ramp_down_variable_constraint_rule(mod, g, tmp):
    """ """
    balancing_type = mod.balancing_type_project[g]
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=balancing_type,
        boundary_type="linear",
    ):
        return Constraint.Skip
    elif check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=balancing_type,
        boundary_type="linked",
    ):
        # TODO: not implemented
        raise UserWarning(
            "WARNING: linked horizons not impelmented for " "gen_hydro_water!!!"
        )
    else:
        return (
            mod.GenHydroWater_Ramp_Down_MW[g, tmp]
            >= mod.GenHydroWater_Power_MW[g, mod.prev_tmp[tmp, balancing_type]]
            - mod.GenHydroWater_Power_MW[g, tmp]
        )


def total_ramp_up_constraint_rule(mod, g, bt, hrz):
    return (
        sum(
            mod.GenHydroWater_Ramp_Up_MW[g, tmp] * mod.hrs_in_tmp[tmp]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        )
        <= mod.gen_hydro_water_total_ramp_up_limit_mw[g, bt, hrz]
    )


def total_ramp_down_constraint_rule(mod, g, bt, hrz):
    return (
        sum(
            mod.GenHydroWater_Ramp_Down_MW[g, tmp] * mod.hrs_in_tmp[tmp]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        )
        <= mod.gen_hydro_water_total_ramp_down_limit_mw[g, bt, hrz]
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp):
    """
    Power provision from curtailable hydro is the gross power minus
    curtailment.
    """
    return mod.GenHydroWater_Power_MW[g, tmp]


def variable_om_cost_rule(mod, g, tmp):
    """
    Variable cost is incurred on all power produced (including what's
    curtailed).
    """
    return mod.GenHydroWater_Power_MW[g, tmp] * mod.variable_om_cost_per_mwh[g]


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.GenHydroWater_Power_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.GenHydroWater_Power_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
    )


def power_delta_rule(mod, g, tmp):
    """
    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint.
    """
    balancing_type = mod.balancing_type_project[g]
    if check_if_first_timepoint(mod=mod, tmp=tmp, balancing_type=balancing_type) and (
        check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=balancing_type,
            boundary_type="linear",
        )
        or check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=balancing_type,
            boundary_type="linked",
        )
    ):
        pass
    else:
        return (
            mod.GenHydroWater_Power_MW[g, tmp]
            - mod.GenHydroWater_Power_MW[g, mod.prev_tmp[tmp, balancing_type]]
        )


def capacity_providing_inertia_rule(mod, g, tmp):
    """
    Capacity providing inertia for GEN_hydro_water project is set to be
    equal to the capacity engaged (This is assumed to be sum of the power
    output and the headroom available or the sum of the capacity of the
    engaged turbines)
    """
    return (
        mod.GenHydroWater_Power_MW[g, tmp]
        + mod.GenHydroWater_Upwards_Reserves_MW[g, tmp]
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
        op_type="gen_hydro_water",
    )

    # BT-hrz ramp up rate limits
    bt_hrz_ramp_up_rate_limits_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "gen_hydro_water_bt_hrz_ramp_up_rate_limits.tab",
    )
    if os.path.exists(bt_hrz_ramp_up_rate_limits_filename):
        data_portal.load(
            filename=bt_hrz_ramp_up_rate_limits_filename,
            index=m.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_UP_RATE_LIMITS,
            param=m.gen_hydro_water_bt_hrz_ramp_up_limit_mw_per_hour,
        )

    bt_hrz_ramp_down_rate_limits_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "gen_hydro_water_bt_hrz_ramp_down_rate_limits.tab",
    )
    if os.path.exists(bt_hrz_ramp_down_rate_limits_filename):
        data_portal.load(
            filename=bt_hrz_ramp_down_rate_limits_filename,
            index=m.GEN_HYDRO_WATER_BT_HRZ_W_BT_HRZ_RAMP_DOWN_RATE_LIMITS,
            param=m.gen_hydro_water_bt_hrz_ramp_down_limit_mw_per_hour,
        )

    # Total ramp up limits
    total_ramp_up_limits_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "gen_hydro_water_total_ramp_up_limits.tab",
    )
    if os.path.exists(total_ramp_up_limits_filename):
        data_portal.load(
            filename=total_ramp_up_limits_filename,
            index=m.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_UP_LIMITS,
            param=m.gen_hydro_water_total_ramp_up_limit_mw,
        )

    total_ramp_down_limits_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "gen_hydro_water_total_ramp_down_limits.tab",
    )
    if os.path.exists(total_ramp_down_limits_filename):
        data_portal.load(
            filename=total_ramp_down_limits_filename,
            index=m.GEN_HYDRO_WATER_BT_HRZ_W_TOTAL_RAMP_DOWN_LIMITS,
            param=m.gen_hydro_water_total_ramp_down_limit_mw,
        )

    # # Linked timepoint params
    # linked_inputs_filename = os.path.join(
    #     scenario_directory,
    #     weather_iteration,
    #     hydro_iteration,
    #     availability_iteration,
    #     subproblem,
    #     stage,
    #     "inputs",
    #     "gen_hydro_water_linked_timepoint_params.tab",
    # )
    # if os.path.exists(linked_inputs_filename):
    #     data_portal.load(
    #         filename=linked_inputs_filename,
    #         index=m.GEN_HYDRO_WATER_LINKED_TMPS,
    #         param=(
    #             m.gen_hydro_water_linked_power,
    #             m.gen_hydro_water_linked_upwards_reserves,
    #             m.gen_hydro_water_linked_downwards_reserves,
    #         ),
    #     )


def add_to_prj_tmp_results(mod):
    results_columns = ["power_mw"]
    data = [
        [
            prj,
            tmp,
            value(mod.GenHydroWater_Power_MW[prj, tmp]),
        ]
        for (prj, tmp) in mod.GEN_HYDRO_WATER_OPR_TMPS
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

    pass
    # # Dispatch results added to project_timepoint.csv via add_to_prj_tmp_results()
    # # If there's a linked_subproblems_map CSV file, check which of the
    # # current subproblem TMPS we should export results for to link to the
    # # next subproblem
    # tmps_to_link, tmp_linked_tmp_dict = check_for_tmps_to_link(
    #     scenario_directory=scenario_directory, subproblem=subproblem, stage=stage
    # )
    #
    # # If the list of timepoints to link is not empty, write the linked
    # # timepoint results for this module in the next subproblem's input
    # # directory
    # if tmps_to_link:
    #     next_subproblem = str(int(subproblem) + 1)
    #
    #     # Export params by project and timepoint
    #     with open(
    #         os.path.join(
    #             scenario_directory,
    #             next_subproblem,
    #             stage,
    #             "inputs",
    #             "gen_hydro_water_linked_timepoint_params.tab",
    #         ),
    #         "w",
    #         newline="",
    #     ) as f:
    #         writer = csv.writer(f, delimiter="\t", lineterminator="\n")
    #         writer.writerow(
    #             [
    #                 "project",
    #                 "linked_timepoint",
    #                 "linked_provide_power",
    #                 "linked_upward_reserves",
    #                 "linked_downward_reserves",
    #             ]
    #         )
    #         for p, tmp in sorted(mod.GEN_HYDRO_WATER_OPR_TMPS):
    #             if tmp in tmps_to_link:
    #                 writer.writerow(
    #                     [
    #                         p,
    #                         tmp_linked_tmp_dict[tmp],
    #                         max(value(mod.GenHydroWater_Power_MW[p, tmp]), 0),
    #                         max(
    #                             value(mod.GenHydroWater_Upwards_Reserves_MW[p, tmp]), 0
    #                         ),
    #                         max(
    #                             value(mod.GenHydroWater_Downwards_Reserves_MW[p, tmp]),
    #                             0,
    #                         ),
    #                     ]
    #                 )


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

    bt_hrz_ramp_up_rate_limits_sql = f"""
        SELECT project, balancing_type, horizon, ramp_up_rate_limit_mw_per_hour
            FROM inputs_project_bt_hrz_ramp_up_rate_limits
            WHERE 1=1
            AND project IN (
                SELECT project
                FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = 
                {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )
            AND (project, bt_hrz_ramp_up_rate_limit_scenario_id) in (
                SELECT project, bt_hrz_ramp_up_rate_limit_scenario_id
                FROM inputs_project_operational_chars
                WHERE project_operational_chars_scenario_id = 
                {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {db_subproblem}
                )
            ;
            """

    c3 = conn.cursor()
    bt_hrz_ramp_up_rate_limits = c3.execute(bt_hrz_ramp_up_rate_limits_sql)

    bt_hrz_ramp_down_rate_limits_sql = f"""
        SELECT project, balancing_type, horizon, ramp_down_rate_limit_mw_per_hour
            FROM inputs_project_bt_hrz_ramp_down_rate_limits
            WHERE 1=1
            AND project IN (
                SELECT project
                FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = 
                {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )
            AND (project, bt_hrz_ramp_down_rate_limit_scenario_id) in (
                SELECT project, bt_hrz_ramp_down_rate_limit_scenario_id
                FROM inputs_project_operational_chars
                WHERE project_operational_chars_scenario_id = 
                {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {db_subproblem}
                )
            ;
            """

    c4 = conn.cursor()
    bt_hrz_ramp_down_rate_limits = c4.execute(bt_hrz_ramp_down_rate_limits_sql)

    total_ramp_up_limits_sql = f"""
        SELECT project, balancing_type, horizon, total_ramp_up_limit_mw
            FROM inputs_project_total_ramp_up_limits
            WHERE 1=1
            AND project IN (
                SELECT project
                FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = 
                {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )
            AND (project, total_ramp_up_limit_scenario_id) in (
                SELECT project, total_ramp_up_limit_scenario_id
                FROM inputs_project_operational_chars
                WHERE project_operational_chars_scenario_id = 
                {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {db_subproblem}
                )
            ;
            """

    c1 = conn.cursor()
    total_ramp_up_limits = c1.execute(total_ramp_up_limits_sql)

    total_ramp_down_limits_sql = f"""
        SELECT project, balancing_type, horizon, total_ramp_down_limit_mw
            FROM inputs_project_total_ramp_down_limits
            WHERE 1=1
            AND project IN (
                SELECT project
                FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = 
                {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )
            AND (project, total_ramp_down_limit_scenario_id) in (
                SELECT project, total_ramp_down_limit_scenario_id
                FROM inputs_project_operational_chars
                WHERE project_operational_chars_scenario_id = 
                {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {db_subproblem}
                )
            ;
            """

    c2 = conn.cursor()
    total_ramp_down_limits = c2.execute(total_ramp_down_limits_sql)

    return (
        bt_hrz_ramp_up_rate_limits,
        bt_hrz_ramp_down_rate_limits,
        total_ramp_up_limits,
        total_ramp_down_limits,
    )


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
    variable_generator_profiles.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    (
        bt_hrz_ramp_up_rate_limits,
        bt_hrz_ramp_down_rate_limits,
        total_ramp_up_limits,
        total_ramp_down_limits,
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

    fname = "gen_hydro_water_bt_hrz_ramp_up_rate_limits.tab"
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname,
        bt_hrz_ramp_up_rate_limits,
    )

    fname = "gen_hydro_water_bt_hrz_ramp_down_rate_limits.tab"
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname,
        bt_hrz_ramp_down_rate_limits,
    )

    fname = "gen_hydro_water_total_ramp_up_limits.tab"
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname,
        total_ramp_up_limits,
    )

    fname = "gen_hydro_water_total_ramp_down_limits.tab"
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname,
        total_ramp_down_limits,
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

    pass
