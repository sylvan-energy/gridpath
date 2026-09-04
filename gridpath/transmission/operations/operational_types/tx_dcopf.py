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

r"""
This operational type describes transmission lines whose flows are simulated
using DC optimal power flow (OPF) equations. DC power flow is a linearized
approach to the AC Optimal Power Flow problem, which is a non-linear,
non-convex set of equations describing the energy flow through each
transmission line. The three main assumptions for the DC power flow
approximation are:

 1. line resistances are negligible compared to line reactances, so reactive
    power flows can be neglected;
 2. voltage magnitudes at each bus are kept at their nominal value; and
 3. voltage angle differences across branches are small enough such that the
    sine of the difference can be approximated by the difference, i.e.
    :math:`\sin(\\theta) \\approx \\theta`.

Using these approximations, the power flow problem becomes linear and can be
added to our capacity-expansion / unit commitment model using an additional
set of constraints for flows on each *tx_dcopf* line. The DC OPF constraints
are based on the Kirchhoff approach laid out in "Horsch et al. (2018).
Linear Optimal Power Flow Using Cycle Flows".

.. warning:: Transmission operational types can be optionally be mixed.
    However, if there are any transmission lines that do not have the
    *tx_dcopf* operational types, they will simply not be considered when
    setting up the network constraints laid out in the *tx_dcopf* module, so
    the network flows will be inaccurate.

.. warning:: GridPath uses one user-specified reactance to characterize a
    transmission line and this value doesn't change across time periods, even
    when the planned transmission capacity changes or when the model selects to
    build additional capacity (in the case of new build transmission). If
    this is not a reasonable assumption for the transmission system of
    interest, we recommended not to use the *tx_dcopf* operational type.

"""

import networkx as nx
import os
import pandas as pd

