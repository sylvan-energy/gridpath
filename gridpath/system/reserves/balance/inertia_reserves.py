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

    # Penalty for violation
    m.Inertia_Reserves_Violation_MWs = Var(
        m.INERTIA_RESERVES_ZONES, m.TMPS, within=NonNegativeReals
    )

    def violation_expression_rule(mod, ba, tmp):
        """

        :param mod:
        :param ba:
        :param tmp:
        :return:
        """
        if mod.inertia_reserves_allow_violation[ba]:
            return mod.Inertia_Reserves_Violation_MWs[ba, tmp]
        else:
            return 0

    m.Inertia_Reserves_Violation_MWs_Expression = Expression(
        m.INERTIA_RESERVES_ZONES * m.TMPS, rule=violation_expression_rule
    )

    # Reserve constraints
    def meet_reserve_rule(mod, ba, tmp):
        return (
            mod.Total_Inertia_Reserves_Provision_MWs[ba, tmp]
            + mod.Inertia_Reserves_Violation_MWs_Expression[ba, tmp]
            >= mod.Iner_Requirement_MWs[ba, tmp]
        )

    m.Meet_Inertia_Reserves_Constraint = Constraint(
        m.INERTIA_RESERVES_ZONES, m.TMPS, rule=meet_reserve_rule
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
            f"system_inertia_reserves.csv",
        ),
        "w",
        newline="",
    ) as results_file:
        writer = csv.writer(results_file)
        writer.writerow(
            [
                f"inertia_reserves_ba",
                "period",
                "timepoint",
                "discount_factor",
                "probability",
                "probability_weighted_discount_factor",
                "number_years_represented",
                "timepoint_weight",
                "number_of_hours_in_timepoint",
                "reserve_requirement_mws",
                "reserve_provision_mws",
                "reserve_violation_mws",
                "dual",
                "marginal_price_per_mws",
            ]
        )
        for ba, tmp in m.INERTIA_RESERVES_ZONES * m.TMPS:
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
                    value(m.Iner_Requirement_MWs[ba, tmp]),
                    value(m.Total_Inertia_Reserves_Provision_MWs[ba, tmp]),
                    value(m.Inertia_Reserves_Violation_MWs_Expression[ba, tmp]),
                    (
                        duals_wrapper(m, m.Meet_Inertia_Reserves_Constraint[ba, tmp])
                        if (ba, tmp)
                        in [idx for idx in m.Meet_Inertia_Reserves_Constraint]
                        else None
                    ),
                    (
                        none_dual_type_error_wrapper(
                            duals_wrapper(
                                m, m.Meet_Inertia_Reserves_Constraint[ba, tmp]
                            ),
                            m.tmp_objective_coefficient[tmp],
                        )
                        if (ba, tmp)
                        in [idx for idx in m.Meet_Inertia_Reserves_Constraint]
                        else None
                    ),
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
        which_results=f"system_inertia_reserves",
    )
