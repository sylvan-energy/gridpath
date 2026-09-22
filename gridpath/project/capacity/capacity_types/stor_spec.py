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
This capacity type describes the power (i.e. charging and discharging
capacity) and energy capacity (i.e., duration -- see important note on interaction
with discharge efficiency) of storage projects that are available to the optimization
without having to incur an investment cost. For example, it can be applied to
existing storage projects or to storage projects that will be built in the future and
whose capital costs we want to ignore (in the objective function).

It is not required to specify a capacity for all periods, i.e. a project can
be operational in some periods but not in others with no restriction on the
order and combination of periods. The user may specify a fixed O&M cost for
specified-storage projects, but this cost will be a fixed number in the
objective function and will therefore not affect any of the optimization
decisions.

.. note:: Please note that to calculate the duration of the storage project, i.e.,
    how long it can sustain discharging at its maximum output, you must adjust the
    energy capacity by the discharge efficiency. For example, a 1 MW  with 1 MWh energy
    capacity battery with discharging losses of 5% (discharging_loss_factor = 95%) would
    have a duration of 1 MWh / (1 MW/0.95) or 0.95 hours rather than 1 hour.

"""

import os.path
import pandas as pd
from pyomo.environ import Set, Param, NonNegativeReals

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.dynamic_components import capacity_type_operational_period_sets
from gridpath.auxiliary.validations import (
    get_projects,
    get_expected_dtypes,
    write_validation_to_database,
    validate_dtypes,
    validate_values,
    validate_idxs,
    validate_missing_inputs,
)
from gridpath.project.capacity.capacity_types.common_methods import (
    spec_get_inputs_from_database,
    spec_write_tab_file,
    spec_determine_inputs,
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
    | | :code:`STOR_SPEC_OPR_PRDS`                                            |
    |                                                                         |
    | Two-dimensional set of project-period combinations that helps describe  |
    | the project capacity available in a given period. This set is added to  |
    | the list of sets to join to get the final :code:`PRJ_OPR_PRDS` set      |
    | defined in **gridpath.project.capacity.capacity**.                      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`stor_spec_power_capacity_mw`                                   |
    | | *Defined over*: :code:`STOR_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The storage project's specified power capacity (in MW) in each          |
    | operational period.                                                     |
    +-------------------------------------------------------------------------+
    | | :code:`stor_spec_energy_capacity_mwh`                                 |
    | | *Defined over*: :code:`STOR_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The storage project's specified energy capacity (in MWh) in each        |
    | operational period.                                                     |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`stor_spec_fixed_cost_per_mw_yr`                                |
    | | *Defined over*: :code:`STOR_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`.                                                 |
    |                                                                         |
    | The storage project's fixed cost for the power components (in $ per     |
    | MW-yr.) in each operational period. This cost will be added to the      |
    | objective function but will not affect optimization decisions.          |
    +-------------------------------------------------------------------------+
    | | :code:`stor_spec_fixed_cost_per_stor_mwh_yr`                          |
    | | *Defined over*: :code:`STOR_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`.                                                 |
    |                                                                         |
    | The storage project's fixed cost for the energy components (in $ per    |
    | MWh-yr.) in each operational period. This cost will be added to the     |
    | objective function but will not affect optimization decisions.          |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.STOR_SPEC_OPR_PRDS = Set(dimen=2)

    # Required Params
    ###########################################################################

    m.stor_spec_power_capacity_mw = Param(m.STOR_SPEC_OPR_PRDS, within=NonNegativeReals)

    m.stor_spec_energy_capacity_mwh = Param(
        m.STOR_SPEC_OPR_PRDS, within=NonNegativeReals
    )

    m.stor_spec_fixed_cost_per_mw_yr = Param(
        m.STOR_SPEC_OPR_PRDS, within=NonNegativeReals, default=0
    )

    m.stor_spec_fixed_cost_per_stor_mwh_yr = Param(
        m.STOR_SPEC_OPR_PRDS, within=NonNegativeReals, default=0
    )

    # Dynamic Components
    ###########################################################################

    # Add to list of sets we'll join to get the final
    # PRJ_OPR_PRDS set
    getattr(d, capacity_type_operational_period_sets).append(
        "STOR_SPEC_OPR_PRDS",
    )


# Capacity Type Methods
###############################################################################


def capacity_rule(mod, g, p):
    """
    The power capacity of projects of the *stor_spec* capacity type is a
    pre-specified number for each of the project's operational periods.
    """
    return mod.stor_spec_power_capacity_mw[g, p]


def energy_stor_capacity_rule(mod, g, p):
    """
    The energy capacity of projects of the *stor_spec* capacity type is a
    pre-specified number for each of the project's operational periods.
    """
    return mod.stor_spec_energy_capacity_mwh[g, p]


def fixed_cost_rule(mod, g, p):
    """
    The fixed cost of projects of the *stor_spec* capacity type is a
    pre-specified number equal to the power capacity times the per-mw fixed
    cost plus the energy capacity times the per-mwh fixed cost for each of
    the project's operational periods.
    """
    return (
        mod.stor_spec_power_capacity_mw[g, p] * mod.stor_spec_fixed_cost_per_mw_yr[g, p]
        + mod.stor_spec_energy_capacity_mwh[g, p]
        * mod.stor_spec_fixed_cost_per_stor_mwh_yr[g, p]
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
    project_period_list, spec_params_dict = spec_determine_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        capacity_type="stor_spec",
    )

    data_portal.data()["STOR_SPEC_OPR_PRDS"] = {None: project_period_list}

    data_portal.data()["stor_spec_power_capacity_mw"] = spec_params_dict[
        "specified_capacity_mw"
    ]

    data_portal.data()["stor_spec_energy_capacity_mwh"] = spec_params_dict[
        "specified_stor_capacity_mwh"
    ]

    data_portal.data()["stor_spec_fixed_cost_per_mw_yr"] = spec_params_dict[
        "fixed_cost_per_mw_yr"
    ]

    data_portal.data()["stor_spec_fixed_cost_per_stor_mwh_yr"] = spec_params_dict[
        "fixed_cost_per_stor_mwh_yr"
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
        capacity_type="stor_spec",
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
    Get inputs from database and write out the model input .tab file
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

    stor_spec_params = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    projects = get_projects(
        conn, scenario_id, subscenarios, "capacity_type", "stor_spec"
    )

    # Convert input data into pandas DataFrame and extract data
    df = cursor_to_df(stor_spec_params)
    spec_projects = df["project"].unique()

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

    # Ensure project capacity is specified in at least 1 period
    msg = "Expected specified capacity for at least one period."
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
        errors=validate_idxs(
            actual_idxs=spec_projects, req_idxs=projects, idx_label="project", msg=msg
        ),
    )

    # Check for missing values (vs. missing row entries above); a NULL
    # energy capacity would otherwise surface only at model load
    cols = [
        "specified_capacity_mw",
        "specified_stor_capacity_mwh",
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
        db_table="inputs_project_specified_capacity",
        severity="High",
        errors=validate_missing_inputs(df, cols),
    )
