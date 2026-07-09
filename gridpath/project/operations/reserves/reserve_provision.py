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

""" """

import csv
import os.path
import pandas as pd
from pyomo.environ import Set, Param, Var, NonNegativeReals, PercentFraction, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import write_validation_to_database, validate_idxs
from gridpath.auxiliary.auxiliary import (
    check_list_items_are_unique,
    find_list_item_position,
    cursor_to_df,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.dynamic_components import (
    reserve_variable_derate_params,
    reserve_to_energy_adjustment_params,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.project import PROJECT_TIMEPOINT_DF


def generic_record_dynamic_components(
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    headroom_or_footroom_dict,
    ba_column_name,
    reserve_provision_variable_name,
    reserve_provision_derate_param_name,
    reserve_to_energy_adjustment_param_name,
    reserve_balancing_area_param_name,
):
    """
    :param d: the DynamicComponents class we'll be populating
    :param scenario_directory: the base scenario directory
    :param stage: the horizon subproblem, not used here
    :param stage: the stage subproblem, not used here
    :param headroom_or_footroom_dict: the headroom or footroom dictionary
        with projects as keys and list of headroom or footroom variables,
        respectively, as values; the keys are populated in the
        *determine_dynamic_inputs* method of *gridpath.project.__init__*
    :param ba_column_name: the name of the column that determines the
        reserve balancing area for the projects in the *projects.tab* input
        file
    :param reserve_provision_variable_name: the variable name for this
        reserve type
    :param reserve_provision_derate_param_name: the reserve-provision derate
        paramater name for this reserve type
    :param reserve_to_energy_adjustment_param_name: the
        reserve-to-energy-adjustment parameter name for this reserve type
    :param reserve_balancing_area_param_name: the project-level balancing
        area parameter name for this reserve type

    This method populates the following 'dynamic components':

    * headroom_variables or footroom_variables
    * reserve_variable_derate_params
    * reserve_to_energy_adjustment_params

    The *headroom_variables* and *footroom_variables* components are populated
    based on the data in the *projects.tab* input file.

    When this method is called, the module calling it will specify whether
    the respective reserve variable name should be added to the headroom or
    footroom dictionaries. The reserve module will also specify what the
    name is of the column in projects.tab where the project's balancing area
    for the respective reserve is specified, the *ba_column_name*. For
    projects for which a balancing area is specified (as opposed to having a
    '.' value indicating no balancing area), the respective
    reserve-provision variable name (the *reserve_provision_variable_name*
    specified by the reserve module calling this method) will be added to
    the project's list of headroom/footroom variables. These lists will then be
    passed to the 'add_model_components' method of the
    operational-modules and used to build the appropriate operational
    constraints for each project, usually named the 'max power rule' (power +
    upward reserves must be less than or equal to online capacity) and 'min
    power rule' (power - downward reserves must be greater than or equal to
    the minimum stable level) in the operational-type modules.

    Advanced GridPath functionality includes the ability to put a more
    stringent constraint on reserve-provision than the available
    headroom/footroom by de-rating how much of the available project
    headroom/footroom can be used for a certain reserve-type in the respective
    constraints in the *operational_type* modules. The
    *reserve_variable_derate_params* dynamic component dictionary is
    populated here; it has the project-level reserve provision variable as
    key and the derate param for the respective reserve variable as value.

    .. note:: Currently, these de-rates are only used in the *variable*
        operational type and we need to add them to other operational types.

    Advanced GridPath functionality also includes the ability to account for
    the energy effects of reserve-provision. For example, when providing
    regulation-up during a timepoint, projects will occasionally be called
    upon, so they will produce extra energy above what was schedule for the
    timepont. Similarly, if they are providing load-following down,
    they will occasionally be called upon to reduce their output, so will
    produce less energy than 'scheduled' for the timepoint. To account for
    this, the simplest treatment is to multiply the reserve-provision
    variables by a parameter and include that 'energy' in other constraints.
    We create a dictionary of the reserve-provision variables and the
    adjustment parameter name for each reserve-type requested by the user.

    .. note:: Currently, these adjustments are only used in the *variable*
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
            if generator not in list(getattr(d, headroom_or_footroom_dict).keys()):
                getattr(d, headroom_or_footroom_dict)[generator] = list()
            # Some generators get the variables associated with
            # provision of various services (e.g. reserves) if flagged
            # Figure out which these are here based on whether a reserve zone
            # is specified ("." = no zone specified, so project does not
            # contribute to this reserve requirement)
            # The names of the reserve variables for each generator
            if row[find_list_item_position(headers, ba_column_name)[0]] != ".":
                getattr(d, headroom_or_footroom_dict)[generator].append(
                    reserve_provision_variable_name
                )

    # The names of the headroom/footroom derate params for each reserve
    # variable
    # Will be used to get the right derate parameter name for each
    # reserve-provision variable
    # TODO: these de-rates are currently only used in the variable
    #  operational_type and must be added to other operational types
    getattr(d, reserve_variable_derate_params)[
        reserve_provision_variable_name
    ] = reserve_provision_derate_param_name

    # The names of the subhourly energy adjustment params and project
    # balancing area param for each reserve variable (adjustment can vary by
    #  reserve type and by balancing area within each reserve type)
    # Will be used to get the right adjustment for each project providing a
    # particular reserve
    # TODO: these adjustments are currently only applied in the variable
    #  operational_type and must be added to other operational types
    getattr(d, reserve_to_energy_adjustment_params)[reserve_provision_variable_name] = (
        reserve_to_energy_adjustment_param_name,
        reserve_balancing_area_param_name,
    )


def generic_add_model_components(
    m,
    d,
    reserve_projects_set,
    reserve_balancing_area_param,
    reserve_provision_derate_param,
    reserve_balancing_areas_set,
    reserve_project_operational_timepoints_set,
    reserve_provision_variable_name,
    reserve_to_energy_adjustment_param,
):
    """
    :param m:
    :param d:
    :param reserve_projects_set:
    :param reserve_balancing_area_param:
    :param reserve_provision_derate_param:
    :param reserve_balancing_areas_set:
    :param reserve_project_operational_timepoints_set:
    :param reserve_provision_variable_name:
    :param reserve_to_energy_adjustment_param:

    Reserve-related components that will be used by the operational_type
    modules.
    """

    setattr(m, reserve_projects_set, Set(within=m.PROJECTS))
    setattr(
        m,
        reserve_balancing_area_param,
        Param(
            getattr(m, reserve_projects_set),
            within=getattr(m, reserve_balancing_areas_set),
        ),
    )

    setattr(
        m,
        reserve_project_operational_timepoints_set,
        Set(
            dimen=2,
            initialize=lambda mod: subset_init_by_set_membership(
                mod=mod,
                superset="PRJ_OPR_TMPS",
                index=0,
                membership_set=getattr(mod, reserve_projects_set),
            ),
        ),
    )

    setattr(
        m,
        reserve_provision_variable_name,
        Var(
            getattr(m, reserve_project_operational_timepoints_set),
            within=NonNegativeReals,
        ),
    )

    # Headroom/footroom derate -- this is how much extra footroom or
    # headroom must be available in order to provide 1 unit of up or down
    # reserves respectively
    # For example, if the derate is 0.5, the required headroom for providing
    # upward reserves is 1/0.5=2 -- twice the reserve that can be provided
    # Defaults to 1 if not specified
    # This param is used by the operational_type modules
    setattr(
        m,
        reserve_provision_derate_param,
        Param(getattr(m, reserve_projects_set), within=PercentFraction, default=1),
    )

    # Energy adjustment from subhourly reserve provision
    # (e.g. for storage state of charge or how much variable RPS energy is
    # delivered because of subhourly reserve provision)
    # This is an optional param, which will default to 0 if not specified
    # This param is used by the operational_type modules
    setattr(
        m,
        reserve_to_energy_adjustment_param,
        Param(
            getattr(m, reserve_balancing_areas_set), within=PercentFraction, default=0
        ),
    )


def generic_load_model_data(
    m,
    d,
    data_portal,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    ba_column_name,
    derate_column_name,
    reserve_balancing_area_param,
    reserve_provision_derate_param,
    reserve_projects_set,
    reserve_to_energy_adjustment_param,
    reserve_balancing_areas_input_file,
):
    """

    :param m:
    :param d:
    :param data_portal:
    :param scenario_directory:
    :param stage:
    :param stage:
    :param ba_column_name:
    :param derate_column_name:
    :param reserve_balancing_area_param:
    :param reserve_provision_derate_param:
    :param reserve_projects_set:
    :param reserve_to_energy_adjustment_param:
    :param reserve_balancing_areas_input_file:
    :return:
    """

    columns_to_import = (
        "project",
        ba_column_name,
    )
    params_to_import = (getattr(m, reserve_balancing_area_param),)
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
    if derate_column_name in projects_file_header:
        columns_to_import += (derate_column_name,)
        params_to_import += (getattr(m, reserve_provision_derate_param),)

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

    data_portal.data()[reserve_projects_set] = {
        None: list(data_portal.data()[reserve_balancing_area_param].keys())
    }

    # Load reserve provision subhourly energy adjustment (e.g. for storage
    # state of charge adjustment or delivered variable RPS energy adjustment)
    # if specified; otherwise it will default to 0
    ba_file_header = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            reserve_balancing_areas_input_file,
        ),
        sep="\t",
        header=None,
        nrows=1,
    ).values[0]

    if "reserve_to_energy_adjustment" in ba_file_header:
        data_portal.load(
            filename=os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                reserve_balancing_areas_input_file,
            ),
            select=("balancing_area", "reserve_to_energy_adjustment"),
            param=reserve_to_energy_adjustment_param,
        )


def generic_export_results(
    m,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    module_name,
    reserve_project_operational_timepoints_set,
    reserve_provision_variable_name,
    reserve_ba_param_name,
):
    """
    Export project-level reserves results
    :param m:
    :param d:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param module_name:
    :param reserve_project_operational_timepoints_set:
    :param reserve_provision_variable_name:
    :param reserve_ba_param_name:
    :return:
    """

    results_columns = [
        f"{module_name}_ba",
        f"{module_name}_reserve_provision_mw",
    ]

    data = [
        [
            prj,
            tmp,
            getattr(m, reserve_ba_param_name)[prj],
            value(getattr(m, reserve_provision_variable_name)[prj, tmp]),
        ]
        for (prj, tmp) in getattr(m, reserve_project_operational_timepoints_set)
    ]

    results_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PROJECT_TIMEPOINT_DF), results_df)


def generic_get_inputs_from_database(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    reserve_type,
    project_ba_subscenario_id,
    ba_subscenario_id,
):
    """

    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :param reserve_type:
    :param project_ba_subscenario_id:
    :param ba_subscenario_id:
    :return:
    """
    # Get project BA
    c1 = conn.cursor()
    project_bas = c1.execute(
        """
        SELECT project, {}_ba
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get BAs for those projects
        (SELECT project, {}_ba
            FROM inputs_project_{}_bas
            WHERE project_{}_ba_scenario_id = {}
        ) as prj_ba_tbl
        USING (project)
        -- Filter out projects whose BA is not one included in our 
        -- reserve_ba_scenario_id
        WHERE {}_ba in (
                SELECT {}_ba
                    FROM inputs_geography_{}_bas
                    WHERE {}_ba_scenario_id = {}
        );
        """.format(
            reserve_type,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            reserve_type,
            reserve_type,
            reserve_type,
            project_ba_subscenario_id,
            reserve_type,
            reserve_type,
            reserve_type,
            reserve_type,
            ba_subscenario_id,
        )
    )

    # Get headroom/footroom derate
    c2 = conn.cursor()
    project_derates = c2.execute(
        """
        SELECT project, {}_derate
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get derates for those projects
        (SELECT project, {}_derate
            FROM inputs_project_operational_chars
            WHERE project_operational_chars_scenario_id = {}
        ) as prj_derate_tbl
        USING (project);
        """.format(
            reserve_type,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            reserve_type,
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
        )
    )

    return project_bas, project_derates


def generic_validate_project_bas(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    reserve_type,
    project_ba_subscenario_id,
    ba_subscenario_id,
):
    """

    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :param reserve_type:
    :param project_ba_subscenario_id:
    :param ba_subscenario_id:
    :return:
    """

    project_bas, prj_derates = generic_get_inputs_from_database(
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        conn=conn,
        reserve_type=reserve_type,
        project_ba_subscenario_id=project_ba_subscenario_id,
        ba_subscenario_id=ba_subscenario_id,
    )

    # Convert input data into pandas DataFrame
    df = cursor_to_df(project_bas)
    df_derate = cursor_to_df(prj_derates).dropna()
    bas_w_project = df["{}_ba".format(reserve_type)].unique()
    projects_w_ba = df["project"].unique()
    projects_w_derate = df_derate["project"].unique()

    # Get the required reserve bas
    c = conn.cursor()
    bas = c.execute(
        """SELECT {}_ba FROM inputs_geography_{}_bas
        WHERE {}_ba_scenario_id = {}
        """.format(
            reserve_type,
            reserve_type,
            reserve_type,
            subscenarios.REGULATION_UP_BA_SCENARIO_ID,
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
        db_table="inputs_project_{}_bas".format(reserve_type),
        severity="High",
        errors=validate_idxs(
            actual_idxs=bas_w_project,
            req_idxs=bas,
            idx_label="{}_ba".format(reserve_type),
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
