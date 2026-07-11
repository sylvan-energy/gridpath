# Copyright 2016-2025 Blue Marble Analytics LLC.
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

""" """

from pyomo.environ import Var, Constraint, NonNegativeReals, Expression, value

from gridpath.auxiliary.dynamic_components import (
    policy_balance_contribution_components,
)
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.policy.generic_policy import POLICY_ZONE_PRD_DF


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

    m.Policy_Target_Shortage = Var(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, within=NonNegativeReals, initialize=0
    )

    def violation_expression_init(mod, policy, zone, bt, h):
        if mod.policy_zone_allow_violation[policy, zone]:
            return mod.Policy_Target_Shortage[policy, zone, bt, h]
        else:
            return 0

    m.Policy_Requirement_Shortage_Expression = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        initialize=violation_expression_init,
    )

    m.Policy_Month_Hour_Requirement_Shortage = Var(
        m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ, within=NonNegativeReals, initialize=0
    )

    def month_hour_violation_expression_init(mod, policy, zone, period, mn, hr):
        if mod.policy_zone_allow_violation[policy, zone]:
            return mod.Policy_Month_Hour_Requirement_Shortage[
                policy, zone, period, mn, hr
            ]
        else:
            return 0

    m.Policy_Month_Hour_Requirement_Shortage_Expression = Expression(
        m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ,
        initialize=month_hour_violation_expression_init,
    )

    m.Total_Policy_Zone_Tmp_Contributions_from_All_Sources_Expression = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        rule=lambda mod, policy, zone, bt, h: sum(
            getattr(mod, component)[policy, zone, bt, h]
            for component in getattr(d, policy_balance_contribution_components)
        ),
    )

    def meet_policy_target_constraint_rule(mod, policy, zone, bt, h):
        """
        Total contributions from all sources (projects, transmission lines)
        must exceed the target
        :param mod:
        :param policy:
        :param zone:
        :param bt:
        :param h:
        :return:
        """
        return (
            mod.Total_Policy_Zone_Tmp_Contributions_from_All_Sources_Expression[
                policy, zone, bt, h
            ]
            + mod.Policy_Requirement_Shortage_Expression[policy, zone, bt, h]
            >= mod.Policy_Zone_Horizon_Requirement[policy, zone, bt, h]
        )

    m.Policy_Requirement_Constraint = Constraint(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, rule=meet_policy_target_constraint_rule
    )

    def meet_policy_month_hour_target_constraint_rule(
        mod, policy, zone, period, mn, hr
    ):
        return (
            mod.Total_Project_Policy_Zone_Month_Hour_Contributions[
                policy, zone, period, mn, hr
            ]
            + mod.Policy_Month_Hour_Requirement_Shortage_Expression[
                policy, zone, period, mn, hr
            ]
            >= mod.Policy_Zone_Month_Hour_Requirement[policy, zone, period, mn, hr]
        )

    m.Policy_Month_Hour_Requirement_Constraint = Constraint(
        m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ,
        rule=meet_policy_month_hour_target_constraint_rule,
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

    if not m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ:
        return

    results_columns = [
        "pre_load_modifier_load_in_hrz",
        "post_load_modifier_load_in_hrz",
        "policy_requirement_calculated_in_horizon",
        "policy_requirement_shortage",
        "dual",
        "policy_requirement_marginal_cost_per_unit",
    ]
    data = [
        [
            p,
            z,
            bt,
            h,
            sum(
                value(m.LZ_Bulk_Static_Load_in_Tmp[lz, tmp])
                * m.hrs_in_tmp[tmp]
                * m.tmp_weight[tmp]
                for (
                    _policy_name,
                    _policy_requirement_zone,
                    lz,
                ) in m.POLICIES_ZONE_LOAD_ZONES
                if (_policy_name, _policy_requirement_zone) == (p, z)
                for tmp in m.TMPS
                if tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, h]
            ),
            sum(
                value(m.LZ_Modified_Load_in_Tmp[lz, tmp])
                * m.hrs_in_tmp[tmp]
                * m.tmp_weight[tmp]
                for (
                    _policy_name,
                    _policy_requirement_zone,
                    lz,
                ) in m.POLICIES_ZONE_LOAD_ZONES
                if (_policy_name, _policy_requirement_zone) == (p, z)
                for tmp in m.TMPS
                if tmp in m.TMPS_BY_BLN_TYPE_HRZ[bt, h]
            ),
            value(m.Policy_Zone_Horizon_Requirement[p, z, bt, h]),
            value(m.Policy_Requirement_Shortage_Expression[p, z, bt, h]),
            (
                duals_wrapper(
                    m, getattr(m, "Policy_Requirement_Constraint")[p, z, bt, h]
                )
                if (p, z, bt, h)
                in [idx for idx in getattr(m, "Policy_Requirement_Constraint")]
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(
                        m, getattr(m, "Policy_Requirement_Constraint")[p, z, bt, h]
                    ),
                    m.hrz_objective_coefficient[bt, h],
                )
                if (p, z, bt, h)
                in [idx for idx in getattr(m, "Policy_Requirement_Constraint")]
                else None
            ),
        ]
        for (p, z, bt, h) in m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
    ]
    results_df = create_results_df(
        index_columns=[
            "policy_name",
            "policy_zone",
            "balancing_type_horizon",
            "horizon",
        ],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, POLICY_ZONE_PRD_DF), results_df)


def save_duals(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    instance,
    dynamic_components,
):
    instance.constraint_indices["Policy_Requirement_Constraint"] = [
        "policy_name",
        "policy_zone",
        "balancing_type",
        "horizon",
        "dual",
    ]
    instance.constraint_indices["Policy_Month_Hour_Requirement_Constraint"] = [
        "policy_name",
        "policy_zone",
        "period",
        "policy_month",
        "policy_hour",
        "dual",
    ]
