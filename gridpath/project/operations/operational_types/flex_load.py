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
This operational type describes a battery-based model for a flexible load
resource. Please use gen_spec as the 'capacity type' for flexible loads.

"""

import csv
import os.path
from pyomo.environ import (
    Var,
    Set,
    Constraint,
    Param,
    NonNegativeReals,
    PercentFraction,
    value,
)
import warnings

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
    write_tab_file_model_inputs,
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
    | | :code:`FLEX_LOAD`                                                     |
    |                                                                         |
    | The set of projects of the :code:`stor` operational type.               |
    +-------------------------------------------------------------------------+
    | | :code:`FLEX_LOAD_OPR_TMPS`                                            |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`stor`                   |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`FLEX_LOAD_LINKED_TMPS`                                         |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`stor`                 |
    | operational type and their linked timepoints.                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`flex_load_storage_efficiency`                                  |
    | | *Defined over*: :code:`FLEX_LOAD`                                     |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The flex load project's storage efficiency (1 = 100% efficient).        |
    +-------------------------------------------------------------------------+
    | | :code:`flex_load_charging_efficiency`                                 |
    | | *Defined over*: :code:`FLEX_LOAD`                                     |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The flex load project's charging efficiency (1 = 100% efficient).       |
    +-------------------------------------------------------------------------+
    | | :code:`flex_load_discharging_efficiency`                              |
    | | *Defined over*: :code:`FLEX_LOAD`                                     |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The flex load project's discharging efficiency (1 = 100% efficient).    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Linked Input Params                                                     |
    +=========================================================================+
    | | :code:`flex_load_linked_starting_energy_in_storage`                   |
    | | *Defined over*: :code:`FLEX_LOAD_LINKED_TMPS`                         |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's starting energy in storage in the linked timepoints.      |
    +-------------------------------------------------------------------------+
    | | :code:`flex_load_linked_discharge`                                    |
    | | *Defined over*: :code:`FLEX_LOAD_LINKED_TMPS`                         |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's dicharging in the linked timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`flex_load_linked_charge`                                       |
    | | *Defined over*: :code:`FLEX_LOAD_LINKED_TMPS`                         |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's charging in the linked timepoints.                        |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Flex_Load_Charge_MW`                                                |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Charging power in MW from this project in each timepoint in which the   |
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Discharge_MW`                                             |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Discharging power in MW from this project in each timepoint in which the|
    |  project is operational (capacity exists and the project is available). |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Starting_Energy_in_Storage_MWh`                           |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The state of charge of the flex load project at the start of each         |
    | timepoint, in MWh of energy stored.                                     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Power and Stage of Charge                                               |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Max_Charge_Constraint`                                    |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    |                                                                         |
    | Limits the project's charging power to the available capacity.          |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Max_Discharge_Constraint`                                 |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    |                                                                         |
    | Limits the project's discharging power to the available capacity.       |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Energy_Tracking_Constraint`                               |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    |                                                                         |
    | Tracks the amount of energy stored in each timepoint based on the       |
    | previous timepoint's energy stored and the charge and discharge         |
    | decisions.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Max_Energy_in_Storage_Constraint`                         |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    |                                                                         |
    | Limits the project's total energy stored to the available energy        |
    | capacity.                                                               |
    +-------------------------------------------------------------------------+
    | Reserves                                                                |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Max_Headroom_Power_Constraint`                            |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    |                                                                         |
    | Limits the project's upward reserves based on available headroom.       |
    | Going from charging to non-charging also counts as headroom, doubling   |
    | the maximum amount of potential headroom.                               |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Max_Footroom_Power_Constraint`                            |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    |                                                                         |
    | Limits the project's downward reserves based on available footroom.     |
    | Going from non-charging to charging also counts as footroom, doubling   |
    | the maximum amount of potential footroom.                               |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Max_Headroom_Energy_Constraint`                           |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    |                                                                         |
    | Can't provide more upward reserves (times sustained duration required)  |
    | than available energy in storage in that timepoint.                     |
    +-------------------------------------------------------------------------+
    | | :code:`Flex_Load_Max_Footroom_Energy_Constraint`                           |
    | | *Defined over*: :code:`FLEX_LOAD_OPR_TMPS`                            |
    |                                                                         |
    | Can't provide more downard reserves (times sustained duration required) |
    | than available capacity to store energy in that timepoint.              |
    +-------------------------------------------------------------------------+



    """
    # Sets
    ###########################################################################

    m.FLEX_LOAD = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "flex_load"
        ),
    )

    m.FLEX_LOAD_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.FLEX_LOAD
        ),
    )

    m.FLEX_LOAD_LINKED_TMPS = Set(dimen=2)

    # Required Params
    ###########################################################################

    m.flex_load_static_profile_mw = Param(m.FLEX_LOAD_OPR_TMPS, within=NonNegativeReals)

    m.flex_load_maximum_stored_energy_mwh = Param(
        m.FLEX_LOAD_OPR_TMPS, within=NonNegativeReals
    )

    m.flex_load_charging_efficiency = Param(
        m.FLEX_LOAD, within=PercentFraction, default=1
    )
    m.flex_load_discharging_efficiency = Param(
        m.FLEX_LOAD, within=PercentFraction, default=1
    )
    m.flex_load_storage_efficiency = Param(
        m.FLEX_LOAD, within=PercentFraction, default=1
    )

    # Linked Params
    ###########################################################################

    m.flex_load_linked_starting_energy_in_storage = Param(
        m.FLEX_LOAD_LINKED_TMPS, within=NonNegativeReals
    )

    m.flex_load_linked_discharge = Param(
        m.FLEX_LOAD_LINKED_TMPS, within=NonNegativeReals
    )

    m.flex_load_linked_charge = Param(m.FLEX_LOAD_LINKED_TMPS, within=NonNegativeReals)

    # Variables
    ###########################################################################

    m.Flex_Load_Grid_MW = Var(m.FLEX_LOAD_OPR_TMPS, within=NonNegativeReals)

    m.Flex_Load_Charge_MW = Var(m.FLEX_LOAD_OPR_TMPS, within=NonNegativeReals)

    m.Flex_Load_Discharge_MW = Var(m.FLEX_LOAD_OPR_TMPS, within=NonNegativeReals)

    m.Flex_Load_Starting_Energy_in_Storage_MWh = Var(
        m.FLEX_LOAD_OPR_TMPS, within=NonNegativeReals
    )

    # Constraints
    ###########################################################################

    # Power and State of Charge
    m.Flex_Load_Max_Grid_Load_Constraint = Constraint(
        m.FLEX_LOAD_OPR_TMPS, rule=max_grid_load_constraint_rule
    )

    m.Flex_Load_Level_of_Service_Constraint = Constraint(
        m.FLEX_LOAD_OPR_TMPS, rule=level_of_service_constraint_rule
    )

    m.Flex_Load_Energy_Tracking_Constraint = Constraint(
        m.FLEX_LOAD_OPR_TMPS, rule=energy_tracking_rule
    )

    m.Flex_Load_Max_Energy_in_Storage_Constraint = Constraint(
        m.FLEX_LOAD_OPR_TMPS, rule=max_energy_in_storage_constraint_rule
    )


