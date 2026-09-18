# Copyright 2021 (c) Crown Copyright, GC.
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

    m.Instantaneous_Penetration_Shortage_MWh = Var(
        m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS, within=NonNegativeReals
    )
    m.Instantaneous_Penetration_Overage_MWh = Var(
        m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS, within=NonNegativeReals
    )
    m.Instantaneous_Penetration_Violation_MWh = Var(
        m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS, within=NonNegativeReals
    )

    def min_violation_expression_rule(mod, z, tmp):
        if mod.allow_violation_min_penetration[z]:
            return mod.Instantaneous_Penetration_Shortage_MWh[z, tmp]
        else:
            return 0

    def max_violation_expression_rule(mod, z, tmp):
        if mod.allow_violation_max_penetration[z]:
            return mod.Instantaneous_Penetration_Overage_MWh[z, tmp]
        else:
            return 0

    def violation_expression_rule(mod, z, tmp):
        return max_violation_expression_rule(
            mod, z, tmp
        ) + min_violation_expression_rule(mod, z, tmp)

    m.Instantaneous_Penetration_Shortage_MWh_Expression = Expression(
        m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS,
        rule=min_violation_expression_rule,
    )
    m.Instantaneous_Penetration_Overage_MWh_Expression = Expression(
        m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS,
        rule=max_violation_expression_rule,
    )
    m.Instantaneous_Penetration_Violation_MWh_Expression = Expression(
        m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS,
        rule=violation_expression_rule,
    )

    def instant_penetration_min_rule(mod, z, tmp):
        """
        Total delivered energy-target-eligible energy must exceed target
        :param mod:
        :param z:
        :param tmp:
        :return:
        """
        return (
            mod.Total_Instantaneous_Penetration_Energy_MWh[z, tmp]
            + mod.Instantaneous_Penetration_Shortage_MWh_Expression[z, tmp]
            >= mod.Inst_Pen_Requirement_min[z, tmp]
        )

    def instant_penetration_max_rule(mod, z, tmp):
        """
        Total delivered energy-target-eligible energy must exceed target
        :param mod:
        :param z:
        :param tmp:
        :return:
        """
        return (
            mod.Total_Instantaneous_Penetration_Energy_MWh[z, tmp]
            - mod.Instantaneous_Penetration_Overage_MWh_Expression[z, tmp]
            <= mod.Inst_Pen_Requirement_max[z, tmp]
        )

    m.Meet_Instantaneous_Penetration_min_Constraint = Constraint(
        m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS, rule=instant_penetration_min_rule
    )
    m.Meet_Instantaneous_Penetration_max_Constraint = Constraint(
        m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS, rule=instant_penetration_max_rule
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

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            f"system_instantaneous_penetration.csv",
        ),
        "w",
        newline="",
    ) as results_file:
        writer = csv.writer(results_file)
        writer.writerow(
            [
                f"instantaneous_penetration_zone",
                "period",
                "timepoint",
                "discount_factor",
                "probability",
                "probability_weighted_discount_factor",
                "number_years_represented",
                "timepoint_weight",
                "number_of_hours_in_timepoint",
                "min_instantaneous_penetration_mwh",
                "max_instantaneous_penetration_mwh",
                "total_instantaneous_penetration_energy_mwh",
                "instantaneous_penetration_shortage_mwh",
                "instantaneous_penetration_overage_mwh",
                "instantaneous_penetration_violation_mwh",
                # "dual_instantaneous_penetration_min",
                # "instantaneous_penetration_min_marginal_price_per_mw",
                # "dual_instantaneous_penetration_min",
                # "instantaneous_penetration_max_marginal_price_per_mw",
            ]
        )
        for z, tmp in m.INSTANTANEOUS_PENETRATION_ZONES * m.TMPS:
            writer.writerow(
                [
                    z,
                    m.period[tmp],
                    tmp,
                    m.discount_factor[m.period[tmp]],
                    m.probability[m.period[tmp]],
                    m.probability_weighted_discount_factor[m.period[tmp]],
                    m.number_years_represented[m.period[tmp]],
                    m.tmp_weight[tmp],
                    m.hrs_in_tmp[tmp],
                    value(m.Inst_Pen_Requirement_min[z, tmp]),
                    value(m.Inst_Pen_Requirement_max[z, tmp]),
                    value(m.Total_Instantaneous_Penetration_Energy_MWh[z, tmp]),
                    value(m.Instantaneous_Penetration_Shortage_MWh_Expression[z, tmp]),
                    value(m.Instantaneous_Penetration_Overage_MWh_Expression[z, tmp]),
                    value(m.Instantaneous_Penetration_Violation_MWh_Expression[z, tmp]),
                    # duals_wrapper(m, getattr(m, "Meet_Instantaneous_Penetration_min_Constraint")[z, tmp])
                    # if (z, tmp) in [idx for idx in getattr(m, "Meet_Instantaneous_Penetration_min_Constraint")]
                    # else None,
                    # (
                    #     none_dual_type_error_wrapper(
                    #         duals_wrapper(
                    #             m, getattr(m, "Meet_Instantaneous_Penetration_min_Constraint")[z, tmp]
                    #         ),
                    #         m.tmp_objective_coefficient[tmp],
                    #     )
                    #     if (z, tmp)
                    #     in [idx for idx in getattr(m, "Meet_Instantaneous_Penetration_min_Constraint")]
                    #     else None
                    # ),
                    # duals_wrapper(m, getattr(m, "Meet_Instantaneous_Penetration_max_Constraint")[z, tmp])
                    # if (z, tmp) in [idx for idx in getattr(m, "Meet_Instantaneous_Penetration_max_Constraint")]
                    # else None,
                    # (
                    #     none_dual_type_error_wrapper(
                    #         duals_wrapper(
                    #             m, getattr(m, "Meet_Instantaneous_Penetration_max_Constraint")[z, tmp]
                    #         ),
                    #         m.tmp_objective_coefficient[tmp],
                    #     )
                    #     if (z, tmp)
                    #     in [idx for idx in getattr(m, "Meet_Instantaneous_Penetration_max_Constraint")]
                    #     else None
                    # ),
                ]
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
    """

    :param scenario_id:
    :param c:
    :param db:
    :param results_directory:
    :param quiet:
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
        which_results=f"system_instantaneous_penetration",
    )
