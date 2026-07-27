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
Water nodes and connections for modeling cascading hydro systems.
"""

import csv
import os.path
from pyomo.environ import (
    Set,
    Param,
    Boolean,
    NonNegativeReals,
    NonNegativeIntegers,
    Var,
    Constraint,
    Expression,
    Any,
    value,
)

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
)
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_boundary_type,
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
    """

    # Volume-elevation relationship
    m.WATER_NODES_W_RESERVOIRS_SEGMENTS = Set(
        within=m.WATER_NODES_W_RESERVOIRS * NonNegativeIntegers
    )

    m.volume_to_elevation_slope = Param(
        m.WATER_NODES_W_RESERVOIRS_SEGMENTS, within=NonNegativeReals
    )

    m.volume_to_elevation_intercept = Param(
        m.WATER_NODES_W_RESERVOIRS_SEGMENTS, within=NonNegativeReals
    )

    # ### Variables ### #

    m.Reservoir_Endogenous_Starting_Elevation_ElevationUnit = Var(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, within=NonNegativeReals
    )

    def elevation_volume_curve_rule(mod, r, seg, tmp):
        """
        This constraint behaves much better when dividing by slope instead of
        multiplying
        TODO: probably remove piecewise linear option and have elevation be
        """
        return (
            mod.Reservoir_Endogenous_Starting_Elevation_ElevationUnit[r, tmp]
            - mod.volume_to_elevation_intercept[r, seg]
        ) / mod.volume_to_elevation_slope[
            r, seg
        ] == mod.Reservoir_Starting_Volume_WaterVolumeUnit[
            r, tmp
        ]

    m.Elevation_Volume_Relationship_Constraint = Constraint(
        m.WATER_NODES_W_RESERVOIRS_SEGMENTS,
        m.TMPS,
        rule=elevation_volume_curve_rule,
    )


def elevation_rule(mod, r, tmp):
    return mod.Reservoir_Endogenous_Starting_Elevation_ElevationUnit[r, tmp]


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
            "reservoir_volume_to_elevation_curves.tab",
        ),
        index=m.WATER_NODES_W_RESERVOIRS_SEGMENTS,
        param=(m.volume_to_elevation_slope, m.volume_to_elevation_intercept),
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
    volume_to_elevation_curves = c.execute(
        f"""SELECT water_node, segment, volume_to_elevation_slope, volume_to_elevation_intercept
        FROM inputs_system_water_node_reservoir_volume_to_elevation_curves
        WHERE (water_node, volume_to_elevation_curve_id)
        IN (SELECT water_node, volume_to_elevation_curve_id
            FROM inputs_system_water_node_reservoirs
            WHERE water_node_reservoir_scenario_id = 
            {subscenarios.WATER_NODE_RESERVOIR_SCENARIO_ID}
        );
        """
    )

    return volume_to_elevation_curves


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

    volume_to_elevation_curves = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # Volume to elevation curves
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "reservoir_volume_to_elevation_curves.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "reservoir",
                "segment",
                "volume_to_elevation_slope",
                "volume_to_elevation_intercept",
            ]
        )

        for row in volume_to_elevation_curves:
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
        "endogenous_starting_elevation",
        "elevation_volume_relationship_constraint_dual",
        "elevation_volume_relationship_constraint_marginal_cost_per_volumeunit",
    ]

    def elevation_volume_constraint_dual(r, seg, tmp):
        return (
            duals_wrapper(m, m.Elevation_Volume_Relationship_Constraint[r, seg, tmp])
            if (r, seg, tmp) in m.Elevation_Volume_Relationship_Constraint
            else None
        )

    data = [
        [
            r,
            seg,
            tmp,
            value(m.Reservoir_Endogenous_Starting_Elevation_ElevationUnit[r, tmp]),
            elevation_volume_constraint_dual(r, seg, tmp),
            none_dual_type_error_wrapper(
                elevation_volume_constraint_dual(r, seg, tmp),
                m.tmp_objective_coefficient[tmp],
            ),
        ]
        for (r, seg) in m.WATER_NODES_W_RESERVOIRS_SEGMENTS
        for tmp in m.TMPS
    ]
    results_df = create_results_df(
        index_columns=["water_node", "segment", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    results_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "system_water_node_elevation_segment_timepoint.csv",
        ),
        sep=",",
        index=True,
    )


def save_duals(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    instance,
    dynamic_components,
):
    instance.constraint_indices["Elevation_Volume_Relationship_Constraint"] = [
        "water_node",
        "segment",
        "timepoint",
        "dual",
    ]


# TODO: results import
