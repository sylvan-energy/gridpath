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
*Projects* assigned this availability type have binary decision variables
for their availability in each timepoint. This type can be useful in
optimizing planned outage schedules. A *project* of this type is constrained
to be unavailable for at least a pre-specified number of hours in each
*period*. In addition, each unavailability event can be constrained to be
within a minimum and maximum number of hours, and constraints can also be
implemented on the minimum and maximum duration between unavailability events.

"""

import csv
import os.path
from pyomo.environ import (
    Param,
    Set,
    Var,
    Constraint,
    Boolean,
    Binary,
    value,
    NonNegativeReals,
)

from gridpath.auxiliary.auxiliary import cursor_to_df, subset_init_by_set_membership
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    get_expected_dtypes,
    validate_dtypes,
    validate_missing_inputs,
    validate_column_monotonicity,
)
from gridpath.common_functions import create_results_df
from gridpath.project import PROJECT_TIMEPOINT_DF
from gridpath.project.operations.operational_types.common_functions import (
    determine_relevant_timepoints,
)
from gridpath.project.common_functions import (
    determine_project_subset,
    check_if_boundary_type_and_first_timepoint,
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
    The following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`AVL_BIN`                                                       |
    |                                                                         |
    | The set of projects of the :code:`binary` availability type.            |
    +-------------------------------------------------------------------------+
    | | :code:`AVL_BIN_OPR_PRDS`                                              |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`binary` availability    |
    | type and their operational periods.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`AVL_BIN_OPR_TMPS`                                              |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`binary` availability    |
    | type and their operational timepoints.                                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`avl_bin_unavl_hrs_per_prd`                                     |
    | | *Defined over*: :code:`AVL_BIN`                                       |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The number of hours the project must be unavailable per period.         |
    +-------------------------------------------------------------------------+
    | | :code:`avl_bin_unavl_hrs_per_prd_req_exact`                           |
    | | *Defined over*: :code:`AVL_BIN`                                       |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | Require exactly the number of hours the project must be unavailable per |
    | period. If set to 0, the constraint is soft.                            |
    +-------------------------------------------------------------------------+
    | | :code:`avl_bin_min_unavl_hrs_per_event`                               |
    | | *Defined over*: :code:`AVL_BIN`                                       |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The minimum number of hours an unavailability event should last for.    |
    +-------------------------------------------------------------------------+
    | | :code:`avl_bin_min_avl_hrs_between_events`                            |
    | | *Defined over*: :code:`AVL_BIN`                                       |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The minimum number of hours a project should be available between       |
    | unavailability events.                                                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`AvlBin_Unavailable`                                            |
    | | *Defined over*: :code:`AVL_BIN_OPR_TMPS`                              |
    | | *Within*: :code:`Binary`                                              |
    |                                                                         |
    | Binary decision variable that specifies whether the project is          |
    | unavailable or not in each operational timepoint (1=unavailable).       |
    +-------------------------------------------------------------------------+
    | | :code:`AvlBin_Start_Unavailability`                                   |
    | | *Defined over*: :code:`AVL_BIN_OPR_TMPS`                              |
    | | *Within*: :code:`Binary`                                              |
    |                                                                         |
    | Binary decision variable that designates the start of an unavailability |
    | event (when the project goes from available to unavailable.             |
    +-------------------------------------------------------------------------+
    | | :code:`AvlBin_Stop_Unavailability`                                    |
    | | *Defined over*: :code:`AVL_BIN_OPR_TMPS`                              |
    | | *Within*: :code:`Binary`                                              |
    |                                                                         |
    | Binary decision variable that designates the end of an unavailability   |
    | event (when the project goes from unavailable to available.             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`AvlBin_Tot_Sched_Unavl_per_Prd_Constraint`                     |
    | | *Defined over*: :code:`AVL_BIN_OPR_PRDS`                              |
    |                                                                         |
    | The project must be unavailable for :code:`avl_bin_unavl_hrs_per_prd`   |
    | hours in each period.                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`AvlBin_Unavl_Start_and_Stop_Constraint`                        |
    | | *Defined over*: :code:`AVL_BIN_OPR_TMPS`                              |
    |                                                                         |
    | Link the three binary variables in each timepoint such that             |
    | :code:`AvlBin_Start_Unavailability` is 1 if the project goes from       |
    | available to unavailable, and :code:`AvlBin_Stop_Unavailability` is 1   |
    | if the project goes from unavailable to available.                      |
    +-------------------------------------------------------------------------+
    | | :code:`AvlBin_Min_Event_Duration_Constraint`                          |
    | | *Defined over*: :code:`AVL_BIN_OPR_TMPS`                              |
    |                                                                         |
    | The duration of each unavailability event should be larger than or      |
    | equal to :code:`avl_bin_min_unavl_hrs_per_event` hours.                 |
    +-------------------------------------------------------------------------+
    | | :code:`AvlBin_Min_Time_Between_Events_Constraint`                     |
    | | *Defined over*: :code:`AVL_BIN_OPR_TMPS`                              |
    |                                                                         |
    | The time between unavailability events should be larger than or equal   |
    | to :code:`avl_bin_min_avl_hrs_between_events` hours.                    |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.AVL_BIN = Set(within=m.PROJECTS)

    m.AVL_BIN_OPR_PRDS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_PRDS", index=0, membership_set=mod.AVL_BIN
        ),
    )

    m.AVL_BIN_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.AVL_BIN
        ),
    )

    # Required Input Params
    ###########################################################################

    m.avl_bin_unavl_hrs_per_prd = Param(m.AVL_BIN, within=NonNegativeReals)
    m.avl_bin_unavl_hrs_per_prd_req_exact = Param(m.AVL_BIN, within=Boolean)

    m.avl_bin_min_unavl_hrs_per_event = Param(m.AVL_BIN, within=NonNegativeReals)

    m.avl_bin_min_avl_hrs_between_events = Param(m.AVL_BIN, within=NonNegativeReals)

    # Variables
    ###########################################################################

    m.AvlBin_Unavailable = Var(m.AVL_BIN_OPR_TMPS, within=Binary)

    m.AvlBin_Start_Unavailability = Var(m.AVL_BIN_OPR_TMPS, within=Binary)

    m.AvlBin_Stop_Unavailability = Var(m.AVL_BIN_OPR_TMPS, within=Binary)

    # Constraints
    ###########################################################################

    m.AvlBin_Tot_Sched_Unavl_per_Prd_Constraint = Constraint(
        m.AVL_BIN_OPR_PRDS, rule=total_scheduled_availability_per_period_rule
    )

    m.AvlBin_Unavl_Start_and_Stop_Constraint = Constraint(
        m.AVL_BIN_OPR_TMPS, rule=unavailability_start_and_stop_rule
    )

    m.AvlBin_Min_Event_Duration_Constraint = Constraint(
        m.AVL_BIN_OPR_TMPS, rule=event_min_duration_rule
    )

    m.AvlBin_Min_Time_Between_Events_Constraint = Constraint(
        m.AVL_BIN_OPR_TMPS, rule=min_time_between_events_rule
    )


# Constraint Formulation Rules
###############################################################################


def total_scheduled_availability_per_period_rule(mod, g, p):
    """
    **Constraint Name**: AvlBin_Tot_Sched_Unavl_per_Prd_Constraint
    **Enforced Over**: AVL_BIN_OPR_PRDS

    The project must be down for avl_bin_unavl_hrs_per_prd in each period if
    avl_bin_unavl_hrs_per_prd_req_exact is 1 or at least
    avl_bin_unavl_hrs_per_prd otherwise.
    """
    lhs = sum(
        mod.AvlBin_Unavailable[g, tmp] * mod.hrs_in_tmp[tmp] * mod.tmp_weight[tmp]
        for tmp in mod.TMPS_IN_PRD[p]
    )
    if mod.avl_bin_unavl_hrs_per_prd_req_exact:
        return lhs == mod.avl_bin_unavl_hrs_per_prd[g]
    else:
        return lhs >= mod.avl_bin_unavl_hrs_per_prd[g]


def unavailability_start_and_stop_rule(mod, g, tmp):
    """
    **Constraint Name**: AvlBin_Unavl_Start_and_Stop_Constraint
    **Enforced Over**: AVL_BIN_OPR_TMPS

    Constrain the start and stop availability variables based on the
    availability status in the current and previous timepoint. If the
    project is down in the current timepoint and was not down in the
    previous timepoint, then the RHS is 1 and AvlBin_Start_Unavailability
    must be set to 1. If the project is not down in the current
    timepoint and was down in the previous timepoint, then the RHS is -1
    and AvlBin_Stop_Unavailability must be set to 1.
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        return (
            mod.AvlBin_Start_Unavailability[g, tmp]
            - mod.AvlBin_Stop_Unavailability[g, tmp]
            == mod.AvlBin_Unavailable[g, tmp]
            - mod.AvlBin_Unavailable[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        )


def event_min_duration_rule(mod, g, tmp):
    """
    **Constraint Name**: AvlBin_Min_Event_Duration_Constraint
    **Enforced Over**: AVL_BIN_OPR_TMPS

    If a project became unavailable within avl_bin_min_unavl_hrs_per_event
    from the current timepoint, it must still be unavailable in the current
    timepoint.
    """
    relevant_tmps, _ = determine_relevant_timepoints(
        mod, g, tmp, mod.avl_bin_min_unavl_hrs_per_event[g]
    )
    if relevant_tmps == [tmp]:
        return Constraint.Skip
    return (
        sum(mod.AvlBin_Start_Unavailability[g, tp] for tp in relevant_tmps)
        <= mod.AvlBin_Unavailable[g, tmp]
    )


def min_time_between_events_rule(mod, g, tmp):
    """
    **Constraint Name**: AvlBin_Min_Time_Between_Events_Constraint
    **Enforced Over**: AVL_BIN_OPR_TMPS

    If a project became available within avl_bin_min_avl_hrs_between_events
    from the current timepoint, it must still be available in the current
    timepoint.
    """
    relevant_tmps, _ = determine_relevant_timepoints(
        mod, g, tmp, mod.avl_bin_min_avl_hrs_between_events[g]
    )
    if relevant_tmps == [tmp]:
        return Constraint.Skip
    return (
        sum(mod.AvlBin_Stop_Unavailability[g, tp] for tp in relevant_tmps)
        <= 1 - mod.AvlBin_Unavailable[g, tmp]
    )


# Availability Type Methods
###############################################################################


def availability_derate_cap_rule(mod, g, tmp):
    """ """
    return 1 - mod.AvlBin_Unavailable[g, tmp]


def availability_derate_hyb_stor_cap_rule(mod, g, tmp):
    """ """
    return 1


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
    project_subset = determine_project_subset(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        column="availability_type",
        type="binary",
        prj_or_tx="project",
    )

    data_portal.data()["AVL_BIN"] = {None: project_subset}

    avl_bin_unavl_hrs_per_prd_dict = {}
    avl_bin_unavl_hrs_per_prd_exact_dict = {}
    avl_bin_min_unavl_hrs_per_event_dict = {}
    avl_bin_min_avl_hrs_between_events_dict = {}

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "project_availability_endogenous.tab",
        ),
        "r",
    ) as f:
        reader = csv.reader(f, delimiter="\t", lineterminator="\n")
        next(reader)

        for row in reader:
            if row[0] in project_subset:
                avl_bin_unavl_hrs_per_prd_dict[row[0]] = float(row[1])
                avl_bin_unavl_hrs_per_prd_exact_dict[row[0]] = int(float(row[2]))
                avl_bin_min_unavl_hrs_per_event_dict[row[0]] = float(row[3])
                avl_bin_min_avl_hrs_between_events_dict[row[0]] = float(row[4])

    data_portal.data()["avl_bin_unavl_hrs_per_prd"] = avl_bin_unavl_hrs_per_prd_dict
    data_portal.data()[
        "avl_bin_unavl_hrs_per_prd_req_exact"
    ] = avl_bin_unavl_hrs_per_prd_exact_dict
    data_portal.data()[
        "avl_bin_min_unavl_hrs_per_event"
    ] = avl_bin_min_unavl_hrs_per_event_dict
    data_portal.data()[
        "avl_bin_min_avl_hrs_between_events"
    ] = avl_bin_min_avl_hrs_between_events_dict


