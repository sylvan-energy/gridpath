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
Powerhouses
"""

import csv
import os.path

import pandas as pd
from pyomo.environ import (
    Set,
    Param,
    Boolean,
    NonNegativeReals,
    Var,
    Constraint,
    Expression,
    Any,
    value,
)

from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.common_functions import create_results_df
from gridpath.project.operations.operational_types.common_functions import (
    get_optype_inputs_as_df,
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

    # ### Sets ### #
    m.POWERHOUSES = Set(within=Any)
    m.POWERHOUSE_GENERATORS = Set(dimen=2)

    def generators_by_powerhouse_set_init(mod):
        generators_by_powerhouse = {pwrh: [] for pwrh in mod.POWERHOUSES}
        for p, g in mod.POWERHOUSE_GENERATORS:
            generators_by_powerhouse[p].append(g)

        return generators_by_powerhouse

    m.GENERATORS_BY_POWERHOUSE = Set(
        m.POWERHOUSES,
        initialize=generators_by_powerhouse_set_init,
    )

    # ### Params ### #
    m.powerhouse_water_node = Param(m.POWERHOUSES, within=m.WATER_NODES)

    # Tailwater assumed constant for now, but actually depends on flow
    m.tailwater_elevation = Param(m.POWERHOUSES, within=NonNegativeReals)

    # Headloss factor assumed constant, but actually depends on flow
    m.headloss_factor = Param(m.POWERHOUSES, within=NonNegativeReals)

    # Turbine efficiency assumed constant, but actually depends on flow
    m.turbine_efficiency = Param(m.POWERHOUSES, within=NonNegativeReals)

    # ### Expressions ### #
    def gross_head_expression_init(mod, p, tmp):
        return (
            mod.Reservoir_Starting_Elevation_ElevationUnit[
                mod.powerhouse_water_node[p], tmp
            ]
            - mod.tailwater_elevation[p]
        )

    m.Gross_Head = Expression(
        m.POWERHOUSES,
        m.TMPS,
        rule=gross_head_expression_init,
    )

    def net_head_expression_init(mod, p, tmp):
        return mod.Gross_Head[p, tmp] * (1 - mod.headloss_factor[p])

    m.Net_Head = Expression(
        m.POWERHOUSES,
        m.TMPS,
        rule=net_head_expression_init,
    )

    # ### Variables ### #

    # Allocate water to generators within the powerhouse
    m.Generator_Allocated_Water_Flow = Var(
        m.POWERHOUSE_GENERATORS, m.TMPS, within=NonNegativeReals
    )

    def generator_water_allocation_constraint_rule(mod, pwrh, tmp):
        return (
            sum(
                mod.Generator_Allocated_Water_Flow[pwrh, g, tmp]
                for g in mod.GENERATORS_BY_POWERHOUSE[pwrh]
            )
            == mod.Discharge_Water_to_Powerhouse_Rate_Vol_Per_Sec[
                mod.powerhouse_water_node[pwrh], tmp
            ]
        )

    # ### Constraints ### #
    m.Generator_Water_Allocation_Constraint = Constraint(
        m.POWERHOUSES, m.TMPS, rule=generator_water_allocation_constraint_rule
    )

    def water_to_power_coeff_gen_init(mod, pwrh, g, tmp):
        """
        Start with simple linear relationship; this actually will depend on
        volume
        """
        return (
            mod.theoretical_power_coefficient
            * mod.Generator_Allocated_Water_Flow[pwrh, g, tmp]
            * mod.Net_Head[pwrh, tmp]
            * mod.turbine_efficiency[pwrh]
        )

    m.Powerhouse_Output_by_Generator = Expression(
        m.POWERHOUSE_GENERATORS, m.TMPS, initialize=water_to_power_coeff_gen_init
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
    fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "powerhouses.tab",
    )

    data_portal.load(
        filename=fname,
        index=m.POWERHOUSES,
        param=(
            m.powerhouse_water_node,
            m.tailwater_elevation,
            m.headloss_factor,
            m.turbine_efficiency,
        ),
    )

    df = get_optype_inputs_as_df(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="gen_hydro_water",
        required_columns=["powerhouse"],
        optional_columns=[],
    )

    powerhouse_project_list = list()
    for row in zip(df["powerhouse"], df["project"]):
        [pwrh, prj] = row
        powerhouse_project_list.append((pwrh, prj))

    data_portal.data()["POWERHOUSE_GENERATORS"] = powerhouse_project_list


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
    powerhouses = c.execute(
        f"""SELECT powerhouse, powerhouse_water_node, tailwater_elevation, 
            headloss_factor, turbine_efficiency
            FROM inputs_system_water_powerhouses
            WHERE water_powerhouse_scenario_id = 
            {subscenarios.WATER_POWERHOUSE_SCENARIO_ID}
            AND powerhouse_water_node IN (
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
            AND powerhouse_water_node in (
                SELECT water_node
                FROM inputs_system_water_node_reservoirs
                WHERE water_node_reservoir_scenario_id = 
                    {subscenarios.WATER_NODE_RESERVOIR_SCENARIO_ID}
            )
            ;
            """
    )

    return powerhouses


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

    powerhouses = get_inputs_from_database(
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
            "powerhouses.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "powerhouse",
                "powerhouse_water_node",
                "tailwater_elevation",
                "headloss_factor",
                "turbine_efficiency",
            ]
        )

        for row in powerhouses:
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
        "water_node",
        "gross_head",
        "net_head",
        "water_discharge_to_powerhouse_rate_vol_per_sec",
    ]
    data = [
        [
            p,
            tmp,
            m.powerhouse_water_node[p],
            value(m.Gross_Head[p, tmp]),
            value(m.Net_Head[p, tmp]),
            value(
                m.Discharge_Water_to_Powerhouse_Rate_Vol_Per_Sec[
                    m.powerhouse_water_node[p], tmp
                ]
            ),
        ]
        for p in m.POWERHOUSES
        for tmp in m.TMPS
    ]
    results_df = create_results_df(
        index_columns=["powerhouse", "timepoint"],
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
            "system_water_powerhouse_timepoint.csv",
        ),
        sep=",",
        index=True,
    )


def import_results_into_database(
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    c,
    db,
    results_directory,
    quiet,
):
    import_csv(
        conn=db,
        cursor=c,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        quiet=quiet,
        results_directory=results_directory,
        which_results="system_water_powerhouse_timepoint",
    )
