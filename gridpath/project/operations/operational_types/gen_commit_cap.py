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
This module describes the operations of generation projects with 'capacity
commitment' operational decisions, i.e. continuous variables to commit some
level of capacity below the total capacity of the project. This operational
type is particularly well suited for application to 'fleets' of generators
with the same characteristics. For example, we could have a GridPath project
with a total capacity of 2000 MW, which actually consists of four 500-MW
units. The optimization decides how much total capacity to commit (i.e. turn
on), e.g. if 2000 MW are committed, then four generators (x 500 MW) are on
and if 500 MW are committed, then one generator is on, etc.

The capacity commitment decision variables are continuous. This approach
makes it possible to reduce problem size by grouping similar generators
together and linearizing the commitment decisions.

The optimization makes the capacity-commitment and dispatch decisions in
every timepoint. Project power output can vary between a minimum loading level
(specified as a fraction of committed capacity) and the committed capacity
in each timepoint when the project is available. Heat rate degradation below
full load is considered. These projects can be allowed to provide upward
and/or downward reserves.

No standard approach exists for applying ramp rate and minimum up and down
time constraints to this operational type. GridPath does include
experimental functionality for doing so. Starts and stops -- and the
associated cost and emissions -- can also be tracked and constrained for
this operational type.

Costs for this operational type include fuel costs, variable O&M costs, and
startup and shutdown costs.

