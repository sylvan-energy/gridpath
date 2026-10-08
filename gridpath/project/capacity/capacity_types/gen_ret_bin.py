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
This capacity type describes generators with the same characteristics as
*gen_ret_lin*. However, retirement decisions are binary, i.e. the generator
is either fully retired or not retired at all.

"""

import csv
import os.path
from pathlib import Path

import pandas as pd
from pyomo.environ import Set, Param, Var, Constraint, NonNegativeReals, Binary, value

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.dynamic_components import capacity_type_operational_period_sets
from gridpath.auxiliary.validations import (
    get_expected_dtypes,
    write_validation_to_database,
    validate_dtypes,
    validate_values,
    validate_missing_inputs,
)
from gridpath.common_functions import create_results_df
from gridpath.project.capacity.capacity_types.common_methods import (
    spec_get_inputs_from_database,
    spec_write_tab_file,
    spec_determine_inputs,
    validate_spec_capacity_coverage,
    read_results_file_generic,
    write_summary_results_generic,
    get_units,
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
    | | :code:`GEN_RET_BIN`                                                   |
    |                                                                         |
    | The list of projects of the :code:`gen_ret_bin` capacity type.          |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_RET_BIN_OPR_PRDS`                                          |
    |                                                                         |
    | Two-dimensional set of project-period combinations that helps describe  |
    | the project capacity available in a given period. This set is added to  |
    | the list of sets to join to get the final :code:`PRJ_OPR_PRDS` set      |
    | defined in **gridpath.project.capacity.capacity**.                      |
    +-------------------------------------------------------------------------+
    | | :code:`OPR_PRDS_BY_GEN_RET_BIN`                                       |
    |                                                                         |
    | Indexed set that describes the operational periods for each             |
    | :code:`gen_ret_bin` project.                                            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_ret_bin_capacity_mw`                                       |
    | | *Defined over*: :code:`GEN_RET_BIN_OPR_PRDS`                          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's specified capacity (in MW) in each operational period if  |
    | no capacity is retired.                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_ret_bin_fixed_cost_per_mw_yr`                              |
    | | *Defined over*: :code:`GEN_RET_BIN_OPR_PRDS`                          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's fixed cost (in $ per MW-yr.) in each operational period.  |
    | This cost can be avoided by retiring the generation project.            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenRetBin_Retire`                                              |
    | | *Defined over*: :code:`GEN_RET_BIN_OPR_PRDS`                          |
    |                                                                         |
    | Binary decision variable that specifies whether the project is to be    |
    | retired in a given operational period or not (1 = retire). When         |
    | retired, no capacity will be available in that period and all following |
    | periods, and any fixed costs will no longer be incurred.                |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`GenRetBin_Retire_Forever_Constraint`                           |
    | | *Defined over*: :code:`GEN_RET_BIN_OPR_PRDS`                          |
    |                                                                         |
    | The binary decision variable has to be less than or equal to the binary |
    | decision variable in the previous period. This will prevent capacity    |
    | from coming back online after it has been retired.                      |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.GEN_RET_BIN_OPR_PRDS = Set(dimen=2)

    m.GEN_RET_BIN = Set(
        initialize=lambda mod: sorted(
            list(set(g for (g, p) in mod.GEN_RET_BIN_OPR_PRDS))
        )
    )

    m.OPR_PRDS_BY_GEN_RET_BIN = Set(
        m.GEN_RET_BIN,
        initialize=lambda mod, prj: sorted(
            list(
                set(
                    period
                    for (project, period) in mod.GEN_RET_BIN_OPR_PRDS
                    if project == prj
                )
            ),
        ),
    )

    # Required Params
    ###########################################################################

    m.gen_ret_bin_capacity_mw = Param(m.GEN_RET_BIN_OPR_PRDS, within=NonNegativeReals)

    m.gen_ret_bin_fixed_cost_per_mw_yr = Param(
        m.GEN_RET_BIN_OPR_PRDS, within=NonNegativeReals
    )

    # Derived Params
    ###########################################################################

    m.gen_ret_bin_first_period = Param(
        m.GEN_RET_BIN,
        initialize=lambda mod, g: min(p for p in mod.OPR_PRDS_BY_GEN_RET_BIN[g]),
    )

    # Variables
    ###########################################################################

    m.GenRetBin_Retire = Var(m.GEN_RET_BIN_OPR_PRDS, within=Binary)

    # Constraints
    ###########################################################################

    m.GenRetBin_Retire_Forever_Constraint = Constraint(
        m.GEN_RET_BIN_OPR_PRDS, rule=retire_forever_rule
    )

    # Dynamic Components
    ###########################################################################

    # Add to list of sets we'll join to get the final
    # PRJ_OPR_PRDS set
    getattr(d, capacity_type_operational_period_sets).append(
        "GEN_RET_BIN_OPR_PRDS",
    )


# Constraint Formulation Rules
###############################################################################


def retire_forever_rule(mod, g, p):
    """
    **Constraint Name**: GenRetBin_Retire_Forever_Constraint
    **Enforced Over**: GEN_RET_BIN_OPR_PRDS

    Once the binary retirement decision is made, the decision will last
    through all following periods, i.e. the binary variable cannot be
    smaller than what it was in the previous period.
    """
    # Skip if we're in the first period
    if p == value(mod.first_period):
        return Constraint.Skip
    # Skip if this is the generator's first period
    if p == mod.gen_ret_bin_first_period[g]:
        return Constraint.Skip
    else:
        return mod.GenRetBin_Retire[g, p] >= mod.GenRetBin_Retire[g, mod.prev_period[p]]


# Capacity Type Methods
###############################################################################


def capacity_rule(mod, g, p):
    """
    The capacity of projects of the *gen_ret_bin* capacity type is a
    pre-specified number for each of the project's operational periods
    multiplied with 1 minus the binary retirement variable.
    """
    return mod.gen_ret_bin_capacity_mw[g, p] * (1 - mod.GenRetBin_Retire[g, p])


def fixed_cost_rule(mod, g, p):
    """
    The fixed cost of projects of the *gen_ret_bin* capacity type is its net
    capacity (pre-specified capacity or zero if retired) times the per-mw
    fixed cost for each of the project's operational periods.
    """
    return (
        mod.gen_ret_bin_fixed_cost_per_mw_yr[g, p]
        * mod.gen_ret_bin_capacity_mw[g, p]
        * (1 - mod.GenRetBin_Retire[g, p])
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
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """

    project_period_list, spec_params_dict = spec_determine_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        capacity_type="gen_ret_bin",
    )

    data_portal.data()["GEN_RET_BIN_OPR_PRDS"] = project_period_list

    data_portal.data()["gen_ret_bin_capacity_mw"] = spec_params_dict[
        "specified_capacity_mw"
    ]

    data_portal.data()["gen_ret_bin_fixed_cost_per_mw_yr"] = spec_params_dict[
        "fixed_cost_per_mw_yr"
    ]


