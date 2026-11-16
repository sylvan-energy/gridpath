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
Add project-level components for upward regulation reserves that also
depend on operational type.

The optional :code:`regulation_up_ramp_rate` input limits the project's
provision to that fraction of its online capacity (unitless: the project's
ramp rate as a fraction of capacity per minute times the product's response
time in minutes, e.g. 0.01/min x 10 min = 0.1). Not limited if not specified.
"""

import csv
import os.path

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import write_validation_to_database, validate_values
from gridpath.project.operations.reserves.reserve_provision import (
    project_bas_input_file_name,
)
from gridpath.project.operations.reserves.op_type_dependent.reserve_limits_by_op_type import (
    generic_add_model_components,
    generic_load_model_data,
)

# Inputs
# The column get_inputs writes to projects.tab (same as the opchar column)
RESERVE_PROVISION_RAMP_RATE_LIMIT_COLUMN_NAME_IN_INPUT_FILE = "regulation_up_ramp_rate"
# Model components
RESERVE_PROVISION_VARIABLE_NAME = "Provide_Regulation_Up_MW"
RESERVE_PROVISION_RAMP_RATE_LIMIT_CONSTRAINT_NAME = (
    "Regulation_Up_Provision_Ramp_Rate_Limit_Constraint"
)
RESERVE_PROVISION_RAMP_RATE_LIMIT_PARAM_NAME = "regulation_up_ramp_rate_limit"
RESERVE_PROJECTS_SET_NAME = "REGULATION_UP_PROJECTS"
RESERVE_PRJ_OPR_TMPS_SET_NAME = "REGULATION_UP_PRJ_OPR_TMPS"


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
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        reserve_projects_set=RESERVE_PROJECTS_SET_NAME,
        reserve_project_operational_timepoints_set=RESERVE_PRJ_OPR_TMPS_SET_NAME,
        reserve_provision_variable_name=RESERVE_PROVISION_VARIABLE_NAME,
        reserve_provision_ramp_rate_limit_param=RESERVE_PROVISION_RAMP_RATE_LIMIT_PARAM_NAME,
        reserve_provision_ramp_rate_limit_constraint=RESERVE_PROVISION_RAMP_RATE_LIMIT_CONSTRAINT_NAME,
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
        ramp_rate_limit_column_name=RESERVE_PROVISION_RAMP_RATE_LIMIT_COLUMN_NAME_IN_INPUT_FILE,
        reserve_provision_ramp_rate_limit_param=RESERVE_PROVISION_RAMP_RATE_LIMIT_PARAM_NAME,
        project_bas_input_file=project_bas_input_file_name("regulation_up"),
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
    # TODO: generalize this for all reserves and inner join to portfolio

    c = conn.cursor()
    # Get regulation_up ramp rate limit
    prj_ramp_rates = c.execute(
        """SELECT project, regulation_up_ramp_rate
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {};""".format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID
        )
    )

    return prj_ramp_rates


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

    prj_ramp_rates = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )
    df = cursor_to_df(prj_ramp_rates)

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_operational_chars",
        severity="Mid",
        errors=validate_values(df, ["regulation_up_ramp_rate"], min=0, max=1),
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
    projects.tab file (to be precise, amend it).
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

    prj_ramp_rates = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # Make a dict for easy access
    prj_ramp_rate_dict = dict()
    for prj, ramp_rate in prj_ramp_rates:
        prj_ramp_rate_dict[str(prj)] = "." if ramp_rate is None else str(ramp_rate)

    # Add params to projects file
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "projects.tab",
        ),
        "r",
    ) as projects_file_in:
        reader = csv.reader(projects_file_in, delimiter="\t", lineterminator="\n")

        new_rows = list()

        # Append column header
        header = next(reader)
        header.append(RESERVE_PROVISION_RAMP_RATE_LIMIT_COLUMN_NAME_IN_INPUT_FILE)
        new_rows.append(header)

        # Append correct values
        for row in reader:
            # If project specified, check if ramp rate specified or not
            if row[0] in list(prj_ramp_rate_dict.keys()):
                row.append(prj_ramp_rate_dict[row[0]])
            # If project not specified, specify no ramp rate
            else:
                row.append(".")

            # Add resulting row to new_rows list
            new_rows.append(row)

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "projects.tab",
        ),
        "w",
        newline="",
    ) as projects_file_out:
        writer = csv.writer(projects_file_out, delimiter="\t", lineterminator="\n")
        writer.writerows(new_rows)