from pyomo.environ import Set, Var, Constraint, Reals, Param

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
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
    | | :code:`TX_DCOPF`                                                      |
    |                                                                         |
    | The set of transmission lines of the :code:`tx_dcopf` operational type. |
    +-------------------------------------------------------------------------+
    | | :code:`TX_DCOPF_OPR_TMPS`                                             |
    |                                                                         |
    | Two-dimensional set with transmission lines of the :code:`tx_dcopf`     |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`TX_DCOPF_OPR_TMPS_W_MIN_CONSTRAINT`                            |
    |                                                                         |
    | Subset of :code:`TX_DCOPF_OPR_TMPS` restricted to line-timepoints whose |
    | line-period has a lower flow limit (i.e. is in the transmission         |
    | capacity module's :code:`TX_OPR_PRDS_W_MIN_LIMIT`). The minimum-flow    |
    | constraint is built over this subset, so a line left unconstrained by   |
    | its capacity type gets no such constraint.                              |
    +-------------------------------------------------------------------------+
    | | :code:`TX_DCOPF_OPR_TMPS_W_MAX_CONSTRAINT`                            |
    |                                                                         |
    | Subset of :code:`TX_DCOPF_OPR_TMPS` restricted to line-timepoints whose |
    | line-period has an upper flow limit (analogous to                       |
    | :code:`TX_DCOPF_OPR_TMPS_W_MIN_CONSTRAINT`); scopes the maximum-flow    |
    | constraint.                                                             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Sets                                                            |
    +=========================================================================+
    | | :code:`PRDS_CYCLES_ZONES`                                             |
    |                                                                         |
    | Three-dimensional set describing the combination of periods, cycles,    |
    | and zones/nodes. A cycle is a "basic cycle" in the network as defined   |
    | in graph theory. This is the key set on which most other sets are       |
    | derived.                                                                |
    +-------------------------------------------------------------------------+
    | | :code:`PRDS_CYCLES`                                                   |
    |                                                                         |
    | Two-dimensional set with the period and cycle_id of the independent     |
    | cycles of the network graph (the network can change between periods).   |
    +-------------------------------------------------------------------------+
    | | :code:`CYCLES_OPR_TMPS`                                               |
    |                                                                         |
    | Two-dimensional set with of cycle IDs and operational timepoints.       |
    | KVL constraint is indexed by this set.                                  |
    +-------------------------------------------------------------------------+
    | | :code:`ZONES_IN_PRD_CYCLE`                                            |
    | | *Defined over*: :code:`PRDS_CYCLES`                                   |
    |                                                                         |
    | Indexed set of ordered zones/nodes by period-cycle. Helper set, not     |
    | directly used in constraints/param indices.                             |
    +-------------------------------------------------------------------------+
    | | :code:`PRDS_CYCLES_TX_DCOPF`                                          |
    |                                                                         |
    | Three-dimensional set of periods, cycle_ids, and transmission lines in  |
    | that period-cycle. This set is used to determine the set                |
    | :code:`TX_DCOPF_IN_PRD_CYCLE`.                                          |
    +-------------------------------------------------------------------------+
    | | :code:`TX_DCOPF_IN_PRD_CYCLE`                                         |
    | | *Defined over*: :code:`PRDS_CYCLES`                                   |
    |                                                                         |
    | Indexed set of transmission lines in each period-cycle. This set is     |
    | used in the KVL constraint when summing up the values.                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Params                                                         |
    +=========================================================================+
    | | :code:`tx_dcopf_reactance_ohms`                                       |
    | | *Defined over*: :code:`TX_DCOPF`                                      |
    |                                                                         |
    | The series reactance in Ohms for each :code:`tx_dcopf` transmission     |
    | line.                                                                   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Params                                                          |
    +=========================================================================+
    | | :code:`tx_dcopf_cycle_direction`                                      |
    | | *Defined over*: :code:`PRDS_CYCLES_TX_DCOPF`                          |
    |                                                                         |
    | The value of the cycle incidence matrix for each period-cycle-tx_line.  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`TxDcopf_Transmit_Power_MW`                                     |
    | | *Defined over*: :code:`TX_DCOPF_OPR_TMPS`                             |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The transmission line's power flow in each timepoint in which the line  |
    | is operational. Negative power means the power flow goes in the         |
    | opposite direction of the line's defined direction.                     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`TxDcopf_Min_Transmit_Constraint`                               |
    | | *Defined over*: :code:`TX_DCOPF_OPR_TMPS`                             |
    |                                                                         |
    | Transmitted power should exceed the transmission line's minimum power   |
    | flow for in every operational timepoint.                                |
    +-------------------------------------------------------------------------+
    | | :code:`TxDcopf_Max_Transmit_Constraint`                               |
    | | *Defined over*: :code:`TX_DCOPF_OPR_TMPS`                             |
    |                                                                         |
    | Transmitted power cannot exceed the transmission line's maximum power   |
    | flow in every operational timepoint.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`TxDcopf_Kirchhoff_Voltage_Law_Constraint`                      |
    | | *Defined over*: :code:`CYCLES_OPR_TMPS`                               |
    |                                                                         |
    | The sum of all potential difference across branches around all cycles   |
    | in the network must be zero. Using DC OPF assumptions, this can be      |
    | expressed in terms of the cycle incidence matrix and line reactance.    |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.TX_DCOPF = Set(
        within=m.TX_LINES,
        initialize=lambda mod: subset_init_by_param_value(
            mod=mod,
            set_name="TX_LINES",
            param_name="tx_operational_type",
            param_value="tx_dcopf",
        ),
    )

    m.TX_DCOPF_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="TX_OPR_TMPS", index=0, membership_set=mod.TX_DCOPF
        ),
    )

    # Operational timepoints whose line-period has a lower / upper flow limit;
    # lines left unconstrained by their capacity type are excluded so no
    # min/max flow constraint is built for them (see the transmission
    # capacity module's TX_OPR_PRDS_W_MIN_LIMIT / _W_MAX_LIMIT).
    m.TX_DCOPF_OPR_TMPS_W_MIN_CONSTRAINT = Set(
        dimen=2,
        within=m.TX_DCOPF_OPR_TMPS,
        initialize=lambda mod: [
            (tx, tmp)
            for (tx, tmp) in mod.TX_DCOPF_OPR_TMPS
            if (tx, mod.period[tmp]) in mod.TX_OPR_PRDS_W_MIN_LIMIT
        ],
    )

    m.TX_DCOPF_OPR_TMPS_W_MAX_CONSTRAINT = Set(
        dimen=2,
        within=m.TX_DCOPF_OPR_TMPS,
        initialize=lambda mod: [
            (tx, tmp)
            for (tx, tmp) in mod.TX_DCOPF_OPR_TMPS
            if (tx, mod.period[tmp]) in mod.TX_OPR_PRDS_W_MAX_LIMIT
        ],
    )

    # Derived Sets
    ###########################################################################

    m.PRDS_CYCLES_ZONES = Set(
        dimen=3, initialize=periods_cycles_zones_init, ordered=True
    )

    m.PRDS_CYCLES = Set(dimen=2, initialize=period_cycles_init)

    # Note: This assumes timepoints are unique across periods
    m.CYCLES_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: list(
            set((c, tmp) for (p, c) in mod.PRDS_CYCLES for tmp in mod.TMPS_IN_PRD[p])
        ),
    )

    m.ZONES_IN_PRD_CYCLE = Set(
        m.PRDS_CYCLES, initialize=zones_by_period_cycle_init, ordered=True
    )

    m.PRDS_CYCLES_TX_DCOPF = Set(
        dimen=3,
        within=m.PRDS_CYCLES * m.TX_LINES,
        initialize=periods_cycles_transmission_lines_init,
    )

    m.TX_DCOPF_IN_PRD_CYCLE = Set(
        m.PRDS_CYCLES, initialize=tx_lines_by_period_cycle_init
    )

    # Required Params
    ###########################################################################

    m.tx_dcopf_reactance_ohms = Param(m.TX_DCOPF)

    # Derived Params
    ###########################################################################

    m.tx_dcopf_cycle_direction = Param(
        m.PRDS_CYCLES_TX_DCOPF, initialize=tx_dcopf_cycle_direction_init
    )

    # Variables
    ###########################################################################

    m.TxDcopf_Transmit_Power_MW = Var(m.TX_DCOPF_OPR_TMPS, within=Reals)

    # Constraints
    ###########################################################################

    m.TxDcopf_Min_Transmit_Constraint = Constraint(
        m.TX_DCOPF_OPR_TMPS_W_MIN_CONSTRAINT, rule=min_transmit_rule
    )

    m.TxDcopf_Max_Transmit_Constraint = Constraint(
        m.TX_DCOPF_OPR_TMPS_W_MAX_CONSTRAINT, rule=max_transmit_rule
    )

    m.TxDcopf_Kirchhoff_Voltage_Law_Constraint = Constraint(
        m.CYCLES_OPR_TMPS, rule=kirchhoff_voltage_law_rule
    )


