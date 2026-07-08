# Copyright 2016-2024 Blue Marble Analytics LLC.
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
For each project assigned this *availability type*, the user may specify an
(un)availability schedule, i.e. a capacity derate for each timepoint in
which the project may be operated. If fully derated in a given timepoint,
the available project capacity will be 0 in that timepoint and all
operational decision variables will therefore also be constrained to 0 in the
optimization.

"""

import csv
import os.path
from pyomo.environ import Param, Set, NonNegativeReals

from gridpath.auxiliary.auxiliary import cursor_to_df, subset_init_by_set_membership
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    get_expected_dtypes,
    validate_dtypes,
    validate_values,
    validate_missing_inputs,
)
from gridpath.project.common_functions import (
    determine_project_subset,
)
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)

# The exogenous derates are fixed input data, so the availability
# derate is a constant in the model
DERATE_IS_CONSTANT = True


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
    | | :code:`AVL_EXOG`                                                      |
    |                                                                         |
    | The set of projects of the :code:`exogenous` availability type.         |
    +-------------------------------------------------------------------------+
    | | :code:`AVL_EXOG_OPR_TMPS`                                             |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`exogenous`              |
    | availability type and their operational timepoints.                     |
    +-------------------------------------------------------------------------+


    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`avl_exog_cap_derate_independent`                               |
    | | *Defined over*: :code:`AVL_EXOG_OPR_TMPS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The pre-specified availability derate (e.g. for maintenance/planned     |
    | outages) that does not depend on weather. Defaults to 1 if not          |
    | specified. Availaibility can also be more than 1.                       |
    +-------------------------------------------------------------------------+
    | | :code:`avl_exog_cap_derate_weather`                                   |
    | | *Defined over*: :code:`AVL_EXOG_OPR_TMPS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The pre-specified availability derate (e.g. for maintenance/planned     |
    | outages) that depends on weather. Defaults to 1 if not specified.       |
    | Availaibility can also be more than 1.                                  |
    +-------------------------------------------------------------------------+
    | | :code:`avl_exog_mnth_derate`                                          |
    | | *Defined over*: :code:`AVL_EXOG, MONTHS`                              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | Availabilty derate that varies by month.                                |
    +-------------------------------------------------------------------------+


    """

    # Sets
    ###########################################################################

    m.AVL_EXOG = Set(within=m.PROJECTS)

    m.AVL_EXOG_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.AVL_EXOG
        ),
    )

    m.AVL_EXOG_PRJ_BT_HRZ_W_WEATHER_DERATES = Set(
        dimen=3, within=m.PROJECTS * m.BLN_TYPE_HRZS
    )

    m.AVL_EXOG_PRJ_BT_HRZ_W_INDEPENDENT_DERATES = Set(
        dimen=3, within=m.PROJECTS * m.BLN_TYPE_HRZS
    )

    # Optional Params
    ###########################################################################

    # For hybrids, this is the derate applied to the generator component
    m.avl_exog_cap_derate_independent = Param(
        m.AVL_EXOG_OPR_TMPS, within=NonNegativeReals, default=1
    )

    m.avl_exog_cap_derate_weather = Param(
        m.AVL_EXOG_OPR_TMPS, within=NonNegativeReals, default=1
    )

    m.avl_exog_hyb_stor_cap_derate_independent = Param(
        m.AVL_EXOG_OPR_TMPS, within=NonNegativeReals, default=1
    )

    m.avl_exog_cap_derate_weather_bt_hrz = Param(
        m.AVL_EXOG_PRJ_BT_HRZ_W_WEATHER_DERATES, within=NonNegativeReals, default=1
    )

    m.avl_exog_cap_derate_independent_bt_hrz = Param(
        m.AVL_EXOG_PRJ_BT_HRZ_W_INDEPENDENT_DERATES, within=NonNegativeReals, default=1
    )

    m.avl_exog_mnth_derate = Param(
        m.AVL_EXOG, m.MONTHS, within=NonNegativeReals, default=1
    )

    # Make timepoint params from the bt-hrz params
    # Note that if timepoints fall within multiple bt-hrz with derates,
    # the derates will be additive
    def hrz_cap_derate_weather_by_tmp_init(mod):
        """
        Note that if timepoints fall within multiple bt-hrz with derates,
        the bt-hrz derates will be additive.
        """
        availability_reduction_dict = {}
        for prj, bt, hrz in mod.AVL_EXOG_PRJ_BT_HRZ_W_WEATHER_DERATES:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (prj, tmp) not in availability_reduction_dict.keys():
                    availability_reduction_dict[(prj, tmp)] = (
                        1 - mod.avl_exog_cap_derate_weather_bt_hrz[prj, bt, hrz]
                    )
                else:
                    availability_reduction_dict[(prj, tmp)] += (
                        1 - mod.avl_exog_cap_derate_weather_bt_hrz[prj, bt, hrz]
                    )

        availability_dict = {
            (prj, tmp): 1 - availability_reduction_dict[(prj, tmp)]
            for (prj, tmp) in availability_reduction_dict.keys()
        }

        return availability_dict

    m.avl_exog_cap_derate_weather_bt_hrz_by_tmp = Param(
        m.AVL_EXOG_OPR_TMPS,
        within=NonNegativeReals,
        initialize=hrz_cap_derate_weather_by_tmp_init,
        default=1,
    )

    def hrz_cap_derate_independent_by_tmp_init(mod):
        """
        Note that if timepoints fall within multiple bt-hrz with derates,
        the bt-hrz derates will be additive.
        """
        availability_reduction_dict = {}
        for prj, bt, hrz in mod.AVL_EXOG_PRJ_BT_HRZ_W_INDEPENDENT_DERATES:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (prj, tmp) not in availability_reduction_dict.keys():
                    availability_reduction_dict[(prj, tmp)] = (
                        1 - mod.avl_exog_cap_derate_independent_bt_hrz[prj, bt, hrz]
                    )
                else:
                    availability_reduction_dict[(prj, tmp)] += (
                        1 - mod.avl_exog_cap_derate_independent_bt_hrz[prj, bt, hrz]
                    )

        availability_dict = {
            (prj, tmp): 1 - availability_reduction_dict[(prj, tmp)]
            for (prj, tmp) in availability_reduction_dict.keys()
        }

        return availability_dict

    m.avl_exog_cap_derate_independent_bt_hrz_by_tmp = Param(
        m.AVL_EXOG_OPR_TMPS,
        within=NonNegativeReals,
        initialize=hrz_cap_derate_independent_by_tmp_init,
        default=1,
    )