"""

import csv
import os.path
import pandas as pd
from pyomo.environ import (
    Var,
    Set,
    Constraint,
    Param,
    NonNegativeReals,
    NonPositiveReals,
    PercentFraction,
    Reals,
    value,
    Expression,
)

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.dynamic_components import headroom_variables, footroom_variables
from gridpath.project.operations.reserves.reserve_aggregation import (
    headroom_provision_rule,
    footroom_provision_rule,
)
from gridpath.project.operations.operational_types.common_functions import (
    determine_relevant_timepoints,
    load_optype_model_data,
    check_for_tmps_to_link,
    validate_opchars,
)
from gridpath.common_functions import create_results_df
from gridpath.project.common_functions import (
    check_if_boundary_type_and_first_timepoint,
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
    | | :code:`GEN_COMMIT_CAP`                                                |
    |                                                                         |
    | The set of generators of the `gen_commit_cap` operational type          |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_COMMIT_CAP_OPR_TMPS`                                       |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_commit_cap`       |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_COMMIT_CAP_LINKED_TMPS`                                    |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_commit_cap`       |
    | operational type and their linked timepoints.                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_commit_cap_unit_size_mw`                                   |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The MW size of a unit in this project (projects of the                  |
    | :code:`gen_commit_cap` type can represent a fleet of similar units).    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_min_stable_level_fraction`                      |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The minimum stable level of this project as a fraction of its capacity. |
    | This can also be interpreted as the minimum stable level of a unit      |
    | within this project (as the project itself can represent multiple       |
    | units with similar characteristics.                                     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_commit_cap_startup_plus_ramp_up_rate`                      |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's ramp rate when starting up as percent of project capacity |
    | per minute (defaults to 1 if not specified).                            |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_shutdown_plus_ramp_down_rate`                   |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's ramp rate when shutting down as percent of project        |
    | capacity per minute (defaults to 1 if not specified).                   |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_ramp_up_when_on_rate`                           |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's upward ramp rate limit during operations, defined as a    |
    | fraction of its capacity per minute.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_ramp_down_when_on_rate`                         |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's downward ramp rate limit during operations, defined as a  |
    | fraction of its capacity per minute.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_min_up_time_hours`                              |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's minimum up time in hours.                                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_min_down_time_hours`                            |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's minimum down time in hours.                               |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_aux_consumption_frac_capacity`                  |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of committed capacity.              |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_aux_consumption_frac_power`                     |
    | | *Defined over*: :code:`GEN_COMMIT_CAP`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of gross power output.              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Linked Input Params                                                     |
    +=========================================================================+
    | | :code:`gen_commit_cap_linked_commit_capacity`                         |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's committed capacity in the linked timepoints.              |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_linked_power`                                   |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's power provision in the linked timepoints.                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_linked_upwards_reserves`                        |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's upward reserve provision in the linked timepoints.        |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_linked_downwards_reserves`                      |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's downward reserve provision in the linked timepoints.      |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_linked_startup`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's startup in the linked timepoints.                         |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_cap_linked_shutdown`                                |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's shutdown in the linked timepoints.                        |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenCommitCap_Provide_Power_MW`                                 |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Power provision in MW from this project in each timepoint in which the  |
    | project is operational (capacity exists and the project is available).  |
    | If modeling auxiliary consumption, this is the gross power output.      |
    +-------------------------------------------------------------------------+
    | | :code:`Commit_Capacity_MW`                                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | A continuous variable that represents the commitment state of the       |
    | (i.e. of the units represented by this project).                        |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Fuel_Burn_MMBTU`                                  |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Fuel burn by this project in each operational timepoint.                |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Up_Startup_MW`                                            |
    | | *Within*: :code:`Reals`                                               |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | The upward ramp of the project when capacity is started up.             |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Down_Startup_MW`                                          |
    | | *Within*: :code:`Reals`                                               |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | The downward ramp of the project when capacity is shutting down.        |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Up_When_On_MW`                                            |
    | | *Within*: :code:`Reals`                                               |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | The upward ramp of the project when capacity on.                        |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Down_When_On_MW`                                          |
    | | *Within*: :code:`Reals`                                               |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | The downward ramp of the project when capacity is on.                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Startup_MW`                                       |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | The amount of capacity started up (in MW).                              |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Shutdown_MW`                                      |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | The amount of capacity shut down (in MW).                               |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`GenCommitCap_Auxiliary_Consumption_MW`                         |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | The project's auxiliary consumption (power consumed on-site and not     |
    | sent to the grid) in each timepoint.                                    |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Commitment and Power                                                    |
    +-------------------------------------------------------------------------+
    | | :code:`Commit_Capacity_Constraint`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits committed capacity to the available capacity.                    |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Max_Power_Constraint`                             |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the power plus upward reserves to the committed capacity.        |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Min_Power_Constraint`                             |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the power provision minus downward reserves to the minimum       |
    | stable level for the project.                                           |
    +-------------------------------------------------------------------------+
    | Ramps                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Up_Off_to_On_Constraint`                                  |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project upward ramp when turning capacity on based   |
    | on the :code:`gen_commit_cap_startup_plus_ramp_up_rate`.                |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Up_When_On_Constraint`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project upward ramp when capacity is on based on     |
    | the :code:`gen_commit_cap_ramp_up_when_on_rate`.                        |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Up_When_On_Headroom_Constraint`                           |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project upward ramp based on the headroom available  |
    | in the previous timepoint.                                              |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Ramp_Up_Constraint`                               |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project upward ramp (regardless of commitment state).|
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Down_On_to_Off_Constraint`                                |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project downward ramp when turning capacity on based |
    | on the :code:`gen_commit_cap_shutdown_plus_ramp_down_rate`.             |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Down_When_On_Constraint`                                  |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project downward ramp when capacity is on based on   |
    | the :code:`gen_commit_cap_ramp_down_when_on_rate`.                      |
    +-------------------------------------------------------------------------+
    | | :code:`Ramp_Down_When_On_Headroom_Constraint`                         |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project downward ramp based on the headroom          |
    | available in the current timepoint.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Ramp_Down_Constraint`                             |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project downward ramp (regardless of commitment      |
    | state).                                                                 |
    +-------------------------------------------------------------------------+
    | Minimum Up and Down Time                                                |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Startup_Constraint`                               |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the capacity started up to the difference in commitment between  |
    | the current and previous timepoint.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Shutdown_Constraint`                              |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Limits the capacity shut down to the difference in commitment between   |
    | the current and previous timepoint.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Min_Up_Time_Constraint`                           |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Requires that when units within this project are started, they stay on  |
    | for at least :code:`gen_commit_cap_min_up_time_hours`.                  |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitCap_Min_Down_Time_Constraint`                         |
    | | *Defined over*: :code:`GEN_COMMIT_CAP_OPR_TMPS`                       |
    |                                                                         |
    | Requires that when units within this project are stopped, they stay off |
    | for at least :code:`gen_commit_cap_min_down_time_hours`.                |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################
    m.GEN_COMMIT_CAP = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_commit_cap"
        ),
    )

    m.GEN_COMMIT_CAP_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.GEN_COMMIT_CAP
        ),
    )

    m.GEN_COMMIT_CAP_LINKED_TMPS = Set(dimen=2)

    # Required Params
    ###########################################################################
    m.gen_commit_cap_unit_size_mw = Param(m.GEN_COMMIT_CAP, within=NonNegativeReals)
    m.gen_commit_cap_min_stable_level_fraction = Param(
        m.GEN_COMMIT_CAP, within=PercentFraction
    )

    # Optional Params
    ###########################################################################

    m.gen_commit_cap_startup_plus_ramp_up_rate = Param(
        m.GEN_COMMIT_CAP, within=PercentFraction, default=1
    )
    m.gen_commit_cap_shutdown_plus_ramp_down_rate = Param(
        m.GEN_COMMIT_CAP, within=PercentFraction, default=1
    )
    m.gen_commit_cap_ramp_up_when_on_rate = Param(
        m.GEN_COMMIT_CAP, within=PercentFraction, default=1
    )
    m.gen_commit_cap_ramp_down_when_on_rate = Param(
        m.GEN_COMMIT_CAP, within=PercentFraction, default=1
    )
    m.gen_commit_cap_min_up_time_hours = Param(
        m.GEN_COMMIT_CAP, within=NonNegativeReals, default=1
    )
    m.gen_commit_cap_min_down_time_hours = Param(
        m.GEN_COMMIT_CAP, within=NonNegativeReals, default=1
    )

    m.gen_commit_cap_aux_consumption_frac_capacity = Param(
        m.GEN_COMMIT_CAP, within=PercentFraction, default=0
    )

    m.gen_commit_cap_aux_consumption_frac_power = Param(
        m.GEN_COMMIT_CAP, within=PercentFraction, default=0
    )

    # Linked Params
    ###########################################################################

    m.gen_commit_cap_linked_commit_capacity = Param(
        m.GEN_COMMIT_CAP_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_commit_cap_linked_power = Param(
        m.GEN_COMMIT_CAP_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_commit_cap_linked_upwards_reserves = Param(
        m.GEN_COMMIT_CAP_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_commit_cap_linked_downwards_reserves = Param(
        m.GEN_COMMIT_CAP_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_commit_cap_linked_startup = Param(
        m.GEN_COMMIT_CAP_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_commit_cap_linked_shutdown = Param(
        m.GEN_COMMIT_CAP_LINKED_TMPS, within=NonNegativeReals
    )

    # Variables
    ###########################################################################
    m.GenCommitCap_Provide_Power_MW = Var(
        m.GEN_COMMIT_CAP_OPR_TMPS, within=NonNegativeReals
    )
    m.Commit_Capacity_MW = Var(m.GEN_COMMIT_CAP_OPR_TMPS, within=NonNegativeReals)

    # Variables for optional ramp constraints
    # We'll have separate treatment of ramps of:
    # generation that is online in both the current and the previous timepoint
    # and of
    # generation that is either started up or shut down since the previous
    # timepoint

    # Ramp_Up_Startup_MW and Ramp_Down_Shutdown_MW must be able to take
    # either positive  or negative values, as they are both constrained by
    # a product of a positive number and the difference committed capacity
    # between the current and previous timepoints (which needs to be able to
    # take on both positive values when turning units on and negative values
    # when turning units off)
    # They also need to be separate variables, as if they were combined,
    # the only solution would be for there to be no startups/shutdowns
    m.Ramp_Up_Startup_MW = Var(m.GEN_COMMIT_CAP_OPR_TMPS, within=Reals)
    m.Ramp_Down_Shutdown_MW = Var(m.GEN_COMMIT_CAP_OPR_TMPS, within=Reals)

    m.Ramp_Up_When_On_MW = Var(m.GEN_COMMIT_CAP_OPR_TMPS, within=NonNegativeReals)
    m.Ramp_Down_When_On_MW = Var(m.GEN_COMMIT_CAP_OPR_TMPS, within=NonPositiveReals)

    # Variables for constraining up and down time
    # Startup and shutdown variables, must be non-negative
    m.GenCommitCap_Startup_MW = Var(m.GEN_COMMIT_CAP_OPR_TMPS, within=NonNegativeReals)
    m.GenCommitCap_Shutdown_MW = Var(m.GEN_COMMIT_CAP_OPR_TMPS, within=NonNegativeReals)

    # Expressions
    ###########################################################################
    # TODO: the reserve rules are the same in all modules, so should be
    #  consolidated
    def upwards_reserve_rule(mod, g, tmp):
        return headroom_provision_rule(d, mod, g, tmp)

    m.GenCommitCap_Upwards_Reserves_MW = Expression(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=upwards_reserve_rule
    )

    def downwards_reserve_rule(mod, g, tmp):
        return footroom_provision_rule(d, mod, g, tmp)

    m.GenCommitCap_Downwards_Reserves_MW = Expression(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=downwards_reserve_rule
    )

    m.GenCommitCap_Auxiliary_Consumption_MW = Expression(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=auxiliary_consumption_rule
    )

    # Constraints
    ###########################################################################

    # Commitment and power
    m.Commit_Capacity_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=commit_capacity_constraint_rule
    )

    m.GenCommitCap_Max_Power_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=max_power_rule
    )

    m.GenCommitCap_Min_Power_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=min_power_rule
    )

    # Ramping
    m.Ramp_Up_Off_to_On_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=ramp_up_off_to_on_constraint_rule
    )

    m.Ramp_Up_When_On_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=ramp_up_on_to_on_constraint_rule
    )

    m.Ramp_Up_When_On_Headroom_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=ramp_up_on_to_on_headroom_constraint_rule
    )

    m.GenCommitCap_Ramp_Up_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=ramp_up_constraint_rule
    )

    m.Ramp_Down_On_to_Off_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=ramp_down_on_to_off_constraint_rule
    )

    m.Ramp_Down_When_On_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=ramp_down_on_to_on_constraint_rule
    )

    m.Ramp_Down_When_On_Headroom_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=ramp_down_on_to_on_headroom_constraint_rule
    )

    m.GenCommitCap_Ramp_Down_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=ramp_down_constraint_rule
    )

    # Min up and down time
    m.GenCommitCap_Startup_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=startup_constraint_rule
    )

    m.GenCommitCap_Shutdown_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=shutdown_constraint_rule
    )

    m.GenCommitCap_Min_Up_Time_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=min_up_time_constraint_rule
    )

    m.GenCommitCap_Min_Down_Time_Constraint = Constraint(
        m.GEN_COMMIT_CAP_OPR_TMPS, rule=min_down_time_constraint_rule
    )


# Expression Rules
###############################################################################
def auxiliary_consumption_rule(mod, g, tmp):
    """
    **Expression Name**: GenCommitCap_Auxiliary_Consumption_MW
    **Defined Over**: GEN_COMMIT_CAP_OPR_TMPS
    """
    return (
        mod.Commit_Capacity_MW[g, tmp]
        * mod.gen_commit_cap_aux_consumption_frac_capacity[g]
        + mod.GenCommitCap_Provide_Power_MW[g, tmp]
        * mod.gen_commit_cap_aux_consumption_frac_power[g]
    )


# Constraint Formulation Rules
###############################################################################


# Commitment and power
def commit_capacity_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: Commit_Capacity_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    Can't commit more capacity than available in each timepoint.
    """
    return (
        mod.Commit_Capacity_MW[g, tmp]
        <= mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
    )


