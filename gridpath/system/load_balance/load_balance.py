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
The load-balance constraint in GridPath consists of production components
and consumption components that are added by various GridPath modules
depending on the selected features. The sum of the production components
must equal the sum of the consumption components in each zone and timepoint.

At a minimum, for each load zone and timepoint, the user must specify a
static load requirement input as a consumption component. On the production
side, the model aggregates the power output of projects in the respective
load zone and timepoint.

.. note:: Net power output from storage and demand-side resources can be
    negative and is currently aggregated with the 'project' production
    component.

Net transmission into/out of the load zone is another possible production
component (see :ref:`transmission-section-ref`).

The user may also optionally allow unserved energy and/or overgeneration to be
incurred by adding the respective variables to the production and
consumption components respectively, and assigning a per unit cost for each
load-balance violation type.
"""

import os.path
import pandas as pd
from pyomo.environ import Var, Constraint, Expression, NonNegativeReals, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.dynamic_components import (
    load_balance_consumption_components,
    load_balance_production_components,
)
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.load_balance import LOAD_ZONE_TMP_DF


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
    r"""
    :param m: the Pyomo abstract model object we are adding the components to
    :param d: the DynamicComponents class object we are adding components to

    Here we add, the overgeneration and unserved-energy per unit costs
    are declared here as well as the overgeneration and unserved-energy
    variables.

    We also get all other production and consumption components and add them
    to the lhs and rhs of the load-balance constraint respectively. With the
    minimum set of features, the load-balance constraint will be formulated
    like this:

    :math:`Power\_Production\_in\_Zone\_MW_{z, tmp} + Unserved\_Energy\_MW_{
    z, tmp} = static\_load\_requirement_{z, tmp} + Overgeneration\_MW_{z,
    tmp}`
    """

    # Penalty variables
    m.Overgeneration_MW = Var(m.LOAD_ZONES, m.TMPS, within=NonNegativeReals)
    m.Unserved_Energy_MW = Var(m.LOAD_ZONES, m.TMPS, within=NonNegativeReals)

    # Penalty expressions (will be zero if violations not allowed)
    def overgeneration_expression_rule(mod, z, tmp):
        """

        :param mod:
        :param z:
        :param tmp:
        :return:
        """
        if mod.allow_overgeneration[z]:
            return mod.Overgeneration_MW[z, tmp]
        else:
            return 0

    m.Overgeneration_MW_Expression = Expression(
        m.LOAD_ZONES, m.TMPS, rule=overgeneration_expression_rule
    )

    def unserved_energy_expression_rule(mod, z, tmp):
        """

        :param mod:
        :param z:
        :param tmp:
        :return:
        """
        if mod.allow_unserved_energy[z]:
            return mod.Unserved_Energy_MW[z, tmp]
        else:
            return 0

    m.Unserved_Energy_MW_Expression = Expression(
        m.LOAD_ZONES, m.TMPS, rule=unserved_energy_expression_rule
    )

    # Add the unserved energy and overgeneration components to the load balance
    record_dynamic_components(dynamic_components=d)

    def meet_load_rule(mod, z, tmp):
        """
        The sum across all energy generation components added by other modules
        for each zone and timepoint must equal the sum across all energy
        consumption components added by other modules for each zone and
        timepoint
        :param mod:
        :param z:
        :param tmp:
        :return:
        """
        return sum(
            getattr(mod, component)[z, tmp]
            for component in getattr(d, load_balance_production_components)
        ) == sum(
            getattr(mod, component)[z, tmp]
            for component in getattr(d, load_balance_consumption_components)
        )

    m.Meet_Load_Constraint = Constraint(m.LOAD_ZONES, m.TMPS, rule=meet_load_rule)

    def use_limit_constraint_rule(mod, lz):
        # No limit specified (defaults to +inf): skip the constraint entirely
        # rather than build a row with an infinite (or huge) RHS, which would
        # be a free row that only hurts solver scaling.
        if mod.unserved_energy_limit_mwh[lz] == float("inf"):
            return Constraint.Skip
        return (
            sum(
                mod.Unserved_Energy_MW_Expression[lz, tmp]
                * mod.hrs_in_tmp[tmp]
                * mod.tmp_weight[tmp]
                for tmp in mod.TMPS
            )
            <= mod.unserved_energy_limit_mwh[lz]
        )

    m.Total_USE_Limit_Constraint = Constraint(
        m.LOAD_ZONES, rule=use_limit_constraint_rule
    )

    def max_unserved_load_limit_constraint_rule(mod, lz, tmp):
        # No limit specified (defaults to +inf): skip (see above).
        if mod.max_unserved_load_limit_mw[lz] == float("inf"):
            return Constraint.Skip
        return (
            mod.Unserved_Energy_MW_Expression[lz, tmp]
            <= mod.max_unserved_load_limit_mw[lz]
        )

    m.Max_Unserved_Load_Limit_Constraint = Constraint(
        m.LOAD_ZONES, m.TMPS, rule=max_unserved_load_limit_constraint_rule
    )


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    This method adds the unserved energy and overgeneration to the load balance
    dynamic components.
    """

    getattr(dynamic_components, load_balance_production_components).append(
        "Unserved_Energy_MW_Expression"
    )
    getattr(dynamic_components, load_balance_consumption_components).append(
        "Overgeneration_MW_Expression"
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
    :param stage:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    results_columns = [
        "overgeneration_mw",
        "unserved_energy_mw",
        "load_balance_dual",
        "load_balance_marginal_cost_per_mw",
    ]
    data = [
        [
            lz,
            tmp,
            value(m.Overgeneration_MW_Expression[lz, tmp]),
            value(m.Unserved_Energy_MW_Expression[lz, tmp]),
            duals_wrapper(m, getattr(m, "Meet_Load_Constraint")[lz, tmp]),
            none_dual_type_error_wrapper(
                duals_wrapper(m, getattr(m, "Meet_Load_Constraint")[lz, tmp]),
                m.tmp_objective_coefficient[tmp],
            ),
        ]
        for lz in getattr(m, "LOAD_ZONES")
        for tmp in getattr(m, "TMPS")
    ]
    results_df = create_results_df(
        index_columns=["load_zone", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, LOAD_ZONE_TMP_DF), results_df)


def export_summary_results(
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
    :param stage:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    # TODO: add dynamic load to these summaries when implemented
    lz_tmp_df = pd.DataFrame(
        columns=[
            "load_zone",
            "timepoint",
            "period",
            "month",
            "day_of_month",
            "hour_of_day",
            "timepoint_weight",
            "number_of_hours_in_timepoint",
            "static_load_mw",
            "unserved_energy_stats_threshold_mw",
            "unserved_energy_mw",
        ],
        data=[
            [
                z,
                tmp,
                m.period[tmp],
                m.month[tmp],
                m.day_of_month[tmp],
                m.hour_of_day[tmp],
                m.tmp_weight[tmp],
                m.hrs_in_tmp[tmp],
                value(m.LZ_Bulk_Static_Load_in_Tmp[z, tmp]),
                m.unserved_energy_stats_threshold_mw[z],
                value(m.Unserved_Energy_MW_Expression[z, tmp]),
            ]
            for z in getattr(m, "LOAD_ZONES")
            for tmp in getattr(m, "TMPS")
            if value(m.Unserved_Energy_MW_Expression[z, tmp])
            > m.unserved_energy_stats_threshold_mw[z]
        ],
    ).set_index(["load_zone", "timepoint"])

    lz_tmp_df.sort_index(inplace=True)

    lz_tmp_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_load_zone_timepoint_loss_of_load_summary.csv",
        ),
        sep=",",
        index=True,
    )

    # Total and max load by load zone
    lz_total_df = pd.DataFrame(
        columns=[
            "load_zone",
            "period",
            "total_static_load_mwh",
            "max_static_load_mw",
        ],
        data=[
            [
                z,
                prd,
                sum(
                    value(m.LZ_Bulk_Static_Load_in_Tmp[z, tmp])
                    * m.tmp_weight[tmp]
                    * m.hrs_in_tmp[tmp]
                    for tmp in m.TMPS_IN_PRD[prd]
                ),
                max(
                    [
                        value(m.LZ_Bulk_Static_Load_in_Tmp[z, tmp])
                        for tmp in m.TMPS_IN_PRD[prd]
                    ]
                ),
            ]
            for z in getattr(m, "LOAD_ZONES")
            for prd in getattr(m, "PERIODS")
        ],
    ).set_index(["load_zone", "period"])

    lz_total_df.sort_index(inplace=True)

    lz_total_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_load_zone_period_load_summary.csv",
        ),
        sep=",",
        index=True,
    )


