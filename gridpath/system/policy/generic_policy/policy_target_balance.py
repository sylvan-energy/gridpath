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

"""
Enforce the policy requirements: the contributions from all sources
(projects, transmission lines) must be at least the requirement of a ``min``
policy and may not exceed the requirement of a ``max`` policy. The
requirement is the horizon requirement (scalar plus load term) plus the base
coefficient times the requirement's base (e.g. an emissions intensity times
the output of the requirement's base projects). Where the policy zone allows
violations, a shortage (``min``) or overage (``max``) variable relaxes the
constraint at the zone's penalty.
"""

from pyomo.environ import Var, Constraint, NonNegativeReals, Expression, value

from gridpath.auxiliary.dynamic_components import (
    policy_balance_base_components,
    policy_balance_contribution_components,
)
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.policy.generic_policy import POLICY_ZONE_PRD_DF, POLICY_MH_DF
from gridpath.system.policy.generic_policy.generic_policy_requirements import MAX


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
    | | :code:`Policy_Target_Shortage`                                        |
    | | *Defined over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The amount by which the contributions fall short of a ``min``           |
    | requirement; enters the constraint only where violations are allowed.  |
    +-------------------------------------------------------------------------+
    | | :code:`Policy_Target_Overage`                                         |
    | | *Defined over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The amount by which the contributions exceed a ``max`` requirement;     |
    | enters the constraint only where violations are allowed.               |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Total_Policy_Zone_Base_from_All_Sources_Expression`            |
    | | *Defined over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`          |
    |                                                                         |
    | The requirement's base over the horizon (the base projects' output or   |
    | capacity, see the policy requirement base module).                      |
    +-------------------------------------------------------------------------+
    | | :code:`Policy_Zone_Horizon_Total_Requirement`                         |
    | | *Defined over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`          |
    |                                                                         |
    | The horizon requirement plus the base coefficient times the base.       |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Policy_Requirement_Constraint`                                 |
    | | *Enforced over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`         |
    |                                                                         |
    | For a ``min`` policy, the contributions plus the shortage are at least  |
    | the total requirement; for a ``max`` policy, the contributions less the |
    | overage are at most the total requirement.                              |
    +-------------------------------------------------------------------------+

    :param m:
    :param d:
    :return:
    """

    m.Policy_Target_Shortage = Var(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, within=NonNegativeReals, initialize=0
    )
    m.Policy_Target_Overage = Var(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, within=NonNegativeReals, initialize=0
    )

    def is_max_policy(mod, policy, zone, bt, h):
        return mod.policy_requirement_sense[policy, zone, bt, h] == MAX

    def violation_expression_init(mod, policy, zone, bt, h):
        if mod.policy_zone_allow_violation[policy, zone] and not is_max_policy(
            mod, policy, zone, bt, h
        ):
            return mod.Policy_Target_Shortage[policy, zone, bt, h]
        else:
            return 0

    m.Policy_Requirement_Shortage_Expression = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        initialize=violation_expression_init,
    )

    def overage_expression_init(mod, policy, zone, bt, h):
        if mod.policy_zone_allow_violation[policy, zone] and is_max_policy(
            mod, policy, zone, bt, h
        ):
            return mod.Policy_Target_Overage[policy, zone, bt, h]
        else:
            return 0

    m.Policy_Requirement_Overage_Expression = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        initialize=overage_expression_init,
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

    m.Total_Policy_Zone_Base_from_All_Sources_Expression = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        rule=lambda mod, policy, zone, bt, h: sum(
            getattr(mod, component)[policy, zone, bt, h]
            for component in getattr(d, policy_balance_base_components)
        ),
    )

    def total_requirement_rule(mod, policy, zone, bt, h):
        """
        The horizon requirement plus the base coefficient times the base (the
        term is dropped where the coefficient is zero)
        """
        base_coeff = mod.policy_requirement_f_base_coeff[policy, zone, bt, h]
        requirement = mod.Policy_Zone_Horizon_Requirement[policy, zone, bt, h]
        if base_coeff == 0:
            return requirement
        else:
            return (
                requirement
                + base_coeff
                * mod.Total_Policy_Zone_Base_from_All_Sources_Expression[
                    policy, zone, bt, h
                ]
            )

    m.Policy_Zone_Horizon_Total_Requirement = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, rule=total_requirement_rule
    )

    def meet_policy_target_constraint_rule(mod, policy, zone, bt, h):
        """
        Total contributions from all sources (projects, transmission lines)
        must be at least the target of a 'min' policy and at most the target
        of a 'max' policy
        :param mod:
        :param policy:
        :param zone:
        :param bt:
        :param h:
        :return:
        """
        contributions = (
            mod.Total_Policy_Zone_Tmp_Contributions_from_All_Sources_Expression[
                policy, zone, bt, h
            ]
        )
        requirement = mod.Policy_Zone_Horizon_Total_Requirement[policy, zone, bt, h]
        if is_max_policy(mod, policy, zone, bt, h):
            return (
                contributions
                - mod.Policy_Requirement_Overage_Expression[policy, zone, bt, h]
                <= requirement
            )
        else:
            return (
                contributions
                + mod.Policy_Requirement_Shortage_Expression[policy, zone, bt, h]
                >= requirement
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

    if m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ:
        export_horizon_results(m, d)

    if m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ:
        export_month_hour_results(m, d)


def export_horizon_results(m, d):
    """
    Shortage or overage, dual, and marginal cost of the horizon-based
    requirements.
    """
    results_columns = [
        "pre_load_modifier_load_in_hrz",
        "post_load_modifier_load_in_hrz",
        "policy_requirement_base_in_hrz",
        "policy_requirement_calculated_in_horizon",
        "policy_requirement_shortage",
        "policy_requirement_overage",
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
            value(m.Total_Policy_Zone_Base_from_All_Sources_Expression[p, z, bt, h]),
            value(m.Policy_Zone_Horizon_Total_Requirement[p, z, bt, h]),
            value(m.Policy_Requirement_Shortage_Expression[p, z, bt, h]),
            value(m.Policy_Requirement_Overage_Expression[p, z, bt, h]),
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


def export_month_hour_results(m, d):
    """
    Shortage, dual, and marginal cost of the month-hour (slice-of-day)
    requirements. The dual is per period, so the marginal cost per unit of
    requirement is the dual divided by the period objective coefficient
    (discount factor x number of years represented).
    """
    constraint = m.Policy_Month_Hour_Requirement_Constraint
    results_columns = [
        "policy_month_hour_requirement_shortage",
        "dual",
        "policy_month_hour_requirement_marginal_cost_per_unit",
    ]
    data = [
        [
            p,
            z,
            prd,
            mn,
            hr,
            value(
                m.Policy_Month_Hour_Requirement_Shortage_Expression[p, z, prd, mn, hr]
            ),
            (
                duals_wrapper(m, constraint[p, z, prd, mn, hr])
                if (p, z, prd, mn, hr) in constraint
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(m, constraint[p, z, prd, mn, hr]),
                    m.period_objective_coefficient[prd],
                )
                if (p, z, prd, mn, hr) in constraint
                else None
            ),
        ]
        for (p, z, prd, mn, hr) in m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ
    ]
    results_df = create_results_df(
        index_columns=[
            "policy_name",
            "policy_zone",
            "period",
            "policy_month",
            "policy_hour",
        ],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, POLICY_MH_DF), results_df)