# Availability Type Methods
###############################################################################


_TMP_INDEXED_CAP_DERATE_PARAMS = [
    "avl_exog_cap_derate_independent",
    "avl_exog_cap_derate_weather",
    "avl_exog_cap_derate_weather_bt_hrz_by_tmp",
    "avl_exog_cap_derate_independent_bt_hrz_by_tmp",
]


def _active_cap_derate_params(mod):
    """
    Derate factor params with no loaded data are 1 (their default)
    everywhere, so they can be skipped in the per-timepoint product for the
    overall derate below in order to speed things up. Figure out which params
    are active here.
    """
    # Check if we already figured out the active params; returns None if not
    active = getattr(mod, "_avl_exog_active_cap_derate_params", None)
    # If we don't have the active params, figure it out
    if active is None:
        active = (
            # Are the per timepoint params active
            [
                getattr(mod, p)
                for p in _TMP_INDEXED_CAP_DERATE_PARAMS
                if len(getattr(mod, p).sparse_keys()) > 0
            ],
            # Is the monthly param active
            len(mod.avl_exog_mnth_derate.sparse_keys()) > 0,
        )
        mod._avl_exog_active_cap_derate_params = active
    return active


def availability_derate_cap_rule(mod, g, tmp):
    """
    The final availability is the product of all derates applied.

    derate =
        mod.avl_exog_cap_derate_independent[g, tmp]
        * mod.avl_exog_cap_derate_weather[g, tmp]
        * mod.avl_exog_cap_derate_weather_bt_hrz_by_tmp[g, tmp]
        * mod.avl_exog_cap_derate_independent_bt_hrz_by_tmp[g, tmp]
        * mod.avl_exog_mnth_derate[g, mod.month[tmp]]


    """
    tmp_indexed_params, mnth_derate_active = _active_cap_derate_params(mod)

    derate = 1
    for param in tmp_indexed_params:
        derate = derate * param[g, tmp]
    if mnth_derate_active:
        derate = derate * mod.avl_exog_mnth_derate[g, mod.month[tmp]]

    return derate


