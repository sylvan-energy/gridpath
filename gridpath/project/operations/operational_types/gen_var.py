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
This operational type describes generator projects whose power output is equal
to a pre-specified fraction of their available capacity (a capacity factor
parameter) in every timepoint, e.g. a wind farm with variable output depending
on local weather. Curtailment (dispatch down) is allowed. GridPath includes
experimental features to allow these generators to provide upward and/or
downward reserves.

Costs for this operational type include variable O&M costs.

"""

from pyomo.environ import (
    Param,
    Set,
    Var,
    Constraint,
    Reals,
    NonNegativeReals,
    Expression,
    value,
)
import warnings

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import (
    footroom_variables,
    headroom_variables,
    reserve_variable_derate_params,
)
from gridpath.project.operations.reserves.reserve_aggregation import (
    derated_headroom_provision_rule,
    derated_footroom_provision_rule,
)
from gridpath.project.operations.reserves.subhourly_energy_adjustment import (
    footroom_subhourly_energy_adjustment_rule,
    headroom_subhourly_energy_adjustment_rule,
)
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_var_profile_inputs,
    get_prj_temporal_index_opr_inputs_from_db,
    write_tab_file_model_inputs,
    validate_opchars,
    validate_var_profiles,
    load_optype_model_data,
)
from gridpath.common_functions import create_results_df


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
    | | :code:`GEN_VAR`                                                       |
    |                                                                         |
    | The set of generators of the :code:`gen_var` operational type.          |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_VAR_OPR_TMPS`                                              |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_var`              |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_var_cap_factor`                                            |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    | | *Within*: :code:`Reals`                                               |
    | | *Default*: :code:`gen_var_cap_factor_default`                         |
    |                                                                         |
    | The project's power output in each operational timepoint as a fraction  |
    | of its available capacity (i.e. the capacity factor). Setting the       |
    | default is optional.                                                    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_var_cap_factor_default`                                    |
    | | *Defined over*: :code:`GEN_VAR`                                       |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | Optinal default value for gen_var_cap_factor. Use with caution.         |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenVar_Provide_Power_MW`                                       |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Power provision in MW from this project in each timepoint in which the  |
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+
    | | :code:`GenVar_Scheduled_Curtailment_MW`                               |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Curtailed power in MW from this project in each timepoint in which the  |
    | project is operational (capacity exists and the project is available).  |
    | This will be the available power minus what was actually provided.      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`GenVar_Subhourly_Curtailment_MW`                               |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    |                                                                         |
    | Sub-hourly curtailment (in MW) from providing downward reserves.        |
    +-------------------------------------------------------------------------+
    | | :code:`GenVar_Subhourly_Energy_Delivered_MW`                          |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    |                                                                         |
    | Sub-hourly energy delivered (in MW) from providing upward reserves.     |
    +-------------------------------------------------------------------------+
    | | :code:`GenVar_Total_Curtailment_MW`                                   |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    |                                                                         |
    | Scheduled curtailment (in MW) plus an upward adjustment for additional  |
    | curtailment when providing downward reserves, and a downward adjustment |
    | adjustment for a reduction in curtailment when providing upward         |
    | reserves, to account for sub-hourly dispatch when providing reserves.   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Power                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenVar_Max_Power_Constraint`                                   |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    |                                                                         |
    | Limits the power plus scheduled curtailment in each timepoint to equal  |
    | the available power.                                                    |
    | :code:`gen_var_cap_factor` and the available capacity.                  |
    +-------------------------------------------------------------------------+
    | | :code:`GenVar_Max_Upward_Reserves_Constraint`                         |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    |                                                                         |
    | Upward reserves cannot exceed curtailment.                              |
    +-------------------------------------------------------------------------+
    | | :code:`GenVar_Max_Downward_Reserves_Constraint`                       |
    | | *Defined over*: :code:`GEN_VAR_OPR_TMPS`                              |
    |                                                                         |
    | Downward reserves cannot exceed power provision when the capacity       |
    | factor is non-negative (power is non-negative); otherwise they are set  |
    | to zero.                                                                |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################
    m.GEN_VAR = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_var"
        ),
    )

    m.GEN_VAR_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.GEN_VAR
        ),
    )

    # Optional Params
    ###########################################################################
    # Use with caution
    m.gen_var_cap_factor_default = Param(
        m.GEN_VAR,
        within=Reals | {"undefined"},
        initialize="undefined",
    )

    # Required Params
    ###########################################################################

    m.gen_var_cap_factor = Param(
        m.GEN_VAR_OPR_TMPS,
        within=Reals,
        default=lambda mod, prj, tmp: mod.gen_var_cap_factor_default[prj],
    )

    # Variables
    ###########################################################################

    m.GenVar_Provide_Power_MW = Var(m.GEN_VAR_OPR_TMPS, within=Reals)
    m.GenVar_Scheduled_Curtailment_MW = Var(m.GEN_VAR_OPR_TMPS, within=NonNegativeReals)

    # Expressions
    ###########################################################################

    def upwards_reserve_rule(mod, g, tmp):
        """
        Gather all headroom variables, and de-rate the total reserves offered
        to account for the fact that gen_var output is uncertain.
        """
        return derated_headroom_provision_rule(d, mod, g, tmp)

    m.GenVar_Upwards_Reserves_MW = Expression(
        m.GEN_VAR_OPR_TMPS, rule=upwards_reserve_rule
    )

    def downwards_reserve_rule(mod, g, tmp):
        """
        Gather all footroom variables, and de-rate the total reserves offered
        to account for the fact that gen_var output is uncertain.
        """
        return derated_footroom_provision_rule(d, mod, g, tmp)

    m.GenVar_Downwards_Reserves_MW = Expression(
        m.GEN_VAR_OPR_TMPS, rule=downwards_reserve_rule
    )

    def subhourly_curtailment_expression_rule(mod, g, tmp):
        """
        Sub-hourly curtailment from providing downward reserves.
        """
        return footroom_subhourly_energy_adjustment_rule(d, mod, g, tmp)

    m.GenVar_Subhourly_Curtailment_MW = Expression(
        m.GEN_VAR_OPR_TMPS, rule=subhourly_curtailment_expression_rule
    )

    def subhourly_delivered_energy_expression_rule(mod, g, tmp):
        """
        Sub-hourly energy delivered from providing upward reserves.
        """
        return headroom_subhourly_energy_adjustment_rule(d, mod, g, tmp)

    m.GenVar_Subhourly_Energy_Delivered_MW = Expression(
        m.GEN_VAR_OPR_TMPS, rule=subhourly_delivered_energy_expression_rule
    )

    m.GenVar_Total_Curtailment_MW = Expression(
        m.GEN_VAR_OPR_TMPS, rule=total_curtailment_expression_rule
    )

    # Constraints
    ###########################################################################

    m.GenVar_Max_Power_Constraint = Constraint(m.GEN_VAR_OPR_TMPS, rule=max_power_rule)

    m.GenVar_Max_Upward_Reserves_Constraint = Constraint(
        m.GEN_VAR_OPR_TMPS, rule=max_upward_reserves_rule
    )

    m.GenVar_Max_Downward_Reserves_Constraint = Constraint(
        m.GEN_VAR_OPR_TMPS, rule=max_downward_reserves_rule
    )


# Expression Methods
###############################################################################


def total_curtailment_expression_rule(mod, g, tmp):
    """
    **Expression Name**: GenVar_Total_Curtailment_MW
    **Defined Over**: GEN_VAR_OPR_TMPS

    Available energy that was not delivered
    There's an adjustment for subhourly reserve provision:
    1) if downward reserves are provided, they will be called upon
    occasionally, so power provision will have to decrease and additional
    curtailment will be incurred;
    2) if upward reserves are provided (energy is being curtailed),
    they will be called upon occasionally, so power provision will have to
    increase and less curtailment will be incurred
    The subhourly adjustment here is a simple linear function of reserve

    Assume cap factors don't incorporate availability derates,
    so don't multiply capacity by Availability_Derate here (will count
    as curtailment).
    """

    return (
        mod.GenVar_Scheduled_Curtailment_MW[g, tmp]
        + mod.GenVar_Subhourly_Curtailment_MW[g, tmp]
        - mod.GenVar_Subhourly_Energy_Delivered_MW[g, tmp]
    )


# Constraint Formulation Rules
###############################################################################


def max_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenVar_Max_Power_Constraint
    **Enforced Over**: GEN_VAR_OPR_TMPS

    Power provision plus curtailment cannot exceed available power, which
    is equal to the available capacity multiplied by the capacity factor.
    """
    return (
        mod.GenVar_Provide_Power_MW[g, tmp]
        + mod.GenVar_Scheduled_Curtailment_MW[g, tmp]
        == mod.Capacity_MW[g, mod.period[tmp]]
        * mod.Availability_Derate[g, tmp]
        * mod.gen_var_cap_factor[g, tmp]
    )


