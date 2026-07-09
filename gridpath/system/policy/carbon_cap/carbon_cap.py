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
Carbon cap for each carbon_cap zone
"""

import csv
import os.path
import pandas as pd

from pyomo.environ import Set, Param, NonNegativeReals, value

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.carbon_cap import CARBON_CAP_ZONE_PRD_DF


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

    m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP = Set(
        dimen=2, within=m.CARBON_CAP_ZONES * m.PERIODS
    )
    m.carbon_cap_target = Param(
        m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP, within=NonNegativeReals
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
    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "carbon_cap.tab",
        ),
        index=m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP,
        param=m.carbon_cap_target,
        select=("carbon_cap_zone", "period", "carbon_cap_target"),
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
    carbon_cap_targets = c.execute(
        """SELECT carbon_cap_zone, period, carbon_cap
        FROM inputs_system_carbon_cap_targets
        JOIN
        (SELECT period
        FROM inputs_temporal_periods
        WHERE temporal_scenario_id = {}) as relevant_periods
        USING (period)
        JOIN
        (SELECT carbon_cap_zone
        FROM inputs_geography_carbon_cap_zones
        WHERE carbon_cap_zone_scenario_id = {}) as relevant_zones
        using (carbon_cap_zone)
        WHERE carbon_cap_target_scenario_id = {}
        AND subproblem_id = {}
        AND stage_id = {};
        """.format(
            subscenarios.TEMPORAL_SCENARIO_ID,
            subscenarios.CARBON_CAP_ZONE_SCENARIO_ID,
            subscenarios.CARBON_CAP_TARGET_SCENARIO_ID,
            subproblem,
            stage,
        )
    )

    return carbon_cap_targets


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
    # carbon_cap_targets = get_inputs_from_database(
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
    carbon_cap.tab file.
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

    carbon_cap_targets = get_inputs_from_database(
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
            "carbon_cap.tab",
        ),
        "w",
        newline="",
    ) as carbon_cap_file:
        writer = csv.writer(carbon_cap_file, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(["carbon_cap_zone", "period", "carbon_cap_target"])

        for row in carbon_cap_targets:
            writer.writerow(row)


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
        "carbon_cap_target",
    ]
    data = [
        [
            z,
            p,
            m.carbon_cap_target[z, p],
        ]
        for (z, p) in m.CARBON_CAP_ZONE_PERIODS_WITH_CARBON_CAP
    ]
    results_df = create_results_df(
        index_columns=["carbon_cap_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, CARBON_CAP_ZONE_PRD_DF), results_df)