def availability_derate_hyb_stor_cap_rule(mod, g, tmp):
    """ """
    return mod.avl_exog_hyb_stor_cap_derate_independent[g, tmp]


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
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """
    # Figure out which projects have this availability type
    # Check the 'exogenous' is the default availability type
    from gridpath.project import DEFAULT_AVAILABILITY_TYPE

    if DEFAULT_AVAILABILITY_TYPE != "exogenous":
        raise Exception(
            "The exogenous availability type must be the default."
            "The 'exogenous' availabilty type assumes this in determing inputs."
        )

    project_subset = determine_project_subset(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        column="availability_type",
        type="exogenous",
        prj_or_tx="project",
    ) + determine_project_subset(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        column="availability_type",
        type=".",  # Projects without availabilty type specified default to
        # exogenous
        prj_or_tx="project",
    )

    data_portal.data()["AVL_EXOG"] = {None: project_subset}

    # Availability derates
    # Get any derates from the project_availability.tab file if it exists;
    # if it does not exist, all projects will get 1 as derate; if it does
    # exist but projects are not specified in it, they will also get 1
    # assigned as their derate
    # The test examples do not currently have a
    # project_availability_exogenous_x.tab, but use the default instead

    input_directory = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
    )

    availability_independent_file = os.path.join(
        input_directory,
        "project_availability_exogenous_independent.tab",
    )

    if os.path.exists(availability_independent_file):
        data_portal.load(
            filename=availability_independent_file,
            param=(
                m.avl_exog_cap_derate_independent,
                m.avl_exog_hyb_stor_cap_derate_independent,
            ),
        )

    availability_weather_file = os.path.join(
        input_directory,
        "project_availability_exogenous_weather.tab",
    )

    if os.path.exists(availability_weather_file):
        data_portal.load(
            filename=availability_weather_file,
            param=m.avl_exog_cap_derate_weather,
        )

    # Balancing type - horizon inputs
    availability_independent_bt_hrz_file = os.path.join(
        input_directory,
        "project_availability_exogenous_independent_bt_hrz.tab",
    )

    if os.path.exists(availability_independent_bt_hrz_file):
        data_portal.load(
            filename=availability_independent_bt_hrz_file,
            index=m.AVL_EXOG_PRJ_BT_HRZ_W_INDEPENDENT_DERATES,
            param=m.avl_exog_cap_derate_independent_bt_hrz,
        )

    availability_weather_bt_hrz_file = os.path.join(
        input_directory,
        "project_availability_exogenous_weather_bt_hrz.tab",
    )

    if os.path.exists(availability_weather_bt_hrz_file):
        data_portal.load(
            filename=availability_weather_bt_hrz_file,
            index=m.AVL_EXOG_PRJ_BT_HRZ_W_WEATHER_DERATES,
            param=m.avl_exog_cap_derate_weather_bt_hrz,
        )

    monthly_av_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "project_availability_exogenous_monthly.tab",
    )

    if os.path.exists(monthly_av_file):
        data_portal.load(filename=monthly_av_file, param=m.avl_exog_mnth_derate)


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
    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :return:
    """

    # Derate by timepoint
    ind_sql = f"""
        SELECT project, timepoint, availability_derate_independent, 
        hyb_stor_cap_availability_derate_independent
        FROM inputs_project_availability_exogenous_independent
        -- Portfolio projects only
        WHERE project IN (
            SELECT project FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        )
        -- Projects from this availability ID and type only
        AND project IN (
            SELECT project
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
            AND availability_type = 'exogenous'
            AND exogenous_availability_independent_scenario_id IS NOT NULL
        )
        -- Relevant optype opchar ID
        AND (project, exogenous_availability_independent_scenario_id) IN (
            SELECT project, exogenous_availability_independent_scenario_id
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
        )
        -- Relevant temporal index
        AND timepoint IN (
            SELECT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
        )
        -- Get the correct availability iteration
        AND availability_iteration = {availability_iteration}
        ;
    """

    c1 = conn.cursor()
    independent_availabilities = c1.execute(ind_sql)

    # Derate by timepoint and weather
    weather_sql = f"""
        SELECT project, timepoint, availability_derate_weather
        FROM inputs_project_availability_exogenous_weather
        -- Portfolio projects only
        WHERE project IN (
            SELECT project FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        )
        -- Projects from this availability ID and type only
        AND project IN (
            SELECT project
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
            AND availability_type = 'exogenous'
            AND exogenous_availability_weather_scenario_id IS NOT NULL
        )
        -- Relevant optype opchar ID
        AND (project, exogenous_availability_weather_scenario_id) IN (
            SELECT project, exogenous_availability_weather_scenario_id
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
        )
        -- Relevant temporal index
        AND timepoint IN (
            SELECT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
        )
        -- Get the correct weather iteration
        AND weather_iteration = {weather_iteration}
        ;
    """

    c2 = conn.cursor()
    weather_availabilities = c2.execute(weather_sql)

    # Derate by balancing type - horizon
    bt_hrz_ind_sql = f"""
        SELECT project, balancing_type_project, horizon, availability_derate_independent_bt_hrz
        FROM inputs_project_availability_exogenous_independent_bt_hrz
        -- Portfolio projects only
        WHERE project IN (
            SELECT project FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        )
        -- Projects from this availability ID and type only
        AND project IN (
            SELECT project
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
            AND availability_type = 'exogenous'
            AND exogenous_availability_independent_bt_hrz_scenario_id IS NOT NULL
        )
        -- Relevant optype opchar ID
        AND (project, exogenous_availability_independent_bt_hrz_scenario_id) IN (
            SELECT project, exogenous_availability_independent_bt_hrz_scenario_id
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
        )
        -- Relevant temporal index
        AND (balancing_type_project, horizon) IN (
            SELECT balancing_type_horizon, horizon
            FROM inputs_temporal_horizon_timepoints
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
        )
        -- Get the correct availability iteration
        AND availability_iteration = {availability_iteration}
        ;
    """

    c3 = conn.cursor()
    bt_hrz_independent_availabilities = c3.execute(bt_hrz_ind_sql)

    # Derate by timepoint and weather
    bt_hrz_weather_sql = f"""
        SELECT project, balancing_type_project, horizon, 
        availability_derate_weather_bt_hrz
        FROM inputs_project_availability_exogenous_weather_bt_hrz
        -- Portfolio projects only
        WHERE project IN (
            SELECT project FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        )
        -- Projects from this availability ID and type only
        AND project IN (
            SELECT project
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
            AND availability_type = 'exogenous'
            AND exogenous_availability_weather_bt_hrz_scenario_id IS NOT NULL
        )
        -- Relevant optype opchar ID
        AND (project, exogenous_availability_weather_bt_hrz_scenario_id) IN (
            SELECT project, exogenous_availability_weather_bt_hrz_scenario_id
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
        )
        -- Relevant temporal index
        AND (balancing_type_project, horizon) IN (
            SELECT balancing_type_horizon, horizon
            FROM inputs_temporal_horizon_timepoints
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
        )
        -- Get the correct weather iteration
        AND weather_iteration = {weather_iteration}
        ;
    """

    c4 = conn.cursor()
    bt_hrz_weather_availabilities = c4.execute(bt_hrz_weather_sql)

    # Simple monthly derates
    mnth_sql = f"""
            SELECT project, month, availability_derate_monthly
            FROM inputs_project_availability_exogenous_monthly
            -- Portfolio projects only
            WHERE project IN (
                SELECT project FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )
            -- Projects from this availability ID and type only
            AND project IN (
                SELECT project
                FROM inputs_project_availability
                WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
                AND availability_type = 'exogenous'
                AND exogenous_availability_monthly_scenario_id IS NOT NULL
            )
            -- Relevant optype opchar ID
            AND (project, exogenous_availability_monthly_scenario_id) IN (
                SELECT project, exogenous_availability_monthly_scenario_id
                FROM inputs_project_availability
                WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
            )
            -- Relevant temporal index
            AND month IN (
            SELECT month
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
        )
            ;
        """

    c5 = conn.cursor()
    monthly_availabilities = c5.execute(mnth_sql)

    return (
        independent_availabilities,
        weather_availabilities,
        bt_hrz_independent_availabilities,
        bt_hrz_weather_availabilities,
        monthly_availabilities,
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
    :param scenario_directory:
    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
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

    (
        independent_availabilities,
        weather_availabilities,
        independent_availabilities_bt_hrz,
        weather_availabilities_bt_hrz,
        monthly_availabilities,
    ) = get_inputs_from_database(
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
        fname="project_availability_exogenous_weather.tab",
        data=weather_availabilities,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="project_availability_exogenous_independent.tab",
        data=independent_availabilities,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="project_availability_exogenous_weather.tab",
        data=weather_availabilities,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="project_availability_exogenous_independent_bt_hrz.tab",
        data=independent_availabilities_bt_hrz,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="project_availability_exogenous_weather_bt_hrz.tab",
        data=weather_availabilities_bt_hrz,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="project_availability_exogenous_monthly.tab",
        data=monthly_availabilities,
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
    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :return:
    """
    (
        independent_availabilities,
        weather_availabilities,
        independent_availabilities_bt_hrz,
        weather_availabilities_bt_hrz,
        monthly_availabilities,
    ) = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    df = cursor_to_df(independent_availabilities)
    idx_cols = ["project", "timepoint"]
    value_cols = ["availability_derate_independent"]

    # Check data types availability
    expected_dtypes = get_expected_dtypes(
        conn,
        [
            "inputs_project_availability",
            "inputs_project_availability_exogenous_independent",
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
        db_table="inputs_project_availability_exogenous_independent",
        severity="High",
        errors=dtype_errors,
    )

    # Check for missing inputs
    msg = (
        "If not specified, availability is assumed to be 100%. If you "
        "don't want to specify any availability derates, simply leave the "
        "exogenous_availability_scenario_id empty and this message will "
        "disappear."
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
        db_table="inputs_project_availability_exogenous_independent",
        severity="Low",
        errors=validate_missing_inputs(df, value_cols, idx_cols, msg),
    )

    # Check for correct sign
    if "availability" not in error_columns:
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_project_availability_exogenous_independent",
            severity="High",
            errors=validate_values(df, value_cols, min=0, max=1),
        )
