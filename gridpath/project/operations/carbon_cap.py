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
Carbon emissions from each carbonaceous project.
"""

import csv
import os.path
from pyomo.environ import Param, Set

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import (
    update_prj_zone_column,
    determine_table_subset_by_start_and_column,
    directories_to_db_values,
)
from gridpath.auxiliary.validations import write_validation_to_database, validate_idxs


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
    | | :code:`CRBN_PRJS_CRBN_CAP_ZONES`                                      |
    | | *Within*: :code:`m.PROJECTS * m.CARBON_CAP_ZONES`                     |                        |
    |                                                                         |
    | Two-dimensional set of carbonaceous projects and the carbon cap zones   |
    | they contribute to. Projects can contribute to multiple carbon cap      |
    | zones.                                                                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Sets                                                            |
    +=========================================================================+
    | | :code:`CRBN_PRJS`                                                     |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | Two set of carbonaceous projects we need to track for the carbon cap.   |
    +-------------------------------------------------------------------------+
    | | :code:`CRBN_PRJS_BY_CARBON_CAP_ZONE`                                  |
    | | *Defined over*: :code:`CARBON_CAP_ZONES`                              |
    | | *Within*: :code:`CRBN_PRJS`                                           |
    |                                                                         |
    | Indexed set that describes the list of carbonaceous projects for each   |
    | carbon cap zone.                                                        |
    +-------------------------------------------------------------------------+
    | | :code:`CRBN_PRJ_OPR_TMPS`                                             |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | Two-dimensional set that defines all project-timepoint combinations     |
    | when a carbonaceous project can be operational.                         |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################
    m.CRBN_PRJS_CRBN_CAP_ZONES = Set(dimen=2, within=m.PROJECTS * m.CARBON_CAP_ZONES)

    # Derived Sets
    ###########################################################################

    m.CRBN_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(set([prj for (prj, z) in mod.CRBN_PRJS_CRBN_CAP_ZONES])),
        ),
    )
    m.CRBN_PRJS_BY_CARBON_CAP_ZONE = Set(
        m.CARBON_CAP_ZONES,
        within=m.PROJECTS,
        initialize=lambda mod, co2_z: [
            prj for (prj, z) in mod.CRBN_PRJS_CRBN_CAP_ZONES if co2_z == z
        ],
    )

    m.CRBN_PRJ_OPR_TMPS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.CRBN_PRJS
        ),
    )


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
            "project_carbon_cap_zones.tab",
        ),
        set=m.CRBN_PRJS_CRBN_CAP_ZONES,
    )


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

    c = conn.cursor()
    project_zones = c.execute(
        """SELECT project, carbon_cap_zone
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get carbon cap zones for those projects
        (SELECT project, carbon_cap_zone
            FROM inputs_project_carbon_cap_zones
            WHERE project_carbon_cap_zone_scenario_id = {}
        ) as prj_cc_zone_tbl
        USING (project)
        -- Filter out projects whose carbon cap zone is not one included in 
        -- our carbon_cap_zone_scenario_id
        WHERE carbon_cap_zone in (
                SELECT carbon_cap_zone
                    FROM inputs_geography_carbon_cap_zones
                    WHERE carbon_cap_zone_scenario_id = {}
        );
        """.format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_CARBON_CAP_ZONE_SCENARIO_ID,
            subscenarios.CARBON_CAP_ZONE_SCENARIO_ID,
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

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "project_carbon_cap_zones.tab",
        ),
        "w",
        newline="",
    ) as projects_file_out:
        writer = csv.writer(projects_file_out, delimiter="\t", lineterminator="\n")
        writer.writerow(["project", "carbon_cap_zone"])
        for row in project_zones.fetchall():
            writer.writerow(list(row))


def process_results(db, c, scenario_id, subscenarios, quiet):
    """

    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("update carbon cap zones")

    tables_to_update = determine_table_subset_by_start_and_column(
        conn=db, tbl_start="results_project_", cols=["carbon_cap_zone"]
    )

    for tbl in tables_to_update:
        update_prj_zone_column(
            conn=db,
            scenario_id=scenario_id,
            subscenarios=subscenarios,
            subscenario="project_carbon_cap_zone_scenario_id",
            subsc_tbl="inputs_project_carbon_cap_zones",
            prj_tbl=tbl,
            col="carbon_cap_zone",
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
    zones_w_project = df["carbon_cap_zone"].unique()

    # Get the required carbon cap zones
    # TODO: make this into a function similar to get_projects()?
    #  could eventually centralize all these db query functions in one place
    c = conn.cursor()
    zones = c.execute("""SELECT carbon_cap_zone FROM inputs_geography_carbon_cap_zones
        WHERE carbon_cap_zone_scenario_id = {}
        """.format(subscenarios.CARBON_CAP_ZONE_SCENARIO_ID))
    zones = [z[0] for z in zones]  # convert to list

    # Check that each carbon cap zone has at least one project assigned to it
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_carbon_cap_zones",
        severity="High",
        errors=validate_idxs(
            actual_idxs=zones_w_project,
            req_idxs=zones,
            idx_label="carbon_cap_zone",
            msg="Each carbon cap zone needs at least 1 " "project assigned to it.",
        ),
    )

    # TODO: need validation that projects with carbon cap zones also have fuels