def add_to_project_period_results(
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
    Export gen_ret_bin retirement results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """
    results_columns = [
        "retired_mw",
        "retired_binary",
    ]
    data = [
        [
            prj,
            prd,
            value(m.GenRetBin_Retire[prj, prd] * m.gen_ret_bin_capacity_mw[prj, prd]),
            value(m.GenRetBin_Retire[prj, prd]),
        ]
        for (prj, prd) in m.GEN_RET_BIN_OPR_PRDS
    ]
    captype_df = create_results_df(
        index_columns=["project", "period"],
        results_columns=results_columns,
        data=data,
    )

    return results_columns, captype_df


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
    :return:
    """
    spec_params = spec_get_inputs_from_database(
        conn=conn,
        subscenarios=subscenarios,
        subproblem=subproblem,
        capacity_type="gen_ret_bin",
    )
    return spec_params


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
    spec_capacity_period_params.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    spec_project_params = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    # If spec_capacity_period_params.tab file already exists, append
    # rows to it
    spec_write_tab_file(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        spec_project_params=spec_project_params,
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

    gen_ret_bin_params = get_model_inputs_from_database(
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
    df = cursor_to_df(gen_ret_bin_params)

    # Get expected dtypes
    expected_dtypes = get_expected_dtypes(
        conn=conn,
        tables=[
            "inputs_project_specified_capacity",
            "inputs_project_specified_fixed_cost",
        ],
    )

    # Check dtypes
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
        db_table="inputs_project_specified_capacity, "
        "inputs_project_specified_fixed_cost",
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
        db_table="inputs_project_specified_capacity, "
        "inputs_project_specified_fixed_cost",
        severity="High",
        errors=validate_values(df, valid_numeric_columns, min=0),
    )

    # Check the period coverage of the capacity rows
    validate_spec_capacity_coverage(
        conn=conn,
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        gridpath_module=__name__,
        capacity_type="gen_ret_bin",
    )

    # Check for missing values (vs. missing row entries above)
    cols = ["specified_capacity_mw", "fixed_cost_per_mw_yr"]
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_specified_capacity, "
        "inputs_project_specified_fixed_cost",
        severity="High",
        errors=validate_missing_inputs(df, cols),
    )
