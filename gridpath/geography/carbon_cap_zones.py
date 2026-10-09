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
Zones where carbon cap enforced; these can be different from the load
zones and other balancing areas.
"""

import csv
import os.path
from pyomo.environ import Set, Param, Boolean, NonNegativeReals

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.system.policy.import_emissions import GROSS, IMPORT_EMISSIONS_BASES


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

    m.CARBON_CAP_ZONES = Set()

    m.carbon_cap_allow_violation = Param(m.CARBON_CAP_ZONES, within=Boolean, default=0)
    m.carbon_cap_violation_penalty_per_emission = Param(
        m.CARBON_CAP_ZONES, within=NonNegativeReals, default=0
    )
    # How imported emissions count toward the zone; see
    # gridpath.system.policy.import_emissions
    m.carbon_cap_import_emissions_basis = Param(
        m.CARBON_CAP_ZONES, within=IMPORT_EMISSIONS_BASES, default=GROSS
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
    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "carbon_cap_zones.tab",
        ),
        index=m.CARBON_CAP_ZONES,
        param=(
            m.carbon_cap_allow_violation,
            m.carbon_cap_violation_penalty_per_emission,
            m.carbon_cap_import_emissions_basis,
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
    carbon_cap_zone = c.execute("""SELECT carbon_cap_zone, allow_violation, 
        violation_penalty_per_emission,
        COALESCE(import_emissions_basis, 'gross') AS import_emissions_basis
        FROM inputs_geography_carbon_cap_zones
        WHERE carbon_cap_zone_scenario_id = {};
        """.format(subscenarios.CARBON_CAP_ZONE_SCENARIO_ID))

    return carbon_cap_zone


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
    # carbon_cap_zone = get_inputs_from_database(
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
    carbon_cap_zones.tab file.
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

    carbon_cap_zone = get_inputs_from_database(
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
            "carbon_cap_zones.tab",
        ),
        "w",
        newline="",
    ) as carbon_cap_zones_file:
        writer = csv.writer(carbon_cap_zones_file, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "carbon_cap_zone",
                "allow_violation",
                "violation_penalty_per_emission",
                "import_emissions_basis",
            ]
        )

        for row in carbon_cap_zone:
            writer.writerow(row)
