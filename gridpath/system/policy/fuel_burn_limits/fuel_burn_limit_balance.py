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
MMBtu [fuel burn unit] limit by horizon. Limits can be absolute or relative to fuel
burn in another fuel - BA.
"""

import csv
import os.path

from pyomo.environ import Var, Constraint, NonNegativeReals, Expression, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.dynamic_components import fuel_burn_balance_components
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.policy.fuel_burn_limits import FUEL_BURN_LIMITS_DF


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
    m.Total_Horizon_Fuel_Burn_By_Fuel_BA_from_All_Sources_Expression = Expression(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT,
        rule=lambda mod, ba, bt, h: sum(
            getattr(mod, component)[ba, bt, h]
            for component in getattr(d, fuel_burn_balance_components)
        ),
    )

    # Absolute constraints on fuel burn
    # Min fuel burn
    m.Fuel_Burn_Min_Shortage_Abs_Unit = Var(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MIN_ABS_LIMIT,
        within=NonNegativeReals,
    )

    def violation_expression_min_abs_rule(mod, ba, bt, h):
        if mod.fuel_burn_min_allow_violation[ba]:
            return mod.Fuel_Burn_Min_Shortage_Abs_Unit[ba, bt, h]
        else:
            return 0

    m.Fuel_Burn_Min_Shortage_Abs_Unit_Expression = Expression(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MIN_ABS_LIMIT,
        rule=violation_expression_min_abs_rule,
    )

    def fuel_burn_min_balance_abs_rule(mod, ba, bt, h):
        """
        Total fuel burn in a ba / bt-horizon must be >= a pre-defined value.

        :param mod:
        :param z:
        :param bt:
        :param h:
        :return:
        """
        return (
            mod.Total_Horizon_Fuel_Burn_By_Fuel_BA_from_All_Sources_Expression[
                ba, bt, h
            ]
            + mod.Fuel_Burn_Min_Shortage_Abs_Unit_Expression[ba, bt, h]
            >= mod.fuel_burn_min_unit[ba, bt, h]
        )

    m.Meet_Fuel_Burn_Min_Abs_Constraint = Constraint(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MIN_ABS_LIMIT,
        rule=fuel_burn_min_balance_abs_rule,
    )

    # Max fuel burn
    m.Fuel_Burn_Max_Overage_Abs_Unit = Var(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_ABS_LIMIT,
        within=NonNegativeReals,
    )

    def violation_expression_max_abs_rule(mod, ba, bt, h):
        if mod.fuel_burn_max_allow_violation[ba]:
            return mod.Fuel_Burn_Max_Overage_Abs_Unit[ba, bt, h]
        else:
            return 0

    m.Fuel_Burn_Max_Overage_Abs_Unit_Expression = Expression(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_ABS_LIMIT,
        rule=violation_expression_max_abs_rule,
    )

    def fuel_burn_max_balance_abs_rule(mod, ba, bt, h):
        """
        Total fuel burn in a ba / bt-horizon must be <= a pre-defined value.

        :param mod:
        :param z:
        :param bt:
        :param h:
        :return:
        """
        return (
            mod.Total_Horizon_Fuel_Burn_By_Fuel_BA_from_All_Sources_Expression[
                ba, bt, h
            ]
            - mod.Fuel_Burn_Max_Overage_Abs_Unit_Expression[ba, bt, h]
            <= mod.fuel_burn_max_unit[ba, bt, h]
        )

    m.Meet_Fuel_Burn_Max_Abs_Constraint = Constraint(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_ABS_LIMIT,
        rule=fuel_burn_max_balance_abs_rule,
    )

    # Relative to fuel burn in other BA
    m.Fuel_Burn_Limit_Overage_Rel_Unit = Var(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_REL_LIMIT,
        within=NonNegativeReals,
    )

    def violation_expression_rel_rule(mod, ba, bt, h):
        if mod.fuel_burn_relative_max_allow_violation[ba]:
            return mod.Fuel_Burn_Limit_Overage_Rel_Unit[ba, bt, h]
        else:
            return 0

    m.Fuel_Burn_Max_Overage_Rel_Unit_Expression = Expression(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_REL_LIMIT,
        rule=violation_expression_rel_rule,
    )

    def fuel_burn_limit_balance_rel_rule(mod, ba, bt, h):
        """
        Total fuel burn in a ba / bt-horizon must be below a pre-defined
        fraction of the fuel burn in another ba.

        :param mod:
        :param z:
        :param bt:
        :param h:
        :return:
        """
        return (
            mod.Total_Horizon_Fuel_Burn_By_Fuel_BA_from_All_Sources_Expression[
                ba, bt, h
            ]
            - mod.Fuel_Burn_Max_Overage_Rel_Unit_Expression[ba, bt, h]
            <= mod.fraction_of_relative_fuel_burn_max_fuel_ba[ba, bt, h]
            * mod.Total_Horizon_Fuel_Burn_By_Fuel_BA_from_All_Sources_Expression[
                mod.relative_fuel_burn_max_ba[ba, bt, h],
                bt,
                h,
            ]
        )

    m.Meet_Fuel_Burn_Max_Rel_Constraint = Constraint(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_REL_LIMIT,
        rule=fuel_burn_limit_balance_rel_rule,
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

    results_columns = [
        "fuel_burn_min_unit",
        "fuel_burn_max_unit",
        "relative_fuel_burn_max_ba",
        "fraction_of_relative_fuel_burn_max_fuel_ba",
        "total_fuel_burn_unit",
        "fuel_burn_min_abs_shortage_unit",
        "fuel_burn_max_abs_overage_unit",
        "fuel_burn_max_rel_overage_unit",
        "abs_min_dual",
        "abs_min_fuel_burn_limit_marginal_cost_per_unit",
        "abs_max_dual",
        "abs_max_fuel_burn_limit_marginal_cost_per_unit",
        "rel_dual",
        "rel_fuel_burn_limit_marginal_cost_per_unit",
    ]
    data = [
        [
            z,
            bt,
            h,
            m.fuel_burn_min_unit[z, bt, h],
            m.fuel_burn_max_unit[z, bt, h],
            m.relative_fuel_burn_max_ba[z, bt, h],
            m.fraction_of_relative_fuel_burn_max_fuel_ba[z, bt, h],
            value(
                m.Total_Horizon_Fuel_Burn_By_Fuel_BA_from_All_Sources_Expression[
                    z, bt, h
                ]
            ),
            (
                value(m.Fuel_Burn_Min_Shortage_Abs_Unit_Expression[z, bt, h])
                if (z, bt, h) in m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MIN_ABS_LIMIT
                else None
            ),
            (
                value(m.Fuel_Burn_Max_Overage_Abs_Unit_Expression[z, bt, h])
                if (z, bt, h) in m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_ABS_LIMIT
                else None
            ),
            (
                value(m.Fuel_Burn_Max_Overage_Rel_Unit_Expression[z, bt, h])
                if (z, bt, h) in m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_REL_LIMIT
                else None
            ),
            (
                duals_wrapper(
                    m, getattr(m, "Meet_Fuel_Burn_Min_Abs_Constraint")[z, bt, h]
                )
                if (z, bt, h)
                in [idx for idx in getattr(m, "Meet_Fuel_Burn_Min_Abs_Constraint")]
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(
                        m, getattr(m, "Meet_Fuel_Burn_Min_Abs_Constraint")[z, bt, h]
                    ),
                    m.hrz_objective_coefficient[bt, h],
                )
                if (z, bt, h)
                in [idx for idx in getattr(m, "Meet_Fuel_Burn_Min_Abs_Constraint")]
                else None
            ),
            (
                duals_wrapper(
                    m, getattr(m, "Meet_Fuel_Burn_Max_Abs_Constraint")[z, bt, h]
                )
                if (z, bt, h)
                in [idx for idx in getattr(m, "Meet_Fuel_Burn_Max_Abs_Constraint")]
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(
                        m, getattr(m, "Meet_Fuel_Burn_Max_Abs_Constraint")[z, bt, h]
                    ),
                    m.hrz_objective_coefficient[bt, h],
                )
                if (z, bt, h)
                in [idx for idx in getattr(m, "Meet_Fuel_Burn_Max_Abs_Constraint")]
                else None
            ),
            (
                duals_wrapper(
                    m, getattr(m, "Meet_Fuel_Burn_Max_Rel_Constraint")[z, bt, h]
                )
                if (z, bt, h)
                in [idx for idx in getattr(m, "Meet_Fuel_Burn_Max_Rel_Constraint")]
                else None
            ),
            (
                none_dual_type_error_wrapper(
                    duals_wrapper(
                        m, getattr(m, "Meet_Fuel_Burn_Max_Rel_Constraint")[z, bt, h]
                    ),
                    m.hrz_objective_coefficient[bt, h],
                )
                if (z, bt, h)
                in [idx for idx in getattr(m, "Meet_Fuel_Burn_Max_Rel_Constraint")]
                else None
            ),
        ]
        for (z, bt, h) in m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT
    ]
    results_df = create_results_df(
        index_columns=[
            "fuel_burn_limit_ba",
            "balancing_type",
            "horizon",
        ],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, FUEL_BURN_LIMITS_DF), results_df)


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
    instance.constraint_indices["Meet_Fuel_Burn_Min_Abs_Constraint"] = [
        "fuel_burn_limit_ba",
        "balancing_type",
        "horizon",
        "dual",
    ]

    instance.constraint_indices["Meet_Fuel_Burn_Max_Abs_Constraint"] = [
        "fuel_burn_limit_ba",
        "balancing_type",
        "horizon",
        "dual",
    ]

    instance.constraint_indices["Meet_Fuel_Burn_Max_Rel_Constraint"] = [
        "fuel_burn_limit_ba",
        "balancing_type",
        "horizon",
        "dual",
    ]
