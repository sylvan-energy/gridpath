# Copyright 2016-2023 Blue Marble Analytics LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writinprj, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This operational type describes a tightly-coupled variable resource and
storage hybrid project, e.g. solar and battery hybrid project where the
battery can only charge from the solar component and not from the grid,
and the total power output of the project from the solar and battery
components is limited separately from each individual component.

We track power availability from the variable resource via a capacity factor
parameter and the amount of power that goes directly to the grid and the
amount that is stored. The former is limited by the power capacity of the
generator component and the latter by the charging power capacity of the
battery. The model tracks the state of charge of the battery. Total grid
power output from the project (from the generator component and from storage
discharging) is limited by the project's nameplate capacity. This
operational type can also be curtailed, and can provide both upward and
downward reserves.

Costs for this operational type include variable O&M costs and, optionally,
a cost on curtailment.

.. warning::
    This module has not been extensively used and vetted, so be extra vigilant
    for buggy behavior.
"""

import csv
import os.path
from pyomo.environ import (
    Param,
    Set,
    Var,
    Constraint,
    NonNegativeReals,
    PercentFraction,
    Expression,
    value,
)

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import (
    footroom_variables,
    headroom_variables,
    reserve_variable_derate_params,
)
from gridpath.project.operations.reserves.reserve_aggregation import (
    derated_headroom_provision_rule,
    derated_footroom_provision_rule,
)
from gridpath.project.operations.operational_types.stor import (
    check_for_soc_infeasibilities,
)
from gridpath.project.operations.reserves.subhourly_energy_adjustment import (
    footroom_subhourly_energy_adjustment_rule,
    headroom_subhourly_energy_adjustment_rule,
)
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_var_profile_inputs,
    get_prj_temporal_index_opr_inputs_from_db,
    write_tab_file_model_inputs,
    validate_opchars,
    validate_var_profiles,
    load_optype_model_data,
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
    | | :code:`GEN_VAR_STOR_HYB`                                              |
    |                                                                         |
    | The set of generators of the :code:`gen_var_stor_hyb` operational type. |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                                     |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_var_stor_hyb`     |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_var_stor_hyb_cap_factor`                                   |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB`                              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's power output in each operational timepoint as a fraction  |
    | of its available capacity (i.e. the capacity factor).                   |
    +-------------------------------------------------------------------------+
    | | :code:`gen_var_stor_hyb_charging_efficiency`                          |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB`                              |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The project's storage component charging efficiency (1 = 100%           |
    | efficient).                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`gen_var_stor_hyb_discharging_efficiency`                       |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB`                              |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The project's storage component discharging efficiency (1 = 100%        |
    | efficient).                                                             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_var_stor_hyb_cap_factor_default`                           |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB`                              |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | Optional default value for gen_var_stor_hyb_cap_factor. Use with        |
    | caution.                                                                |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenVarStorHyb_Provide_Power_MW`                                |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Power provision in MW from this project in each timepoint in which the  |
    | project is operational (capacity exists and the project is available).  |
    | This can come either directly from the variable resource via the        |
    | the generator component or from the storage component.                  |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Charge_MW`                                       |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Charging power in MW from this project in each timepoint in which the   |
    | project is operational (capacity exists and the project is available).  |
    | This operational type can only charge from the variable resource, not   |
    | from the grid.                                                          |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Discharge_MW`                                    |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Discharging power in MW from this project in each timepoint in which the|
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Starting_Energy_in_Storage_MWh`                  |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The state of charge of the project's storage component  at the start of |
    | each timepoint, in MWh of energy stored.                                |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`GenVarStorHyb_Available_Gen_Power_MW`                          |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | The available power from the variable resource.                         |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Scheduled_Curtailment_MW`                        |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | The available power minus what was actually provided (in MW).           |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Subtimepoint_Curtailment_MW`                     |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | Curtailment resulting from provision of downward reserves.              |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Total_Curtailment_MW`                            |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | Scheduled curtailment (in MW) plus an upward adjustment for additional  |
    | curtailment when providing downward reserves, and a downward adjustment |
    | adjustment for a reduction in curtailment when providing upward         |
    | reserves, to account for sub-hourly dispatch when providing reserves.   |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Subtimepoint_Energy_Delivered_MW`                |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | Delivered energy resulting from provision of upward reserves.           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`GenVarStorHyb_Max_Power_Constraint`                            |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | The project's power and upward reserves cannot exceed the available     |
    | capacity.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Max_Available_Power_Constraint`                  |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | Limits the power plus upward reserves in each timepoint based on the    |
    | product of :code:`gen_var_stor_hyb_cap_factor` and the available        |
    | capacity (available power) plus the net power from storage.             |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Min_Power_Constraint`                            |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | Power provision minus downward reserves should be greater than or equal |
    | to zero. We are assuming that the hybrid storage cannot charge from the |
    | grid (so power provision cannot go negative).                           |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Max_Charge_Constraint`                           |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | Storage charging power can't exceed available storage component         |
    | capacity.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Max_Discharge_Constraint`                        |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | Storage discharging power can't exceed available storage component      |
    | capacity.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Energy_Tracking_Constraint`                      |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | The energy stored in each timepoint is equal to the energy stored in    |
    | the previous timepoint minus any discharged power (adjusted for         |
    | discharging efficiency and timepoint duration) plus any charged power   |
    | (adjusted for charging efficiency and timepoint duration).              |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Max_Energy_in_Storage_Constraint`                |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    | The amount of energy stored in each operational timepoint cannot exceed |
    | the available energy capacity.                                          |
    +-------------------------------------------------------------------------+
    | | :code:`GenVarStorHyb_Max_Stor_Headroom_Power_Constraint`              |
    | | *Defined over*: :code:`GEN_VAR_STOR_HYB_OPR_TMPS`                     |
    |                                                                         |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################
    m.GEN_VAR_STOR_HYB = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_var_stor_hyb"
        ),
    )

    m.GEN_VAR_STOR_HYB_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.GEN_VAR_STOR_HYB,
        ),
    )

    # Optional Params
    ###########################################################################
    # Use with caution
    m.gen_var_stor_hyb_cap_factor_default = Param(
        m.GEN_VAR_STOR_HYB,
        within=NonNegativeReals | {"undefined"},
        initialize="undefined",
    )

    # Required Params
    ###########################################################################

    m.gen_var_stor_hyb_cap_factor = Param(
        m.GEN_VAR_STOR_HYB_OPR_TMPS,
        within=NonNegativeReals,
        default=lambda mod, prj, tmp: mod.gen_var_stor_hyb_cap_factor_default[prj],
    )

    m.gen_var_stor_hyb_charging_efficiency = Param(
        m.GEN_VAR_STOR_HYB, within=PercentFraction
    )

    m.gen_var_stor_hyb_discharging_efficiency = Param(
        m.GEN_VAR_STOR_HYB, within=PercentFraction
    )

    # Optional Params
    ###########################################################################

    m.gen_var_stor_hyb_upward_reserves_to_soc_depletion = Param(
        m.GEN_VAR_STOR_HYB, default=0
    )

    # Variables
    ###########################################################################

    m.GenVarStorHyb_Provide_Power_MW = Var(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, within=NonNegativeReals
    )

    m.GenVarStorHyb_Charge_MW = Var(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, within=NonNegativeReals
    )

    m.GenVarStorHyb_Discharge_MW = Var(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, within=NonNegativeReals
    )

    m.GenVarStorHyb_Starting_Energy_in_Storage_MWh = Var(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, within=NonNegativeReals
    )

    m.GenVarStorHyb_Upward_Reserves_from_Gen_MW = Var(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, within=NonNegativeReals
    )

    m.GenVarStorHyb_Upward_Reserves_from_Stor_MW = Var(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, within=NonNegativeReals
    )

    # Expressions
    ###########################################################################

    def available_power_rule(mod, prj, tmp):
        """
        The amount of power from the variable resource generation component
        (e.g. solar field) available in every timepoint.
        """
        return (
            mod.Hyb_Gen_Capacity_MW[prj, mod.period[tmp]]
            * mod.Availability_Derate[prj, tmp]
            * mod.gen_var_stor_hyb_cap_factor[prj, tmp]
        )

    m.GenVarStorHyb_Available_Gen_Power_MW = Expression(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=available_power_rule
    )

    def upwards_reserve_rule(mod, prj, tmp):
        """
        Gather all headroom variables, and de-rate the total reserves offered
        to account for the fact that gen_var_stor_hyb output is uncertain.
        """
        return derated_headroom_provision_rule(d, mod, prj, tmp)

    m.GenVarStorHyb_Upward_Reserves_MW = Expression(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=upwards_reserve_rule
    )

    def downwards_reserve_rule(mod, prj, tmp):
        """
        Gather all footroom variables, and de-rate the total reserves offered
        to account for the fact that gen_var_stor_hyb output is uncertain.
        """
        return derated_footroom_provision_rule(d, mod, prj, tmp)

    m.GenVarStorHyb_Downward_Reserves_MW = Expression(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=downwards_reserve_rule
    )

    def subtimepoint_curtailment_expression_rule(mod, prj, tmp):
        """
        Sub-hourly curtailment from providing downward reserves.
        """
        return footroom_subhourly_energy_adjustment_rule(d, mod, prj, tmp)

    m.GenVarStorHyb_Subtimepoint_Curtailment_MW = Expression(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=subtimepoint_curtailment_expression_rule
    )

    def subtimepoint_delivered_energy_expression_rule(mod, prj, tmp):
        """
        Sub-hourly energy delivered from providing upward reserves.
        """
        return headroom_subhourly_energy_adjustment_rule(d, mod, prj, tmp)

    m.GenVarStorHyb_Subtimepoint_Energy_Delivered_MW = Expression(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=subtimepoint_delivered_energy_expression_rule
    )

    m.GenVarStorHyb_Scheduled_Curtailment_MW = Expression(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=scheduled_curtailment_expression_rule
    )

    m.GenVarStorHyb_Total_Curtailment_MW = Expression(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=total_curtailment_expression_rule
    )

    # Constraints
    ###########################################################################

    m.GenVarStorHyb_Max_Power_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=max_power_rule
    )

    m.GenVarStorHyb_Max_Available_Power_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=max_available_power_rule
    )

    m.GenVarStorHyb_Min_Power_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=min_power_rule
    )

    m.GenVarStorHyb_Max_Charge_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=max_charge_rule
    )

    m.GenVarStorHyb_Max_Discharge_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=max_discharge_rule
    )

    m.GenVarStorHyb_Energy_Tracking_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=energy_tracking_rule
    )

    m.GenVarStorHyb_Max_Energy_in_Storage_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=max_energy_in_storage_rule
    )

    m.GenVarStorHyb_Max_Stor_Headroom_Power_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=max_stor_headroom_power_rule
    )

    m.GenVarStorHyb_Max_Stor_Headroom_Energy_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=max_stor_headroom_energy_rule
    )

    m.GenVarStorHyb_Total_Upward_Reserves_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=total_upward_reserves_rule
    )

    m.GenVarStorHyb_Max_Upward_Reserves_from_Gen_Constraint = Constraint(
        m.GEN_VAR_STOR_HYB_OPR_TMPS, rule=max_upward_reserves_from_gen_rule
    )


# Expression Methods
###############################################################################


def scheduled_curtailment_expression_rule(mod, prj, tmp):
    """
    **Expression Name**: GenVarStorHyb_Scheduled_Curtailment_MW
    **Defined Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    Scheduled curtailment is the available power (variable resource + net
    power from storage) minus what was actually provided to the grid.
    """
    return (
        mod.GenVarStorHyb_Available_Gen_Power_MW[prj, tmp]
        + mod.GenVarStorHyb_Discharge_MW[prj, tmp]
        - mod.GenVarStorHyb_Charge_MW[prj, tmp]
        - mod.GenVarStorHyb_Provide_Power_MW[prj, tmp]
    )


def total_curtailment_expression_rule(mod, prj, tmp):
    """
    **Expression Name**: GenVarStorHyb_Total_Curtailment_MW
    **Defined Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    Available energy that was not delivered includes the scheduled
    curtailment plus an adjustment for subtimepoint reserve provision.

    There's an adjustment for subtimepoint reserve provision:
    1) if downward reserves are provided, they will be called upon
    occasionally, so power provision will have to decrease and additional
    curtailment will be incurred;
    2) if upward reserves are provided (energy is being curtailed),
    they will be called upon occasionally, so power provision will have to
    increase and less curtailment will be incurred
    The subtimepoint adjustment here is a simple linear function of reserve

    Assume cap factors don't incorporate availability derates,
    so don't multiply capacity by Availability_Derate here (will count
    as curtailment).
    """

    return (
        scheduled_curtailment_expression_rule(mod, prj, tmp)
        + mod.GenVarStorHyb_Subtimepoint_Curtailment_MW[prj, tmp]
        - mod.GenVarStorHyb_Subtimepoint_Energy_Delivered_MW[prj, tmp]
    )


# Constraint Formulation Rules
###############################################################################


def max_power_rule(mod, prj, tmp):
    """
    **Constraint Name**: GenVarStorHyb_Max_Headroom_Power_Constraint
    **Enforced Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    The project's power and upward reserves cannot exceed the available
    capacity (Tx limit).
    """
    return (
        mod.GenVarStorHyb_Provide_Power_MW[prj, tmp]
        + mod.GenVarStorHyb_Upward_Reserves_MW[prj, tmp]
        <= mod.Capacity_MW[prj, mod.period[tmp]] * mod.Availability_Derate[prj, tmp]
    )


def max_available_power_rule(mod, prj, tmp):
    """
    **Constraint Name**: GenVarStorHyb_Max_Available_Power_Constraint
    **Enforced Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    Power provision plus upward services (from the whole project) cannot exceed
    available power, which is equal to the available capacity multiplied by
    the capacity factor plus the net power from storage.
    """
    return (
        mod.GenVarStorHyb_Provide_Power_MW[prj, tmp]
        + mod.GenVarStorHyb_Upward_Reserves_MW[prj, tmp]
        <= mod.GenVarStorHyb_Available_Gen_Power_MW[prj, tmp]
        + mod.GenVarStorHyb_Discharge_MW[prj, tmp]
        - mod.GenVarStorHyb_Charge_MW[prj, tmp]
    )


def min_power_rule(mod, prj, tmp):
    """
    **Constraint Name**: GenVarStorHyb_Min_Power_Constraint
    **Enforced Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    Power provision minus downward services cannot be less than 0. Here,
    we are assuming that the hybrid storage cannot charge from the grid (so
    power provision from the grid's standpoint cannot go negative).
    """
    return (
        mod.GenVarStorHyb_Provide_Power_MW[prj, tmp]
        - mod.GenVarStorHyb_Downward_Reserves_MW[prj, tmp]
        >= 0
    )


# TODO: can some of this be consolidated with the 'stor' optype methods
# Power and State of Charge
def max_discharge_rule(mod, s, tmp):
    """
    **Constraint Name**: GenVarStorHyb_Max_Discharge_Constraint
    **Enforced Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    Storage discharging power can't exceed available storage component
    capacity.
    """
    # TODO: capacity multipliers
    return (
        mod.GenVarStorHyb_Discharge_MW[s, tmp]
        <= mod.Hyb_Stor_Capacity_MW[s, mod.period[tmp]]
        * mod.Availability_Hyb_Stor_Cap_Derate[s, tmp]
    )


def max_charge_rule(mod, s, tmp):
    """
    **Constraint Name**: GenVarStorHyb_Max_Charge_Constraint
    **Enforced Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    Storage charging power can't exceed available storage component capacity.
    """
    # TODO: capacity multipliers
    return (
        mod.GenVarStorHyb_Charge_MW[s, tmp]
        <= mod.Hyb_Stor_Capacity_MW[s, mod.period[tmp]]
        * mod.Availability_Hyb_Stor_Cap_Derate[s, tmp]
    )


# TODO: adjust storage energy for reserves provided
def energy_tracking_rule(mod, s, tmp):
    """
    **Constraint Name**: GenVarStorHyb_Energy_Tracking_Constraint
    **Enforced Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    The energy stored in each timepoint is equal to the energy stored in the
    previous timepoint minus any discharged power (adjusted for discharging
    efficiency and timepoint duration) plus any charged power (adjusted for
    charging efficiency and timepoint duration).
    """
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[s]
    ) and check_boundary_type(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[s],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_first_timepoint(
            mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[s]
        ) and check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[s],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_starting_energy_in_storage = (
                mod.gen_var_stor_hyb_linked_starting_energy_in_storage[s, 0]
            )
            prev_tmp_discharge = mod.gen_var_stor_hyb_linked_discharge[s, 0]
            prev_tmp_charge = mod.gen_var_stor_hyb_linked_charge[s, 0]

            calculated_starting_energy_in_storage = (
                prev_tmp_starting_energy_in_storage
                + prev_tmp_charge
                * prev_tmp_hrs_in_tmp
                * mod.gen_var_stor_hyb_charging_efficiency[s]
                - prev_tmp_discharge
                * prev_tmp_hrs_in_tmp
                / mod.gen_var_stor_hyb_discharging_efficiency[s]
            )

            # Deal with possible precision-related infeasibilities, e.g. if
            # the calculated energy in storage is just below or just above
            # its boundaries of 0 and the energy capacity x availability
            # If no infeasibilities found, just return the calculated value
            starting_soc = check_for_soc_infeasibilities(
                mod=mod,
                s=s,
                tmp=tmp,
                starting_soc=calculated_starting_energy_in_storage,
            )

        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[s]]
            ]
            prev_tmp_starting_energy_in_storage = (
                mod.GenVarStorHyb_Starting_Energy_in_Storage_MWh[
                    s, mod.prev_tmp[tmp, mod.balancing_type_project[s]]
                ]
            )
            prev_tmp_discharge = mod.GenVarStorHyb_Discharge_MW[
                s, mod.prev_tmp[tmp, mod.balancing_type_project[s]]
            ]
            prev_tmp_charge = mod.GenVarStorHyb_Charge_MW[
                s, mod.prev_tmp[tmp, mod.balancing_type_project[s]]
            ]
            prev_tmp_upward_reserves = (mod.GenVarStorHyb_Upward_Reserves_from_Stor_MW)[
                s, mod.prev_tmp[tmp, mod.balancing_type_project[s]]
            ]

            starting_soc = (
                prev_tmp_starting_energy_in_storage
                + prev_tmp_charge
                * prev_tmp_hrs_in_tmp
                * mod.gen_var_stor_hyb_charging_efficiency[s]
                - (
                    prev_tmp_discharge
                    + prev_tmp_upward_reserves
                    * mod.gen_var_stor_hyb_upward_reserves_to_soc_depletion[s]
                )
                * prev_tmp_hrs_in_tmp
                / mod.gen_var_stor_hyb_discharging_efficiency[s]
            )

        return mod.GenVarStorHyb_Starting_Energy_in_Storage_MWh[s, tmp] == starting_soc


def max_energy_in_storage_rule(mod, s, tmp):
    """
    **Constraint Name**: GenVarStorHyb_Max_Energy_in_Stor_Constraint
    **Enforced Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    The amount of energy stored in each operational timepoint cannot exceed
    the available energy capacity.
    """
    return (
        mod.GenVarStorHyb_Starting_Energy_in_Storage_MWh[s, tmp]
        <= mod.Energy_Storage_Capacity_MWh[s, mod.period[tmp]]
        * mod.Availability_Derate[s, tmp]
    )


def max_stor_headroom_power_rule(mod, s, tmp):
    """
    **Constraint Name**: GenVarStorHyb_Max_Stor_Headroom_Power_Constraint
    **Enforced Over**: GEN_VAR_STOR_HYB_OPR_TMPS

    The storage upward reserves cannot exceed the available headroom.
    Going from charging to non-charging also counts as headroom, doubling
    the maximum amount of potential headroom.
    """
    return (
        mod.GenVarStorHyb_Upward_Reserves_from_Stor_MW[s, tmp]
        <= mod.Hyb_Stor_Capacity_MW[s, mod.period[tmp]]
        * mod.Availability_Hyb_Stor_Cap_Derate[s, tmp]
        - mod.GenVarStorHyb_Discharge_MW[s, tmp]
        + mod.GenVarStorHyb_Charge_MW[s, tmp]
    )


def max_stor_headroom_energy_rule(mod, s, tmp):
    """
    Can't provide more reserves (times sustained duration required) than
    available energy in storage in that timepoint. Said differently,
    must have enough energy available to be at the new set point (for
    the full duration of the timepoint).
    """
    return (
        mod.GenVarStorHyb_Upward_Reserves_from_Stor_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        / mod.gen_var_stor_hyb_discharging_efficiency[s]
        <= mod.GenVarStorHyb_Starting_Energy_in_Storage_MWh[s, tmp]
        + mod.GenVarStorHyb_Charge_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        * mod.gen_var_stor_hyb_charging_efficiency[s]
        - mod.GenVarStorHyb_Discharge_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        / mod.gen_var_stor_hyb_discharging_efficiency[s]
    )


def total_upward_reserves_rule(mod, prj, tmp):
    return (
        mod.GenVarStorHyb_Upward_Reserves_MW[prj, tmp]
        == mod.GenVarStorHyb_Upward_Reserves_from_Gen_MW[prj, tmp]
        + mod.GenVarStorHyb_Upward_Reserves_from_Stor_MW[prj, tmp]
    )


def max_upward_reserves_from_gen_rule(mod, g, tmp):
    """
    Upward reserves can't exceed curtailment
    """
    return mod.GenVarStorHyb_Upward_Reserves_from_Gen_MW[
        g, tmp
    ] <= scheduled_curtailment_expression_rule(mod, g, tmp)


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, prj, tmp):
    """
    Power provision from variable generators is their capacity times the
    capacity factor in each timepoint minus any upward reserves/curtailment.
    """

    return mod.GenVarStorHyb_Provide_Power_MW[prj, tmp]


def variable_om_cost_rule(mod, prj, tmp):
    """
    Variable cost is incurred on all power produced (including what's
    curtailed).
    """
    return (
        mod.GenVarStorHyb_Provide_Power_MW[prj, tmp] * mod.variable_om_cost_per_mwh[prj]
    )


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.GenVarStorHyb_Provide_Power_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.GenVarStorHyb_Provide_Power_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
    )


def scheduled_curtailment_rule(mod, prj, tmp):
    """
    Variable generation can be dispatched down, i.e. scheduled below the
    available energy
    """
    return mod.GenVarStorHyb_Scheduled_Curtailment_MW[prj, tmp]


def subtimepoint_curtailment_rule(mod, prj, tmp):
    """
    If providing downward reserves, variable generators will occasionally
    have to be dispatched down relative to their schedule, resulting in
    additional curtailment within the hour
    """
    return mod.GenVarStorHyb_Subtimepoint_Curtailment_MW[prj, tmp]


def subtimepoint_energy_delivered_rule(mod, prj, tmp):
    """
    If providing upward reserves, variable generators will occasionally be
    dispatched up, so additional energy will be delivered within the hour
    relative to their schedule (less curtailment)
    """
    return mod.GenVarStorHyb_Subtimepoint_Energy_Delivered_MW[prj, tmp]


def curtailment_cost_rule(mod, prj, tmp):
    """
    Apply curtailment cost to scheduled and subtimepoint curtailment
    """
    return (
        mod.GenVarStorHyb_Scheduled_Curtailment_MW[prj, tmp]
        + mod.GenVarStorHyb_Subtimepoint_Curtailment_MW[prj, tmp]
    ) * (
        mod.curtailment_cost_per_powerunithour[prj, mod.period[tmp]]
        if (prj, mod.period[tmp]) in mod.CURTAILMENT_COST_PRJ_PRDS
        else 0
    )


def power_delta_rule(mod, prj, tmp):
    """
    Curtailment is counted as part of the ramp here; excludes any ramping from
    reserve provision.

    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint.
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
            mod.GenVarStorHyb_Provide_Power_MW[prj, tmp]
            - mod.GenVarStorHyb_Provide_Power_MW[
                prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]
        )