def max_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenCommitCap_Max_Power_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    Power plus upward services cannot exceed capacity.
    """
    return (
        mod.GenCommitCap_Provide_Power_MW[g, tmp]
        + mod.GenCommitCap_Upwards_Reserves_MW[g, tmp]
        <= mod.Commit_Capacity_MW[g, tmp]
    )


def min_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenCommitCap_Min_Power_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    Power minus downward services cannot be below a minimum stable level.
    """
    return (
        mod.GenCommitCap_Provide_Power_MW[g, tmp]
        - mod.GenCommitCap_Downwards_Reserves_MW[g, tmp]
        >= mod.Commit_Capacity_MW[g, tmp]
        * mod.gen_commit_cap_min_stable_level_fraction[g]
    )


# Ramping
def ramp_up_off_to_on_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: Ramp_Up_Off_to_On_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    When turning on, generators can ramp up to a certain fraction of
    started up capacity. This fraction must be greater than or equal to
    the minimum stable level for the generator to be able to turn on.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_commit_capacity = mod.gen_commit_cap_linked_commit_capacity[g, 0]
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_commit_capacity = mod.Commit_Capacity_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]

        return (
            mod.Ramp_Up_Startup_MW[g, tmp]
            <= (mod.Commit_Capacity_MW[g, tmp] - prev_tmp_commit_capacity)
            * mod.gen_commit_cap_startup_plus_ramp_up_rate[g]
            * 60
            * prev_tmp_hrs_in_tmp
        )


