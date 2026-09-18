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


import csv
import os.path
from pyomo.environ import Var, Constraint, NonNegativeReals, Expression, value

from gridpath.auxiliary.db_interface import import_csv
from gridpath.common_functions import duals_wrapper, none_dual_type_error_wrapper


def generic_add_model_components(
    m,
    d,
    reserve_zone_set,
    reserve_violation_variable,
    reserve_violation_expression,
    reserve_violation_allowed_param,
    reserve_requirement_expression,
    total_reserve_provision_expression,
    meet_reserve_constraint,
):
    """
    Ensure reserves are balanced
    :param m:
    :param d:
    :param reserve_zone_set:
    :param reserve_violation_variable:
    :param reserve_violation_expression:
    :param reserve_violation_allowed_param:
    :param reserve_requirement_expression:
    :param total_reserve_provision_expression:
    :param meet_reserve_constraint:
    :return:
    """

    # Penalty for violation
    setattr(
        m,
        reserve_violation_variable,
        Var(getattr(m, reserve_zone_set), m.TMPS, within=NonNegativeReals),
    )

    def violation_expression_rule(mod, ba, tmp):
        """

        :param mod:
        :param ba:
        :param tmp:
        :return:
        """
        if getattr(mod, reserve_violation_allowed_param)[ba]:
            return getattr(mod, reserve_violation_variable)[ba, tmp]
        else:
            return 0

    setattr(
        m,
        reserve_violation_expression,
        Expression(
            getattr(m, reserve_zone_set), m.TMPS, rule=violation_expression_rule
        ),
    )

    # Reserve constraints
    def meet_reserve_rule(mod, ba, tmp):
        return (
            getattr(mod, total_reserve_provision_expression)[ba, tmp]
            + getattr(mod, reserve_violation_expression)[ba, tmp]
            == getattr(mod, reserve_requirement_expression)[ba, tmp]
        )

    setattr(
        m,
        meet_reserve_constraint,
        Constraint(getattr(m, reserve_zone_set), m.TMPS, rule=meet_reserve_rule),
    )


def generic_export_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    m,
    d,
    reserve_type,
    reserve_zone_set,
    reserve_requirement_expression,
    total_reserve_provision_expression,
    reserve_violation_expression,
):
    """

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :param reserve_type:
    :param column_name:
    :param reserve_zone_set:
    :param reserve_violation_expression:
    :return:
    """

    duals_map = {
        "lf_reserves_up": "Meet_LF_Reserves_Up_Constraint",
        "lf_reserves_down": "Meet_LF_Reserves_Down_Constraint",
        "regulation_up": "Meet_Regulation_Up_Constraint",
        "regulation_down": "Meet_Regulation_Down_Constraint",
        "frequency_response": "Meet_Frequency_Response_Constraint",
        "frequency_response_partial": "Meet_Frequency_Response_Partial_Constraint",
        "spinning_reserves": "Meet_Spinning_Reserves_Constraint",
    }

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            f"system_{reserve_type}.csv",
        ),
        "w",
        newline="",
    ) as results_file:
        writer = csv.writer(results_file)
        writer.writerow(
            [
                f"{reserve_type}_ba",
                "period",
                "timepoint",
                "discount_factor",
                "probability",
                "probability_weighted_discount_factor",
                "number_years_represented",
                "timepoint_weight",
                "number_of_hours_in_timepoint",
                "reserve_requirement_mw",
                "reserve_provision_mw",
                "reserve_violation_mw",
                "dual",
                "marginal_price_per_mw",
            ]
        )
        for ba, tmp in getattr(m, reserve_zone_set) * m.TMPS:
            writer.writerow(
                [
                    ba,
                    m.period[tmp],
                    tmp,
                    m.discount_factor[m.period[tmp]],
                    m.probability[m.period[tmp]],
                    m.probability_weighted_discount_factor[m.period[tmp]],
                    m.number_years_represented[m.period[tmp]],
                    m.tmp_weight[tmp],
                    m.hrs_in_tmp[tmp],
                    value(getattr(m, reserve_requirement_expression)[ba, tmp]),
                    value(getattr(m, total_reserve_provision_expression)[ba, tmp]),
                    value(getattr(m, reserve_violation_expression)[ba, tmp]),
                    (
                        duals_wrapper(m, getattr(m, duals_map[reserve_type])[ba, tmp])
                        if (ba, tmp)
                        in [idx for idx in getattr(m, duals_map[reserve_type])]
                        else None
                    ),
                    (
                        none_dual_type_error_wrapper(
                            duals_wrapper(
                                m, getattr(m, duals_map[reserve_type])[ba, tmp]
                            ),
                            m.tmp_objective_coefficient[tmp],
                        )
                        if (ba, tmp)
                        in [idx for idx in getattr(m, duals_map[reserve_type])]
                        else None
                    ),
                ]
            )


def generic_import_results_to_database(
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    c,
    db,
    results_directory,
    reserve_type,
    quiet,
):
    """

    :param scenario_id:
    :param subproblem:
    :param stage:
    :param c:
    :param db:
    :param results_directory:
    :param reserve_type:
    :return:
    """

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
        which_results=f"system_{reserve_type}",
    )