def capacity_providing_inertia_rule(mod, prj, tmp):
    """
    Capacity providing inertia for GEN_VAR_STOR_HYB project is equal to the online
    capacity if any of it is generating
    """
    if mod.gen_var_stor_hyb_cap_factor[prj, tmp] >= 0:
        return mod.Capacity_MW[prj, mod.period[tmp]] * mod.Availability_Derate[prj, tmp]
    else:
        return 0


# Inputs-Outputs
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

    # Load data from projects.tab and get the list of projects of this type
    projects = load_optype_model_data(
        mod=mod,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="gen_var_stor_hyb",
    )

    load_var_profile_inputs(
        data_portal,
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "gen_var_stor_hyb",
    )


def add_to_prj_tmp_results(mod):
    results_columns = [
        "scheduled_curtailment_mw",
        "hyb_storage_charge_mw",
        "hyb_storage_discharge_mw",
        "subhourly_curtailment_mw",
        "subhourly_energy_delivered_mw",
        "total_curtailment_mw",
    ]
    data = [
        [
            prj,
            tmp,
            value(mod.GenVarStorHyb_Scheduled_Curtailment_MW[prj, tmp]),
            value(mod.GenVarStorHyb_Charge_MW[prj, tmp]),
            value(mod.GenVarStorHyb_Discharge_MW[prj, tmp]),
            value(mod.GenVarStorHyb_Subtimepoint_Curtailment_MW[prj, tmp]),
            value(mod.GenVarStorHyb_Subtimepoint_Energy_Delivered_MW[prj, tmp]),
            value(mod.GenVarStorHyb_Total_Curtailment_MW[prj, tmp]),
        ]
        for (prj, tmp) in mod.GEN_VAR_STOR_HYB_OPR_TMPS
    ]

    optype_dispatch_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    return results_columns, optype_dispatch_df


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
    :return: cursor object with query results
    """

    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )

    prj_tmp_data = get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=subscenarios,
        weather_iteration=db_weather_iteration,
        hydro_iteration=db_hydro_iteration,
        availability_iteration=db_availability_iteration,
        subproblem=db_subproblem,
        stage=db_stage,
        conn=conn,
        op_type="gen_var_stor_hyb",
        table="inputs_project_variable_generator_profiles" "",
        subscenario_id_column="variable_generator_profile_scenario_id",
        data_column="cap_factor",
    )

    return prj_tmp_data


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
    :param scenario_directory: string; the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    data = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )
    fname = "variable_generator_profiles.tab"

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


def process_model_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate scheduled curtailment
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate variable curtailment")

    # Delete old aggregated variable curtailment results
    del_sql = """
        DELETE FROM results_project_curtailment_variable_periodagg 
        WHERE scenario_id = ?;
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Aggregate variable curtailment (just scheduled curtailment)
    insert_sql = """
        INSERT INTO results_project_curtailment_variable_periodagg
        (scenario_id, subproblem_id, stage_id, period, timepoint, 
        timepoint_weight, number_of_hours_in_timepoint, month, hour_of_day,
        load_zone, scheduled_curtailment_mw)
        SELECT
        scenario_id, subproblem_id, stage_id, period, timepoint, 
        timepoint_weight, number_of_hours_in_timepoint, month, hour_of_day,
        load_zone, scheduled_curtailment_mw
        FROM (
            SELECT scenario_id, subproblem_id, stage_id, period, 
            timepoint, timepoint_weight, number_of_hours_in_timepoint, 
            load_zone, 
            sum(scheduled_curtailment_mw) AS scheduled_curtailment_mw
            FROM results_project_timepoint
            WHERE operational_type = 'gen_var_stor_hyb'
            GROUP BY scenario_id, subproblem_id, stage_id, timepoint, load_zone
        ) as agg_curtailment_tbl
        JOIN (
            SELECT subproblem_id, stage_id, timepoint, month, hour_of_day
            FROM inputs_temporal
            WHERE temporal_scenario_id = (
                SELECT temporal_scenario_id 
                FROM scenarios
                WHERE scenario_id = ?
                )
        ) as tmp_info_tbl
        USING (subproblem_id, stage_id, timepoint)
        WHERE scenario_id = ?
        ORDER BY subproblem_id, stage_id, load_zone, timepoint;"""

    spin_on_database_lock(
        conn=db, cursor=c, sql=insert_sql, data=(scenario_id, scenario_id), many=False
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
        "gen_var_stor_hyb",
    )

    # Validate var profiles input table
    validate_var_profiles(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "gen_var_stor_hyb",
    )
