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
Flows across water links.
"""

import os.path

from pyomo.environ import (
    Set,
    Param,
    NonNegativeReals,
    Var,
    Constraint,
    Any,
    value,
    Expression,
    Boolean,
    PositiveReals,
)

from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.common_functions import create_results_df
from gridpath.project.common_functions import (
    check_if_boundary_type_and_last_timepoint,
    check_boundary_type,
    check_if_boundary_type_and_first_timepoint,
)
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

    :param m:
    :param d:
    :return:
    """
    m.water_link_default_min_flow_vol_per_sec = Param(m.WATER_LINKS, default=0)
    m.allow_water_link_min_flow_violation = Param(
        m.WATER_LINKS, within=Boolean, default=0
    )
    m.min_flow_violation_penalty_cost = Param(
        m.WATER_LINKS, within=NonNegativeReals, default=0
    )
    m.allow_water_link_max_flow_violation = Param(
        m.WATER_LINKS, within=Boolean, default=0
    )
    m.max_flow_violation_penalty_cost = Param(
        m.WATER_LINKS, within=NonNegativeReals, default=0
    )

    m.allow_water_link_hrz_min_flow_violation = Param(
        m.WATER_LINKS, within=Boolean, default=0
    )
    m.hrz_min_flow_violation_penalty_cost_per_hour = Param(
        m.WATER_LINKS, within=NonNegativeReals, default=0
    )

    m.allow_water_link_hrz_max_flow_violation = Param(
        m.WATER_LINKS, within=Boolean, default=0
    )
    m.hrz_max_flow_violation_penalty_cost_per_hour = Param(
        m.WATER_LINKS, within=NonNegativeReals, default=0
    )

    # Start with these as params BUT:
    # These are probably not params but expressions with a non-linear
    # relationship to elevation; most of the curves look they can be
    # piecewise linear
    m.min_tmp_flow_vol_per_second = Param(
        m.WATER_LINKS,
        m.TMPS,
        within=NonNegativeReals,
        default=lambda mod, wl, tmp: mod.water_link_default_min_flow_vol_per_sec[wl],
    )
    m.max_tmp_flow_vol_per_second = Param(m.WATER_LINKS, m.TMPS, default=float("inf"))

    # Min and max total flows by horizon
    m.WATER_LINKS_W_BT_HRZ_MIN_FLOW_CONSTRAINT = Set(
        dimen=3, within=m.WATER_LINKS * m.BLN_TYPE_HRZS
    )
    m.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT = Set(
        dimen=3, within=m.WATER_LINKS * m.BLN_TYPE_HRZS
    )

    m.min_bt_hrz_flow_avg_vol_per_second = Param(
        m.WATER_LINKS_W_BT_HRZ_MIN_FLOW_CONSTRAINT,
        within=NonNegativeReals,
    )

    m.max_bt_hrz_flow_avg_vol_per_second = Param(
        m.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT,
        within=NonNegativeReals,
    )

    # Threshold upstream inflow above which max horizon flows will be adjusted
    # If not specified, defaults to infinity, so no adjustment will be made
    m.threshold_side_stream_avg_vol_per_second = Param(
        m.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT,
        within=NonNegativeReals,
        default=float("inf"),
    )

    # Set WATER_LINK_DEPARTURE_ARRIVAL_TMPS
    def water_link_departure_arrival_tmp_init(mod):
        wl_dep_arr_tmp = []
        for wl in mod.WATER_LINKS:
            transport_time = mod.water_link_flow_transport_time_hours[wl]
            for departure_tmp in mod.TMPS:
                arrival_tmp = determine_future_timepoint(
                    mod=mod,
                    dep_tmp=departure_tmp,
                    time_from_dep_tmp=transport_time,
                )
                if arrival_tmp is not None:
                    wl_dep_arr_tmp.append((wl, departure_tmp, arrival_tmp))

        return wl_dep_arr_tmp

    m.TMPS_AND_OUTSIDE_HORIZON = Set(initialize=m.TMPS | {"tmp_outside_horizon"})
    # No within= domain check: this set is derived from model data by
    # construction, so membership is guaranteed and the per-element check
    # would only add construction time on the largest water set
    m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS = Set(
        dimen=3,
        initialize=water_link_departure_arrival_tmp_init,
    )

    def departure_tmp_init(mod):
        dep_tmp_dict = {}
        for water_link, dep_tmp, arr_tmp in mod.WATER_LINK_DEPARTURE_ARRIVAL_TMPS:
            dep_tmp_dict[water_link, arr_tmp] = dep_tmp

        return dep_tmp_dict

    m.departure_timepoint = Param(
        m.WATER_LINKS,
        m.TMPS_AND_OUTSIDE_HORIZON,
        default="tmp_outside_horizon",
        within=m.TMPS_AND_OUTSIDE_HORIZON,
        initialize=departure_tmp_init,
    )

    def arrival_tmp_init(mod):
        arr_tmp_dict = {}
        for water_link, dep_tmp, arr_tmp in mod.WATER_LINK_DEPARTURE_ARRIVAL_TMPS:
            arr_tmp_dict[water_link, dep_tmp] = arr_tmp

        return arr_tmp_dict

    m.arrival_timepoint = Param(
        m.WATER_LINKS,
        m.TMPS,
        within=m.TMPS_AND_OUTSIDE_HORIZON,
        initialize=arrival_tmp_init,
    )

    # Ramp limits
    m.WATER_LINK_RAMP_LIMITS = Set(
        dimen=2,
        within=m.WATER_LINKS * Any,
    )

    m.water_link_ramp_limit_up_or_down = Param(
        m.WATER_LINK_RAMP_LIMITS,
        within=[1, -1],
    )
    m.water_link_ramp_limit_n_hours = Param(
        m.WATER_LINK_RAMP_LIMITS,
        within=PositiveReals,
    )

    m.WATER_LINK_RAMP_LIMITS_BT_HRZ = Set(
        dimen=4, within=m.WATER_LINK_RAMP_LIMITS * m.BLN_TYPE_HRZS
    )
    m.water_link_ramp_limit_bt_hrz_allowed_flow_delta = Param(
        m.WATER_LINK_RAMP_LIMITS_BT_HRZ, within=NonNegativeReals, default=float("inf")
    )

    def tmp_ramp_limit_init(mod):
        """
        If multiple bt-hrz include this timepoint, apply the min of the
        values (the most binding)
        """
        tmp_ramp_limits = {}
        for water_link, ramp_limit, bt, hrz in mod.WATER_LINK_RAMP_LIMITS_BT_HRZ:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (water_link, ramp_limit, tmp) not in tmp_ramp_limits.keys():
                    tmp_ramp_limits[(water_link, ramp_limit, tmp)] = [
                        mod.water_link_ramp_limit_bt_hrz_allowed_flow_delta[
                            water_link, ramp_limit, bt, hrz
                        ]
                    ]
                else:
                    tmp_ramp_limits[(water_link, ramp_limit, tmp)].append(
                        mod.water_link_ramp_limit_bt_hrz_allowed_flow_delta[
                            water_link, ramp_limit, bt, hrz
                        ]
                    )

        # Apply min
        for k in tmp_ramp_limits:
            tmp_ramp_limits[k] = min([v for v in tmp_ramp_limits[k]])

        return tmp_ramp_limits

    m.water_link_ramp_limit_tmp_allowed_flow_delta = Param(
        m.WATER_LINK_RAMP_LIMITS,
        m.TMPS,
        within=NonNegativeReals,
        default=float("inf"),
        initialize=tmp_ramp_limit_init,
    )

    def ramp_limit_tmps_set_init(mod):
        ramp_limit_tmps = []
        for water_link, ramp_limit in mod.WATER_LINK_RAMP_LIMITS:
            n_hours = mod.water_link_ramp_limit_n_hours[water_link, ramp_limit]
            for tmp in mod.TMPS:
                dep_to_arr_tmps = determine_future_timepoint(
                    mod,
                    tmp,
                    n_hours,
                    keep_tmps=True,
                )
                for arr_tmp in dep_to_arr_tmps:
                    ramp_limit_tmps.append((water_link, ramp_limit, tmp, arr_tmp))

        return ramp_limit_tmps

    # No within= domain check: derived from model data by construction
    m.WATER_LINK_RAMP_LIMIT_DEP_ARR_TMPS = Set(
        dimen=4,
        initialize=ramp_limit_tmps_set_init,
    )

    # ### Variables ### #
    m.Water_Link_Flow_Rate_Vol_per_Sec = Var(
        m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS, within=NonNegativeReals
    )

    m.Water_Link_Min_Flow_Violation_Vol_per_Sec = Var(
        m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS, within=NonNegativeReals
    )
    m.Water_Link_Max_Flow_Violation_Vol_per_Sec = Var(
        m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS, within=NonNegativeReals
    )

    m.Water_Link_Hrz_Min_Flow_Violation_Avg_Vol_per_Sec = Var(
        m.WATER_LINKS_W_BT_HRZ_MIN_FLOW_CONSTRAINT, within=NonNegativeReals
    )

    m.Water_Link_Hrz_Max_Flow_Violation_Avg_Vol_per_Sec = Var(
        m.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT, within=NonNegativeReals
    )

    def min_flow_violation_expression_init(mod, wl, dep_tmp, arr_tmp):
        """

        :param mod:
        :param z:
        :param tmp:
        :return:
        """
        if mod.allow_water_link_min_flow_violation[wl]:
            return mod.Water_Link_Min_Flow_Violation_Vol_per_Sec[wl, dep_tmp, arr_tmp]
        else:
            return 0

    m.Water_Link_Min_Flow_Violation_Vol_per_Sec_Expression = Expression(
        m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS,
        initialize=min_flow_violation_expression_init,
    )

    def max_flow_violation_expression_init(mod, wl, dep_tmp, arr_tmp):
        """

        :param mod:
        :param z:
        :param tmp:
        :return:
        """
        if mod.allow_water_link_max_flow_violation[wl]:
            return mod.Water_Link_Max_Flow_Violation_Vol_per_Sec[wl, dep_tmp, arr_tmp]
        else:
            return 0

    m.Water_Link_Max_Flow_Violation_Vol_per_Sec_Expression = Expression(
        m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS,
        initialize=max_flow_violation_expression_init,
    )

    def hrz_min_flow_violation_expression_init(mod, wl, bt, hrz):
        """

        :param mod:
        :param wl:
        :param bt:
        :param hrz:
        :return:
        """
        if mod.allow_water_link_hrz_min_flow_violation[wl]:
            return mod.Water_Link_Hrz_Min_Flow_Violation_Avg_Vol_per_Sec[wl, bt, hrz]
        else:
            return 0

    m.Water_Link_Hrz_Min_Flow_Violation_Avg_Vol_per_Sec_Expression = Expression(
        m.WATER_LINKS_W_BT_HRZ_MIN_FLOW_CONSTRAINT,
        initialize=hrz_min_flow_violation_expression_init,
    )

    def hrz_max_flow_violation_expression_init(mod, wl, bt, hrz):
        """

        :param mod:
        :param wl:
        :param bt:
        :param hrz:
        :return:
        """
        if mod.allow_water_link_hrz_max_flow_violation[wl]:
            return mod.Water_Link_Hrz_Max_Flow_Violation_Avg_Vol_per_Sec[wl, bt, hrz]
        else:
            return 0

    m.Water_Link_Hrz_Max_Flow_Violation_Avg_Vol_per_Sec_Expression = Expression(
        m.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT,
        initialize=hrz_max_flow_violation_expression_init,
    )

    # ### Constraints ### #
    def min_tmp_flow_rule(mod, wl, dep_tmp, arr_tmp):
        min_flow = mod.min_tmp_flow_vol_per_second[wl, dep_tmp]
        # Flow and violation are both non-negative, so a bound of 0 (the
        # default) can never bind
        if min_flow == 0:
            return Constraint.Skip
        return (
            mod.Water_Link_Flow_Rate_Vol_per_Sec[wl, dep_tmp, arr_tmp]
            + mod.Water_Link_Min_Flow_Violation_Vol_per_Sec_Expression[
                wl, dep_tmp, arr_tmp
            ]
            >= min_flow
        )

    m.Water_Link_Minimum_Flow_Constraint = Constraint(
        m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS, rule=min_tmp_flow_rule
    )

    def max_tmp_flow_rule(mod, wl, dep_tmp, arr_tmp):
        max_flow = mod.max_tmp_flow_vol_per_second[wl, dep_tmp]
        if max_flow == float("inf"):
            return Constraint.Skip
        return (
            mod.Water_Link_Flow_Rate_Vol_per_Sec[wl, dep_tmp, arr_tmp]
            - mod.Water_Link_Max_Flow_Violation_Vol_per_Sec_Expression[
                wl, dep_tmp, arr_tmp
            ]
            <= max_flow
        )

    m.Water_Link_Maximum_Flow_Constraint = Constraint(
        m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS, rule=max_tmp_flow_rule
    )

    def min_total_hrz_flow_constraint_rule(mod, wl, bt, hrz):
        """ """
        return sum(
            (
                mod.Water_Link_Flow_Rate_Vol_per_Sec[
                    wl, dep_tmp, mod.arrival_timepoint[wl, dep_tmp]
                ]
                + mod.Water_Link_Hrz_Min_Flow_Violation_Avg_Vol_per_Sec_Expression[
                    wl, bt, hrz
                ]
            )
            * mod.hrs_in_tmp[dep_tmp]
            for dep_tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        ) >= sum(
            mod.min_bt_hrz_flow_avg_vol_per_second[wl, bt, hrz] * mod.hrs_in_tmp[tmp]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        )

    m.Water_Link_Min_Total_Hrz_Flow_Constraint = Constraint(
        m.WATER_LINKS_W_BT_HRZ_MIN_FLOW_CONSTRAINT,
        rule=min_total_hrz_flow_constraint_rule,
    )

    m.WATER_LINK_UPSTREAM_WATER_NODES = Set(within=m.WATER_LINKS * m.WATER_NODES)

    def upstream_water_nodes_by_water_link_init(mod):
        nodes_by_link = {wl: [] for wl in mod.WATER_LINKS}
        for _wl, wn in mod.WATER_LINK_UPSTREAM_WATER_NODES:
            nodes_by_link[_wl].append(wn)

        return nodes_by_link

    m.UPSTREAM_WATER_NODES_BY_WATER_LINK = Set(
        m.WATER_LINKS,
        initialize=upstream_water_nodes_by_water_link_init,
    )

    def max_total_hrz_flow_constraint_rule(mod, wl, bt, hrz):
        """
        Rule for max flows over a horizon. The max is a parameter by bt-hrz
        plus an optional adjustment for upstream exogenous inflows (requires
        a mapping to be provided of water nodes upstream from water link wl)
        above a threshold inflow amount (
        threshold_side_stream_avg_vol_per_second). If the latter are not
        specified, the max_bt_hrz_flow_avg_vol_per_second will bind.
        """
        upstream_exogenous_inflows = sum(
            mod.exogenous_water_inflow_rate_vol_per_sec[wn, tmp] * mod.hrs_in_tmp[tmp]
            for wn in mod.UPSTREAM_WATER_NODES_BY_WATER_LINK[wl]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        )
        return sum(
            (
                mod.Water_Link_Flow_Rate_Vol_per_Sec[
                    wl, dep_tmp, mod.arrival_timepoint[wl, dep_tmp]
                ]
                - mod.Water_Link_Hrz_Max_Flow_Violation_Avg_Vol_per_Sec_Expression[
                    wl, bt, hrz
                ]
            )
            * mod.hrs_in_tmp[dep_tmp]
            for dep_tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        ) <= sum(
            mod.max_bt_hrz_flow_avg_vol_per_second[wl, bt, hrz] * mod.hrs_in_tmp[tmp]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        ) + max(
            (
                upstream_exogenous_inflows
                - sum(
                    mod.threshold_side_stream_avg_vol_per_second[wl, bt, hrz]
                    * mod.hrs_in_tmp[dep_tmp]
                    for dep_tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
                )
            ),
            0,
        )

    m.Water_Link_Max_Total_Hrz_Flow_Constraint = Constraint(
        m.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT,
        rule=max_total_hrz_flow_constraint_rule,
    )

    # Ramp constraints
    def water_link_flow_ramp_constraint_rule(mod, wl, ramp_limit, tmp, future_tmp):
        if future_tmp == "tmp_outside_horizon":
            return Constraint.Skip
        else:
            allowed_flow_delta = mod.water_link_ramp_limit_tmp_allowed_flow_delta[
                wl, ramp_limit, tmp
            ]
            # No constraint for timepoints without a specified limit (the
            # default is infinity)
            if allowed_flow_delta == float("inf"):
                return Constraint.Skip
            return (
                mod.water_link_ramp_limit_up_or_down[wl, ramp_limit]
                * (
                    mod.Water_Link_Flow_Rate_Vol_per_Sec[
                        wl, future_tmp, mod.arrival_timepoint[wl, future_tmp]
                    ]
                    - mod.Water_Link_Flow_Rate_Vol_per_Sec[
                        wl, tmp, mod.arrival_timepoint[wl, tmp]
                    ]
                )
                <= allowed_flow_delta
            )

    m.Water_Link_Flow_Ramp_Constraint = Constraint(
        m.WATER_LINK_RAMP_LIMIT_DEP_ARR_TMPS, rule=water_link_flow_ramp_constraint_rule
    )


