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
Constraints on the minimum and maximum capacity build by vintage and the minimum and
maximum cumulative capacity by period.
"""

import csv
import os.path
from pyomo.environ import Param, Constraint, NonNegativeReals, Expression

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_row_monotonicity,
    validate_column_monotonicity,
)
from gridpath.auxiliary.auxiliary import get_required_subtype_modules
from gridpath.common_functions import (
    create_results_df,
    duals_wrapper,
    update_results_df,
)
from gridpath.project import PROJECT_PERIOD_DF
from gridpath.project.capacity.common_functions import (
    load_project_capacity_type_modules,
)
import gridpath.project.capacity.capacity_types as cap_type_init


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
    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`min_new_build_power`                                           |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The minimum amount of power capacity for a project to be built in a     |
    | certain period.                                                         |
    +-------------------------------------------------------------------------+
    | | :code:`max_new_build_power`                                           |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`Infinity`                                           |
    |                                                                         |
    | The maximum amount of power capacity for a project to be built in a     |
    | certain period.                                                         |
    +-------------------------------------------------------------------------+
    | | :code:`min_capacity_power`                                            |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The minimum amount of power capacity for a project in a certain period. |
    +-------------------------------------------------------------------------+
    | | :code:`max_capacity_power`                                            |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`Infinity`                                           |
    |                                                                         |
    | The maximum amount of power capacity for a project in a certain period. |
    +-------------------------------------------------------------------------+
    | | :code:`min_new_build_stor_energy`                                          |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The minimum amount of energy capacity for a project to be built in a    |
    | certain period.                                                         |
    +-------------------------------------------------------------------------+
    | | :code:`max_new_build_stor_energy`                                          |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`Infinity`                                           |
    |                                                                         |
    | The maximum amount of energy capacity for a project to be built in a    |
    | certain period.                                                         |
    +-------------------------------------------------------------------------+
    | | :code:`min_capacity_stor_energy`                                           |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The minimum amount of energy capacity for a project in a certain period.|
    +-------------------------------------------------------------------------+
    | | :code:`max_capacity_stor_energy`                                           |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`Infinity`                                           |
    |                                                                         |
    | The maximum amount of energy capacity for a project in a certain period.|
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Min_Build_Power_Constraint`                                    |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    |                                                                         |
    | Ensures that certain amount of power capacity must be built in a        |
    | particular period, based on :code:`min_new_build_power`.                |
    +-------------------------------------------------------------------------+
    | | :code:`Max_Build_Power_Constraint`                                    |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    |                                                                         |
    | Limits the amount of power capacity that can be built in a particular   |
    | period based on :code:`max_new_build_power`.                            |
    +-------------------------------------------------------------------------+
    | | :code:`Min_Power_Constraint`                                          |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    |                                                                         |
    | Ensures that certain amount of power capacity must exist in a certain   |
    | period, based on :code:`min_capacity_power`.                            |
    +-------------------------------------------------------------------------+
    | | :code:`Max_Power_Constraint`                                          |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    |                                                                         |
    | Limits the amount of power capacity that can exist in a certain period, |
    | based on :code:`max_capacity_power`.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`Min_Build_Stor_Energy_Constraint`                                   |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    |                                                                         |
    | Ensures that certain amount of energy capacity must be built in a       |
    | particular period, based on :code:`min_new_build_stor_energy`.               |
    +-------------------------------------------------------------------------+
    | | :code:`Max_Build_Stor_Energy_Constraint`                                   |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    |                                                                         |
    | Limits the amount of energy capacity that can be built in a particular  |
    | period based on :code:`max_new_build_stor_energy`.                           |
    +-------------------------------------------------------------------------+
    | | :code:`Min_Stor_Energy_Constraint`                                         |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    |                                                                         |
    | Ensures that certain amount of energy capacity must exist in a certain  |
    | period, based on :code:`min_capacity_stor_energy`.                           |
    +-------------------------------------------------------------------------+
    | | :code:`Max_Stor_Energy_Constraint`                                         |
    | | *Defined over*: :code:`PROJECTS`, :code:`PERIODS`                     |
    |                                                                         |
    | Limits the amount of energy capacity that can exist in a certain        |
    | period, based on :code:`max_capacity_stor_energy`.                           |
    +-------------------------------------------------------------------------+


    """
    # Import needed capacity type modules
    required_capacity_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="capacity_type",
    )

    imported_capacity_modules = load_project_capacity_type_modules(
        required_capacity_modules
    )

    def new_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        # The capacity type modules check if this period is a "vintage" for
        # this project and return 0 if not
        if hasattr(imported_capacity_modules[cap_type], "new_capacity_rule"):
            return imported_capacity_modules[cap_type].new_capacity_rule(mod, prj, prd)
        else:
            return cap_type_init.new_capacity_rule(mod, prj, prd)

    def new_energy_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        # The capacity type modules check if this period is a "vintage" for
        # this project and return 0 if not
        if hasattr(imported_capacity_modules[cap_type], "new_energy_rule"):
            return imported_capacity_modules[cap_type].new_energy_rule(mod, prj, prd)
        else:
            return cap_type_init.new_energy_rule(mod, prj, prd)

    def new_energy_stor_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        # The capacity type modules check if this period is a "vintage" for
        # this project and return 0 if not
        if hasattr(
            imported_capacity_modules[cap_type], "new_energy_stor_capacity_rule"
        ):
            return imported_capacity_modules[cap_type].new_energy_stor_capacity_rule(
                mod, prj, prd
            )
        else:
            return cap_type_init.new_energy_stor_capacity_rule(mod, prj, prd)

    # Optional Params
    ###########################################################################

    m.min_new_build_power = Param(
        m.PROJECTS, m.PERIODS, within=NonNegativeReals, default=0
    )

    m.max_new_build_power = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=float("inf"),
    )

    m.min_capacity_power = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=0,
    )

    m.max_capacity_power = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=float("inf"),
    )

    m.min_new_build_stor_energy = Param(
        m.PROJECTS, m.PERIODS, within=NonNegativeReals, default=0
    )

    m.max_new_build_stor_energy = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=float("inf"),
    )

    m.min_capacity_stor_energy = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=0,
    )

    m.max_capacity_stor_energy = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=float("inf"),
    )

    m.min_new_procured_energy = Param(
        m.PROJECTS, m.PERIODS, within=NonNegativeReals, default=0
    )

    m.max_new_procured_energy = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=float("inf"),
    )

    m.min_total_energy = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=0,
    )

    m.max_total_energy = Param(
        m.PROJECTS,
        m.PERIODS,
        within=NonNegativeReals,
        default=float("inf"),
    )

    # Constraints
    ###########################################################################

    # Power capacity
    def min_build_power_rule(mod, prj, prd):
        """
        **Constraint Name**: Min_Build_Power_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIODS

        Must build a certain amount of capacity in period.
        """
        if mod.min_new_build_power[prj, prd] == 0:
            return Constraint.Skip
        else:
            return new_capacity_rule(mod, prj, prd) >= mod.min_new_build_power[prj, prd]

    m.Min_Build_Power_Constraint = Constraint(m.PRJ_OPR_PRDS, rule=min_build_power_rule)

    def max_build_power_rule(mod, prj, prd):
        """
        **Constraint Name**: Max_Build_Power_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIODS

        Can't build more than certain amount of capacity in period.
        """
        if (
            mod.max_new_build_power[prj, prd] == float("inf")
            or "spec" in mod.capacity_type[prj]
        ):
            return Constraint.Skip
        else:
            return new_capacity_rule(mod, prj, prd) <= mod.max_new_build_power[prj, prd]

    m.Max_Build_Power_Constraint = Constraint(m.PRJ_OPR_PRDS, rule=max_build_power_rule)

    def min_power_rule(mod, prj, prd):
        """
        **Constraint Name**: Min_Power_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIOD

        Must have a certain amount of capacity in period.
        """
        if mod.min_capacity_power[prj, prd] == 0:
            return Constraint.Skip
        else:
            return mod.Capacity_MW[prj, prd] >= mod.min_capacity_power[prj, prd]

    m.Min_Power_Constraint = Constraint(m.PRJ_OPR_PRDS, rule=min_power_rule)

    def max_power_rule(mod, prj, prd):
        """
        **Constraint Name**: Max_Power_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIOD

        Can't have more than certain amount of capacity in period.
        """
        if mod.max_capacity_power[prj, prd] == float("inf"):
            return Constraint.Skip
        else:
            return mod.Capacity_MW[prj, prd] <= mod.max_capacity_power[prj, prd]

    m.Max_Power_Constraint = Constraint(m.PRJ_OPR_PRDS, rule=max_power_rule)

    # Energy storage capacity (this is not energy procurement)
    def min_build_stor_energy_rule(mod, prj, prd):
        """
        **Constraint Name**: Min_Build_Stor_Energy_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIODS

        Must build a certain amount of energy capacity in period.
        """
        if mod.min_new_build_stor_energy[prj, prd] == 0:
            return Constraint.Skip
        else:
            return (
                new_energy_stor_capacity_rule(mod, prj, prd)
                >= mod.min_new_build_stor_energy[prj, prd]
            )

    m.Min_Build_Stor_Energy_Constraint = Constraint(
        m.PRJ_OPR_PRDS, rule=min_build_stor_energy_rule
    )

    def max_build_stor_energy_rule(mod, prj, prd):
        """
        **Constraint Name**: Max_Build_Stor_Energy_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIODS

        Can't build more than certain amount of energy capacity in period.
        """
        if mod.max_new_build_stor_energy[prj, prd] == float("inf"):
            return Constraint.Skip
        else:
            return (
                new_energy_stor_capacity_rule(mod, prj, prd)
                <= mod.max_new_build_stor_energy[prj, prd]
            )

    m.Max_Build_Stor_Energy_Constraint = Constraint(
        m.PRJ_OPR_PRDS, rule=max_build_stor_energy_rule
    )

    def min_energy_rule(mod, prj, prd):
        """
        **Constraint Name**: Min_Stor_Energy_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIOD

        Must have a certain amount of energy capacity in period.
        """
        if mod.min_capacity_stor_energy[prj, prd] == 0:
            return Constraint.Skip
        else:
            return (
                mod.Energy_Storage_Capacity_MWh[prj, prd]
                >= mod.min_capacity_stor_energy[prj, prd]
            )

    m.Min_Stor_Energy_Constraint = Constraint(m.PRJ_OPR_PRDS, rule=min_energy_rule)

    def max_energy_rule(mod, prj, prd):
        """
        **Constraint Name**: Max_Stor_Energy_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIOD

        Can't have more than certain amount of energy capacity in period.
        """
        if mod.max_capacity_stor_energy[prj, prd] == float("inf"):
            return Constraint.Skip
        else:
            return (
                mod.Energy_Storage_Capacity_MWh[prj, prd]
                <= mod.max_capacity_stor_energy[prj, prd]
            )

    m.Max_Stor_Energy_Constraint = Constraint(m.PRJ_OPR_PRDS, rule=max_energy_rule)

    # Energy products
    def min_procured_energy_rule(mod, prj, prd):
        """
        **Constraint Name**: Min_Build_Energy_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIODS

        Must build a certain amount of capacity in period.
        """
        if mod.min_new_procured_energy[prj, prd] == 0:
            return Constraint.Skip
        else:
            return (
                new_energy_rule(mod, prj, prd) >= mod.min_new_procured_energy[prj, prd]
            )

    m.Min_Build_Energy_Constraint = Constraint(
        m.PRJ_OPR_PRDS, rule=min_procured_energy_rule
    )

    def max_procured_energy_rule(mod, prj, prd):
        """
        **Constraint Name**: Max_Build_Energy_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIODS

        Can't build more than certain amount of capacity in period.
        """
        if mod.max_new_procured_energy[prj, prd] == float("inf"):
            return Constraint.Skip
        else:
            return (
                new_energy_rule(mod, prj, prd) <= mod.max_new_procured_energy[prj, prd]
            )

    m.Max_Build_Energy_Constraint = Constraint(
        m.PRJ_OPR_PRDS, rule=max_procured_energy_rule
    )

    def min_energy_rule(mod, prj, prd):
        """
        **Constraint Name**: Min_Energy_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIOD

        Must have a certain amount of capacity in period.
        """
        if mod.min_total_energy[prj, prd] == 0:
            return Constraint.Skip
        else:
            return mod.Energy_MWh[prj, prd] >= mod.min_total_energy[prj, prd]

    m.Min_Energy_Constraint = Constraint(m.PRJ_OPR_PRDS, rule=min_energy_rule)

    def max_energy_rule(mod, prj, prd):
        """
        **Constraint Name**: Max_Energy_Constraint
        **Enforced Over**: m.PROJECTS, m.PERIOD

        Can't have more than certain amount of capacity in period.
        """
        if mod.max_total_energy[prj, prd] == float("inf"):
            return Constraint.Skip
        else:
            return mod.Energy_MWh[prj, prd] <= mod.max_total_energy[prj, prd]

    m.Max_Energy_Constraint = Constraint(m.PRJ_OPR_PRDS, rule=max_energy_rule)


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
    potentials_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "new_build_potentials.tab",
    )
    if os.path.exists(potentials_file):
        data_portal.load(
            filename=potentials_file,
            param=(
                m.min_new_build_power,
                m.max_new_build_power,
                m.min_capacity_power,
                m.max_capacity_power,
                m.min_new_build_stor_energy,
                m.max_new_build_stor_energy,
                m.min_capacity_stor_energy,
                m.max_capacity_stor_energy,
                m.min_new_procured_energy,
                m.max_new_procured_energy,
                m.min_total_energy,
                m.max_total_energy,
            ),
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
    c = conn.cursor()

    potentials = c.execute(
        """SELECT project, period, min_new_build_power, max_new_build_power,
            min_capacity_power, max_capacity_power,
            min_new_build_stor_energy, max_new_build_stor_energy,
            min_capacity_stor_energy, max_capacity_stor_energy,
            min_new_procured_energy, max_new_procured_energy,
            min_total_procured_energy, max_total_procured_energy
            FROM inputs_project_portfolios
            CROSS JOIN
            (SELECT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {temporal}) as relevant_vintages
            INNER JOIN (
            SELECT project, period, min_new_build_power, max_new_build_power,
            min_capacity_power, max_capacity_power,
            min_new_build_stor_energy, max_new_build_stor_energy,
            min_capacity_stor_energy, max_capacity_stor_energy,
            min_new_procured_energy, max_new_procured_energy,
            min_total_procured_energy, max_total_procured_energy
            FROM inputs_project_new_potential
            WHERE project_new_potential_scenario_id = {potential}) as potential
            USING (project, period)
            WHERE project_portfolio_scenario_id = {portfolio}
            """.format(
            temporal=subscenarios.TEMPORAL_SCENARIO_ID,
            potential=subscenarios.PROJECT_NEW_POTENTIAL_SCENARIO_ID,
            portfolio=subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    return potentials


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
    new_build_generator_vintage_costs.tab file
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    potentials = [
        row
        for row in get_model_inputs_from_database(
            scenario_id,
            subscenarios,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            conn,
        ).fetchall()
    ]

    if potentials:
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "new_build_potentials.tab",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(
                [
                    "project",
                    "period",
                    "min_new_build_power",
                    "max_new_build_power",
                    "min_capacity_power",
                    "max_capacity_power",
                    "min_new_build_stor_energy",
                    "max_new_build_stor_energy",
                    "min_capacity_stor_energy",
                    "max_capacity_stor_energy",
                    "min_new_procured_energy",
                    "max_new_procured_energy",
                    "min_total_procured_energy",
                    "max_total_procured_energy",
                ]
            )

            for row in potentials:
                replace_nulls = ["." if i is None else i for i in row]
                writer.writerow(replace_nulls)


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
    instance.constraint_indices["Min_Build_Power_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Max_Build_Power_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Min_Power_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Max_Power_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Min_Build_Stor_Energy_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Max_Build_Stor_Energy_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Min_Stor_Energy_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Max_Stor_Energy_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Min_Build_Energy_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Max_Build_Energy_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Min_Energy_Constraint"] = [
        "project",
        "period",
        "dual",
    ]

    instance.constraint_indices["Max_Energy_Constraint"] = [
        "project",
        "period",
        "dual",
    ]


def export_results(
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
    Export capacity results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    results_columns = [
        "min_build_power_dual",
        "max_build_power_dual",
        "min_total_power_dual",
        "max_total_power_dual",
        "min_build_stor_energy_dual",
        "max_build_stor_energy_dual",
        "min_total_stor_energy_dual",
        "max_total_stor_energy_dual",
        "min_build_energy_dual",
        "max_build_energy_dual",
        "min_total_energy_dual",
        "max_total_energy_dual",
    ]
    data = [
        [
            prj,
            prd,
            (
                duals_wrapper(m, getattr(m, "Min_Build_Power_Constraint")[prj, prd])
                if (prj, prd)
                in [idx for idx in getattr(m, "Min_Build_Power_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Max_Build_Power_Constraint")[prj, prd])
                if (prj, prd)
                in [idx for idx in getattr(m, "Max_Build_Power_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Min_Power_Constraint")[prj, prd])
                if (prj, prd) in [idx for idx in getattr(m, "Min_Power_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Max_Power_Constraint")[prj, prd])
                if (prj, prd) in [idx for idx in getattr(m, "Max_Power_Constraint")]
                else None
            ),
            (
                duals_wrapper(
                    m, getattr(m, "Min_Build_Stor_Energy_Constraint")[prj, prd]
                )
                if (prj, prd)
                in [idx for idx in getattr(m, "Min_Build_Stor_Energy_Constraint")]
                else None
            ),
            (
                duals_wrapper(
                    m, getattr(m, "Max_Build_Stor_Energy_Constraint")[prj, prd]
                )
                if (prj, prd)
                in [idx for idx in getattr(m, "Max_Build_Stor_Energy_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Min_Stor_Energy_Constraint")[prj, prd])
                if (prj, prd)
                in [idx for idx in getattr(m, "Min_Stor_Energy_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Max_Stor_Energy_Constraint")[prj, prd])
                if (prj, prd)
                in [idx for idx in getattr(m, "Max_Stor_Energy_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Min_Build_Energy_Constraint")[prj, prd])
                if (prj, prd)
                in [idx for idx in getattr(m, "Min_Build_Energy_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Max_Build_Energy_Constraint")[prj, prd])
                if (prj, prd)
                in [idx for idx in getattr(m, "Max_Build_Energy_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Min_Energy_Constraint")[prj, prd])
                if (prj, prd) in [idx for idx in getattr(m, "Min_Energy_Constraint")]
                else None
            ),
            (
                duals_wrapper(m, getattr(m, "Max_Energy_Constraint")[prj, prd])
                if (prj, prd) in [idx for idx in getattr(m, "Max_Energy_Constraint")]
                else None
            ),
        ]
        for (prj, prd) in m.PRJ_OPR_PRDS
    ]
    results_df = create_results_df(
        index_columns=["project", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PROJECT_PERIOD_DF), results_df)


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
    potentials = get_model_inputs_from_database(
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
    potentials_df = cursor_to_df(potentials)
    df_cols = potentials_df.columns

    cols = [
        "min_new_build_power",
        "max_new_build_power",
        "min_capacity_power",
        "max_capacity_power",
    ]
    # Check that maximum new build doesn't decrease
    if cols[1] in df_cols:
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_project_new_potential",
            severity="Mid",
            errors=validate_row_monotonicity(
                df=potentials_df, col=cols[1], rank_col="period"
            ),
        )

    # check that min build <= max build
    if set(cols).issubset(set(df_cols)):
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_project_new_potential",
            severity="High",
            errors=validate_column_monotonicity(
                df=potentials_df, cols=cols, idx_col=["project", "period"]
            ),
        )

    cols = ["min_capacity_stor_energy", "max_capacity_stor_energy"]
    # Check that maximum new build doesn't decrease - MWh
    if cols[1] in df_cols:
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_project_new_potential",
            severity="Mid",
            errors=validate_row_monotonicity(
                df=potentials_df, col=cols[1], rank_col="period"
            ),
        )

    # check that min build <= max build - MWh
    if set(cols).issubset(set(df_cols)):
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_project_new_potential",
            severity="High",
            errors=validate_column_monotonicity(
                df=potentials_df, cols=cols, idx_col=["project", "period"]
            ),
        )
