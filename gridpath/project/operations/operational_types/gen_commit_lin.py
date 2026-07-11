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
This operational type is the same as the *gen_commit_bin* operational type,
but the commitment decisions are declared as continuous (with bounds of 0 to
1) instead of binary, so 'partial' generators can be committed. This
linear relaxation treatment can be helpful in situations when mixed-integer
problem run-times are long and is similar to loosening the MIP gap (but can
target specific generators). Please refer to the *gen_commit_bin* module for
more information on the formulation.
"""

from gridpath.project.operations.operational_types.common_functions import (
    validate_opchars,
)
from gridpath.common_functions import create_results_df, update_results_df
import gridpath.project.operations.operational_types.gen_commit_unit_common as gen_commit_unit_common


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
    See the formulation documentation in the
    gen_commit_unit_common.add_model_components().
    """

    gen_commit_unit_common.add_model_components(
        m=m,
        d=d,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        bin_or_lin_optype="gen_commit_lin",
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp):
    """
    Power provision for gen_commit_lin generators is a variable constrained
    constrained to be between the generator's minimum stable level and its
    capacity if the generator is committed and 0 otherwise.
    """
    return gen_commit_unit_common.power_provision_rule(mod, g, tmp, "Lin")


def commitment_rule(mod, g, tmp):
    """
    Commitment decision in each timepoint
    """
    return gen_commit_unit_common.commitment_rule(mod, g, tmp, "Lin")


def online_capacity_rule(mod, g, tmp):
    """
    Capacity online in each timepoint.
    """
    return gen_commit_unit_common.online_capacity_rule(mod, g, tmp, "Lin")


def variable_om_cost_rule(mod, g, tmp):
    """
    Variable O&M cost has two components which are additive:
    1. A fixed variable O&M rate (cost/MWh) that doesn't change with loading
       levels: :code:`variable_om_cost_per_mwh`.
    2. A fixed variable O&M rate by period (cost/MWh) that doesn't change with
       loading levels: :code:`variable_om_cost_per_mwh_by_period`.
    3. A variable O&M rate that changes with the loading level,
       similar to the heat rates. The idea is to represent higher variable cost
       rates at lower loading levels. This is captured in the
       :code:`GenCommitLin_Variable_OM_Cost_By_LL` decision variable. If no
       variable O&M curve inputs are provided, this component will be zero.

    Most users will only use the first component, which is specified in the
    operational characteristics table.  Only operational types with
    commitment decisions can have the second component.

    We need to explicitly have the op type method here because of auxiliary
    consumption. The default method takes Project_Power_Provision_MW multiplied by
    the variable cost, and Project_Power_Provision_MW is equal to Provide_Power_MW
    minus the auxiliary consumption. The variable cost should be applied to
    the gross power.
    """
    return gen_commit_unit_common.variable_om_cost_rule(mod, g, tmp, "Lin")


def variable_om_by_period_cost_rule(mod, g, tmp):
    """ """
    return gen_commit_unit_common.variable_om_by_period_cost_rule(mod, g, tmp, "Lin")


def variable_om_by_timepoint_cost_rule(mod, g, tmp):
    """ """
    return gen_commit_unit_common.variable_om_by_timepoint_cost_rule(mod, g, tmp, "Lin")


def variable_om_cost_by_ll_rule(mod, g, tmp, s):
    """
    Variable O&M cost has two components which are additive:
    1. A fixed variable O&M rate (cost/MWh) that doesn't change with loading
       levels: :code:`variable_om_cost_per_mwh`.
    2. A variable variable O&M rate that changes with the loading level,
       similar to the heat rates. The idea is to represent higher variable cost
       rates at lower loading levels. This is captured in the
       :code:`GenCommitLin_Variable_OM_Cost_By_LL` decision variable. If no
       variable O&M curve inputs are provided, this component will be zero.

    Most users will only use the first component, which is specified in the
    operational characteristics table.  Only operational types with
    commitment decisions can have the second component.
    """
    return gen_commit_unit_common.variable_om_cost_by_ll_rule(mod, g, tmp, s, "Lin")


