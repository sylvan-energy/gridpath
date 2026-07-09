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
Add project-level components for downward load-following reserves
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Set, Param, Var, NonNegativeReals, PercentFraction, value
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import (
    reserve_variable_derate_params,
)
from gridpath.auxiliary.validations import write_validation_to_database, validate_idxs
from gridpath.auxiliary.auxiliary import (
    check_list_items_are_unique,
    find_list_item_position,
    cursor_to_df,
    subset_init_by_set_membership,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.project import PROJECT_TIMEPOINT_DF


def record_dynamic_components(
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    :param d: the DynamicComponents class we'll be populating
    :param scenario_directory: the base scenario directory
    :param stage: the horizon subproblem, not used here
    :param stage: the stage subproblem, not used here

    This method populates the following 'dynamic components':

    * inertia_variable
    * reserve_variable_derate_params

    The *inertia_variable* component is populated
    based on the data in the *projects.tab* input file.

    For projects for which a balancing area is specified (as opposed to
    having a '.' value indicating no balancing area), the inertia
    reserve-provision variable name  will be added to
    the project's list of inertia variables. These lists will then be
    passed to the 'add_model_components' method of the
    operational-modules and used to build the appropriate operational
    constraints for each project, usually named the 'inertia_provision_rule'
    in the operational-type modules.

    Advanced GridPath functionality includes the ability to put a more
    stringent constraint on reserve-provision than the available
    inertia by de-rating how much of the available project
    inertia can be used for a certain reserve-type in the respective
    constraints in the *operational_type* modules. The
    *reserve_variable_derate_params* dynamic component dictionary is
    populated here; it has the project-level reserve provision variable as
    key and the derate param for the respective reserve variable as value.

    .. note:: Currently, these de-rates are only used in the *variable*
        operational type and we need to add them to other operational types.
    """

    # Check which projects have been assigned a balancing area for the
    # current reserve type (i.e. they have a value in the column named
    # 'ba_column_name'); add the variable name for the current reserve type
    # to the list of variables in the headroom/footroom dictionary for the
    # project
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
    ) as projects_file:
        projects_file_reader = csv.reader(
            projects_file, delimiter="\t", lineterminator="\n"
        )
        headers = next(projects_file_reader)
        # Check that column names are not repeated
        check_list_items_are_unique(headers)
        for row in projects_file_reader:
            # Get generator name; we have checked that column names are unique
            # so can expect a single-item list here and get 0th element
            generator = row[find_list_item_position(headers, "project")[0]]

            # If we have already added this generator to the head/footroom
            # variables dictionary, move on; otherwise, create the
            # dictionary item
            if generator not in list(getattr(d, "inertia_variable").keys()):
                getattr(d, "inertia_variable")[generator] = list()
            # Some generators get the variables associated with
            # provision of various services (e.g. reserves) if flagged
            # Figure out which these are here based on whether a reserve zone
            # is specified ("." = no zone specified, so project does not
            # contribute to this reserve requirement)
            # The names of the reserve variables for each generator
            if row[find_list_item_position(headers, "inertia_reserves_ba")[0]] != ".":
                getattr(d, "inertia_variable")[generator].append(
                    "Provide_Inertia_Reserves_MWs"
                )

    # The names of the headroom/footroom derate params for each reserve
    # variable
    # Will be used to get the right derate parameter name for each
    # reserve-provision variable
    # TODO: these de-rates are currently only used in the variable
    #  operational_type and must be added to other operational types
    getattr(d, reserve_variable_derate_params)[
        "Provide_Inertia_Reserves_MWs"
    ] = "inertia_reserves_derate"


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

    record_dynamic_components(
        d,
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    )

    m.INERTIA_RESERVES_PROJECTS = Set(within=m.PROJECTS)

    m.inertia_reserves_zone = Param(
        m.INERTIA_RESERVES_PROJECTS, within=m.INERTIA_RESERVES_ZONES
    )

    m.INERTIA_RESERVES_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.INERTIA_RESERVES_PROJECTS,
        ),
    )

    m.Provide_Inertia_Reserves_MWs = Var(
        m.INERTIA_RESERVES_PRJ_OPR_TMPS, within=NonNegativeReals
    )

    # Inertia derate -- this is how much inertia must be available in order
    # to provide 1 unit of reserves
    # For example, if the derate is 0.5, the required inertia for providing
    # inertia reserves is 1/0.5=2 -- twice the reserve that can be provided
    # Defaults to 1 if not specified
    # This param is used by the operational_type modules
    m.inertia_reserves_derate = Param(
        m.INERTIA_RESERVES_PROJECTS, within=PercentFraction, default=1
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

    columns_to_import = (
        "project",
        "inertia_reserves_ba",
    )
    params_to_import = (m.inertia_reserves_zone,)
    projects_file_header = pd.read_csv(
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
        sep="\t",
        header=None,
        nrows=1,
    ).values[0]

    # Import reserve provision headroom/footroom de-rate parameter only if
    # column is present
    # Otherwise, the de-rate param goes to its default of 1
    if "inertia_reserves_derate" in projects_file_header:
        columns_to_import += ("inertia_reserves_derate",)
        params_to_import += (m.inertia_reserves_derate,)

    # Load the needed data
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
        select=columns_to_import,
        param=params_to_import,
    )

    data_portal.data()["INERTIA_RESERVES_PROJECTS"] = {
        None: list(data_portal.data()["inertia_reserves_zone"].keys())
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
    Export project-level results for downward load-following
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    results_columns = [
        f"inertia_reserves_ba",
        f"inertia_reserves_reserve_provision_mws",
    ]

    data = [
        [
            prj,
            tmp,
            m.inertia_reserves_zone[prj],
            value(m.Provide_Inertia_Reserves_MWs[prj, tmp]),
        ]
        for (prj, tmp) in m.INERTIA_RESERVES_PRJ_OPR_TMPS
    ]

    results_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PROJECT_TIMEPOINT_DF), results_df)


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
    # Get project BA
    # Get project BA
    c1 = conn.cursor()
    prj_bas = c1.execute(
        """
        SELECT project, inertia_reserves_ba
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get BAs for those projects
        (SELECT project, inertia_reserves_ba
            FROM inputs_project_inertia_reserves_bas
            WHERE project_inertia_reserves_ba_scenario_id = {}
        ) as prj_ba_tbl
        USING (project)
        -- Filter out projects whose BA is not one included in our 
        -- reserve_ba_scenario_id
        WHERE inertia_reserves_ba in (
                SELECT inertia_reserves_ba
                    FROM inputs_geography_inertia_reserves_bas
                    WHERE inertia_reserves_ba_scenario_id = {}
        );
        """.format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_INERTIA_RESERVES_BA_SCENARIO_ID,
            subscenarios.INERTIA_RESERVES_BA_SCENARIO_ID,
        )
    )

    # Get headroom/footroom derate
    c2 = conn.cursor()
    prj_derates = c2.execute(
        """
        SELECT project, inertia_reserves_derate
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get derates for those projects
        (SELECT project, inertia_reserves_derate
            FROM inputs_project_operational_chars
            WHERE project_operational_chars_scenario_id = {}
        ) as prj_derate_tbl
        USING (project);
        """.format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
        )
    )

    return prj_bas, prj_derates


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

    project_bas, prj_derates = get_inputs_from_database(
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        conn=conn,
    )

    # Convert input data into pandas DataFrame
    df = cursor_to_df(project_bas)
    df_derate = cursor_to_df(prj_derates).dropna()
    bas_w_project = df["inertia_reserves_ba"].unique()
    projects_w_ba = df["project"].unique()
    projects_w_derate = df_derate["project"].unique()

    # Get the required reserve bas
    c = conn.cursor()
    bas = c.execute(
        """SELECT inertia_reserves_ba FROM inputs_geography_inertia_reserves_bas
        WHERE inertia_reserves_ba_scenario_id = {}
        """.format(
            subscenarios.INERTIA_RESERVES_BA_SCENARIO_ID,
        )
    )
    bas = [b[0] for b in bas]  # convert to list

    # Check that each reserve BA has at least one project assigned to it
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_inertia_reserves_bas",
        severity="High",
        errors=validate_idxs(
            actual_idxs=bas_w_project,
            req_idxs=bas,
            idx_label="inertia_reserves_ba",
            msg="Each reserve BA needs at least 1 " "project assigned to it.",
        ),
    )

    # Check that all projects w derates have a BA specified
    msg = "Project has a reserve derate specified but no relevant BA."
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
        severity="Low",
        errors=validate_idxs(
            actual_idxs=projects_w_ba,
            req_idxs=projects_w_derate,
            idx_label="project",
            msg=msg,
        ),
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

    project_bas, prj_derates = get_inputs_from_database(
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
    prj_ba_dict = dict()
    for prj, ba in project_bas:
        prj_ba_dict[str(prj)] = "." if ba is None else str(ba)

    # Make a dict for easy access
    prj_derate_dict = dict()
    for prj, derate in prj_derates:
        prj_derate_dict[str(prj)] = "." if derate is None else str(derate)

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
        header.append("inertia_reserves_ba")
        header.append("inertia_reserves_derate")
        new_rows.append(header)

        # Append correct values
        for row in reader:
            # If project specified, check if BA specified or not
            if row[0] in list(prj_ba_dict.keys()):
                row.append(prj_ba_dict[row[0]])
            # If project not specified, specify no BA
            else:
                row.append(".")

            # If project specified, check if derate specified or not
            if row[0] in list(prj_derate_dict.keys()):
                row.append(prj_derate_dict[row[0]])
            # If project not specified, specify no derate
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
