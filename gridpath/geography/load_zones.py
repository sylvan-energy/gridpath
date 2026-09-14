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
The **gridpath.geography.load_zones** module describes the geographic unit
at which load is met. Here, we also define whether violations
(overgeneration and unserved energy) are allowed and what the violation
costs are.
"""

import csv
import os.path
from pyomo.environ import Set, Param, Boolean, NonNegativeReals

from gridpath.auxiliary.db_interface import directories_to_db_values


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
    :param d: the dynamic inputs class object; not used here

    The module adds the *LOAD_ZONES* set to the model formulation as well as vairous
    parameters associated with load balance penalties and limits.
    """
    m.LOAD_ZONES = Set()

    m.allow_overgeneration = Param(m.LOAD_ZONES, within=Boolean)
    m.overgeneration_penalty_per_mw = Param(m.LOAD_ZONES, within=NonNegativeReals)

    m.allow_unserved_energy = Param(m.LOAD_ZONES, within=Boolean)

    m.unserved_energy_penalty_per_mwh = Param(
        m.LOAD_ZONES, within=NonNegativeReals, default=0
    )
    m.unserved_energy_limit_mwh = Param(
        m.LOAD_ZONES, within=NonNegativeReals, default=float("inf")
    )

    m.max_unserved_load_penalty_per_mw = Param(
        m.LOAD_ZONES, within=NonNegativeReals, default=0
    )
    m.max_unserved_load_limit_mw = Param(
        m.LOAD_ZONES, within=NonNegativeReals, default=float("inf")
    )

    m.avg_unserved_load_penalty_per_mwa = Param(
        m.LOAD_ZONES, within=NonNegativeReals, default=0
    )

    # Can only be applied if transmission is included
    m.export_penalty_cost_per_mwh = Param(
        m.LOAD_ZONES, within=NonNegativeReals, default=0
    )

    # Unserved energy threshold used in results processing (size of unserved
    # load events that counts for the loss of load statistics)
    m.unserved_energy_stats_threshold_mw = Param(
        m.LOAD_ZONES, within=NonNegativeReals, default=0
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
    :param stage:
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
            "load_zones.tab",
        ),
        index=m.LOAD_ZONES,
        param=(
            m.allow_overgeneration,
            m.overgeneration_penalty_per_mw,
            m.allow_unserved_energy,
            m.unserved_energy_penalty_per_mwh,
            m.unserved_energy_limit_mwh,
            m.max_unserved_load_penalty_per_mw,
            m.max_unserved_load_limit_mw,
            m.avg_unserved_load_penalty_per_mwa,
            m.export_penalty_cost_per_mwh,
            m.unserved_energy_stats_threshold_mw,
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

    c = conn.cursor()
    load_zones = c.execute(f"""
        SELECT load_zone, allow_overgeneration, overgeneration_penalty_per_mw, 
        allow_unserved_energy, unserved_energy_penalty_per_mwh, 
        unserved_energy_limit_mwh, max_unserved_load_penalty_per_mw, 
        max_unserved_load_limit_mw, avg_unserved_load_penalty_per_mwa, 
        export_penalty_cost_per_mwh, unserved_energy_stats_threshold_mw
        FROM inputs_geography_load_balance
        WHERE load_balance_scenario_id = {subscenarios.LOAD_BALANCE_SCENARIO_ID}
        AND load_zone in (
            SELECT load_zone
            FROM inputs_geography_load_zones        
            WHERE load_zone_scenario_id = {subscenarios.LOAD_ZONE_SCENARIO_ID}
        );""")

    return load_zones


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
    # load_zones = get_inputs_from_database(
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
    load_zones.tab file.
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

    load_zones = get_inputs_from_database(
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
            "load_zones.tab",
        ),
        "w",
        newline="",
    ) as load_zones_tab_file:
        writer = csv.writer(load_zones_tab_file, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "load_zone",
                "allow_overgeneration",
                "overgeneration_penalty_per_mw",
                "allow_unserved_energy",
                "unserved_energy_penalty_per_mwh",
                "unserved_energy_limit_mwh",
                "max_unserved_load_penalty_per_mw",
                "max_unserved_load_limit_mw",
                "avg_unserved_load_penalty_per_mwa",
                "export_penalty_cost_per_mwh",
                "unserved_energy_stats_threshold_mw",
            ]
        )

        for row in load_zones:
            replace_nulls = ["." if i is None else i for i in row]
            writer.writerow(replace_nulls)