def ramp_up_on_to_on_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: Ramp_Up_When_On_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    Generators online in the last timepoint, if still online, could have
    ramped up at a rate at or below the online capacity times a
    pre-specified ramp rate fraction. The max on to on ramp up
    allowed is if they all stayed online. Startups are treated separately.
    There are limitations to this approach. For example, if online
    capacity was producing at full power at t-2 and t-1, some additional
    capacity was turned on at t-1 and ramped to some level above its
    Pmin but not full output, this constraint would allow for the total
    committed capacity in t-1 to be ramped up, even though in reality
    only the started up capacity can be ramped as the capacity from t-2
    is already producing at full power. In reality, this situation is
    unlikely to be an issue, as most generators can ramp from Pmin to
    Pmax fully in an hour, so the fact that this constraint is too lax
    in this situation does not matter when modeling fleets at an hourly
    or coarser resolution.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_commit_capacity = mod.gen_commit_cap_linked_commit_capacity[g, 0]
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_commit_capacity = mod.Commit_Capacity_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        return (
            mod.Ramp_Up_When_On_MW[g, tmp]
            <= prev_tmp_commit_capacity
            * mod.gen_commit_cap_ramp_up_when_on_rate[g]
            * 60
            * prev_tmp_hrs_in_tmp
        )


