# Copyright 2022 (c) Crown Copyright, GC.
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

""" """

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
    | | :code:`PERFORMANCE_STANDARD_PRJS_PERFORMANCE_STANDARD_ZONES`          |
    | | *Within*: :code:`m.PROJECTS * m.PERFORMANCE_STANDARD_ZONES`           |
    |                                                                         |
    | set of projects we need to track for the performance standard.          |
    | Two-dimensional set of performance standard projects and the            |
    | performance standard zones they contribute to. Projects can contribute  |
    | to multiple performance standard zones.                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Sets                                                            |
    +=========================================================================+
    | | :code:`PERFORMANCE_STANDARD_PRJS`                                     |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | Two set of performance standard projects we need to track for the       |
    | performance standard.                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`PERFORMANCE_STANDARD_PRJS_BY_PERFORMANCE_STANDARD_ZONE`        |
    | | *Defined over*: :code:`PERFORMANCE_STANDARD_ZONES`                    |
    | | *Within*: :code:`PERFORMANCE_STANDARD_PRJS`                           |
    |                                                                         |
    | Indexed set that describes the list of performance standard projects    |
    | for each performance standard zone.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`PERFORMANCE_STANDARD_OPR_TMPS`                                 |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | Two-dimensional set that defines all project-timepoint combinations     |
    | when a performance standard project can be operational.                 |
    +-------------------------------------------------------------------------+
    | | :code:`PERFORMANCE_STANDARD_OPR_PRDS`                                 |
    | | *Within*: :code:`PRJ_OPR_PRDS`                                        |
    |                                                                         |
    | Two-dimensional set that defines all project-period combinations        |
    | when a performance standard project can be operational.                 |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.PERFORMANCE_STANDARD_PRJS_PERFORMANCE_STANDARD_ZONES = Set(
        dimen=2, within=m.PROJECTS * m.PERFORMANCE_STANDARD_ZONES
    )

    # Derived Sets
    ###########################################################################

    m.PERFORMANCE_STANDARD_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: list(
            set(
                [
                    prj
                    for (
                        prj,
                        z,
                    ) in mod.PERFORMANCE_STANDARD_PRJS_PERFORMANCE_STANDARD_ZONES
                ]
            )
        ),
    )

    m.PERFORMANCE_STANDARD_PRJS_BY_PERFORMANCE_STANDARD_ZONE = Set(
        m.PERFORMANCE_STANDARD_ZONES,
        within=m.PROJECTS,
        initialize=lambda mod, ps_z: [
            prj
            for (prj, z) in mod.PERFORMANCE_STANDARD_PRJS_PERFORMANCE_STANDARD_ZONES
            if ps_z == z
        ],
    )

    m.PERFORMANCE_STANDARD_OPR_TMPS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.PERFORMANCE_STANDARD_PRJS,
        ),
    )
    m.PERFORMANCE_STANDARD_OPR_PRDS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_PRDS",
            index=0,
            membership_set=mod.PERFORMANCE_STANDARD_PRJS,
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
            "project_performance_standard_zones.tab",
        ),
        set=m.PERFORMANCE_STANDARD_PRJS_PERFORMANCE_STANDARD_ZONES,
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
        """SELECT project, performance_standard_zone
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get performance standard zones for those projects
        (SELECT project, performance_standard_zone
            FROM inputs_project_performance_standard_zones
            WHERE project_performance_standard_zone_scenario_id = {}
        ) as prj_ps_zone_tbl
        USING (project)
        -- Filter out projects whose performance standard zone is not one included in 
        -- our performance_standard_zone_scenario_id
        WHERE performance_standard_zone in (
                SELECT performance_standard_zone
                    FROM inputs_geography_performance_standard_zones
                    WHERE performance_standard_zone_scenario_id = {}
        );
        """.format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_PERFORMANCE_STANDARD_ZONE_SCENARIO_ID,
            subscenarios.PERFORMANCE_STANDARD_ZONE_SCENARIO_ID,
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
    in project_performance_standard_zones.tab file.
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
            "project_performance_standard_zones.tab",
        ),
        "w",
        newline="",
    ) as projects_file_out:
        writer = csv.writer(projects_file_out, delimiter="\t", lineterminator="\n")
        writer.writerow(["project", "performance_standard_zone"])
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
        print("update performance standard zones")

    tables_to_update = determine_table_subset_by_start_and_column(
        conn=db, tbl_start="results_project_", cols=["performance_standard_zone"]
    )

    for tbl in tables_to_update:
        update_prj_zone_column(
            conn=db,
            scenario_id=scenario_id,
            subscenarios=subscenarios,
            subscenario="project_performance_standard_zone_scenario_id",
            subsc_tbl="inputs_project_performance_standard_zones",
            prj_tbl=tbl,
            col="performance_standard_zone",
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
    zones_w_project = df["performance_standard_zone"].unique()

    # Get the required performance standard zones
    c = conn.cursor()
    zones = c.execute(
        """SELECT performance_standard_zone FROM inputs_geography_performance_standard_zones
        WHERE performance_standard_zone_scenario_id = {}
        """.format(
            subscenarios.PERFORMANCE_STANDARD_ZONE_SCENARIO_ID
        )
    )
    zones = [z[0] for z in zones]  # convert to list

    # Check that each performance standard zone has at least one project assigned to it
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_performance_standard_zones",
        severity="High",
        errors=validate_idxs(
            actual_idxs=zones_w_project,
            req_idxs=zones,
            idx_label="performance_standard_zone",
            msg="Each performance standard zone needs at least 1 "
            "project assigned to it.",
        ),
    )
