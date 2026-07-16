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
This operational type describes transmission lines whose flows are simulated
using a linear transport model, i.e. transmission flow is constrained to be
less than or equal to the line capacity. Line capacity can be defined for
both transmission flow directions. The user can define losses as a fraction
of line flow.

"""

import os
import pandas as pd
from pyomo.environ import (
    Set,
    Param,
    Var,
    Constraint,
    NonNegativeReals,
    Reals,
    PercentFraction,
)

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)

Negative_Infinity = float("-inf")
Infinity = float("inf")


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
    | | :code:`TX_SIMPLE`                                                     |
    |                                                                         |
    | The set of transmission lines of the :code:`tx_simple` operational      |
    | type.                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`TX_SIMPLE_OPR_TMPS`                                            |
    |                                                                         |
    | Two-dimensional set with transmission lines of the :code:`tx_simple`    |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`TX_SIMPLE_OPR_TMPS_W_MIN_LIMIT`                                |
    |                                                                         |
    | Subset of :code:`TX_SIMPLE_OPR_TMPS` restricted to line-timepoints      |
    | whose line-period has a lower flow limit (i.e. is in the transmission   |
    | capacity module's :code:`TX_OPR_PRDS_W_MIN_LIMIT`). The minimum-flow    |
    | and "from"-direction loss constraints are built over this subset, so a  |
    | line left unconstrained by its capacity type gets no such constraint.   |
    +-------------------------------------------------------------------------+
    | | :code:`TX_SIMPLE_OPR_TMPS_W_MAX_LIMIT`                                |
    |                                                                         |
    | Subset of :code:`TX_SIMPLE_OPR_TMPS` restricted to line-timepoints      |
    | whose line-period has an upper flow limit (analogous to                 |
    | :code:`TX_SIMPLE_OPR_TMPS_W_MIN_LIMIT`); scopes the maximum-flow and    |
    | "to"-direction loss constraints.                                        |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Params                                                                  |
    +=========================================================================+
    | | :code:`tx_simple_loss_factor`                                         |
    | | *Defined over*: :code:`TX_SIMPLE`                                     |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The fraction of power that is lost when transmitted over this line.     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`TxSimple_Transmit_Power_MW`                                    |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The transmission line's power flow in each timepoint in which the line  |
    | is operational. Negative power means the power flow goes in the         |
    | opposite direction of the line's defined direction.                     |
    +-------------------------------------------------------------------------+
    | | :code:`TxSimple_Losses_LZ_From_MW`                                    |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Losses on the transmission line in each timepoint, which we'll account  |
    | for in the "from" origin load zone's load balance, i.e. losses incurred |
    | when power is flowing to the "from" zone.                               |
    +-------------------------------------------------------------------------+
    | | :code:`TxSimple_Losses_LZ_To_MW`                                      |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Losses on the transmission line in each timepoint, which we'll account  |
    | for in the "to" origin load zone's load balance, i.e. losses incurred   |
    | when power is flowing to the "to" zone.                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`TxSimple_Min_Transmit_Constraint`                              |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    |                                                                         |
    | Transmitted power should exceed the transmission line's minimum power   |
    | flow for in every operational timepoint.                                |
    +-------------------------------------------------------------------------+
    | | :code:`TxSimple_Max_Transmit_Constraint`                              |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    |                                                                         |
    | Transmitted power cannot exceed the transmission line's maximum power   |
    | flow in every operational timepoint.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`TxSimple_Losses_LZ_From_Constraint`                            |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    |                                                                         |
    | Losses to be accounted for in the "from" load zone's load balance are 0 |
    | when power flow on the line is positive (power flowing from the "from"  |
    | to the "to" load zone) and must be greater than or equal to  the flow   |
    | times the loss factor otherwise (power flowing to the "from" load zone).|
    +-------------------------------------------------------------------------+
    | | :code:`TxSimple_Losses_LZ_To_Constraint`                              |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    |                                                                         |
    | Losses to be accounted for in the "to" load zone's load balance are 0   |
    | when power flow on the line is negative (power flowing from the "to"    |
    | to the "from" load zone) and must be greater than or equal to the flow  |
    | times the loss factor otherwise (power flowing to the "to" load zone).  |
    +-------------------------------------------------------------------------+
    | | :code:`TxSimple_Max_Losses_From_Constraint`                           |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    |                                                                         |
    | Losses cannot exceed the maximum transmission flow capacity times the   |
    | loss factor in each operational timepoint. Provides upper bound on      |
    | losses.                                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`TxSimple_Max_Losses_To_Constraint`                             |
    | | *Defined over*: :code:`TX_SIMPLE_OPR_TMPS`                            |
    |                                                                         |
    | Losses cannot exceed the maximum transmission flow capacity times the   |
    | loss factor in each operational timepoint. Provides upper bound on      |
    | losses.                                                                 |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.TX_SIMPLE = Set(
        within=m.TX_LINES,
        initialize=lambda mod: subset_init_by_param_value(
            mod=mod,
            set_name="TX_LINES",
            param_name="tx_operational_type",
            param_value="tx_simple",
        ),
    )

    m.TX_SIMPLE_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="TX_OPR_TMPS", index=0, membership_set=mod.TX_SIMPLE
        ),
    )

    # Operational timepoints whose line-period has a lower / upper flow limit.
    # Lines left unconstrained by their capacity type (e.g. a tx_spec line with
    # a blank min or max) are excluded, so no min/max flow constraint is built
    # for them. TX_OPR_PRDS_W_MIN_LIMIT / _W_MAX_LIMIT come from the
    # transmission capacity module.
    # Note: distinct from the identically-purposed but separately-fed
    # TX_SIMPLE_OPR_TMPS_W_{MIN,MAX}_CONSTRAINT sets in
    # transmission/operations/transmission_flow_limits.py (which come from the
    # optional transmission_flow_limits inputs). These "_LIMIT" sets come from
    # the line's *capacity* and gate the capacity-based transmit constraints.
    m.TX_SIMPLE_OPR_TMPS_W_MIN_LIMIT = Set(
        dimen=2,
        within=m.TX_SIMPLE_OPR_TMPS,
        initialize=lambda mod: [
            (tx, tmp)
            for (tx, tmp) in mod.TX_SIMPLE_OPR_TMPS
            if (tx, mod.period[tmp]) in mod.TX_OPR_PRDS_W_MIN_LIMIT
        ],
    )

    m.TX_SIMPLE_OPR_TMPS_W_MAX_LIMIT = Set(
        dimen=2,
        within=m.TX_SIMPLE_OPR_TMPS,
        initialize=lambda mod: [
            (tx, tmp)
            for (tx, tmp) in mod.TX_SIMPLE_OPR_TMPS
            if (tx, mod.period[tmp]) in mod.TX_OPR_PRDS_W_MAX_LIMIT
        ],
    )

    # Params
    ###########################################################################
    m.tx_simple_loss_factor = Param(m.TX_SIMPLE, within=PercentFraction, default=0)
    m.losses_tuning_cost_per_mw = Param(m.TX_SIMPLE, within=NonNegativeReals, default=0)
    # Variables
    ###########################################################################

    m.TxSimple_Transmit_Power_MW = Var(m.TX_SIMPLE_OPR_TMPS, within=Reals)
    m.TxSimple_Losses_LZ_From_MW = Var(m.TX_SIMPLE_OPR_TMPS, within=NonNegativeReals)

    m.TxSimple_Losses_LZ_To_MW = Var(m.TX_SIMPLE_OPR_TMPS, within=NonNegativeReals)

    # Constraints
    ###########################################################################

    m.TxSimple_Min_Transmit_Constraint = Constraint(
        m.TX_SIMPLE_OPR_TMPS_W_MIN_LIMIT, rule=min_transmit_rule
    )

    m.TxSimple_Max_Transmit_Constraint = Constraint(
        m.TX_SIMPLE_OPR_TMPS_W_MAX_LIMIT, rule=max_transmit_rule
    )

    m.TxSimple_Losses_LZ_From_Constraint = Constraint(
        m.TX_SIMPLE_OPR_TMPS, rule=losses_lz_from_rule
    )

    m.TxSimple_Losses_LZ_To_Constraint = Constraint(
        m.TX_SIMPLE_OPR_TMPS, rule=losses_lz_to_rule
    )

    # The loss upper bounds are the flow capacity times the loss factor, so
    # they only apply where that capacity is finite (min for the "from"
    # direction, max for the "to" direction).
    m.TxSimple_Max_Losses_From_Constraint = Constraint(
        m.TX_SIMPLE_OPR_TMPS_W_MIN_LIMIT, rule=max_losses_from_rule
    )

    m.TxSimple_Max_Losses_To_Constraint = Constraint(
        m.TX_SIMPLE_OPR_TMPS_W_MAX_LIMIT, rule=max_losses_to_rule
    )


# Constraint Formulation Rules
###############################################################################


# TODO: should these move to operations.py since all transmission op_types
#  have this constraint?
def min_transmit_rule(mod, l, tmp):
    """
    **Constraint Name**: TxSimple_Min_Transmit_Constraint
    **Enforced Over**: TX_SIMPLE_OPR_TMPS

    Transmitted power should exceed the minimum transmission flow capacity in
    each operational timepoint.
    """
    return (
        mod.TxSimple_Transmit_Power_MW[l, tmp]
        >= mod.Tx_Min_Capacity_MW[l, mod.period[tmp]]
        * mod.Tx_Availability_Derate[l, tmp]
    )


def max_transmit_rule(mod, l, tmp):
    """
    **Constraint Name**: TxSimple_Max_Transmit_Constraint
    **Enforced Over**: TX_SIMPLE_OPR_TMPS

    Transmitted power cannot exceed the maximum transmission flow capacity in
    each operational timepoint.
    """
    return (
        mod.TxSimple_Transmit_Power_MW[l, tmp]
        <= mod.Tx_Max_Capacity_MW[l, mod.period[tmp]]
        * mod.Tx_Availability_Derate[l, tmp]
    )


def losses_lz_from_rule(mod, l, tmp):
    """
    **Constraint Name**: TxSimple_Losses_LZ_From_Constraint
    **Enforced Over**: TX_SIMPLE_OPR_TMPS

    Losses for the 'from' load zone of this transmission line (non-negative
    variable) must be greater than or equal to the negative of the flow times
    the loss factor. When the flow on the line is negative, power is flowing
    to the 'from', so losses are positive. When the flow on the line is
    positive (i.e. power flowing from the 'from' load zone), losses can be set
    to zero.
    If the tx_simple_loss_factor is 0, losses are set to 0.
    WARNING: since we have a greater than or equal constraint here, whenever
    tx_simple_loss_factor is not 0, the model can incur line losses that are
    not actually real.
    """
    if mod.tx_simple_loss_factor[l] == 0:
        return mod.TxSimple_Losses_LZ_From_MW[l, tmp] == 0
    else:
        return (
            mod.TxSimple_Losses_LZ_From_MW[l, tmp]
            >= -mod.TxSimple_Transmit_Power_MW[l, tmp] * mod.tx_simple_loss_factor[l]
        )


def losses_lz_to_rule(mod, l, tmp):
    """
    **Constraint Name**: TxSimple_Losses_LZ_To_Constraint
    **Enforced Over**: TX_SIMPLE_OPR_TMPS

    Losses for the 'to' load zone of this transmission line (non-negative
    variable) must be greater than or equal to the flow times the loss
    factor. When the flow on the line is positive, power is flowing to the
    'to' LZ, so losses are positive. When the flow on the line is negative
    (i.e. power flowing from the 'to' load zone), losses can be set to zero.
    If the tx_simple_loss_factor is 0, losses are set to 0.
    WARNING: since we have a greater than or equal constraint here, whenever
    tx_simple_loss_factor is not 0, the model can incur line losses that are
    not actually real.
    """
    if mod.tx_simple_loss_factor[l] == 0:
        return mod.TxSimple_Losses_LZ_To_MW[l, tmp] == 0
    else:
        return (
            mod.TxSimple_Losses_LZ_To_MW[l, tmp]
            >= mod.TxSimple_Transmit_Power_MW[l, tmp] * mod.tx_simple_loss_factor[l]
        )


def max_losses_from_rule(mod, l, tmp):
    """
    **Constraint Name**: TxSimple_Max_Losses_From_Constraint
    **Enforced Over**: TX_SIMPLE_OPR_TMPS

    Losses cannot exceed the maximum transmission flow capacity times the
    loss factor in each operational timepoint. Provides upper bound on losses.
    """
    if mod.tx_simple_loss_factor[l] == 0:
        return mod.TxSimple_Losses_LZ_From_MW[l, tmp] == 0
    else:
        return (
            mod.TxSimple_Losses_LZ_From_MW[l, tmp]
            <= -mod.Tx_Min_Capacity_MW[l, mod.period[tmp]]
            * mod.Tx_Availability_Derate[l, tmp]
            * mod.tx_simple_loss_factor[l]
        )


def max_losses_to_rule(mod, l, tmp):
    """
    **Constraint Name**: TxSimple_Max_Losses_To_Constraint
    **Enforced Over**: TX_SIMPLE_OPR_TMPS

    Losses cannot exceed the maximum transmission flow capacity times the
    loss factor in each operational timepoint. Provides upper bound on losses.
    """
    if mod.tx_simple_loss_factor[l] == 0:
        return mod.TxSimple_Losses_LZ_To_MW[l, tmp] == 0
    else:
        return (
            mod.TxSimple_Losses_LZ_To_MW[l, tmp]
            <= mod.Tx_Max_Capacity_MW[l, mod.period[tmp]]
            * mod.Tx_Availability_Derate[l, tmp]
            * mod.tx_simple_loss_factor[l]
        )


# Transmission Operational Type Methods
###############################################################################


def transmit_power_rule(mod, line, tmp):
    """
    The power flow on this transmission line before accounting for losses.
    """
    return mod.TxSimple_Transmit_Power_MW[line, tmp]


def transmit_power_losses_lz_from_rule(mod, line, tmp):
    """
    Transmission losses that we'll account for in the origin
    load zone (load_zone_from) of this transmission line. These are zero
    when the flow is positive (power flowing from the origin load zone) and
    can be more than 0 when the flow is negative (power flowing to the
    origin load zone).
    """
    return mod.TxSimple_Losses_LZ_From_MW[line, tmp]


def transmit_power_losses_lz_to_rule(mod, line, tmp):
    """
    Transmission losses that we'll account for in the destination
    load zone (load_zone_to) of this transmission line. These are zero
    when the flow is negative (power flowing from the destination load zone)
    and can be more than 0 when the flow is positive (power flowing to the
    destination load zone).
    """
    return mod.TxSimple_Losses_LZ_To_MW[line, tmp]


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

    # Get the simple transport model lines
    df = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "transmission_lines.tab",
        ),
        sep="\t",
        usecols=[
            "transmission_line",
            "tx_operational_type",
            "tx_simple_loss_factor",
            "losses_tuning_cost_per_mw",
        ],
    )
    df = df[df["tx_operational_type"] == "tx_simple"]

    # Dict of loss factor by tx_simple line based on raw data
    loss_factor_raw = dict(zip(df["transmission_line"], df["tx_simple_loss_factor"]))
    loss_tuning_raw = dict(
        zip(df["transmission_line"], df["losses_tuning_cost_per_mw"])
    )

    # Convert loss factors to float and remove any missing data (will
    # default to 0 in the model)
    loss_factor = {
        line: float(loss_factor_raw[line])
        for line in loss_factor_raw
        if loss_factor_raw[line] != "."
    }

    loss_tuning = {
        line: float(loss_tuning_raw[line])
        for line in loss_tuning_raw
        if loss_tuning_raw[line] != "."
    }

    # Load data
    data_portal.data()["tx_simple_loss_factor"] = loss_factor
    data_portal.data()["losses_tuning_cost_per_mw"] = loss_tuning