# Constraint Formulation Rules
###############################################################################


# Power and State of Charge
def max_grid_load_constraint_rule(mod, prj, tmp):
    """
    **Constraint Name**: Flex_Load_Max_Grid_Load_Constraint
    **Enforced Over**: FLEX_LOAD_OPR_TMPS

    The maximum load on the grid after shifting cannot exceed a pre-specified level in any timepoint.
    """
    return (
        mod.Flex_Load_Grid_MW[prj, tmp]
        <= mod.Capacity_MW[prj, mod.period[tmp]] * mod.Availability_Derate[prj, tmp]
    )


def level_of_service_constraint_rule(mod, prj, tmp):
    """
    **Constraint Name**: Flex_Load_Level_of_Service_Constraint
    **Enforced Over**: FLEX_LOAD_OPR_TMPS

    The static load-based level of service must be maintained.
    """
    return (
        mod.Flex_Load_Grid_MW[prj, tmp]
        - mod.Flex_Load_Charge_MW[prj, tmp]
        + mod.Flex_Load_Discharge_MW[prj, tmp]
        == mod.flex_load_static_profile_mw[prj, tmp]
    )


def energy_tracking_rule(mod, prj, tmp):
    """
    **Constraint Name**: Flex_Load_Energy_Tracking_Constraint
    **Enforced Over**: FLEX_LOAD_OPR_TMPS

    The energy stored in each timepoint is equal to the energy stored in the
    previous timepoint minus any discharged power (adjusted for discharging
    efficiency and timepoint duration) plus any charged power (adjusted for
    charging efficiency and timepoint duration).
    """
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
        if check_if_first_timepoint(
            mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[prj]
        ) and check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[prj],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_starting_energy_in_storage = (
                mod.flex_load_linked_starting_energy_in_storage[prj, 0]
            )
            prev_tmp_discharge = mod.flex_load_linked_discharge[prj, 0]
            prev_tmp_charge = mod.flex_load_linked_charge[prj, 0]

            calculated_starting_energy_in_storage = (
                prev_tmp_starting_energy_in_storage
                * mod.flex_load_storage_efficiency[prj]
                + prev_tmp_charge
                * prev_tmp_hrs_in_tmp
                * mod.flex_load_charging_efficiency[prj]
                - prev_tmp_discharge
                * prev_tmp_hrs_in_tmp
                / mod.flex_load_discharging_efficiency[prj]
            )

            # Deal with possible precision-related infeasibilities, e.g. if
            # the calculated energy in storage is just below or just above
            # its boundaries of 0 and the energy capacity x availability
            if calculated_starting_energy_in_storage < 0:
                warnings.warn(
                    f"Starting energy in storage was "
                    f"{calculated_starting_energy_in_storage} for project "
                    f"{prj}, "
                    f"which would have resulted in infeasibility. "
                    f"Changed to 0."
                )
                return mod.Flex_Load_Starting_Energy_in_Storage_MWh[prj, tmp] == 0
            elif calculated_starting_energy_in_storage > (
                mod.flex_load_maximum_stored_energy_mwh[prj, tmp]
            ):
                warnings.warn(
                    f"Starting energy in storage was "
                    f"{calculated_starting_energy_in_storage} for project "
                    f"{prj}, "
                    f"which would have resulted in infeasibility. "
                    f"Changed to "
                    f"mod.flex_load_maximum_stored_energy_mwh[prj, tmp]."
                )
                return (
                    mod.Flex_Load_Starting_Energy_in_Storage_MWh[prj, tmp]
                    == mod.flex_load_maximum_stored_energy_mwh[prj, tmp]
                )
            else:
                return (
                    mod.Flex_Load_Starting_Energy_in_Storage_MWh[prj, tmp]
                    == calculated_starting_energy_in_storage
                )

        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]
            prev_tmp_starting_energy_in_storage = (
                mod.Flex_Load_Starting_Energy_in_Storage_MWh[
                    prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
                ]
            )
            prev_tmp_discharge = mod.Flex_Load_Discharge_MW[
                prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]
            prev_tmp_charge = mod.Flex_Load_Charge_MW[
                prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]

            return (
                mod.Flex_Load_Starting_Energy_in_Storage_MWh[prj, tmp]
                == prev_tmp_starting_energy_in_storage
                * mod.flex_load_storage_efficiency[prj]
                + prev_tmp_charge
                * prev_tmp_hrs_in_tmp
                * mod.flex_load_charging_efficiency[prj]
                - prev_tmp_discharge
                * prev_tmp_hrs_in_tmp
                / mod.flex_load_discharging_efficiency[prj]
            )


