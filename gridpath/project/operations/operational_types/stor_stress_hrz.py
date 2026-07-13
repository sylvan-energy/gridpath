# Copyright 2026 Sylvan Energy Analytics LLC.
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
This operational type describes a storage resource whose state of charge
is built up under "average" system conditions and then drawn down during
"stress" conditions, e.g. multi-day or seasonal storage.

The type distinguishes between two kinds of horizons (of the project's
balancing type), designated via the :code:`stor_stress_hrz_type` input:

* **Average-condition horizons**: the project can only charge (discharging
  is not allowed) and the state of charge is not tracked timepoint to
  timepoint. Instead, we track the total energy put into storage over each
  period's average-condition horizons -- the sum over their timepoints of
  charging (adjusted for the charging efficiency), scaled by each
  timepoint's duration and weight. This total is constrained to fit within
  the project's energy capacity in the period.

  A period will usually have a single average-condition horizon; if it has
  more than one, the net energy stored is summed across all of them into
  one period total.

* **Stress horizons**: the state of charge is tracked explicitly timepoint
  to timepoint, as in the :code:`stor` operational type. The state of
  charge at the *start* of each stress horizon is set to the total energy
  stored over the same period's average-condition horizons, i.e., the
  storage enters the stress event with whatever it accumulated under
  average conditions.

Every period that contains a stress horizon for a project of this type
must also contain at least one average-condition horizon for that project
(otherwise the starting state of charge for the stress horizon is
undefined and model construction will fail with an informative error).

The starting state of charge of a stress horizon is anchored to the
average-condition energy build-up regardless of the horizon's boundary
type: there is no state-of-charge wrap-around (circular) or link to a
previous horizon (linked) for projects of this type.

Reserves, linked timepoints, and exogenously specified state of charge are
not supported for this operational type.

.. note:: Model construction performance: most components in this module
    are indexed by project-timepoint, so their rules are called once per
    index. Per-index work that only depends on the project is hoisted into
    locals, horizon-level structures are built by iterating the small
    project-horizon sets rather than filtering timepoint-level supersets,
    and derived sets initialized by filtering another set do not
    re-declare that set as :code:`within` (the domain check would be
    redundant with the initializer).
