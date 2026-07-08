# Copyright 2022 (c) Crown Copyright, GC.
# Modifications Copyright Blue Marble Analytics LLC 2023.
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
Min and max transmission targets by balancing type, horizon, and direction.
"""

import csv
import os.path
from pyomo.environ import (
    Set,
    Param,
    NonNegativeReals,
)

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.transmission_targets import TX_TARGETS_DF


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

    m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET = Set(
        dimen=3, within=m.TRANSMISSION_TARGET_ZONES * m.BLN_TYPE_HRZS
    )

    # Transmission targets specified in energy terms for the positive
    # direction of the tx line
    m.transmission_target_pos_dir_min_mwh = Param(
        m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET,
        within=NonNegativeReals,
        default=0,
    )

    m.transmission_target_pos_dir_max_mwh = Param(
        m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET,
        within=NonNegativeReals,
        default=float("inf"),
    )

    # Transmission targets specified in energy terms for the negative
    # direction of the tx line
    m.transmission_target_neg_dir_min_mwh = Param(
        m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET,
        within=NonNegativeReals,
        default=0,
    )

    m.transmission_target_neg_dir_max_mwh = Param(
        m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET,
        within=NonNegativeReals,
        default=float("inf"),
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
    # Load the targets
    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "transmission_targets.tab",
        ),
        index=m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET,
        param=(
            m.transmission_target_pos_dir_min_mwh,
            m.transmission_target_pos_dir_max_mwh,
            m.transmission_target_neg_dir_min_mwh,
            m.transmission_target_neg_dir_max_mwh,
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

    # Get the transmission flow and percent targets
    c = conn.cursor()

    transmission_targets = c.execute(
        f"""SELECT transmission_target_zone, balancing_type, 
        inputs_system_transmission_targets.horizon, 
        transmission_target_pos_dir_min_mwh,
        transmission_target_pos_dir_max_mwh, 
        transmission_target_neg_dir_min_mwh,
        transmission_target_neg_dir_max_mwh
        FROM inputs_system_transmission_targets
        JOIN
        (SELECT balancing_type_horizon, horizon
        FROM inputs_temporal_horizons
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}) AS 
        relevant_bt_horizons
        ON (inputs_system_transmission_targets.balancing_type
        =relevant_bt_horizons.balancing_type_horizon AND 
        inputs_system_transmission_targets.horizon=relevant_bt_horizons.horizon)
        JOIN
        (SELECT transmission_target_zone
        FROM inputs_geography_transmission_target_zones
        WHERE transmission_target_zone_scenario_id = {subscenarios.TRANSMISSION_TARGET_ZONE_SCENARIO_ID}) as relevant_zones
        USING (transmission_target_zone)
        WHERE transmission_target_scenario_id = {subscenarios.TRANSMISSION_TARGET_SCENARIO_ID}
        AND subproblem_id = {subproblem}
        AND stage_ID = {stage}
        ;
        """
    )

    return transmission_targets


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
    transmission_targets.tab file.
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

    transmission_targets = get_inputs_from_database(
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
            "transmission_targets.tab",
        ),
        "w",
        newline="",
    ) as transmission_targets_tab_file:
        writer = csv.writer(
            transmission_targets_tab_file, delimiter="\t", lineterminator="\n"
        )

        # Write header
        writer.writerow(
            [
                "transmission_target_zone",
                "balancing_type",
                "horizon",
                "transmission_target_pos_dir_min_mwh",
                "transmission_target_pos_dir_max_mwh",
                "transmission_target_neg_dir_min_mwh",
                "transmission_target_neg_dir_max_mwh",
            ]
        )

        for row in transmission_targets:
            # It's OK if targets are not specified; they default to 0
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
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """
    results_columns = [
        "transmission_target_pos_dir_min_mwh",
        "transmission_target_pos_dir_max_mwh",
        "transmission_target_neg_dir_min_mwh",
        "transmission_target_neg_dir_max_mwh",
    ]
    data = [
        [
            z,
            bt,
            hz,
            m.transmission_target_pos_dir_min_mwh[z, bt, hz],
            m.transmission_target_pos_dir_max_mwh[z, bt, hz],
            m.transmission_target_neg_dir_min_mwh[z, bt, hz],
            m.transmission_target_neg_dir_max_mwh[z, bt, hz],
        ]
        for (
            z,
            bt,
            hz,
        ) in m.TRANSMISSION_TARGET_ZONE_BLN_TYPE_HRZS_WITH_TRANSMISSION_TARGET
    ]
    results_df = create_results_df(
        index_columns=["transmission_target_zone", "balancing_type", "horizon"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, TX_TARGETS_DF), results_df)
