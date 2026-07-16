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
This operational type describes the operational constraints on fuel production
facilities.

The type is associated with three main variables in each timepoint when the
project is available: the fuel production level, the fuel release level, and the
fuel available in storage. The first two are constrained to be less than
or equal to the project's fuel production and fuel release capacity respectively. The
third is constrained to be less than or equal to the project's fuel storage capacity.
The model tracks the amount of fuel available in storage in each timepoint based on the
fuel production and fuel release decisions in the previous timepoint. Fuel
production projects do not provide reserves or other system services.

Costs for this operational type include variable O&M costs, currently based on the
project's power consumption (note that this is applied through the generic
variable_om_cost_per_mwh parameter, which is specified in project.operatons.__init__.

Note that it is usually the case that you also need to enforce fuel burn limits to
ensure that only fuel produced by projects of this type can be used by other projects.

"""

import csv
import os.path
from pyomo.environ import Set, Param, Var, Constraint, NonNegativeReals, value

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_optype_model_data,
    check_for_tmps_to_link,
    validate_opchars,
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
    | | :code:`FUEL_PROD`                                                     |
    |                                                                         |
    | The set of projects of the :code:`fuel_prod` operational type.          |
    +-------------------------------------------------------------------------+
    | | :code:`FUEL_PROD_OPR_TMPS`                                            |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`fuel_prod`              |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`FUEL_PROD_LINKED_TMPS`                                         |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`fuel_prod`            |
    | operational type and their linked timepoints.                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`fuel_prod_powerunithour_per_fuelunit`                          |
    | | *Defined over*: :code:`FUEL_PROD`                                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's energy consumption to produce a unit of fuel.             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Produce_Fuel_FuelUnitPerHour`                                  |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Fuel production from this project in each timepoint in which the        |
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+
    | | :code:`Release_Fuel_FuelUnitPerHour`                                  |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Fuel release from this project in each timepoint in which the project   |
    | is operational (capacity exists and the project is available).          |
    +-------------------------------------------------------------------------+
    | | :code:`Fuel_Prod_Starting_Fuel_in_Storage_FuelUnit`                   |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The amount of fuel stored at this project at the start of each          |
    | timepoint, in FuelUnit of fuel stored.                                  |
    +-------------------------------------------------------------------------+
    | | :code:`Fuel_Prod_Consume_Power_PowerUnit`                             |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Power consumption to produce fuel at this project in each timepoint.    |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Fuel Production, Release, and Storage
    +-------------------------------------------------------------------------+
    | | :code:`Fuel_Prod_Max_Production_Constraint`                           |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    |                                                                         |
    | Limits the project's fuel production to the available production        |
    | capacity.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`Fuel_Prod_Max_Release_Constraint`                              |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    |                                                                         |
    | Limits the project's fuel release to the available release capacity.    |
    +-------------------------------------------------------------------------+
    | | :code:`Fuel_Prod_Fuel_Tracking_Constraint`                            |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    |                                                                         |
    | Tracks the amount of fuel stored in each timepoint based on the         |
    | previous timepoint's fuel stored and the fuel production and relea      |
    | decisions.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`Fuel_Prod_Max_Fuel_in_Storage_Constraint`                      |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    |                                                                         |
    | Limits the project's total fuel stored to the available fuel storag     |
    | capacity.                                                               |
    +-------------------------------------------------------------------------+
    | Power Consumption                                                       |
    +-------------------------------------------------------------------------+
    | | :code:`Fuel_Prod_Power_Consumption_in_Timepoint`                      |
    | | *Defined over*: :code:`FUEL_PROD_OPR_TMPS`                            |
    |                                                                         |
    | Enforces power consumption at this project when fuel is being produced. |
    +-------------------------------------------------------------------------+


    """
    # Sets
    ###########################################################################

    m.FUEL_PROD = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "fuel_prod"
        ),
    )

    m.FUEL_PROD_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.FUEL_PROD
        ),
    )

    # TODO: link fuel storage
    m.FUEL_PROD_LINKED_TMPS = Set(dimen=2)

    # Required Params
    ###########################################################################

    m.fuel_prod_powerunithour_per_fuelunit = Param(m.FUEL_PROD, within=NonNegativeReals)

    # Variables
    ###########################################################################

    m.Produce_Fuel_FuelUnitPerHour = Var(m.FUEL_PROD_OPR_TMPS, within=NonNegativeReals)

    m.Release_Fuel_FuelUnitPerHour = Var(m.FUEL_PROD_OPR_TMPS, within=NonNegativeReals)

    m.Fuel_Prod_Starting_Fuel_in_Storage_FuelUnit = Var(
        m.FUEL_PROD_OPR_TMPS, within=NonNegativeReals
    )

    m.Fuel_Prod_Consume_Power_PowerUnit = Var(
        m.FUEL_PROD_OPR_TMPS, within=NonNegativeReals
    )

    # Constraints
    ###########################################################################

    m.Fuel_Prod_Max_Production_Constraint = Constraint(
        m.FUEL_PROD_OPR_TMPS, rule=max_production_rule
    )

    m.Fuel_Prod_Max_Release_Constraint = Constraint(
        m.FUEL_PROD_OPR_TMPS, rule=max_release_rule
    )

    m.Fuel_Prod_Fuel_Tracking_Constraint = Constraint(
        m.FUEL_PROD_OPR_TMPS, rule=fuel_in_storage_tracking_rule
    )

    m.Fuel_Prod_Max_Fuel_in_Storage_Constraint = Constraint(
        m.FUEL_PROD_OPR_TMPS, rule=max_fuel_in_storage_rule
    )

    m.Fuel_Prod_Power_Consumption_in_Timepoint = Constraint(
        m.FUEL_PROD_OPR_TMPS, rule=fuel_prod_power_consumption_rule
    )