# Set Rules
###############################################################################


def periods_cycles_zones_init(mod):
    """
    Use the networkx module to determine the elementary (basic) cycles in the
    network graph, where a cycle is defined by the list of unordered zones
    (nodes) that belong to it. We do this for each period since the network
    can change between periods as we add/remove transmission lines (edges).

    The result is returned as a 3-dimensional set of period-cycle-zone
    combinations, e.g. (2030, 1, zone1) means that zone1 belongs to cycle 1
    in period 2030. This is the key set on which all other derived sets are
    based such that we onlyl have to perform the networkx calculations once.
    """
    result = list()
    for period in mod.PERIODS:
        # Get the relevant tx_lines (= currently operational & DC OPF)
        tx_lines = list(mod.TX_DCOPF & mod.TX_LINES_OPR_IN_PRD[period])

        # Get the edges from the relevant tx_lines
        edges = [(mod.load_zone_to[tx], mod.load_zone_from[tx]) for tx in tx_lines]
        # TODO: make sure there are no parallel edges (or pre-process those)

        # Create a network graph from the list of lines (edges) and find
        # the elementary cycles (if any)
        graph = nx.Graph()
        graph.add_edges_from(edges)
        cycles = nx.cycle_basis(graph)  # list w list of zones for each cycle
        for cycle_id, cycle in enumerate(cycles):
            for zone in cycle:
                result.append((period, cycle_id, zone))
    return result