def add_to_prj_tmp_results(
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
    :param m: The Pyomo abstract model
    :param d: Dynamic components
    :return: Nothing
    """

    results_columns = [
        "unavailability_decision",
        "start_unavailability",
        "stop_unavailability",
    ]
    data = [
        [
            prj,
            tmp,
            value(m.AvlBin_Unavailable[prj, tmp]),
            value(m.AvlBin_Start_Unavailability[prj, tmp]),
            value(m.AvlBin_Stop_Unavailability[prj, tmp]),
        ]
        for (prj, tmp) in m.AVL_BIN_OPR_TMPS
    ]
    results_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    return results_columns, results_df


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

    # Get project availability if project_availability_scenario_id is not NUL
    c = conn.cursor()
    availability_params = c.execute(
        """
            SELECT project, unavailable_hours_per_period, 
            unavailable_hours_per_period_require_exact,
            unavailable_hours_per_event_min,
            available_hours_between_events_min
            FROM (
            SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
            ) as portfolio_tbl
            INNER JOIN (
                SELECT project, endogenous_availability_scenario_id
                FROM inputs_project_availability
                WHERE project_availability_scenario_id = {}
                AND availability_type = 'binary'
                AND endogenous_availability_scenario_id IS NOT NULL
                ) AS avail_char
             USING (project)
            LEFT OUTER JOIN
            inputs_project_availability_endogenous
            USING (endogenous_availability_scenario_id, project);
            """.format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_AVAILABILITY_SCENARIO_ID,
        )
    )

    return availability_params


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

    endogenous_availability_params = get_inputs_from_database(
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        conn=conn,
    )

    # Check if project_availability_endogenous.tab exists; only write header
    # if the file wasn't already created
    availability_file = os.path.join(
        scenario_directory,
        subproblem,
        stage,
        "inputs",
        "project_availability_endogenous.tab",
    )

    if not os.path.exists(availability_file):
        with open(availability_file, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            # Write header
            writer.writerow(
                [
                    "project",
                    "unavailable_hours_per_period",
                    "unavailable_hours_per_period_require_exact",
                    "unavailable_hours_per_event_min",
                    "available_hours_between_events_min",
                ]
            )

    with open(availability_file, "a", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        # Write rows
        for row in endogenous_availability_params:
            replace_nulls = ["." if i is None else i for i in row]
            writer.writerow(replace_nulls)


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

    params = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    df = cursor_to_df(params)

    # Check data types availability
    expected_dtypes = get_expected_dtypes(
        conn, ["inputs_project_availability", "inputs_project_availability_endogenous"]
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
        db_table="inputs_project_availability_endogenous",
        severity="High",
        errors=dtype_errors,
    )

    # Check for missing inputs
    msg = ""
    value_cols = [
        "unavailable_hours_per_period",
        "unavailable_hours_per_event_min",
        "available_hours_between_events_min",
    ]
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_availability_endogenous",
        severity="Low",
        errors=validate_missing_inputs(df, value_cols, "project", msg),
    )

    cols = ["unavailable_hours_per_event_min", "unavailable_hours_per_period"]
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_availability_endogenous",
        severity="High",
        errors=validate_column_monotonicity(df=df, cols=cols, idx_col=["project"]),
    )
