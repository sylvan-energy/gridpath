# Copyright 2021 (c) Crown Copyright, GC.
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
Get RECs for each project
"""

import csv
import os.path
from pyomo.environ import Param, Set, value

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import (
    update_prj_zone_column,
    determine_table_subset_by_start_and_column,
    directories_to_db_values,
)
from gridpath.common_functions import create_results_df
from gridpath.auxiliary.validations import write_validation_to_database, validate_idxs
from gridpath.project import PROJECT_TIMEPOINT_DF


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
    The following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`INST_PEN_PRJS`                                                 |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of all instantaneous penetration eligible projects.             |
    +-------------------------------------------------------------------------+
    | | :code:`INST_PEN_PRJ_OPR_TMP`                                          |
    |                                                                         |
    | Two-dimensional set that defines all project-timepoint combinations     |
    | when an instantaneous penetration eligible project can be operational.  |
    +-------------------------------------------------------------------------+
    | | :code:`INST_PEN_PRJ_OPR_TMP`                      |
    | | *Defined over*: :code:`INSTANTANEOUS_PENETRATION_ZONES`                           |
    | | *Within*: :code:`ENERGY_TARGET_PRJS`                                  |
    |                                                                         |
    | Indexed set that describes the instantaneous penetration projects for   |
    | each instantaneous penetration zone.                                    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Input Params                                                            |
    +=========================================================================+
    | | :code:`instantaneous_penetration_zone`                                |
    | | *Defined over*: :code:`INST_PEN_PRJS`                                 |
    | | *Within*: :code:`INSTANTANEOUS_PENETRATION_ZONES`                     |
    |                                                                         |
    | This param describes the instantaneous penetration zone for each        |
    | instantaneous penetration project.                                      |
    +-------------------------------------------------------------------------+

    """
    # Sets
    ###########################################################################

    m.INST_PEN_PRJS = Set(within=m.PROJECTS)

    m.INST_PEN_PRJ_OPR_TMP = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.INST_PEN_PRJS,
        ),
    )

    # Input Params
    ###########################################################################

    m.instantaneous_penetration_zone = Param(
        m.INST_PEN_PRJS, within=m.INSTANTANEOUS_PENETRATION_ZONES
    )

    # Derived Sets (requires input params)
    ###########################################################################

    m.INST_PEN_PRJS_BY_INSTANTANEOUS_PENETRATION_ZONE = Set(
        m.INST_PEN_PRJS,
        within=m.INST_PEN_PRJ_OPR_TMP,
        initialize=determine_instantaneous_penetration_generators_by_instantaneous_penetration_zone,
    )


# Set Rules
###############################################################################


def determine_instantaneous_penetration_generators_by_instantaneous_penetration_zone(
    mod, instantaneous_penetration_z
):
    return [
        p
        for p in mod.INST_PEN_PRJS
        if mod.instantaneous_penetration_zone[p] == instantaneous_penetration_z
    ]


# Input-Output
###############################################################################


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
        select=("project", "instantaneous_penetration_zone"),
        param=(m.instantaneous_penetration_zone,),
    )

    data_portal.data()["INST_PEN_PRJS"] = {
        None: list(data_portal.data()["instantaneous_penetration_zone"].keys())
    }


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
        "instantaneous_penetration_zone",
        "instantaneous_penetration_power_mw",
    ]
    data = [
        [
            prj,
            tmp,
            m.instantaneous_penetration_zone[prj],
            value(m.Bulk_Power_Provision_MW[prj, tmp]),
        ]
        for (prj, tmp) in m.INST_PEN_PRJ_OPR_TMP
    ]

    results_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    for c in results_columns:
        getattr(d, PROJECT_TIMEPOINT_DF)[c] = None
    getattr(d, PROJECT_TIMEPOINT_DF).update(results_df)


# Database
###############################################################################


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
    subproblem = 1 if subproblem == "" else subproblem
    stage = 1 if stage == "" else stage
    c = conn.cursor()

    # Get the instantaneous penetration zones for project in our portfolio
    # and with zones in our instantaneous penetration zones
    project_zones = c.execute(
        """SELECT project, instantaneous_penetration_zone
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get energy_target zones for those projects
        (SELECT project, instantaneous_penetration_zone
            FROM inputs_project_instantaneous_penetration_zones
            WHERE project_instantaneous_penetration_zone_scenario_id = {}
        ) as prj_instantaneous_penetration_zone_tbl
        USING (project)
        -- Filter out projects whose RPS zone is not one included in our 
        -- instantaneous_penetration_zone_scenario_id
        WHERE instantaneous_penetration_zone in (
                SELECT instantaneous_penetration_zone
                    FROM inputs_geography_instantaneous_penetration_zones
                    WHERE instantaneous_penetration_zone_scenario_id = {}
        );
        """.format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_INSTANTANEOUS_PENETRATION_ZONE_SCENARIO_ID,
            subscenarios.INSTANTANEOUS_PENETRATION_ZONE_SCENARIO_ID,
        )
    )

    return project_zones


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
    prj_zone_dict = dict()
    for prj, zone in project_zones:
        prj_zone_dict[str(prj)] = "." if zone is None else str(zone)

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
        header.append("instantaneous_penetration_zone")
        new_rows.append(header)

        # Append correct values
        for row in reader:
            # If project specified, check if BA specified or not
            if row[0] in list(prj_zone_dict.keys()):
                row.append(prj_zone_dict[row[0]])
                new_rows.append(row)
            # If project not specified, specify no BA
            else:
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


def process_results(db, c, scenario_id, subscenarios, quiet):
    """

    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("update instantaneous_penetration zones")

    tables_to_update = determine_table_subset_by_start_and_column(
        conn=db, tbl_start="results_project_", cols=["instantaneous_penetration_zone"]
    )

    for tbl in tables_to_update:
        update_prj_zone_column(
            conn=db,
            scenario_id=scenario_id,
            subscenarios=subscenarios,
            subscenario="project_instantaneous_penetration_zone_scenario_id",
            subsc_tbl="inputs_project_instantaneous_penetration_zones",
            prj_tbl=tbl,
            col="instantaneous_penetration_zone",
        )


# Validation
###############################################################################


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

    # Get the projects and energy-target zones
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
    zones_w_project = df["instantaneous_penetration_zone"].unique()

    # Get the required RPS zones
    # TODO: make this into a function similar to get_projects()?
    #  could eventually centralize all these db query functions in one place
    c = conn.cursor()
    zones = c.execute(
        """SELECT instantaneous_penetration_zone FROM inputs_geography_instantaneous_penetration_zones
        WHERE instantaneous_penetration_zone_scenario_id = {}
        """.format(
            subscenarios.INSTANTANEOUS_PENETRATION_ZONE_SCENARIO_ID
        )
    )
    zones = [z[0] for z in zones]  # convert to list

    # Check that each RPS zone has at least one project assigned to it
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_energy_target_zones",
        severity="High",
        errors=validate_idxs(
            actual_idxs=zones_w_project,
            req_idxs=zones,
            idx_label="instantaneous_penetration_zone",
            msg="Each energy target zone needs at least 1 " "project assigned to it.",
        ),
    )