def period_cycles_init(mod):
    """
    Determine the period-cycle combinations from the larger PRDS_CYCLES_ZONES
    set. Note: set() will remove duplicates.
    """
    return list(set([(p, c) for (p, c, z) in mod.PRDS_CYCLES_ZONES]))


def zones_by_period_cycle_init(mod, period, cycle):
    """
    Re-arrange the 3-dimensional PRDS_CYCLES_ZONES set into a 1-dimensional
    set of ZONES, indexed by PRD_CYCLES
    """
    zones = [z for (p, c, z) in mod.PRDS_CYCLES_ZONES if p == period and c == cycle]
    return zones


def periods_cycles_transmission_lines_init(mod):
    """
    Based on which zones are in which cycle in each period (as defined in
    ZONES_IN_PRD_CYCLE), create a 3-dimensional set describing which
    transmission lines are in which cycle during each period.

    Note: Alternatively, we could simply define this set by the bigger set
    m.PRDS_CYCLES * m.TX_DCOPF and set the tx_dcopf_cycle_direction to zero
    whenever the line is not part of the cycle. This would get rid of the
    repetitive code in the init function below at the cost of iterating over
    more tx_lines than necessary in the summation of the KVL constraint.
    """
    result = list()
    for p, c in mod.PRDS_CYCLES:
        # Ordered list of zones in the current cycle
        zones = list(mod.ZONES_IN_PRD_CYCLE[(p, c)])

        # Relevant tx_lines
        tx_lines = list(mod.TX_DCOPF & mod.TX_LINES_OPR_IN_PRD[p])

        # Get the edges from the relevant tx_lines
        edges = [(mod.load_zone_to[tx], mod.load_zone_from[tx]) for tx in tx_lines]

        # Get the tx lines in this cycle
        for tx_from, tx_to in zip(zones[-1:] + zones[:-1], zones):
            try:
                index = edges.index((tx_from, tx_to))
            except:
                try:
                    # Revert direction
                    index = edges.index((tx_to, tx_from))
                except:
                    raise ValueError(
                        "The branch connecting {} and {} is not in the "
                        "transmission line inputs".format(tx_from, tx_to)
                    )
            tx_line = tx_lines[index]
            result.append((p, c, tx_line))
    return result


def tx_lines_by_period_cycle_init(mod, period, cycle):
    """
    Re-arrange the 3-dimensional PRDS_CYCLES_TX_DCOPF set into a 1-dimensional
    set of TX_DCOPF, indexed by PRD_CYCLES.
    """
    txs = list(
        tx for (p, c, tx) in mod.PRDS_CYCLES_TX_DCOPF if c == cycle and p == period
    )
    return txs


# Param Rules
###############################################################################


def tx_dcopf_cycle_direction_init(mod, period, cycle, tx_line):
    """
    **Param Name**: tx_dcopf_cycle_direction
    **Defined Over**: PRDS_CYCLES_TX_DCOPF

    This parameter describes the non-zero values of the cycle incidence
    matrix in each period. The parameter's value is 1 if the given tx_line
    is an element of the given cycle in the given period and -1 if it is the
    case for the reversed transmission line. The index of this param already
    excludes combinations of transmission lines that aren't part of a cycle,
    so the value is never zero.

    Note: The cycle direction is randomly determined by the networkx
    algorithm which means the param values can all be multiplied by (-1)
    in some model runs compared ot others.

    See "Horsch et al. (2018). Linear Optimal Power Flow Using Cycle Flows"
    for more background.
    """
    zones = list(mod.ZONES_IN_PRD_CYCLE[(period, cycle)])
    from_to = (mod.load_zone_from[tx_line], mod.load_zone_to[tx_line])
    if from_to in zip(zones[-1:] + zones[:-1], zones):
        direction = 1
    elif from_to in zip(zones, zones[-1:] + zones[:-1]):
        direction = -1
    else:
        raise ValueError(
            "The branch connecting {} and {} is not in the "
            "transmission line inputs".format(
                mod.load_zone_from[tx_line], mod.load_zone_to[tx_line]
            )
        )
    return direction


