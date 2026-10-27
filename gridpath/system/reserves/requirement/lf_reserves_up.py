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
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.system.reserves.requirement.reserve_requirements import (
    generic_get_inputs_from_database,
    generic_add_model_components,
    generic_load_model_data,
    generic_validate_inputs,
    generic_write_model_inputs,
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

    generic_add_model_components(
        m=m,
        d=d,
        reserve_zone_set="LF_RESERVES_UP_ZONES",
        reserve_requirement_tmp_param="lf_reserves_up_requirement_mw",
        reserve_requirement_percent_param="lf_up_per_req",
        reserve_zone_load_zone_set="LF_UP_BA_LZ",
        ba_prj_req_contribution_set="LF_UP_BA_PRJ_CONTRIBUTION",
        prj_power_param="lf_up_prj_pwr_contribution",
        prj_capacity_param="lf_up_prj_cap_contribution",
        reserve_requirement_expression="LF_Up_Requirement",
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
    generic_load_model_data(
        m=m,
        d=d,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        reserve_requirement_param="lf_reserves_up_requirement_mw",
        reserve_zone_load_zone_set="LF_UP_BA_LZ",
        reserve_requirement_percent_param="lf_up_per_req",
        ba_prj_req_contribution_set="LF_UP_BA_PRJ_CONTRIBUTION",
        prj_power_param="lf_up_prj_pwr_contribution",
        prj_capacity_param="lf_up_prj_cap_contribution",
        reserve_type="lf_reserves_up",
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
    return generic_get_inputs_from_database(
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        conn=conn,
        reserve_type="lf_reserves_up",
        reserve_type_ba_subscenario_id=subscenarios.LF_RESERVES_UP_BA_SCENARIO_ID,
        reserve_type_req_subscenario_id=subscenarios.LF_RESERVES_UP_SCENARIO_ID,
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
    generic_validate_inputs(
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        conn=conn,
        reserve_type="lf_reserves_up",
        reserve_type_ba_subscenario_id=subscenarios.LF_RESERVES_UP_BA_SCENARIO_ID,
        reserve_type_req_subscenario_id=subscenarios.LF_RESERVES_UP_SCENARIO_ID,
        gridpath_module=__name__,
    )


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
    lf_reserves_up_requirement.tab file.
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

    tmp_req, percent_req, percent_map, project_contributions = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    generic_write_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        timepoint_req=tmp_req,
        percent_req=percent_req,
        percent_map=percent_map,
        project_contributions=project_contributions,
        reserve_type="lf_reserves_up",
    )
