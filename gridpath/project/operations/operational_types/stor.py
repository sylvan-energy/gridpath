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
This operational type describes a generic storage resource. It can be
applied to a battery, to a pumped-hydro project or another storage
technology.

The type is associated with three main variables in each timepoint when the
project is available: the charging level, the discharging level, and the
energy available in storage. The first two are constrained to be less than
or equal to the project's power capacity. The third is constrained to be
less than or equal to the project's energy capacity. The model tracks the
stage of charge in each timepoint based on the charging and discharging
decisions in the previous timepoint, with adjustments for charging and
discharging efficiencies. Storage projects can be allowed to provide upward
and/or downward reserves.

Costs for this operational type include variable O&M costs.

.. note:: Please note that to calculate the duration of the storage project, i.e.,
    how long it can sustain discharging at its maximum output, you must adjust the
    energy capacity by the discharge efficiency. For example, a 1 MW  with 1 MWh energy
    capacity battery with discharging losses of 5% (discharging_loss_factor = 95%) would
    have a duration of 1 MWh / (1 MW/0.95) or 0.95 hours rather than 1 hour.

"""

import csv
import os.path
from pyomo.environ import (
    Var,
    Set,
    Constraint,
    Param,
    Expression,
    NonNegativeReals,
    PercentFraction,
    value,
)
import warnings

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import headroom_variables, footroom_variables
from gridpath.project.operations.reserves.reserve_aggregation import (
    headroom_provision_rule,
    footroom_provision_rule,
)
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_if_last_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_optype_model_data,
    check_for_tmps_to_link,
    validate_opchars,
    write_tab_file_model_inputs,
    get_prj_temporal_index_opr_inputs_from_db,
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
    | | :code:`STOR`                                                          |
    |                                                                         |
    | The set of projects of the :code:`stor` operational type.               |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_OPR_TMPS`                                                 |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`stor`                   |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_LINKED_TMPS`                                              |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`stor`                 |
    | operational type and their linked timepoints.                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`stor_charging_efficiency`                                      |
    | | *Defined over*: :code:`STOR`                                          |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The storage project's charging efficiency (1 = 100% efficient).         |
    +-------------------------------------------------------------------------+
    | | :code:`stor_discharging_efficiency`                                   |
    | | *Defined over*: :code:`STOR`                                          |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The storage project's discharging efficiency (1 = 100% efficient).      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`stor_storage_efficiency`                                       |
    | | *Defined over*: :code:`STOR`                                          |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The storage project's storage efficiency (1 = 100% efficient).          |
    +-------------------------------------------------------------------------+
    | | :code:`stor_losses_factor_in_energy_target`                           |
    | | *Defined over*: :code:`STOR`                                          |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The fraction of storage losses that count against the energy target.    |
    +-------------------------------------------------------------------------+
    | | :code:`stor_losses_factor_curtailment`                                |
    | | *Defined over*: :code:`STOR`                                          |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The fraction of storage losses that count against curtailment.          |
    +-------------------------------------------------------------------------+
    | | :code:`stor_charging_capacity_multiplier`                             |
    | | *Defined over*: :code:`STOR`                                          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1.0`                                                |
    |                                                                         |
    | The storage project's charging capacity multiplier to be used if the    |
    | charging capacity is different from the nameplate capacity.             |
    +-------------------------------------------------------------------------+
    | | :code:`stor_discharging_capacity_multiplier`                          |
    | | *Defined over*: :code:`STOR`                                          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1.0`                                                |
    |                                                                         |
    | The storage project's discharging capacity multiplier to be used if the |
    | discharging capacity is different from the nameplate capacity.          |
    +-------------------------------------------------------------------------+
    | | :code:`stor_exogenous_starting_state_of_charge`                       |
    | | *Defined over*: :code:`STOR_EXOG_SOC_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The storage project's exogenously specified starting state of charge.   |
    | If not specified, the state of charge is endogenously determined by the |
    | optimization subject to the rest of the constraints.                    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Linked Input Params                                                     |
    +=========================================================================+
    | | :code:`stor_linked_starting_energy_in_storage`                        |
    | | *Defined over*: :code:`STOR_LINKED_TMPS`                              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's starting energy in storage in the linked timepoints.      |
    +-------------------------------------------------------------------------+
    | | :code:`stor_linked_discharge`                                         |
    | | *Defined over*: :code:`STOR_LINKED_TMPS`                              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's dicharging in the linked timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`stor_linked_charge`                                            |
    | | *Defined over*: :code:`STOR_LINKED_TMPS`                              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's charging in the linked timepoints.                        |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Stor_Charge_MW`                                                |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Charging power in MW from this project in each timepoint in which the   |
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Discharge_MW`                                             |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Discharging power in MW from this project in each timepoint in which the|
    |  project is operational (capacity exists and the project is available). |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Starting_Energy_in_Storage_MWh`                           |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The state of charge of the storage project at the start of each         |
    | timepoint, in MWh of energy stored.                                     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Power and Stage of Charge                                               |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Max_Charge_Constraint`                                    |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    |                                                                         |
    | Limits the project's charging power to the available capacity.          |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Max_Discharge_Constraint`                                 |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    |                                                                         |
    | Limits the project's discharging power to the available capacity.       |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Energy_Tracking_Constraint`                               |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    |                                                                         |
    | Tracks the amount of energy stored in each timepoint based on the       |
    | previous timepoint's energy stored and the charge and discharge         |
    | decisions.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Max_Energy_in_Storage_Constraint`                         |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    |                                                                         |
    | Limits the project's total energy stored to the available energy        |
    | capacity.                                                               |
    +-------------------------------------------------------------------------+
    | Reserves                                                                |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Max_Headroom_Power_Constraint`                            |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    |                                                                         |
    | Limits the project's upward reserves based on available headroom.       |
    | Going from charging to non-charging also counts as headroom, doubling   |
    | the maximum amount of potential headroom.                               |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Max_Footroom_Power_Constraint`                            |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    |                                                                         |
    | Limits the project's downward reserves based on available footroom.     |
    | Going from non-charging to charging also counts as footroom, doubling   |
    | the maximum amount of potential footroom.                               |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Max_Headroom_Energy_Constraint`                           |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    |                                                                         |
    | Can't provide more upward reserves (times sustained duration required)  |
    | than available energy in storage in that timepoint.                     |
    +-------------------------------------------------------------------------+
    | | :code:`Stor_Max_Footroom_Energy_Constraint`                           |
    | | *Defined over*: :code:`STOR_OPR_TMPS`                                 |
    |                                                                         |
    | Can't provide more downard reserves (times sustained duration required) |
    | than available capacity to store energy in that timepoint.              |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.STOR = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "stor"
        ),
    )

    m.STOR_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.STOR
        ),
    )

    m.STOR_LINKED_TMPS = Set(dimen=2)

    m.STOR_EXOG_SOC_TMPS = Set(within=m.STOR_OPR_TMPS)

    def stor_opr_bt_hrz_set_init(mod):
        prj_bt_hrz = []
        for prj in mod.STOR:
            bt = mod.balancing_type_project[prj]
            for hrz in mod.HRZS_BY_BLN_TYPE[bt]:
                # Add to the set if all timepoints in the horizon are in
                # the project's operational timepoints
                if all(
                    (prj, tmp) in mod.PRJ_OPR_TMPS
                    for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
                ):
                    prj_bt_hrz.append((prj, bt, hrz))

        return prj_bt_hrz

    m.STOR_OPR_BT_HRZ = Set(
        within=m.STOR * m.BLN_TYPE_HRZS, initialize=stor_opr_bt_hrz_set_init
    )

    # Required Params
    ###########################################################################

    m.stor_charging_efficiency = Param(m.STOR, within=PercentFraction)

    m.stor_discharging_efficiency = Param(m.STOR, within=PercentFraction)

    # Optional Params
    ###########################################################################

    m.stor_storage_efficiency = Param(m.STOR, within=PercentFraction, default=1)

    m.stor_losses_factor_in_energy_target = Param(m.STOR, default=1)

    m.stor_losses_factor_curtailment = Param(m.STOR, default=1)

    m.stor_upward_reserves_to_soc_depletion = Param(m.STOR, default=0)

    m.stor_charging_capacity_multiplier = Param(
        m.STOR, within=NonNegativeReals, default=1.0
    )

    m.stor_discharging_capacity_multiplier = Param(
        m.STOR, within=NonNegativeReals, default=1.0
    )

    m.stor_exogenous_starting_state_of_charge = Param(
        m.STOR_EXOG_SOC_TMPS, within=NonNegativeReals
    )

    m.stor_max_losses_in_hrz_frac_stor_energy_capacity = Param(
        m.STOR, within=NonNegativeReals, default=float("inf")
    )

    # Linked Params
    ###########################################################################

    m.stor_linked_starting_energy_in_storage = Param(
        m.STOR_LINKED_TMPS, within=NonNegativeReals
    )

    m.stor_linked_discharge = Param(m.STOR_LINKED_TMPS, within=NonNegativeReals)

    m.stor_linked_charge = Param(m.STOR_LINKED_TMPS, within=NonNegativeReals)

    # Variables
    ###########################################################################

    m.Stor_Charge_MW = Var(m.STOR_OPR_TMPS, within=NonNegativeReals)

    m.Stor_Discharge_MW = Var(m.STOR_OPR_TMPS, within=NonNegativeReals)

    m.Stor_Starting_Energy_in_Storage_MWh = Var(
        m.STOR_OPR_TMPS, within=NonNegativeReals
    )

    # Expressions
    ###########################################################################
    def ending_energy_in_storage_expression_rule(mod, prj, tmp):
        return (
            mod.Stor_Starting_Energy_in_Storage_MWh[prj, tmp]
            + mod.Stor_Charge_MW[prj, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.stor_charging_efficiency[prj]
            - mod.Stor_Discharge_MW[prj, tmp]
            * mod.hrs_in_tmp[tmp]
            / mod.stor_discharging_efficiency[prj]
        )

    m.Stor_Ending_Energy_in_Storage_MWh = Expression(
        m.STOR_OPR_TMPS,
        initialize=ending_energy_in_storage_expression_rule,
    )

    def upward_reserve_rule(mod, g, tmp):
        return headroom_provision_rule(d, mod, g, tmp)

    m.Stor_Upward_Reserves_MW = Expression(m.STOR_OPR_TMPS, rule=upward_reserve_rule)

    def downward_reserve_rule(mod, g, tmp):
        return footroom_provision_rule(d, mod, g, tmp)

    m.Stor_Downward_Reserves_MW = Expression(
        m.STOR_OPR_TMPS, rule=downward_reserve_rule
    )

    # Constraints
    ###########################################################################

    # Power and State of Charge
    m.Stor_Max_Charge_Constraint = Constraint(m.STOR_OPR_TMPS, rule=max_charge_rule)

    m.Stor_Max_Discharge_Constraint = Constraint(
        m.STOR_OPR_TMPS, rule=max_discharge_rule
    )

    m.Stor_Energy_Tracking_Constraint = Constraint(
        m.STOR_OPR_TMPS, rule=energy_tracking_rule
    )

    m.Stor_Max_Energy_in_Storage_Constraint = Constraint(
        m.STOR_OPR_TMPS, rule=max_energy_in_storage_rule
    )

    m.Stor_Max_Losses_Constraint = Constraint(
        m.STOR_OPR_BT_HRZ, rule=max_losses_in_hrz_rule
    )

    # Reserves
    m.Stor_Max_Headroom_Power_Constraint = Constraint(
        m.STOR_OPR_TMPS, rule=max_headroom_power_rule
    )

    m.Stor_Max_Footroom_Power_Constraint = Constraint(
        m.STOR_OPR_TMPS, rule=max_footroom_power_rule
    )

    m.Stor_Max_Headroom_Energy_Constraint = Constraint(
        m.STOR_OPR_TMPS, rule=max_headroom_energy_rule
    )

    m.Stor_Max_Footroom_Energy_Constraint = Constraint(
        m.STOR_OPR_TMPS, rule=max_footroom_energy_rule
    )


# Constraint Formulation Rules
###############################################################################


# Power and State of Charge
def max_discharge_rule(mod, s, tmp):
    """
    **Constraint Name**: Stor_Max_Discharge_Constraint
    **Enforced Over**: STOR_OPR_TMPS

    Storage discharging power can't exceed available capacity.
    """
    return (
        mod.Stor_Discharge_MW[s, tmp]
        <= mod.Capacity_MW[s, mod.period[tmp]]
        * mod.Availability_Derate[s, tmp]
        * mod.stor_discharging_capacity_multiplier[s]
    )


def max_charge_rule(mod, s, tmp):
    """
    **Constraint Name**: Stor_Max_Charge_Constraint
    **Enforced Over**: STOR_OPR_TMPS

    Storage charging power can't exceed available capacity.
    """
    return (
        mod.Stor_Charge_MW[s, tmp]
        <= mod.Capacity_MW[s, mod.period[tmp]]
        * mod.Availability_Derate[s, tmp]
        * mod.stor_charging_capacity_multiplier[s]
    )


# TODO: also adjust storage energy for downward reserves provided
def energy_tracking_rule(mod, s, tmp):
    """
    **Constraint Name**: Stor_Energy_Tracking_Constraint
    **Enforced Over**: STOR_OPR_TMPS

    The energy stored in each timepoint is equal to the energy stored in the
    previous timepoint minus any discharged power (adjusted for discharging
    efficiency and timepoint duration) plus any charged power (adjusted for
    charging efficiency and timepoint duration).
    """
    if (s, tmp) in mod.STOR_EXOG_SOC_TMPS:
        starting_soc = check_for_soc_infeasibilities(
            mod=mod,
            s=s,
            tmp=tmp,
            starting_soc=mod.stor_exogenous_starting_state_of_charge[s, tmp],
        )
    else:
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
                    mod.stor_linked_starting_energy_in_storage[s, 0]
                )
                prev_tmp_discharge = mod.stor_linked_discharge[s, 0]
                prev_tmp_charge = mod.stor_linked_charge[s, 0]

                calculated_starting_energy_in_storage = (
                    prev_tmp_starting_energy_in_storage * mod.stor_storage_efficiency[s]
                    + prev_tmp_charge
                    * prev_tmp_hrs_in_tmp
                    * mod.stor_charging_efficiency[s]
                    - prev_tmp_discharge
                    * prev_tmp_hrs_in_tmp
                    / mod.stor_discharging_efficiency[s]
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
                    mod.Stor_Starting_Energy_in_Storage_MWh[
                        s, mod.prev_tmp[tmp, mod.balancing_type_project[s]]
                    ]
                )
                prev_tmp_discharge = mod.Stor_Discharge_MW[
                    s, mod.prev_tmp[tmp, mod.balancing_type_project[s]]
                ]
                prev_tmp_charge = mod.Stor_Charge_MW[
                    s, mod.prev_tmp[tmp, mod.balancing_type_project[s]]
                ]
                prev_tmp_upward_reserves = mod.Stor_Upward_Reserves_MW[
                    s, mod.prev_tmp[tmp, mod.balancing_type_project[s]]
                ]

                starting_soc = (
                    prev_tmp_starting_energy_in_storage * mod.stor_storage_efficiency[s]
                    + prev_tmp_charge
                    * prev_tmp_hrs_in_tmp
                    * mod.stor_charging_efficiency[s]
                    - (
                        prev_tmp_discharge
                        + prev_tmp_upward_reserves
                        * mod.stor_upward_reserves_to_soc_depletion[s]
                    )
                    * prev_tmp_hrs_in_tmp
                    / mod.stor_discharging_efficiency[s]
                )

    return mod.Stor_Starting_Energy_in_Storage_MWh[s, tmp] == starting_soc


def max_energy_in_storage_rule(mod, s, tmp):
    """
    **Constraint Name**: Stor_Max_Energy_in_Storage_Constraint
    **Enforced Over**: STOR_OPR_TMPS

    The amount of energy stored in each operational timepoint cannot exceed
    the available energy capacity.
    """
    return (
        mod.Stor_Starting_Energy_in_Storage_MWh[s, tmp]
        <= mod.Energy_Storage_Capacity_MWh[s, mod.period[tmp]]
        * mod.Availability_Derate[s, tmp]
    )


# Max losses in horizon (e.g., to limit cycling)
def max_losses_in_hrz_rule(mod, prj, bt, hrz):
    """
    Limit losses in each horizon
    Can be used to constrain cycling or acting as load
    """
    if mod.stor_max_losses_in_hrz_frac_stor_energy_capacity[prj] == float("inf"):
        return Constraint.Skip
    else:
        return (
            sum(
                (mod.Stor_Charge_MW[prj, tmp] - mod.Stor_Discharge_MW[prj, tmp])
                * mod.hrs_in_tmp[tmp]
                for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            <= mod.stor_max_losses_in_hrz_frac_stor_energy_capacity[prj]
            * mod.Energy_Storage_Capacity_MWh[
                prj, mod.period[mod.first_hrz_tmp[bt, hrz]]
            ]
        )


# Reserves
def max_headroom_power_rule(mod, s, tmp):
    """
    **Constraint Name**: Stor_Max_Headroom_Power_Constraint
    **Enforced Over**: STOR_OPR_TMPS

    The project's upward reserves cannot exceed the available headroom.
    Going from charging to non-charging also counts as headroom, doubling
    the maximum amount of potential headroom.
    """
    return (
        mod.Stor_Upward_Reserves_MW[s, tmp]
        <= mod.Capacity_MW[s, mod.period[tmp]] * mod.Availability_Derate[s, tmp]
        - mod.Stor_Discharge_MW[s, tmp]
        + mod.Stor_Charge_MW[s, tmp]
    )


def max_footroom_power_rule(mod, s, tmp):
    """
    **Constraint Name**: Stor_Max_Footroom_Power_Constraint
    **Enforced Over**: STOR_OPR_TMPS

    The project's downward reserves cannot exceed the available footroom.
    Going from non-charging to charging also counts as footroom, doubling
    the the maximum amount of potential footroom.
    """
    return (
        mod.Stor_Downward_Reserves_MW[s, tmp]
        <= mod.Stor_Discharge_MW[s, tmp]
        + mod.Capacity_MW[s, mod.period[tmp]] * mod.Availability_Derate[s, tmp]
        - mod.Stor_Charge_MW[s, tmp]
    )


# Headroom and footroom energy constraints
# TODO: allow different sustained duration requirements; assumption here is
#  that if reserves are called, new setpoint must be sustained for 1 hour
# TODO: allow derate of the net energy in the current timepoint in the
#  headroom and footroom energy rules; in reality, reserves could be
#  called at the very beginning or the very end of the timepoint (e.g.
#  hour)
#  If called at the end, we would have all the net energy (or
#  resulting 'room in the tank') available, but if called in the beginning
#  none of it would be available


def max_headroom_energy_rule(mod, s, tmp):
    """
    **Constraint Name**: Stor_Max_Headroom_Energy_Constraint
    **Enforced Over**: STOR_OPR_TMPS

    Can't provide more reserves (times sustained duration required) than
    available energy in storage in that timepoint. Said differently,
    must have enough energy available to be at the new set point (for
    the full duration of the timepoint).
    """
    return (
        mod.Stor_Upward_Reserves_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        / mod.stor_discharging_efficiency[s]
        <= mod.Stor_Starting_Energy_in_Storage_MWh[s, tmp]
        + mod.Stor_Charge_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        * mod.stor_charging_efficiency[s]
        - mod.Stor_Discharge_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        / mod.stor_discharging_efficiency[s]
    )


def max_footroom_energy_rule(mod, s, tmp):
    """
    **Constraint Name**: Stor_Max_Footroom_Energy_Constraint
    **Enforced Over**: STOR_OPR_TMPS

    Can't provide more reserves (times sustained duration required) than
    available capacity to store energy in that timepoint. Said differently,
    must have enough 'room left in the tank' (remaining energy capacity)
    to be at the new set point (for the full duration of the timepoint).
    """
    return (
        mod.Stor_Downward_Reserves_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        * mod.stor_charging_efficiency[s]
        <= mod.Energy_Storage_Capacity_MWh[s, mod.period[tmp]]
        * mod.Availability_Derate[s, tmp]
        - mod.Stor_Starting_Energy_in_Storage_MWh[s, tmp]
        - mod.Stor_Charge_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        * mod.stor_charging_efficiency[s]
        + mod.Stor_Discharge_MW[s, tmp]
        * mod.hrs_in_tmp[tmp]
        / mod.stor_discharging_efficiency[s]
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, s, tmp):
    """
    Power provision for generic storage resources is the net power (i.e.
    discharging minus charging). The two variables are constrained to be
    less than or equal to the storage power capacity (with an adjustment for
    reserve-provision), and are also constrained by the storage state of
    charge (i.e. can't charge when the storage is full; can't discharge when
    storage is empty).
    """
    return mod.Stor_Discharge_MW[s, tmp] - mod.Stor_Charge_MW[s, tmp]


def rec_provision_rule(mod, g, tmp):
    """
    If modeled as eligible for RPS, losses incurred by storage (the sum
    over all timepoints of total charging minus total discharging) will count
    against the RPS (i.e. increase RPS requirement, we take the negative of
    the losses as the contribution of the storage to the RPS). By default
     all losses count against the RPS, but this can be derated with the
    stor_losses_factor_in_energy_target parameter (can be between 0 and 1 with
    default of 1). Storage MUST be modeled as eligible for RPS for this rule
    to apply.

    Modeling storage this way can be necessary to avoid having storage behave
    as load (e.g. by charging and discharging at the same time) in order to
    absorb RPS-eligible energy that would otherwise be curtailed, making it
    appear as if it were delivered to load.
    """
    return (
        mod.Stor_Discharge_MW[g, tmp] - mod.Stor_Charge_MW[g, tmp]
    ) * mod.stor_losses_factor_in_energy_target[g]


def variable_om_cost_rule(mod, g, tmp):
    """
    Variable O&M costs are applied only to the storage discharge, i.e. when the
    project is providing power to the system.
    """
    return mod.Stor_Discharge_MW[g, tmp] * mod.variable_om_cost_per_mwh[g]


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.Stor_Discharge_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.Stor_Discharge_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
    )


def curtailment_cost_rule(mod, g, tmp):
    """
    Apply curtailment cost to round trip storage loss: to balance
    against curtailment of variable projects.

    Downstream this is summed over all timepoints, so losses from storage (
    the sum of all discharging minus the sum of all charging) will incur the
    curtailment cost. By default all losses incur the curtailment cost,
    but this can be derated with the stor_losses_factor_curtailment parameter
    (default of 1).

    Modeling storage this way can be necessary to avoid having storage behave
    as load (e.g. by charging and discharging at the same time) in order to
    absorb energy that would otherwise be curtailed and incur a cost, making it
    appear as if it were delivered to load.
    """
    return (
        (mod.Stor_Charge_MW[g, tmp] - mod.Stor_Discharge_MW[g, tmp])
        * (
            mod.curtailment_cost_per_powerunithour[g, mod.period[tmp]]
            if (g, mod.period[tmp]) in mod.CURTAILMENT_COST_PRJ_PRDS
            else 0
        )
        * mod.stor_losses_factor_curtailment[g]
    )


def soc_penalty_cost_rule(mod, prj, tmp):
    """ """
    return mod.soc_penalty_cost_per_energyunit[prj] * (
        mod.Energy_Storage_Capacity_MWh[prj, mod.period[tmp]]
        * mod.Availability_Derate[prj, tmp]
        - mod.Stor_Ending_Energy_in_Storage_MWh[prj, tmp]
    )


def soc_last_tmp_penalty_cost_rule(mod, prj, tmp):
    """ """
    if check_if_last_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[prj]
    ):
        return mod.soc_last_tmp_penalty_cost_per_energyunit[prj] * (
            mod.Energy_Storage_Capacity_MWh[prj, mod.period[tmp]]
            * mod.Availability_Derate[prj, tmp]
            - mod.Stor_Ending_Energy_in_Storage_MWh[prj, tmp]
        )
    else:
        return 0


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
        return (mod.Stor_Discharge_MW[g, tmp] - mod.Stor_Charge_MW[g, tmp]) - (
            mod.Stor_Discharge_MW[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            - mod.Stor_Charge_MW[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
        )


# Input-Output
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
        op_type="stor",
        table="inputs_project_stor_exog_state_of_charge",
        subscenario_id_column="stor_exog_state_of_charge_scenario_id",
        data_column="exog_state_of_charge_mwh",
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
    :param scenario_directory: string, the scenario directory
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

    fname = "stor_exogenous_state_of_charge.tab"

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname,
        data,
        replace_nulls=True,
    )


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
        op_type="stor",
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
        "stor_linked_timepoint_params.tab",
    )
    if os.path.exists(linked_inputs_filename):
        data_portal.load(
            filename=linked_inputs_filename,
            index=mod.STOR_LINKED_TMPS,
            param=(
                mod.stor_linked_starting_energy_in_storage,
                mod.stor_linked_discharge,
                mod.stor_linked_charge,
            ),
        )

    # Exogenously specified SOC
    exog_soc_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "stor_exogenous_state_of_charge.tab",
    )
    if os.path.exists(exog_soc_filename):
        data_portal.load(
            filename=exog_soc_filename,
            index=mod.STOR_EXOG_SOC_TMPS,
            param=mod.stor_exogenous_starting_state_of_charge,
        )
    else:
        pass


def add_to_prj_tmp_results(mod):
    results_columns = [
        "starting_energy_mwh",
        "charge_mw",
        "discharge_mw",
    ]
    data = [
        [
            prj,
            tmp,
            value(mod.Stor_Starting_Energy_in_Storage_MWh[prj, tmp]),
            value(mod.Stor_Charge_MW[prj, tmp]),
            value(mod.Stor_Discharge_MW[prj, tmp]),
        ]
        for (prj, tmp) in mod.STOR_OPR_TMPS
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
                "stor_linked_timepoint_params.tab",
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
            for p, tmp in sorted(mod.STOR_OPR_TMPS):
                if tmp in tmps_to_link:
                    writer.writerow(
                        [
                            p,
                            tmp_linked_tmp_dict[tmp],
                            max(
                                value(mod.Stor_Starting_Energy_in_Storage_MWh[p, tmp]),
                                0,
                            ),
                            max(value(mod.Stor_Discharge_MW[p, tmp]), 0),
                            max(value(mod.Stor_Charge_MW[p, tmp]), 0),
                        ]
                    )


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
        "stor",
    )


# ### OTHER ### #
def check_for_soc_infeasibilities(mod, s, tmp, starting_soc):
    if starting_soc < 0:
        warnings.warn(
            f"Starting energy in storage was "
            f"{starting_soc} for project {s}, "
            f"which would have resulted in infeasibility. "
            f"Changed to 0. This can happen due to solver tolerances and "
            f"precision of results. If you didn't expect this, check the "
            f"inputs and results."
        )
        return 0
    elif mod.capacity_type[s] == "stor_spec" and starting_soc > (
        mod.stor_spec_energy_capacity_mwh[s, mod.period[tmp]]
        * mod.avl_exog_cap_derate_independent[s, tmp]
        * mod.avl_exog_cap_derate_weather[s, tmp]
    ):
        warnings.warn(
            f"Starting energy in storage was "
            f"{starting_soc} for project {s}, "
            f"which would have resulted in infeasibility. "
            f"Changed to "
            f"mod.stor_spec_energy_capacity_mwh[s,mod.period[tmp]] "
            f"* mod.Availability_Derate[s, tmp]. This can happen due to "
            f"solver tolerances and precision of results. If you didn't expect "
            f"this, check the inputs and results."
        )
        return (
            mod.stor_spec_energy_capacity_mwh[s, mod.period[tmp]]
            * mod.Availability_Derate[s, tmp]
        )
    else:
        return starting_soc