def determine_future_timepoint(mod, dep_tmp, time_from_dep_tmp, keep_tmps=False):
    """
    USER WARNING: timepoint durations longer than the travel time may create
    issues. You could also see issues if timepoints don't receive any flows
    because of short durations. This functionality is new and not yet
    extensively tested, so proceed with caution.

    The result depends only on the arguments (not on which water link is
    asking), so it is cached on the model instance: links sharing a
    transport time would otherwise redo the same walk through the
    timepoints for every (link, timepoint) pair.
    """
    cache = getattr(mod, "_gridpath_future_tmp_cache", None)
    if cache is None:
        cache = {}
        setattr(mod, "_gridpath_future_tmp_cache", cache)
    cache_key = (dep_tmp, time_from_dep_tmp, keep_tmps)
    if cache_key in cache:
        return cache[cache_key]

    dep_to_arr_tmps_list = []
    # If travel time is less than the hours in the departure timepoint,
    # balancing happens within the departure timepoint
    if time_from_dep_tmp < mod.hrs_in_tmp[dep_tmp]:
        arr_tmp = dep_tmp
        if keep_tmps:
            dep_to_arr_tmps_list.append(arr_tmp)
    # If this is the last timepoint of a linear horizon, there are no
    # timepoints to check and we'll return 'tmp_outside_horizon'
    elif check_if_boundary_type_and_last_timepoint(
        mod=mod,
        tmp=dep_tmp,
        balancing_type=mod.water_system_balancing_type,
        boundary_type="linear",
    ):
        arr_tmp = "tmp_outside_horizon"
        if keep_tmps:
            dep_to_arr_tmps_list.append(arr_tmp)
    elif check_if_boundary_type_and_last_timepoint(
        mod=mod,
        tmp=dep_tmp,
        balancing_type=mod.water_system_balancing_type,
        boundary_type="linked",
    ):
        # TODO: add linked
        arr_tmp = None
    else:
        # Otherwise, we check the following timepoints
        # First we'll check the next timepoint of the starting timepoint and
        # start with the duration of the starting timepoint
        arr_tmp = mod.next_tmp[dep_tmp, mod.water_system_balancing_type]
        dep_to_arr_tmps_list.append(arr_tmp)
        hours_from_departure_tmp = mod.hrs_in_tmp[dep_tmp]
        while hours_from_departure_tmp < time_from_dep_tmp:
            # If we haven't exceeded the travel time yet, we move on to the next tmp
            # In a 'linear' horizon setting, once we reach the last
            # timepoint of the horizon, we set the arrival timepoint to
            # "tmp_outside_horizon" and break out of the loop
            if check_if_boundary_type_and_last_timepoint(
                mod=mod,
                tmp=arr_tmp,
                balancing_type=mod.water_system_balancing_type,
                boundary_type="linear",
            ):
                arr_tmp = "tmp_outside_horizon"
                if keep_tmps:
                    dep_to_arr_tmps_list.append(arr_tmp)
                break
            # In a 'circular' horizon setting, once we loop back to the
            # departure timepoint again, we break out of the loop since there
            # are no more timepoints to consider (we have already checked all
            # horizon timepoints)
            elif (
                check_boundary_type(
                    mod=mod,
                    tmp=dep_tmp,
                    balancing_type=mod.water_system_balancing_type,
                    boundary_type="circular",
                )
                and arr_tmp == dep_tmp
            ):
                arr_tmp = "tmp_outside_horizon"
                if keep_tmps:
                    dep_to_arr_tmps_list.append(arr_tmp)
                break
            # TODO: only allow the first horizon of a subproblem to have
            #  linked timepoints
            # In a 'linked' horizon setting, once we reach the first
            # timepoint of the horizon, we'll start adding the linked
            # timepoints until we reach the target min time
            elif check_if_boundary_type_and_last_timepoint(
                mod=mod,
                tmp=arr_tmp,
                balancing_type=mod.water_system_balancing_type,
                boundary_type="linked",
            ):
                # TODO: add linked
                arr_tmp = None
                break
            # Otherwise, we move on to the next timepoint and will add that
            # timepoint's duration to hours_from_departure_tmp
            else:
                hours_from_departure_tmp += mod.hrs_in_tmp[arr_tmp]
                arr_tmp = mod.next_tmp[arr_tmp, mod.water_system_balancing_type]
                if keep_tmps:
                    dep_to_arr_tmps_list.append(arr_tmp)
    result = dep_to_arr_tmps_list if keep_tmps else arr_tmp
    cache[cache_key] = result

    return result


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
    inputs_directory = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
    )
    data_portal.load(
        filename=os.path.join(
            inputs_directory,
            "water_flow_params.tab",
        ),
        param=(
            m.water_link_default_min_flow_vol_per_sec,
            m.allow_water_link_min_flow_violation,
            m.min_flow_violation_penalty_cost,
            m.allow_water_link_max_flow_violation,
            m.max_flow_violation_penalty_cost,
            m.allow_water_link_hrz_min_flow_violation,
            m.hrz_min_flow_violation_penalty_cost_per_hour,
            m.allow_water_link_hrz_max_flow_violation,
            m.hrz_max_flow_violation_penalty_cost_per_hour,
        ),
    )

    tmp_fname = os.path.join(
        inputs_directory,
        "water_flow_tmp_bounds.tab",
    )
    if os.path.exists(tmp_fname):
        data_portal.load(
            filename=tmp_fname,
            param=(m.min_tmp_flow_vol_per_second, m.max_tmp_flow_vol_per_second),
        )

    hrz_min_fname = os.path.join(
        inputs_directory,
        "water_flow_hrz_min_bounds.tab",
    )

    if os.path.exists(hrz_min_fname):
        data_portal.load(
            filename=hrz_min_fname,
            index=m.WATER_LINKS_W_BT_HRZ_MIN_FLOW_CONSTRAINT,
            param=m.min_bt_hrz_flow_avg_vol_per_second,
        )

    hrz_max_fname = os.path.join(
        inputs_directory,
        "water_flow_hrz_max_bounds.tab",
    )

    if os.path.exists(hrz_max_fname):
        data_portal.load(
            filename=hrz_max_fname,
            index=m.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT,
            param=(
                m.max_bt_hrz_flow_avg_vol_per_second,
                m.threshold_side_stream_avg_vol_per_second,
            ),
        )

    wl_upstream_water_node_map_fname = os.path.join(
        inputs_directory,
        "water_flow_water_link_upstream_flow_map.tab",
    )

    if os.path.exists(wl_upstream_water_node_map_fname):
        data_portal.load(
            filename=wl_upstream_water_node_map_fname,
            set=m.WATER_LINK_UPSTREAM_WATER_NODES,
        )

    ramp_limit_fname = os.path.join(
        inputs_directory,
        "water_flow_ramp_limits.tab",
    )

    if os.path.exists(ramp_limit_fname):
        data_portal.load(
            filename=ramp_limit_fname,
            index=m.WATER_LINK_RAMP_LIMITS,
            param=(
                m.water_link_ramp_limit_up_or_down,
                m.water_link_ramp_limit_n_hours,
            ),
        )

    ramp_limit_values_fname = os.path.join(
        inputs_directory,
        "water_flow_ramp_limit_values.tab",
    )

    if os.path.exists(ramp_limit_values_fname):
        data_portal.load(
            filename=ramp_limit_values_fname,
            index=m.WATER_LINK_RAMP_LIMITS_BT_HRZ,
            param=m.water_link_ramp_limit_bt_hrz_allowed_flow_delta,
        )


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
    c0 = conn.cursor()
    water_flow_params = c0.execute(f"""SELECT water_link,
        default_min_flow_vol_per_sec,
        allow_water_link_min_flow_violation,
        min_flow_violation_penalty_cost,
        allow_water_link_max_flow_violation,
        max_flow_violation_penalty_cost,
        allow_water_link_hrz_min_flow_violation,
        hrz_min_flow_violation_penalty_cost_per_hour,
        allow_water_link_hrz_max_flow_violation,
        hrz_max_flow_violation_penalty_cost_per_hour
        FROM inputs_system_water_flows
        WHERE water_flow_scenario_id = {subscenarios.WATER_FLOW_SCENARIO_ID}
        AND water_link IN (
                SELECT water_link
                FROM inputs_geography_water_network
                WHERE water_network_scenario_id = 
                {subscenarios.WATER_NETWORK_SCENARIO_ID}
            )
        ;
        """)

    c1 = conn.cursor()
    tmp_sql = f"""SELECT water_link, timepoint, 
            min_tmp_flow_vol_per_second, max_tmp_flow_vol_per_second
            FROM inputs_system_water_flows_timepoint_bounds
            WHERE (water_link, water_flow_timepoint_bounds_scenario_id) in (
                SELECT water_link, water_flow_timepoint_bounds_scenario_id
                FROM inputs_system_water_flows
                WHERE water_flow_scenario_id = 
                {subscenarios.WATER_FLOW_SCENARIO_ID}
            )
            AND water_link IN (
                SELECT water_link
                FROM inputs_geography_water_network
                WHERE water_network_scenario_id = 
                {subscenarios.WATER_NETWORK_SCENARIO_ID}
            )
            AND timepoint
            IN (SELECT timepoint
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage})
            ;
            """

    tmp_flow_bounds = c1.execute(tmp_sql)

    hrz_min_sql = f"""SELECT water_link, balancing_type, horizon,
            min_bt_hrz_flow_avg_vol_per_second
            FROM inputs_system_water_flows_horizon_bounds
            WHERE min_bt_hrz_flow_avg_vol_per_second IS NOT NULL
            AND (water_link, water_flow_horizon_bounds_scenario_id) in (
                SELECT water_link, water_flow_horizon_bounds_scenario_id
                FROM inputs_system_water_flows
                WHERE water_flow_scenario_id = 
                {subscenarios.WATER_FLOW_SCENARIO_ID}
            )
            AND water_link IN (
                SELECT water_link
                FROM inputs_geography_water_network
                WHERE water_network_scenario_id = 
                {subscenarios.WATER_NETWORK_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                )
            ;
            """
    c2 = conn.cursor()
    hrz_min_flow_bounds = c2.execute(hrz_min_sql)

    hrz_max_sql = f"""SELECT water_link, balancing_type, horizon,
            max_bt_hrz_flow_avg_vol_per_second, threshold_side_stream_avg_vol_per_second
            FROM inputs_system_water_flows_horizon_bounds
            WHERE max_bt_hrz_flow_avg_vol_per_second IS NOT NULL
            AND (water_link, water_flow_horizon_bounds_scenario_id) in (
                SELECT water_link, water_flow_horizon_bounds_scenario_id
                FROM inputs_system_water_flows
                WHERE water_flow_scenario_id = 
                {subscenarios.WATER_FLOW_SCENARIO_ID}
            )
            AND water_link IN (
                SELECT water_link
                FROM inputs_geography_water_network
                WHERE water_network_scenario_id = 
                {subscenarios.WATER_NETWORK_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                )
            ;
            """
    c3 = conn.cursor()
    hrz_max_flow_bounds = c3.execute(hrz_max_sql)

    wl_upstream_wn_map_sql = f"""SELECT water_link, upstream_water_node
            FROM inputs_system_water_flows_horizon_bounds_upstream_node_map
            WHERE (water_link, water_flow_horizon_bounds_scenario_id) in (
                SELECT water_link, water_flow_horizon_bounds_scenario_id
                FROM inputs_system_water_flows
                WHERE water_flow_scenario_id = 
                {subscenarios.WATER_FLOW_SCENARIO_ID}
            )
            AND water_link IN (
                SELECT water_link
                FROM inputs_geography_water_network
                WHERE water_network_scenario_id = 
                {subscenarios.WATER_NETWORK_SCENARIO_ID}
            )
            ;
            """
    c4 = conn.cursor()
    wl_upstream_wn_map = c4.execute(wl_upstream_wn_map_sql)

    ramp_limits_sql = f"""
        SELECT water_link,
        ramp_limit_name,
        ramp_limit_up_or_down,
        ramp_limit_n_hours
        FROM inputs_system_water_flow_ramp_limits
        WHERE (water_link, water_flow_ramp_limit_scenario_id) in (
                SELECT water_link, water_flow_ramp_limit_scenario_id
                FROM inputs_system_water_flows
                WHERE water_flow_scenario_id = 
                {subscenarios.WATER_FLOW_SCENARIO_ID}
            )
        AND water_link IN (
                SELECT water_link
                FROM inputs_geography_water_network
                WHERE water_network_scenario_id = 
                {subscenarios.WATER_NETWORK_SCENARIO_ID}
            )
        ;
        """
    c5 = conn.cursor()
    ramp_limits = c5.execute(ramp_limits_sql)

    ramp_limit_values_sql = f"""
        SELECT water_link, ramp_limit_name, balancing_type, horizon,
            allowed_flow_delta_vol_per_sec
            FROM inputs_system_water_flow_ramp_limit_bt_hrz_values
            WHERE (water_link, water_flow_ramp_limit_scenario_id) in (
                SELECT water_link, water_flow_ramp_limit_scenario_id
                FROM inputs_system_water_flows
                WHERE water_flow_scenario_id = 
                {subscenarios.WATER_FLOW_SCENARIO_ID}
            )
            AND water_link IN (
                SELECT water_link
                FROM inputs_geography_water_network
                WHERE water_network_scenario_id = 
                {subscenarios.WATER_NETWORK_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                )
            ;
            """

    c6 = conn.cursor()
    ramp_limit_values = c6.execute(ramp_limit_values_sql)

    return (
        water_flow_params,
        tmp_flow_bounds,
        hrz_min_flow_bounds,
        hrz_max_flow_bounds,
        wl_upstream_wn_map,
        ramp_limits,
        ramp_limit_values,
    )


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
    # Validation to be added
    # carbon_cap_zone = get_inputs_from_database(
    #     scenario_id, subscenarios, subproblem, stage, conn)


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
    water_flow_tmp_bounds.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
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

    (
        water_flow_params,
        tmp_flow_bounds,
        hrz_min_flow_bounds,
        hrz_max_flow_bounds,
        wl_upstream_wn_map,
        ramp_limits,
        ramp_limit_values,
    ) = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_flow_params.tab",
        data=water_flow_params,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_flow_tmp_bounds.tab",
        data=tmp_flow_bounds,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_flow_water_link_upstream_flow_map.tab",
        data=wl_upstream_wn_map,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_flow_hrz_min_bounds.tab",
        data=hrz_min_flow_bounds,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_flow_hrz_max_bounds.tab",
        data=hrz_max_flow_bounds,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_flow_ramp_limits.tab",
        data=ramp_limits,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_flow_ramp_limit_values.tab",
        data=ramp_limit_values,
        replace_nulls=True,
    )


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

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """
    tmp_results_columns = [
        "water_flow_vol_per_sec",
        "water_flow_min_violation_vol_per_sec",
        "water_flow_max_violation_vol_per_sec",
    ]
    tmp_data = [
        [
            wl,
            dep_tmp,
            arr_tmp,
            value(m.Water_Link_Flow_Rate_Vol_per_Sec[wl, dep_tmp, arr_tmp]),
            value(
                m.Water_Link_Min_Flow_Violation_Vol_per_Sec_Expression[
                    wl, dep_tmp, arr_tmp
                ]
            ),
            value(
                m.Water_Link_Max_Flow_Violation_Vol_per_Sec_Expression[
                    wl, dep_tmp, arr_tmp
                ]
            ),
        ]
        for (wl, dep_tmp, arr_tmp) in m.WATER_LINK_DEPARTURE_ARRIVAL_TMPS
    ]
    tmp_results_df = create_results_df(
        index_columns=["water_link", "departure_timepoint", "arrival_timepoint"],
        results_columns=tmp_results_columns,
        data=tmp_data,
    )

    tmp_results_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_water_link_timepoint.csv",
        ),
        sep=",",
        index=True,
    )

    hrz_results_columns = [
        "hrs_in_bt_hrz",
        "max_allowed_avg_flow",
        "threshold_side_stream_avg_vol_per_second",
        "upstream_exogenous_inflows_avg_vol_per_second",
        "adjusted_max_allowed_avg_flow",
        "actual_avg_flow_vol_per_second",
        "violation_expression_avg_flow_vol_per_second",
    ]
    hrz_data = [
        [
            wl,
            bt,
            hrz,
            # hrs_in_bt_hrz
            sum(m.hrs_in_tmp[tmp] for tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]),
            # max_allowed_avg_flow
            m.max_bt_hrz_flow_avg_vol_per_second[wl, bt, hrz],
            # threshold_side_stream_avg_vol_per_second
            m.threshold_side_stream_avg_vol_per_second[wl, bt, hrz],
            # upstream_exogenous_inflows_avg_vol_per_second
            sum(
                m.exogenous_water_inflow_rate_vol_per_sec[wn, tmp] * m.hrs_in_tmp[tmp]
                for wn in m.UPSTREAM_WATER_NODES_BY_WATER_LINK[wl]
                for tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            / sum(m.hrs_in_tmp[tmp] for tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]),
            # adjusted_max_allowed_avg_flow
            m.max_bt_hrz_flow_avg_vol_per_second[wl, bt, hrz]
            + max(
                (
                    sum(
                        m.exogenous_water_inflow_rate_vol_per_sec[wn, tmp]
                        * m.hrs_in_tmp[tmp]
                        for wn in m.UPSTREAM_WATER_NODES_BY_WATER_LINK[wl]
                        for tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
                    )
                    / sum(m.hrs_in_tmp[tmp] for tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz])
                    - m.threshold_side_stream_avg_vol_per_second[wl, bt, hrz]
                ),
                0,
            ),
            # actual_avg_flow_vol_per_second
            sum(
                value(
                    m.Water_Link_Flow_Rate_Vol_per_Sec[
                        wl, dep_tmp, m.arrival_timepoint[wl, dep_tmp]
                    ]
                )
                * m.hrs_in_tmp[dep_tmp]
                for dep_tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            / sum(m.hrs_in_tmp[tmp] for tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]),
            # violation_expression
            value(
                m.Water_Link_Hrz_Max_Flow_Violation_Avg_Vol_per_Sec_Expression[
                    wl, bt, hrz
                ]
            ),
        ]
        for (wl, bt, hrz) in m.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT
    ]
    hrz_results_df = create_results_df(
        index_columns=["water_link", "balancing_type", "horizon"],
        results_columns=hrz_results_columns,
        data=hrz_data,
    )

    hrz_results_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_water_link_bt_hrz.csv",
        ),
        sep=",",
        index=True,
    )


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
        which_results="system_water_link_timepoint",
    )
