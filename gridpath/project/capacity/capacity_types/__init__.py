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
The **gridpath.project.capacity.capacity_types** package contains modules to
describe the various ways in which project capacity can be treated in the
optimization problem, e.g. as specified, available to be built, available to
be retired, etc.
"""

from gridpath.project.capacity.common_functions import (
    load_project_capacity_type_modules,
)
from gridpath.auxiliary.db_interface import get_required_capacity_types_from_database
from gridpath.auxiliary.validations import validate_period_wildcard_rows


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

    # Load in the required capacity type modules
    required_capacity_type_modules = get_required_capacity_types_from_database(
        conn,
        scenario_id,
    )
    imported_capacity_type_modules = load_project_capacity_type_modules(
        required_capacity_type_modules
    )

    # Specified fixed cost period wildcard rows that apply to no period
    validate_period_wildcard_rows(
        conn=conn,
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        gridpath_module=__name__,
        table="inputs_project_specified_fixed_cost",
        key_columns=["project", "project_specified_fixed_cost_scenario_id"],
        row_filter=f"""project_specified_fixed_cost_scenario_id =
            {subscenarios.PROJECT_SPECIFIED_FIXED_COST_SCENARIO_ID}
            AND project IN (
                SELECT project FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id =
                {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )""",
    )

    # Validate module-specific inputs
    for op_m in required_capacity_type_modules:
        if hasattr(imported_capacity_type_modules[op_m], "validate_inputs"):
            imported_capacity_type_modules[op_m].validate_inputs(
                scenario_id,
                subscenarios,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                conn,
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
    Get inputs from database and write out the model input .tab files
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """
    c = conn.cursor()
    # Load in the required capacity type modules

    required_capacity_type_modules = get_required_capacity_types_from_database(
        conn, scenario_id
    )
    imported_capacity_type_modules = load_project_capacity_type_modules(
        required_capacity_type_modules
    )

    # Get module-specific inputs
    for op_m in required_capacity_type_modules:
        if hasattr(imported_capacity_type_modules[op_m], "write_model_inputs"):
            imported_capacity_type_modules[op_m].write_model_inputs(
                scenario_directory,
                scenario_id,
                subscenarios,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                conn,
            )


# Capacity Type Module Method Defaults
###############################################################################
def capacity_rule(mod, prj, prd):
    """ """
    return 0


def energy_rule(mod, g, p):
    """ """
    return 0


def hyb_gen_capacity_rule(mod, prj, prd):
    """
    Power capacity of a hybrid project's generation component.
    """
    return 0


def hyb_stor_capacity_rule(mod, prj, prd):
    """
    Power capacity of a hybrid project's storage component.
    """
    return 0


def energy_stor_capacity_rule(mod, prj, prd):
    """ """
    return 0


def capacity_cost_rule(mod, prj, prd):
    """
    For new capacity investment separate from the fixed cost
    """
    return 0


def energy_cost_rule(mod, prj, prd):
    """
    For new energy purchases separate from the fixed cost
    """
    return 0


def fixed_cost_rule(mod, prj, prd):
    """ """
    return 0


def new_capacity_rule(mod, prj, prd):
    """
    New capacity built at project g in period p.
    """
    return 0


def new_energy_rule(mod, prj, prd):
    """
    New energy procured at project g in period p. This is NOT the storage
    energy capacity built.
    """
    return 0


def new_energy_stor_capacity_rule(mod, prj, prd):
    """
    Storage energy capacity; not used anywhere but here for clarity
    """
    return 0


def fuel_prod_capacity_rule(mod, prj, prd):
    """
    Fuel production capacity.
    """
    return 0


def fuel_release_capacity_rule(mod, prj, prd):
    """
    Fuel release capacity.
    """
    return 0


def fuel_storage_capacity_rule(mod, prj, prd):
    """
    Fuel storage capacity.
    """
    return 0