"""

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

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.project import PROJECT_PERIOD_DF
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_if_last_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_optype_model_data,
    validate_opchars,
    write_tab_file_model_inputs,
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
    | | :code:`STOR_STRESS_HRZ`                                               |
    |                                                                         |
    | The set of projects of the :code:`stor_stress_hrz` operational type.    |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_STRESS_HRZ_OPR_TMPS`                                      |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`stor_stress_hrz`        |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_STRESS_HRZ_OPR_BT_HRZ`                                    |
    |                                                                         |
    | Three-dimensional set with projects of the :code:`stor_stress_hrz`      |
    | operational type and the balancing type-horizons in which all           |
    | timepoints are operational timepoints of the project.                   |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ`                             |
    |                                                                         |
    | The subset of :code:`STOR_STRESS_HRZ_OPR_BT_HRZ` where the horizon is   |
    | of the "stress" type.                                                  |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_STRESS_HRZ_AVG_OPR_BT_HRZ`                                |
    |                                                                         |
    | The subset of :code:`STOR_STRESS_HRZ_OPR_BT_HRZ` where the horizon is   |
    | of the "average" (average-condition) type: the complement of            |
    | :code:`STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ`, so the two sets always       |
    | partition :code:`STOR_STRESS_HRZ_OPR_BT_HRZ` and every horizon is       |
    | covered.                                                                |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_STRESS_HRZ_STRESS_OPR_TMPS`                               |
    |                                                                         |
    | Two-dimensional set with projects of the :code:`stor_stress_hrz`        |
    | operational type and their operational timepoints that are in stress    |
    | horizons. The state of charge is tracked only over these timepoints.    |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_STRESS_HRZ_AVG_PRJ_PRDS`                                  |
    |                                                                         |
    | Two-dimensional set of projects of the :code:`stor_stress_hrz`          |
    | operational type and the periods in which they have average-condition   |
    | horizons.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`STOR_STRESS_HRZ_AVG_BT_HRZS_BY_PRJ_PRD`                        |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_AVG_PRJ_PRDS`                  |
    |                                                                         |
    | Indexed set of the balancing type-horizons that are the project's       |
    | average-condition horizons in each period.                              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`stor_stress_hrz_charging_efficiency`                                  |
    | | *Defined over*: :code:`STOR_STRESS_HRZ`                                      |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The storage project's charging efficiency (1 = 100% efficient).         |
    +-------------------------------------------------------------------------+
    | | :code:`stor_stress_hrz_discharging_efficiency`                               |
    | | *Defined over*: :code:`STOR_STRESS_HRZ`                                      |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The storage project's discharging efficiency (1 = 100% efficient).      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`stor_stress_hrz_type`                                             |
    | | *Defined over*: :code:`BLN_TYPE_HRZS`                                 |
    | | *Within*: :code:`["average", "stress"]`                               |
    | | *Default*: :code:`"average"`                                          |
    |                                                                         |
    | The type of each balancing type-horizon for the purposes of this        |
    | operational type: "average" (average-condition) or "stress".            |
    +-------------------------------------------------------------------------+
    | | :code:`stor_stress_hrz_storage_efficiency`                            |
    | | *Defined over*: :code:`STOR_STRESS_HRZ`                               |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The storage project's storage efficiency (1 = 100% efficient), applied  |
    | to the state of charge between timepoints of stress horizons.           |
    +-------------------------------------------------------------------------+
    | | :code:`stor_stress_hrz_charging_capacity_multiplier`                  |
    | | *Defined over*: :code:`STOR_STRESS_HRZ`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1.0`                                                |
    |                                                                         |
    | The storage project's charging capacity multiplier to be used if the    |
    | charging capacity is different from the nameplate capacity.             |
    +-------------------------------------------------------------------------+
    | | :code:`stor_stress_hrz_discharging_capacity_multiplier`               |
    | | *Defined over*: :code:`STOR_STRESS_HRZ`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1.0`                                                |
    |                                                                         |
    | The storage project's discharging capacity multiplier to be used if the |
    | discharging capacity is different from the nameplate capacity.          |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`StorStressHrz_Charge_MW`                                       |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_OPR_TMPS`                      |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Charging power in MW from this project in each timepoint in which the   |
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Discharge_MW`                                    |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_STRESS_OPR_TMPS`               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Discharging power in MW from this project in each of its operational    |
    | timepoints in stress horizons. Discharging is not allowed in            |
    | average-condition horizons.                                             |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Starting_Energy_in_Storage_MWh`                  |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_STRESS_OPR_TMPS`               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The state of charge of the storage project at the start of each         |
    | timepoint of its stress horizons, in MWh of energy stored.              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`StorStressHrz_Avg_Hrz_Stored_Energy_MWh`                       |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_AVG_PRJ_PRDS`                  |
    |                                                                         |
    | The total energy in storage accumulated over the period's               |
    | average-condition horizons: the sum over their timepoints of charging,  |
    | adjusted for the charging efficiency and scaled by timepoint duration   |
    | and weight.                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Ending_Energy_in_Storage_MWh`                    |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_STRESS_OPR_TMPS`               |
    |                                                                         |
    | The state of charge at the end of each stress-horizon timepoint: the    |
    | starting state of charge plus charging minus discharging in the         |
    | timepoint, adjusted for the charging and discharging efficiencies.      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Power                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Max_Charge_Constraint`                           |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_OPR_TMPS`                      |
    |                                                                         |
    | Limits the project's charging power to the available capacity.          |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Max_Discharge_Constraint`                        |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_STRESS_OPR_TMPS`               |
    |                                                                         |
    | Limits the project's discharging power to the available capacity.       |
    +-------------------------------------------------------------------------+
    | Average-Condition Horizon Energy                                        |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Avg_Hrz_Max_Stored_Energy_Constraint`            |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_AVG_PRJ_PRDS`                  |
    |                                                                         |
    | The energy stored over the period's average-condition horizons can't    |
    | exceed the project's energy capacity in the period.                     |
    +-------------------------------------------------------------------------+
    | Stress Horizon State of Charge                                          |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Stress_Hrz_Energy_Tracking_Constraint`           |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_STRESS_OPR_TMPS`               |
    |                                                                         |
    | Tracks the amount of energy stored in each timepoint of the stress      |
    | horizons based on the previous timepoint's energy stored and the        |
    | charge and discharge decisions; in the first timepoint of a stress      |
    | horizon, sets the starting state of charge to the total energy stored   |
    | over the period's average-condition horizons.                           |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Stress_Hrz_Max_Energy_in_Storage_Constraint`     |
    | | *Defined over*: :code:`STOR_STRESS_HRZ_STRESS_OPR_TMPS`               |
    |                                                                         |
    | Limits the project's total energy stored in stress-horizon timepoints   |
    | to the available energy capacity.                                       |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Stress_Hrz_Last_Tmp_Min_Ending_Energy_Constraint`|
    | | *Defined over*: :code:`STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ`             |
    |                                                                         |
    | The ending state of charge in the last timepoint of each stress         |
    | horizon can't be negative. For all other timepoints this is implied by  |
    | the energy tracking constraint and the non-negativity of the next       |
    | timepoint's starting state of charge, but the anchoring of the first    |
    | timepoint's state of charge breaks that chain at the end of the         |
    | horizon (regardless of the horizon's boundary type), so the last        |
    | timepoint needs an explicit bound.                                      |
    +-------------------------------------------------------------------------+
    | | :code:`StorStressHrz_Stress_Hrz_Last_Tmp_Max_Ending_Energy_Constraint`|
    | | *Defined over*: :code:`STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ`             |
    |                                                                         |
    | The ending state of charge in the last timepoint of each stress         |
    | horizon can't exceed the available energy capacity (same reasoning as   |
    | for the minimum ending energy constraint).                              |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.STOR_STRESS_HRZ = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "stor_stress_hrz"
        ),
    )

    m.STOR_STRESS_HRZ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.STOR_STRESS_HRZ,
        ),
    )

    def stor_stress_hrz_opr_bt_hrz_set_init(mod):
        prj_bt_hrz = []
        for prj in mod.STOR_STRESS_HRZ:
            bt = mod.balancing_type_project[prj]
            for hrz in mod.HRZS_BY_BLN_TYPE[bt]:
                # Add to the set if all timepoints in the horizon are in
                # the project's operational timepoints
                # Keep the element-by-element membership checks: they are
                # O(1) each and short-circuit, whereas an issubset() test
                # against PRJ_OPR_TMPS would copy that entire set per
                # project-horizon
                if all(
                    (prj, tmp) in mod.PRJ_OPR_TMPS
                    for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
                ):
                    prj_bt_hrz.append((prj, bt, hrz))

        return prj_bt_hrz

    m.STOR_STRESS_HRZ_OPR_BT_HRZ = Set(
        within=m.STOR_STRESS_HRZ * m.BLN_TYPE_HRZS,
        initialize=stor_stress_hrz_opr_bt_hrz_set_init,
    )

    # Horizon type designation; this is an input, so declare it before the
    # sets derived from it (construction order follows declaration order)
    m.stor_stress_hrz_type = Param(
        m.BLN_TYPE_HRZS, within=["average", "stress"], default="average"
    )

    # These filter the (small) project-horizon set, not any
    # timepoint-indexed superset
    # The average set is the complement of the stress set, so the two are
    # guaranteed to partition STOR_STRESS_HRZ_OPR_BT_HRZ (their union covers every
    # project-horizon); the stor_stress_hrz_type domain rejects any value other
    # than "average"/"stress" at load time
    m.STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ = Set(
        dimen=3,
        initialize=lambda mod: [
            (prj, bt, hrz)
            for (prj, bt, hrz) in mod.STOR_STRESS_HRZ_OPR_BT_HRZ
            if mod.stor_stress_hrz_type[bt, hrz] == "stress"
        ],
    )

    m.STOR_STRESS_HRZ_AVG_OPR_BT_HRZ = Set(
        dimen=3,
        initialize=lambda mod: [
            (prj, bt, hrz)
            for (prj, bt, hrz) in mod.STOR_STRESS_HRZ_OPR_BT_HRZ
            if (prj, bt, hrz) not in mod.STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ
        ],
    )

    m.STOR_STRESS_HRZ_STRESS_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: [
            (prj, tmp)
            for (prj, bt, hrz) in mod.STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        ],
    )

    def stor_stress_hrz_avg_prj_prds_init(mod):
        # Ordered dedup of the (project, period) pairs with average-condition
        # horizons
        return list(
            dict.fromkeys(
                (prj, mod.hrz_period[bt, hrz])
                for (prj, bt, hrz) in mod.STOR_STRESS_HRZ_AVG_OPR_BT_HRZ
            )
        )

    m.STOR_STRESS_HRZ_AVG_PRJ_PRDS = Set(
        dimen=2, initialize=stor_stress_hrz_avg_prj_prds_init
    )

    def stor_stress_hrz_avg_bt_hrzs_by_prj_prd_init(mod):
        # Build the whole indexed structure in one pass over the
        # project-horizon set and return the dict
        avg_bt_hrzs_by_prj_prd = {
            (prj, prd): [] for (prj, prd) in mod.STOR_STRESS_HRZ_AVG_PRJ_PRDS
        }
        for prj, bt, hrz in mod.STOR_STRESS_HRZ_AVG_OPR_BT_HRZ:
            avg_bt_hrzs_by_prj_prd[prj, mod.hrz_period[bt, hrz]].append((bt, hrz))

        return avg_bt_hrzs_by_prj_prd

    m.STOR_STRESS_HRZ_AVG_BT_HRZS_BY_PRJ_PRD = Set(
        m.STOR_STRESS_HRZ_AVG_PRJ_PRDS,
        dimen=2,
        initialize=stor_stress_hrz_avg_bt_hrzs_by_prj_prd_init,
    )

    # Required Params
    ###########################################################################

    m.stor_stress_hrz_charging_efficiency = Param(
        m.STOR_STRESS_HRZ, within=PercentFraction
    )

    m.stor_stress_hrz_discharging_efficiency = Param(
        m.STOR_STRESS_HRZ, within=PercentFraction
    )

    # Optional Params
    ###########################################################################

    m.stor_stress_hrz_storage_efficiency = Param(
        m.STOR_STRESS_HRZ, within=PercentFraction, default=1
    )

    m.stor_stress_hrz_charging_capacity_multiplier = Param(
        m.STOR_STRESS_HRZ, within=NonNegativeReals, default=1.0
    )

    m.stor_stress_hrz_discharging_capacity_multiplier = Param(
        m.STOR_STRESS_HRZ, within=NonNegativeReals, default=1.0
    )

    # Variables
    ###########################################################################

    m.StorStressHrz_Charge_MW = Var(m.STOR_STRESS_HRZ_OPR_TMPS, within=NonNegativeReals)

    # Discharging is only allowed in stress horizons
    m.StorStressHrz_Discharge_MW = Var(
        m.STOR_STRESS_HRZ_STRESS_OPR_TMPS, within=NonNegativeReals
    )

    m.StorStressHrz_Starting_Energy_in_Storage_MWh = Var(
        m.STOR_STRESS_HRZ_STRESS_OPR_TMPS, within=NonNegativeReals
    )

    # Expressions
    ###########################################################################

    def avg_hrz_stored_energy_expression_rule(mod, prj, prd):
        """
        The total energy put into storage over the period's
        average-condition horizons: charging adjusted for the charging
        efficiency, scaled by timepoint duration and weight.
        """
        eff_chg = mod.stor_stress_hrz_charging_efficiency[prj]
        return sum(
            mod.StorStressHrz_Charge_MW[prj, tmp]
            * eff_chg
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (bt, hrz) in mod.STOR_STRESS_HRZ_AVG_BT_HRZS_BY_PRJ_PRD[prj, prd]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        )

    m.StorStressHrz_Avg_Hrz_Stored_Energy_MWh = Expression(
        m.STOR_STRESS_HRZ_AVG_PRJ_PRDS, initialize=avg_hrz_stored_energy_expression_rule
    )

    def ending_energy_in_storage_expression_rule(mod, prj, tmp):
        hrs_in_tmp = mod.hrs_in_tmp[tmp]
        return (
            mod.StorStressHrz_Starting_Energy_in_Storage_MWh[prj, tmp]
            + mod.StorStressHrz_Charge_MW[prj, tmp]
            * hrs_in_tmp
            * mod.stor_stress_hrz_charging_efficiency[prj]
            - mod.StorStressHrz_Discharge_MW[prj, tmp]
            * hrs_in_tmp
            / mod.stor_stress_hrz_discharging_efficiency[prj]
        )

    m.StorStressHrz_Ending_Energy_in_Storage_MWh = Expression(
        m.STOR_STRESS_HRZ_STRESS_OPR_TMPS,
        initialize=ending_energy_in_storage_expression_rule,
    )

    # Constraints
    ###########################################################################

    # Power
    m.StorStressHrz_Max_Charge_Constraint = Constraint(
        m.STOR_STRESS_HRZ_OPR_TMPS, rule=max_charge_rule
    )

    m.StorStressHrz_Max_Discharge_Constraint = Constraint(
        m.STOR_STRESS_HRZ_STRESS_OPR_TMPS, rule=max_discharge_rule
    )

    # Average-condition horizon energy
    m.StorStressHrz_Avg_Hrz_Max_Stored_Energy_Constraint = Constraint(
        m.STOR_STRESS_HRZ_AVG_PRJ_PRDS, rule=avg_hrz_max_stored_energy_rule
    )

    # Stress horizon state of charge
    m.StorStressHrz_Stress_Hrz_Energy_Tracking_Constraint = Constraint(
        m.STOR_STRESS_HRZ_STRESS_OPR_TMPS, rule=stress_hrz_energy_tracking_rule
    )

    m.StorStressHrz_Stress_Hrz_Max_Energy_in_Storage_Constraint = Constraint(
        m.STOR_STRESS_HRZ_STRESS_OPR_TMPS, rule=stress_hrz_max_energy_in_storage_rule
    )

    m.StorStressHrz_Stress_Hrz_Last_Tmp_Min_Ending_Energy_Constraint = Constraint(
        m.STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ,
        rule=stress_hrz_last_tmp_min_ending_energy_rule,
    )

    m.StorStressHrz_Stress_Hrz_Last_Tmp_Max_Ending_Energy_Constraint = Constraint(
        m.STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ,
        rule=stress_hrz_last_tmp_max_ending_energy_rule,
    )


# Constraint Formulation Rules
###############################################################################


# Power
def max_charge_rule(mod, s, tmp):
    """
    **Constraint Name**: StorStressHrz_Max_Charge_Constraint
    **Enforced Over**: STOR_STRESS_HRZ_OPR_TMPS

    Storage charging power can't exceed available capacity.
    """
    return (
        mod.StorStressHrz_Charge_MW[s, tmp]
        <= mod.Capacity_MW[s, mod.period[tmp]]
        * mod.Availability_Derate[s, tmp]
        * mod.stor_stress_hrz_charging_capacity_multiplier[s]
    )


def max_discharge_rule(mod, s, tmp):
    """
    **Constraint Name**: StorStressHrz_Max_Discharge_Constraint
    **Enforced Over**: STOR_STRESS_HRZ_STRESS_OPR_TMPS

    Storage discharging power can't exceed available capacity.
    """
    return (
        mod.StorStressHrz_Discharge_MW[s, tmp]
        <= mod.Capacity_MW[s, mod.period[tmp]]
        * mod.Availability_Derate[s, tmp]
        * mod.stor_stress_hrz_discharging_capacity_multiplier[s]
    )


# Average-condition horizon energy
def avg_hrz_max_stored_energy_rule(mod, s, prd):
    """
    **Constraint Name**: StorStressHrz_Avg_Hrz_Max_Stored_Energy_Constraint
    **Enforced Over**: STOR_STRESS_HRZ_AVG_PRJ_PRDS

    The energy stored over the period's average-condition horizons can't
    exceed the project's energy capacity in the period.
    """
    return (
        mod.StorStressHrz_Avg_Hrz_Stored_Energy_MWh[s, prd]
        <= mod.Energy_Storage_Capacity_MWh[s, prd]
    )


# Stress horizon state of charge
def stress_hrz_energy_tracking_rule(mod, s, tmp):
    """
    **Constraint Name**: StorStressHrz_Stress_Hrz_Energy_Tracking_Constraint
    **Enforced Over**: STOR_STRESS_HRZ_STRESS_OPR_TMPS

    In the first timepoint of a stress horizon, the starting state of
    charge is the total energy stored over the same period's
    average-condition horizons. In every subsequent timepoint, the energy
    stored is equal to the energy stored in the previous timepoint minus
    any discharged power (adjusted for discharging efficiency and
    timepoint duration) plus any charged power (adjusted for charging
    efficiency and timepoint duration).
    """
    bt = mod.balancing_type_project[s]
    if check_if_first_timepoint(mod=mod, tmp=tmp, balancing_type=bt):
        prd = mod.period[tmp]
        if (s, prd) not in mod.STOR_STRESS_HRZ_AVG_PRJ_PRDS:
            raise ValueError(
                f"Project {s} of the stor_stress_hrz operational type has a "
                f"stress horizon in period {prd} but no average-condition "
                f"horizon in that period, so the starting state of charge "
                f"for the stress horizon is undefined. Check the "
                f"stor_stress_hrz_type inputs."
            )
        return (
            mod.StorStressHrz_Starting_Energy_in_Storage_MWh[s, tmp]
            == mod.StorStressHrz_Avg_Hrz_Stored_Energy_MWh[s, prd]
        )
    else:
        # Look up the previous timepoint once for all the terms below
        prev = mod.prev_tmp[tmp, bt]
        prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[prev]

        return mod.StorStressHrz_Starting_Energy_in_Storage_MWh[s, tmp] == (
            mod.StorStressHrz_Starting_Energy_in_Storage_MWh[s, prev]
            * mod.stor_stress_hrz_storage_efficiency[s]
            + mod.StorStressHrz_Charge_MW[s, prev]
            * prev_tmp_hrs_in_tmp
            * mod.stor_stress_hrz_charging_efficiency[s]
            - mod.StorStressHrz_Discharge_MW[s, prev]
            * prev_tmp_hrs_in_tmp
            / mod.stor_stress_hrz_discharging_efficiency[s]
        )


def stress_hrz_max_energy_in_storage_rule(mod, s, tmp):
    """
    **Constraint Name**: StorStressHrz_Stress_Hrz_Max_Energy_in_Storage_Constraint
    **Enforced Over**: STOR_STRESS_HRZ_STRESS_OPR_TMPS

    The amount of energy stored in each stress-horizon timepoint cannot
    exceed the available energy capacity.
    """
    return (
        mod.StorStressHrz_Starting_Energy_in_Storage_MWh[s, tmp]
        <= mod.Energy_Storage_Capacity_MWh[s, mod.period[tmp]]
        * mod.Availability_Derate[s, tmp]
    )


def stress_hrz_last_tmp_min_ending_energy_rule(mod, s, bt, hrz):
    """
    **Constraint Name**:
    StorStressHrz_Stress_Hrz_Last_Tmp_Min_Ending_Energy_Constraint
    **Enforced Over**: STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ

    The ending state of charge in the last timepoint of each stress horizon
    can't be negative, i.e., the project can't discharge energy it does not
    have. For all other timepoints this is implied by the energy tracking
    constraint and the non-negativity of the next timepoint's starting
    state of charge; the last timepoint needs an explicit bound because the
    first timepoint's state of charge is anchored to the average-condition
    energy build-up rather than tracked from the last timepoint.
    """
    last_tmp = mod.last_hrz_tmp[bt, hrz]
    return mod.StorStressHrz_Ending_Energy_in_Storage_MWh[s, last_tmp] >= 0


def stress_hrz_last_tmp_max_ending_energy_rule(mod, s, bt, hrz):
    """
    **Constraint Name**:
    StorStressHrz_Stress_Hrz_Last_Tmp_Max_Ending_Energy_Constraint
    **Enforced Over**: STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ

    The ending state of charge in the last timepoint of each stress horizon
    can't exceed the available energy capacity (same reasoning as for the
    minimum ending energy constraint).
    """
    last_tmp = mod.last_hrz_tmp[bt, hrz]
    return (
        mod.StorStressHrz_Ending_Energy_in_Storage_MWh[s, last_tmp]
        <= mod.Energy_Storage_Capacity_MWh[s, mod.period[last_tmp]]
        * mod.Availability_Derate[s, last_tmp]
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, s, tmp):
    """
    Power provision for stress-horizon storage resources is the net power
    (i.e.
    discharging minus charging). In average-condition horizons, there is no
    discharging variable, so the project can only draw power from the system.
    """
    if (s, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS:
        return (
            mod.StorStressHrz_Discharge_MW[s, tmp] - mod.StorStressHrz_Charge_MW[s, tmp]
        )
    else:
        return -mod.StorStressHrz_Charge_MW[s, tmp]


def variable_om_cost_rule(mod, g, tmp):
    """
    Variable O&M costs are applied only to the storage discharge, i.e. when
    the project is providing power to the system, which can only happen in
    stress horizons.
    """
    if (g, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS:
        return mod.StorStressHrz_Discharge_MW[g, tmp] * mod.variable_om_cost_per_mwh[g]
    else:
        return 0


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """ """
    if (prj, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS:
        return (
            mod.StorStressHrz_Discharge_MW[prj, tmp]
            * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
        )
    else:
        return 0


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """ """
    if (prj, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS:
        return (
            mod.StorStressHrz_Discharge_MW[prj, tmp]
            * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
        )
    else:
        return 0


def soc_penalty_cost_rule(mod, prj, tmp):
    """
    SOC penalties apply only in stress horizons, where the state of charge
    is tracked.
    """
    if (prj, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS:
        return mod.soc_penalty_cost_per_energyunit[prj] * (
            mod.Energy_Storage_Capacity_MWh[prj, mod.period[tmp]]
            * mod.Availability_Derate[prj, tmp]
            - mod.StorStressHrz_Ending_Energy_in_Storage_MWh[prj, tmp]
        )
    else:
        return 0


def soc_last_tmp_penalty_cost_rule(mod, prj, tmp):
    """
    Applied in the last timepoint of each stress horizon (the state of
    charge is not tracked in average-condition horizons).
    """
    if (prj, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS and check_if_last_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[prj]
    ):
        return mod.soc_last_tmp_penalty_cost_per_energyunit[prj] * (
            mod.Energy_Storage_Capacity_MWh[prj, mod.period[tmp]]
            * mod.Availability_Derate[prj, tmp]
            - mod.StorStressHrz_Ending_Energy_in_Storage_MWh[prj, tmp]
        )
    else:
        return 0


def power_delta_rule(mod, g, tmp):
    """
    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint. The previous timepoint is in the same horizon
    as the current one, so the two are always of the same horizon type.
    """
    bt = mod.balancing_type_project[g]
    if check_if_first_timepoint(mod=mod, tmp=tmp, balancing_type=bt) and (
        check_boundary_type(mod=mod, tmp=tmp, balancing_type=bt, boundary_type="linear")
        or check_boundary_type(
            mod=mod, tmp=tmp, balancing_type=bt, boundary_type="linked"
        )
    ):
        pass
    else:
        prev = mod.prev_tmp[tmp, bt]
        if (g, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS:
            return (
                mod.StorStressHrz_Discharge_MW[g, tmp]
                - mod.StorStressHrz_Charge_MW[g, tmp]
            ) - (
                mod.StorStressHrz_Discharge_MW[g, prev]
                - mod.StorStressHrz_Charge_MW[g, prev]
            )
        else:
            return (
                -mod.StorStressHrz_Charge_MW[g, tmp]
                + mod.StorStressHrz_Charge_MW[g, prev]
            )


# Input-Output
###############################################################################


def add_to_prj_tmp_results(mod):
    """
    Charging is reported in every operational timepoint; the state of charge
    and discharging exist only in stress horizons and are reported as NaN
    (empty in the results file) elsewhere.
    """
    results_columns = [
        "starting_energy_mwh",
        "charge_mw",
        "discharge_mw",
    ]
    data = [
        [
            prj,
            tmp,
            (
                value(mod.StorStressHrz_Starting_Energy_in_Storage_MWh[prj, tmp])
                if (prj, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS
                else float("nan")
            ),
            value(mod.StorStressHrz_Charge_MW[prj, tmp]),
            (
                value(mod.StorStressHrz_Discharge_MW[prj, tmp])
                if (prj, tmp) in mod.STOR_STRESS_HRZ_STRESS_OPR_TMPS
                else float("nan")
            ),
        ]
        for (prj, tmp) in mod.STOR_STRESS_HRZ_OPR_TMPS
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
    Export the total energy stored over each period's average-condition
    horizons to the project-period results. (Timepoint-level dispatch results
    are added to project_timepoint.csv via add_to_prj_tmp_results().)
    """
    results_columns = ["stor_stress_hrz_avg_hrz_stored_energy_mwh"]
    data = [
        [
            prj,
            prd,
            value(mod.StorStressHrz_Avg_Hrz_Stored_Energy_MWh[prj, prd]),
        ]
        for (prj, prd) in mod.STOR_STRESS_HRZ_AVG_PRJ_PRDS
    ]

    results_df = create_results_df(
        index_columns=["project", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PROJECT_PERIOD_DF), results_df)


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

    Get the horizon type designations ("average"/"stress") for the horizons
    in the current subproblem and stage. Horizon types can be specified for
    user-defined horizons (built-in horizons are not in
    inputs_temporal_horizon_timepoints and default to "average").
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

    # If the subscenario ID is not set for this scenario,
    # subscenarios.STOR_STRESS_HRZ_TYPE_SCENARIO_ID is the string "NULL" and
    # the query returns no rows (all horizons then default to "average")
    c = conn.cursor()
    hrz_types = c.execute(
        f"""SELECT balancing_type_horizon, horizon, stor_stress_hrz_type
        FROM inputs_project_stor_stress_hrz_types
        WHERE stor_stress_hrz_type_scenario_id =
        {subscenarios.STOR_STRESS_HRZ_TYPE_SCENARIO_ID}
        -- Only horizons in the current subproblem and stage, as other
        -- horizons are not valid indices of the model's horizon set
        AND (balancing_type_horizon, horizon) IN (
            SELECT DISTINCT balancing_type_horizon, horizon
            FROM inputs_temporal_horizon_timepoints
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {db_subproblem}
            AND stage_id = {db_stage}
        )
        ORDER BY balancing_type_horizon, horizon;"""
    )

    return hrz_types


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
    stor_stress_hrz_horizon_types.tab file (skipped if there are no horizon type
    inputs for this scenario).
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

    fname = "stor_stress_hrz_horizon_types.tab"

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
        op_type="stor_stress_hrz",
    )

    # Horizon types; optional file -- horizons not in it (or all horizons if
    # the file doesn't exist) default to "average"
    hrz_type_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "stor_stress_hrz_horizon_types.tab",
    )
    if os.path.exists(hrz_type_filename):
        data_portal.load(
            filename=hrz_type_filename,
            select=("balancing_type_horizon", "horizon", "stor_stress_hrz_type"),
            param=mod.stor_stress_hrz_type,
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
        "stor_stress_hrz",
    )