# Constraint Formulations
###############################################################################


def min_transmit_rule(mod, l, tmp):
    """
    **Constraint Name**: TxDcopf_Min_Transmit_Constraint
    **Enforced Over**: TX_DCOPF_OPR_TMPS

    Transmitted power should exceed the minimum transmission flow capacity in
    each operational timepoint.
    """
    return (
        mod.TxDcopf_Transmit_Power_MW[l, tmp]
        >= mod.Tx_Min_Capacity_MW[l, mod.period[tmp]]
        * mod.Tx_Availability_Derate[l, tmp]
    )


def max_transmit_rule(mod, l, tmp):
    """
    **Constraint Name**: TxDcopf_Max_Transmit_Constraint
    **Enforced Over**: TX_DCOPF_OPR_TMPS

    Transmitted power cannot exceed the maximum transmission flow capacity in
    each operational timepoint.
    """
    return (
        mod.TxDcopf_Transmit_Power_MW[l, tmp]
        <= mod.Tx_Max_Capacity_MW[l, mod.period[tmp]]
        * mod.Tx_Availability_Derate[l, tmp]
    )


def kirchhoff_voltage_law_rule(mod, c, tmp):
    """
    **Constraint Name**: TxDcopf_Kirchhoff_Voltage_Law_Constraint
    **Enforced Over**: CYCLES_OPR_TMPS

    The sum of all potential difference across branches around all cycles
    in the network must be zero in each operational timepoint. In DC power
    flow we assume all voltage magnitudes are kept at nominal value and the
    voltage  angle differences across branches is small enough that we can
    approximate the sinus of the angle with the angle itself, i.e. sin(
    theta) ~ theta. We can therefore write KVL in terms of voltage angles as
    follows:

    ..math:: \\sum_{l} C_{l,c} * \theta_{l} = 0   \\forall c = 1,...,L-N+1

    Using the linearized relationship between voltage angle
    differences across branches and the line flow, :math:`\theta_{l} = x_{l}
    * f_{l}`, we can factor out the voltage angles and write KVL purely in
    terms of line flows and line reactances:

    .. math:: C_{l,c} * x_{l} * f_{l} = 0   \\forall c = 1,...,L-N+1

    The latter equation is enforced in this constraint.

    Note: While most power flow formulations normalize all inputs to per
    unit (p.u.) we can safely avoid that here since the normalization
    factors out in the equation, and it is really just about the relative
    magnitude of the reactance of the lines.

    Source: Horsch et al. (2018). Linear Optimal Power Flow Using Cycle Flows
    """

    return (
        sum(
            mod.TxDcopf_Transmit_Power_MW[l, tmp]
            * mod.tx_dcopf_cycle_direction[mod.period[tmp], c, l]
            * mod.tx_dcopf_reactance_ohms[l]
            for l in mod.TX_DCOPF_IN_PRD_CYCLE[mod.period[tmp], c]
        )
        == 0
    )


# Operational Type Methods
###############################################################################


def transmit_power_rule(mod, l, tmp):
    """ """
    return mod.TxDcopf_Transmit_Power_MW[l, tmp]


def transmit_power_losses_lz_from_rule(mod, line, tmp):
    """
    No losses in DC OPF module for now.
    """
    return 0


def transmit_power_losses_lz_to_rule(mod, line, tmp):
    """
    No losses in DC OPF module for now.
    """
    return 0


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

    # Get the DC OPF lines
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
            "load_zone_from",
            "load_zone_to",
            "tx_operational_type",
            "reactance_ohms",
        ],
    )
    df = df[df["tx_operational_type"] == "tx_dcopf"]

    # Dict of reactance by tx_dcopf line
    reactance_ohms = dict(
        zip(df["transmission_line"], pd.to_numeric(df["reactance_ohms"]))
    )

    # Load data
    data_portal.data()["tx_dcopf_reactance_ohms"] = reactance_ohms
