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
This capacity type describes fuel production facilities with exogenously specified
capacity characteristics.

Note that it is usually the case that you also need to enforce fuel burn limits to
ensure that only fuel produced by projects of this type (and potentially
'fuel_prod_new') can be used by other projects.
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
    | | :code:`FUEL_SPEC_OPR_PRDS`                                            |
    |                                                                         |
    | Two-dimensional set of project-period combinations that helps describe  |
    | the project capacity that exists in a period. This set is added to the  |
    | list of sets to join to get the final :code:`PRJ_OPR_PRDS` set defined  |
    | in **gridpath.project.capacity.capacity**.                              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`fuel_production_capacity_fuelunitperhour`                      |
    | | *Defined over*: :code:`FUEL_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's specified fuel production capacity (in fuel units         |
    | per hour, e.g. MMBtu/hour) in each operational period.                  |
    +-------------------------------------------------------------------------+
    | | :code:`fuel_release_capacity_fuelunitperhour`                         |
    | | *Defined over*: :code:`FUEL_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's specified fuel release capacity (in fuel units per hour,  |
    | e.g. MMBtu/hour) in each operational period.                            |
    +-------------------------------------------------------------------------+
    | | :code:`fuel_storage_capacity_fuelunit`                                |
    | | *Defined over*: :code:`FUEL_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's specified fuel storage capacity (in fuel units, e.g.      |
    | MMBtu) in each operational period.                                      |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr`    |
    | | *Defined over*: :code:`FUEL_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`.                                                 |
    |                                                                         |
    | The project's fixed cost for the fuel production components (in $ per   |
    | FuelUnitPerHour-yr.) in each operational period. This cost will be      |
    | added to the objective function but will not affect optimization        |
    | decisions.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr`       |
    | | *Defined over*: :code:`FUEL_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`.                                                 |
    |                                                                         |
    | The project's fixed cost for the fuel release components (in $ per      |
    | FuelUnitPerHour-yr.) in each operational period. This cost will be      |
    | added to the objective function but will not affect optimization        |
    | decisions.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`fuel_storage_capacity_fixed_cost_per_fuelunit_yr`              |
    | | *Defined over*: :code:`FUEL_SPEC_OPR_PRDS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`.                                                 |
    |                                                                         |
    | The project's fixed cost for the energy components (in $ per            |
    | FuelUnit-yr.) in each operational period. This cost will be added to    |
    | the objective function but will not affect optimization decisions.      |
    +-------------------------------------------------------------------------+
    """

    # Sets
    m.FUEL_SPEC_OPR_PRDS = Set(dimen=2)

    # Params
    m.fuel_production_capacity_fuelunitperhour = Param(
        m.FUEL_SPEC_OPR_PRDS, within=NonNegativeReals
    )

    m.fuel_release_capacity_fuelunitperhour = Param(
        m.FUEL_SPEC_OPR_PRDS, within=NonNegativeReals
    )

    m.fuel_storage_capacity_fuelunit = Param(
        m.FUEL_SPEC_OPR_PRDS, within=NonNegativeReals
    )

    m.fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr = Param(
        m.FUEL_SPEC_OPR_PRDS, within=NonNegativeReals, default=0
    )

    m.fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr = Param(
        m.FUEL_SPEC_OPR_PRDS, within=NonNegativeReals, default=0
    )

    m.fuel_storage_capacity_fixed_cost_per_fuelunit_yr = Param(
        m.FUEL_SPEC_OPR_PRDS, within=NonNegativeReals, default=0
    )

    # Dynamic Components
    ####################################################################################

    # Add to list of sets we'll join to get the final
    # PRJ_OPR_PRDS set
    getattr(d, capacity_type_operational_period_sets).append(
        "FUEL_SPEC_OPR_PRDS",
    )


# Capacity Type Methods
########################################################################################


def fuel_prod_capacity_rule(mod, prj, prd):
    """
    Fuel production capacity.
    """
    return mod.fuel_production_capacity_fuelunitperhour[prj, prd]


def fuel_release_capacity_rule(mod, prj, prd):
    """
    Fuel release capacity.
    """
    return mod.fuel_release_capacity_fuelunitperhour[prj, prd]


def fuel_storage_capacity_rule(mod, prj, prd):
    """
    Fuel storage capacity.
    """
    return mod.fuel_storage_capacity_fuelunit[prj, prd]


def fixed_cost_rule(mod, prj, prd):
    """
    The fixed cost of projects of the *fuel_spec* capacity type is a
    pre-specified number with the following costs:
    * fuel production capacity x fuel production fixed cost;
    * fuel release capacity x fuel release fixed cost;
    * fuel storage capacity x fuel storage fixed cost.
    """
    return (
        mod.fuel_production_capacity_fuelunitperhour[prj, prd]
        * mod.fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr[prj, prd]
        + mod.fuel_release_capacity_fuelunitperhour[prj, prd]
        * mod.fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr[prj, prd]
        + mod.fuel_storage_capacity_fuelunit[prj, prd]
        * mod.fuel_storage_capacity_fixed_cost_per_fuelunit_yr[prj, prd]
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
        capacity_type="fuel_prod_spec",
    )

    data_portal.data()["FUEL_SPEC_OPR_PRDS"] = {None: project_period_list}

    data_portal.data()["fuel_production_capacity_fuelunitperhour"] = spec_params_dict[
        "fuel_production_capacity_fuelunitperhour"
    ]

    data_portal.data()["fuel_release_capacity_fuelunitperhour"] = spec_params_dict[
        "fuel_release_capacity_fuelunitperhour"
    ]

    data_portal.data()["fuel_storage_capacity_fuelunit"] = spec_params_dict[
        "fuel_storage_capacity_fuelunit"
    ]

    data_portal.data()["fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr"] = (
        spec_params_dict["fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr"]
    )

    data_portal.data()["fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr"] = (
        spec_params_dict["fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr"]
    )

    data_portal.data()["fuel_storage_capacity_fixed_cost_per_fuelunit_yr"] = (
        spec_params_dict["fuel_storage_capacity_fixed_cost_per_fuelunit_yr"]
    )


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
        capacity_type="fuel_prod_spec",
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

    # Convert input data into pandas DataFrame
    df = cursor_to_df(stor_spec_params)

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
        capacity_type="fuel_prod_spec",
    )

    # Check for missing values (vs. missing row entries above)
    cols = [
        "fuel_production_capacity_fuelunitperhour",
        "fuel_release_capacity_fuelunitperhour",
        "fuel_storage_capacity_fuelunit",
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
