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
Sell carbon credits to other sectors.
"""

import csv
import os.path
from pyomo.environ import Param, Var, NonNegativeReals, value

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.auxiliary.dynamic_components import (
    carbon_credits_balance_purchase_components,
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

    m.carbon_credit_price = Param(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=NonNegativeReals, default=0
    )

    m.Sell_Carbon_Credits = Var(
        m.CARBON_CREDITS_ZONES, m.PERIODS, within=NonNegativeReals, initialize=0
    )

    # Add to the carbon credits tracking balance
    record_dynamic_components(d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    This method adds the static load to the load balance dynamic components.
    """
    getattr(dynamic_components, carbon_credits_balance_purchase_components).append(
        "Sell_Carbon_Credits"
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
        subproblem,
        stage,
        "inputs",
        "carbon_credits_prices.tab",
    )
    if os.path.exists(input_file):
        data_portal.load(
            filename=input_file,
            param=m.carbon_credit_price,
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

    c = conn.cursor()
    zones = c.execute(f"""SELECT carbon_credits_zone, period, carbon_credit_price
        FROM inputs_system_carbon_credits_prices
        WHERE carbon_credits_price_scenario_id = 
        {subscenarios.CARBON_CREDITS_PRICE_SCENARIO_ID}
        AND period IN (
            SELECT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        );
        """)

    return zones


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
    Get inputs from database and validate the inputs
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """
    pass
    # Validation to be added
    # carbon_tax_zone = get_inputs_from_database(
    #     scenario_id, subscenarios, subproblem, stage, conn)


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

    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )
    query_results = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )
    # carbon_tax_zones_carbon_credits_zone_mapping.tab
    df = cursor_to_df(query_results)
    if not df.empty:
        df = df.fillna(".")
        fpath = os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "carbon_credits_prices.tab",
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
        "sell_credits",
    ]
    data = [
        [
            z,
            p,
            value(m.Sell_Carbon_Credits[z, p]),
        ]
        for z in m.CARBON_CREDITS_ZONES
        for p in m.PERIODS
    ]
    results_df = create_results_df(
        index_columns=["carbon_credits_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, CARBON_CREDITS_ZONE_PRD_DF), results_df)