def ramp_up_on_to_on_headroom_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: Ramp_Up_When_On_Headroom_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    Generators online in the previous timepoint that are still online
    could not have ramped up above their total online capacity, i.e. not
    more than their available headroom in the previous timepoint.
    The maximum possible headroom in the previous timepoint is equal to
    the difference between committed capacity and (power provided minus
    downward reserves).
    """
    # TODO: check behavior more carefully (same for ramp down)
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_commit_capacity = mod.gen_commit_cap_linked_commit_capacity[g, 0]
            prev_tmp_power = mod.gen_commit_cap_linked_power[g, 0]
            prev_tmp_downwards_reserves = mod.gen_commit_cap_linked_downwards_reserves[
                g, 0
            ]
        else:
            prev_tmp_commit_capacity = mod.Commit_Capacity_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_power = mod.GenCommitCap_Provide_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_downwards_reserves = mod.GenCommitCap_Downwards_Reserves_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        return mod.Ramp_Up_When_On_MW[g, tmp] <= prev_tmp_commit_capacity - (
            prev_tmp_power - prev_tmp_downwards_reserves
        )


def ramp_up_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: GenCommitCap_Ramp_Up_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    The ramp up (power provided in the current timepoint minus power
    provided in the previous timepoint), adjusted for any reserve provision
    in the current and previous timepoint, cannot exceed a prespecified
    ramp rate (expressed as fraction of capacity)
    Two components:
    1) Ramp_Up_Startup_MW (see Ramp_Up_Off_to_On_Constraint above):
    If we are turning generators on since the previous timepoint, we will
    allow the ramp of going from 0 to minimum stable level + some
    additional ramping : the gen_commit_cap_startup_plus_ramp_up_rate
    parameter
    2) Ramp_Up_When_On_MW (see Ramp_Up_When_On_Constraint and
    Ramp_Up_When_On_Headroom_Constraint above):
    Units committed in both the current timepoint and the previous
    timepoint could have ramped up at a certain rate since the previous
    timepoint
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_power = mod.gen_commit_cap_linked_power[g, 0]
            prev_tmp_downwards_reserves = mod.gen_commit_cap_linked_downwards_reserves[
                g, 0
            ]
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_power = mod.GenCommitCap_Provide_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_downwards_reserves = mod.GenCommitCap_Downwards_Reserves_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        # If ramp rate limits, adjusted for timepoint duration, allow you to
        # start up the full capacity and ramp up the full operable range
        # between timepoints, constraint won't bind, so skip
        if mod.gen_commit_cap_startup_plus_ramp_up_rate[
            g
        ] * 60 * prev_tmp_hrs_in_tmp >= 1 and mod.gen_commit_cap_ramp_up_when_on_rate[
            g
        ] * 60 * prev_tmp_hrs_in_tmp >= (
            1 - mod.gen_commit_cap_min_stable_level_fraction[g]
        ):
            return Constraint.Skip
        else:
            return (
                mod.GenCommitCap_Provide_Power_MW[g, tmp]
                + mod.GenCommitCap_Upwards_Reserves_MW[g, tmp]
            ) - (
                prev_tmp_power - prev_tmp_downwards_reserves
            ) <= mod.Ramp_Up_Startup_MW[
                g, tmp
            ] + mod.Ramp_Up_When_On_MW[
                g, tmp
            ]


def ramp_down_on_to_off_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: Ramp_Down_On_to_Off_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    When turning off, generators can ramp down from a certain
    fraction of the capacity to be shut down to 0. This fraction must be
    greater than or equal to the minimum stable level for the generator
    to be able to turn off.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_commit_capacity = mod.gen_commit_cap_linked_commit_capacity[g, 0]
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_commit_capacity = mod.Commit_Capacity_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        return (
            mod.Ramp_Down_Shutdown_MW[g, tmp]
            >= (mod.Commit_Capacity_MW[g, tmp] - prev_tmp_commit_capacity)
            * mod.gen_commit_cap_shutdown_plus_ramp_down_rate[g]
            * 60
            * prev_tmp_hrs_in_tmp
        )


def ramp_down_on_to_on_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: Ramp_Down_When_On_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    Generators still online in the current timepoint could have ramped
    down at a rate at or below the online capacity times a pre-specified
    ramp rate fraction. Shutdowns are treated separately.
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        return (
            mod.Ramp_Down_When_On_MW[g, tmp]
            >= mod.Commit_Capacity_MW[g, tmp]
            * (-mod.gen_commit_cap_ramp_down_when_on_rate[g])
            * 60
            * prev_tmp_hrs_in_tmp
        )


def ramp_down_on_to_on_headroom_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: Ramp_Down_When_On_Headroom_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    Generators still online in the current timepoint could not have ramped
    down more than their current headroom. The maximum possible headroom is
    equal to the difference between committed capacity and (power provided
    minus downward reserves).
    Note: Ramp_Down_When_On_MW is negative when a unit is ramping down, so
    we add a negative sign before it the constraint.
    """
    # TODO: bug -- this shouldn't be skipping the first tmp of linear
    #  horizons as it's not looking to a previous timepoint
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        return -mod.Ramp_Down_When_On_MW[g, tmp] <= mod.Commit_Capacity_MW[g, tmp] - (
            mod.GenCommitCap_Provide_Power_MW[g, tmp]
            - mod.GenCommitCap_Downwards_Reserves_MW[g, tmp]
        )


