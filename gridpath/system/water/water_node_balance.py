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
Defines the mass balance at each node. For nodes with no reservoirs,
total inflows equal total outflows. For nodes with reservoirs, total inflows
minus total inflows equals the change in reservoir volume between timepoints.
"""

from pyomo.environ import Constraint

from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
    update_results_df,
)
from gridpath.system.water import WATER_NODE_TMP_DF


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
    # ### Constraints ### #

    # Set the sum of outflows from the node to be equal to discharge & spill
    # for nodes with storage and to inflow for nodes without storage
    def enforce_mass_balance_outflow_rule(mod, wn, tmp):
        """
        The sum of the flows on all links from this node must equal the
        reservoir release for nodes with reservoirs and total inflows for
        reservoirs without reservoirs. Skip constraint for the last node in the
        network with no out links.

        For linear horizons, the lwater outflows may arrive outside of the
        horizon boundary if travel time is more than hours in the remaining
        timepoints. We still need to enforce outflow constraints (that are
        based on the departure timepoint). These flows have the
        "tmp_outside_horizon" index for the arrival timepoint.
        """
        if len(mod.WATER_LINKS_FROM_BY_WATER_NODE[wn]) > 0:
            # For nodes with reservoirs, set to reservoir release
            if wn in mod.WATER_NODES_W_RESERVOIRS:
                return (
                    mod.Gross_Water_Node_Outflow_Rate_Vol_per_Sec[wn, tmp]
                    == mod.Gross_Reservoir_Release_Rate_Vol_Per_Sec[wn, tmp]
                )
            else:
                # For nodes without reservoirs, set to inflow
                return (
                    mod.Gross_Water_Node_Outflow_Rate_Vol_per_Sec[wn, tmp]
                    == mod.Gross_Water_Node_Inflow_Rate_Vol_Per_Sec[wn, tmp]
                )
        else:
            return Constraint.Skip

    m.Water_Node_Outflow_Constraint = Constraint(
        m.WATER_NODES, m.TMPS, rule=enforce_mass_balance_outflow_rule
    )


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
    Add the node outflow constraint duals to the consolidated water
    node-timepoint results dataframe.
    """
    results_columns = [
        "water_node_outflow_constraint_dual",
        "water_node_outflow_constraint_marginal_cost_per_vol_per_sec",
    ]

    def outflow_constraint_dual(wn, tmp):
        # The constraint is skipped for nodes with no outgoing links, so
        # check membership first
        return (
            duals_wrapper(m, m.Water_Node_Outflow_Constraint[wn, tmp])
            if (wn, tmp) in m.Water_Node_Outflow_Constraint
            else None
        )

    data = [
        [
            wn,
            tmp,
            outflow_constraint_dual(wn, tmp),
            none_dual_type_error_wrapper(
                outflow_constraint_dual(wn, tmp),
                m.tmp_objective_coefficient[tmp],
            ),
        ]
        for wn in m.WATER_NODES
        for tmp in m.TMPS
    ]
    results_df = create_results_df(
        index_columns=["water_node", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, WATER_NODE_TMP_DF), results_df)


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
    instance.constraint_indices["Water_Node_Outflow_Constraint"] = [
        "water_node",
        "timepoint",
        "dual",
    ]
