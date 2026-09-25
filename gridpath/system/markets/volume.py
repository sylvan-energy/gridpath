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
Limits on how much a scenario may transact in the markets it participates in.

Limits come in two scopes and three temporal resolutions.

The *by-market* limits apply to a single market's net position, i.e. to the
sum of the net purchases of every load zone participating in that market. The
*total* limits apply to the sum of the net positions across all markets, and
are the right place to express a system-wide import or export limit.

Timepoint-level limits are in MW and apply to the net position in the
timepoint. Horizon- and period-level limits are in MWh and apply to the net
position summed over the timepoints of the horizon or period, each weighted
by its number of hours and its timepoint weight. Horizon-level limits follow
a balancing type the user picks, so a limit can be imposed over any horizon
defined in the scenario's temporal structure (a day, a week, a month, ...)
rather than only over a timepoint or a period.

+-------------+----------------+------------------------------+
| Scope       | Resolution     | Limits                       |
+=============+================+==============================+
| By market   | Timepoint (MW) | sales, purchases             |
+-------------+----------------+------------------------------+
| By market   | Timepoint (MW) | final sales, final purchases |
+-------------+----------------+------------------------------+
| By market   | Horizon (MWh)  | net sales, net purchases     |
+-------------+----------------+------------------------------+
| All markets | Timepoint (MW) | net sales, net purchases     |
+-------------+----------------+------------------------------+
| All markets | Horizon (MWh)  | net sales, net purchases     |
+-------------+----------------+------------------------------+
| All markets | Period (MWh)   | net sales, net purchases     |
+-------------+----------------+------------------------------+

The *final* by-timepoint limits apply to the position including the
transactions carried over from previous stages; the others apply to the
position taken in the current stage.

A limit that is not specified defaults to infinity, i.e. it is not enforced
and no constraint is built for it.

**Default (wildcard) rows.** Every limit input table accepts a wildcard row
that supplies the default for the rest of the table, so a limit that is the
same in every timepoint, horizon or period need only be entered once. The
wildcard row is the one whose temporal index is 0: ``timepoint = 0`` in the
timepoint-level tables, ``horizon = 0`` in the horizon-level tables (a
separate default per balancing type) and ``period = 0`` in the period-level
table.

Resolution is per column: an explicit row wins over the wildcard row, and the
wildcard row wins over the default of infinity. A cell left NULL in an
explicit row falls through to the wildcard row, so a row that overrides one
limit need not repeat the others. To leave a single timepoint unlimited when
a finite default is in force, give it an explicitly large value.