# Constraint Formulation Rules
###############################################################################


# Power and State of Charge
def max_production_rule(mod, prj, tmp):
    """
    **Constraint Name**: Fuel_Prod_Max_Production_Constraint
    **Enforced Over**: FUEL_PROD_OPR_TMPS

    Fuel production can't exceed available production capacity.
    """
    return (
        mod.Produce_Fuel_FuelUnitPerHour[prj, tmp]
        <= mod.Fuel_Production_Capacity_FuelUnitPerHour[prj, mod.period[tmp]]
        * mod.Availability_Derate[prj, tmp]
    )


def max_release_rule(mod, prj, tmp):
    """
    **Constraint Name**: Fuel_Prod_Max_Release_Constraint
    **Enforced Over**: FUEL_PROD_OPR_TMPS

    Fuel production can't exceed available production capacity.
    """
    return (
        mod.Release_Fuel_FuelUnitPerHour[prj, tmp]
        <= mod.Fuel_Release_Capacity_FuelUnitPerHour[prj, mod.period[tmp]]
        * mod.Availability_Derate[prj, tmp]
    )


def fuel_in_storage_tracking_rule(mod, prj, tmp):
    """
    **Constraint Name**: Fuel_Prod_Fuel_Tracking_Constraint
    **Enforced Over**: FUEL_PROD_OPR_TMPS

    The fuel in storage in each timepoint is equal to the fuel in storage in the
    previous timepoint plus fuel production in the previous timepoint (adjusted for
    timepoint duration) minus fuel release in the previous timepoint (adjusted for
    timepoint duration).
    """
    # No constraint enforced if this is the first timepoint of a linear horizon type
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[prj]
    ) and check_boundary_type(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[prj],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        # If the boundary type is linked, we need find the linked params; otherwise,
        # we look at the previous timepoint
        if check_if_first_timepoint(
            mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[prj]
        ) and check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[prj],
            boundary_type="linked",
        ):
            # prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            # prev_tmp_starting_energy_in_storage = (
            #     mod.stor_linked_starting_energy_in_storage[prj, 0]
            # )
            # prev_tmp_discharge = mod.stor_linked_discharge[prj, 0]
            # prev_tmp_charge = mod.stor_linked_charge[prj, 0]
            raise (
                "Linked horizons are not implemented yet for fuel production "
                "facilities."
            )
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]
            prev_tmp_starting_fuel_in_storage = (
                mod.Fuel_Prod_Starting_Fuel_in_Storage_FuelUnit[
                    prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
                ]
            )
            prev_tmp_production = mod.Produce_Fuel_FuelUnitPerHour[
                prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]
            prev_tmp_release = mod.Release_Fuel_FuelUnitPerHour[
                prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]

        return (
            mod.Fuel_Prod_Starting_Fuel_in_Storage_FuelUnit[prj, tmp]
            == prev_tmp_starting_fuel_in_storage
            + prev_tmp_production * prev_tmp_hrs_in_tmp
            - prev_tmp_release * prev_tmp_hrs_in_tmp
        )


def max_fuel_in_storage_rule(mod, prj, tmp):
    """
    **Constraint Name**: Fuel_Prod_Max_Fuel_in_Storage_Constraint
    **Enforced Over**: FUEL_PROD_OPR_TMPS

    The amount of fuel stored in each operational timepoint cannot exceed
    the available fuel storage capacity.
    """
    return (
        mod.Fuel_Prod_Starting_Fuel_in_Storage_FuelUnit[prj, tmp]
        <= mod.Fuel_Storage_Capacity_FuelUnit[prj, mod.period[tmp]]
        * mod.Availability_Derate[prj, tmp]
    )


