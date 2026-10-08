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
This capacity type describes generator projects with the same
characteristics as *gen_spec*, but whose fixed O&M cost can be avoided by
'retiring' them.

The optimization can make the decision to retire generation in each study
*period*. Once retired, the generator may not become operational again.
Retirement decisions for this capacity type are 'linearized,' i.e. the
optimization may retire generators partially (e.g. retire only 200 MW of
a 500-MW generator). If retired, the annual fixed O&M cost of these projects
is avoided in the objective function.

"""

import csv
import os.path
from pathlib import Path

import pandas as pd
from pyomo.environ import (
    Set,
    Param,
    Var,
    Constraint,
    Expression,
    NonNegativeReals,
    value,
)

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.dynamic_components import (
    capacity_type_operational_period_sets,
    capacity_type_financial_period_sets,
)
from gridpath.auxiliary.validations import (
    get_expected_dtypes,
    write_validation_to_database,
    validate_dtypes,
    validate_values,
    validate_row_monotonicity,
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
    | | :code:`GEN_RET_LIN`                                                   |
    |                                                                         |
    | The list of projects of the :code:`gen_ret_lin` capacity type.          |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_RET_LIN_OPR_PRDS`                                          |
    |                                                                         |
    | Two-dimensional set of project-period combinations that helps describe  |
    | the project capacity available in a given period. This set is added to  |
    | the list of sets to join to get the final :code:`PRJ_OPR_PRDS` set      |
    | defined in **gridpath.project.capacity.capacity**.                      |
    +-------------------------------------------------------------------------+
    | | :code:`OPR_PRDS_BY_GEN_RET_LIN`                                       |
    |                                                                         |
    | Indexed set that describes the operational periods for each             |
    | :code:`gen_ret_lin` project.                                            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_ret_lin_capacity_mw`                                       |
    | | *Defined over*: :code:`GEN_RET_LIN_OPR_PRDS`                          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's specified capacity (in MW) in each operational period if  |
    | no capacity is retired.                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_ret_lin_fixed_cost_per_mw_yr`                              |
    | | *Defined over*: :code:`GEN_RET_LIN_OPR_PRDS`                          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's fixed cost (in $ per MW-yr.) in each operational period.  |
    | This cost can be avoided by retiring the generation project.            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenRetLin_Retire_MW`                                           |
    | | *Defined over*: :code:`GEN_RET_LIN_OPR_PRDS`                          |
    |                                                                         |
    | The amount of capacity (in MW) to be retired for each project in each   |
    | operational period. Has to be larger than zero and smaller than         |
    | :code:`gen_ret_lin_capacity_mw`.                                        |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`GenRetLin_Retire_Forever_Constraint`                           |
    | | *Defined over*: :code:`GEN_RET_LIN_OPR_PRDS`                          |
    |                                                                         |
    | Total capacity after retirement must be less than or equal what is was  |
    | in the previous period. This ensures retirement decisions cannot be     |
    | undone.                                                                 |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.GEN_RET_LIN_OPR_PRDS = Set(dimen=2)

    m.GEN_RET_LIN = Set(
        initialize=lambda mod: sorted(
            list(set(g for (g, p) in mod.GEN_RET_LIN_OPR_PRDS))
        )
    )

    m.OPR_PRDS_BY_GEN_RET_LIN = Set(
        m.GEN_RET_LIN,
        initialize=lambda mod, prj: list(
            set(
                period
                for (project, period) in mod.GEN_RET_LIN_OPR_PRDS
                if project == prj
            )
        ),
    )

    # Required Params
    ###########################################################################

    m.gen_ret_lin_capacity_mw = Param(m.GEN_RET_LIN_OPR_PRDS, within=NonNegativeReals)

    m.gen_ret_lin_fixed_cost_per_mw_yr = Param(
        m.GEN_RET_LIN_OPR_PRDS,
        within=NonNegativeReals,
    )

    # Derived Params
    ###########################################################################

    m.gen_ret_lin_first_period = Param(
        m.GEN_RET_LIN,
        initialize=lambda mod, g: min(p for p in mod.OPR_PRDS_BY_GEN_RET_LIN[g]),
    )

    # Variables
    ###########################################################################

    # Retire capacity variable
    m.GenRetLin_Retire_MW = Var(m.GEN_RET_LIN_OPR_PRDS, bounds=retire_capacity_bounds)

    # Expressions
    ###########################################################################

    m.GenRetLin_Capacity_MW = Expression(
        m.GEN_RET_LIN_OPR_PRDS, rule=gen_ret_lin_capacity_rule
    )

    # Constraints
    ###########################################################################

    m.GenRetLin_Retire_Forever_Constraint = Constraint(
        m.GEN_RET_LIN_OPR_PRDS, rule=retire_forever_rule
    )

    # Dynamic Components
    ###########################################################################

    # Add to list of sets we'll join to get the final
    # PRJ_OPR_PRDS set
    getattr(d, capacity_type_operational_period_sets).append(
        "GEN_RET_LIN_OPR_PRDS",
    )


# Variable Bound Rules
###############################################################################


def retire_capacity_bounds(mod, g, p):
    """
    Shouldn't be able to retire more than available capacity
    """
    return 0, mod.gen_ret_lin_capacity_mw[g, p]


# Expression Rules
###############################################################################


def gen_ret_lin_capacity_rule(mod, g, p):
    """
    **Expressions Name**: GenRetLin_Capacity_MW
    **Enforced Over**: GEN_RET_LIN_OPR_PRDS

    Existing capacity minus retirements.
    """
    return mod.gen_ret_lin_capacity_mw[g, p] - mod.GenRetLin_Retire_MW[g, p]


# Constraint Formulation Rules
###############################################################################


def retire_forever_rule(mod, g, p):
    """
    **Constraint Name**: GenRetLin_Retire_Forever_Constraint
    **Enforced Over**: GEN_RET_LIN_OPR_PRDS

    Once retired, capacity cannot be brought back (i.e. in the current
    period, total capacity (after retirement) must be less than or equal
    what it was in the last period.
    """
    # Skip if we're in the first period
    if p == value(mod.first_period):
        return Constraint.Skip
    # Skip if this is the generator's first period
    if p == mod.gen_ret_lin_first_period[g]:
        return Constraint.Skip
    else:
        return (
            mod.GenRetLin_Capacity_MW[g, p]
            <= mod.GenRetLin_Capacity_MW[g, mod.prev_period[p]]
        )


# Capacity Type Methods
###############################################################################


def capacity_rule(mod, g, p):
    """
    The capacity of projects of the *gen_ret_lin* capacity type is a
    pre-specified number for each of the project's operational periods minus
    any capacity that was retired.
    """
    return mod.GenRetLin_Capacity_MW[g, p]


def fixed_cost_rule(mod, g, p):
    """
    The fixed cost of projects of the *gen_ret_lin* capacity type is its net
    capacity (pre-specified capacity minus retired capacity) times the per-mw
    fixed cost for each of the project's operational periods.
    """
    return mod.GenRetLin_Capacity_MW[g, p] * mod.gen_ret_lin_fixed_cost_per_mw_yr[g, p]


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
        capacity_type="gen_ret_lin",
    )

    data_portal.data()["GEN_RET_LIN_OPR_PRDS"] = {None: project_period_list}

    data_portal.data()["gen_ret_lin_capacity_mw"] = spec_params_dict[
        "specified_capacity_mw"
    ]

    data_portal.data()["gen_ret_lin_fixed_cost_per_mw_yr"] = spec_params_dict[
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
    Export gen_ret_lin retirement results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """
    results_columns = ["retired_mw"]
    data = [
        [prj, prd, value(m.GenRetLin_Retire_MW[prj, prd])]
        for (prj, prd) in m.GEN_RET_LIN_OPR_PRDS
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
        capacity_type="gen_ret_lin",
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
    spec_capacity_period_params.tab file
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

    gen_ret_lin_params = get_model_inputs_from_database(
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
    df = cursor_to_df(gen_ret_lin_params)

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
        capacity_type="gen_ret_lin",
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

    # Check project capacity is not increasing
    msg = (
        "gen_ret_lin projects are not expected to have increasing "
        "specified capacity. Any increases will force retirements. "
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
        db_table="inputs_project_specified_capacity",
        severity="High",
        errors=validate_row_monotonicity(
            df=df,
            col="specified_capacity_mw",
            rank_col="period",
            increasing=False,
            msg=msg,
        ),
    )
