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
The 'project' package contains modules to describe the available
capacity and operational characteristics of generation, storage,
and demand-side infrastructure 'projects' in the optimization problem.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Set, Param, Any, value, NonNegativeReals

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_dtypes,
    get_expected_dtypes,
    validate_values,
    validate_columns,
    validate_missing_inputs,
)
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)

DEFAULT_AVAILABILITY_TYPE = "exogenous"
PROJECT_PERIOD_DF = "project_period_df"
PROJECT_TIMEPOINT_DF = "project_timepoint_df"


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
    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`PROJECTS`                                                      |
    |                                                                         |
    | The list of all projects considered in the optimization problem.        |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Input Params                                                            |
    +=========================================================================+
    | | :code:`load_zone`                                                     |
    | | *Defined over*: :code:`PROJECTS`                                      |
    | | *Within*: :code:`LOAD_ZONES`                                          |
    |                                                                         |
    | This param describes which load zone's load-balance constraint each     |
    | project contributes to.                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`capacity_type`                                                 |
    | | *Defined over*: :code:`PROJECTS`                                      |
    | | *Within*: :code:`["dr_new", "gen_new_bin", "gen_new_lin",`            |
    | | :code:`"gen_ret_bin", "gen_ret_lin", "gen_spec", "stor_new_bin",`     |
    | | :code:`"stor_new_lin", "stor_spec", "fuel_prod_spec", "fuel_prod_new` |
    | | :code:`"energy_spec", "energy_new_lin"]`                              |
    |                                                                         |
    | This param describes each project's capacity type, which determines how |
    | the available capacity of the project is defined (depending on the      |
    | type, it could be a fixed for each period or a decision variable).      |
    +-------------------------------------------------------------------------+
    | | :code:`operational_type`                                              |
    | | *Defined over*: :code:`PROJECTS`                                      |
    | | *Within*: :code:`["dr", "gen_always_on", "gen_commit_bin",`           |
    | | :code:`"gen_commit_cap", "gen_commit_lin", "gen_hydro",`              |
    | | :code:`"gen_hydro_must_take", "gen_must_run", "gen_simple",`          |
    | | :code:`"gen_var", "gen_var_must_take", "stor", "fuel_prod",`          |
    | | :code:`"dispatchable_load", "flex_load",`                             |
    | | :code:`"gen_simple_no_load_balance_power"]`                           |
    |                                                                         |
    | This param describes each project's operational type, which determines  |
    | how the project operates, e.g. whether it is fuel-based dispatchable    |
    | generator, a baseload project, a variable generation project, a storage |
    | project, etc.                                                           |
    +-------------------------------------------------------------------------+
    | | :code:`availability_type`                                             |
    | | *Defined over*: :code:`PROJECTS`                                      |
    | | *Within*: :code:`["binary", "continuous", "exogenous"]`               |
    | | *Default*: :code:`"exogenous"`                                        |
    |                                                                         |
    | This param describes each project's availability type, which determines |
    | how the project availability is determined (exogenously or              |
    | endogenously).                                                          |
    +-------------------------------------------------------------------------+
    | | :code:`balancing_type_project`                                        |
    | | *Defined over*: :code:`PROJECTS`                                      |
    | | *Within*: :code:`BLN_TYPES`                                           |
    |                                                                         |
    | This param describes each project's balancing type, which determines    |
    | how timepoints are grouped in horizons for that project. See            |
    | :code:`horizons` module for more info.                                  |
    +-------------------------------------------------------------------------+
    | | :code:`technology`                                                    |
    | | *Defined over*: :code:`PROJECTS`                                      |
    | | *Within*: :code:`Any`                                                 |
    | | *Default*: :code:`unspecified`                                        |
    |                                                                         |
    | The technology for each project, which is only used for aggregation     |
    | purposes in the results.                                                |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.PROJECTS = Set()

    # Input Params
    ###########################################################################

    m.load_zone = Param(m.PROJECTS, within=m.LOAD_ZONES)
    m.capacity_type = Param(
        m.PROJECTS,
        within=[
            "dr_new",
            "gen_new_bin",
            "gen_new_lin",
            "gen_ret_bin",
            "gen_ret_lin",
            "gen_spec",
            "stor_new_bin",
            "stor_new_lin",
            "stor_spec",
            "gen_stor_hyb_spec",
            "fuel_prod_spec",
            "fuel_prod_new",
            "energy_spec",
            "energy_new_lin",
        ],
    )
    m.operational_type = Param(
        m.PROJECTS,
        within=[
            "dr",
            "gen_always_on",
            "gen_commit_bin",
            "gen_commit_cap",
            "gen_commit_lin",
            "gen_hydro",
            "gen_hydro_must_take",
            "gen_must_run",
            "gen_simple",
            "gen_var",
            "gen_var_must_take",
            "stor",
            "stor_stress_hrz",
            "gen_var_stor_hyb",
            "fuel_prod",
            "dispatchable_load",
            "flex_load",
            "gen_hydro_water",
            "energy_profile",
            "energy_hrz_shaping",
            "energy_load_following",
            "energy_slice_hrz_shaping",
            "load_component_modifier",
            "load_component_shift",
            "gen_simple_no_load_balance_power",
        ],
    )
    m.availability_type = Param(
        m.PROJECTS,
        within=["binary", "continuous", "exogenous"],
        default=DEFAULT_AVAILABILITY_TYPE,
    )
    m.balancing_type_project = Param(m.PROJECTS, within=m.BLN_TYPES)
    m.technology = Param(m.PROJECTS, within=Any, default="unspecified")
    # TODO: considering technology is only used on the results side, should we
    # keep it here?

    m.load_modifier_flag = Param(m.PROJECTS, within=[0, 1], default=0)
    m.distribution_loss_adjustment_factor = Param(
        m.PROJECTS, within=NonNegativeReals, default=0
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
    """ """
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
        index=m.PROJECTS,
        select=(
            "project",
            "load_zone",
            "capacity_type",
            "availability_type",
            "operational_type",
            "balancing_type_project",
            "load_modifier_flag",
            "distribution_loss_adjustment_factor",
        ),
        param=(
            m.load_zone,
            m.capacity_type,
            m.availability_type,
            m.operational_type,
            m.balancing_type_project,
            m.load_modifier_flag,
            m.distribution_loss_adjustment_factor,
        ),
    )

    # Technology column is optional (default param value is 'unspecified')
    header = pd.read_csv(
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

    if "technology" in header:
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
            select=("project", "technology"),
            param=m.technology,
        )


