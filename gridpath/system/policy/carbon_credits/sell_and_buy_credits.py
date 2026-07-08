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
Sell carbon credits to other sectors and buy credits from other sectors.
"""

import csv
import os.path
from pyomo.environ import Param, Var, NonNegativeReals, value, Boolean, Constraint

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_row_monotonicity,
    validate_column_monotonicity,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.auxiliary.dynamic_components import (
    carbon_credits_balance_purchase_components,
    carbon_credits_balance_generation_components,
)
from gridpath.system.policy.carbon_credits import CARBON_CREDITS_ZONE_PRD_DF


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

    m.allow_carbon_credits_infinite_demand = Param(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=Boolean, default=0
    )

    m.carbon_credits_demand_tco2 = Param(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=NonNegativeReals, default=0
    )

    m.carbon_credits_demand_price = Param(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=NonNegativeReals, default=0
    )

    m.allow_carbon_credits_infinite_supply = Param(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=Boolean, default=0
    )

    m.carbon_credits_supply_tco2 = Param(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=NonNegativeReals, default=0
    )

    m.carbon_credits_supply_price = Param(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=NonNegativeReals, default=0
    )

    m.Sell_Carbon_Credits = Var(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=NonNegativeReals, initialize=0
    )

    m.Buy_Carbon_Credits = Var(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=NonNegativeReals, initialize=0
    )

    def max_sell_carbon_credits_rule(mod, z, prd):
        if mod.allow_carbon_credits_infinite_demand[z, prd]:
            return Constraint.Skip
        else:
            return (
                mod.Sell_Carbon_Credits[z, prd]
                <= mod.carbon_credits_demand_tco2[z, prd]
            )

    m.Max_Sell_Carbon_Credits_Constraint = Constraint(
        m.CARBON_CREDITS_ZONES, m.PERIODS, rule=max_sell_carbon_credits_rule
    )

    def max_buy_carbon_credits_rule(mod, z, prd):
        if mod.allow_carbon_credits_infinite_supply[z, prd]:
            return Constraint.Skip
        else:
            return (
                mod.Buy_Carbon_Credits[z, prd] <= mod.carbon_credits_supply_tco2[z, prd]
            )

    m.Max_Buy_Carbon_Credits_Constraint = Constraint(
        m.CARBON_CREDITS_ZONES, m.PERIODS, rule=max_buy_carbon_credits_rule
    )

    # Add to the carbon credits tracking balance
    record_dynamic_components(d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:
    """
    getattr(dynamic_components, carbon_credits_balance_purchase_components).append(
        "Sell_Carbon_Credits"
    )

    getattr(dynamic_components, carbon_credits_balance_generation_components).append(
        "Buy_Carbon_Credits"
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
    """

    :param m:
    :param d:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """
    input_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        str(subproblem),
        str(stage),
        "inputs",
        "carbon_credits_params.tab",
    )
    if os.path.exists(input_file):
        data_portal.load(
            filename=input_file,
            param=(
                m.allow_carbon_credits_infinite_demand,
                m.carbon_credits_demand_tco2,
                m.carbon_credits_demand_price,
                m.allow_carbon_credits_infinite_supply,
                m.carbon_credits_supply_tco2,
                m.carbon_credits_supply_price,
            ),
        )


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
    subproblem = 1 if subproblem == "" else subproblem
    stage = 1 if stage == "" else stage
    c = conn.cursor()
    zones = c.execute(
        f"""SELECT carbon_credits_zone, period, allow_carbon_credits_infinite_demand, carbon_credits_demand_tco2,
                carbon_credits_demand_price, allow_carbon_credits_infinite_supply, carbon_credits_supply_tco2, 
                carbon_credits_supply_price
            FROM
            (SELECT carbon_credits_zone
                FROM inputs_geography_carbon_credits_zones
                WHERE carbon_credits_zone_scenario_id = {subscenarios.CARBON_CREDITS_ZONE_SCENARIO_ID}
            ) as cc_zone_tbl
            CROSS JOIN
            (SELECT period
                FROM inputs_temporal_periods
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            ) as period_tbl
            LEFT OUTER JOIN
            inputs_system_carbon_credits_params
            USING (carbon_credits_zone, period)
            WHERE carbon_credits_params_scenario_id = {subscenarios.CARBON_CREDITS_PARAMS_SCENARIO_ID};
            """
    )

    return zones


def validate_inputs(
    scenario_id,
    subscenarios,
    subproblem,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    stage,
    conn,
):
    """
    Get inputs from database and validate the inputs
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """
    carbon_credits_params = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    # Convert input data into pandas DataFrame
    carbon_credits_params_df = cursor_to_df(carbon_credits_params)
    df_cols = carbon_credits_params_df.columns

    # Filter only for carbon_credit_zone-period combinations that infinite supply and demand is allowed
    carbon_credits_params_df = carbon_credits_params_df[
        (carbon_credits_params_df["allow_carbon_credits_infinite_demand"] == 1)
        & (carbon_credits_params_df["allow_carbon_credits_infinite_supply"] == 1)
    ]

    cols = [
        "carbon_credits_demand_price",
        "carbon_credits_supply_price",
    ]

    # check that min build <= max build
    if set(cols).issubset(set(df_cols)):
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_system_carbon_credits_params",
            severity="High",
            errors=validate_column_monotonicity(
                df=carbon_credits_params_df,
                cols=cols,
                idx_col=["carbon_credits_zone", "period"],
            ),
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
    Get inputs from database and write out the model input
    carbon_tax_zones.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    query_results = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )
    # carbon_tax_zones_carbon_credits_zone_mapping.tab
    df = cursor_to_df(query_results)
    df = df.fillna(".")
    fpath = os.path.join(
        scenario_directory,
        str(subproblem),
        str(stage),
        "inputs",
        "carbon_credits_params.tab",
    )
    df.to_csv(fpath, index=False, sep="\t")


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
        "buy_credits",
        "sell_credits",
    ]
    data = [
        [z, p, value(m.Buy_Carbon_Credits[z, p]), value(m.Sell_Carbon_Credits[z, p])]
        for z in m.CARBON_CREDITS_ZONES
        for p in m.PERIODS
    ]
    results_df = create_results_df(
        index_columns=["carbon_credits_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, CARBON_CREDITS_ZONE_PRD_DF), results_df)
