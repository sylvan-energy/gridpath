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
This module adds load-balance penalty costs to the objective function.
Penalties can be applied on unserved energy, overgeneration, and the maximum
unserved load experienced in the study period (the latter is only indexed by
load zone and is not weighted by any timepoint- or period-level parameters).

.. note:: Unserved_Energy_MW, unserved_energy_penalty_per_mwh,
    Overgeneration_MW, overgeneration_penalty_per_mw, and
    max_unserved_load_penalty_per_mw are declared in
    system/load_balance/load_balance.py
"""

from pyomo.environ import Var, NonNegativeReals, Constraint, Expression

from gridpath.auxiliary.dynamic_components import cost_components


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
    :param m: the Pyomo abstract model object we are adding components to
    :param d: the DynamicComponents class object we will get components from

    Here, we aggregate total unserved-energy and overgeneration costs as
    well as any penalties on max unserved load by load zone,
    and add them as a dynamic component to the objective function.

    Note these are aggregated over the entire optimization, not per period.
    """

    m.Max_Unserved_Load_MW = Var(m.LOAD_ZONES, within=NonNegativeReals, initialize=0)

    def max_unserved_load_penalty_constraint_rule(mod, lz, tmp):
        if mod.max_unserved_load_penalty_per_mw[lz] == 0:
            return Constraint.Skip
        else:
            return (
                mod.Max_Unserved_Load_MW[lz]
                >= mod.Unserved_Energy_MW_Expression[lz, tmp]
            )

    m.Max_Unserved_Load_Constraint = Constraint(
        m.LOAD_ZONES, m.TMPS, rule=max_unserved_load_penalty_constraint_rule
    )

    def avg_unserved_load(mod, lz):
        return sum(
            mod.Unserved_Energy_MW_Expression[lz, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for tmp in mod.TMPS
        ) / sum(
            mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            * mod.number_years_represented[mod.period[tmp]]
            * mod.probability_weighted_discount_factor[mod.period[tmp]]
            for tmp in mod.TMPS
        )

    m.Avg_Unserved_Load_MWa = Expression(m.LOAD_ZONES, rule=avg_unserved_load)

    def total_penalty_costs_rule(mod):
        return (
            sum(
                (
                    mod.Unserved_Energy_MW_Expression[z, tmp]
                    * mod.unserved_energy_penalty_per_mwh[z]
                    + mod.Overgeneration_MW_Expression[z, tmp]
                    * mod.overgeneration_penalty_per_mw[z]
                )
                * mod.hrs_in_tmp[tmp]
                * mod.tmp_weight[tmp]
                * mod.number_years_represented[mod.period[tmp]]
                * mod.probability_weighted_discount_factor[mod.period[tmp]]
                for z in mod.LOAD_ZONES
                for tmp in mod.TMPS
            )
            + sum(
                mod.Max_Unserved_Load_MW[z] * mod.max_unserved_load_penalty_per_mw[z]
                for z in mod.LOAD_ZONES
            )
            + sum(
                mod.Avg_Unserved_Load_MWa[z] * mod.avg_unserved_load_penalty_per_mwa[z]
                for z in mod.LOAD_ZONES
            )
        )

    m.Total_Load_Balance_Penalty_Costs = Expression(rule=total_penalty_costs_rule)

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add total load balance penalty costs to cost components
    """

    getattr(dynamic_components, cost_components).append(
        "Total_Load_Balance_Penalty_Costs"
    )
