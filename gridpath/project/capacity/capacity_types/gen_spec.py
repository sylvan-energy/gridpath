# Copyright 2016-2025 Blue Marble Analytics LLC.
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
This capacity type describes generator projects that are available to the
optimization without having to incur an investment cost, e.g. existing
projects or projects that will be built in the future and whose capital
costs we want to ignore (in the objective function). A specified generator can
be available at a specified capacity in all periods, or in some periods only,
with no restriction on the order and combination of periods or the variation
in capacity by period. A project is operational in exactly the periods for
which it has a specified-capacity row with a capacity value: leaving a period
out, or leaving every capacity column of its row blank, keeps the project
out of the model in that period entirely (no variables or constraints are
created for it), which is the way to model a project that retires or comes
online within the study horizon, whereas a row with zero
capacity keeps the project in the model, and in the results, at zero
capacity, so all of the project's operational inputs for that period (e.g.
variable profiles, hydro budgets, timepoint-varying costs) are still
required. The choice between the two is the user's; input validation flags
periods left out between periods with capacity, and projects with no capacity
in any period of a subproblem, at low severity.

The user may specify a fixed O&M cost for these generators, but this cost will
be a fixed number in the objective function and will therefore not affect any
of the optimization decisions.
"""

from pyomo.environ import Set, Param, NonNegativeReals

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.dynamic_components import capacity_type_operational_period_sets
from gridpath.auxiliary.validations import (
    get_expected_dtypes,
    write_validation_to_database,
    validate_dtypes,
    validate_values,
    validate_missing_inputs,
)
from gridpath.project.capacity.capacity_types.common_methods import (
    spec_get_inputs_from_database,
    spec_write_tab_file,
    spec_determine_inputs,
    validate_spec_capacity_coverage,
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
    | | :code:`GEN_SPEC_OPR_PRDS`                                             |
    |                                                                         |
    | Two-dimensional set of project-period combinations that describes the   |
    | project capacity available in a given period. This set is added to the  |
    | list of sets to join to get the final :code:`PRJ_OPR_PRDS` set defined  |
    | in **gridpath.project.capacity.capacity**.                              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_spec_capacity_mw`                                          |
    | | *Defined over*: :code:`GEN_SPEC_OPR_PRDS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's specified capacity (in MW) in each operational period.    |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_spec_fixed_cost_per_mw_yr`                                 |
    | | *Defined over*: :code:`GEN_SPEC_OPR_PRDS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`.                                                 |
    |                                                                         |
    | The project's fixed cost (in $ per MW-yr.) in each operational period.  |
    | This cost will be added to the objective function but will not affect   |
    | optimization decisions.                                                 |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.GEN_SPEC_OPR_PRDS = Set(dimen=2, within=m.PROJECTS * m.PERIODS)

    # Required Params
    ###########################################################################

    m.gen_spec_capacity_mw = Param(m.GEN_SPEC_OPR_PRDS, within=NonNegativeReals)

    m.gen_spec_fixed_cost_per_mw_yr = Param(
        m.GEN_SPEC_OPR_PRDS, within=NonNegativeReals, default=0
    )

    # Dynamic Components
    ###########################################################################

    # Add to list of sets we'll join to get the final
    # PRJ_OPR_PRDS set
    getattr(d, capacity_type_operational_period_sets).append(
        "GEN_SPEC_OPR_PRDS",
    )


# Capacity Type Methods
###############################################################################


def capacity_rule(mod, g, p):
    """
    The capacity of projects of the *gen_spec* capacity type is a
    pre-specified number for each of the project's operational periods.
    """
    return mod.gen_spec_capacity_mw[g, p]


def fixed_cost_rule(mod, g, p):
    """
    The fixed cost of projects of the *gen_spec* capacity type is a
    pre-specified number equal to the capacity times the per-mw fixed cost
    for each of the project's operational periods.
    """
    return mod.gen_spec_capacity_mw[g, p] * mod.gen_spec_fixed_cost_per_mw_yr[g, p]


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
        capacity_type="gen_spec",
    )

    data_portal.data()["GEN_SPEC_OPR_PRDS"] = project_period_list

    data_portal.data()["gen_spec_capacity_mw"] = spec_params_dict[
        "specified_capacity_mw"
    ]

    data_portal.data()["gen_spec_fixed_cost_per_mw_yr"] = spec_params_dict[
        "fixed_cost_per_mw_yr"
    ]


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
        capacity_type="gen_spec",
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

    gen_spec_params = get_model_inputs_from_database(
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
    df = cursor_to_df(gen_spec_params)

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
        capacity_type="gen_spec",
    )

    # Check for missing values (vs. missing row entries above)
    # Capacity is required, fixed cost is optional (defaults to 0)
    cols = ["specified_capacity_mw"]
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
        errors=validate_missing_inputs(df, cols),
    )