def startup_cost_simple_rule(mod, g, tmp):
    """
    Simple startup costs are applied in each timepoint based on the amount of
    capacity (in MW) that is started up in that timepoint and the startup cost
    parameter.
    """
    return gen_commit_unit_common.startup_cost_simple_rule(mod, g, tmp, "Lin")


def startup_cost_by_st_rule(mod, g, tmp):
    """
    Startup costs are applied in each timepoint based on the amount of capacity
    (in MW) that is started up in that timepoint for a given startup type and
    the startup cost parameter for that startup type. We take the sum across
    all startup types since only one startup type is active at the same time.
    """
    return gen_commit_unit_common.startup_cost_by_st_rule(mod, g, tmp, "LIN", "Lin")


def shutdown_cost_rule(mod, g, tmp):
    """
    Shutdown costs are applied in each timepoint based on the amount of
    capacity (in Mw) that is shut down in that timepoint and the shutdown
    cost parameter.
    """
    return gen_commit_unit_common.shutdown_cost_rule(mod, g, tmp, "Lin")


def fuel_burn_by_ll_rule(mod, g, tmp, s):
    """ """
    return gen_commit_unit_common.fuel_burn_by_ll_rule(mod, g, tmp, s, "Lin")


def startup_fuel_burn_rule(mod, g, tmp):
    """
    Startup fuel burn is applied in each timepoint based on the amount of
    capacity (in MW) that is started up in that timepoint and the startup
    fuel parameter. This does not vary by startup type.
    """
    return gen_commit_unit_common.startup_fuel_burn_rule(mod, g, tmp, "Lin")


def power_delta_rule(mod, g, tmp):
    """
    Ramp between this timepoint and the previous timepoint.
    Actual ramp rate in MW/hr depends on the duration of the timepoints.
    This is only used in tuning costs, so fine to skip for linked horizon's
    first timepoint.
    """
    return gen_commit_unit_common.power_delta_rule(mod, g, tmp, "Lin")


def fix_commitment(mod, g, tmp):
    """ """
    return gen_commit_unit_common.fix_commitment(mod, g, tmp, "Lin")


def operational_violation_cost_rule(mod, g, tmp):
    """

    :param mod:
    :param g:
    :param tmp:
    :return:
    """
    return gen_commit_unit_common.operational_violation_cost_rule(
        mod, g, tmp, "lin", "Lin"
    )


def capacity_providing_inertia_rule(mod, g, tmp):
    """
    Capacity providing inertia for GEN_VAR project is equal to the online
    capacity
    """
    return gen_commit_unit_common.capacity_providing_inertia_rule(mod, g, tmp, "Lin")


# Input-Output
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

    gen_commit_unit_common.load_model_data(
        mod=mod,
        d=d,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        bin_or_lin_optype="gen_commit_lin",
        bin_or_lin="lin",
        BIN_OR_LIN="LIN",
    )


def add_to_prj_tmp_results(mod):
    results_columns, data = gen_commit_unit_common.add_to_prj_tmp_results(
        mod=mod,
        BIN_OR_LIN="LIN",
        Bin_or_Lin="Lin",
        bin_or_lin="lin",
    )

    (
        duals_results_columns,
        duals_data,
    ) = gen_commit_unit_common.add_duals_to_dispatch_results(
        mod=mod,
        BIN_OR_LIN="LIN",
        Bin_or_Lin="Lin",
    )

    # Create DF
    optype_dispatch_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    # Get the duals
    optype_duals_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=duals_results_columns,
        data=duals_data,
    )

    # Add duals to dispatch DF
    results_columns += duals_results_columns
    update_results_df(optype_dispatch_df, optype_duals_df)

    return results_columns, optype_dispatch_df


def export_results(
    mod,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param mod:
    :param d:
    :return:
    """
    gen_commit_unit_common.export_linked_subproblem_inputs(
        mod=mod,
        d=d,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        BIN_OR_LIN="LIN",
        Bin_or_Lin="Lin",
        bin_or_lin="lin",
    )


def save_duals(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    instance,
    dynamic_components,
):
    gen_commit_unit_common.save_duals(instance, "Lin")


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
    opchar_df = validate_opchars(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "gen_commit_lin",
    )
