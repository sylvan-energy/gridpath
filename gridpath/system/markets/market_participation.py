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
import pandas as pd
from pyomo.environ import (
    Set,
    Param,
    Var,
    Expression,
    PositiveIntegers,
    Reals,
    Boolean,
    value,
)

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import check_for_integer_subdirectories
from gridpath.auxiliary.dynamic_components import load_balance_production_components
from gridpath.auxiliary.db_interface import (
    import_csv,
    directories_to_db_values,
)
from gridpath.common_functions import create_results_df
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
    """ """

    m.LZ_MARKETS = Set(dimen=2, within=m.LOAD_ZONES * m.MARKETS)

    m.MARKET_LZS = Set(
        within=m.LOAD_ZONES,
        initialize=lambda mod: sorted(
            list(set([lz for (lz, hub) in mod.LZ_MARKETS])),
        ),
    )

    m.MARKETS_BY_LZ = Set(
        m.MARKET_LZS,
        within=m.MARKETS,
        initialize=lambda mod, lz: [
            hub for (zone, hub) in mod.LZ_MARKETS if zone == lz
        ],
    )

    m.final_participation_stage = Param(
        m.LZ_MARKETS, within=PositiveIntegers, default=1
    )

    # Determine whether there is market participation in this stage
    # If no stages, we're using empty string as the stage, so convert that back to 1
    # If there are stages, convert the string to an integer for the comparison
    m.first_stage_flag = Param(within=Boolean)

    m.no_market_participation_in_stage = Param(
        m.LZ_MARKETS,
        rule=lambda mod, lz, hub: (
            True
            if mod.final_participation_stage[lz, hub]
            < (1 if stage == "" else int(stage))
            else False
        ),
    )

    m.LZ_MARKETS_PREV_STAGE_TMPS = Set(dimen=3)

    m.prev_stage_net_market_purchased_power = Param(
        m.LZ_MARKETS_PREV_STAGE_TMPS, within=Reals, default=0
    )

    # Variables
    # This is positive when purchasing power and negative when buying power
    # Market participation in the current stage
    m.Net_Market_Purchased_Power = Var(m.LZ_MARKETS, m.TMPS, within=Reals)

    # Adjusted net purchased power based on previous stage net purchases to use in
    # the load-balance constraints
    def final_market_position_init(mod, lz, hub, tmp):
        if mod.first_stage_flag:
            prev_position = 0
        else:
            prev_position = mod.prev_stage_net_market_purchased_power[
                lz, hub, mod.prev_stage_tmp_map[tmp]
            ]

        return mod.Net_Market_Purchased_Power[lz, hub, tmp] + prev_position

    m.Final_Net_Market_Purchased_Power = Expression(
        m.LZ_MARKETS, m.TMPS, initialize=final_market_position_init
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
    subproblem_directory = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
    )

    data_portal.load(
        filename=os.path.join(
            subproblem_directory,
            stage,
            "inputs",
            "load_zone_markets.tab",
        ),
        index=m.LZ_MARKETS,
        param=m.final_participation_stage,
    )

    # Load starting market positions if applicable
    stages = check_for_integer_subdirectories(os.path.join(subproblem_directory))

    if stages:
        # First check if we are in the first stage and set the first_stage_flag to
        # True if so; this is we'll know whether to look for previous stage positions
        # (an avoid errors when we are in the first stage)
        if int(stage) == int(stages[0]):
            first_stage_flag = {None: True}
        else:
            first_stage_flag = {None: False}

            starting_market_positions_df = pd.read_csv(
                os.path.join(
                    subproblem_directory,
                    "pass_through_inputs",
                    "market_positions.tab",
                ),
                sep="\t",
                dtype={"stage": str},
            )

            starting_market_positions_df["stage_index"] = (
                starting_market_positions_df.apply(
                    lambda row: stages.index(row["stage"]), axis=1
                )
            )
            prev_stage_net_market_purchased_powers_df = starting_market_positions_df[
                starting_market_positions_df["stage_index"] == stages.index(stage) - 1
            ]
            lz_market_timepoints = list(
                zip(
                    prev_stage_net_market_purchased_powers_df["load_zone"],
                    prev_stage_net_market_purchased_powers_df["market"],
                    prev_stage_net_market_purchased_powers_df["timepoint"],
                )
            )
            net_market_purchased_power_dict = dict(
                zip(
                    lz_market_timepoints,
                    prev_stage_net_market_purchased_powers_df[
                        "final_net_market_purchased_power"
                    ],
                )
            )

            data_portal.data()["LZ_MARKETS_PREV_STAGE_TMPS"] = {
                None: lz_market_timepoints
            }
            data_portal.data()[
                "prev_stage_net_market_purchased_power"
            ] = net_market_purchased_power_dict
    else:
        first_stage_flag = {None: True}

    data_portal.data()["first_stage_flag"] = first_stage_flag


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

    # Get load zones and their markets; only include load zones that are
    # in the load_zone_scenario_id and markets that are in the
    # market_scenario_id
    load_zone_markets = c.execute(
        """
        SELECT load_zone, market, final_participation_stage
        FROM
        -- Get included load_zones only
        (SELECT load_zone
            FROM inputs_geography_load_zones
            WHERE load_zone_scenario_id = ?
        ) as lz_tbl
        LEFT OUTER JOIN 
        -- Get markets for those load zones
        (SELECT load_zone, market, final_participation_stage
            FROM inputs_load_zone_markets
            WHERE load_zone_market_scenario_id = ?
        ) as lz_mh_tbl
        USING (load_zone)
        -- Filter out load zones whose market is not included in our 
        -- market_scenario_id
        WHERE market in (
            SELECT market
                FROM inputs_geography_markets
                WHERE market_scenario_id = ?
        );
        """,
        (
            subscenarios.LOAD_ZONE_SCENARIO_ID,
            subscenarios.LOAD_ZONE_MARKET_SCENARIO_ID,
            subscenarios.MARKET_SCENARIO_ID,
        ),
    )

    return load_zone_markets


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
    load_zone_markets.tab file.
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

    load_zone_markets = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "load_zone_markets.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")

        writer.writerow(["load_zone", "market", "final_participation_stage"])
        for row in load_zone_markets:
            replace_nulls = ["." if i is None else i for i in row]
            writer.writerow(replace_nulls)


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

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_market_participation.csv",
        ),
        "w",
        newline="",
    ) as results_file:
        writer = csv.writer(results_file)
        writer.writerow(
            [
                "load_zone",
                "market",
                "timepoint",
                "period",
                "discount_factor",
                "probability",
                "probability_weighted_discount_factor",
                "number_years_represented",
                "timepoint_weight",
                "number_of_hours_in_timepoint",
                "sell_power",
                "buy_power",
                "net_buy_power",
                "final_sell_power",
                "final_buy_power",
                "final_net_buy_power",
            ]
        )
        for z, mrkt in sorted(getattr(m, "LZ_MARKETS")):
            for tmp in sorted(getattr(m, "TMPS")):
                writer.writerow(
                    [
                        z,
                        mrkt,
                        tmp,
                        m.period[tmp],
                        m.discount_factor[m.period[tmp]],
                        m.probability[m.period[tmp]],
                        m.probability_weighted_discount_factor[m.period[tmp]],
                        m.number_years_represented[m.period[tmp]],
                        m.tmp_weight[tmp],
                        m.hrs_in_tmp[tmp],
                        (
                            -value(m.Net_Market_Purchased_Power[z, mrkt, tmp])
                            if value(m.Net_Market_Purchased_Power[z, mrkt, tmp]) < 0
                            else 0
                        ),
                        (
                            value(m.Net_Market_Purchased_Power[z, mrkt, tmp])
                            if value(m.Net_Market_Purchased_Power[z, mrkt, tmp]) >= 0
                            else 0
                        ),
                        value(m.Net_Market_Purchased_Power[z, mrkt, tmp]),
                        (
                            -value(m.Final_Net_Market_Purchased_Power[z, mrkt, tmp])
                            if value(m.Final_Net_Market_Purchased_Power[z, mrkt, tmp])
                            < 0
                            else 0
                        ),
                        (
                            value(m.Final_Net_Market_Purchased_Power[z, mrkt, tmp])
                            if value(m.Final_Net_Market_Purchased_Power[z, mrkt, tmp])
                            >= 0
                            else 0
                        ),
                        value(m.Final_Net_Market_Purchased_Power[z, mrkt, tmp]),
                    ]
                )


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
    Export all results from the PROJECT_CAPACITY_DF and PROJECT_OPERATIONS_DF
    that various modules have added to
    """

    purchases_dict = {}
    costs_dict = {}
    sales_dict = {}
    revenue_dict = {}
    for z, mrkt in m.LZ_MARKETS:
        for prd in m.PERIODS:
            for tmp in m.TMPS_IN_PRD[prd]:
                month = m.month[tmp]

                # Purchases
                purchases = (
                    value(m.Net_Market_Purchased_Power[z, mrkt, tmp])
                    * m.tmp_weight[tmp]
                    * m.hrs_in_tmp[tmp]
                    if value(m.Net_Market_Purchased_Power[z, mrkt, tmp]) > 0
                    else 0
                )
                if (z, mrkt, prd, month) not in purchases_dict.keys():
                    purchases_dict[z, mrkt, prd, month] = purchases
                else:
                    purchases_dict[z, mrkt, prd, month] += purchases

                # Costs
                costs = (
                    value(m.Net_Market_Purchased_Power[z, mrkt, tmp])
                    * m.tmp_weight[tmp]
                    * m.hrs_in_tmp[tmp]
                    * m.market_price[mrkt, tmp]
                    if value(m.Net_Market_Purchased_Power[z, mrkt, tmp]) > 0
                    else 0
                )
                if (z, mrkt, prd, month) not in costs_dict.keys():
                    costs_dict[z, mrkt, prd, month] = costs
                else:
                    costs_dict[z, mrkt, prd, month] += costs

                # Sales
                sales = (
                    -value(m.Net_Market_Purchased_Power[z, mrkt, tmp])
                    * m.tmp_weight[tmp]
                    * m.hrs_in_tmp[tmp]
                    if value(m.Net_Market_Purchased_Power[z, mrkt, tmp]) < 0
                    else 0
                )
                if (z, mrkt, prd, month) not in sales_dict.keys():
                    sales_dict[z, mrkt, prd, month] = sales
                else:
                    sales_dict[z, mrkt, prd, month] += sales

                # Revenue
                revenue = (
                    -value(m.Net_Market_Purchased_Power[z, mrkt, tmp])
                    * m.tmp_weight[tmp]
                    * m.hrs_in_tmp[tmp]
                    * m.market_price[mrkt, tmp]
                    if value(m.Net_Market_Purchased_Power[z, mrkt, tmp]) < 0
                    else 0
                )
                if (z, mrkt, prd, month) not in revenue_dict.keys():
                    revenue_dict[z, mrkt, prd, month] = revenue
                else:
                    revenue_dict[z, mrkt, prd, month] += revenue

    market_summary_df = pd.DataFrame(
        columns=[
            "load_zone",
            "market",
            "period",
            "month",
            "purchases_mwh",
            "sales_mwh",
            "costs",
            "revenue",
        ],
        data=[
            [
                z,
                mrkt,
                prd,
                month,
                purchases_dict[z, mrkt, prd, month],
                sales_dict[z, mrkt, prd, month],
                costs_dict[z, mrkt, prd, month],
                revenue_dict[z, mrkt, prd, month],
            ]
            for (z, mrkt, prd, month) in purchases_dict.keys()  # purchase and
            # sales dict keys are the same
        ],
    ).set_index(
        [
            "load_zone",
            "market",
            "period",
            "month",
        ]
    )

    market_summary_df.sort_index(inplace=True)

    market_summary_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_market_summary.csv",
        ),
        sep=",",
        index=True,
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
        which_results="system_market_participation",
    )

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
        which_results="system_market_summary",
    )