The wildcard rows are resolved when the model inputs are written, so the
scenario's input files carry the resolved limits and the model itself never
sees a wildcard.
"""

import csv
import os.path

from pyomo.environ import (
    Boolean,
    Constraint,
    Expression,
    NonNegativeReals,
    Param,
    Set,
    value,
)

from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.auxiliary.validations import write_validation_to_database
from gridpath.common_functions import constraint_dual, none_dual_type_error_wrapper
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)

Infinity = float("inf")

# The operational type whose losses may be added to the total market sales
# limits (see the *include_storage_losses* inputs)
STORAGE_LOSS_OPERATIONAL_TYPE = "stor"


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
    """ """
    m.max_market_sales = Param(m.MARKETS, m.TMPS, default=Infinity)
    m.max_market_purchases = Param(m.MARKETS, m.TMPS, default=Infinity)
    m.max_final_market_sales = Param(m.MARKETS, m.TMPS, default=Infinity)
    m.max_final_market_purchases = Param(m.MARKETS, m.TMPS, default=Infinity)

    # Params limiting a single market's transactions over a horizon of the
    # user's chosen balancing type
    m.MARKET_BLN_TYPE_HRZS_W_VOLUME_LIMIT = Set(
        dimen=3, within=m.MARKETS * m.BLN_TYPE_HRZS
    )
    m.max_market_sales_in_hrz = Param(
        m.MARKET_BLN_TYPE_HRZS_W_VOLUME_LIMIT,
        within=NonNegativeReals,
        default=Infinity,
    )
    m.max_market_purchases_in_hrz = Param(
        m.MARKET_BLN_TYPE_HRZS_W_VOLUME_LIMIT,
        within=NonNegativeReals,
        default=Infinity,
    )

    # Params limiting total transactions across all markets in a timepoint
    m.max_total_net_market_purchases_in_tmp = Param(
        m.TMPS, within=NonNegativeReals, default=Infinity
    )
    m.max_total_net_market_sales_in_tmp = Param(
        m.TMPS, within=NonNegativeReals, default=Infinity
    )

    # Params limiting total transactions across all markets over a horizon of
    # the user's chosen balancing type
    m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT = Set(dimen=2, within=m.BLN_TYPE_HRZS)
    m.max_total_net_market_purchases_in_hrz = Param(
        m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT,
        within=NonNegativeReals,
        default=Infinity,
    )
    m.max_total_net_market_sales_in_hrz = Param(
        m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT,
        within=NonNegativeReals,
        default=Infinity,
    )
    # Based on 'stor' operational type
    m.max_total_net_market_sales_in_hrz_include_storage_losses = Param(
        m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT, within=Boolean, default=0
    )

    # Params limiting total transactions across all markets in a period
    m.max_total_net_market_purchases_in_prd = Param(
        m.PERIODS, within=NonNegativeReals, default=Infinity
    )
    m.max_total_net_market_sales_in_prd = Param(
        m.PERIODS, within=NonNegativeReals, default=Infinity
    )
    # Based on 'stor' operational type
    m.max_total_net_market_sales_in_prd_include_storage_losses = Param(
        m.PERIODS, within=Boolean, default=0
    )

    # The projects whose losses the *include_storage_losses* limits are based
    # on; collected once here rather than by rescanning PRJ_OPR_TMPS in every
    # period's and every horizon's constraint
    m.MARKET_VOLUME_LIMIT_STOR_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: [
            prj
            for prj in mod.PROJECTS
            if mod.operational_type[prj] == STORAGE_LOSS_OPERATIONAL_TYPE
        ],
    )

    # Constrain total net purchases in the current stage
    def total_net_market_purchases_init(mod, market, tmp):
        return sum(
            mod.Net_Market_Purchased_Power[lz, mrkt, tmp]
            for (lz, mrkt) in mod.LZ_MARKETS
            if mrkt == market
        )

    m.Total_Net_Market_Purchased_Power = Expression(
        m.MARKETS, m.TMPS, initialize=total_net_market_purchases_init
    )

    def max_market_sales_rule(mod, market, tmp):
        if mod.max_market_sales[market, tmp] == Infinity:
            return Constraint.Skip
        return (
            mod.Total_Net_Market_Purchased_Power[market, tmp]
            >= -mod.max_market_sales[market, tmp]
        )

    m.Max_Market_Sales_Constraint = Constraint(
        m.MARKETS, m.TMPS, rule=max_market_sales_rule
    )

    def max_market_purchases_rule(mod, market, tmp):
        if mod.max_market_purchases[market, tmp] == Infinity:
            return Constraint.Skip
        return (
            mod.Total_Net_Market_Purchased_Power[market, tmp]
            <= mod.max_market_purchases[market, tmp]
        )

    m.Max_Market_Purchases_Constraint = Constraint(
        m.MARKETS, m.TMPS, rule=max_market_purchases_rule
    )

    # Constrain total final net purchases in the current stage (given previous stage
    # positions)
    def total_final_net_market_purchases_init(mod, market, tmp):
        return sum(
            mod.Final_Net_Market_Purchased_Power[lz, mrkt, tmp]
            for (lz, mrkt) in mod.LZ_MARKETS
            if mrkt == market
        )

    m.Total_Final_Net_Market_Purchased_Power = Expression(
        m.MARKETS, m.TMPS, rule=total_final_net_market_purchases_init
    )

    def max_final_market_sales_rule(mod, market, tmp):
        if mod.max_final_market_sales[market, tmp] == Infinity:
            return Constraint.Skip
        return (
            mod.Total_Final_Net_Market_Purchased_Power[market, tmp]
            >= -mod.max_final_market_sales[market, tmp]
        )

    m.Max_Final_Market_Sales_Constraint = Constraint(
        m.MARKETS, m.TMPS, rule=max_final_market_sales_rule
    )

    def max_final_market_purchases_rule(mod, market, tmp):
        if mod.max_final_market_purchases[market, tmp] == Infinity:
            return Constraint.Skip
        return (
            mod.Total_Final_Net_Market_Purchased_Power[market, tmp]
            <= mod.max_final_market_purchases[market, tmp]
        )

    m.Max_Final_Market_Purchases_Constraint = Constraint(
        m.MARKETS, m.TMPS, rule=max_final_market_purchases_rule
    )

    # Horizon-level limits by market
    def market_sales_in_hrz_constraint_rule(mod, market, bt, hrz):
        if mod.max_market_sales_in_hrz[market, bt, hrz] == Infinity:
            return Constraint.Skip
        return (
            net_market_purchases_in_hrz(mod, market, bt, hrz)
            >= -mod.max_market_sales_in_hrz[market, bt, hrz]
        )

    m.Max_Market_Sales_in_Hrz_Constraint = Constraint(
        m.MARKET_BLN_TYPE_HRZS_W_VOLUME_LIMIT, rule=market_sales_in_hrz_constraint_rule
    )

    def market_purchases_in_hrz_constraint_rule(mod, market, bt, hrz):
        if mod.max_market_purchases_in_hrz[market, bt, hrz] == Infinity:
            return Constraint.Skip
        return (
            net_market_purchases_in_hrz(mod, market, bt, hrz)
            <= mod.max_market_purchases_in_hrz[market, bt, hrz]
        )

    m.Max_Market_Purchases_in_Hrz_Constraint = Constraint(
        m.MARKET_BLN_TYPE_HRZS_W_VOLUME_LIMIT,
        rule=market_purchases_in_hrz_constraint_rule,
    )

    # Constraints on total transactions across all markets (e.g., a total
    # import limit or total sales limit in a timepoint)
    def total_purchases_in_tmp_constraint_rule(mod, tmp):
        if mod.max_total_net_market_purchases_in_tmp[tmp] == Infinity:
            return Constraint.Skip
        return (
            sum(
                mod.Total_Net_Market_Purchased_Power[market, tmp]
                for market in mod.MARKETS
            )
            <= mod.max_total_net_market_purchases_in_tmp[tmp]
        )

    m.Total_Purchases_in_Tmp_Constraint = Constraint(
        m.TMPS, rule=total_purchases_in_tmp_constraint_rule
    )

    def total_sales_in_tmp_constraint_rule(mod, tmp):
        if mod.max_total_net_market_sales_in_tmp[tmp] == Infinity:
            return Constraint.Skip
        return (
            sum(
                mod.Total_Net_Market_Purchased_Power[market, tmp]
                for market in mod.MARKETS
            )
            >= -mod.max_total_net_market_sales_in_tmp[tmp]
        )

    m.Aggregate_Sales_in_Tmp_Constraint = Constraint(
        m.TMPS, rule=total_sales_in_tmp_constraint_rule
    )

    # Horizon-level totals
    def total_purchases_in_hrz_constraint_rule(mod, bt, hrz):
        if mod.max_total_net_market_purchases_in_hrz[bt, hrz] == Infinity:
            return Constraint.Skip
        return (
            total_net_market_purchases_in_tmps(mod, mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz])
            <= mod.max_total_net_market_purchases_in_hrz[bt, hrz]
        )

    m.Total_Purchases_in_Hrz_Constraint = Constraint(
        m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT,
        rule=total_purchases_in_hrz_constraint_rule,
    )

    def total_sales_in_hrz_constraint_rule(mod, bt, hrz):
        if mod.max_total_net_market_sales_in_hrz[bt, hrz] == Infinity:
            return Constraint.Skip
        tmps = mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        return total_net_market_purchases_in_tmps(
            mod, tmps
        ) >= -mod.max_total_net_market_sales_in_hrz[
            bt, hrz
        ] + mod.max_total_net_market_sales_in_hrz_include_storage_losses[
            bt, hrz
        ] * storage_losses_in_tmps(
            mod, tmps
        )

    m.Aggregate_Sales_in_Hrz_Constraint = Constraint(
        m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT, rule=total_sales_in_hrz_constraint_rule
    )

    # Period-level totals
    # Constraints on total transactions across all markets (e.g., a total
    # import limit or total sales limit in a timepoint)
    def total_purchases_in_prd_constraint_rule(mod, prd):
        if mod.max_total_net_market_purchases_in_prd[prd] == Infinity:
            return Constraint.Skip
        return (
            total_net_market_purchases_in_tmps(mod, mod.TMPS_IN_PRD[prd])
            <= mod.max_total_net_market_purchases_in_prd[prd]
        )

    m.Total_Purchases_in_Prd_Constraint = Constraint(
        m.PERIODS, rule=total_purchases_in_prd_constraint_rule
    )

    def total_sales_in_prd_constraint_rule(mod, prd):
        if mod.max_total_net_market_sales_in_prd[prd] == Infinity:
            return Constraint.Skip
        tmps = mod.TMPS_IN_PRD[prd]
        return total_net_market_purchases_in_tmps(
            mod, tmps
        ) >= -mod.max_total_net_market_sales_in_prd[
            prd
        ] + mod.max_total_net_market_sales_in_prd_include_storage_losses[
            prd
        ] * storage_losses_in_tmps(
            mod, tmps
        )

    m.Aggregate_Sales_in_Prd_Constraint = Constraint(
        m.PERIODS, rule=total_sales_in_prd_constraint_rule
    )


def net_market_purchases_in_hrz(mod, market, bt, hrz):
    """
    A single market's net purchased energy in MWh over the timepoints of
    horizon *hrz* of balancing type *bt*.
    """
    return sum(
        mod.Total_Net_Market_Purchased_Power[market, tmp]
        * mod.hrs_in_tmp[tmp]
        * mod.tmp_weight[tmp]
        for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
    )


def total_net_market_purchases_in_tmps(mod, tmps):
    """
    Net purchased energy in MWh across all markets over the timepoints *tmps*.
    """
    return sum(
        mod.Total_Net_Market_Purchased_Power[market, tmp]
        * mod.hrs_in_tmp[tmp]
        * mod.tmp_weight[tmp]
        for market in mod.MARKETS
        for tmp in tmps
    )


def storage_losses_in_tmps(mod, tmps):
    """
    Net storage losses in MWh over the timepoints *tmps*, i.e. the energy
    charged less the energy discharged by the projects of the 'stor'
    operational type.
    """
    return sum(
        (mod.Stor_Charge_MW[prj, tmp] - mod.Stor_Discharge_MW[prj, tmp])
        * mod.hrs_in_tmp[tmp]
        * mod.tmp_weight[tmp]
        for prj in mod.MARKET_VOLUME_LIMIT_STOR_PRJS
        for tmp in tmps
        if (prj, tmp) in mod.PRJ_OPR_TMPS
    )


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
    def input_file(fname):
        return os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            fname,
        )

    by_market_volumes_filename = input_file("market_volume.tab")
    if os.path.exists(by_market_volumes_filename):
        data_portal.load(
            filename=by_market_volumes_filename,
            param=(
                m.max_market_sales,
                m.max_market_purchases,
                m.max_final_market_sales,
                m.max_final_market_purchases,
            ),
        )

    by_market_hrz_volumes_filename = input_file("market_volume_hrz.tab")
    if os.path.exists(by_market_hrz_volumes_filename):
        data_portal.load(
            filename=by_market_hrz_volumes_filename,
            index=m.MARKET_BLN_TYPE_HRZS_W_VOLUME_LIMIT,
            param=(
                m.max_market_sales_in_hrz,
                m.max_market_purchases_in_hrz,
            ),
        )

    total_volume_in_tmp_filename = input_file("market_volume_totals_in_tmp.tab")
    if os.path.exists(total_volume_in_tmp_filename):
        data_portal.load(
            filename=total_volume_in_tmp_filename,
            param=(
                m.max_total_net_market_purchases_in_tmp,
                m.max_total_net_market_sales_in_tmp,
            ),
        )

    total_volume_in_hrz_filename = input_file("market_volume_totals_in_hrz.tab")
    if os.path.exists(total_volume_in_hrz_filename):
        data_portal.load(
            filename=total_volume_in_hrz_filename,
            index=m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT,
            param=(
                m.max_total_net_market_purchases_in_hrz,
                m.max_total_net_market_sales_in_hrz,
                m.max_total_net_market_sales_in_hrz_include_storage_losses,
            ),
        )

    total_volume_in_prd_filename = input_file("market_volume_totals_in_prd.tab")
    if os.path.exists(total_volume_in_prd_filename):
        data_portal.load(
            filename=total_volume_in_prd_filename,
            param=(
                m.max_total_net_market_purchases_in_prd,
                m.max_total_net_market_sales_in_prd,
                m.max_total_net_market_sales_in_prd_include_storage_losses,
            ),
        )


def limits_with_defaults_sql(
    index_subquery,
    data_subquery,
    value_columns,
    index_columns,
    match_columns,
    default_match_columns,
    wildcard_column,
    gate_on_data,
    extra_select="",
):
    """
    Build the SQL that resolves a limits table against a scenario's temporal
    index, applying the table's wildcard (default) rows.

    :param index_subquery: SQL selecting the scenario's temporal index (e.g.
        its timepoints), i.e. the rows the limits are resolved for
    :param data_subquery: SQL selecting the limits rows, carrying a
        ``{wildcard_filter}`` placeholder that this function fills in to
        select either the explicit rows or the single wildcard row; it must
        select *wildcard_column* along with *value_columns*
    :param value_columns: the limit columns, each emitted as
        COALESCE(explicit, wildcard)
    :param index_columns: the index columns to emit
    :param match_columns: the columns joining the index to the explicit rows
    :param default_match_columns: the columns joining the index to the
        wildcard row; empty for a table with a single table-wide wildcard
    :param wildcard_column: the temporal column whose value of 0 marks the
        wildcard row
    :param gate_on_data: whether to drop index entries that have neither an
        explicit nor a wildcard row, which keeps a scenario with no limits
        from writing a file of nothing but defaults
    :param extra_select: literal columns to emit before the index columns
    :return: the SQL string

    An explicit row wins over the wildcard row and the wildcard row wins over
    the limit's model default of infinity. The COALESCE is per column, so a
    NULL cell in an explicit row falls through to the wildcard row.
    """
    select_index = ", ".join(f"idx.{c} AS {c}" for c in index_columns)
    select_values = ", ".join(
        f"COALESCE(explicit.{c}, wildcard.{c}) AS {c}" for c in value_columns
    )
    explicit_join = " AND ".join(f"idx.{c} = explicit.{c}" for c in match_columns)
    wildcard_join = (
        " AND ".join(f"idx.{c} = wildcard.{c}" for c in default_match_columns)
        if default_match_columns
        else "1 = 1"
    )
    gate = (
        f"WHERE explicit.{wildcard_column} IS NOT NULL "
        f"OR wildcard.{wildcard_column} IS NOT NULL"
        if gate_on_data
        else ""
    )

    return f"""
        SELECT {extra_select}{select_index}, {select_values}
        FROM ({index_subquery}) AS idx
        LEFT OUTER JOIN (
            {data_subquery.format(wildcard_filter=f"{wildcard_column} != 0")}
        ) AS explicit
            ON {explicit_join}
        LEFT OUTER JOIN (
            {data_subquery.format(wildcard_filter=f"{wildcard_column} = 0")}
        ) AS wildcard
            ON {wildcard_join}
        {gate}
        """


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

    c = conn.cursor()
    market_list = c.execute(f"""
        SELECT market, 
        market_volume_profile_scenario_id,
        varies_by_weather_iteration, 
        varies_by_hydro_iteration
        FROM inputs_market_volume
        WHERE market_volume_scenario_id = {subscenarios.MARKET_VOLUME_SCENARIO_ID}
        -- Get volume for included markets only
        AND market in (
            SELECT market
            FROM inputs_geography_markets
            WHERE market_scenario_id = {subscenarios.MARKET_SCENARIO_ID}
        )
        """).fetchall()

    tmps_of_stage_sql = f"""
        SELECT stage_id, timepoint 
        FROM inputs_temporal
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND subproblem_id = {subproblem}
        AND stage_id = {stage}
        """
    hrzs_of_stage_sql = f"""
        SELECT DISTINCT balancing_type_horizon, horizon
        FROM inputs_temporal_horizon_timepoints
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND subproblem_id = {subproblem}
        AND stage_id = {stage}
        """

    tmp_value_columns = [
        "max_market_sales",
        "max_market_purchases",
        "max_final_market_sales",
        "max_final_market_purchases",
    ]
    hrz_value_columns = ["max_market_sales_in_hrz", "max_market_purchases_in_hrz"]

    # Loop over the markets for the final queries since volumes don't all vary
    # by the same iteration types
    n_markets = len(market_list)
    tmp_query_all = str()
    hrz_query_all = str()
    n = 1
    for (
        market,
        market_volume_profile_scenario_id,
        varies_by_weather_iteration,
        varies_by_hydro_iteration,
    ) in market_list:
        union_str = "UNION" if n < n_markets else ""

        weather_iteration_to_use = (
            weather_iteration if varies_by_weather_iteration else 0
        )
        hydro_iteration_to_use = hydro_iteration if varies_by_hydro_iteration else 0

        profile_filter = f"""
            market = '{market}'
            AND market_volume_profile_scenario_id = {market_volume_profile_scenario_id}
            AND hydro_iteration = {hydro_iteration_to_use}
            AND weather_iteration = {weather_iteration_to_use}
            AND stage_id = {stage}
            """

        # Select market name explicitly here to print even if volumes are not
        # found for the relevant timepoints
        tmp_query_all += (
            limits_with_defaults_sql(
                index_subquery=tmps_of_stage_sql,
                data_subquery=f"""
                SELECT stage_id, timepoint, {", ".join(tmp_value_columns)}
                FROM inputs_market_volume_profiles
                WHERE {profile_filter}
                AND {{wildcard_filter}}
                """,
                value_columns=tmp_value_columns,
                index_columns=["timepoint"],
                match_columns=["stage_id", "timepoint"],
                default_match_columns=["stage_id"],
                wildcard_column="timepoint",
                gate_on_data=False,
                extra_select=f"'{market}' AS market, ",
            )
            + union_str
        )

        hrz_query_all += (
            limits_with_defaults_sql(
                index_subquery=hrzs_of_stage_sql,
                data_subquery=f"""
                SELECT balancing_type_horizon, horizon,
                {", ".join(hrz_value_columns)}
                FROM inputs_market_volume_hrz_profiles
                WHERE {profile_filter}
                AND {{wildcard_filter}}
                """,
                value_columns=hrz_value_columns,
                index_columns=["balancing_type_horizon", "horizon"],
                match_columns=["balancing_type_horizon", "horizon"],
                default_match_columns=["balancing_type_horizon"],
                wildcard_column="horizon",
                gate_on_data=True,
                extra_select=f"'{market}' AS market, ",
            )
            + union_str
        )

        n += 1

    # With no markets in the volume subscenario there is nothing to resolve;
    # run a query that returns no rows but still names the columns
    if not market_list:
        tmp_query_all = no_rows_sql(["market", "timepoint"] + tmp_value_columns)
        hrz_query_all = no_rows_sql(
            ["market", "balancing_type_horizon", "horizon"] + hrz_value_columns
        )

    c1 = conn.cursor()
    volume = c1.execute(tmp_query_all)

    c2 = conn.cursor()
    volume_hrz = c2.execute(f"{hrz_query_all} ORDER BY 1, 2, 3")

    # Timepoint totals
    tot_in_tmp_value_columns = [
        "max_total_net_market_purchases_in_tmp",
        "max_total_net_market_sales_in_tmp",
    ]
    totals_in_tmp_query = (
        limits_with_defaults_sql(
            index_subquery=f"""
            SELECT DISTINCT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            """,
            data_subquery=f"""
            SELECT timepoint, {", ".join(tot_in_tmp_value_columns)}
            FROM inputs_market_volume_totals_in_tmp
            WHERE market_volume_total_in_tmp_scenario_id =
            {subscenarios.MARKET_VOLUME_TOTAL_IN_TMP_SCENARIO_ID}
            AND weather_iteration = {weather_iteration}
            AND {{wildcard_filter}}
            """,
            value_columns=tot_in_tmp_value_columns,
            index_columns=["timepoint"],
            match_columns=["timepoint"],
            default_match_columns=[],
            wildcard_column="timepoint",
            gate_on_data=True,
        )
        + " ORDER BY timepoint"
    )
    tot_in_tmp_c = conn.cursor()
    totals_in_tmp_agg = tot_in_tmp_c.execute(totals_in_tmp_query)

    # Horizon totals
    tot_in_hrz_value_columns = [
        "max_total_net_market_purchases_in_hrz",
        "max_total_net_market_sales_in_hrz",
        "max_total_net_market_sales_in_hrz_include_storage_losses",
    ]
    totals_in_hrz_query = (
        limits_with_defaults_sql(
            index_subquery=hrzs_of_stage_sql,
            data_subquery=f"""
            SELECT balancing_type_horizon, horizon,
            {", ".join(tot_in_hrz_value_columns)}
            FROM inputs_market_volume_totals_in_hrz
            WHERE market_volume_total_in_hrz_scenario_id =
            {subscenarios.MARKET_VOLUME_TOTAL_IN_HRZ_SCENARIO_ID}
            AND weather_iteration = {weather_iteration}
            AND {{wildcard_filter}}
            """,
            value_columns=tot_in_hrz_value_columns,
            index_columns=["balancing_type_horizon", "horizon"],
            match_columns=["balancing_type_horizon", "horizon"],
            default_match_columns=["balancing_type_horizon"],
            wildcard_column="horizon",
            gate_on_data=True,
        )
        + " ORDER BY balancing_type_horizon, horizon"
    )
    tot_in_hrz_c = conn.cursor()
    totals_in_hrz_agg = tot_in_hrz_c.execute(totals_in_hrz_query)

    # Period totals
    tot_in_prd_value_columns = [
        "max_total_net_market_purchases_in_prd",
        "max_total_net_market_sales_in_prd",
        "max_total_net_market_sales_in_prd_include_storage_losses",
    ]
    totals_in_prd_query = (
        limits_with_defaults_sql(
            index_subquery=f"""
            SELECT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            """,
            data_subquery=f"""
            SELECT period, {", ".join(tot_in_prd_value_columns)}
            FROM inputs_market_volume_totals_in_prd
            WHERE market_volume_total_in_prd_scenario_id =
            {subscenarios.MARKET_VOLUME_TOTAL_IN_PRD_SCENARIO_ID}
            AND {{wildcard_filter}}
            """,
            value_columns=tot_in_prd_value_columns,
            index_columns=["period"],
            match_columns=["period"],
            default_match_columns=[],
            wildcard_column="period",
            gate_on_data=True,
        )
        + " ORDER BY period"
    )
    tot_in_prd_c = conn.cursor()
    totals_in_prd_agg = tot_in_prd_c.execute(totals_in_prd_query)

    return (
        volume,
        volume_hrz,
        totals_in_tmp_agg,
        totals_in_hrz_agg,
        totals_in_prd_agg,
    )


def no_rows_sql(columns):
    """
    A query that returns no rows but names *columns*, so a caller that reads
    the cursor's description gets the right header.
    """
    return "SELECT " + ", ".join(f"NULL AS {c}" for c in columns) + " WHERE 0"


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
    Get inputs from database and validate the inputs.

    The limits are resolved against the scenario's temporal structure with an
    inner join, so a row that names a balancing type or a horizon the scenario
    does not have is silently dropped; flag those rather than let a typo
    quietly remove a limit. Also flag negative limits, which would otherwise
    fail only at model load.

    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """
    c = conn.cursor()

    # The two per-market profile tables share one subscenario ID, which the
    # scenario's market volume subscenario maps each market to
    profile_filter = f"""
        market_volume_profile_scenario_id IN (
            SELECT market_volume_profile_scenario_id
            FROM inputs_market_volume
            WHERE market_volume_scenario_id =
            {subscenarios.MARKET_VOLUME_SCENARIO_ID}
        )
        """
    totals_in_hrz_filter = f"""
        market_volume_total_in_hrz_scenario_id =
        {subscenarios.MARKET_VOLUME_TOTAL_IN_HRZ_SCENARIO_ID}
        """

    horizon_tables = {
        "inputs_market_volume_hrz_profiles": profile_filter,
        "inputs_market_volume_totals_in_hrz": totals_in_hrz_filter,
    }

    errors = []
    for table, subscenario_filter in horizon_tables.items():
        # Balancing types the scenario's temporal structure does not define
        unknown_bts = c.execute(f"""
            SELECT DISTINCT balancing_type_horizon
            FROM {table}
            WHERE {subscenario_filter}
            AND balancing_type_horizon NOT IN (
                SELECT DISTINCT balancing_type_horizon
                FROM inputs_temporal_horizons
                WHERE temporal_scenario_id =
                {subscenarios.TEMPORAL_SCENARIO_ID}
            )
            """).fetchall()
        for (bt,) in unknown_bts:
            errors.append(
                f"{table}: balancing type '{bt}' is not in the scenario's "
                f"temporal structure, so its limits are ignored."
            )

        # Horizons the scenario's temporal structure does not define (a
        # horizon of 0 is the wildcard row and has no horizon to match)
        unknown_hrzs = c.execute(f"""
            SELECT DISTINCT balancing_type_horizon, horizon
            FROM {table}
            WHERE {subscenario_filter}
            AND horizon != 0
            AND balancing_type_horizon IN (
                SELECT DISTINCT balancing_type_horizon
                FROM inputs_temporal_horizons
                WHERE temporal_scenario_id =
                {subscenarios.TEMPORAL_SCENARIO_ID}
            )
            AND (balancing_type_horizon, horizon) NOT IN (
                SELECT balancing_type_horizon, horizon
                FROM inputs_temporal_horizons
                WHERE temporal_scenario_id =
                {subscenarios.TEMPORAL_SCENARIO_ID}
            )
            """).fetchall()
        for bt, hrz in unknown_hrzs:
            errors.append(
                f"{table}: horizon {hrz} of balancing type '{bt}' is not in "
                f"the scenario's temporal structure, so its limits are "
                f"ignored."
            )

    # Negative limits; the model params are non-negative, so these would
    # otherwise fail only at model load
    negative_limit_checks = [
        (
            "inputs_market_volume_profiles",
            [
                "max_market_sales",
                "max_market_purchases",
                "max_final_market_sales",
                "max_final_market_purchases",
            ],
            profile_filter,
        ),
        (
            "inputs_market_volume_hrz_profiles",
            ["max_market_sales_in_hrz", "max_market_purchases_in_hrz"],
            profile_filter,
        ),
        (
            "inputs_market_volume_totals_in_tmp",
            [
                "max_total_net_market_purchases_in_tmp",
                "max_total_net_market_sales_in_tmp",
            ],
            f"""market_volume_total_in_tmp_scenario_id =
            {subscenarios.MARKET_VOLUME_TOTAL_IN_TMP_SCENARIO_ID}""",
        ),
        (
            "inputs_market_volume_totals_in_hrz",
            [
                "max_total_net_market_purchases_in_hrz",
                "max_total_net_market_sales_in_hrz",
            ],
            totals_in_hrz_filter,
        ),
        (
            "inputs_market_volume_totals_in_prd",
            [
                "max_total_net_market_purchases_in_prd",
                "max_total_net_market_sales_in_prd",
            ],
            f"""market_volume_total_in_prd_scenario_id =
            {subscenarios.MARKET_VOLUME_TOTAL_IN_PRD_SCENARIO_ID}""",
        ),
    ]
    for table, columns, subscenario_filter in negative_limit_checks:
        for column in columns:
            (n_negative,) = c.execute(f"""
                SELECT COUNT(*)
                FROM {table}
                WHERE {subscenario_filter}
                AND {column} < 0
                """).fetchone()
            if n_negative:
                errors.append(
                    f"{table}: {n_negative} row(s) have a negative "
                    f"{column}; market volume limits must be non-negative."
                )

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_market_volume",
        severity="High",
        errors=errors,
    )


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
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection

    Get inputs from database and write out the model input
    market volume files.
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
        market_limits,
        market_limits_hrz,
        totals_in_tmp,
        totals_in_hrz,
        totals_in_prd,
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

    for fname, data in [
        ("market_volume.tab", market_limits),
        ("market_volume_hrz.tab", market_limits_hrz),
        ("market_volume_totals_in_tmp.tab", totals_in_tmp),
        ("market_volume_totals_in_hrz.tab", totals_in_hrz),
        ("market_volume_totals_in_prd.tab", totals_in_prd),
    ]:
        write_tab_file_model_inputs(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            fname=fname,
            data=data,
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
    Export the horizon-level market volume limits, the energy they constrain,
    and the duals of the constraints enforcing them (a limit left at its
    default of infinity is not enforced and so has no dual).

    The timepoint- and period-level limits are not exported here; the
    positions they constrain are in the market participation results.

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    def results_file(fname):
        return os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            fname,
        )

    # Most scenarios define no horizon-level limits; write nothing rather
    # than a header-only file in every results directory (a Monte Carlo run
    # has one per draw per subproblem)
    if len(m.MARKET_BLN_TYPE_HRZS_W_VOLUME_LIMIT) > 0:
        with open(results_file("system_market_volume_hrz.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "market",
                    "balancing_type_horizon",
                    "horizon",
                    "net_market_purchased_power_mwh",
                    "max_market_purchases_in_hrz",
                    "max_market_sales_in_hrz",
                    "max_market_purchases_in_hrz_dual",
                    "max_market_sales_in_hrz_dual",
                    "max_market_purchases_in_hrz_marginal_cost",
                    "max_market_sales_in_hrz_marginal_cost",
                ]
            )
            for market, bt, hrz in sorted(m.MARKET_BLN_TYPE_HRZS_W_VOLUME_LIMIT):
                purchases_dual = constraint_dual(
                    m, m.Max_Market_Purchases_in_Hrz_Constraint, (market, bt, hrz)
                )
                sales_dual = constraint_dual(
                    m, m.Max_Market_Sales_in_Hrz_Constraint, (market, bt, hrz)
                )
                # The duals are in the objective's NPV terms; normalize by
                # the horizon's objective coefficient to get a marginal cost
                # per MWh, as the load balance marginal costs do
                coefficient = m.hrz_objective_coefficient[bt, hrz]
                writer.writerow(
                    [
                        market,
                        bt,
                        hrz,
                        value(net_market_purchases_in_hrz(m, market, bt, hrz)),
                        m.max_market_purchases_in_hrz[market, bt, hrz],
                        m.max_market_sales_in_hrz[market, bt, hrz],
                        purchases_dual,
                        sales_dual,
                        none_dual_type_error_wrapper(purchases_dual, coefficient),
                        none_dual_type_error_wrapper(sales_dual, coefficient),
                    ]
                )

    if len(m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT) > 0:
        with open(
            results_file("system_market_volume_totals_in_hrz.csv"), "w", newline=""
        ) as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "balancing_type_horizon",
                    "horizon",
                    "total_net_market_purchased_power_mwh",
                    "max_total_net_market_purchases_in_hrz",
                    "max_total_net_market_sales_in_hrz",
                    "max_total_net_market_purchases_in_hrz_dual",
                    "max_total_net_market_sales_in_hrz_dual",
                    "max_total_net_market_purchases_in_hrz_marginal_cost",
                    "max_total_net_market_sales_in_hrz_marginal_cost",
                ]
            )
            for bt, hrz in sorted(m.BLN_TYPE_HRZS_W_TOTAL_VOLUME_LIMIT):
                purchases_dual = constraint_dual(
                    m, m.Total_Purchases_in_Hrz_Constraint, (bt, hrz)
                )
                sales_dual = constraint_dual(
                    m, m.Aggregate_Sales_in_Hrz_Constraint, (bt, hrz)
                )
                coefficient = m.hrz_objective_coefficient[bt, hrz]
                writer.writerow(
                    [
                        bt,
                        hrz,
                        value(
                            total_net_market_purchases_in_tmps(
                                m, m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
                            )
                        ),
                        m.max_total_net_market_purchases_in_hrz[bt, hrz],
                        m.max_total_net_market_sales_in_hrz[bt, hrz],
                        purchases_dual,
                        sales_dual,
                        none_dual_type_error_wrapper(purchases_dual, coefficient),
                        none_dual_type_error_wrapper(sales_dual, coefficient),
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
    for which_results in [
        "system_market_volume_hrz",
        "system_market_volume_totals_in_hrz",
    ]:
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
            which_results=which_results,
        )
