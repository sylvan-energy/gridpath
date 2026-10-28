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

A project-level :code:`default_exogenous_availability` (in the
:code:`inputs_project_availability` table) replaces 1 as the outage
timepoint derate wherever the project has no timepoint-level outage
derate, so a single value can apply to all timepoints; the other derates
(weather, balancing type - horizon, monthly) still multiply it. It does not
apply to the hybrid storage capacity derate.

"""

import csv
import os.path
from pyomo.environ import Param, Set, SetOf, NonNegativeReals

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    get_required_subtype_modules,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.calendar_rows import (
    calendar_index_cte_sql,
    calendar_rows_sql,
)
from gridpath.auxiliary.validations import (
    warn_on_unknown_balancing_types,
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

DEFAULT_DERATE_FILENAME = "project_availability_exogenous_default.tab"


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
    | | :code:`avl_exog_cap_derate_outage`                                    |
    | | *Defined over*: :code:`AVL_EXOG_OPR_TMPS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The availability derate from planned or forced outages (an outage       |
    | timeline) of the availability iteration; in the database, a project's   |
    | rows can also be keyed by the weather iteration (e.g. outages drawn     |
    | against weather-dependent forced outage rates). Defaults                |
    | to the project's :code:`avl_exog_default_cap_derate` if not specified.  |
    | Availaibility can also be more than 1.                                  |
    +-------------------------------------------------------------------------+
    | | :code:`avl_exog_default_cap_derate`                                   |
    | | *Defined over*: :code:`AVL_EXOG`                                      |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's outage derate in the timepoints                           |
    | without a timepoint-level :code:`avl_exog_cap_derate_outage`.           |
    +-------------------------------------------------------------------------+
    | | :code:`avl_exog_cap_derate_weather`                                   |
    | | *Defined over*: :code:`AVL_EXOG_OPR_TMPS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The availability derate that follows the weather, e.g. reduced          |
    | capability at high ambient temperature. Defaults to 1 if not specified. |
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

    # If every project is of the exogenous availability type (the type is
    # also the default for projects with no type specified), then
    # AVL_EXOG_OPR_TMPS would equal PRJ_OPR_TMPS, so make it a zero-copy
    # view of PRJ_OPR_TMPS instead of a filtered copy; at production scale
    # the copy is tens of millions of elements
    availability_types_in_use = set(
        get_required_subtype_modules(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            which_type="availability_type",
        )
    )

    if availability_types_in_use <= {"exogenous", "."}:
        m.AVL_EXOG_OPR_TMPS = SetOf(m.PRJ_OPR_TMPS)
    else:
        m.AVL_EXOG_OPR_TMPS = Set(
            dimen=2,
            initialize=lambda mod: subset_init_by_set_membership(
                mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.AVL_EXOG
            ),
        )

    m.AVL_EXOG_PRJ_BT_HRZ_W_WEATHER_DERATES = Set(
        dimen=3, within=m.PROJECTS * m.BLN_TYPE_HRZS
    )

    m.AVL_EXOG_PRJ_BT_HRZ_W_OUTAGE_DERATES = Set(
        dimen=3, within=m.PROJECTS * m.BLN_TYPE_HRZS
    )

    # Optional Params
    ###########################################################################

    m.avl_exog_default_cap_derate = Param(
        m.AVL_EXOG, within=NonNegativeReals, default=1
    )

    # For hybrids, this is the derate applied to the generator component
    # The default is replaced with the project defaults in load_model_data
    # if any are specified
    m.avl_exog_cap_derate_outage = Param(
        m.AVL_EXOG_OPR_TMPS, within=NonNegativeReals, default=1
    )

    m.avl_exog_cap_derate_weather = Param(
        m.AVL_EXOG_OPR_TMPS, within=NonNegativeReals, default=1
    )

    m.avl_exog_hyb_stor_cap_derate_outage = Param(
        m.AVL_EXOG_OPR_TMPS, within=NonNegativeReals, default=1
    )

    m.avl_exog_cap_derate_weather_bt_hrz = Param(
        m.AVL_EXOG_PRJ_BT_HRZ_W_WEATHER_DERATES, within=NonNegativeReals, default=1
    )

    m.avl_exog_cap_derate_outage_bt_hrz = Param(
        m.AVL_EXOG_PRJ_BT_HRZ_W_OUTAGE_DERATES, within=NonNegativeReals, default=1
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

    def hrz_cap_derate_outage_by_tmp_init(mod):
        """
        Note that if timepoints fall within multiple bt-hrz with derates,
        the bt-hrz derates will be additive.
        """
        availability_reduction_dict = {}
        for prj, bt, hrz in mod.AVL_EXOG_PRJ_BT_HRZ_W_OUTAGE_DERATES:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (prj, tmp) not in availability_reduction_dict.keys():
                    availability_reduction_dict[(prj, tmp)] = (
                        1 - mod.avl_exog_cap_derate_outage_bt_hrz[prj, bt, hrz]
                    )
                else:
                    availability_reduction_dict[(prj, tmp)] += (
                        1 - mod.avl_exog_cap_derate_outage_bt_hrz[prj, bt, hrz]
                    )

        availability_dict = {
            (prj, tmp): 1 - availability_reduction_dict[(prj, tmp)]
            for (prj, tmp) in availability_reduction_dict.keys()
        }

        return availability_dict

    m.avl_exog_cap_derate_outage_bt_hrz_by_tmp = Param(
        m.AVL_EXOG_OPR_TMPS,
        within=NonNegativeReals,
        initialize=hrz_cap_derate_outage_by_tmp_init,
        default=1,
    )


# Availability Type Methods
###############################################################################


_TMP_INDEXED_CAP_DERATE_PARAMS = [
    "avl_exog_cap_derate_outage",
    "avl_exog_cap_derate_weather",
    "avl_exog_cap_derate_weather_bt_hrz_by_tmp",
    "avl_exog_cap_derate_outage_bt_hrz_by_tmp",
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
        # Note: sparse_keys() returns a lazy iterator as of Pyomo 6.10, so
        # test for loaded values with any() rather than len()
        active = (
            # Are the per timepoint params active
            [
                getattr(mod, p)
                for p in _TMP_INDEXED_CAP_DERATE_PARAMS
                if any(True for _ in getattr(mod, p).sparse_keys())
                # The outage derate defaults to the project defaults
                or (
                    p == "avl_exog_cap_derate_outage"
                    and any(True for _ in mod.avl_exog_default_cap_derate.sparse_keys())
                )
            ],
            # Is the monthly param active
            any(True for _ in mod.avl_exog_mnth_derate.sparse_keys()),
        )
        mod._avl_exog_active_cap_derate_params = active
    return active


def availability_derate_cap_rule(mod, g, tmp):
    """
    The final availability is the product of all derates applied.

    derate =
        mod.avl_exog_cap_derate_outage[g, tmp]
        * mod.avl_exog_cap_derate_weather[g, tmp]
        * mod.avl_exog_cap_derate_weather_bt_hrz_by_tmp[g, tmp]
        * mod.avl_exog_cap_derate_outage_bt_hrz_by_tmp[g, tmp]
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
    return mod.avl_exog_hyb_stor_cap_derate_outage[g, tmp]


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

    availability_outage_file = os.path.join(
        input_directory,
        "project_availability_exogenous_outage.tab",
    )

    if os.path.exists(availability_outage_file):
        data_portal.load(
            filename=availability_outage_file,
            param=(
                m.avl_exog_cap_derate_outage,
                m.avl_exog_hyb_stor_cap_derate_outage,
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
    availability_outage_bt_hrz_file = os.path.join(
        input_directory,
        "project_availability_exogenous_outage_bt_hrz.tab",
    )

    if os.path.exists(availability_outage_bt_hrz_file):
        data_portal.load(
            filename=availability_outage_bt_hrz_file,
            index=m.AVL_EXOG_PRJ_BT_HRZ_W_OUTAGE_DERATES,
            param=m.avl_exog_cap_derate_outage_bt_hrz,
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

    default_derate_file = os.path.join(input_directory, DEFAULT_DERATE_FILENAME)

    # Only fall back to the project defaults when there are any: a function
    # default is called (and domain-checked) on every access, so keep the
    # constant default otherwise
    if os.path.exists(default_derate_file):
        data_portal.load(
            filename=default_derate_file, param=m.avl_exog_default_cap_derate
        )
        m.avl_exog_cap_derate_outage.set_default(
            lambda mod, prj, tmp: mod.avl_exog_default_cap_derate[prj]
        )


# Database
###############################################################################


def get_outage_iteration_config_sql(subscenarios):
    """
    :return: SQL selecting (project, exogenous_availability_outage_scenario_id,
        varies_by_weather_iteration) for the portfolio's
        exogenous-availability projects with an outage derate subscenario

    Whether a project's outage derates vary by weather iteration comes from
    inputs_project_availability_exogenous_outage_iterations; a project
    without a row does not, i.e. its rows sit at weather_iteration 0.
    """
    return f"""
        SELECT av.project,
        av.exogenous_availability_outage_scenario_id,
        COALESCE(it.varies_by_weather_iteration, 0)
            AS varies_by_weather_iteration
        FROM inputs_project_availability AS av
        LEFT JOIN inputs_project_availability_exogenous_outage_iterations
            AS it
        USING (project, exogenous_availability_outage_scenario_id)
        WHERE av.project_availability_scenario_id
            = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
        AND av.availability_type = 'exogenous'
        AND av.exogenous_availability_outage_scenario_id IS NOT NULL
        -- Portfolio projects only
        AND av.project IN (
            SELECT project FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id
                = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        )
    """


def check_outage_iteration_config(subscenarios, weather_iteration, conn):
    """
    Raise if a project's outage derates vary by weather iteration but the
    run has none (weather_iteration 0), the same guard the operational
    characteristics iteration inputs apply.
    """
    if weather_iteration != 0:
        return

    offending = [prj for (prj,) in conn.execute(f"""
        SELECT project
        FROM ({get_outage_iteration_config_sql(subscenarios)})
        WHERE varies_by_weather_iteration
        ORDER BY project
        ;""").fetchall()]
    if offending:
        raise ValueError(
            f"The outage derates of projects {offending} vary by weather "
            f"iteration but the run has weather_iteration=0. Projects should "
            f"not vary by weather iteration when the scenario has none."
        )


def get_unread_outage_rows(subscenarios, conn):
    """
    :return: list of (project, weather_iteration) of outage derate rows at
        a non-zero weather iteration of projects whose derates are not
        flagged to vary by it; such rows are never read
    """
    # cfg must be the outer loop (CROSS JOIN fixes SQLite's join order, see
    # get_outage_derate_sql) so only the unflagged projects' rows are
    # searched; weather_iteration > 0 and < 0 are separate index ranges
    # (SQLite searches "!= 0" by scanning all the project's rows)
    return conn.execute(
        "\nUNION\n".join(f"""
        SELECT project, weather_iteration
        FROM ({get_outage_iteration_config_sql(subscenarios)}) AS cfg
        CROSS JOIN inputs_project_availability_exogenous_outage
        USING (project, exogenous_availability_outage_scenario_id)
        WHERE NOT cfg.varies_by_weather_iteration
        AND weather_iteration {comparison} 0
        """ for comparison in (">", "<")) + "ORDER BY project, weather_iteration;"
    ).fetchall()


def get_outage_derate_sql(
    subscenarios, weather_iteration, availability_iteration, subproblem, stage
):
    """
    :return: SQL selecting (project, timepoint, availability_derate_outage,
        hyb_stor_cap_availability_derate_outage) for the subproblem and
        stage's timepoints, at the run's availability iteration and at its
        weather iteration for the projects whose derates vary by it and at
        weather_iteration 0 otherwise
    """
    # cfg must be the outer loop: the weather iteration to read depends on
    # cfg.varies_by_weather_iteration, so with the outage table outside it
    # SQLite can search the outage table's primary key only by project and
    # subscenario and reads every weather and availability iteration of each
    # project, in every subproblem. CROSS JOIN is SQLite's way to fix the
    # join order (a plain JOIN may be reordered).
    return f"""
        SELECT project, timepoint, availability_derate_outage,
        hyb_stor_cap_availability_derate_outage
        FROM ({get_outage_iteration_config_sql(subscenarios)}) AS cfg
        CROSS JOIN inputs_project_availability_exogenous_outage
        USING (project, exogenous_availability_outage_scenario_id)
        -- Relevant temporal index
        WHERE timepoint IN (
            SELECT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
        )
        -- Get the correct iterations
        AND weather_iteration = CASE WHEN cfg.varies_by_weather_iteration
            THEN {weather_iteration} ELSE 0 END
        AND availability_iteration = {availability_iteration}
        -- Get the stage's data
        AND stage_id = {stage}
        ;
    """


def get_bt_hrz_derate_sql(
    subscenarios,
    subproblem,
    stage,
    table,
    scenario_id_column,
    derate_column,
    iteration_column,
    iteration,
):
    """
    The (project, balancing type, horizon) derates of *table* for the
    portfolio's exogenous-availability projects with a *scenario_id_column*
    subscenario, for the horizons of the subproblem, and the iteration and
    stage; on the built-in month and day balancing types, calendar rows
    (month-of-year and day-of-year rows, see gridpath.auxiliary.calendar_rows)
    supply the horizons without an explicit row.
    """
    row_filter = f"""project IN (
            SELECT project FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        )
        -- Projects from this availability ID and type with this subscenario
        AND (project, {scenario_id_column}) IN (
            SELECT project, {scenario_id_column}
            FROM inputs_project_availability
            WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
            AND availability_type = 'exogenous'
            AND {scenario_id_column} IS NOT NULL
        )
        -- Get the correct iteration
        AND {iteration_column} = {iteration}
        -- Get the stage's data
        AND stage_id = {stage}"""

    calendar_rows = calendar_rows_sql(
        table=table,
        bt_column="balancing_type_project",
        select_columns=("project", derate_column),
        row_filter=row_filter,
        key_columns=["project", scenario_id_column],
        explicit_filter=f"""AND explicit.{iteration_column} = {iteration}
            AND explicit.stage_id = {stage}""",
    )

    return f"""
        {calendar_index_cte_sql(
            subscenarios.TEMPORAL_SCENARIO_ID, subproblem, stage, first=True
        )}
        SELECT project, balancing_type_project, horizon, {derate_column}
        FROM {table}
        WHERE {row_filter}
        -- Relevant temporal index
        AND (balancing_type_project, horizon) IN (
            SELECT balancing_type_horizon, horizon
            FROM inputs_temporal_horizon_timepoints
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
        )
        UNION ALL
        {calendar_rows}
        """


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

    # Derate by timepoint, read at the run's weather iteration for the
    # projects whose data varies by it and at weather_iteration 0 otherwise
    check_outage_iteration_config(
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        conn=conn,
    )
    ind_sql = get_outage_derate_sql(
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
    )

    c1 = conn.cursor()
    outage_availabilities = c1.execute(ind_sql)

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
        -- Get the stage's data
        AND stage_id = {stage}
        ;
    """

    c2 = conn.cursor()
    weather_availabilities = c2.execute(weather_sql)

    # Balancing types the temporal scenario lacks are dropped by the
    # balancing type - horizon queries below
    for bt_hrz_table, bt_hrz_scenario_id_column in [
        (
            "inputs_project_availability_exogenous_outage_bt_hrz",
            "exogenous_availability_outage_bt_hrz_scenario_id",
        ),
        (
            "inputs_project_availability_exogenous_weather_bt_hrz",
            "exogenous_availability_weather_bt_hrz_scenario_id",
        ),
    ]:
        warn_on_unknown_balancing_types(
            conn=conn,
            temporal_scenario_id=subscenarios.TEMPORAL_SCENARIO_ID,
            table=bt_hrz_table,
            bt_column="balancing_type_project",
            row_filter=f"""project IN (
                SELECT project FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )
            AND (project, {bt_hrz_scenario_id_column}) IN (
                SELECT project, {bt_hrz_scenario_id_column}
                FROM inputs_project_availability
                WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
                AND availability_type = 'exogenous'
            )""",
        )

    # Derates by balancing type - horizon, outage and weather-dependent
    bt_hrz_ind_sql = get_bt_hrz_derate_sql(
        subscenarios=subscenarios,
        subproblem=subproblem,
        stage=stage,
        table="inputs_project_availability_exogenous_outage_bt_hrz",
        scenario_id_column="exogenous_availability_outage_bt_hrz_scenario_id",
        derate_column="availability_derate_outage_bt_hrz",
        iteration_column="availability_iteration",
        iteration=availability_iteration,
    )
    c3 = conn.cursor()
    bt_hrz_outage_availabilities = c3.execute(bt_hrz_ind_sql)

    bt_hrz_weather_sql = get_bt_hrz_derate_sql(
        subscenarios=subscenarios,
        subproblem=subproblem,
        stage=stage,
        table="inputs_project_availability_exogenous_weather_bt_hrz",
        scenario_id_column="exogenous_availability_weather_bt_hrz_scenario_id",
        derate_column="availability_derate_weather_bt_hrz",
        iteration_column="weather_iteration",
        iteration=weather_iteration,
    )
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

    # Project defaults for the outage derate
    default_sql = f"""
        SELECT project, default_exogenous_availability
        FROM inputs_project_availability
        WHERE project_availability_scenario_id = {subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID}
        AND availability_type = 'exogenous'
        AND default_exogenous_availability IS NOT NULL
        -- Portfolio projects only
        AND project IN (
            SELECT project FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        )
        ;
    """

    c6 = conn.cursor()
    default_availabilities = c6.execute(default_sql)

    return (
        outage_availabilities,
        weather_availabilities,
        bt_hrz_outage_availabilities,
        bt_hrz_weather_availabilities,
        monthly_availabilities,
        default_availabilities,
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
        outage_availabilities,
        weather_availabilities,
        outage_availabilities_bt_hrz,
        weather_availabilities_bt_hrz,
        monthly_availabilities,
        default_availabilities,
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
        fname="project_availability_exogenous_outage.tab",
        data=outage_availabilities,
        replace_nulls=True,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="project_availability_exogenous_outage_bt_hrz.tab",
        data=outage_availabilities_bt_hrz,
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

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname=DEFAULT_DERATE_FILENAME,
        data=default_availabilities,
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
        outage_availabilities,
        weather_availabilities,
        outage_availabilities_bt_hrz,
        weather_availabilities_bt_hrz,
        monthly_availabilities,
        default_availabilities,
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

    df = cursor_to_df(outage_availabilities)
    idx_cols = ["project", "timepoint"]
    value_cols = ["availability_derate_outage"]

    # Check data types availability
    expected_dtypes = get_expected_dtypes(
        conn,
        [
            "inputs_project_availability",
            "inputs_project_availability_exogenous_outage",
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
        db_table="inputs_project_availability_exogenous_outage",
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
        db_table="inputs_project_availability_exogenous_outage",
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
            db_table="inputs_project_availability_exogenous_outage",
            severity="High",
            errors=validate_values(df, value_cols, min=0, max=1),
        )

    # Rows at an iteration the project's derates are not flagged to vary by
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_availability_exogenous_outage",
        severity="High",
        errors=[
            f"Project {prj} has rows at weather_iteration {w} but is not "
            f"flagged to vary by weather iteration in "
            f"inputs_project_availability_exogenous_outage_iterations, "
            f"so they are never read."
            for prj, w in get_unread_outage_rows(subscenarios, conn)
        ],
    )

    # Project defaults for the outage derate
    default_df = cursor_to_df(default_availabilities)
    default_dtype_errors, default_error_columns = validate_dtypes(
        default_df, expected_dtypes
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
        db_table="inputs_project_availability",
        severity="High",
        errors=default_dtype_errors,
    )
    if "default_exogenous_availability" not in default_error_columns:
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_project_availability",
            severity="High",
            errors=validate_values(
                default_df, ["default_exogenous_availability"], min=0, max=1
            ),
        )
