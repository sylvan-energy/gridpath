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

A limit applies to a **market group**, i.e. to the sum of the net positions
of the markets the group contains. A group of one limits a single market, a
group of all the scenario's markets is a system-wide limit, and a group of
some of them, e.g. all the hubs of one region, is a limit on that region's
transactions. Groups may overlap, so a market can be limited on its own and
as part of a wider total at the same time.

A group's net position in a timepoint is the sum, over the markets in the
group and the load zones participating in each, of the net power purchased.
The *final* position is the same quantity including the transactions carried
over from the previous stages.

Limits come at three temporal resolutions. The timepoint-level limits are in
MW and apply to the position in the timepoint. The horizon- and period-level
limits are in MWh and apply to the position summed over the timepoints of the
horizon or period, each weighted by its number of hours and its timepoint
weight. Horizon-level limits follow a balancing type the user picks, so a
limit can be imposed over any horizon defined in the scenario's temporal
structure (a day, a week, a month, ...).

+------------+------------------------------+------+
| Resolution | Limits                       | Unit |
+============+==============================+======+
| Timepoint  | sales, purchases             | MW   |
+------------+------------------------------+------+
| Timepoint  | final sales, final purchases | MW   |
+------------+------------------------------+------+
| Horizon    | sales, purchases             | MWh  |
+------------+------------------------------+------+
| Period     | sales, purchases             | MWh  |
+------------+------------------------------+------+

A limit that is not specified defaults to infinity, i.e. it is not enforced
and no constraint is built for it.

The horizon- and period-level sales limits can optionally be relaxed by the
energy the system's storage loses, for a limit meant to cap net exports
rather than gross ones. The losses are those of the projects of the *stor*
operational type and are system-wide, not group-specific.

**Groups and the scenario's markets.** A group is narrowed to the markets of
the scenario's market subscenario, so one group definition serves scenarios
with different market sets: a group of every hub in the interconnection
limits whichever of them a given scenario models, and a group left with none
of them contributes no constraints. This is the same scoping that lets one
market volume subscenario serve scenarios with different market sets.

**Default (wildcard) rows.** Every limit table accepts a wildcard row that
supplies the default for the rest of the table, so a limit that is the same
in every timepoint, horizon or period need only be entered once. The wildcard
row is the one whose temporal index is 0: ``timepoint = 0`` in the
timepoint-level table, ``horizon = 0`` in the horizon-level table (a separate
default per balancing type) and ``period = 0`` in the period-level table.

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

# The operational type whose losses may be added to the sales limits (see the
# include_storage_losses inputs)
STORAGE_LOSS_OPERATIONAL_TYPE = "stor"