def process_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate capacity costs by load zone, and break out into
    spinup_or_lookahead.
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("calculating loss of load timepoint summary")

    # results_system_timepoint_loss_of_load_summary
    del_sql = """
        DELETE FROM results_system_timepoint_loss_of_load_summary
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    agg_sql = """
        INSERT INTO results_system_timepoint_loss_of_load_summary
        (scenario_id, weather_iteration, hydro_iteration, 
        availability_iteration, subproblem_id, stage_id, timepoint, period, 
        month, day_of_month, hour_of_day, timepoint_weight, 
        number_of_hours_in_timepoint, 
        spinup_or_lookahead, static_load_mw, unserved_energy_mw)
        SELECT
        scenario_id, weather_iteration, hydro_iteration, 
        availability_iteration, subproblem_id, stage_id, timepoint, period, 
        month, day_of_month, hour_of_day, timepoint_weight, 
        number_of_hours_in_timepoint, spinup_or_lookahead,
        SUM(static_load_mw) AS static_load_mw,
        SUM(unserved_energy_mw) AS unserved_energy_mw
        FROM results_system_load_zone_timepoint_loss_of_load_summary
        WHERE scenario_id = ?
        GROUP BY scenario_id, weather_iteration, hydro_iteration, 
        availability_iteration, subproblem_id, stage_id, timepoint
        ORDER BY scenario_id, weather_iteration, hydro_iteration, 
        availability_iteration, subproblem_id, stage_id, timepoint;"""
    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )

    if not quiet:
        print("calculating loss of load days summary")

    # results_system_days_loss_of_load_summary
    del_sql = """
        DELETE FROM results_system_days_loss_of_load_summary
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    agg_sql = """
        INSERT INTO results_system_days_loss_of_load_summary
        (scenario_id, weather_iteration, hydro_iteration, 
        availability_iteration, subproblem_id, stage_id, period, month, 
        day_of_month, max_unserved_energy_mw, total_unserved_energy_mw, 
        duration_hours)
        SELECT
        scenario_id, weather_iteration, hydro_iteration, 
        availability_iteration, subproblem_id, stage_id, period, month, 
        day_of_month, MAX(unserved_energy_mw) as max_unserved_energy_mw, 
        SUM(unserved_energy_mw * timepoint_weight * 
        number_of_hours_in_timepoint) AS total_unserved_energy_mw,
        SUM(number_of_hours_in_timepoint)
        FROM results_system_timepoint_loss_of_load_summary
        WHERE scenario_id = ?
        GROUP BY scenario_id, weather_iteration, hydro_iteration, 
        availability_iteration, subproblem_id, stage_id, period, month, 
        day_of_month
        ORDER BY scenario_id, weather_iteration, hydro_iteration, 
        availability_iteration, subproblem_id, stage_id, period, month, 
        day_of_month;"""
    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )

    if not quiet:
        print("calculating loss of load metrics summary")

    # results_system_loss_of_load_metrics_summary
    del_sql = """
        DELETE FROM results_system_loss_of_load_metrics_summary
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    iter_combos = c.execute(f"""
        SELECT count(*)
        FROM inputs_temporal_iterations
        WHERE temporal_scenario_id = (
            SELECT temporal_scenario_id
            FROM scenarios WHERE scenario_id = {scenario_id}
        )
        """).fetchone()[0]

    hrs_per_combo = c.execute(f"""
        SELECT SUM(number_of_hours_in_timepoint)
        FROM inputs_temporal
        WHERE temporal_scenario_id = (
            SELECT temporal_scenario_id
            FROM scenarios WHERE scenario_id = {scenario_id}
        )
        """).fetchone()[0]

    hrs_per_year = 8760

    n_years = iter_combos * hrs_per_combo / hrs_per_year

    # Only calculate stats if we have iterations
    if n_years != 0:
        total_loss_of_load_hours, total_use = c.execute(f"""
            SELECT sum(number_of_hours_in_timepoint), sum(unserved_energy_mw * 
            number_of_hours_in_timepoint)
            FROM results_system_timepoint_loss_of_load_summary
            WHERE scenario_id = {scenario_id}
            """).fetchone()

        total_loss_of_load_hours = (
            0 if total_loss_of_load_hours is None else total_loss_of_load_hours
        )
        total_use = 0 if total_use is None else total_use

        LOLH = total_loss_of_load_hours / n_years
        EUE = total_use / n_years

        total_loss_of_load_days = c.execute(f"""
            SELECT count(*)
            FROM results_system_days_loss_of_load_summary
            WHERE scenario_id = {scenario_id}
            """).fetchone()[0]

        total_loss_of_load_days = (
            0 if total_loss_of_load_days is None else total_loss_of_load_days
        )

        LOLE = total_loss_of_load_days / n_years

        years_with_lost_load = c.execute(f"""
            SELECT count(*)
            FROM (
                SELECT DISTINCT weather_iteration, hydro_iteration, 
                availability_iteration
                FROM results_system_days_loss_of_load_summary
                WHERE scenario_id = {scenario_id}
            );
            """).fetchone()[0]

        years_with_lost_load = (
            0 if years_with_lost_load is None else years_with_lost_load
        )

        LOLP = years_with_lost_load / n_years

        metrics_sql = f"""
            INSERT INTO results_system_loss_of_load_metrics_summary
            (scenario_id, LOLH_hrs_per_year, EUE_MWh_per_year, LOLE_days_per_year, 
            LOLP_year_fraction_of_years)
            VALUES ({scenario_id}, {LOLH}, {EUE}, {LOLE}, {LOLP});"""
        spin_on_database_lock(conn=db, cursor=c, sql=metrics_sql, data=(), many=False)

        # results_system_loss_of_load_month_hour_metrics_summary
        # month-hour heat maps

        del_sql = """
            DELETE FROM results_system_loss_of_load_month_hour_metrics_summary
            WHERE scenario_id = ?
            """
        spin_on_database_lock(
            conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
        )

        nh_sql = f"""
            INSERT INTO results_system_loss_of_load_month_hour_metrics_summary
            (scenario_id, month, hour_of_day, LOLH, EUE)
            SELECT scenario_id, month, hour_of_day, 
            sum(number_of_hours_in_timepoint)/{n_years}, 
            sum(unserved_energy_mw * number_of_hours_in_timepoint)/{n_years}
            FROM results_system_timepoint_loss_of_load_summary
            WHERE scenario_id = {scenario_id}
            GROUP BY month, hour_of_day
            ;
            """

        spin_on_database_lock(conn=db, cursor=c, sql=nh_sql, data=(), many=False)

        # convergence
        del_sql = """
            DELETE FROM results_system_loss_of_load_metrics_convergence_summary
            WHERE scenario_id = ?
            """
        spin_on_database_lock(
            conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
        )

        iteration_combos = [combo for combo in c.execute(f"""
            SELECT weather_iteration, hydro_iteration, availability_iteration
            FROM inputs_temporal_iterations
            WHERE temporal_scenario_id = (
                SELECT temporal_scenario_id
                FROM scenarios
                WHERE scenario_id = {scenario_id}
            )
            """).fetchall()]

        n = 1
        current_loss_of_load_hours = 0
        current_use = 0
        current_loss_of_load_days = 0
        current_years_with_lost_load = 0
        for iter_combo in iteration_combos:
            weather_iteration, hydro_iteration, availability_iteration = iter_combo
            current_n_years = n * hrs_per_combo / hrs_per_year

            iter_loss_of_load_hours, iter_use = c.execute(f"""
                    SELECT sum(number_of_hours_in_timepoint), sum(unserved_energy_mw * 
                    number_of_hours_in_timepoint)
                    FROM results_system_timepoint_loss_of_load_summary
                    WHERE scenario_id = {scenario_id}
                    AND weather_iteration = {weather_iteration}
                    AND hydro_iteration = {hydro_iteration}
                    AND availability_iteration = {availability_iteration}
                    ;
                    """).fetchone()

            current_loss_of_load_hours += (
                iter_loss_of_load_hours if iter_loss_of_load_hours is not None else 0
            )
            current_use += iter_use if iter_use is not None else 0

            current_LOLH = current_loss_of_load_hours / current_n_years
            current_EUE = current_use / current_n_years

            iter_loss_of_load_days = c.execute(f"""
                    SELECT count(*)
                    FROM results_system_days_loss_of_load_summary
                    WHERE scenario_id = {scenario_id}
                    AND weather_iteration = {weather_iteration}
                    AND hydro_iteration = {hydro_iteration}
                    AND availability_iteration = {availability_iteration}
                    """).fetchone()[0]

            current_loss_of_load_days += (
                iter_loss_of_load_days if iter_loss_of_load_days is not None else 0
            )
            current_LOLE = current_loss_of_load_days / current_n_years

            iter_years_with_lost_load = c.execute(f"""
                    SELECT count(*)
                    FROM (
                        SELECT DISTINCT weather_iteration, hydro_iteration, 
                        availability_iteration
                        FROM results_system_days_loss_of_load_summary
                        WHERE scenario_id = {scenario_id}
                        AND weather_iteration = {weather_iteration}
                        AND hydro_iteration = {hydro_iteration}
                        AND availability_iteration = {availability_iteration}
                    );
                    """).fetchone()[0]

            current_years_with_lost_load += (
                iter_years_with_lost_load
                if iter_years_with_lost_load is not None
                else 0
            )
            current_LOLP = current_years_with_lost_load / current_n_years

            convergence_sql = f"""
                INSERT INTO results_system_loss_of_load_metrics_convergence_summary
                (scenario_id, n_years, LOLH_hrs_per_year, EUE_MWh_per_year, 
                LOLE_days_per_year, LOLP_year_fraction_of_years)
                VALUES ({scenario_id}, 
                {current_n_years}, {current_LOLH}, {current_EUE}, 
                {current_LOLE}, {current_LOLP})
                ;
            """

            spin_on_database_lock(
                conn=db, cursor=c, sql=convergence_sql, data=(), many=False
            )

            n += 1
