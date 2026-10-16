# Copyright 2016-2024 Blue Marble Analytics LLC.
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
Policies and "zones" where they will be enforced, with each zone's violation
settings and its import-emissions basis (how the emissions of imports over
transmission lines and market purchases mapped to the zone with the
*import_emissions* compliance type count: ``gross`` or ``net_prd``, see
:code:`gridpath.system.policy.import_emissions`).
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

    m.POLICIES_ZONES = Set(dimen=2)

    m.policy_zone_allow_violation = Param(m.POLICIES_ZONES, within=Boolean, default=0)
    m.policy_zone_violation_penalty_per_unit = Param(
        m.POLICIES_ZONES, within=NonNegativeReals, default=0
    )
    m.policy_import_emissions_basis = Param(
        m.POLICIES_ZONES, within=IMPORT_EMISSIONS_BASES, default=GROSS
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
            "policy_zones.tab",
        ),
        index=m.POLICIES_ZONES,
        param=(
            m.policy_zone_allow_violation,
            m.policy_zone_violation_penalty_per_unit,
            m.policy_import_emissions_basis,
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
    # TODO: add list of policies subscenario and filter by that here

    c = conn.cursor()
    policies_zones = c.execute(f"""SELECT policy_name, policy_zone, allow_violation,
        violation_penalty_per_unit,
        COALESCE(import_emissions_basis, '{GROSS}') AS import_emissions_basis
        FROM inputs_geography_policy_zones
        WHERE policy_zone_scenario_id = {subscenarios.POLICY_ZONE_SCENARIO_ID};
        """)

    return policies_zones


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
    # policy_zone_zone = get_inputs_from_database(
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
    policy_zones.tab file.
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

    policies_zones = get_inputs_from_database(
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
            "policy_zones.tab",
        ),
        "w",
        newline="",
    ) as policy_zone_zones_file:
        writer = csv.writer(policy_zone_zones_file, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "policy_name",
                "policy_zone",
                "allow_violation",
                "violation_penalty_per_unit",
                "import_emissions_basis",
            ]
        )

        for row in policies_zones:
            writer.writerow(row)