def ramp_down_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: GenCommitCap_Ramp_Down_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    The ramp down (power provided in the current timepoint minus power
    provided in the previous timepoint), adjusted for any reserve provision
    in the current and previous timepoint, cannot exceed a prespecified
    ramp rate (expressed as fraction of capacity)
    Two components:
    1) Ramp_Down_Shutdown_MW (see Ramp_Down_On_to_Off_Constraint above):
    If we are turning generators off, we will allow the ramp of
    going from minimum stable level to 0 + some additional ramping from
    above minimum stable level
    2) Ramp_Down_When_On_MW (see Ramp_Down_When_On_Constraint and
    Ramp_Down_When_On_Headroom_Constraint above):
    Units still committed in the current timepoint could have ramped down
    at a certain rate since the previous timepoint
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_power = mod.gen_commit_cap_linked_power[g, 0]
            prev_tmp_upwards_reserves = mod.gen_commit_cap_linked_upwards_reserves[g, 0]
        else:
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_power = mod.GenCommitCap_Provide_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            prev_tmp_upwards_reserves = mod.GenCommitCap_Upwards_Reserves_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]

        # If ramp rate limits, adjusted for timepoint duration, allow you to
        # shut down the full capacity and ramp down the full operable range
        # between timepoints, constraint won't bind, so skip
        if mod.gen_commit_cap_shutdown_plus_ramp_down_rate[
            g
        ] * 60 * prev_tmp_hrs_in_tmp >= 1 and mod.gen_commit_cap_ramp_down_when_on_rate[
            g
        ] * 60 * prev_tmp_hrs_in_tmp >= (
            1 - mod.gen_commit_cap_min_stable_level_fraction[g]
        ):
            return Constraint.Skip
        else:
            return (
                mod.GenCommitCap_Provide_Power_MW[g, tmp]
                - mod.GenCommitCap_Downwards_Reserves_MW[g, tmp]
            ) - (
                prev_tmp_power + prev_tmp_upwards_reserves
            ) >= mod.Ramp_Down_Shutdown_MW[
                g, tmp
            ] + mod.Ramp_Down_When_On_MW[
                g, tmp
            ]


def startup_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: GenCommitCap_Startup_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    When units are shut off, GenCommitCap_Startup_MW will be 0 (as it
    has to be non-negative)
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_commit_capacity = mod.gen_commit_cap_linked_commit_capacity[g, 0]
        else:
            prev_tmp_commit_capacity = mod.Commit_Capacity_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        return (
            mod.GenCommitCap_Startup_MW[g, tmp]
            >= mod.Commit_Capacity_MW[g, tmp] - prev_tmp_commit_capacity
        )


def shutdown_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: GenCommitCap_Shutdown_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    When units are turned on, GenCommitCap_Shutdown_MW will be 0 (as it
    has to be non-negative)
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_tmp_commit_capacity = mod.gen_commit_cap_linked_commit_capacity[g, 0]
        else:
            prev_tmp_commit_capacity = mod.Commit_Capacity_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        return (
            mod.GenCommitCap_Shutdown_MW[g, tmp]
            >= prev_tmp_commit_capacity - mod.Commit_Capacity_MW[g, tmp]
        )


