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
Fuel burn limit for each fuel burn balancing area.
"""

import csv
import os.path


from pyomo.environ import Set, Param, NonNegativeReals, Any, Reals

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import warn_on_unknown_balancing_types

Infinity = float("inf")
Negative_Infinity = float("-inf")


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

    m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT = Set(
        dimen=3, within=m.FUEL_BURN_LIMIT_BAS * m.BLN_TYPE_HRZS
    )
    m.fuel_burn_min_unit = Param(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT,
        within=Reals,
        default=Negative_Infinity,
    )
    m.fuel_burn_max_unit = Param(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT,
        within=NonNegativeReals,
        default=Infinity,
    )
    m.relative_fuel_burn_max_ba = Param(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT,
        within=Any,
        default="undefined",
    )
    m.fraction_of_relative_fuel_burn_max_fuel_ba = Param(
        m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT,
        within=NonNegativeReals,
        default=Infinity,
    )

    m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MIN_ABS_LIMIT = Set(
        dimen=3,
        initialize=lambda mod: [
            (ba, bt, h)
            for (ba, bt, h) in mod.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT
            if mod.fuel_burn_min_unit[ba, bt, h] != Negative_Infinity
        ],
    )

    m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_ABS_LIMIT = Set(
        dimen=3,
        initialize=lambda mod: [
            (ba, bt, h)
            for (ba, bt, h) in mod.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT
            if mod.fuel_burn_max_unit[ba, bt, h] != Infinity
        ],
    )

    m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_MAX_REL_LIMIT = Set(
        dimen=3,
        initialize=lambda mod: [
            (ba, bt, h)
            for (ba, bt, h) in mod.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT
            if (
                mod.relative_fuel_burn_max_ba[ba, bt, h] != "undefined"
                and mod.fraction_of_relative_fuel_burn_max_fuel_ba[ba, bt, h]
                != Infinity
            )
        ],
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
    :param subproblem:
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
            "fuel_burn_limits.tab",
        ),
        index=m.FUEL_BA_BLN_TYPE_HRZS_WITH_FUEL_BURN_LIMIT,
        param=(
            m.fuel_burn_min_unit,
            m.fuel_burn_max_unit,
            m.relative_fuel_burn_max_ba,
            m.fraction_of_relative_fuel_burn_max_fuel_ba,
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

    # Balancing types the temporal scenario lacks are dropped by the query
    # below
    warn_on_unknown_balancing_types(
        conn=conn,
        temporal_scenario_id=subscenarios.TEMPORAL_SCENARIO_ID,
        table="inputs_system_fuel_burn_limits",
        bt_column="balancing_type_horizon",
        row_filter=f"""fuel_burn_limit_scenario_id = {subscenarios.FUEL_BURN_LIMIT_SCENARIO_ID}
        AND subproblem_id = {subproblem}
        AND stage_id = {stage}
        AND fuel_burn_limit_ba IN (
            SELECT fuel_burn_limit_ba
            FROM inputs_geography_fuel_burn_limit_balancing_areas
            WHERE fuel_burn_limit_ba_scenario_id = {subscenarios.FUEL_BURN_LIMIT_BA_SCENARIO_ID}
        )""",
    )

    c = conn.cursor()
    fuel_burn_limits = c.execute(
        """SELECT fuel_burn_limit_ba, balancing_type_horizon, horizon, 
        fuel_burn_min_unit, fuel_burn_max_unit,
        relative_fuel_burn_max_ba, fraction_of_relative_fuel_burn_max_fuel_ba
        FROM inputs_system_fuel_burn_limits
        JOIN
        (SELECT balancing_type_horizon, horizon
        FROM inputs_temporal_horizons
        WHERE temporal_scenario_id = {temporal_scenario_id}) as relevant_horizons
        USING (balancing_type_horizon, horizon)
        JOIN
        (SELECT fuel_burn_limit_ba
        FROM inputs_geography_fuel_burn_limit_balancing_areas
        WHERE fuel_burn_limit_ba_scenario_id = {fuel_burn_limit_ba_scenario_id}
        ) as 
        relevant_zones
        USING (fuel_burn_limit_ba)
        WHERE fuel_burn_limit_scenario_id = {fuel_burn_limit_scenario_id}
        AND subproblem_id = {subproblem_id}
        AND stage_id = {stage_id};
        """.format(
            temporal_scenario_id=subscenarios.TEMPORAL_SCENARIO_ID,
            fuel_burn_limit_ba_scenario_id=subscenarios.FUEL_BURN_LIMIT_BA_SCENARIO_ID,
            fuel_burn_limit_scenario_id=subscenarios.FUEL_BURN_LIMIT_SCENARIO_ID,
            subproblem_id=subproblem,
            stage_id=stage,
        )
    )

    return fuel_burn_limits


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
    carbon_cap.tab file.
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

    fuel_burn_limits = get_inputs_from_database(
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
            "fuel_burn_limits.tab",
        ),
        "w",
        newline="",
    ) as carbon_cap_file:
        writer = csv.writer(carbon_cap_file, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "fuel_burn_limit_ba",
                "balancing_type",
                "horizon",
                "fuel_burn_min_unit",
                "fuel_burn_max_unit",
                "relative_fuel_burn_max_ba",
                "fraction_of_relative_fuel_burn_max_fuel_ba",
            ]
        )

        for row in fuel_burn_limits:
            row = ["." if i is None else i for i in row]
            writer.writerow(row)
