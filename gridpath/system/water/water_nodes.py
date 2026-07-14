# Copyright 2016-2025 Blue Marble Analytics LLC.
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
Water nodes and inflow rate parameters.
"""

import csv
import os.path
from pyomo.environ import (
    Set,
    Param,
    Boolean,
    Reals,
    NonNegativeIntegers,
    Any,
)

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
    :param m:
    :param d:
    :return:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`WATER_NODES`                                                   |
    |                                                                         |
    | Derived from end points of WATER_LINKS.                                 |
    +-------------------------------------------------------------------------+
    | | :code:`WATER_LINKS_TO_BY_WATER_NODE`                                  |
    | | *Defined over*: :code:`WATER_NODES`                                   |
    | | *Within*: :code:`WATER_LINKS`                                         |
    |                                                                         |
    | Derived based on  WATER_LINKS set.                                      |
    +-------------------------------------------------------------------------+
    | | :code:`WATER_LINKS_FROM_BY_WATER_NODE`                                |
    | | *Defined over*: :code:`WATER_NODES`                                   |
    | | *Within*: :code:`WATER_LINKS`                                         |
    |                                                                         |
    | Derived based on  WATER_LINKS set.                                      |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Params                                                                  |
    +=========================================================================+
    | | :code:`exogenous_water_inflow_rate_vol_per_sec`                       |
    | | *Defined over*: :code:`WATER_NODES, TMPS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Water inflow rate at the node at each timepoint. Note this must be      |
    | defined in volume units per second. The total inflow in the timepoint   |
    | will be calculated based on the number of hours in the timepoint. This  |
    | parameter defaults to 0.                                                |
    +-------------------------------------------------------------------------+
    """
    # #### Parameters #### #
    # Inflow rate, defined in volume units per second
    m.exogenous_water_inflow_rate_vol_per_sec = Param(
        m.WATER_NODES, m.TMPS, default=0, within=Reals
    )

    # ### Derived Sets ### #
    # Build the whole indexed structure in one pass over WATER_LINKS rather
    # than rescanning WATER_LINKS for every node
    def water_links_to_by_water_node_init(mod):
        links_by_node = {wn: [] for wn in mod.WATER_NODES}
        for wl in mod.WATER_LINKS:
            links_by_node[mod.water_node_to[wl]].append(wl)

        return links_by_node

    def water_links_from_by_water_node_init(mod):
        links_by_node = {wn: [] for wn in mod.WATER_NODES}
        for wl in mod.WATER_LINKS:
            links_by_node[mod.water_node_from[wl]].append(wl)

        return links_by_node

    m.WATER_LINKS_TO_BY_WATER_NODE = Set(
        m.WATER_NODES, initialize=water_links_to_by_water_node_init
    )

    m.WATER_LINKS_FROM_BY_WATER_NODE = Set(
        m.WATER_NODES, initialize=water_links_from_by_water_node_init
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
            "water_inflows.tab",
        ),
        param=m.exogenous_water_inflow_rate_vol_per_sec,
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
    water_inflows = c.execute(
        f"""SELECT water_node, timepoint, exogenous_water_inflow_rate_vol_per_sec
                FROM inputs_system_water_inflows
                WHERE water_inflow_scenario_id = 
                {subscenarios.WATER_INFLOW_SCENARIO_ID}
                AND water_node IN (
                    SELECT water_node_from as water_node
                    FROM inputs_geography_water_network
                    WHERE water_network_scenario_id = 
                    {subscenarios.WATER_NETWORK_SCENARIO_ID}
                    UNION
                    SELECT water_node_to as water_node
                    FROM inputs_geography_water_network
                    WHERE water_network_scenario_id = 
                    {subscenarios.WATER_NETWORK_SCENARIO_ID}
                )
                AND timepoint
                IN (SELECT timepoint
                    FROM inputs_temporal
                    WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                    AND subproblem_id = {subproblem}
                    AND stage_id = {stage})
                AND hydro_iteration = {hydro_iteration}
                ;
                """
    )
    return water_inflows


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
    water_network.tab file.
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

    inflows = get_inputs_from_database(
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
            "water_inflows.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "water_node",
                "timepoint",
                "exogenous_water_inflow_rate_vol_per_sec",
            ]
        )

        for row in inflows:
            writer.writerow(row)