def fuel_prod_power_consumption_rule(mod, prj, tmp):
    """ """
    return (
        mod.Fuel_Prod_Consume_Power_PowerUnit[prj, tmp]
        >= mod.Produce_Fuel_FuelUnitPerHour[prj, tmp]
        * mod.fuel_prod_powerunithour_per_fuelunit[prj]
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, prj, tmp):
    """
    Power provision is a load, so a negative number is returned here whenever fuel is
    being produced.
    """
    return -mod.Fuel_Prod_Consume_Power_PowerUnit[prj, tmp]


def variable_om_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.Fuel_Prod_Consume_Power_PowerUnit[prj, tmp]
        * mod.variable_om_cost_per_mwh[prj]
    )


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.Fuel_Prod_Consume_Power_PowerUnit[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.Fuel_Prod_Consume_Power_PowerUnit[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
    )


def fuel_contribution_rule(mod, prj, tmp):
    """
    Fuel burn returned is negative (i.e. added to the fuel availability)
    """
    return mod.Release_Fuel_FuelUnitPerHour[prj, tmp]


def power_delta_rule(mod, prj, tmp):
    """
    This isn't used downstream for now.
    """

    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[prj]
    ) and (
        check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[prj],
            boundary_type="linear",
        )
        or check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[prj],
            boundary_type="linked",
        )
    ):
        pass
    else:
        return (
            mod.Fuel_Prod_Consume_Power_PowerUnit[prj, tmp]
            - mod.Fuel_Prod_Consume_Power_PowerUnit[
                prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]
        )


# Validations
# TODO: validate that a fuel is specified for these projects


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
    load_optype_model_data(
        mod=mod,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="fuel_prod",
    )

    # # Linked timepoint params
    # linked_inputs_filename = os.path.join(
    #     scenario_directory,
    #     subproblem,
    #     stage,
    #     "inputs",
    #     "stor_linked_timepoint_params.tab",
    # )
    # if os.path.exists(linked_inputs_filename):
    #     data_portal.load(
    #         filename=linked_inputs_filename,
    #         index=mod.FUEL_PROD_LINKED_TMPS,
    #         param=(
    #             mod.stor_linked_starting_energy_in_storage,
    #             mod.stor_linked_discharge,
    #             mod.stor_linked_charge,
    #         ),
    #     )
    # else:
    #     pass


def add_to_prj_tmp_results(mod):
    results_columns = [
        "fuel_in_storage_fuelunit",
        "produce_fuel_fuelunitperhour",
        "release_fuel_fuelunitperhour",
        "fuel_prod_power_consumption_powerunit",
    ]
    data = [
        [
            prj,
            tmp,
            value(mod.Fuel_Prod_Starting_Fuel_in_Storage_FuelUnit[prj, tmp]),
            value(mod.Produce_Fuel_FuelUnitPerHour[prj, tmp]),
            value(mod.Release_Fuel_FuelUnitPerHour[prj, tmp]),
            value(mod.Fuel_Prod_Consume_Power_PowerUnit[prj, tmp]),
        ]
        for (prj, tmp) in mod.FUEL_PROD_OPR_TMPS
    ]

    optype_dispatch_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

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

    # Dispatch results added to project_timepoint.csv via add_to_prj_tmp_results()

    # # If there's a linked_subproblems_map CSV file, check which of the
    # # current subproblem TMPS we should export results for to link to the
    # # next subproblem
    # tmps_to_link, tmp_linked_tmp_dict = check_for_tmps_to_link(
    #     scenario_directory=scenario_directory, subproblem=subproblem, stage=stage
    # )
    #
    # # If the list of timepoints to link is not empty, write the linked
    # # timepoint results for this module in the next subproblem's input
    # # directory
    # if tmps_to_link:
    #     next_subproblem = str(int(subproblem) + 1)
    #
    #     # Export params by project and timepoint
    #     with open(
    #         os.path.join(
    #             scenario_directory,
    #             next_subproblem,
    #             stage,
    #             "inputs",
    #             "stor_linked_timepoint_params.tab",
    #         ),
    #         "w",
    #         newline="",
    #     ) as f:
    #         writer = csv.writer(f, delimiter="\t", lineterminator="\n")
    #         writer.writerow(
    #             [
    #                 "project",
    #                 "linked_timepoint",
    #                 "linked_starting_energy_in_storage",
    #                 "linked_discharge",
    #                 "linked_charge",
    #             ]
    #         )
    #         for (p, tmp) in sorted(mod.FUEL_PROD_OPR_TMPS):
    #             if tmp in tmps_to_link:
    #                 writer.writerow(
    #                     [
    #                         p,
    #                         tmp_linked_tmp_dict[tmp],
    #                         max(
    #                             value(mod.Stor_Starting_Energy_in_Storage_MWh[p, tmp]),
    #                             0,
    #                         ),
    #                         max(value(mod.Stor_Discharge_MW[p, tmp]), 0),
    #                         max(value(mod.Stor_Charge_MW[p, tmp]), 0),
    #                     ]
    #                 )


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
        "fuel_prod",
    )


# TODO: validate that these projects have only a single fuel specified
