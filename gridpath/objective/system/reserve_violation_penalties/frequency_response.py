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


from pyomo.environ import Expression

from gridpath.auxiliary.dynamic_components import cost_components
from .aggregate_reserve_violation_penalties import (
    generic_record_dynamic_components,
    generic_add_model_components,
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

    # Total freq response requirement
    generic_add_model_components(
        m,
        d,
        scenario_directory,
        subproblem,
        stage,
        "FREQUENCY_RESPONSE_BAS",
        "Frequency_Response_Violation_MW_Expression",
        "frequency_response_violation_penalty_per_mw",
        "Frequency_Response_Penalty_Costs",
    )

    # Partial frequency response requirement

    # Add violation penalty costs incurred to objective function
    # Assume violation cost is the same as for the total requirement
    def partial_frequency_response_penalty_costs_rule(mod):
        return sum(
            mod.Frequency_Response_Partial_Violation_MW[ba, tmp]
            * mod.frequency_response_violation_penalty_per_mw[ba]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for (ba, tmp) in mod.FREQUENCY_RESPONSE_BAS * mod.TMPS
        )

    m.Frequency_Response_Partial_Penalty_Costs = Expression(
        rule=partial_frequency_response_penalty_costs_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    generic_record_dynamic_components(
        dynamic_components, "Frequency_Response_Penalty_Costs"
    )

    getattr(dynamic_components, cost_components).append(
        "Frequency_Response_Partial_Penalty_Costs"
    )
