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
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)


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
    | | :code:`exogenous_water_inflow_rate_avg_vol_per_sec`                   |
    | | *Defined over*: :code:`WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS`     |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | Average water inflow rate at the node over the horizon, in volume       |
    | units per second. This inflow is spread uniformly across the horizon's  |
    | timepoints and is additive with the timepoint-level inflow rate. Use    |
    | this parameter to reduce data requirements when inflows are defined     |
    | over longer periods of time (e.g. days) rather than by timepoint.       |
    +-------------------------------------------------------------------------+
    | | :code:`total_exogenous_water_inflow_rate_vol_per_sec`                 |
    | | *Defined over*: :code:`WATER_NODES, TMPS`                             |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Derived param: the total exogenous inflow rate at the node in the       |
    | timepoint, i.e. the timepoint-level inflow rate plus the horizon-level  |
    | average inflow rate of each horizon the timepoint belongs to. This is   |
    | the parameter the rest of the model should use.                         |
    +-------------------------------------------------------------------------+
    """
    # #### Parameters #### #
    # Inflow rate by timepoint, defined in volume units per second
    m.exogenous_water_inflow_rate_vol_per_sec = Param(
        m.WATER_NODES, m.TMPS, default=0, within=Reals
    )

    # Average inflow rate by horizon, defined in volume units per second;
    # spread uniformly across the horizon's timepoints and additive with the
    # timepoint-level inflow rate
    m.WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS = Set(
        dimen=3, within=m.WATER_NODES * m.BLN_TYPE_HRZS
    )

    m.exogenous_water_inflow_rate_avg_vol_per_sec = Param(
        m.WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS, within=Reals
    )

    def total_exogenous_water_inflow_rate_init(mod):
        """
        Total exogenous inflow rate by node-timepoint: the timepoint-level
        inflow rate plus the average inflow rate of each horizon the
        timepoint belongs to (the horizon-level inflows are spread
        uniformly, i.e. the average rate is added in each of the horizon's
        timepoints). Built as a sparse dict in one pass over each input's
        data; (node, timepoint) indices with no data fall back to the
        param default of 0.
        """
        total = {
            (wn, tmp): mod.exogenous_water_inflow_rate_vol_per_sec[wn, tmp]
            for (wn, tmp) in mod.exogenous_water_inflow_rate_vol_per_sec.sparse_keys()
        }
        for wn, bt, hrz in mod.WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS:
            avg_rate = mod.exogenous_water_inflow_rate_avg_vol_per_sec[wn, bt, hrz]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                total[wn, tmp] = total.get((wn, tmp), 0) + avg_rate

        return total

    m.total_exogenous_water_inflow_rate_vol_per_sec = Param(
        m.WATER_NODES,
        m.TMPS,
        default=0,
        within=Reals,
        initialize=total_exogenous_water_inflow_rate_init,
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

    # Both inflow files are optional: inflows may be specified by timepoint,
    # by horizon (spread across the horizon's timepoints), or both (they are
    # additive); a node-timepoint with no data defaults to an inflow of 0
    tmp_fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "water_inflows.tab",
    )
    if os.path.exists(tmp_fname):
        data_portal.load(
            filename=tmp_fname,
            param=m.exogenous_water_inflow_rate_vol_per_sec,
        )

    bt_hrz_fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "water_inflows_bt_hrz.tab",
    )
    if os.path.exists(bt_hrz_fname):
        data_portal.load(
            filename=bt_hrz_fname,
            index=m.WATER_NODE_BT_HRZS_WITH_EXOGENOUS_INFLOWS,
            param=m.exogenous_water_inflow_rate_avg_vol_per_sec,
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
                WHERE water_inflow_tmp_scenario_id = 
                {subscenarios.WATER_INFLOW_TMP_SCENARIO_ID}
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

    c2 = conn.cursor()
    bt_hrz_water_inflows = c2.execute(f"""SELECT water_node, balancing_type, horizon,
                exogenous_water_inflow_rate_avg_vol_per_sec
                FROM inputs_system_water_inflows_bt_hrz
                WHERE water_inflow_bt_hrz_scenario_id =
                {subscenarios.WATER_INFLOW_BT_HRZ_SCENARIO_ID}
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
                AND (balancing_type, horizon)
                IN (SELECT DISTINCT balancing_type_horizon, horizon
                    FROM inputs_temporal_horizon_timepoints
                    WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                    AND subproblem_id = {subproblem}
                    )
                AND hydro_iteration = {hydro_iteration}
                ;
                """)

    return water_inflows, bt_hrz_water_inflows


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

    inflows, bt_hrz_inflows = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # Optional file with timepoint-level inflows; not written if the
    # scenario has no timepoint-level inflow data (e.g. inflows specified
    # by horizon only)
    inflow_rows = inflows.fetchall()
    if inflow_rows:
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

            for row in inflow_rows:
                writer.writerow(row)

    # Optional file with horizon-level average inflows; not written if the
    # scenario has no horizon-level inflow data
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_inflows_bt_hrz.tab",
        data=bt_hrz_inflows,
        replace_nulls=True,
    )