# Cached on the model instance by lz_markets_in_group()
LZ_MARKETS_BY_GROUP_CACHE = "_gridpath_lz_markets_by_market_group"


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
    # Market groups: the markets each group contains, already narrowed to the
    # markets of this scenario
    m.MARKET_GROUP_MARKETS = Set(dimen=2)

    m.MARKET_GROUPS = Set(
        initialize=lambda mod: sorted(
            set(grp for (grp, mrkt) in mod.MARKET_GROUP_MARKETS)
        )
    )

    m.MARKETS_BY_MARKET_GROUP = Set(
        m.MARKET_GROUPS,
        within=m.MARKETS,
        initialize=lambda mod, group: [
            mrkt for (grp, mrkt) in mod.MARKET_GROUP_MARKETS if grp == group
        ],
    )

    # Limits by temporal resolution; each set holds only the group-index
    # pairs a limit was specified for
    m.MARKET_GROUP_TMPS_W_LIMIT = Set(dimen=2, within=m.MARKET_GROUPS * m.TMPS)
    m.max_market_sales = Param(
        m.MARKET_GROUP_TMPS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_market_purchases = Param(
        m.MARKET_GROUP_TMPS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_final_market_sales = Param(
        m.MARKET_GROUP_TMPS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_final_market_purchases = Param(
        m.MARKET_GROUP_TMPS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )

    m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT = Set(
        dimen=3, within=m.MARKET_GROUPS * m.BLN_TYPE_HRZS
    )
    m.max_market_sales_in_hrz = Param(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_market_purchases_in_hrz = Param(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    # Based on 'stor' operational type
    m.max_market_sales_in_hrz_include_storage_losses = Param(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, within=Boolean, default=0
    )

    m.MARKET_GROUP_PRDS_W_LIMIT = Set(dimen=2, within=m.MARKET_GROUPS * m.PERIODS)
    m.max_market_sales_in_prd = Param(
        m.MARKET_GROUP_PRDS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    m.max_market_purchases_in_prd = Param(
        m.MARKET_GROUP_PRDS_W_LIMIT, within=NonNegativeReals, default=Infinity
    )
    # Based on 'stor' operational type
    m.max_market_sales_in_prd_include_storage_losses = Param(
        m.MARKET_GROUP_PRDS_W_LIMIT, within=Boolean, default=0
    )

    # The groups a limit was specified for at any resolution; the position
    # expressions are built for these only, so a scenario that defines groups
    # but limits none of them builds nothing
    m.MARKET_GROUPS_W_LIMITS = Set(
        within=m.MARKET_GROUPS,
        initialize=lambda mod: sorted(
            set(grp for (grp, tmp) in mod.MARKET_GROUP_TMPS_W_LIMIT)
            | set(grp for (grp, bt, hrz) in mod.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT)
            | set(grp for (grp, prd) in mod.MARKET_GROUP_PRDS_W_LIMIT)
        ),
    )

    # The projects whose losses the include_storage_losses limits are based
    # on; collected once here rather than by rescanning PRJ_OPR_TMPS in every
    # horizon's and period's constraint
    m.MARKET_VOLUME_LIMIT_STOR_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: [
            prj
            for prj in mod.PROJECTS
            if mod.operational_type[prj] == STORAGE_LOSS_OPERATIONAL_TYPE
        ],
    )

    # A group's net position in the current stage, and the final position
    # given the previous stages' transactions
    def group_net_market_purchases_init(mod, group, tmp):
        return sum(
            mod.Net_Market_Purchased_Power[lz, mrkt, tmp]
            for (lz, mrkt) in lz_markets_in_group(mod, group)
        )

    m.Group_Net_Market_Purchased_Power = Expression(
        m.MARKET_GROUPS_W_LIMITS, m.TMPS, initialize=group_net_market_purchases_init
    )

    def group_final_net_market_purchases_init(mod, group, tmp):
        return sum(
            mod.Final_Net_Market_Purchased_Power[lz, mrkt, tmp]
            for (lz, mrkt) in lz_markets_in_group(mod, group)
        )

    # Only the timepoint-level limits apply to the final position
    m.Group_Final_Net_Market_Purchased_Power = Expression(
        m.MARKET_GROUP_TMPS_W_LIMIT, initialize=group_final_net_market_purchases_init
    )

    # Timepoint-level limits
    def max_market_sales_rule(mod, group, tmp):
        if mod.max_market_sales[group, tmp] == Infinity:
            return Constraint.Skip
        return (
            mod.Group_Net_Market_Purchased_Power[group, tmp]
            >= -mod.max_market_sales[group, tmp]
        )

    m.Max_Market_Group_Sales_Constraint = Constraint(
        m.MARKET_GROUP_TMPS_W_LIMIT, rule=max_market_sales_rule
    )

    def max_market_purchases_rule(mod, group, tmp):
        if mod.max_market_purchases[group, tmp] == Infinity:
            return Constraint.Skip
        return (
            mod.Group_Net_Market_Purchased_Power[group, tmp]
            <= mod.max_market_purchases[group, tmp]
        )

    m.Max_Market_Group_Purchases_Constraint = Constraint(
        m.MARKET_GROUP_TMPS_W_LIMIT, rule=max_market_purchases_rule
    )

    def max_final_market_sales_rule(mod, group, tmp):
        if mod.max_final_market_sales[group, tmp] == Infinity:
            return Constraint.Skip
        return (
            mod.Group_Final_Net_Market_Purchased_Power[group, tmp]
            >= -mod.max_final_market_sales[group, tmp]
        )

    m.Max_Market_Group_Final_Sales_Constraint = Constraint(
        m.MARKET_GROUP_TMPS_W_LIMIT, rule=max_final_market_sales_rule
    )

    def max_final_market_purchases_rule(mod, group, tmp):
        if mod.max_final_market_purchases[group, tmp] == Infinity:
            return Constraint.Skip
        return (
            mod.Group_Final_Net_Market_Purchased_Power[group, tmp]
            <= mod.max_final_market_purchases[group, tmp]
        )

    m.Max_Market_Group_Final_Purchases_Constraint = Constraint(
        m.MARKET_GROUP_TMPS_W_LIMIT, rule=max_final_market_purchases_rule
    )

    # Horizon-level limits
    def max_market_sales_in_hrz_rule(mod, group, bt, hrz):
        if mod.max_market_sales_in_hrz[group, bt, hrz] == Infinity:
            return Constraint.Skip
        tmps = mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        return group_net_market_purchases_in_tmps(
            mod, group, tmps
        ) >= -mod.max_market_sales_in_hrz[
            group, bt, hrz
        ] + mod.max_market_sales_in_hrz_include_storage_losses[
            group, bt, hrz
        ] * storage_losses_in_tmps(
            mod, tmps
        )

    m.Max_Market_Group_Sales_in_Hrz_Constraint = Constraint(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, rule=max_market_sales_in_hrz_rule
    )

    def max_market_purchases_in_hrz_rule(mod, group, bt, hrz):
        if mod.max_market_purchases_in_hrz[group, bt, hrz] == Infinity:
            return Constraint.Skip
        return (
            group_net_market_purchases_in_tmps(
                mod, group, mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            <= mod.max_market_purchases_in_hrz[group, bt, hrz]
        )

    m.Max_Market_Group_Purchases_in_Hrz_Constraint = Constraint(
        m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT, rule=max_market_purchases_in_hrz_rule
    )

    # Period-level limits
    def max_market_sales_in_prd_rule(mod, group, prd):
        if mod.max_market_sales_in_prd[group, prd] == Infinity:
            return Constraint.Skip
        tmps = mod.TMPS_IN_PRD[prd]
        return group_net_market_purchases_in_tmps(
            mod, group, tmps
        ) >= -mod.max_market_sales_in_prd[
            group, prd
        ] + mod.max_market_sales_in_prd_include_storage_losses[
            group, prd
        ] * storage_losses_in_tmps(
            mod, tmps
        )

    m.Max_Market_Group_Sales_in_Prd_Constraint = Constraint(
        m.MARKET_GROUP_PRDS_W_LIMIT, rule=max_market_sales_in_prd_rule
    )

    def max_market_purchases_in_prd_rule(mod, group, prd):
        if mod.max_market_purchases_in_prd[group, prd] == Infinity:
            return Constraint.Skip
        return (
            group_net_market_purchases_in_tmps(mod, group, mod.TMPS_IN_PRD[prd])
            <= mod.max_market_purchases_in_prd[group, prd]
        )

    m.Max_Market_Group_Purchases_in_Prd_Constraint = Constraint(
        m.MARKET_GROUP_PRDS_W_LIMIT, rule=max_market_purchases_in_prd_rule
    )


def lz_markets_in_group(mod, group):
    """
    The (load zone, market) pairs that make up *group*'s position, built in
    one pass over LZ_MARKETS the first time it is asked for rather than
    rescanned in every index of every position expression.
    """
    cache = getattr(mod, LZ_MARKETS_BY_GROUP_CACHE, None)
    if cache is None:
        cache = {}
        for grp in mod.MARKET_GROUPS:
            markets = set(mod.MARKETS_BY_MARKET_GROUP[grp])
            cache[grp] = [
                (lz, mrkt) for (lz, mrkt) in mod.LZ_MARKETS if mrkt in markets
            ]
        setattr(mod, LZ_MARKETS_BY_GROUP_CACHE, cache)

    return cache[group]


def group_net_market_purchases_in_tmps(mod, group, tmps):
    """
    A market group's net purchased energy in MWh over the timepoints *tmps*.
    """
    return sum(
        mod.Group_Net_Market_Purchased_Power[group, tmp]
        * mod.hrs_in_tmp[tmp]
        * mod.tmp_weight[tmp]
        for tmp in tmps
    )


def storage_losses_in_tmps(mod, tmps):
    """
    Net storage losses in MWh over the timepoints *tmps*, i.e. the energy
    charged less the energy discharged by the projects of the 'stor'
    operational type. System-wide, not specific to a market group.
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

    groups_filename = input_file("market_groups.tab")
    if os.path.exists(groups_filename):
        data_portal.load(filename=groups_filename, set=m.MARKET_GROUP_MARKETS)

    tmp_limits_filename = input_file("market_volume_tmp.tab")
    if os.path.exists(tmp_limits_filename):
        data_portal.load(
            filename=tmp_limits_filename,
            index=m.MARKET_GROUP_TMPS_W_LIMIT,
            param=(
                m.max_market_sales,
                m.max_market_purchases,
                m.max_final_market_sales,
                m.max_final_market_purchases,
            ),
        )

    hrz_limits_filename = input_file("market_volume_hrz.tab")
    if os.path.exists(hrz_limits_filename):
        data_portal.load(
            filename=hrz_limits_filename,
            index=m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT,
            param=(
                m.max_market_sales_in_hrz,
                m.max_market_purchases_in_hrz,
                m.max_market_sales_in_hrz_include_storage_losses,
            ),
        )

    prd_limits_filename = input_file("market_volume_prd.tab")
    if os.path.exists(prd_limits_filename):
        data_portal.load(
            filename=prd_limits_filename,
            index=m.MARKET_GROUP_PRDS_W_LIMIT,
            param=(
                m.max_market_sales_in_prd,
                m.max_market_purchases_in_prd,
                m.max_market_sales_in_prd_include_storage_losses,
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
    :param extra_select: literal columns to emit before the index columns
    :return: the SQL string

    An explicit row wins over the wildcard row and the wildcard row wins over
    the limit's model default of infinity. The COALESCE is per column, so a
    NULL cell in an explicit row falls through to the wildcard row.

    Index entries with neither an explicit nor a wildcard row are dropped, so
    a group with no limits at this resolution contributes no rows and a
    scenario with no limits at all writes no file.
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
        WHERE explicit.{wildcard_column} IS NOT NULL
        OR wildcard.{wildcard_column} IS NOT NULL
        """


def no_rows_sql(columns):
    """
    A query that returns no rows but names *columns*, so a caller that reads
    the cursor's description gets the right header.
    """
    return "SELECT " + ", ".join(f"NULL AS {c}" for c in columns) + " WHERE 0"


def get_market_groups_sql(subscenarios):
    """
    The scenario's market groups and their members, narrowed to the markets
    of the scenario's market subscenario.
    """
    return f"""
        SELECT market_group, market
        FROM inputs_market_groups
        WHERE market_group_scenario_id =
        {subscenarios.MARKET_GROUP_SCENARIO_ID}
        AND market IN (
            SELECT market
            FROM inputs_geography_markets
            WHERE market_scenario_id = {subscenarios.MARKET_SCENARIO_ID}
        )
        ORDER BY market_group, market
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
    groups_c = conn.cursor()
    market_groups = groups_c.execute(get_market_groups_sql(subscenarios))

    c = conn.cursor()
    group_list = c.execute(f"""
        SELECT market_group,
        market_volume_profile_scenario_id,
        market_volume_hrz_profile_scenario_id,
        market_volume_prd_profile_scenario_id,
        varies_by_weather_iteration,
        varies_by_hydro_iteration
        FROM inputs_market_volume
        WHERE market_volume_scenario_id = {subscenarios.MARKET_VOLUME_SCENARIO_ID}
        -- Limit groups that have at least one of the scenario's markets
        AND market_group IN (
            SELECT DISTINCT market_group
            FROM inputs_market_groups
            WHERE market_group_scenario_id =
            {subscenarios.MARKET_GROUP_SCENARIO_ID}
            AND market IN (
                SELECT market
                FROM inputs_geography_markets
                WHERE market_scenario_id = {subscenarios.MARKET_SCENARIO_ID}
            )
        )
        """).fetchall()

    # The three limit resolutions: the temporal index each is resolved
    # against, the table it comes from, and how its wildcard row matches
    resolutions = [
        {
            "table": "inputs_market_volume_profiles",
            "profile_id_column": "market_volume_profile_scenario_id",
            "index_subquery": f"""
                SELECT stage_id, timepoint
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                """,
            "value_columns": [
                "max_market_sales",
                "max_market_purchases",
                "max_final_market_sales",
                "max_final_market_purchases",
            ],
            "index_columns": ["timepoint"],
            "match_columns": ["stage_id", "timepoint"],
            "default_match_columns": ["stage_id"],
            "wildcard_column": "timepoint",
            "data_index_columns": ["stage_id", "timepoint"],
        },
        {
            "table": "inputs_market_volume_hrz_profiles",
            "profile_id_column": "market_volume_hrz_profile_scenario_id",
            "index_subquery": f"""
                SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
                """,
            "value_columns": [
                "max_market_sales_in_hrz",
                "max_market_purchases_in_hrz",
                "max_market_sales_in_hrz_include_storage_losses",
            ],
            "index_columns": ["balancing_type_horizon", "horizon"],
            "match_columns": ["balancing_type_horizon", "horizon"],
            "default_match_columns": ["balancing_type_horizon"],
            "wildcard_column": "horizon",
            "data_index_columns": ["balancing_type_horizon", "horizon"],
        },
        {
            "table": "inputs_market_volume_prd_profiles",
            "profile_id_column": "market_volume_prd_profile_scenario_id",
            "index_subquery": f"""
                SELECT DISTINCT period
                FROM inputs_temporal
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                """,
            "value_columns": [
                "max_market_sales_in_prd",
                "max_market_purchases_in_prd",
                "max_market_sales_in_prd_include_storage_losses",
            ],
            "index_columns": ["period"],
            "match_columns": ["period"],
            "default_match_columns": [],
            "wildcard_column": "period",
            "data_index_columns": ["period"],
        },
    ]

    # Loop over the groups for each resolution's query, since their limits
    # don't all vary by the same iteration types
    n_groups = len(group_list)
    queries = ["" for _ in resolutions]
    n = 1
    for (
        market_group,
        tmp_profile_id,
        hrz_profile_id,
        prd_profile_id,
        varies_by_weather_iteration,
        varies_by_hydro_iteration,
    ) in group_list:
        union_str = "UNION" if n < n_groups else ""

        weather_iteration_to_use = (
            weather_iteration if varies_by_weather_iteration else 0
        )
        hydro_iteration_to_use = hydro_iteration if varies_by_hydro_iteration else 0

        # A profile the group does not have comes back as None; "NULL" makes
        # the filter a valid query that matches no row, so the resolution is
        # simply skipped for this group
        profile_ids = {
            "market_volume_profile_scenario_id": tmp_profile_id,
            "market_volume_hrz_profile_scenario_id": hrz_profile_id,
            "market_volume_prd_profile_scenario_id": prd_profile_id,
        }

        for i, resolution in enumerate(resolutions):
            profile_id = profile_ids[resolution["profile_id_column"]]
            profile_filter = f"""
                market_group = '{market_group}'
                AND {resolution["profile_id_column"]} =
                {"NULL" if profile_id is None else profile_id}
                AND hydro_iteration = {hydro_iteration_to_use}
                AND weather_iteration = {weather_iteration_to_use}
                AND stage_id = {stage}
                """
            data_columns = ", ".join(
                resolution["data_index_columns"] + resolution["value_columns"]
            )
            queries[i] += (
                limits_with_defaults_sql(
                    index_subquery=resolution["index_subquery"],
                    data_subquery=f"""
                    SELECT {data_columns}
                    FROM {resolution["table"]}
                    WHERE {profile_filter}
                    AND {{wildcard_filter}}
                    """,
                    value_columns=resolution["value_columns"],
                    index_columns=resolution["index_columns"],
                    match_columns=resolution["match_columns"],
                    default_match_columns=resolution["default_match_columns"],
                    wildcard_column=resolution["wildcard_column"],
                    extra_select=f"'{market_group}' AS market_group, ",
                )
                + union_str
            )

        n += 1

    limits = []
    for i, resolution in enumerate(resolutions):
        columns = (
            ["market_group"] + resolution["index_columns"] + resolution["value_columns"]
        )
        # With no groups in the volume subscenario there is nothing to
        # resolve; run a query that returns no rows but still names the
        # columns
        query = queries[i] if group_list else no_rows_sql(columns)
        order_by = ", ".join(
            str(j + 1) for j in range(len(columns) - len(resolution["value_columns"]))
        )
        cursor = conn.cursor()
        limits.append(cursor.execute(f"{query} ORDER BY {order_by}"))

    return (market_groups,) + tuple(limits)


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

    Limit rows are resolved against the scenario's temporal structure with
    an inner join, so
    a row naming a balancing type or horizon the scenario does not have is
    dropped silently; flag those rather than let a typo quietly remove a
    limit. Also flag negative limits, which would otherwise fail only at
    model load.

    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """
    c = conn.cursor()
    errors = []

    # A group that narrows to none of the scenario's markets is not an
    # error: group and volume subscenarios are shared across scenarios with
    # different market sets, and such a group simply contributes no
    # constraints. A group the group subscenario never defines at all is a
    # different matter, and is almost always a typo.
    undefined_groups = c.execute(f"""
        SELECT DISTINCT market_group
        FROM inputs_market_volume
        WHERE market_volume_scenario_id = {subscenarios.MARKET_VOLUME_SCENARIO_ID}
        AND market_group NOT IN (
            SELECT DISTINCT market_group
            FROM inputs_market_groups
            WHERE market_group_scenario_id =
            {subscenarios.MARKET_GROUP_SCENARIO_ID}
        )
        """).fetchall()
    for (group,) in undefined_groups:
        errors.append(
            f"inputs_market_volume: market group '{group}' is not defined by "
            f"the scenario's market group subscenario, so its limits are "
            f"ignored."
        )

    # Each profile table has its own subscenario column, which the
    # scenario's market volume subscenario maps each group to
    def profile_filter_for(column):
        return f"""
            (market_group, {column}) IN (
                SELECT market_group, {column}
                FROM inputs_market_volume
                WHERE market_volume_scenario_id =
                {subscenarios.MARKET_VOLUME_SCENARIO_ID}
            )
            """

    profile_filter = profile_filter_for("market_volume_hrz_profile_scenario_id")

    # Balancing types and horizons the temporal structure does not define (a
    # horizon of 0 is the wildcard row and has no horizon to match)
    unknown_bts = c.execute(f"""
        SELECT DISTINCT balancing_type_horizon
        FROM inputs_market_volume_hrz_profiles
        WHERE {profile_filter}
        AND balancing_type_horizon NOT IN (
            SELECT DISTINCT balancing_type_horizon
            FROM inputs_temporal_horizons
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        )
        """).fetchall()
    for (bt,) in unknown_bts:
        errors.append(
            f"inputs_market_volume_hrz_profiles: balancing type '{bt}' is "
            f"not in the scenario's temporal structure, so its limits are "
            f"ignored."
        )

    unknown_hrzs = c.execute(f"""
        SELECT DISTINCT balancing_type_horizon, horizon
        FROM inputs_market_volume_hrz_profiles
        WHERE {profile_filter}
        AND horizon != 0
        AND balancing_type_horizon IN (
            SELECT DISTINCT balancing_type_horizon
            FROM inputs_temporal_horizons
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        )
        AND (balancing_type_horizon, horizon) NOT IN (
            SELECT balancing_type_horizon, horizon
            FROM inputs_temporal_horizons
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        )
        """).fetchall()
    for bt, hrz in unknown_hrzs:
        errors.append(
            f"inputs_market_volume_hrz_profiles: horizon {hrz} of balancing "
            f"type '{bt}' is not in the scenario's temporal structure, so "
            f"its limits are ignored."
        )

    # Negative limits; the model params are non-negative, so these would
    # otherwise fail only at model load
    negative_limit_checks = [
        (
            "inputs_market_volume_profiles",
            "market_volume_profile_scenario_id",
            [
                "max_market_sales",
                "max_market_purchases",
                "max_final_market_sales",
                "max_final_market_purchases",
            ],
        ),
        (
            "inputs_market_volume_hrz_profiles",
            "market_volume_hrz_profile_scenario_id",
            ["max_market_sales_in_hrz", "max_market_purchases_in_hrz"],
        ),
        (
            "inputs_market_volume_prd_profiles",
            "market_volume_prd_profile_scenario_id",
            ["max_market_sales_in_prd", "max_market_purchases_in_prd"],
        ),
    ]
    for table, profile_id_column, columns in negative_limit_checks:
        for column in columns:
            (n_negative,) = c.execute(f"""
                SELECT COUNT(*)
                FROM {table}
                WHERE {profile_filter_for(profile_id_column)}
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

    Get inputs from database and write out the market group and market
    volume limit files.
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
        market_groups,
        tmp_limits,
        hrz_limits,
        prd_limits,
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
        ("market_groups.tab", market_groups),
        ("market_volume_tmp.tab", tmp_limits),
        ("market_volume_hrz.tab", hrz_limits),
        ("market_volume_prd.tab", prd_limits),
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
    Export each market group's limits, the position they constrain, and the
    duals of the constraints enforcing them (a limit left at its default of
    infinity is not enforced and so has no dual).

    The duals are in the objective's NPV terms; normalize each by its index's
    objective coefficient to get a marginal cost per MW or MWh, as the load
    balance marginal costs do.

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    def results_writer(fname, header):
        """
        Open the results file and write its header; most scenarios define no
        limits at a given resolution, and writing nothing rather than a
        header-only file keeps them out of every results directory (a Monte
        Carlo run has one per draw per subproblem).
        """
        f = open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "results",
                fname,
            ),
            "w",
            newline="",
        )
        writer = csv.writer(f)
        writer.writerow(header)
        return f, writer

    if len(m.MARKET_GROUP_TMPS_W_LIMIT) > 0:
        f, writer = results_writer(
            "system_market_volume_tmp.csv",
            [
                "market_group",
                "timepoint",
                "period",
                "net_market_purchased_power_mw",
                "final_net_market_purchased_power_mw",
                "max_market_purchases",
                "max_market_sales",
                "max_final_market_purchases",
                "max_final_market_sales",
                "max_market_purchases_dual",
                "max_market_sales_dual",
                "max_final_market_purchases_dual",
                "max_final_market_sales_dual",
                "max_market_purchases_marginal_cost",
                "max_market_sales_marginal_cost",
                "max_final_market_purchases_marginal_cost",
                "max_final_market_sales_marginal_cost",
            ],
        )
        with f:
            for group, tmp in sorted(m.MARKET_GROUP_TMPS_W_LIMIT):
                duals = [
                    constraint_dual(m, constraint, (group, tmp))
                    for constraint in [
                        m.Max_Market_Group_Purchases_Constraint,
                        m.Max_Market_Group_Sales_Constraint,
                        m.Max_Market_Group_Final_Purchases_Constraint,
                        m.Max_Market_Group_Final_Sales_Constraint,
                    ]
                ]
                coefficient = m.tmp_objective_coefficient[tmp]
                writer.writerow(
                    [
                        group,
                        tmp,
                        m.period[tmp],
                        value(m.Group_Net_Market_Purchased_Power[group, tmp]),
                        value(m.Group_Final_Net_Market_Purchased_Power[group, tmp]),
                        m.max_market_purchases[group, tmp],
                        m.max_market_sales[group, tmp],
                        m.max_final_market_purchases[group, tmp],
                        m.max_final_market_sales[group, tmp],
                    ]
                    + duals
                    + [
                        none_dual_type_error_wrapper(dual, coefficient)
                        for dual in duals
                    ]
                )

    if len(m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT) > 0:
        f, writer = results_writer(
            "system_market_volume_hrz.csv",
            [
                "market_group",
                "balancing_type_horizon",
                "horizon",
                "net_market_purchased_power_mwh",
                "max_market_purchases_in_hrz",
                "max_market_sales_in_hrz",
                "max_market_purchases_in_hrz_dual",
                "max_market_sales_in_hrz_dual",
                "max_market_purchases_in_hrz_marginal_cost",
                "max_market_sales_in_hrz_marginal_cost",
            ],
        )
        with f:
            for group, bt, hrz in sorted(m.MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT):
                duals = [
                    constraint_dual(m, constraint, (group, bt, hrz))
                    for constraint in [
                        m.Max_Market_Group_Purchases_in_Hrz_Constraint,
                        m.Max_Market_Group_Sales_in_Hrz_Constraint,
                    ]
                ]
                coefficient = m.hrz_objective_coefficient[bt, hrz]
                writer.writerow(
                    [
                        group,
                        bt,
                        hrz,
                        value(
                            group_net_market_purchases_in_tmps(
                                m, group, m.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
                            )
                        ),
                        m.max_market_purchases_in_hrz[group, bt, hrz],
                        m.max_market_sales_in_hrz[group, bt, hrz],
                    ]
                    + duals
                    + [
                        none_dual_type_error_wrapper(dual, coefficient)
                        for dual in duals
                    ]
                )

    if len(m.MARKET_GROUP_PRDS_W_LIMIT) > 0:
        f, writer = results_writer(
            "system_market_volume_prd.csv",
            [
                "market_group",
                "period",
                "net_market_purchased_power_mwh",
                "max_market_purchases_in_prd",
                "max_market_sales_in_prd",
                "max_market_purchases_in_prd_dual",
                "max_market_sales_in_prd_dual",
                "max_market_purchases_in_prd_marginal_cost",
                "max_market_sales_in_prd_marginal_cost",
            ],
        )
        with f:
            for group, prd in sorted(m.MARKET_GROUP_PRDS_W_LIMIT):
                duals = [
                    constraint_dual(m, constraint, (group, prd))
                    for constraint in [
                        m.Max_Market_Group_Purchases_in_Prd_Constraint,
                        m.Max_Market_Group_Sales_in_Prd_Constraint,
                    ]
                ]
                coefficient = m.period_objective_coefficient[prd]
                writer.writerow(
                    [
                        group,
                        prd,
                        value(
                            group_net_market_purchases_in_tmps(
                                m, group, m.TMPS_IN_PRD[prd]
                            )
                        ),
                        m.max_market_purchases_in_prd[group, prd],
                        m.max_market_sales_in_prd[group, prd],
                    ]
                    + duals
                    + [
                        none_dual_type_error_wrapper(dual, coefficient)
                        for dual in duals
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
        "system_market_volume_tmp",
        "system_market_volume_hrz",
        "system_market_volume_prd",
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