def min_up_time_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: GenCommitCap_Min_Up_Time_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    When units are started, they have to stay on for a minimum number
    of hours described by the gen_commit_cap_min_up_time_hours parameter.
    The constraint is enforced by ensuring that the online capacity
    (committed capacity) is at least as large as the amount of capacity
    that was started within min down time hours.

    We ensure capacity turned on less than the minimum up time ago is
    still on in the current timepoint *tmp* by checking how much capacity
    was turned on in each 'relevant' timepoint (i.e. a timepoint that
    begins more than or equal to gen_commit_cap_min_up_time_hours ago
    relative to the start of timepoint *tmp*) and then summing those
    capacities.
    """
    relevant_tmps, relevant_linked_timepoints = determine_relevant_timepoints(
        mod, g, tmp, mod.gen_commit_cap_min_up_time_hours[g]
    )

    # If only the current timepoint is determined to be relevant (and there
    # are no linked timepoints), this constraint is redundant (it will
    # simplify to Commit_Capacity_MW[g, prev_tmp[tmp]} >= 0)
    # This also takes care of the first timepoint in a linear horizon
    # setting, which has only *tmp* in the list of relevant timepoints
    if relevant_tmps == [tmp] and not relevant_linked_timepoints:
        return Constraint.Skip
    # Otherwise, we must have at least as much capacity committed as was
    # started up in the relevant timepoints
    else:
        capacity_turned_on_min_up_time_or_less_hours_ago = sum(
            mod.GenCommitCap_Startup_MW[g, tp] for tp in relevant_tmps
        ) + sum(
            mod.gen_commit_cap_linked_startup[g, ltp]
            for ltp in relevant_linked_timepoints
        )

        return (
            mod.Commit_Capacity_MW[g, tmp]
            >= capacity_turned_on_min_up_time_or_less_hours_ago
        )


def min_down_time_constraint_rule(mod, g, tmp):
    """
    **Constraint Name**: GenCommitCap_Min_Down_Time_Constraint
    **Enforced Over**: GEN_COMMIT_CAP_OPR_TMPS

    When units are stopped, they have to stay off for a minimum number
    of hours described by the gen_commit_cap_min_down_time_hours parameter.
    The constraint is enforced by ensuring that the offline capacity
    (available capacity minus committed capacity) is at least as large
    as the amount of capacity that was stopped within min down time hours.

    We ensure capacity turned off less than the minimum down time ago is
    still off in the current timepoint *tmp* by checking how much capacity
    was turned off in each 'relevant' timepoint (i.e. a timepoint that
    begins more than or equal to gen_commit_cap_min_down_time_hours ago
    relative to the start of timepoint *tmp*) and then summing those
    capacities.
    """

    relevant_tmps, relevant_linked_timepoints = determine_relevant_timepoints(
        mod, g, tmp, mod.gen_commit_cap_min_down_time_hours[g]
    )

    capacity_turned_off_min_down_time_or_less_hours_ago = sum(
        mod.GenCommitCap_Shutdown_MW[g, tp] for tp in relevant_tmps
    ) + sum(
        mod.gen_commit_cap_linked_shutdown[g, ltp] for ltp in relevant_linked_timepoints
    )

    # If only the current timepoint is determined to be relevant (and there
    # are no linked timepoints), this constraint is redundant (it will
    # simplify to Commit_Capacity_MW[g, prev_tmp[tmp]} >= 0)
    # This also takes care of the first timepoint in a linear horizon
    # setting, which has only *tmp* in the list of relevant timepoints
    if relevant_tmps == [tmp] and not relevant_linked_timepoints:
        return Constraint.Skip
    # Otherwise, we must have at least as much capacity off as was shut
    # down in the relevant timepoints
    else:
        return (
            mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
            - mod.Commit_Capacity_MW[g, tmp]
            >= capacity_turned_off_min_down_time_or_less_hours_ago
        )


# Operational Type Methods
###############################################################################
def power_provision_rule(mod, g, tmp):
    """
    Power provision for dispatchable-capacity-commit generators is a
    variable constrained to be between the minimum stable level (defined as
    a fraction of committed capacity) and the committed capacity.
    """
    return (
        mod.GenCommitCap_Provide_Power_MW[g, tmp]
        - mod.GenCommitCap_Auxiliary_Consumption_MW[g, tmp]
    )


def commitment_rule(mod, g, tmp):
    """
    Number of units committed is the committed capacity divided by the unit
    size
    """
    return mod.Commit_Capacity_MW[g, tmp]


def online_capacity_rule(mod, g, tmp):
    """
    Capacity online in each timepoint
    """
    return mod.Commit_Capacity_MW[g, tmp]


def fuel_burn_by_ll_rule(mod, g, tmp, s):
    """ """
    return (
        mod.fuel_burn_slope_mmbtu_per_mwh[g, mod.period[tmp], s]
        * mod.GenCommitCap_Provide_Power_MW[g, tmp]
        + mod.fuel_burn_intercept_mmbtu_per_mw_hr[g, mod.period[tmp], s]
        * mod.Commit_Capacity_MW[g, tmp]
    )


def variable_om_cost_rule(mod, g, tmp):
    """
    Variable O&M cost has two components which are additive:
    1. A fixed variable O&M rate (cost/MWh) that doesn't change with loading
       levels: :code:`gen_commit_cap_variable_om_cost_per_mwh`.
    2. A variable variable O&M rate that changes with the loading level,
       similar to the heat rates. The idea is to represent higher variable cost
       rates at lower loading levels. This is captured in the
       :code:`GenCommitCap_Variable_OM_Cost_By_LL` decision variable. If no
       variable O&M curve inputs are provided, this component will be zero.

    Most users will only use the first component, which is specified in the
    operational characteristics table.  Only operational types with
    commitment decisions can have the second component.

    We need to explicitly have the op type method here because of auxiliary
    consumption. The default method takes Project_Power_Provision_MW multiplied by
    the variable cost, and Project_Power_Provision_MW is equal to Provide_Power_MW
    minus the auxiliary consumption. The variable cost should be applied to
    the gross power.
    """
    return mod.GenCommitCap_Provide_Power_MW[g, tmp] * mod.variable_om_cost_per_mwh[g]


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.GenCommitCap_Provide_Power_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.GenCommitCap_Provide_Power_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
    )


def variable_om_cost_by_ll_rule(mod, g, tmp, s):
    """
    Variable O&M cost has two components which are additive:
    1. A fixed variable O&M rate (cost/MWh) that doesn't change with loading
       levels: :code:`gen_commit_cap_variable_om_cost_per_mwh`.
    2. A variable variable O&M rate that changes with the loading level,
       similar to the heat rates. The idea is to represent higher variable cost
       rates at lower loading levels. This is captured in the
       :code:`GenCommitCap_Variable_OM_Cost_By_LL` decision variable. If no
       variable O&M curve inputs are provided, this component will be zero.

    Most users will only use the first component, which is specified in the
    operational characteristics table.  Only operational types with
    commitment decisions can have the second component.
    """
    return (
        mod.vom_slope_cost_per_mwh[g, mod.period[tmp], s]
        * mod.GenCommitCap_Provide_Power_MW[g, tmp]
        + mod.vom_intercept_cost_per_mw_hr[g, mod.period[tmp], s]
        * mod.Commit_Capacity_MW[g, tmp]
    )


def startup_cost_simple_rule(mod, g, tmp):
    """
    Startup costs are applied in each timepoint based on the amount of capacity
    (in MW) that is started up in that timepoint and the startup cost
    parameter.
    """
    return mod.GenCommitCap_Startup_MW[g, tmp] * mod.startup_cost_per_mw[g]


def shutdown_cost_rule(mod, g, tmp):
    """
    Shutdown costs are applied in each timepoint based on the amount of
    capacity (in Mw) that is shut down in that timepoint and the shutdown
    cost parameter.
    """
    return mod.GenCommitCap_Shutdown_MW[g, tmp] * mod.shutdown_cost_per_mw[g]


def startup_fuel_burn_rule(mod, g, tmp):
    """
    Startup fuel burn is applied in each timepoint based on the amount of
    capacity (in MW) that is started up in that timepoint and the startup
    fuel parameter.
    """
    return mod.GenCommitCap_Startup_MW[g, tmp] * mod.startup_fuel_mmbtu_per_mw[g]


def power_delta_rule(mod, g, tmp):
    """
    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint.
    """
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linear",
    ) or check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=mod.balancing_type_project[g],
        boundary_type="linked",
    ):
        pass
    else:
        return (
            mod.GenCommitCap_Provide_Power_MW[g, tmp]
            - mod.GenCommitCap_Provide_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        )


def capacity_providing_inertia_rule(mod, g, tmp):
    """
    Capacity providing inertia for GEN_VAR project is equal to the online
    capacity
    """
    return mod.Commit_Capacity_MW[g, tmp]


def fix_commitment(mod, g, tmp):
    """
    Fix committed capacity based on number of committed units and unit size
    """
    mod.Commit_Capacity_MW[g, tmp] = mod.fixed_commitment[
        g, mod.prev_stage_tmp_map[tmp]
    ]
    mod.Commit_Capacity_MW[g, tmp].fixed = True


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
        op_type="gen_commit_cap",
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
        "gen_commit_cap_linked_timepoint_params.tab",
    )
    if os.path.exists(linked_inputs_filename):
        data_portal.load(
            filename=linked_inputs_filename,
            index=mod.GEN_COMMIT_CAP_LINKED_TMPS,
            param=(
                mod.gen_commit_cap_linked_commit_capacity,
                mod.gen_commit_cap_linked_power,
                mod.gen_commit_cap_linked_upwards_reserves,
                mod.gen_commit_cap_linked_downwards_reserves,
                mod.gen_commit_cap_linked_startup,
                mod.gen_commit_cap_linked_shutdown,
            ),
        )


def add_to_prj_tmp_results(mod):
    results_columns = [
        "gross_power_mw",
        "auxiliary_consumption_mw",
        "net_power_mw",
        "committed_mw",
        "committed_units",
    ]
    data = [
        [
            prj,
            tmp,
            value(mod.GenCommitCap_Provide_Power_MW[prj, tmp]),
            value(mod.GenCommitCap_Auxiliary_Consumption_MW[prj, tmp]),
            value(mod.GenCommitCap_Provide_Power_MW[prj, tmp])
            - value(mod.GenCommitCap_Auxiliary_Consumption_MW[prj, tmp]),
            value(mod.Commit_Capacity_MW[prj, tmp]),
            value(mod.Commit_Capacity_MW[prj, tmp])
            / mod.gen_commit_cap_unit_size_mw[prj],
        ]
        for (prj, tmp) in mod.GEN_COMMIT_CAP_OPR_TMPS
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
                "gen_commit_cap_linked_timepoint_params.tab",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(
                [
                    "project",
                    "linked_timepoint",
                    "linked_commitment",
                    "linked_provide_power",
                    "linked_upward_reserves",
                    "linked_downward_reserves",
                    "linked_startup",
                    "linked_shutdown",
                ]
            )
            for p, tmp in sorted(mod.GEN_COMMIT_CAP_OPR_TMPS):
                if tmp in tmps_to_link:
                    writer.writerow(
                        [
                            p,
                            tmp_linked_tmp_dict[tmp],
                            max(value(mod.Commit_Capacity_MW[p, tmp]), 0),
                            max(value(mod.GenCommitCap_Provide_Power_MW[p, tmp]), 0),
                            max(value(mod.GenCommitCap_Upwards_Reserves_MW[p, tmp]), 0),
                            max(
                                value(mod.GenCommitCap_Downwards_Reserves_MW[p, tmp]), 0
                            ),
                            max(value(mod.GenCommitCap_Startup_MW[p, tmp]), 0),
                            max(value(mod.GenCommitCap_Shutdown_MW[p, tmp]), 0),
                        ]
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
        "gen_commit_cap",
    )
