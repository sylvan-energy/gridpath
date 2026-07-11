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
PRM projects and the zone they contribute to
"""

import csv
import os.path
from pyomo.environ import Param, Set

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_idxs,
    validate_missing_inputs,
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
    # First figure out which projects we need to track for PRM contribution
    m.PRM_PROJECTS = Set(within=m.PROJECTS)
    m.prm_zone = Param(m.PRM_PROJECTS, within=m.PRM_ZONES)
    m.prm_type = Param(
        m.PRM_PROJECTS,
        within=[
            "energy_only_allowed",
            "fully_deliverable",
            "fully_deliverable_energy_limited",
        ],
    )

    m.PRM_PROJECTS_BY_PRM_ZONE = Set(
        m.PRM_ZONES,
        within=m.PRM_PROJECTS,
        initialize=lambda mod, prm_z: subset_init_by_param_value(
            mod, "PRM_PROJECTS", "prm_zone", prm_z
        ),
    )

    # Get operational carbon cap projects - timepoints combinations
    m.PRM_PRJ_OPR_PRDS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_PRDS", index=0, membership_set=mod.PRM_PROJECTS
        ),
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
            "projects.tab",
        ),
        select=("project", "prm_zone", "prm_type"),
        param=(m.prm_zone, m.prm_type),
    )

    data_portal.data()["PRM_PROJECTS"] = {
        None: list(data_portal.data()["prm_zone"].keys())
    }


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
    project_zones = c.execute(
        """SELECT project, prm_zone, prm_type
        FROM 
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {portfolio}
        ) as prj_tbl
            LEFT OUTER JOIN
        (SELECT project, prm_zone
        FROM inputs_project_prm_zones
        WHERE project_prm_zone_scenario_id = {prj_prm_zone}) as prm_zone_tbl
        USING (project)
        LEFT OUTER JOIN
        (SELECT DISTINCT project, prm_type -- make sure prm_type is the same in all prds
        FROM inputs_project_elcc_chars
        WHERE project_elcc_chars_scenario_id = {prj_elcc}) as prm_type_tbl
        USING (project)
        -- Filter out projects whose PRM zone is not one included in our 
        -- prm_zone_sceenario_id
        WHERE prm_zone in (
                SELECT prm_zone
                    FROM inputs_geography_prm_zones
                    WHERE prm_zone_scenario_id = {prm_zone}
        );
        """.format(
            portfolio=subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            prj_prm_zone=subscenarios.PROJECT_PRM_ZONE_SCENARIO_ID,
            prj_elcc=subscenarios.PROJECT_ELCC_CHARS_SCENARIO_ID,
            prm_zone=subscenarios.PRM_ZONE_SCENARIO_ID,
        )
    )

    return project_zones


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

    project_zones = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    # Convert input data into pandas DataFrame
    df = cursor_to_df(project_zones)
    zones_w_project = df["prm_zone"].unique()

    # Get the required PRM zones
    # TODO: make this into a function similar to get_projects()?
    #  could eventually centralize all these db query functions in one place
    c = conn.cursor()
    zones = c.execute("""SELECT prm_zone FROM inputs_geography_prm_zones
        WHERE prm_zone_scenario_id = {}
        """.format(subscenarios.PRM_ZONE_SCENARIO_ID))
    zones = [z[0] for z in zones]  # convert to list

    # Check that each PRM zone has at least one project assigned to it
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_prm_zones",
        severity="High",
        errors=validate_idxs(
            actual_idxs=zones_w_project,
            req_idxs=zones,
            idx_label="prm_zone",
            msg="Each PRM zone needs at least 1 project " "assigned to it.",
        ),
    )

    # Make sure PRM type is specified
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_elcc_chars",
        severity="High",
        errors=validate_missing_inputs(df, "prm_type"),
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

    project_zones = get_inputs_from_database(
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
    # Only assign a type to projects that contribute to a PRM zone in case
    # we have projects with missing zones here
    prj_zone_type_dict = dict()
    for prj, zone, prm_type in project_zones:
        prj_zone_type_dict[str(prj)] = (
            (".", ".") if zone is None else (str(zone), str(prm_type))
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
            "projects.tab",
        ),
        "r",
    ) as projects_file_in:
        reader = csv.reader(projects_file_in, delimiter="\t", lineterminator="\n")

        new_rows = list()

        # Append column header
        header = next(reader)
        for new_column in ["prm_zone", "prm_type"]:
            header.append(new_column)
        new_rows.append(header)

        # Append correct values
        for row in reader:
            # If project specified, check if BA specified or not
            if row[0] in list(prj_zone_type_dict.keys()):
                for new_column_value in [
                    prj_zone_type_dict[row[0]][0],
                    prj_zone_type_dict[row[0]][1],
                ]:
                    row.append(new_column_value)
                new_rows.append(row)
            # If project not specified, specify no BA
            else:
                for new_column in range(2):
                    row.append(".")
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