# Input-Output
###############################################################################


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
    Export operations results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    The Pyomo abstract model
    :param d:
    Dynamic components
    :return:
    Nothing
    """

    # First create the results dataframes
    # Other modules will update these dataframe with actual results
    # The results dataframes are by index

    # Project-period DF
    project_period_df = pd.DataFrame(
        columns=[
            "project",
            "period",
            "capacity_type",
            "availability_type",
            "operational_type",
            "technology",
            "load_modifier_flag",
            "distribution_loss_adjustment_factor",
            "load_zone",
        ],
        data=[
            [
                prj,
                prd,
                m.capacity_type[prj],
                m.availability_type[prj],
                m.operational_type[prj],
                m.technology[prj],
                m.load_modifier_flag[prj],
                m.distribution_loss_adjustment_factor[prj],
                m.load_zone[prj],
            ]
            for (prj, prd) in sorted(list(set(m.PRJ_OPR_PRDS | m.PRJ_FIN_PRDS)))
        ],
    ).set_index(["project", "period"])

    project_period_df.sort_index(inplace=True)

    # Add the dataframe to the dynamic components to pass to other modules
    setattr(d, PROJECT_PERIOD_DF, project_period_df)

    # Project-timepoint DF
    project_timepoint_df = pd.DataFrame(
        columns=[
            "project",
            "timepoint",
            "period",
            "horizon",
            "capacity_type",
            "availability_type",
            "operational_type",
            "balancing_type",
            "timepoint_weight",
            "number_of_hours_in_timepoint",
            "load_zone",
            "technology",
            "load_modifier_flag",
            "distribution_loss_adjustment_factor",
            "capacity_mw",
        ],
        data=[
            [
                prj,
                tmp,
                m.period[tmp],
                (
                    m.horizon[tmp, m.balancing_type_project[prj]]
                    if (tmp, m.balancing_type_project[prj]) in m.TMPS_BLN_TYPES
                    else None
                ),
                m.capacity_type[prj],
                m.availability_type[prj],
                m.operational_type[prj],
                m.balancing_type_project[prj],
                m.tmp_weight[tmp],
                m.hrs_in_tmp[tmp],
                m.load_zone[prj],
                m.technology[prj],
                m.load_modifier_flag[prj],
                m.distribution_loss_adjustment_factor[prj],
                value(m.Capacity_MW[prj, m.period[tmp]]),
            ]
            for (prj, tmp) in m.PRJ_OPR_TMPS
        ],
    ).set_index(["project", "timepoint"])

    project_timepoint_df.sort_index(inplace=True)

    # Add the dataframe to the dynamic components to pass to other modules
    setattr(d, PROJECT_TIMEPOINT_DF, project_timepoint_df)


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

    projects = c.execute(
        f"""SELECT project, capacity_type, availability_type, operational_type, 
        balancing_type_project, load_modifier_flag, distribution_loss_adjustment_factor, 
        technology, load_zone
        FROM
        -- Get only the subset of projects in the portfolio with their 
        -- capacity types based on the project_portfolio_scenario_id 
        (SELECT project, capacity_type
        FROM inputs_project_portfolios
        WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}) as portfolio_tbl
        -- Get the load_zones for these projects depending on the
        -- project_load_zone_scenario_id
        LEFT OUTER JOIN
        (SELECT project, load_zone
        FROM inputs_project_load_zones
        WHERE project_load_zone_scenario_id = {subscenarios.PROJECT_LOAD_ZONE_SCENARIO_ID}) as prj_load_zones
        USING (project)
        LEFT OUTER JOIN
        -- Get the availability types for these projects depending on the
        -- project_availability_scenario_id
        (SELECT project, availability_type
        FROM inputs_project_availability
        WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}) as prj_av_types
        USING (project)
        LEFT OUTER JOIN
        -- Get the operational type, balancing_type, technology, 
        -- and variable cost for these projects depending ont the 
        -- project_operational_chars_scenario_id
        (SELECT project, operational_type, balancing_type_project, 
        load_modifier_flag, distribution_loss_adjustment_factor, technology
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}) as prj_chars
        USING (project)
        ;"""
    )

    return projects


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
    projects.tab file.
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

    projects = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="projects.tab",
        data=projects,
        replace_nulls=True,
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

    c = conn.cursor()

    # Get the project inputs
    projects = get_inputs_from_database(
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
    df = cursor_to_df(projects)

    # Check data types:
    expected_dtypes = get_expected_dtypes(
        conn,
        [
            "inputs_project_portfolios",
            "inputs_project_availability",
            "inputs_project_load_zones",
            "inputs_project_operational_chars",
        ],
    )

    dtype_errors, error_columns = validate_dtypes(df, expected_dtypes)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_operational_chars, inputs_project_portfolios",
        severity="High",
        errors=dtype_errors,
    )

    # Check valid numeric columns are non-negative
    numeric_columns = [c for c in df.columns if expected_dtypes[c] == "numeric"]
    valid_numeric_columns = set(numeric_columns) - set(error_columns)

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
        severity="High",
        errors=validate_values(df, valid_numeric_columns, min=0),
    )

    # Check that we're not combining incompatible cap-types and op-types
    cols = ["capacity_type", "operational_type"]
    invalid_combos = c.execute("""
        SELECT {} FROM mod_capacity_and_operational_type_invalid_combos
        """.format(",".join(cols))).fetchall()

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_operational_chars, inputs_project_portfolios",
        severity="High",
        errors=validate_columns(df, cols, invalids=invalid_combos),
    )

    # Check that capacity type is valid
    # Note: foreign key already ensures this!
    valid_cap_types = c.execute(
        """SELECT capacity_type from mod_capacity_types"""
    ).fetchall()
    valid_cap_types = [v[0] for v in valid_cap_types]

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_portfolios",
        severity="High",
        errors=validate_columns(df, "capacity_type", valids=valid_cap_types),
    )

    # Check that operational type is valid
    # Note: foreign key already ensures this!
    valid_op_types = c.execute(
        """SELECT operational_type from mod_operational_types"""
    ).fetchall()
    valid_op_types = [v[0] for v in valid_op_types]

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_portfolios",
        severity="High",
        errors=validate_columns(df, "operational_type", valids=valid_op_types),
    )

    # Check that all portfolio projects are present in the opchar inputs
    msg = (
        "All projects in the portfolio should have an operational type "
        "and balancing type specified in the "
        "inputs_project_operational_chars table."
    )
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
        severity="High",
        errors=validate_missing_inputs(
            df, ["operational_type", "balancing_type_project"], msg=msg
        ),
    )

    # Check that all portfolio projects are present in the load zone inputs
    msg = (
        "All projects in the portfolio should have a load zone "
        "specified in the inputs_project_load_zones table."
    )
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_load_zones",
        severity="High",
        errors=validate_missing_inputs(df, "load_zone", msg=msg),
    )