def max_upward_reserves_rule(mod, g, tmp):
    """
    Upward reserves can't exceed curtailment
    """
    return (
        mod.GenVar_Upwards_Reserves_MW[g, tmp]
        <= mod.GenVar_Scheduled_Curtailment_MW[g, tmp]
    )


def max_downward_reserves_rule(mod, g, tmp):
    """
    **Constraint Name**: GenVar_Min_Power_Constraint
    **Enforced Over**: GEN_VAR_OPR_TMPS

    Downward reserves can't exceed power provision.
    """
    if mod.gen_var_cap_factor[g, tmp] >= 0:
        return (
            mod.GenVar_Downwards_Reserves_MW[g, tmp]
            <= mod.GenVar_Provide_Power_MW[g, tmp]
        )
    else:
        return mod.GenVar_Downwards_Reserves_MW[g, tmp] == 0


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp):
    """
    Power provision from variable generators is their capacity times the
    capacity factor in each timepoint minus any upward reserves/curtailment.
    """

    return mod.GenVar_Provide_Power_MW[g, tmp]


def variable_om_cost_rule(mod, g, tmp):
    """
    Variable cost is incurred on all power produced (including what's
    curtailed).
    """
    return (
        mod.Capacity_MW[g, mod.period[tmp]]
        * mod.Availability_Derate[g, tmp]
        * mod.gen_var_cap_factor[g, tmp]
        * mod.variable_om_cost_per_mwh[g]
    )


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.Capacity_MW[prj, mod.period[tmp]]
        * mod.Availability_Derate[prj, tmp]
        * mod.gen_var_cap_factor[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.Capacity_MW[prj, mod.period[tmp]]
        * mod.Availability_Derate[prj, tmp]
        * mod.gen_var_cap_factor[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
    )


def scheduled_curtailment_rule(mod, g, tmp):
    """
    Variable generation can be dispatched down, i.e. scheduled below the
    available energy
    """
    return mod.GenVar_Scheduled_Curtailment_MW[g, tmp]


def subhourly_curtailment_rule(mod, g, tmp):
    """
    If providing downward reserves, variable generators will occasionally
    have to be dispatched down relative to their schedule, resulting in
    additional curtailment within the hour
    """
    return mod.GenVar_Subhourly_Curtailment_MW[g, tmp]


def subhourly_energy_delivered_rule(mod, g, tmp):
    """
    If providing upward reserves, variable generators will occasionally be
    dispatched up, so additional energy will be delivered within the hour
    relative to their schedule (less curtailment)
    """
    return mod.GenVar_Subhourly_Energy_Delivered_MW[g, tmp]


def curtailment_cost_rule(mod, g, tmp):
    """
    Apply curtailment cost to scheduled and subhourly curtailment
    """
    return (
        mod.GenVar_Scheduled_Curtailment_MW[g, tmp]
        + mod.GenVar_Subhourly_Curtailment_MW[g, tmp]
    ) * (
        mod.curtailment_cost_per_powerunithour[g, mod.period[tmp]]
        if (g, mod.period[tmp]) in mod.CURTAILMENT_COST_PRJ_PRDS
        else 0
    )


def power_delta_rule(mod, g, tmp):
    """
    Curtailment is counted as part of the ramp here; excludes any ramping from
    reserve provision.

    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint.
    """
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[g]
    ) and (
        check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linear",
        )
        or check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        )
    ):
        pass
    else:
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * mod.gen_var_cap_factor[g, tmp]
        ) - (
            mod.Capacity_MW[
                g, mod.period[mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            ]
            * mod.Availability_Derate[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            * mod.gen_var_cap_factor[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        )


def capacity_providing_inertia_rule(mod, g, tmp):
    """
    Capacity providing inertia for GEN_VAR project is equal to the online
    capacity if any of it is generating
    """
    if mod.gen_var_cap_factor[g, tmp] >= 0:
        return mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
    else:
        return 0


# Inputs-Outputs
###############################################################################


def load_model_data(
    mod,
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
    :param mod:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """

    # Load data from projects.tab and get the list of projects of this type
    projects = load_optype_model_data(
        mod=mod,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="gen_var",
    )

    load_var_profile_inputs(
        data_portal,
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "gen_var",
    )


def add_to_prj_tmp_results(mod):
    results_columns = [
        "scheduled_curtailment_mw",
        "subhourly_curtailment_mw",
        "subhourly_energy_delivered_mw",
        "total_curtailment_mw",
    ]
    data = [
        [
            prj,
            tmp,
            value(mod.GenVar_Scheduled_Curtailment_MW[prj, tmp]),
            value(mod.GenVar_Subhourly_Curtailment_MW[prj, tmp]),
            value(mod.GenVar_Subhourly_Energy_Delivered_MW[prj, tmp]),
            value(mod.GenVar_Total_Curtailment_MW[prj, tmp]),
        ]
        for (prj, tmp) in mod.GEN_VAR_OPR_TMPS
    ]

    optype_dispatch_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    return results_columns, optype_dispatch_df


# Database
###############################################################################


def get_model_inputs_from_database(
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
    :return: cursor object with query results
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

    prj_tmp_data = get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=subscenarios,
        weather_iteration=db_weather_iteration,
        hydro_iteration=db_hydro_iteration,
        availability_iteration=db_availability_iteration,
        subproblem=db_subproblem,
        stage=db_stage,
        conn=conn,
        op_type="gen_var",
        table="inputs_project_variable_generator_profiles",
        subscenario_id_column="variable_generator_profile_scenario_id",
        data_column="cap_factor",
    )

    return prj_tmp_data


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
    variable_generator_profiles.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    data = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )
    fname = "variable_generator_profiles.tab"

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname,
        data,
    )


def process_model_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate scheduled curtailment
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate variable curtailment")

    # Delete old aggregated variable curtailment results
    del_sql = """
        DELETE FROM results_project_curtailment_variable_periodagg 
        WHERE scenario_id = ?;
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Aggregate variable curtailment (just scheduled curtailment)
    insert_sql = """
        INSERT INTO results_project_curtailment_variable_periodagg
        (scenario_id, subproblem_id, stage_id, period, timepoint, 
        timepoint_weight, number_of_hours_in_timepoint, month, hour_of_day,
        load_zone, scheduled_curtailment_mw)
        SELECT
        scenario_id, subproblem_id, stage_id, period, timepoint, 
        timepoint_weight, number_of_hours_in_timepoint, month, hour_of_day,
        load_zone, scheduled_curtailment_mw
        FROM (
            SELECT scenario_id, subproblem_id, stage_id, period, 
            timepoint, timepoint_weight, number_of_hours_in_timepoint, 
            load_zone, 
            sum(scheduled_curtailment_mw) AS scheduled_curtailment_mw
            FROM results_project_timepoint
            WHERE operational_type = 'gen_var'
            GROUP BY scenario_id, subproblem_id, stage_id, timepoint, load_zone
        ) as agg_curtailment_tbl
        JOIN (
            SELECT subproblem_id, stage_id, timepoint, month, hour_of_day
            FROM inputs_temporal
            WHERE temporal_scenario_id = (
                SELECT temporal_scenario_id 
                FROM scenarios
                WHERE scenario_id = ?
                )
        ) as tmp_info_tbl
        USING (subproblem_id, stage_id, timepoint)
        WHERE scenario_id = ?
        ORDER BY subproblem_id, stage_id, load_zone, timepoint;"""

    spin_on_database_lock(
        conn=db, cursor=c, sql=insert_sql, data=(scenario_id, scenario_id), many=False
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

    # Validate operational chars table inputs
    validate_opchars(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "gen_var",
    )

    # Validate var profiles input table
    cap_factor_validation_error = validate_var_profiles(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "gen_var",
    )
