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
This module adds the main load-balance consumption component, the static
load requirement to the load-balance constraint.
"""

import csv
import os.path
from pyomo.environ import Set, Param, Any, NonNegativeReals, Expression, value

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import load_balance_consumption_components
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)
from gridpath.system.load_balance import LOAD_ZONE_TMP_DF


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    This method adds the static load to the load balance dynamic components.
    """
    getattr(dynamic_components, load_balance_consumption_components).append(
        "LZ_Bulk_Static_Load_in_Tmp"
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
    :param m: the Pyomo abstract model object we are adding the components to
    :param d: the DynamicComponents class object we are adding components to

    Here, we add profiles for the various load components that must be defined
    for each load zone *z* and timepoint *tmp*. These profiles are summed
    into the *LZ_Bulk_Static_Load_in_Tmp* expression, which in turn is added to the
    dynamic load-balance consumption components that will go into the load
    balance constraint in the *load_balance* module (i.e. the constraint's RHS).

    The following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`LOAD_ZONE_LOAD_CMPNTS_ALL`                                     |
    |                                                                         |
    | Two-dimensional set of all load_zone-load_components.                   |
    +-------------------------------------------------------------------------+
    | | :code:`LOAD_ZONE_TMP_LOAD_CMPNTS_ALL`                                 |
    |                                                                         |
    | Three-dimensional set of all load_zone-timepoint-load_components.       |
    +-------------------------------------------------------------------------+
    | | :code:`LOAD_ZONE_TMP_LOAD_CMPNTS_W_DEFINED_LOAD`                      |
    |                                                                         |
    | Three-dimensional set of load_zone-timepoint-load_component             |
    | for which load will be defined.                                         |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`component_static_load_mw_w_tmp_value`                          |
    | | *Defined over*: :code:`LOAD_ZONE_TMP_LOAD_CMPNTS_W_DEFINED_LOAD`      |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Load level for load_zone, timepoint, and load_component.                |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`load_level_default`                                            |
    | | *Defined over*: :code:`LOAD_ZONE_LOAD_CMPNTS`                         |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`"undefined"`                                        |
    |                                                                         |
    | Default value for load level if it is not defined for via the timepoint |
    | inputs; if not defined, this parameter itself defaults to infinity. If  |
    | it ends up defaulting to infinity, a ValueError is raised.              |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Derived Params                                                          |
    +=========================================================================+
    | | :code:`component_static_load_mw`                                      |
    | | *Defined over*: :code:`LOAD_ZONE_TMP_LOAD_CMPNTS_ALL`                 |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Will either be set to component_static_load_mw_w_tmp_value or to        |
    | load_level_default. One or the other is required; if both are specified |
    | a ValueError will be thrown.                                            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`LZ_Bulk_Static_Load_in_Tmp`                                    |
    | | *Defined over*: :code:`LOAD_ZONES, TMPS`                              |
    |                                                                         |
    | The total load (sum of all load components) for this load zone and      |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+


    """

    # Static load
    # All load zones and load componenst
    m.LOAD_ZONE_LOAD_CMPNTS_ALL = Set(dimen=2, within=m.LOAD_ZONES * Any)
    # Defaults for each load_zone-load_component
    m.load_level_default = Param(
        m.LOAD_ZONE_LOAD_CMPNTS_ALL,
        within=NonNegativeReals | {"undefined"},
        initialize="undefined",
    )
    # Distribution loss factor
    m.load_component_distribution_loss_adjustment_factor = Param(
        m.LOAD_ZONE_LOAD_CMPNTS_ALL, within=NonNegativeReals, default=0
    )

    # All load_zone-tmp-load_component combinations
    m.LOAD_ZONE_TMP_LOAD_CMPNTS_ALL = Set(
        dimen=3,
        within=m.LOAD_ZONES * m.TMPS * Any,
        initialize=lambda mod: [
            (lz, tmp, cmp)
            for (lz, cmp) in mod.LOAD_ZONE_LOAD_CMPNTS_ALL
            for tmp in mod.TMPS
        ],
    )

    # LZ-tmp-load_components with defined load
    m.LOAD_ZONE_TMP_LOAD_CMPNTS_W_DEFINED_LOAD = Set(
        dimen=3, within=m.LOAD_ZONES * m.TMPS * Any
    )
    m.component_static_load_mw_w_tmp_value = Param(
        m.LOAD_ZONE_TMP_LOAD_CMPNTS_W_DEFINED_LOAD,
        within=NonNegativeReals,
    )

    def set_default_and_warn_about_undefined_loads(mod, lz, tmp, cmp):
        if (lz, tmp, cmp) in mod.LOAD_ZONE_TMP_LOAD_CMPNTS_W_DEFINED_LOAD:
            if mod.load_level_default[lz, cmp] != "undefined":
                raise ValueError(f"""
                    You have both a default value and a by-timepoint value 
                    defined for load in load_zone {lz}, component {cmp}. 
                    Please check your inputs and select either one or the other.
                """)
            else:
                return mod.component_static_load_mw_w_tmp_value[lz, tmp, cmp]
        else:
            check_for_value_and_raise_value_error(
                param=mod.load_level_default[lz, cmp],
                value_to_check="undefined",
                msg=f"""
                Parameter component_static_load_mw at index 
                {lz, tmp, cmp} has no value defined. It 
                must either be included with the load inputs or a value must 
                be set via the load_level_default parameter of load_zone 
                {lz}.
                """,
            )

            return mod.load_level_default[lz, cmp]

    m.component_static_load_mw = Param(
        m.LOAD_ZONE_TMP_LOAD_CMPNTS_ALL,
        within=NonNegativeReals,
        default=lambda mod, lz, tmp, cmp: set_default_and_warn_about_undefined_loads(
            mod, lz, tmp, cmp
        ),
    )

    def total_static_load_from_components_init(mod):
        lz_load_in_tmp = {}
        for (
            load_zone,
            timepoint,
            component,
        ) in mod.LOAD_ZONE_TMP_LOAD_CMPNTS_ALL:
            if (
                mod.component_static_load_mw[load_zone, timepoint, component]
                == "undefined"
            ):
                raise ValueError(f"""
                Parameter component_static_load_mw at index 
                {load_zone, timepoint, component} has no value defined. Load 
                must either be included with the timepoint load inputs or a 
                value must be set via the load_level_default parameter of 
                load_zone {load_zone}.
                """)
            else:
                distribution_loss_adjusted_load = mod.component_static_load_mw[
                    load_zone, timepoint, component
                ] * (
                    1
                    + mod.load_component_distribution_loss_adjustment_factor[
                        load_zone, component
                    ]
                )
                if (load_zone, timepoint) not in lz_load_in_tmp.keys():
                    lz_load_in_tmp[(load_zone, timepoint)] = (
                        distribution_loss_adjusted_load
                    )
                else:
                    lz_load_in_tmp[
                        (load_zone, timepoint)
                    ] += distribution_loss_adjusted_load

        # print(lz_load_in_tmp)
        return lz_load_in_tmp

    m.LZ_Bulk_Static_Load_in_Tmp = Expression(
        m.LOAD_ZONES, m.TMPS, initialize=total_static_load_from_components_init
    )

    record_dynamic_components(dynamic_components=d)


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
            "load_mw.tab",
        ),
        index=m.LOAD_ZONE_TMP_LOAD_CMPNTS_W_DEFINED_LOAD,
        param=m.component_static_load_mw_w_tmp_value,
    )

    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "load_component_params.tab",
        ),
        index=m.LOAD_ZONE_LOAD_CMPNTS_ALL,
        param=(
            m.load_level_default,
            m.load_component_distribution_loss_adjustment_factor,
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

    Check the load_scenario_id for the scenario. Based on that, find
    the load_components_scenario_id and will select the relevant load
    components for this scenario. Finally, it will find the profiles for each
    one of those load components based on the load_levels_scenario_id for the
    scenario’s load_scenario_id.
    """

    c = conn.cursor()
    # Select only profiles for timepoints form the correct temporal
    # scenario and the correct subproblem
    # Select only profiles of load_zones that are part of the correct
    # load_zone_scenario
    # Select only profiles for the correct load_scenario
    sql = f"""SELECT load_zone, timepoint, load_component, load_mw
        FROM inputs_system_load_levels
        INNER JOIN
        -- Get only relevant timepionts
        (SELECT timepoint
        FROM inputs_temporal
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND subproblem_id ={subproblem}
        AND stage_id = {stage}) as relevant_timepoints
        USING (timepoint)
        INNER JOIN
        -- Get only relevant load zones
        (SELECT load_zone
        FROM inputs_geography_load_zones
        WHERE load_zone_scenario_id = {subscenarios.LOAD_ZONE_SCENARIO_ID}) as relevant_load_zones
        USING (load_zone)
        -- Get the relevant subscenario
        WHERE load_levels_scenario_id = (
            SELECT load_levels_scenario_id
            FROM inputs_system_load
            WHERE load_scenario_id = {subscenarios.LOAD_SCENARIO_ID}
            )
        AND (load_zone, load_component) in (
            SELECT load_zone, load_component
            FROM inputs_system_load_components
            WHERE load_components_scenario_id = (
                SELECT load_components_scenario_id
                FROM inputs_system_load
                WHERE load_scenario_id = {subscenarios.LOAD_SCENARIO_ID}
                )
            )
        -- Get the relevant weather iteration and stage
        AND weather_iteration = {weather_iteration}
        AND stage_id = {stage}
        """

    loads = c.execute(sql)

    c2 = conn.cursor()
    ld_comp_defaults = c2.execute(
        f"""SELECT load_zone, load_component, load_level_default, 
        load_component_distribution_loss_adjustment_factor
            FROM inputs_system_load_components
            INNER JOIN
            -- Get only relevant load zones
            (SELECT load_zone
            FROM inputs_geography_load_zones
            WHERE load_zone_scenario_id = {subscenarios.LOAD_ZONE_SCENARIO_ID}) as relevant_load_zones
            USING (load_zone)
            WHERE load_components_scenario_id = (
                SELECT load_components_scenario_id
                FROM inputs_system_load
                WHERE load_scenario_id = {subscenarios.LOAD_SCENARIO_ID}
                )
        """
    )

    return loads, ld_comp_defaults


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
    # loads = get_inputs_from_database(
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
    load_mw.tab file.
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

    loads, load_component_params = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # Load timeseries
    load_file = "load_mw.tab"
    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname=load_file,
        data=loads,
    )

    # Load component params
    load_component_params_file = "load_component_params.tab"
    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname=load_component_params_file,
        data=load_component_params,
        replace_nulls=True,
    )


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
    :param stage:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    results_columns = [
        "static_load_mw",
    ]
    data = [
        [
            lz,
            tmp,
            value(m.LZ_Bulk_Static_Load_in_Tmp[lz, tmp]),
        ]
        for lz in getattr(m, "LOAD_ZONES")
        for tmp in getattr(m, "TMPS")
    ]
    results_df = create_results_df(
        index_columns=["load_zone", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, LOAD_ZONE_TMP_DF), results_df)


def check_for_value_and_raise_value_error(param, value_to_check, msg):
    if param == value_to_check:
        raise ValueError(msg)
