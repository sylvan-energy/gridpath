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
This module defines the reservoir operation for water nodes that have
reservoirs.
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

from gridpath.auxiliary.auxiliary import (
    get_required_subtype_modules,
    load_subtype_modules,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_boundary_type,
)
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
    | | :code:`WATER_NODES_W_RESERVOIRS`                                      |
    | | *Within*: :code:`WATER_NODES`                                         |
    |                                                                         |
    | A subset of water nodes that have reservoirs.                           |
    +-------------------------------------------------------------------------+
    | | :code:`WATER_NODE_RESERVOIR_TMPS_W_TARGET_STARTING_VOLUME`                     |
    | | *Within*: :code:`WATER_NODES * TMPS`                                  |
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

    # ### Sets ### #
    m.WATER_NODES_W_RESERVOIRS = Set(within=m.WATER_NODES)

    # Target volume node-timepoints
    m.WATER_NODE_RESERVOIR_TMPS_W_TARGET_STARTING_VOLUME = Set(
        within=m.WATER_NODES_W_RESERVOIRS * m.TMPS
    )

    m.WATER_NODE_RESERVOIR_TMPS_W_TARGET_ENDING_VOLUME = Set(
        within=m.WATER_NODES_W_RESERVOIRS * m.TMPS
    )

    # Target release node-bt_horizons
    m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_TOTAL_RELEASE_REQUIREMENTS = Set(
        dimen=3, within=m.WATER_NODES * m.BLN_TYPE_HRZS
    )

    # ### Parameters ###
    # Volume targets
    m.reservoir_target_starting_volume = Param(
        m.WATER_NODE_RESERVOIR_TMPS_W_TARGET_STARTING_VOLUME, within=NonNegativeReals
    )

    m.reservoir_target_ending_volume = Param(
        m.WATER_NODE_RESERVOIR_TMPS_W_TARGET_ENDING_VOLUME, within=NonNegativeReals
    )

    # Volume bounds
    m.maximum_volume_volumeunit = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals
    )

    m.allow_min_volume_violation = Param(
        m.WATER_NODES_W_RESERVOIRS, within=Boolean, default=0
    )

    m.min_volume_violation_cost = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals, default=0
    )

    m.minimum_volume_volumeunit = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals
    )

    m.allow_max_volume_violation = Param(
        m.WATER_NODES_W_RESERVOIRS, within=Boolean, default=0
    )

    m.max_volume_violation_cost = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals, default=0
    )

    # TODO: horizon volume bounds need tests
    m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_MAX_VOL_REQUIRMENTS = Set(
        dimen=3, within=m.WATER_NODES_W_RESERVOIRS * m.BLN_TYPE_HRZS
    )

    m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_MIN_VOL_REQUIRMENTS = Set(
        dimen=3, within=m.WATER_NODES_W_RESERVOIRS * m.BLN_TYPE_HRZS
    )

    m.hrz_maximum_volume_volumeunit = Param(
        m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_MAX_VOL_REQUIRMENTS, within=NonNegativeReals
    )

    m.hrz_minimum_volume_volumeunit = Param(
        m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_MIN_VOL_REQUIRMENTS, within=NonNegativeReals
    )

    # Build the timepoint-level bounds in one pass over the horizon
    # requirements (rather than rescanning them for every reservoir-timepoint)
    # and store values only where a horizon requirement tightens the static
    # bound; everywhere else the default returns the static bound. If
    # multiple bt-hrzs include a timepoint, the most binding value applies.
    def max_volume_by_tmp_init(mod):
        max_vol_by_tmp = {}
        for r, bt, hrz in mod.WATER_NODE_RESERVOIR_BT_HRZS_WITH_MAX_VOL_REQUIRMENTS:
            hrz_max = mod.hrz_maximum_volume_volumeunit[r, bt, hrz]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (r, tmp) in max_vol_by_tmp:
                    max_vol_by_tmp[r, tmp] = min(max_vol_by_tmp[r, tmp], hrz_max)
                else:
                    max_vol_by_tmp[r, tmp] = min(
                        mod.maximum_volume_volumeunit[r], hrz_max
                    )

        return max_vol_by_tmp

    m.maximum_volume_volumeunit_by_tmp = Param(
        m.WATER_NODES_W_RESERVOIRS,
        m.TMPS,
        initialize=max_volume_by_tmp_init,
        default=lambda mod, r, tmp: mod.maximum_volume_volumeunit[r],
    )

    def min_volume_by_tmp_init(mod):
        min_vol_by_tmp = {}
        for r, bt, hrz in mod.WATER_NODE_RESERVOIR_BT_HRZS_WITH_MIN_VOL_REQUIRMENTS:
            hrz_min = mod.hrz_minimum_volume_volumeunit[r, bt, hrz]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (r, tmp) in min_vol_by_tmp:
                    min_vol_by_tmp[r, tmp] = max(min_vol_by_tmp[r, tmp], hrz_min)
                else:
                    min_vol_by_tmp[r, tmp] = max(
                        mod.minimum_volume_volumeunit[r], hrz_min
                    )

        return min_vol_by_tmp

    m.minimum_volume_volumeunit_by_tmp = Param(
        m.WATER_NODES_W_RESERVOIRS,
        m.TMPS,
        initialize=min_volume_by_tmp_init,
        default=lambda mod, r, tmp: mod.minimum_volume_volumeunit[r],
    )

    # Release targets
    m.reservoir_target_release_avg_flow_volunit_per_sec = Param(
        m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_TOTAL_RELEASE_REQUIREMENTS,
        within=NonNegativeReals,
    )

    m.allow_target_release_violation = Param(
        m.WATER_NODES_W_RESERVOIRS, within=Boolean, default=0
    )

    m.target_release_violation_cost = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals, default=0
    )

    # Powerhouse release and spill bounds
    m.max_powerhouse_release_vol_unit_per_sec = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals
    )
    m.max_spill_vol_unit_per_sec = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals
    )
    m.max_total_outflow_vol_unit_per_sec = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals
    )

    # Losses
    # TODO: by month
    m.evaporation_coefficient = Param(
        m.WATER_NODES_W_RESERVOIRS, within=NonNegativeReals
    )

    # ### Variables ### #
    m.Reservoir_Starting_Volume_WaterVolumeUnit = Var(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, within=NonNegativeReals
    )

    m.Discharge_Water_to_Powerhouse_Rate_Vol_Per_Sec = Var(
        m.WATER_NODES_W_RESERVOIRS,
        m.TMPS,
        within=NonNegativeReals,
    )

    m.Spill_Water_Rate_Vol_Per_Sec = Var(
        m.WATER_NODES_W_RESERVOIRS,
        m.TMPS,
        within=NonNegativeReals,
    )

    # Slack variables
    m.Target_Release_Violation_VolUnit = Var(
        m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_TOTAL_RELEASE_REQUIREMENTS,
        within=NonNegativeReals,
        initialize=0,
    )

    m.Min_Reservoir_Storage_Violation = Var(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, within=NonNegativeReals, initialize=0
    )

    m.Max_Reservoir_Storage_Violation = Var(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, within=NonNegativeReals, initialize=0
    )

    # Expressions
    # TODO: add evaporative losses
    def gross_reservoir_release(mod, wn_w_r, tmp):
        return (
            mod.Discharge_Water_to_Powerhouse_Rate_Vol_Per_Sec[wn_w_r, tmp]
            + mod.Spill_Water_Rate_Vol_Per_Sec[wn_w_r, tmp]
        )

    m.Gross_Reservoir_Release_Rate_Vol_Per_Sec = Expression(
        m.WATER_NODES_W_RESERVOIRS,
        m.TMPS,
        initialize=gross_reservoir_release,
    )

    def get_total_reservoir_release_volunit(mod, wn, tmp):
        outflow_in_tmp = (
            mod.Gross_Reservoir_Release_Rate_Vol_Per_Sec[wn, tmp]
            * 3600
            * mod.hrs_in_tmp[tmp]
        )

        return outflow_in_tmp

    def ending_volume_init(mod, wn, tmp):
        inflow = get_total_inflow_for_reservoir_tracking_volunit(mod, wn, tmp)
        outflow = get_total_reservoir_release_volunit(mod, wn, tmp)

        return mod.Reservoir_Starting_Volume_WaterVolumeUnit[wn, tmp] + inflow - outflow

    m.Reservoir_Ending_Volume_WaterVolumeUnit = Expression(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, initialize=ending_volume_init
    )

    # ### Constraints ### #

    def max_powerhouse_discharge_constraint_rule(mod, wn_w_r, tmp):
        return (
            mod.Discharge_Water_to_Powerhouse_Rate_Vol_Per_Sec[wn_w_r, tmp]
            <= mod.max_powerhouse_release_vol_unit_per_sec[wn_w_r]
        )

    m.Max_Discharge_Water_to_Powerhouse_Constraint = Constraint(
        m.WATER_NODES_W_RESERVOIRS,
        m.TMPS,
        rule=max_powerhouse_discharge_constraint_rule,
    )

    def max_spill_constraint_rule(mod, wn_w_r, tmp):
        return (
            mod.Spill_Water_Rate_Vol_Per_Sec[wn_w_r, tmp]
            <= mod.max_spill_vol_unit_per_sec[wn_w_r]
        )

    m.Max_Spill_Constraint = Constraint(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, rule=max_spill_constraint_rule
    )

    def max_gross_outflow_constraint_rule(mod, wn_w_r, tmp):
        return (
            mod.Gross_Reservoir_Release_Rate_Vol_Per_Sec[wn_w_r, tmp]
            <= mod.max_total_outflow_vol_unit_per_sec[wn_w_r]
        )

    m.Max_Gross_Outflow_Constraint = Constraint(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, rule=max_gross_outflow_constraint_rule
    )

    def reservoir_target_starting_volume_constraint_rule(mod, wn_w_r, tmp):
        """ """
        return (
            mod.Reservoir_Starting_Volume_WaterVolumeUnit[wn_w_r, tmp]
            == mod.reservoir_target_starting_volume[wn_w_r, tmp]
        )

    m.Reservoir_Target_Starting_Volume_Constraint = Constraint(
        m.WATER_NODE_RESERVOIR_TMPS_W_TARGET_STARTING_VOLUME,
        rule=reservoir_target_starting_volume_constraint_rule,
    )

    def reservoir_target_ending_volume_constraint_rule(mod, wn_w_r, tmp):
        """ """
        return (
            mod.Reservoir_Ending_Volume_WaterVolumeUnit[wn_w_r, tmp]
            == mod.reservoir_target_ending_volume[wn_w_r, tmp]
        )

    m.Reservoir_Target_Ending_Volume_Constraint = Constraint(
        m.WATER_NODE_RESERVOIR_TMPS_W_TARGET_ENDING_VOLUME,
        rule=reservoir_target_ending_volume_constraint_rule,
    )

    def reservoir_storage_min_bound_constraint_rule(mod, r, tmp):
        if mod.allow_min_volume_violation[r]:
            violation = mod.Min_Reservoir_Storage_Violation[r, tmp]
        else:
            violation = 0
        return (
            mod.Reservoir_Starting_Volume_WaterVolumeUnit[r, tmp] + violation
            >= mod.minimum_volume_volumeunit_by_tmp[r, tmp]
        )

    m.Minimum_Water_Storage_Constraint = Constraint(
        m.WATER_NODES_W_RESERVOIRS,
        m.TMPS,
        rule=reservoir_storage_min_bound_constraint_rule,
    )

    def reservoir_storage_max_bound_constraint_rule(mod, r, tmp):
        if mod.allow_max_volume_violation[r]:
            violation = mod.Max_Reservoir_Storage_Violation[r, tmp]
        else:
            violation = 0
        return (
            mod.Reservoir_Starting_Volume_WaterVolumeUnit[r, tmp]
            <= mod.maximum_volume_volumeunit_by_tmp[r, tmp] + violation
        )

    m.Maximum_Water_Storage_Constraint = Constraint(
        m.WATER_NODES_W_RESERVOIRS,
        m.TMPS,
        rule=reservoir_storage_max_bound_constraint_rule,
    )

    # Target releases
    def reservoir_target_release_constraint_rule(mod, wn, bt, hrz):
        """ """
        if mod.allow_target_release_violation[wn]:
            violation = mod.Target_Release_Violation_VolUnit[wn, bt, hrz]
        else:
            violation = 0
        return (
            sum(
                mod.Gross_Reservoir_Release_Rate_Vol_Per_Sec[wn, tmp]
                * 3600
                * mod.hrs_in_tmp[tmp]
                for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            == sum(
                mod.reservoir_target_release_avg_flow_volunit_per_sec[wn, bt, hrz]
                * 3600
                * mod.hrs_in_tmp[tmp]
                for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            - violation
        )

    m.Water_Node_Target_Release_Constraint = Constraint(
        m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_TOTAL_RELEASE_REQUIREMENTS,
        rule=reservoir_target_release_constraint_rule,
    )

    # ### Elevation ### #
    m.elevation_type = Param(
        m.WATER_NODES_W_RESERVOIRS, within=["constant", "exogenous", "endogenous"]
    )

    # Import needed elevation modules
    required_elevation_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="elevation_type",
        filename="water_node_reservoirs",
    )

    imported_elevation_modules = load_subtype_modules(
        required_subtype_modules=required_elevation_modules,
        package="gridpath.system.water.elevation_types",
        required_attributes=[],
    )

    # Add any components specific to the operational modules
    for op_m in required_elevation_modules:
        imp_op_m = imported_elevation_modules[op_m]
        if hasattr(imp_op_m, "add_model_components"):
            imp_op_m.add_model_components(
                m,
                d,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            )

    def elevation_rule(mod, r, tmp):
        elevation_type = mod.elevation_type[r]
        return imported_elevation_modules[elevation_type].elevation_rule(mod, r, tmp)

    m.Reservoir_Starting_Elevation_ElevationUnit = Expression(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, rule=elevation_rule
    )

    def get_total_inflow_for_reservoir_tracking_volunit(mod, wn, tmp):
        """
        Total inflow is exogenous inflow at node plus sum of endogenous
        inflows from all links to node
        """
        inflow_in_tmp = (
            mod.Gross_Water_Node_Inflow_Rate_Vol_Per_Sec[wn, tmp]
            * 3600
            * mod.hrs_in_tmp[tmp]
        )

        return inflow_in_tmp

    def reservoir_storage_tracking_rule(mod, wn, tmp):
        """ """
        balancing_type = mod.water_system_balancing_type
        if check_if_first_timepoint(mod=mod, tmp=tmp, balancing_type=balancing_type):
            # No constraint in the first timepoint of a linear horizon (no
            # previous timepoints for tracking reservoir levels)
            if check_boundary_type(
                mod=mod,
                tmp=tmp,
                balancing_type=balancing_type,
                boundary_type="linear",
            ):
                return Constraint.Skip
            # TODO: add linked horizons
            elif check_boundary_type(
                mod=mod,
                tmp=tmp,
                balancing_type=balancing_type,
                boundary_type="linked",
            ):
                raise (
                    UserWarning(
                        "Linked horizons have not been implemented for "
                        "water system feature."
                    )
                )

        prev_tmp = mod.prev_tmp[tmp, balancing_type]
        current_tmp_starting_water_volume = (
            mod.Reservoir_Starting_Volume_WaterVolumeUnit[wn, tmp]
        )
        prev_tmp_starting_water_volume = mod.Reservoir_Starting_Volume_WaterVolumeUnit[
            wn, prev_tmp
        ]

        # Inflows and releases; these are already calculated
        # based on per sec flows and hours in the timepoint
        prev_tmp_inflow = get_total_inflow_for_reservoir_tracking_volunit(
            mod, wn, prev_tmp
        )

        prev_tmp_outflow = get_total_reservoir_release_volunit(mod, wn, prev_tmp)

        return current_tmp_starting_water_volume == (
            prev_tmp_starting_water_volume + prev_tmp_inflow - prev_tmp_outflow
        )

    m.Reservoir_Storage_Tracking_Constraint = Constraint(
        m.WATER_NODES_W_RESERVOIRS, m.TMPS, rule=reservoir_storage_tracking_rule
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
            "water_node_reservoirs.tab",
        ),
        index=m.WATER_NODES_W_RESERVOIRS,
        param=(
            m.max_powerhouse_release_vol_unit_per_sec,
            m.max_spill_vol_unit_per_sec,
            m.max_total_outflow_vol_unit_per_sec,
            m.allow_target_release_violation,
            m.target_release_violation_cost,
            m.minimum_volume_volumeunit,
            m.maximum_volume_volumeunit,
            m.allow_min_volume_violation,
            m.min_volume_violation_cost,
            m.allow_max_volume_violation,
            m.max_volume_violation_cost,
            m.evaporation_coefficient,
            m.elevation_type,
        ),
    )

    hrz_max_vol_fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "reservoir_max_volume_by_horizon.tab",
    )

    if os.path.exists(hrz_max_vol_fname):
        data_portal.load(
            filename=hrz_max_vol_fname,
            index=m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_MAX_VOL_REQUIRMENTS,
            param=m.hrz_maximum_volume_volumeunit,
        )

    hrz_min_vol_fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "reservoir_min_volume_by_horizon.tab",
    )

    if os.path.exists(hrz_min_vol_fname):
        data_portal.load(
            filename=hrz_min_vol_fname,
            index=m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_MIN_VOL_REQUIRMENTS,
            param=m.hrz_minimum_volume_volumeunit,
        )

    starting_volume_fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "reservoir_target_starting_volumes.tab",
    )
    if os.path.exists(starting_volume_fname):
        data_portal.load(
            filename=starting_volume_fname,
            index=m.WATER_NODE_RESERVOIR_TMPS_W_TARGET_STARTING_VOLUME,
            param=m.reservoir_target_starting_volume,
        )

    ending_volume_fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "reservoir_target_ending_volumes.tab",
    )
    if os.path.exists(ending_volume_fname):
        data_portal.load(
            filename=ending_volume_fname,
            index=m.WATER_NODE_RESERVOIR_TMPS_W_TARGET_ENDING_VOLUME,
            param=m.reservoir_target_ending_volume,
        )

    rel_fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "reservoir_target_releases.tab",
    )

    if os.path.exists(rel_fname):
        data_portal.load(
            filename=rel_fname,
            index=m.WATER_NODE_RESERVOIR_BT_HRZS_WITH_TOTAL_RELEASE_REQUIREMENTS,
            param=m.reservoir_target_release_avg_flow_volunit_per_sec,
        )

    # TODO: refactor
    # Import needed elevation modules
    required_elevation_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="elevation_type",
        filename="water_node_reservoirs",
    )

    imported_elevation_modules = load_subtype_modules(
        required_subtype_modules=required_elevation_modules,
        package="gridpath.system.water.elevation_types",
        required_attributes=[],
    )

    # Add any components specific to the operational modules
    for op_m in required_elevation_modules:
        imp_op_m = imported_elevation_modules[op_m]
        if hasattr(imp_op_m, "load_model_data"):
            imp_op_m.load_model_data(
                m,
                d,
                data_portal,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
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
    reservoirs = c.execute(f"""SELECT water_node,
            max_powerhouse_release_vol_unit_per_sec,
            max_spill_vol_unit_per_sec,
            max_total_outflow_vol_unit_per_sec,
            allow_target_release_violation,
            target_release_violation_cost,
            minimum_volume_volumeunit,
            maximum_volume_volumeunit,
            allow_min_volume_violation,
            min_volume_violation_cost,
            allow_max_volume_violation,
            max_volume_violation_cost,
            evaporation_coefficient,
            elevation_type
        FROM inputs_system_water_node_reservoirs
        WHERE water_node_reservoir_scenario_id = 
        {subscenarios.WATER_NODE_RESERVOIR_SCENARIO_ID}
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
        ;
        """)

    c4 = conn.cursor()
    hrz_max_volumes = c4.execute(
        f"""SELECT water_node, balancing_type, horizon, maximum_volume_volumeunit
            FROM inputs_system_water_node_reservoirs_volume_horizon_bounds
            WHERE (water_node, volume_hrz_bounds_scenario_id)
            IN (SELECT water_node, volume_hrz_bounds_scenario_id
                FROM inputs_system_water_node_reservoirs
                WHERE water_node_reservoir_scenario_id = 
                {subscenarios.WATER_NODE_RESERVOIR_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
            )
            AND maximum_volume_volumeunit IS NOT NULL
            ;
            """
    )

    c5 = conn.cursor()
    hrz_min_volumes = c5.execute(
        f"""SELECT water_node, balancing_type, horizon, minimum_volume_volumeunit
            FROM inputs_system_water_node_reservoirs_volume_horizon_bounds
            WHERE (water_node, volume_hrz_bounds_scenario_id)
            IN (SELECT water_node, volume_hrz_bounds_scenario_id
                FROM inputs_system_water_node_reservoirs
                WHERE water_node_reservoir_scenario_id = 
                {subscenarios.WATER_NODE_RESERVOIR_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
            )
            AND minimum_volume_volumeunit IS NOT NULL
            ;
            """
    )

    c1 = conn.cursor()
    target_starting_volumes = c1.execute(
        f"""SELECT water_node, timepoint, reservoir_target_starting_volume
        FROM inputs_system_water_node_reservoirs_target_volumes
        WHERE (water_node, target_volume_scenario_id)
        IN (SELECT water_node, target_volume_scenario_id
            FROM inputs_system_water_node_reservoirs
            WHERE water_node_reservoir_scenario_id = 
            {subscenarios.WATER_NODE_RESERVOIR_SCENARIO_ID}
        )
        AND timepoint
        IN (SELECT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage})
        AND hydro_iteration = {hydro_iteration}
        AND reservoir_target_starting_volume IS NOT NULL
        ;
        """
    )

    c2 = conn.cursor()
    target_ending_volumes = c2.execute(
        f"""SELECT water_node, timepoint, reservoir_target_ending_volume
        FROM inputs_system_water_node_reservoirs_target_volumes
        WHERE (water_node, target_volume_scenario_id)
        IN (SELECT water_node, target_volume_scenario_id
            FROM inputs_system_water_node_reservoirs
            WHERE water_node_reservoir_scenario_id = 
            {subscenarios.WATER_NODE_RESERVOIR_SCENARIO_ID}
        )
        AND timepoint
        IN (SELECT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage})
        AND hydro_iteration = {hydro_iteration}
        AND reservoir_target_ending_volume IS NOT NULL
        ;
        """
    )

    c3 = conn.cursor()
    target_releases = c3.execute(
        f"""SELECT water_node, balancing_type, horizon, reservoir_target_release_avg_flow_volunit_per_sec
            FROM inputs_system_water_node_reservoirs_target_releases
            WHERE (water_node, target_release_scenario_id)
            IN (SELECT water_node, target_release_scenario_id
                FROM inputs_system_water_node_reservoirs
                WHERE water_node_reservoir_scenario_id = 
                {subscenarios.WATER_NODE_RESERVOIR_SCENARIO_ID}
            )
            AND (balancing_type, horizon)
            IN (SELECT DISTINCT balancing_type_horizon, horizon
                FROM inputs_temporal_horizon_timepoints
                WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                AND subproblem_id = {subproblem}
                AND stage_id = {stage}
            )
            AND hydro_iteration = {hydro_iteration}
            ;
            """
    )

    return (
        reservoirs,
        hrz_max_volumes,
        hrz_min_volumes,
        target_starting_volumes,
        target_ending_volumes,
        target_releases,
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

    (
        reservoirs,
        hrz_max_volumes,
        hrz_min_volumes,
        target_starting_volumes,
        target_ending_volumes,
        target_releases,
    ) = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="water_node_reservoirs.tab",
        data=reservoirs,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="reservoir_max_volume_by_horizon.tab",
        data=hrz_max_volumes,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="reservoir_min_volume_by_horizon.tab",
        data=hrz_min_volumes,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="reservoir_target_starting_volumes.tab",
        data=target_starting_volumes,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="reservoir_target_ending_volumes.tab",
        data=target_ending_volumes,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="reservoir_target_releases.tab",
        data=target_releases,
    )

    # TODO: refactor
    # Import needed elevation modules
    required_elevation_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="elevation_type",
        filename="water_node_reservoirs",
    )

    imported_elevation_modules = load_subtype_modules(
        required_subtype_modules=required_elevation_modules,
        package="gridpath.system.water.elevation_types",
        required_attributes=[],
    )

    # Add any components specific to the operational modules
    for op_m in required_elevation_modules:
        imp_op_m = imported_elevation_modules[op_m]
        if hasattr(imp_op_m, "write_model_inputs"):
            imp_op_m.write_model_inputs(
                scenario_directory,
                scenario_id,
                subscenarios,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                conn,
            )


# TODO: results import