def max_energy_in_storage_constraint_rule(mod, prj, tmp):
    """
    **Constraint Name**: Flex_Load_Max_Energy_in_Storage_Constraint
    **Enforced Over**: FLEX_LOAD_OPR_TMPS

    The amount of energy stored in each operational timepoint cannot exceed
    the available energy capacity.
    """
    return (
        mod.Flex_Load_Starting_Energy_in_Storage_MWh[prj, tmp]
        <= mod.flex_load_maximum_stored_energy_mwh[prj, tmp]
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, prj, tmp):
    """
    Negative of the shifted load.
    """
    return mod.flex_load_static_profile_mw[prj, tmp] - mod.Flex_Load_Grid_MW[prj, tmp]


def power_delta_rule(mod, g, tmp):
    """
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
        return power_provision_rule(mod, g, tmp) - power_provision_rule(
            mod, g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
        )


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
        op_type="flex_load",
    )

    flex_load_profiles_file = os.path.join(
        scenario_directory,
        subproblem,
        stage,
        "inputs",
        "flex_load_profiles.tab",
    )

    data_portal.load(
        filename=flex_load_profiles_file,
        param=(
            mod.flex_load_static_profile_mw,
            mod.flex_load_maximum_stored_energy_mwh,
        ),
    )

    # Linked timepoint params
    linked_inputs_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "flex_load_linked_timepoint_params.tab",
    )
    if os.path.exists(linked_inputs_filename):
        data_portal.load(
            filename=linked_inputs_filename,
            index=mod.FLEX_LOAD_LINKED_TMPS,
            param=(
                mod.flex_load_linked_starting_energy_in_storage,
                mod.flex_load_linked_discharge,
                mod.flex_load_linked_charge,
            ),
        )


def add_to_prj_tmp_results(mod):
    results_columns = [
        "static_load_mw",
        "flex_load_mw",
        "starting_energy_mwh",
        "charge_mw",
        "discharge_mw",
    ]
    data = [
        [
            prj,
            tmp,
            mod.flex_load_static_profile_mw[prj, tmp],
            value(mod.Flex_Load_Grid_MW[prj, tmp]),
            value(mod.Flex_Load_Starting_Energy_in_Storage_MWh[prj, tmp]),
            value(mod.Flex_Load_Charge_MW[prj, tmp]),
            value(mod.Flex_Load_Discharge_MW[prj, tmp]),
        ]
        for (prj, tmp) in mod.FLEX_LOAD_OPR_TMPS
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

    # If there's a linked_subproblems_map CSV file, check which of the
    # current subproblem TMPS we should export results for to link to the
    # next subproblem
    tmps_to_link, tmp_linked_tmp_dict = check_for_tmps_to_link(
        scenario_directory=scenario_directory, subproblem=subproblem, stage=stage
    )

    # If the list of timepoints to link is not empty, write the linked
    # timepoint results for this module in the next subproblem's input
    # directory
    if tmps_to_link:
        next_subproblem = str(int(subproblem) + 1)

        # Export params by project and timepoint
        with open(
            os.path.join(
                scenario_directory,
                next_subproblem,
                stage,
                "inputs",
                "flex_load_linked_timepoint_params.tab",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(
                [
                    "project",
                    "linked_timepoint",
                    "linked_starting_energy_in_storage",
                    "linked_discharge",
                    "linked_charge",
                ]
            )
            for p, tmp in sorted(mod.FLEX_LOAD_OPR_TMPS):
                if tmp in tmps_to_link:
                    writer.writerow(
                        [
                            p,
                            tmp_linked_tmp_dict[tmp],
                            max(
                                value(
                                    mod.Flex_Load_Starting_Energy_in_Storage_MWh[p, tmp]
                                ),
                                0,
                            ),
                            max(value(mod.Flex_Load_Discharge_MW[p, tmp]), 0),
                            max(value(mod.Flex_Load_Charge_MW[p, tmp]), 0),
                        ]
                    )


# ### Database ### #
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
    subproblem_for_db = 1 if subproblem == "" else subproblem
    stage_for_db = 1 if stage == "" else stage

    c = conn.cursor()
    # NOTE: There can be cases where a resource is both in specified capacity
    # table and in new build table, but depending on capacity type you'd only
    # use one of them, so filtering with OR is not 100% correct.

    sql = f"""
        SELECT project, timepoint, static_load_mw, maximum_stored_energy_mwh
        -- Select only projects, periods, horizons from the relevant portfolio, 
        -- relevant opchar scenario id, operational type, 
        -- and temporal scenario id
        FROM 
            (SELECT project, stage_id, timepoint, 
            flex_load_static_profile_scenario_id
            FROM project_operational_timepoints
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            AND project_operational_chars_scenario_id = {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
            AND operational_type = 'flex_load'
            AND temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND (project_specified_capacity_scenario_id = {subscenarios.PROJECT_SPECIFIED_CAPACITY_SCENARIO_ID}
                 OR project_new_cost_scenario_id = {subscenarios.PROJECT_NEW_COST_SCENARIO_ID})
            AND subproblem_id = {subproblem_for_db}
            AND stage_id = {stage_for_db}
            ) as projects_periods_timepoints_tbl
        -- Now that we have the relevant projects and timepoints, get the 
        -- respective cap factors (and no others) from 
        -- inputs_project_flex_load_static_profiles
        LEFT OUTER JOIN
            inputs_project_flex_load_static_profiles
        USING (flex_load_static_profile_scenario_id, project, 
        stage_id, timepoint)
        ;
        """

    data = c.execute(sql)

    fname = "flex_load_profiles.tab"

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


# ### VALIDATION ### #
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
        "flex_load",
    )
