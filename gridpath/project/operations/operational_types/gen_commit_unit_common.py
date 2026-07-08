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
This operational types describes generation projects that can be turned on and
off, i.e. that have binary commitment variables associated with them. This is
particularly useful for production cost modeling approaches where capturing
the unit commitment decisions is important, e.g. when modeling a slow-starting
coal plant. This operational type is not compatible with new-build capacity
types (e.g. gen_new_lin) where the available capacity is an endogenous decision
variable.

The optimization makes commitment and power output decisions in every
timepoint. If the project is not committed (or starting up / shutting down),
power output is zero. If it is committed, power output can vary between a
pre-specified minimum stable level (greater than zero) and the project's
available capacity. Heat rate degradation below full load is considered.
These projects can be allowed to provide upward and/or downward reserves.

Startup and/or shutdown trajectories can be optionally modeled by specifying a
low startup and/or shutdown ramp rate.  Ramp rate limits as well us minimum up
and down time constraints are implemented. Starts and stops -- and the
associated cost and emissions -- can be tracked and constrained.

Costs for this operational type include fuel costs, variable O&M costs, and
startup and shutdown costs.

Interesting background papers:
- "Hidden power system inflexibilities imposed by traditional unit commitment
formulations", Morales-Espana et al. (2017).
- "Tight and compact MILP formulation for the thermal unit commitment problem",
Morales-Espana et al. (2013).

"""

import csv
import os.path
from pyomo.environ import (
    Var,
    Set,
    Param,
    Constraint,
    NonNegativeReals,
    Binary,
    PercentFraction,
    Boolean,
    Expression,
    value,
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
from gridpath.common_functions import duals_wrapper
from gridpath.project.operations.operational_types.common_functions import (
    determine_relevant_timepoints,
    load_optype_model_data,
    load_startup_chars,
    check_for_tmps_to_link,
)
from gridpath.project.common_functions import (
    check_if_boundary_type_and_first_timepoint,
    check_if_first_timepoint,
    check_boundary_type,
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
    bin_or_lin_optype,
):
    """
    The tables below list the Pyomo model components defined in the
    'gen_commit_bin' module followed below by the respective components
    defined in the 'gen_commit_lin" module.

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`GEN_COMMIT_BIN`                                                |
    |                                                                         |
    | | :code:`GEN_COMMIT_LIN`                                                |
    |                                                                         |
    | The set of generators of the :code:`gen_commit_bin` (`gen_commit_lin`)  |
    | operational type.                                                       |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_COMMIT_BIN_STARTUP_BY_ST_PRJS`                             |
    | | *within*: :code:`GEN_COMMIT_BIN`                                      |
    |                                                                         |
    | | :code:`GEN_COMMIT_LIN_STARTUP_BY_ST_PRJS`                             |
    | | *within*: :code:`GEN_COMMIT_LIN`                                      |
    |                                                                         |
    | The set of generators of the :code:`gen_commit_bin` (`gen_commit_lin`)  |
    | operational type that also have startup ramp rates specified.           |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_COMMIT_BIN_STARTUP_BY_ST_PRJS_TYPES`                       |
    |                                                                         |
    | | :code:`GEN_COMMIT_LIN_STARTUP_BY_ST_PRJS_TYPES`                       |
    |                                                                         |
    | Two-dimensional set of generators of the respective operational type    |
    | and their startup types (if the project is in                           |
    | :code:`GEN_COMMIT_BIN_STARTUP_BY_ST_PRJS`). Startup types are ordered   |
    | from hottest to coldest, e.g. if there are 3 startup types the hottest  |
    | start is indicated by 1, and the coldest start is indicated by 3.       |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_COMMIT_BIN_OPR_TMPS`                                       |
    |                                                                         |
    | | :code:`GEN_COMMIT_LIN_OPR_TMPS`                                       |
    |                                                                         |
    | Two-dimensional set with generators of the respective operational type  |
    | and their operational timepoints.                                       |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES`                             |
    |                                                                         |
    | | :code:`GEN_COMMIT_LIN_OPR_TMPS_STR_TYPES`                             |
    |                                                                         |
    | Three-dimensional set with generators of the respective operational     |
    | type, their operational timepoints, and their startup  types (if the    |
    | project is in :code:`GEN_COMMIT_BIN_STARTUP_BY_ST_PRJS` or              |
    | :code:`GEN_COMMIT_LIN_STARTUP_BY_ST_PRJS` respectively).                |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_COMMIT_BIN_STR_TYPES_BY_PRJ`                               |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    |                                                                         |
    | | :code:`GEN_COMMIT_LIN_STR_TYPES_BY_PRJ`                               |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    |                                                                         |
    | Indexed set that describes the startup types for each project of the    |
    | respective operational type.                                            |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_COMMIT_BIN_LINKED_TMPS`                                    |
    |                                                                         |
    | | :code:`GEN_COMMIT_LIN_LINKED_TMPS`                                    |
    |                                                                         |
    | Two-dimensional set with generators of the respective operational type  |
    | and their linked timepoints.                                            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_commit_bin_min_stable_level_fraction`                      |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | | :code:`gen_commit_lin_min_stable_level_fraction`                      |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The minimum stable level of this project as a fraction of its capacity. |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_commit_bin_ramp_up_when_on_rate`                           |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | | :code:`gen_commit_lin_ramp_up_when_on_rate`                           |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's upward ramp rate limit during operations, defined as a    |
    | fraction of its capacity per minute.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_ramp_down_when_on_rate`                         |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | | :code:`gen_commit_lin_ramp_down_when_on_rate`                         |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's downward ramp rate limit during operations, defined as a  |
    | fraction of its capacity per minute.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_startup_plus_ramp_up_rate_by_st`                |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_STARTUP_BY_ST_PRJS_TYPES`       |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | | :code:`gen_commit_lin_startup_plus_ramp_up_rate_by_st`                |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_STARTUP_BY_ST_PRJS_TYPES`       |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's upward ramp rate limit during startup for a given         |
    | startup type, defined as a fraction of its capacity per minute. If,     |
    | after adjusting for timepoint duration, this is smaller than the        |
    | minimum stable level, the project will have a startup trajectory across |
    | multiple timepoints.                                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_shutdown_plus_ramp_down_rate`                   |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | | :code:`gen_commit_lin_shutdown_plus_ramp_down_rate`                   |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's downward ramp rate limit during startup, defined as a     |
    | fraction of its capacity per minute. If, after adjusting for timepoint  |
    | duration, this is smaller than the minimum stable level, the project    |
    | will have a shutdown trajectory across multiple timepoitns.             |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_min_up_time_hours`                              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | | :code:`gen_commit_lin_min_up_time_hours`                              |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The project's minimum up time in hours.                                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_min_down_time_hours`                            |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | | :code:`gen_commit_lin_min_down_time_hours`                            |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The project's minimum down time in hours.                               |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_aux_consumption_frac_capacity`                  |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | | :code:`gen_commit_lin_aux_consumption_frac_capacity`                  |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of committed capacity.              |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_aux_consumption_frac_power`                     |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | | :code:`gen_commit_lin_aux_consumption_frac_power`                     |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of gross power output.              |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_down_time_cutoff_hours`                         |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_STARTUP_BY_ST_PRJS_TYPES`       |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_down_time_cutoff_hours`                         |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_STARTUP_BY_ST_PRJS_TYPES`       |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's minimum down time cutoff to activate a given startup      |
    | type. If the unit has been down for more hours than this cutoff, the    |
    | relevant startup type will be activated. E.g. if a unit has 2 startup   |
    | types (hot and cold) with respective cutoffs of 4 hours and 8 hours, it |
    | means that startup type 1 (the hot start) will be activated if the unit |
    | starts after a down time between 4-8 hours, and startup type 2 (the     |
    | cold start) will be activated if the unit starts after a down time of   |
    | over 8 hours. The cutoff for the hottest start must match the unit's    |
    | minimum down time. If the unit is fast-start without a minimum down     |
    | time, the user should input zero (rather than NULL)                     |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_partial_availability_threshold`                 |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0.01`                                               |
    |                                                                         |
    | | :code:`gen_commit_lin_partial_availability_threshold`                 |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0.01`                                               |
    |                                                                         |
    | The project's availability threshold below which it cannot be           |
    | committed/synced. Defaults to 0.01, i.e., the commit and sync variables |
    | will be set to zero any time availability is 0.01 or less (for          |
    | gen_commit_bin; the gen_commit_lin variables are still continuous), but |
    | can be 1 otherwise. Make sure to set this to a positive fraction to     |
    | ensure you approximate partial availability but avoid the issue where   |
    | the optimization can set the sync variables to 1 even when the project  |
    | is unavailable, thus avoiding startup costs.                            |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_max_n_starts_per_hrz`                           |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_N_STARTUP_BT_HRZS`              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`inf`                                                |
    |                                                                         |
    | | :code:`gen_commit_lin_max_n_starts_per_hrz`                           |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_N_STARTUP_BT_HRZS`              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`inf`                                                |
    |                                                                         |
    | The maximum number of starts allowed in a given horizon.                |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Params                                                          |
    +=========================================================================+
    | | :code:`gen_commit_bin_allow_ramp_up_violation`                        |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | | :code:`gen_commit_lin_allow_ramp_up_violation`                        |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | Determines whether the ramp up constraint can be violated. It is 1 if a |
    | ramp_up_violation_penalty is specified for the project.                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_allow_ramp_down_violation`                      |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | | :code:`gen_commit_lin_allow_ramp_down_violation`                      |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | Determines whether the ramp down constraint can be violated. It is 1 if |
    | a ramp_down_violation_penalty is specified for the project.             |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_allow_min_up_time_violation`                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | | :code:`gen_commit_lin_allow_min_up_time_violation`                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | Determines whether the min up time constraint can be violated. It is 1  |
    | if a min_up_time_violation_penalty is specified for the project.        |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_allow_min_down_time_violation`                  |
    | | *Defined over*: :code:`GEN_COMMIT_BIN`                                |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | | :code:`gen_commit_lin_allow_min_down_time_violation`                  |
    | | *Defined over*: :code:`GEN_COMMIT_LIN`                                |
    | | *Within*: :code:`Boolean`                                             |
    |                                                                         |
    | Determines whether the min down time constraint can be violated. It is  |
    | 1 if a min_down_time_violation_penalty is specified for the project.    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Linked Input Params                                                     |
    +=========================================================================+
    | | :code:`gen_commit_bin_linked_commit`                                  |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_commit`                                  |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The project's commitment status in the linked timepoints.               |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_startup`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_startup`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The project's startup status in the linked timepoints.                  |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_shutdown`                                |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_shutdown`                                |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`PercentFraction`                                     |
    |                                                                         |
    | The project's shutdown status in the linked timepoints.                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_power_above_pmin`                        |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_power_above_pmin`                        |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's power provision above Pmin in the linked timepoints.      |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_upwards_reserves`                        |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's upward reserve provision in the linked timepoints.        |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_downwards_reserves`                      |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_upwards_reserves`                        |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's downward reserve provision in the linked timepoints.      |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_ramp_up_rate_mw_per_tmp`                 |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_downwards_reserves`                      |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's upward ramp rate in MW in the linked timepoints           |
    | (depends on timepoint duration.)                                        |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_ramp_down_rate_mw_per_tmp`               |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_ramp_up_rate_mw_per_tmp`                 |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's downward ramp rate in MW in the linked timepoints         |
    | (depends on timepoint duration.)                                        |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_provide_power_startup_by_st_mw`          |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS_STR_TYPES`          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_provide_power_startup_by_st_mw`          |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS_STR_TYPES`          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's startup power provision by startup type for each linked   |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_startup_ramp_rate_by_st_mw_per_tmp`      |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS_STR_TYPES`          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_startup_ramp_rate_by_st_mw_per_tmp`      |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS_STR_TYPES`          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's startup ramp rate in MW by startup type in the linked     |
    | timepoints (depends on timepoint duration.)                             |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_provide_power_shutdown_mw`               |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_provide_power_shutdown_mw`               |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's shutdown power provision for each linked timepoint.       |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_shutdown_ramp_rate_mw_per_tmp`           |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_shutdown_ramp_rate_mw_per_tmp`           |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's shutdown ramp rate in MW in the linked timepoints         |
    | (depends on timepoint duration.)                                        |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_pmin_mw`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_pmin_mw`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's minimum power output (in MW), if the unit was committed,  |
    | in the linked timepoints.                                               |
    +-------------------------------------------------------------------------+
    | | :code:`gen_commit_bin_linked_pmax_mw`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | | :code:`gen_commit_lin_linked_pmax_mw`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_LINKED_TMPS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's maximum power output (in MW), if the unit was committed,  |
    | in the linked timepoints.                                               |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenCommitBin_Commit`                                           |
    | | *Within*: :code:`Binary`                                              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Commit`                                           |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | In gen_commit_bin, a binary variable which represents the commitment    |
    | decision in each operational timepoint. It is one if the unit is        |
    | committed and zero otherwise (including during a startup and shutdown   |
    | trajectory).                                                            |
    |                                                                         |
    | In gen_commit_lin, this variable can take on non-binary values between  |
    | zero and 1 (i.e. partial commitment of the unit is allowed).            |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Startup`                                          |
    | | *Within*: :code:`Binary`                                              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Startup`                                          |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Binary variable which is one if the unit starts up and zero otherwise.  |
    | A startup is defined as changing commitment from zero to one.           |
    | Note: this variable is zero throughout a startup trajectory!            |
    | In gen_commit_lin, this variable can take on non-binary values between  |
    | zero and 1.                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Startup_Type`                                     |
    | | *Within*: :code:`Binary`                                              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | | :code:`GenCommitLin_Startup_Type`                                     |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | Binary variable which is one if the unit starts up for the given        |
    | startup type and zero otherwise. A startup is defined as changing       |
    | commitment from zero to one, whereas the startup type indicates the     |
    | hotness/coldness of the start. Note: this variable is zero throughout   |
    | a startup trajectory!                                                   |
    | In gen_commit_lin, this variable can take on non-binary values between  |
    | zero and 1.                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Shutdown`                                         |
    | | *Within*: :code:`Binary`                                              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Shutdown`                                         |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Binary variable which is one if the unit shuts down and zero otherwise. |
    | A shutdown is defined as changing commitment from one to zero.          |
    | Note: this variable is zero throughout a shutdown trajectory!           |
    | In gen_commit_lin, this variable can take on non-binary values between  |
    | zero and 1.                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Synced`                                           |
    | | *Within*: :code:`Binary`                                              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Synced`                                           |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Binary variable which is one if the project is providing *any* power (  |
    | either because it is committed or because it is in a startup or shutdown|
    | trajectory), and zero otherwise.                                        |
    | In gen_commit_lin, this variable can take on non-binary values between  |
    | zero and 1.                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Provide_Power_Above_Pmin_MW`                      |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Provide_Power_Above_Pmin_MW`                      |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Power provision above the minimum stable level in MW from this project  |
    | in each timepoint in which the project is committed.                    |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Provide_Power_Startup_By_ST_MW`                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | | :code:`GenCommitLin_Provide_Power_Startup_By_ST_MW`                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | Power provision during startup in each timepoint in which the project   |
    | is starting up, for each startup type (zero if project is committed or  |
    | not starting up).                                                       |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Provide_Power_Shutdown_MW`                        |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Provide_Power_Shutdown_MW`                        |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Power provision during shutdown in each timepoint in which the project  |
    | is shutting down (zero if project is committed or not shutting down).   |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Ramp_Up_Violation_MW`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Ramp_Up_Violation_MW`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Violation of the project's ramp up constraint in each operational       |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Ramp_Down_Violation_MW`                           |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Ramp_Down_Violation_MW`                           |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Violation of the project's ramp down constraint in each operational     |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Min_Up_Time_Violation`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Min_Up_Time_Violation`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Violation of the project's min up time constraint in each operational   |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Min_Down_Time_Violation`                          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Min_Down_Time_Violation`                          |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Violation of the project's min down time constraint in each operational |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`GenCommitBin_Pmax_MW`                                          |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Pmax_MW`                                          |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's maximum power output (in MW) if the unit was committed.   |
    | Depends on the project's availability and capacity in the timepoint.    |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Pmin_MW`                                          |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Pmin_MW`                                          |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's minimum power output (in MW) if the unit was committed.   |
    | Depends on the project's availability and capacity in the timepoint,    |
    | and the minimum stable level.                                           |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Provide_Power_Startup_MW`                         |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Provide_Power_Startup_MW`                         |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Power provision during startup in each timepoint in which the project   |
    | is starting up (zero if project is committed or not starting up).       |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Provide_Power_MW`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Provide_Power_MW`                                 |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's total power output (in MW) in each operational timepoint, |
    | including power from a startup or shutdown trajectory. If modeling      |
    | auxiliary consumption, this is the gross power output.                  |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Ramp_Up_Rate_MW_Per_Tmp`                          |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's upward ramp-able capacity (in MW) in each operational     |
    | timepoint. Depends on the :code:`gen_commit_bin_ramp_up_when_on_rate`,  |
    | the availability and capacity in the timepoint, and the timepoint's     |
    | duration.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Ramp_Down_Rate_MW_Per_Tmp`                        |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Ramp_Up_Rate_MW_Per_Tmp`                          |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's downward ramp-able capacity (in MW) in each operationa    |
    | timepoint. Depends on the :code:`gen_commit_bin_ramp_down_when_on_rate` |
    | , the availability and capacity in the timepoint, and the timepoint's   |
    | duration.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Startup_Ramp_Rate_By_ST_MW_Per_Tmp`               |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | | :code:`GenCommitLin_Startup_Ramp_Rate_By_ST_MW_Per_Tmp`               |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | The project's upward ramp-able capacity (in MW) during startup in each  |
    | operational timepoint. Depends on the                                   |
    | :code:`gen_commit_bin_startup_plus_ramp_up_rate_by_st`, the             |
    | availability and capacity in the timepoint, and the timepoint's         |
    | duration.                                                               |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Shutdown_Ramp_Rate_MW_Per_Tmp`                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Shutdown_Ramp_Rate_MW_Per_Tmp`                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's downward ramp-able capacity (in MW) during shutdown in    |
    | each operational timepoint. Depends on the                              |
    | :code:`gen_commit_bin_shutdown_plus_ramp_down_rate`, the availability   |
    | and capacity in the timepoint, and the timepoint's duration.            |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Active_Startup_Type`                              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Active_Startup_Type`                              |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's active startup type in each operational timepoint,        |
    | described as an integer. If no startup type is active (the project is   |
    | not starting up in this timepoint), this expression returns zero.       |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Upwards_Reserves_MW`                              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Upwards_Reserves_MW`                              |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's total upward reserves offered (in MW) in each timepoint.  |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Downwards_Reserves_MW`                            |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Downwards_Reserves_MW`                            |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's total downward reserves offered (in MW) in each timepoint.|
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Auxiliary_Consumption_MW`                         |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | The project's auxiliary consumption (power consumed on-site and not     |
    | sent to the grid) in each timepoint.                                    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Commitment                                                              |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Binary_Logic_Constraint`                          |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Binary_Logic_Constraint`                          |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Defines the relationship between the binary commitment, startup, and    |
    | shutdown variables. When the commitment changes from zero to one, the   |
    | startup variable is one, when it changes from one to zero, the shutdown |
    | variable is one.                                                        |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Synced_Constraint`                                |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Synced_Constraint`                                |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Sets the GenCommitBin_Synced variable to one if the project is          |
    | providing  *any* power (either because it is committed or because it is |
    | in a startup or shutdown trajectory), and zero otherwise.               |
    +-------------------------------------------------------------------------+
    | Power                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Max_Power_Constraint`                             |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Max_Power_Constraint`                             |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Limits the power plus upward reserves to the available capacity.        |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Min_Power_Constraint`                             |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | Power provision minus downward reserves should exceed the minimum       |
    | stable level for the project.                                           |
    +-------------------------------------------------------------------------+
    | Minimum Up and Down Time                                                |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Min_Up_Time_Constraint`                           |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Min_Up_Time_Constraint`                           |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Requires that when the project is started, it stays on for at least     |
    | :code:`gen_commit_bin_min_up_time_hours`.                               |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Min_Down_Time_Constraint`                         |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Min_Down_Time_Constraint`                         |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Requires that when the project is shut down, it stays off for at least  |
    | :code:`gen_commit_bin_min_up_time_hours`.                               |
    +-------------------------------------------------------------------------+
    | Ramps                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Ramp_Up_Constraint`                               |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Ramp_Up_Constraint`                               |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project upward ramp during operations based on the   |
    | :code:`gen_commit_bin_ramp_up_when_on_rate`.                            |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Ramp_Down_Constraint`                             |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Ramp_Down_Constraint`                             |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project downward ramp during operations based on the |
    | :code:`gen_commit_bin_ramp_down_when_on_rate`.                          |
    +-------------------------------------------------------------------------+
    | Startup Power                                                           |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Unique_Startup_Type_Constraint`                   |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Unique_Startup_Type_Constraint`                   |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Ensures that only one startup type can be active at the same time.      |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Active_Startup_Type_Constraint`                   |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | | :code:`GenCommitLin_Active_Startup_Type_Constraint`                   |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | Ensures that a startup type can only be active if the unit has been     |
    | down for the appropriate interval.                                      |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Max_Startup_Power_Constraint`                     |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Max_Startup_Power_Constraint`                     |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Limits startup power to zero when the project is committed and to the   |
    | minimum stable level when it is not committed.                          |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Ramp_During_Startup_By_ST_Constraint`             |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | | :code:`GenCommitLin_Ramp_During_Startup_By_ST_Constraint`             |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | Limits the allowed project upward startup power ramp based on the       |
    | :code:`gen_commit_bin_startup_plus_ramp_up_rate_by_st`.                 |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Increasing_Startup_Power_By_ST_Constraint`        |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | | :code:`GenCommitLin_Increasing_Startup_Power_By_ST_Constraint`        |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | Requires that the startup power always increases, except for the        |
    | startup timepoint (when :code:`GenCommitBin_Startup` is one).           |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Power_During_Startup_By_ST_Constraint`            |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | | :code:`GenCommitLin_Power_During_Startup_By_ST_Constraint`            |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS_STR_TYPES`             |
    |                                                                         |
    | Limits the difference between the power provision in the startup        |
    | timepoint and the startup power in the previous timepoint based on the  |
    | :code:`gen_commit_bin_startup_plus_ramp_up_rate_by_st`.                 |
    +-------------------------------------------------------------------------+
    | Shutdown Power                                                          |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Max_Shutdown_Power_Constraint`                    |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Max_Shutdown_Power_Constraint`                    |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Limits shutdown power to zero when the project is committed and to the  |
    | minimum stable level when it is not committed.                          |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Ramp_During_Shutdown_Constraint`                  |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Ramp_During_Shutdown_Constraint`                  |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Limits the allowed project downward shutdown power ramp based on the    |
    | :code:`gen_commit_bin_shutdown_plus_ramp_down_rate`.                    |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Decreasing_Shutdown_Power_Constraint`             |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Decreasing_Shutdown_Power_Constraint`             |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Requires that the shutdown power always decreases, except for the       |
    | shutdown timepoint (when :code:`GenCommitBin_Shutdown` is one).         |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_Power_During_Shutdown_Constraint`                 |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_Power_During_Shutdown_Constraint`                 |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | Limits the difference between the power provision in the shutdown       |
    | timepoint and the shutdown power in the next timepoint based on the     |
    | :code:`gen_commit_bin_shutdown_plus_ramp_down_rate`.                    |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_No_Sync_When_Unavailable_Constraint`              |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | | :code:`GenCommitLin_No_Sync_When_Unavailable_Constraint`              |
    | | *Defined over*: :code:`GEN_COMMIT_LIN_OPR_TMPS`                       |
    |                                                                         |
    | A project cannot be synced (committed or providing startup/shutdown     |
    | power) when unavailable (<1% available).                                |
    +-------------------------------------------------------------------------+
    | | :code:`GenCommitBin_No_Commit_When_Unavailable_Constraint`            |
    | | *Defined over*: :code:`GEN_COMMIT_BIN_OPR_TMPS`                       |
    |                                                                         |
    | Forces the binary commitment to 0 when the project is unavailable       |
    | (<1% available).                                                        |
    +-------------------------------------------------------------------------+

    """
    if bin_or_lin_optype == "gen_commit_bin":
        BIN_OR_LIN = "BIN"
        bin_or_lin = "bin"
        Bin_or_Lin = "Bin"
        Pyomo_Binary_or_PercentFraction = Binary
    elif bin_or_lin_optype == "gen_commit_lin":
        BIN_OR_LIN = "LIN"
        bin_or_lin = "lin"
        Bin_or_Lin = "Lin"
        Pyomo_Binary_or_PercentFraction = PercentFraction
    else:
        raise ValueError("""GridPath ERROR:
        Allowed types are 'gen_commit_unit_bin' or 'gen_commit_unit_lin'. 
        You used {}.""".format(bin_or_lin_optype))

    # Sets
    ###########################################################################

    setattr(
        m,
        "GEN_COMMIT_{}".format(BIN_OR_LIN),
        Set(
            within=m.PROJECTS,
            initialize=lambda mod: subset_init_by_param_value(
                mod, "PROJECTS", "operational_type", bin_or_lin_optype
            ),
        ),
    )

    setattr(
        m,
        "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN),
        Set(
            dimen=2,
            initialize=lambda mod: subset_init_by_set_membership(
                mod=mod,
                superset="PRJ_OPR_TMPS",
                index=0,
                membership_set=getattr(mod, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            ),
        ),
    )

    setattr(
        m,
        "GEN_COMMIT_{}_STARTUP_BY_ST_PRJS".format(BIN_OR_LIN),
        Set(
            within=getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            initialize=lambda mod: subset_init_by_param_value(
                mod=mod,
                set_name="STARTUP_BY_ST_PRJS",
                param_name="operational_type",
                param_value=bin_or_lin_optype,
            ),
        ),
    )

    setattr(
        m,
        "GEN_COMMIT_{}_STARTUP_BY_ST_PRJS_TYPES".format(BIN_OR_LIN),
        Set(
            dimen=2,
            ordered=True,
            initialize=lambda mod: sorted(
                list(
                    (prj, s)
                    for (prj, s) in mod.STARTUP_BY_ST_PRJS_TYPES
                    if mod.operational_type[prj] == bin_or_lin_optype
                )
            ),
        ),
    )

    setattr(
        m,
        "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN),
        Set(
            dimen=3,
            initialize=lambda mod: set(
                (g, tmp, s)
                for (g, tmp) in mod.PRJ_OPR_TMPS
                for _g, s in getattr(
                    mod, "GEN_COMMIT_{}_STARTUP_BY_ST_PRJS_TYPES".format(BIN_OR_LIN)
                )
                if g == _g
            ),
        ),
    )

    def get_startup_types_by_project(mod, g):
        """
        Get indexed set of startup types by project, ordered from hottest to
        coldest.
        """
        types = sorted(
            [
                s
                for (_g, s) in getattr(
                    mod, "GEN_COMMIT_{}_STARTUP_BY_ST_PRJS_TYPES".format(BIN_OR_LIN)
                )
                if g == _g
            ]
        )
        return types

    setattr(
        m,
        "GEN_COMMIT_{}_STR_TYPES_BY_PRJ".format(BIN_OR_LIN),
        Set(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            initialize=get_startup_types_by_project,
            ordered=True,
        ),
    )

    setattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN), Set(dimen=2))

    setattr(
        m,
        "GEN_COMMIT_{}_LINKED_TMPS_STR_TYPES".format(BIN_OR_LIN),
        Set(
            dimen=3,
            initialize=lambda mod: set(
                (g, tmp, s)
                for (g, tmp) in getattr(
                    mod, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)
                )
                for _g, s in getattr(
                    mod, "GEN_COMMIT_{}_STARTUP_BY_ST_PRJS_TYPES".format(BIN_OR_LIN)
                )
                if g == _g
            ),
        ),
    )

    setattr(
        m,
        f"GEN_COMMIT_{BIN_OR_LIN}_N_STARTUP_BT_HRZS",
        Set(
            dimen=3,
            within=getattr(m, f"GEN_COMMIT_{BIN_OR_LIN}") * getattr(m, "BLN_TYPE_HRZS"),
        ),
    )

    # Required Params
    ###########################################################################
    setattr(
        m,
        "gen_commit_{}_min_stable_level_fraction".format(bin_or_lin),
        Param(getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)), within=PercentFraction),
    )

    # Optional Params
    ###########################################################################

    setattr(
        m,
        "gen_commit_{}_ramp_up_when_on_rate".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=PercentFraction,
            default=1,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_ramp_down_when_on_rate".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=PercentFraction,
            default=1,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_startup_plus_ramp_up_rate_by_st".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_STARTUP_BY_ST_PRJS_TYPES".format(BIN_OR_LIN)),
            within=PercentFraction,
            default=1,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_shutdown_plus_ramp_down_rate".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=PercentFraction,
            default=1,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_min_up_time_hours".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=NonNegativeReals,
            default=0,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_min_down_time_hours".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=NonNegativeReals,
            default=0,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_allow_startup_shutdown_power".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=Boolean,
            default=0,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_aux_consumption_frac_capacity".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=PercentFraction,
            default=0,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_aux_consumption_frac_power".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=PercentFraction,
            default=0,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_down_time_cutoff_hours".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_STARTUP_BY_ST_PRJS_TYPES".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_partial_availability_threshold".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=PercentFraction,
            default=0.01,
        ),
    )

    setattr(
        m,
        f"gen_commit_{bin_or_lin}_max_n_starts_per_hrz",
        Param(
            getattr(m, f"GEN_COMMIT_{BIN_OR_LIN}_N_STARTUP_BT_HRZS"),
            within=NonNegativeReals,
            default=float("inf"),
        ),
    )

    # Derived Params
    ###########################################################################

    setattr(
        m,
        "gen_commit_{}_allow_ramp_up_violation".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=Boolean,
            initialize=lambda mod, prj: 1 if prj in mod.RAMP_UP_VIOL_PRJS else 0,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_allow_ramp_down_violation".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=Boolean,
            initialize=lambda mod, prj: 1 if prj in mod.RAMP_DOWN_VIOL_PRJS else 0,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_allow_min_up_time_violation".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=Boolean,
            initialize=lambda mod, prj: 1 if prj in mod.MIN_UP_TIME_VIOL_PRJS else 0,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_allow_min_down_time_violation".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}".format(BIN_OR_LIN)),
            within=Boolean,
            initialize=lambda mod, prj: 1 if prj in mod.MIN_DOWN_TIME_VIOL_PRJS else 0,
        ),
    )

    # Linked Params
    ###########################################################################

    setattr(
        m,
        "gen_commit_{}_linked_commit".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=PercentFraction,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_startup".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=PercentFraction,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_shutdown".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=PercentFraction,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_power_above_pmin".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_upwards_reserves".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_downwards_reserves".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_ramp_up_rate_mw_per_tmp".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_ramp_down_rate_mw_per_tmp".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_provide_power_startup_by_st_mw".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_startup_ramp_rate_by_st_mw_per_tmp".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_provide_power_shutdown_mw".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_shutdown_ramp_rate_mw_per_tmp".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_pmin_mw".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "gen_commit_{}_linked_pmax_mw".format(bin_or_lin),
        Param(
            getattr(m, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    # Variables
    ###########################################################################

    setattr(
        m,
        "GenCommit{}_Commit".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=Pyomo_Binary_or_PercentFraction,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Startup".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=Pyomo_Binary_or_PercentFraction,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Startup_Type".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            within=Pyomo_Binary_or_PercentFraction,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Shutdown".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=Pyomo_Binary_or_PercentFraction,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Synced".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=Pyomo_Binary_or_PercentFraction,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Provide_Power_Startup_By_ST_MW".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Ramp_Up_Violation_MW".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
            initialize=0,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Ramp_Down_Violation_MW".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
            initialize=0,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Min_Up_Time_Violation".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
            initialize=0,
        ),
    )

    setattr(
        m,
        "GenCommit{}_Min_Down_Time_Violation".format(Bin_or_Lin),
        Var(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            within=NonNegativeReals,
            initialize=0,
        ),
    )

    # Expressions
    ###########################################################################

    def pmax_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Pmax_MW
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS
        """
        return mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]

    setattr(
        m,
        "GenCommit{}_Pmax_MW".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)), rule=pmax_rule
        ),
    )

    def pmin_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Pmin_MW
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * getattr(
                mod, "gen_commit_{}_min_stable_level_fraction".format(bin_or_lin)
            )[g]
        )

    setattr(
        m,
        "GenCommit{}_Pmin_MW".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)), rule=pmin_rule
        ),
    )

    def provide_power_startup_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Provide_Power_Startup_MW
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS
        """
        return sum(
            getattr(
                mod, "GenCommit{}_Provide_Power_Startup_By_ST_MW".format(Bin_or_Lin)
            )[g, tmp, s]
            for s in getattr(mod, "GEN_COMMIT_{}_STR_TYPES_BY_PRJ".format(BIN_OR_LIN))[
                g
            ]
        )

    setattr(
        m,
        "GenCommit{}_Provide_Power_Startup_MW".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=provide_power_startup_rule,
        ),
    )

    def provide_power_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Provide_Power_MW
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS
        """
        return (
            getattr(mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            + getattr(mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin))[g, tmp]
            * getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
            + getattr(mod, "GenCommit{}_Provide_Power_Startup_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            + getattr(mod, "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin))[
                g, tmp
            ]
        )

    setattr(
        m,
        "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=provide_power_rule,
        ),
    )

    def ramp_up_rate_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Ramp_Up_Rate_MW_Per_Tmp
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS

        Ramp up rate limit in MW per timepoint, derived from input ramp rate
        which is given in fraction of installed capacity per minute. Longer
        timepoints will lead to a larger ramp up rate limit, since ramping
        can take place over a longer duration.
        Unit check:
            capacity [MW]
            * availability [unit-less]
            * ramp up rate [1/min]
            * hours in timepoint [hours/timepoint]
            * minutes per hour [min/hour]
            = ramp up rate [MW/timepoint]
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * getattr(mod, "gen_commit_{}_ramp_up_when_on_rate".format(bin_or_lin))[g]
            * mod.hrs_in_tmp[tmp]
            * 60
        )  # convert min to hours

    setattr(
        m,
        "GenCommit{}_Ramp_Up_Rate_MW_Per_Tmp".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=ramp_up_rate_rule,
        ),
    )

    def ramp_down_rate_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Ramp_Down_Rate_MW_Per_Tmp
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS

        Ramp down rate limit in MW per timepoint, derived from input ramp rate
        which is given in fraction of installed capacity per minute. Longer
        timepoints will lead to a larger ramp down rate limit, since ramping
        can take place over a longer duration.
        Unit check:
            capacity [MW]
            * availability [unit-less]
            * ramp down rate [1/min]
            * hours in timepoint [hours/timepoint]
            * minutes per hour [min/hour]
            = ramp down rate [MW/timepoint]
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * getattr(mod, "gen_commit_{}_ramp_down_when_on_rate".format(bin_or_lin))[g]
            * mod.hrs_in_tmp[tmp]
            * 60
        )  # convert min to hours

    setattr(
        m,
        "GenCommit{}_Ramp_Down_Rate_MW_Per_Tmp".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=ramp_down_rate_rule,
        ),
    )

    def startup_ramp_rate_rule(mod, g, tmp, s):
        """
        **Expression Name**: GenCommitBin_Startup_Ramp_Rate_By_ST_MW_Per_Tmp
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * min(
                getattr(
                    mod,
                    "gen_commit_{}_startup_plus_ramp_up_rate_by_st".format(bin_or_lin),
                )[g, s]
                * mod.hrs_in_tmp[tmp]
                * 60,
                1,
            )
        )

    setattr(
        m,
        "GenCommit{}_Startup_Ramp_Rate_By_ST_MW_Per_Tmp".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            rule=startup_ramp_rate_rule,
        ),
    )

    def shutdown_ramp_rate_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Shutdown_Ramp_Rate_MW_Per_Tmp
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * min(
                getattr(
                    mod, "gen_commit_{}_shutdown_plus_ramp_down_rate".format(bin_or_lin)
                )[g]
                * mod.hrs_in_tmp[tmp]
                * 60,
                1,
            )
        )

    setattr(
        m,
        "GenCommit{}_Shutdown_Ramp_Rate_MW_Per_Tmp".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=shutdown_ramp_rate_rule,
        ),
    )

    def active_startup_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Active_Startup_Type
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS
        """
        return sum(
            getattr(mod, "GenCommit{}_Startup_Type".format(Bin_or_Lin))[g, tmp, s] * s
            for s in getattr(mod, "GEN_COMMIT_{}_STR_TYPES_BY_PRJ".format(BIN_OR_LIN))[
                g
            ]
        )

    setattr(
        m,
        "GenCommit{}_Active_Startup_Type".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=active_startup_rule,
        ),
    )

    def upwards_reserve_rule(mod, g, tmp):
        return headroom_provision_rule(d, mod, g, tmp)

    setattr(
        m,
        "GenCommit{}_Upwards_Reserves_MW".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=upwards_reserve_rule,
        ),
    )

    def downwards_reserve_rule(mod, g, tmp):
        return footroom_provision_rule(d, mod, g, tmp)

    setattr(
        m,
        "GenCommit{}_Downwards_Reserves_MW".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=downwards_reserve_rule,
        ),
    )

    def auxiliary_consumption_rule(mod, g, tmp):
        """
        **Expression Name**: GenCommitBin_Auxiliary_Consumption_MW
        **Defined Over**: GEN_COMMIT_BIN_OPR_TMPS
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
            * getattr(
                mod, "gen_commit_{}_aux_consumption_frac_capacity".format(bin_or_lin)
            )[g]
            + getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[g, tmp]
            * getattr(
                mod, "gen_commit_{}_aux_consumption_frac_power".format(bin_or_lin)
            )[g]
        )

    setattr(
        m,
        "GenCommit{}_Auxiliary_Consumption_MW".format(Bin_or_Lin),
        Expression(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=auxiliary_consumption_rule,
        ),
    )

    # Constraints
    ###########################################################################

    # Sync (committed, starting, or shutting down)
    # We use the Synced variable to determine when to incur variable costs
    # and burn fuel

    def no_sync_when_unavailable_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_No_Sync_When_Unavailable_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        A unit cannot be synced when (fully-ish) unavailable. When the
        availability derate is < a user-specified number (defaults to 0.01),
        this will force commitment, power, and startup/shutdown
        power to 0 for gen_commit_bin.

        This constraint is needed to prevent the model from committing a
        unit while unavailable, thus avoiding startup costs when the unit
        comes back from unavailability, as startup costs are based on
        available capacity started up.

        If Availability_Derate is 1, GenCommitB/Lin_Synced can be set to 1.
        If Availability_Derate is 0, GenCommitB/Lin_Synced must be set to 0.
        If Availability_Derate >= partial_availability_threshold,
        GenCommitBin_Synced can be set to 1.
        If Availability_Derate < partial_availability_threshold,
        GenCommitBin_Synced must be set to 0.

        Pyomo disallows strict inequalities, so 1% is set as default as it is
        unlikely to have availabilities lower than this and the number is scaled
        appropriately to avoid numerical issues.
        """
        return getattr(mod, "GenCommit{}_Synced".format(Bin_or_Lin))[
            g, tmp
        ] <= mod.Availability_Derate[g, tmp] + (
            1
            - getattr(
                mod, "gen_commit_{}_partial_availability_threshold".format(bin_or_lin)
            )[g]
        )

    setattr(
        m,
        "GenCommit{}_No_Sync_When_Unavailable_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=no_sync_when_unavailable_constraint_rule,
        ),
    )

    def no_commit_when_unavailable_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_No_Commit_When_Unavailable_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS
        Ensure that the commitment flag remains zero while the project is
        unavailable (< 1% available).
        Commit[t] = 0 when Availability_Derate[t] < 0.01

        Redundant with the no_sync_when_unavailable_constraint_rule.

        Pyomo disallows strict inequalities, so 1% is set as default as it is
        unlikely to have availabilities lower than this and the number is scaled
        appropriately to avoid numerical issues.
        """

        return getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[
            g, tmp
        ] <= mod.Availability_Derate[g, tmp] + (
            1
            - getattr(
                mod, "gen_commit_{}_partial_availability_threshold".format(bin_or_lin)
            )[g]
        )

    setattr(
        m,
        "GenCommit{}_Commit_When_Unavailable_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=no_commit_when_unavailable_constraint_rule,
        ),
    )

    def synced_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Synced_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        Synced is 1 if the unit is committed, starting, or stopping and zero
        otherwise.

        Note: This contains a division by the Pmin expression, so cases
        where Pmin would be zero need to be treated differently to avoid
        zero-division errors.
        """
        # If min stable level Pmin expression is exogenously specified as
        # zero, whether due to the min stable level fraction, availability,
        # or capacity being zero, there will be no startup/shutdown power
        # (it is limited by the Pmin expression), so we can drop the second
        # RHS term which checks for startup/shutdown power
        if (
            (
                mod.capacity_type[g] in ["gen_spec", "gen_ret_bin", "gen_ret_lin"]
                and getattr(mod, mod.capacity_type[g] + "_capacity_mw")[
                    g, mod.period[tmp]
                ]
                == 0
            )
            or (
                mod.availability_type[g] == "exogenous"
                and mod.avl_exog_cap_derate_independent[g, tmp]
                * mod.avl_exog_cap_derate_weather[g, tmp]
                == 0
            )
            or getattr(
                mod, "gen_commit_{}_min_stable_level_fraction".format(bin_or_lin)
            )[g]
            == 0
        ):
            startup_shutdown_fraction = 0
        else:
            startup_shutdown_fraction = (
                getattr(mod, "GenCommit{}_Provide_Power_Startup_MW".format(Bin_or_Lin))[
                    g, tmp
                ]
                + getattr(
                    mod, "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin)
                )[g, tmp]
            ) / getattr(mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin))[g, tmp]

        return (
            getattr(mod, "GenCommit{}_Synced".format(Bin_or_Lin))[g, tmp]
            >= getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
            + startup_shutdown_fraction
        )

    setattr(
        m,
        "GenCommit{}_Synced_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=synced_constraint_rule,
        ),
    )

    # Commitment
    def binary_logic_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Binary_Logic_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        If commit status changes, unit is turning on or shutting down.
        The *GenCommitBin_Startup* variable is 1 for the first timepoint the
        unit is committed after being offline; it will be able to provide
        power in that timepoint. The *GenCommitBin_Shutdown* variable is 1
        for the first timepoint the unit is not committed after being
        online; it will not be able to provide power in that timepoint.

        Constraint (8) in Morales-Espana et al. (2013)
        """
        # If this is the first timepoint of a linear horizon, skip the
        # constraint
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linear",
        ):
            return Constraint.Skip
        else:
            # If this is the first timepoint of a linked horizon, set the
            # previous timepoint's commitment to that in the closest linked
            # timepoint (the linked timepoint with index 0)
            if check_if_boundary_type_and_first_timepoint(
                mod=mod,
                tmp=tmp,
                balancing_type=mod.balancing_type_project[g],
                boundary_type="linked",
            ):
                prev_timepoint_commit = getattr(
                    mod, "gen_commit_{}_linked_commit".format(bin_or_lin)
                )[g, 0]
            # Otherwise, use the previous timepoint's commitment
            else:
                prev_timepoint_commit = getattr(
                    mod, "GenCommit{}_Commit".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]

            return (
                getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
                - prev_timepoint_commit
                == getattr(mod, "GenCommit{}_Startup".format(Bin_or_Lin))[g, tmp]
                - getattr(mod, "GenCommit{}_Shutdown".format(Bin_or_Lin))[g, tmp]
            )

    setattr(
        m,
        "GenCommit{}_Binary_Logic_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=binary_logic_constraint_rule,
        ),
    )

    # Power
    def max_power_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Max_Power_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        Power provision plus upward reserves shall not exceed maximum power.
        """
        return (
            getattr(mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            + getattr(mod, "GenCommit{}_Upwards_Reserves_MW".format(Bin_or_Lin))[g, tmp]
        ) <= (
            getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
            - getattr(mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin))[g, tmp]
        ) * getattr(
            mod, "GenCommit{}_Commit".format(Bin_or_Lin)
        )[
            g, tmp
        ]

    setattr(
        m,
        "GenCommit{}_Max_Power_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=max_power_constraint_rule,
        ),
    )

    def min_power_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Min_Power_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        Power minus downward services cannot be below minimum stable level.
        This constraint is not in Morales-Espana et al. (2013) because they
        don't look at downward reserves. In that case, enforcing
        provide_power_above_pmin to be within NonNegativeReals is sufficient.
        """
        return (
            getattr(mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            - getattr(mod, "GenCommit{}_Downwards_Reserves_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            >= 0
        )

    setattr(
        m,
        "GenCommit{}_Min_Power_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=min_power_constraint_rule,
        ),
    )

    # Minimum Up and Down Time
    def min_up_time_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Min_Up_Time_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        When units are started, they have to stay on for a minimum number
        of hours described by the gen_commit_bin_min_up_time_hours parameter.
        The constraint is enforced by ensuring that the binary commitment
        is at least as large as the number of unit starts within min up time
        hours.

        We ensure a unit turned on less than the minimum up time ago is
        still on in the current timepoint *tmp* by checking how much units
        were turned on in each 'relevant' timepoint (i.e. a timepoint that
        begins more than or equal to gen_commit_bin_min_up_time_hours ago
        relative to the start of timepoint *tmp*) and then summing those
        starts.

        If using linear horizon boundaries, the constraint is skipped for all
        timepoints less than min up time hours from the start of the
        timepoint's horizon because the constraint for the first included
        timepoint will sufficiently constrain the binary start variables of
        all the timepoints before it.

        Constraint (6) in Morales-Espana et al. (2013)

        Example 1:
          min_up_time = 4; tmps = [0,1,2,3];
          hours_in_tmps = [1,3,1,1];
          tmp = 2; relevant_tmps = [1,2]
          --> if there is a start in tmp 1, you have to be committed in tmp 2
          --> starts in all other tmps (incl. tmp 0) don't affect tmp 2
        Example 2:
          min_up_time = 4; tmps = [0,1,2,3];
          hours_in_tmps = [1,4,1,1];
          tmp = 2; relevant_tmps = [2]
          --> start in t1 does not affect state of t2; tmp 1 is 4 hrs long
          --> so even if you start in tmp 1 you can stop again in tmp 2
          --> The constraint simply ensures that the unit is committed if
          --> it is turned on.
        Example 3:
          min_up_time = 4; tmps = [0,1,2,3];
          hours_in_tmps = [1,1,1,1];
          tmp = 2; relevant_tmps = [0,1,2,3]
          --> if there is a start in tmp 0, 1, 2, or 3, you have to be
          --> committed
          --> in tmp 2. The unit either has to be on for all timepoints, or
          --> off for all timepoints
        """

        relevant_tmps, relevant_linked_timepoints = determine_relevant_timepoints(
            mod,
            g,
            tmp,
            getattr(mod, "gen_commit_{}_min_up_time_hours".format(bin_or_lin))[g],
        )

        number_of_starts_min_up_time_or_less_hours_ago = sum(
            getattr(mod, "GenCommit{}_Startup".format(Bin_or_Lin))[g, tp]
            for tp in relevant_tmps
        ) + sum(
            getattr(mod, "gen_commit_{}_linked_startup".format(bin_or_lin))[g, ltp]
            for ltp in relevant_linked_timepoints
        )

        # If we've reached the first timepoint in linear boundary mode and
        # the total duration of the relevant timepoints (which includes *tmp*)
        # is less than the minimum up time, skip the constraint since the next
        # timepoint's constraint will already cover these same timepoints.
        # Don't skip if this timepoint is the last timepoint of the horizon
        # (since there will be no next timepoint).
        if (
            mod.boundary[
                mod.balancing_type_project[g],
                mod.horizon[tmp, mod.balancing_type_project[g]],
            ]
            == "linear"
            and relevant_tmps[-1]
            == mod.first_hrz_tmp[
                mod.balancing_type_project[g],
                mod.horizon[tmp, mod.balancing_type_project[g]],
            ]
            and sum(mod.hrs_in_tmp[t] for t in relevant_tmps)
            < getattr(mod, "gen_commit_{}_min_up_time_hours".format(bin_or_lin))[g]
            and tmp
            != mod.last_hrz_tmp[
                mod.balancing_type_project[g],
                mod.horizon[tmp, mod.balancing_type_project[g]],
            ]
        ):
            return Constraint.Skip
        # Otherwise, if there was a start min_up_time or less ago, the unit has
        # to remain committed.
        else:
            return (
                getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
                + getattr(
                    mod, "gen_commit_{}_allow_min_up_time_violation".format(bin_or_lin)
                )[g]
                * getattr(mod, "GenCommit{}_Min_Up_Time_Violation".format(Bin_or_Lin))[
                    g, tmp
                ]
                >= number_of_starts_min_up_time_or_less_hours_ago
            )

    setattr(
        m,
        "GenCommit{}_Min_Up_Time_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=min_up_time_constraint_rule,
        ),
    )

    def min_down_time_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Min_Down_Time_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        When units are shut down, they have to stay off for a minimum number
        of hours described by the gen_commit_bin_min_down_time_hours parameter.
        The constraint is enforced by ensuring that (1-binary commitment)
        is at least as large as the number of unit shutdowns within min down
        time hours.

        We ensure a unit shut down less than the minimum up time ago is
        still off in the current timepoint *tmp* by checking how much units
        were shut down in each 'relevant' timepoint (i.e. a timepoint that
        begins more than or equal to gen_commit_bin_min_down_time_hours ago
        relative to the start of timepoint *tmp*) and then summing those
        shutdowns.

        If using linear horizon boundaries, the constraint is skipped for all
        timepoints less than min down time hours from the start of the
        timepoint's horizon because the constraint for the first included
        timepoint will sufficiently constrain the binary stop variables of all
        the timepoints before it.

        Constraint (7) in Morales-Espana et al. (2013)
        """

        relevant_tmps, relevant_linked_timepoints = determine_relevant_timepoints(
            mod,
            g,
            tmp,
            getattr(mod, "gen_commit_{}_min_down_time_hours".format(bin_or_lin))[g],
        )

        number_of_stops_min_down_time_or_less_hours_ago = sum(
            getattr(mod, "GenCommit{}_Shutdown".format(Bin_or_Lin))[g, tp]
            for tp in relevant_tmps
        ) + sum(
            getattr(mod, "gen_commit_{}_linked_shutdown".format(bin_or_lin))[g, ltp]
            for ltp in relevant_linked_timepoints
        )

        # If we've reached the first timepoint in linear boundary mode and
        # the total duration of the relevant timepoints (which includes *tmp*)
        # is less than the minimum down time, skip the constraint since the
        # next timepoint's constraint will already cover these same timepoints.
        # Don't skip if this timepoint is the last timepoint of the horizon
        # (since there will be no next timepoint).
        if (
            mod.boundary[
                mod.balancing_type_project[g],
                mod.horizon[tmp, mod.balancing_type_project[g]],
            ]
            == "linear"
            and relevant_tmps[-1]
            == mod.first_hrz_tmp[
                mod.balancing_type_project[g],
                mod.horizon[tmp, mod.balancing_type_project[g]],
            ]
            and sum(mod.hrs_in_tmp[t] for t in relevant_tmps)
            < getattr(mod, "gen_commit_{}_min_down_time_hours".format(bin_or_lin))[g]
            and tmp
            != mod.last_hrz_tmp[
                mod.balancing_type_project[g],
                mod.horizon[tmp, mod.balancing_type_project[g]],
            ]
        ):
            return Constraint.Skip
        # Otherwise, if there was a shutdown min_down_time or less ago, the
        # unit has to remain shut down.
        else:
            return (
                1
                - (
                    getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
                    - getattr(
                        mod,
                        "gen_commit_{}_allow_min_down_time_violation".format(
                            bin_or_lin
                        ),
                    )[g]
                    * getattr(
                        mod, "GenCommit{}_Min_Down_Time_Violation".format(Bin_or_Lin)
                    )[g, tmp]
                )
                >= number_of_stops_min_down_time_or_less_hours_ago
            )

    setattr(
        m,
        "GenCommit{}_Min_Down_Time_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=min_down_time_constraint_rule,
        ),
    )

    # Ramps
    def ramp_up_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Ramp_Up_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        Difference between power generation of consecutive timepoints has to
        obey ramp up rates.

        We assume that a unit has to reach its setpoint at the start of the
        timepoint; as such, the ramping between 2 timepoints is assumed to
        take place during the duration of the first timepoint, and the
        ramp rate is adjusted for the duration of the first timepoint.
        Constraint (12) in Morales-Espana et al. (2013)
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
                prev_tmp_power_above_pmin = getattr(
                    mod, "gen_commit_{}_linked_power_above_pmin".format(bin_or_lin)
                )[g, 0]
                prev_tmp_downwards_reserves = getattr(
                    mod, "gen_commit_{}_linked_downwards_reserves".format(bin_or_lin)
                )[g, 0]
                prev_tmp_ramp_up_rate_mw_per_tmp = getattr(
                    mod,
                    "gen_commit_{}_linked_ramp_up_rate_mw_per_tmp".format(bin_or_lin),
                )[g, 0]
            else:
                prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                    mod.prev_tmp[tmp, mod.balancing_type_project[g]]
                ]
                prev_tmp_power_above_pmin = getattr(
                    mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
                prev_tmp_downwards_reserves = getattr(
                    mod, "GenCommit{}_Downwards_Reserves_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
                prev_tmp_ramp_up_rate_mw_per_tmp = getattr(
                    mod, "GenCommit{}_Ramp_Up_Rate_MW_Per_Tmp".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]

            # Apply constraints
            # If ramp rate limits, adjusted for timepoint duration, allow you
            # to ramp up the full operable range between timepoints, constraint
            # won't bind, so skip
            if getattr(mod, "gen_commit_{}_ramp_up_when_on_rate".format(bin_or_lin))[
                g
            ] * 60 * prev_tmp_hrs_in_tmp >= (
                1
                - getattr(
                    mod, "gen_commit_{}_min_stable_level_fraction".format(bin_or_lin)
                )[g]
            ):
                return Constraint.Skip
            else:
                return (
                    getattr(
                        mod,
                        "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin),
                    )[g, tmp]
                    + getattr(
                        mod, "GenCommit{}_Upwards_Reserves_MW".format(Bin_or_Lin)
                    )[g, tmp]
                ) - (
                    prev_tmp_power_above_pmin - prev_tmp_downwards_reserves
                ) <= prev_tmp_ramp_up_rate_mw_per_tmp + getattr(
                    mod, "gen_commit_{}_allow_ramp_up_violation".format(bin_or_lin)
                )[
                    g
                ] * getattr(
                    mod, "GenCommit{}_Ramp_Up_Violation_MW".format(Bin_or_Lin)
                )[
                    g, tmp
                ]

    setattr(
        m,
        "GenCommit{}_Ramp_Up_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=ramp_up_constraint_rule,
        ),
    )

    def ramp_down_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Ramp_Down_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        Difference between power generation of consecutive timepoints has to
        obey ramp down rates.
        We assume that a unit has to reach its setpoint at the start of the
        timepoint; as such, the ramping between 2 timepoints is assumed to
        take place during the duration of the first timepoint, and the
        ramp rate is adjusted for the duration of the first timepoint.
        Constraint (13) in Morales-Espana et al. (2013)
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
                prev_tmp_power_above_pmin = getattr(
                    mod, "gen_commit_{}_linked_power_above_pmin".format(bin_or_lin)
                )[g, 0]
                prev_tmp_upwards_reserves = getattr(
                    mod, "gen_commit_{}_linked_upwards_reserves".format(bin_or_lin)
                )[g, 0]
                prev_tmp_ramp_down_rate_mw_per_tmp = getattr(
                    mod,
                    "gen_commit_{}_linked_ramp_down_rate_mw_per_tmp".format(bin_or_lin),
                )[g, 0]
            else:
                prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[
                    mod.prev_tmp[tmp, mod.balancing_type_project[g]]
                ]
                prev_tmp_power_above_pmin = getattr(
                    mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
                prev_tmp_upwards_reserves = getattr(
                    mod, "GenCommit{}_Upwards_Reserves_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
                prev_tmp_ramp_down_rate_mw_per_tmp = getattr(
                    mod, "GenCommit{}_Ramp_Down_Rate_MW_Per_Tmp".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            # If ramp rate limits, adjusted for timepoint duration, allow you
            # to ramp down the full operable range between timepoints,
            # constraint won't bind, so skip
            if getattr(mod, "gen_commit_{}_ramp_down_when_on_rate".format(bin_or_lin))[
                g
            ] * 60 * prev_tmp_hrs_in_tmp >= (
                1
                - getattr(
                    mod, "gen_commit_{}_min_stable_level_fraction".format(bin_or_lin)
                )[g]
            ):
                return Constraint.Skip
            else:
                return (prev_tmp_power_above_pmin + prev_tmp_upwards_reserves) - (
                    getattr(
                        mod,
                        "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin),
                    )[g, tmp]
                    - getattr(
                        mod, "GenCommit{}_Downwards_Reserves_MW".format(Bin_or_Lin)
                    )[g, tmp]
                ) <= prev_tmp_ramp_down_rate_mw_per_tmp + getattr(
                    mod, "gen_commit_{}_allow_ramp_down_violation".format(bin_or_lin)
                )[
                    g
                ] * getattr(
                    mod, "GenCommit{}_Ramp_Down_Violation_MW".format(Bin_or_Lin)
                )[
                    g, tmp
                ]

    setattr(
        m,
        "GenCommit{}_Ramp_Down_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=ramp_down_constraint_rule,
        ),
    )

    # Startup Power
    def unique_startup_type_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Unique_Startup_Type_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        Only one startup type can be active (>= 1) at the same time.
        """

        if g not in getattr(mod, "GEN_COMMIT_{}_STARTUP_BY_ST_PRJS".format(BIN_OR_LIN)):
            return Constraint.Skip

        sum_startup_types = sum(
            getattr(mod, "GenCommit{}_Startup_Type".format(Bin_or_Lin))[g, tmp, s]
            for s in getattr(mod, "GEN_COMMIT_{}_STR_TYPES_BY_PRJ".format(BIN_OR_LIN))[
                g
            ]
        )

        return (
            sum_startup_types
            == getattr(mod, "GenCommit{}_Startup".format(Bin_or_Lin))[g, tmp]
        )

    setattr(
        m,
        "GenCommit{}_Unique_Startup_Type_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=unique_startup_type_constraint_rule,
        ),
    )

    def active_startup_type_constraint_rule(mod, g, tmp, s):
        """
        **Constraint Name**: GenCommitBin_Active_Startup_Type_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES

        Startup_type s can only be activated (startup_type >= 1) if the unit
        has previously been down within the appropriate interval. The
        interval for startup type s is defined by the user specified
        boundary parameters gen_commit_bin_down_time_cutoff_hours[s] and
        gen_commit_bin_down_time_cutoff_hours[s+1]. Note that the down time
        interval includes any timepoints during which the unit is starting up.

        For the coldest (last) startup type, there is no s+1 and the
        constraint is skipped. This is okay because the model will select a
        hotter, cheaper startup type if it can and there can only be one
        startup_type active at once (see unique_startup_type_constraint_rule).
        This also means the constraint will be skipped if there is only one
        startup type.

        The constraint works by first determining the relevant timepoints, i.e.
        the timepoints within [TSU,s ; TSU,s+1) hours from *tmp*. If the unit
        has been down in any of these timepoints, we can activate the startup
        variable of the associated startup type for timepoint *tmp* (but only
        if the unit is actually starting in timepoint *tmp*).

        Example: we are in timepoint 7 (hourly resolution) and the down time
        interval is 2-4 hours for a hot start and >=4 hours for a cold start.
        This means timepoints 4 and 5 will be the relevant timepoints (resp. 2
        and 3 hours from *tmp*). A shutdown in any of those timepoints means
        that a start in timepoint 7 would be a hot start.

        See constraint (7) in Morales-Espana et al. (2017).
        """

        # Coldest startup type is un-constrained
        if s == getattr(mod, "GEN_COMMIT_{}_STR_TYPES_BY_PRJ".format(BIN_OR_LIN))[g].at(
            -1
        ):
            return Constraint.Skip

        # Get the timepoints within [TSU,s; TSU,s+1) hours from *tmp*
        relevant_tmps1, relevant_linked_tmps1 = determine_relevant_timepoints(
            mod,
            g,
            tmp,
            getattr(mod, "gen_commit_{}_down_time_cutoff_hours".format(bin_or_lin))[
                g, s
            ],
        )
        relevant_tmps2, relevant_linked_tmps2 = determine_relevant_timepoints(
            mod,
            g,
            tmp,
            getattr(mod, "gen_commit_{}_down_time_cutoff_hours".format(bin_or_lin))[
                g, s + 1
            ],
        )
        relevant_tmps = set(relevant_tmps2) - set(relevant_tmps1)
        relevant_linked_tmps = set(relevant_linked_tmps2) - set(relevant_linked_tmps1)

        # Skip constraint if we are within TSU,s hours from the start of the
        # horizon (linear horizon boundary), from the start of the furthest
        # linked timepoint (linked horizon boundary) or from the current tmp
        # (circular horizon boundary). We have no way to know whether unit was
        # down [TSU,s; TSU,s+1) hours ago so we can't know if this start
        # type could be active.
        if len(relevant_tmps) == 0 and len(relevant_linked_tmps) == 0:
            return Constraint.Skip

        # Equal to 1 if unit has been down within interval [TSU,s; TSU,s+1)
        # before hour t. This "activates" this particular startup type
        shutdown_within_interval = sum(
            getattr(mod, "GenCommit{}_Shutdown".format(Bin_or_Lin))[g, tp]
            for tp in relevant_tmps
        ) + sum(
            getattr(mod, "gen_commit_{}_linked_shutdown".format(bin_or_lin))[g, ltp]
            for ltp in relevant_linked_tmps
        )

        return (
            getattr(mod, "GenCommit{}_Startup_Type".format(Bin_or_Lin))[g, tmp, s]
            <= shutdown_within_interval
        )

    setattr(
        m,
        "GenCommit{}_Active_Startup_Type_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            rule=active_startup_type_constraint_rule,
        ),
    )

    def max_startup_power_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Max_Startup_Power_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        Startup power is 0 when the unit is committed and must be less than or
        equal to the minimum stable level when not committed.
        """

        return (
            getattr(mod, "GenCommit{}_Provide_Power_Startup_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            <= (1 - getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp])
            * getattr(mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin))[g, tmp]
            * getattr(
                mod, "gen_commit_{}_allow_startup_shutdown_power".format(bin_or_lin)
            )[g]
        )

    setattr(
        m,
        "GenCommit{}_Max_Startup_Power_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=max_startup_power_constraint_rule,
        ),
    )

    def ramp_during_startup_by_st_constraint_rule(mod, g, tmp, s):
        """
        **Constraint Name**: GenCommitBin_Ramp_During_Startup_By_ST_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES

        The difference between startup power of consecutive timepoints has to
        obey startup ramp up rates.

        We assume that a unit has to reach its setpoint at the start of the
        timepoint; as such, the ramping between 2 timepoints is assumed to
        take place during the duration of the first timepoint, and the
        ramp rate is adjusted for the duration of the first timepoint.
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
                prev_tmp_provide_power_startup = getattr(
                    mod,
                    "gen_commit_{}_linked_provide_power_startup_by_st_mw".format(
                        bin_or_lin
                    ),
                )[g, 0, s]
                prev_tmp_startup_ramp_rate_mw_per_tmp = getattr(
                    mod,
                    "gen_commit_{}_linked_startup_ramp_rate_by_st_mw_per_tmp".format(
                        bin_or_lin
                    ),
                )[g, 0, s]
            else:
                prev_tmp_provide_power_startup = getattr(
                    mod, "GenCommit{}_Provide_Power_Startup_By_ST_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]], s]
                prev_tmp_startup_ramp_rate_mw_per_tmp = getattr(
                    mod,
                    "GenCommit{}_Startup_Ramp_Rate_By_ST_MW_Per_Tmp".format(Bin_or_Lin),
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]], s]

            return (
                getattr(
                    mod, "GenCommit{}_Provide_Power_Startup_By_ST_MW".format(Bin_or_Lin)
                )[g, tmp, s]
                - prev_tmp_provide_power_startup
                <= prev_tmp_startup_ramp_rate_mw_per_tmp
                + getattr(
                    mod, "gen_commit_{}_allow_ramp_up_violation".format(bin_or_lin)
                )[g]
                * getattr(mod, "GenCommit{}_Ramp_Up_Violation_MW".format(Bin_or_Lin))[
                    g, tmp
                ]
            )

    setattr(
        m,
        "GenCommit{}_Ramp_During_Startup_By_ST_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            rule=ramp_during_startup_by_st_constraint_rule,
        ),
    )

    def increasing_startup_power_by_st_constraint_rule(mod, g, tmp, s):
        """
        **Constraint Name**:
        GenCommitBin_Increasing_Startup_Power_By_ST_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES

        GenCommitBin_Provide_Power_Startup_By_ST_MW[t] can only be less than
        GenCommitBin_Provide_Power_Startup_By_ST_MW[t-1] in the starting
        timepoint (when it is is back at 0). In other words,
        GenCommitBin_Provide_Power_Startup_By_ST_MW can only decrease in the
        starting timepoint; in all other timepoints it should increase or stay
        constant. This prevents situations in which the model can abuse this by
        providing starting power in some timepoints and then reducing power
        back to 0 without ever committing the unit.
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
                prev_tmp_provide_power_startup = getattr(
                    mod,
                    "gen_commit_{}_linked_provide_power_startup_by_st_mw".format(
                        bin_or_lin
                    ),
                )[g, 0, s]
            else:
                prev_tmp_provide_power_startup = getattr(
                    mod, "GenCommit{}_Provide_Power_Startup_By_ST_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]], s]

            return (
                getattr(
                    mod, "GenCommit{}_Provide_Power_Startup_By_ST_MW".format(Bin_or_Lin)
                )[g, tmp, s]
                - prev_tmp_provide_power_startup
                >= -getattr(mod, "GenCommit{}_Startup_Type".format(Bin_or_Lin))[
                    g, tmp, s
                ]
                * getattr(mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin))[g, tmp]
            )

    setattr(
        m,
        "GenCommit{}_Increasing_Startup_Power_By_ST_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            rule=increasing_startup_power_by_st_constraint_rule,
        ),
    )

    def power_during_startup_by_st_constraint_rule(mod, g, tmp, s):
        """
        **Constraint Name**: GenCommitBin_Power_During_Startup_By_ST_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS_STR_TYPES

        Power provision in the start timepoint (i.e. the timepoint when the unit
        is first committed) is constrained by the startup ramp rate (adjusted
        for timepoint duration).

        In other words, to provide 'committed' power in the start timepoint, we
        need to have provided startup power in the previous timepoint, which
        will in turn set the whole startup trajectory based on the previous
        constraints.

        When we are not in the start timepoint, simply constrain power provision
        by the capacity, which may not bind. To elaborate, when we are not in a
        start timepoint, t-1 could have had:
        1) the unit committed, meaning Pstarting[t-1]=0, resulting in
        power provision <= capacity, or
        2) the unit not committed, meaning that we are also not committed in t,
        i.e. power provision[t]=0, resulting in -Pstarting[t-1] <= capacity

        (Commit[t] x Pmin + P_above_Pmin[t]) - Pstarting[t-1]
        <=
        (1 - Start[t]) x Pmax + Start[t] x Startup_Ramp_Rate x Pmax
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
                prev_tmp_provide_power_startup = getattr(
                    mod,
                    "gen_commit_{}_linked_provide_power_startup_by_st_mw".format(
                        bin_or_lin
                    ),
                )[g, 0, s]
                prev_tmp_startup_ramp_rate_mw_per_tmp = getattr(
                    mod,
                    "gen_commit_{}_linked_startup_ramp_rate_by_st_mw_per_tmp".format(
                        bin_or_lin
                    ),
                )[g, 0, s]
            else:
                prev_tmp_provide_power_startup = getattr(
                    mod, "GenCommit{}_Provide_Power_Startup_By_ST_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]], s]
                prev_tmp_startup_ramp_rate_mw_per_tmp = getattr(
                    mod,
                    "GenCommit{}_Startup_Ramp_Rate_By_ST_MW_Per_Tmp".format(Bin_or_Lin),
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]], s]

            return (
                getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
                * getattr(mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin))[g, tmp]
                + getattr(
                    mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin)
                )[g, tmp]
            ) + getattr(mod, "GenCommit{}_Upwards_Reserves_MW".format(Bin_or_Lin))[
                g, tmp
            ] - prev_tmp_provide_power_startup <= (
                1
                - getattr(mod, "GenCommit{}_Startup_Type".format(Bin_or_Lin))[g, tmp, s]
            ) * getattr(
                mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin)
            )[
                g, tmp
            ] + getattr(
                mod, "GenCommit{}_Startup".format(Bin_or_Lin)
            )[
                g, tmp
            ] * prev_tmp_startup_ramp_rate_mw_per_tmp

    setattr(
        m,
        "GenCommit{}_Power_During_Startup_By_ST_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)),
            rule=power_during_startup_by_st_constraint_rule,
        ),
    )

    # Shutdown Power
    def max_shutdown_power_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Max_Shutdown_Power_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        Shutdown power is 0 when the unit is committed and must be less than or
        equal to the minimum stable level when not committed. Shutdown power
        must be explicitly allowed.
        """

        return (
            getattr(mod, "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            <= (1 - getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp])
            * getattr(mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin))[g, tmp]
            * getattr(
                mod, "gen_commit_{}_allow_startup_shutdown_power".format(bin_or_lin)
            )[g]
        )

    setattr(
        m,
        "GenCommit{}_Max_Shutdown_Power_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=max_shutdown_power_constraint_rule,
        ),
    )

    def ramp_during_shutdown_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Ramp_During_Shutdown_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        The difference between shutdown power of consecutive timepoints has to
        obey shutdown ramp up rates.

        We assume that a unit has to reach its setpoint at the start of the
        timepoint; as such, the ramping between 2 timepoints is assumed to
        take place during the duration of the first timepoint, and the
        ramp rate is adjusted for the duration of the first timepoint.
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
                prev_tmp_provide_power_shutdown = getattr(
                    mod,
                    "gen_commit_{}_linked_provide_power_shutdown_mw".format(bin_or_lin),
                )[g, 0]
                prev_tmp_shutdown_ramp_rate_mw_per_tmp = getattr(
                    mod,
                    "gen_commit_{}_linked_shutdown_ramp_rate_mw_per_tmp".format(
                        bin_or_lin
                    ),
                )[g, 0]
            else:
                prev_tmp_provide_power_shutdown = getattr(
                    mod, "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
                prev_tmp_shutdown_ramp_rate_mw_per_tmp = getattr(
                    mod, "GenCommit{}_Shutdown_Ramp_Rate_MW_Per_Tmp".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]

            return (
                prev_tmp_provide_power_shutdown
                - getattr(
                    mod, "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin)
                )[g, tmp]
                <= prev_tmp_shutdown_ramp_rate_mw_per_tmp
                + getattr(
                    mod, "gen_commit_{}_allow_ramp_down_violation".format(bin_or_lin)
                )[g]
                * getattr(mod, "GenCommit{}_Ramp_Down_Violation_MW".format(Bin_or_Lin))[
                    g, tmp
                ]
            )

    setattr(
        m,
        "GenCommit{}_Ramp_During_Shutdown_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=ramp_during_shutdown_constraint_rule,
        ),
    )

    def decreasing_shutdown_power_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Decreasing_Shutdown_Power_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        GenCommitBin_Provide_Power_Shutdown_MW[t-1] can only be less than
        GenCommitBin_Provide_Power_Shutdown_MW[t] if the unit stops in t (when
        it is back above 0). In other words, GenCommitBin_Provide_Power_Shutdown_MW
        can only increase in the stopping timepoint; in all other timepoints it
        should decrease or stay constant. This prevents situations in which the
        model can abuse this by providing stopping power in some timepoints without
        previously having committed the unit.
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
                prev_tmp_provide_power_shutdown = getattr(
                    mod,
                    "gen_commit_{}_linked_provide_power_shutdown_mw".format(bin_or_lin),
                )[g, 0]
            else:
                prev_tmp_provide_power_shutdown = getattr(
                    mod, "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin)
                )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]

        return (
            prev_tmp_provide_power_shutdown
            - getattr(mod, "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            >= -getattr(mod, "GenCommit{}_Shutdown".format(Bin_or_Lin))[g, tmp]
            * getattr(mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin))[g, tmp]
        )

    setattr(
        m,
        "GenCommit{}_Decreasing_Shutdown_Power_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=decreasing_shutdown_power_constraint_rule,
        ),
    )

    def min_power_on_shutdown_constraint_rule(mod, g, tmp):
        """
        **Constraint Name**: GenCommitBin_Power_During_Shutdown_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_TMPS

        This constraint ensures that power provision in the stop timepoint (
        i.e. the first timepoint the unit is not committed after having been
        committed) is constrained by the shutdown ramp rate (adjusted for
        timepoint duration), i.e., the unit can't immediately go down to zero
        when shutting down.

        When we are in not in the stop timepoint, the constraint simplifies
        to Pcommitted[prev_tmp] + Upwared_Reserves[prev_tmp] <= Pmax[
        prev_tmp]. In the stop timepoint, the constraint simplifies to
        Pstopping[tmp] >= Power_Provision[prev_tmp] -  Shutdown_Ramp_Rate[prev_tmp]

        .. note:: Note that the ramp rate (in MW per tmp) is set based on
        availabilty in the previous timepoint.

        (Commit[t-1] x Pmin[t-1] + P_above_Pmin[t-1]) - Pstopping[t]
        <=
        (1 - Stop[t]) x Pmax[t] + Stop[t] x shutdown_ramp_rate x Pmax[t-1]

        """

        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        ):
            prev_timepoint_commit = getattr(
                mod, "gen_commit_{}_linked_commit".format(bin_or_lin)
            )[g, 0]
            prev_timepoint_power_above_pmin = getattr(
                mod, "gen_commit_{}_linked_power_above_pmin".format(bin_or_lin)
            )[g, 0]
            prev_timepoint_upward_reserves = getattr(
                mod, "gen_commit_{}_linked_upwards_reserves".format(bin_or_lin)
            )[g, 0]
            prev_timepoint_shutdown_ramp_rate = getattr(
                mod,
                "gen_commit_{}_linked_shutdown_ramp_rate_mw_per_tmp".format(bin_or_lin),
            )[g, 0]
            prev_timepoint_pmin = getattr(
                mod,
                "gen_commit_{}_linked_pmin_mw".format(bin_or_lin),
            )[g, 0]
            prev_timepoint_pmax = getattr(
                mod,
                "gen_commit_{}_linked_pmax_mw".format(bin_or_lin),
            )[g, 0]
        elif check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linear",
        ):
            prev_timepoint_commit = None
            prev_timepoint_power_above_pmin = None
            prev_timepoint_upward_reserves = None
            prev_timepoint_shutdown_ramp_rate = None
            prev_timepoint_pmin = None
            prev_timepoint_pmax = None
        else:
            prev_timepoint_commit = getattr(
                mod, "GenCommit{}_Commit".format(Bin_or_Lin)
            )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            prev_timepoint_power_above_pmin = getattr(
                mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin)
            )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            prev_timepoint_upward_reserves = getattr(
                mod, "GenCommit{}_Upwards_Reserves_MW".format(Bin_or_Lin)
            )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            prev_timepoint_shutdown_ramp_rate = getattr(
                mod, "GenCommit{}_Shutdown_Ramp_Rate_MW_Per_Tmp".format(Bin_or_Lin)
            )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            prev_timepoint_pmin = getattr(
                mod, "GenCommit{}_Pmin_MW".format(Bin_or_Lin)
            )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            prev_timepoint_pmax = getattr(
                mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin)
            )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]

        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linear",
        ):
            return Constraint.Skip
        else:
            return (
                prev_timepoint_commit * prev_timepoint_pmin
                + prev_timepoint_power_above_pmin
            ) + prev_timepoint_upward_reserves - getattr(
                mod, "GenCommit{}_Provide_Power_Shutdown_MW".format(Bin_or_Lin)
            )[
                g, tmp
            ] <= (
                1 - getattr(mod, "GenCommit{}_Shutdown".format(Bin_or_Lin))[g, tmp]
            ) * prev_timepoint_pmax + getattr(
                mod, "GenCommit{}_Shutdown".format(Bin_or_Lin)
            )[
                g, tmp
            ] * prev_timepoint_shutdown_ramp_rate

    setattr(
        m,
        "GenCommit{}_Power_During_Shutdown_Constraint".format(Bin_or_Lin),
        Constraint(
            getattr(m, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)),
            rule=min_power_on_shutdown_constraint_rule,
        ),
    )

    def max_n_starts_per_hrz_rule(mod, prj, bt, hrz):
        """
        **Constraint Name**: GenCommitBin_Max_N_Starts_Per_Hrz_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_OPR_PRJS_BAL_TYPES_HRZS

        Limit the number of startups over a horizon.
        """

        if getattr(mod, f"gen_commit_{bin_or_lin}_max_n_starts_per_hrz")[
            prj, bt, hrz
        ] == float("inf"):
            return Constraint.Skip
        else:
            return (
                sum(
                    getattr(mod, "GenCommit{}_Startup".format(Bin_or_Lin))[prj, tmp]
                    for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
                )
                <= getattr(
                    mod, "gen_commit_{}_max_n_starts_per_hrz".format(bin_or_lin)
                )[prj, bt, hrz]
            )

    setattr(
        m,
        f"GenCommit{Bin_or_Lin}_Max_N_Starts_Per_Hrz_Constraint",
        Constraint(
            getattr(m, f"GEN_COMMIT_{BIN_OR_LIN}_N_STARTUP_BT_HRZS"),
            rule=max_n_starts_per_hrz_rule,
        ),
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp, Bin_or_Lin):
    """
    Power provision for gen_commit_bin generators is a variable constrained
    constrained to be between the generator's minimum stable level and its
    capacity if the generator is committed and 0 otherwise.
    """
    return (
        getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[g, tmp]
        - getattr(mod, "GenCommit{}_Auxiliary_Consumption_MW".format(Bin_or_Lin))[
            g, tmp
        ]
    )


def commitment_rule(mod, g, tmp, Bin_or_Lin):
    """
    Commitment decision in each timepoint
    """
    # TODO: shouldn't we return MW here to make this consistent w
    #  gen_commit_cap?
    return getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]


def online_capacity_rule(mod, g, tmp, Bin_or_Lin):
    """
    Capacity online in each timepoint.
    """
    return (
        getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
        * getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
    )


def variable_om_cost_rule(mod, g, tmp, Bin_or_Lin):
    """
    Variable O&M cost has two components which are additive:
    1. A fixed variable O&M rate (cost/MWh) that doesn't change with loading
       levels: :code:`variable_om_cost_per_mwh`.
    2. A variable variable O&M rate that changes with the loading level,
       similar to the heat rates. The idea is to represent higher variable cost
       rates at lower loading levels. This is captured in the
       :code:`GenCommitBin_Variable_OM_Cost_By_LL` decision variable. If no
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
    return (
        getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[g, tmp]
        * mod.variable_om_cost_per_mwh[g]
    )


def variable_om_by_period_cost_rule(mod, g, tmp, Bin_or_Lin):
    """ """
    return (
        getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[g, tmp]
        * mod.variable_om_cost_per_mwh_by_period[g, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, g, tmp, Bin_or_Lin):
    """ """
    return (
        getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[g, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[tmp]
    )


def variable_om_cost_by_ll_rule(mod, g, tmp, s, Bin_or_Lin):
    """
    Variable O&M cost has two components which are additive:
    1. A fixed variable O&M rate (cost/MWh) that doesn't change with loading
       levels: :code:`variable_om_cost_per_mwh`.
    2. A variable variable O&M rate that changes with the loading level,
       similar to the heat rates. The idea is to represent higher variable cost
       rates at lower loading levels. This is captured in the
       :code:`GenCommitBin_Variable_OM_Cost_By_LL` decision variable. If no
       variable O&M curve inputs are provided, this component will be zero.

    Most users will only use the first component, which is specified in the
    operational characteristics table.  Only operational types with
    commitment decisions can have the second component.
    """
    return (
        mod.vom_slope_cost_per_mwh[g, mod.period[tmp], s]
        * getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[g, tmp]
        + mod.vom_intercept_cost_per_mw_hr[g, mod.period[tmp], s]
        * getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
        * getattr(mod, "GenCommit{}_Synced".format(Bin_or_Lin))[g, tmp]
    )


def startup_cost_simple_rule(mod, g, tmp, Bin_or_Lin):
    """
    Simple startup costs are applied in each timepoint based on the amount of
    capacity (in MW) that is started up in that timepoint and the startup cost
    parameter.
    """
    return (
        getattr(mod, "GenCommit{}_Startup".format(Bin_or_Lin))[g, tmp]
        * getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
        * mod.startup_cost_per_mw[g]
    )


def startup_cost_by_st_rule(mod, g, tmp, BIN_OR_LIN, Bin_or_Lin):
    """
    Startup costs are applied in each timepoint based on the amount of capacity
    (in MW) that is started up in that timepoint for a given startup type and
    the startup cost parameter for that startup type. We take the sum across
    all startup types since only one startup type is active at the same time.
    """
    return (
        sum(
            mod.startup_cost_by_st_per_mw[g, s]
            * getattr(mod, "GenCommit{}_Startup_Type".format(Bin_or_Lin))[g, tmp, s]
            for s in getattr(mod, "GEN_COMMIT_{}_STR_TYPES_BY_PRJ".format(BIN_OR_LIN))[
                g
            ]
        )
        * getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
    )


def shutdown_cost_rule(mod, g, tmp, Bin_or_Lin):
    """
    Shutdown costs are applied in each timepoint based on the amount of
    capacity (in Mw) that is shut down in that timepoint and the shutdown
    cost parameter.
    """
    return (
        getattr(mod, "GenCommit{}_Shutdown".format(Bin_or_Lin))[g, tmp]
        * getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
        * mod.shutdown_cost_per_mw[g]
    )


def fuel_burn_by_ll_rule(mod, g, tmp, s, Bin_or_Lin):
    """ """
    return (
        mod.fuel_burn_slope_mmbtu_per_mwh[g, mod.period[tmp], s]
        * getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[g, tmp]
        + mod.fuel_burn_intercept_mmbtu_per_mw_hr[g, mod.period[tmp], s]
        * getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
        * getattr(mod, "GenCommit{}_Synced".format(Bin_or_Lin))[g, tmp]
    )


def startup_fuel_burn_rule(mod, g, tmp, Bin_or_Lin):
    """
    Startup fuel burn is applied in each timepoint based on the amount of
    capacity (in MW) that is started up in that timepoint and the startup
    fuel parameter. This does not vary by startup type.
    """
    return (
        getattr(mod, "GenCommit{}_Startup".format(Bin_or_Lin))[g, tmp]
        * getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
        * mod.startup_fuel_mmbtu_per_mw[g]
    )


def power_delta_rule(mod, g, tmp, Bin_or_Lin):
    """
    Ramp between this timepoint and the previous timepoint.
    Actual ramp rate in MW/hr depends on the duration of the timepoints.
    This is only used in tuning costs, so fine to skip for linked horizon's
    first timepoint.
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
        return (
            getattr(mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            - getattr(
                mod, "GenCommit{}_Provide_Power_Above_Pmin_MW".format(Bin_or_Lin)
            )[g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
        )


def fix_commitment(mod, g, tmp, Bin_or_Lin):
    """ """
    getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp] = (
        mod.fixed_commitment[g, mod.prev_stage_tmp_map[tmp]]
    )
    getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp].fixed = True


def operational_violation_cost_rule(mod, g, tmp, bin_or_lin, Bin_or_Lin):
    """

    :param mod:
    :param g:
    :param tmp:
    :return:
    """
    ramp_up_violation = (
        (
            getattr(mod, "GenCommit{}_Ramp_Up_Violation_MW".format(Bin_or_Lin))[g, tmp]
            * mod.ramp_up_violation_penalty[g]
        )
        if getattr(mod, "gen_commit_{}_allow_ramp_up_violation".format(bin_or_lin))[g]
        else 0
    )
    ramp_down_violation = (
        (
            getattr(mod, "GenCommit{}_Ramp_Down_Violation_MW".format(Bin_or_Lin))[
                g, tmp
            ]
            * mod.ramp_down_violation_penalty[g]
        )
        if getattr(mod, "gen_commit_{}_allow_ramp_down_violation".format(bin_or_lin))[g]
        else 0
    )
    min_up_time_violation = (
        (
            getattr(mod, "GenCommit{}_Min_Up_Time_Violation".format(Bin_or_Lin))[g, tmp]
            * mod.min_up_time_violation_penalty[g]
        )
        if getattr(mod, "gen_commit_{}_allow_min_up_time_violation".format(bin_or_lin))[
            g
        ]
        else 0
    )
    min_down_time_violation = (
        (
            getattr(mod, "GenCommit{}_Min_Down_Time_Violation".format(Bin_or_Lin))[
                g, tmp
            ]
            * mod.min_down_time_violation_penalty[g]
        )
        if getattr(
            mod, "gen_commit_{}_allow_min_down_time_violation".format(bin_or_lin)
        )[g]
        else 0
    )

    return (
        ramp_up_violation
        + ramp_down_violation
        + min_up_time_violation
        + min_down_time_violation
    )


def capacity_providing_inertia_rule(mod, g, tmp, Bin_or_Lin):
    """
    Capacity online in each timepoint.
    """
    return (
        getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[g, tmp]
        * getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[g, tmp]
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
    bin_or_lin_optype,
    bin_or_lin,
    BIN_OR_LIN,
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
        op_type=bin_or_lin_optype,
    )

    # Load data from startup_chars.tab (if it exists)
    load_startup_chars(
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type=bin_or_lin_optype,
        projects=projects,
    )

    # Number of starts allowed per horizon
    n_starts_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "startup_limits.tab",
    )

    if os.path.exists(n_starts_file):
        data_portal.load(
            filename=n_starts_file,
            index=getattr(mod, f"GEN_COMMIT_{BIN_OR_LIN}_N_STARTUP_BT_HRZS"),
            param=(
                getattr(
                    mod,
                    f"gen_commit_{bin_or_lin}_max_n_starts_per_hrz",
                ),
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
        "gen_commit_{}_linked_timepoint_params.tab".format(bin_or_lin),
    )
    if os.path.exists(linked_inputs_filename):
        data_portal.load(
            filename=linked_inputs_filename,
            index=getattr(mod, "GEN_COMMIT_{}_LINKED_TMPS".format(BIN_OR_LIN)),
            param=(
                getattr(mod, "gen_commit_{}_linked_commit".format(bin_or_lin)),
                getattr(mod, "gen_commit_{}_linked_startup".format(bin_or_lin)),
                getattr(mod, "gen_commit_{}_linked_shutdown".format(bin_or_lin)),
                getattr(
                    mod, "gen_commit_{}_linked_power_above_pmin".format(bin_or_lin)
                ),
                getattr(
                    mod, "gen_commit_{}_linked_upwards_reserves".format(bin_or_lin)
                ),
                getattr(
                    mod, "gen_commit_{}_linked_downwards_reserves".format(bin_or_lin)
                ),
                getattr(
                    mod,
                    "gen_commit_{}_linked_ramp_up_rate_mw_per_tmp".format(bin_or_lin),
                ),
                getattr(
                    mod,
                    "gen_commit_{}_linked_ramp_down_rate_mw_per_tmp".format(bin_or_lin),
                ),
                getattr(
                    mod,
                    "gen_commit_{}_linked_provide_power_shutdown_mw"
                    "".format(bin_or_lin),
                ),
                getattr(
                    mod,
                    "gen_commit_{}_linked_shutdown_ramp_rate_mw_per_tmp".format(
                        bin_or_lin
                    ),
                ),
                getattr(
                    mod,
                    "gen_commit_{}_linked_pmin_mw".format(bin_or_lin),
                ),
                getattr(
                    mod,
                    "gen_commit_{}_linked_pmax_mw".format(bin_or_lin),
                ),
            ),
        )

    # Linked timepoint params (by startup type)
    linked_startup_inputs_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "gen_commit_{}_linked_timepoint_str_type_params.tab".format(bin_or_lin),
    )
    if os.path.exists(linked_startup_inputs_filename):
        data_portal.load(
            filename=linked_startup_inputs_filename,
            param=(
                getattr(
                    mod,
                    "gen_commit_{}_linked_provide_power_startup_by_st_mw".format(
                        bin_or_lin
                    ),
                ),
                getattr(
                    mod,
                    "gen_commit_{}_linked_startup_ramp_rate_by_st_mw_per_tmp".format(
                        bin_or_lin
                    ),
                ),
            ),
        )


def add_to_prj_tmp_results(
    mod,
    BIN_OR_LIN,
    Bin_or_Lin,
    bin_or_lin,
):
    """ """

    results_columns = [
        "gross_power_mw",
        "auxiliary_consumption_mw",
        "net_power_mw",
        "committed_mw",
        "committed_units",
        "started_units",
        "stopped_units",
        "synced_units",
        "active_startup_type",
        "ramp_up_violation",
        "ramp_down_violation",
        "min_up_time_violation",
        "min_down_time_violation",
    ]

    data = [
        [
            prj,
            tmp,
            value(
                getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[
                    prj, tmp
                ]
            ),
            value(
                getattr(
                    mod,
                    "GenCommit{}_Auxiliary_Consumption_MW".format(Bin_or_Lin),
                )[prj, tmp]
            ),
            value(
                getattr(mod, "GenCommit{}_Provide_Power_MW".format(Bin_or_Lin))[
                    prj, tmp
                ]
            )
            - value(
                getattr(
                    mod,
                    "GenCommit{}_Auxiliary_Consumption_MW".format(Bin_or_Lin),
                )[prj, tmp]
            ),
            value(getattr(mod, "GenCommit{}_Pmax_MW".format(Bin_or_Lin))[prj, tmp])
            * value(getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[prj, tmp]),
            value(getattr(mod, "GenCommit{}_Commit".format(Bin_or_Lin))[prj, tmp]),
            value(getattr(mod, "GenCommit{}_Startup".format(Bin_or_Lin))[prj, tmp]),
            value(getattr(mod, "GenCommit{}_Shutdown".format(Bin_or_Lin))[prj, tmp]),
            value(getattr(mod, "GenCommit{}_Synced".format(Bin_or_Lin))[prj, tmp]),
            value(
                getattr(mod, "GenCommit{}_Active_Startup_Type".format(Bin_or_Lin))[
                    prj, tmp
                ]
            ),
            value(
                getattr(mod, "GenCommit{}_Ramp_Up_Violation_MW".format(Bin_or_Lin))[
                    prj, tmp
                ]
            ),
            value(
                getattr(mod, "GenCommit{}_Ramp_Down_Violation_MW".format(Bin_or_Lin))[
                    prj, tmp
                ]
            ),
            value(
                getattr(mod, "GenCommit{}_Min_Up_Time_Violation".format(Bin_or_Lin))[
                    prj, tmp
                ]
            ),
            value(
                getattr(
                    mod,
                    "GenCommit{}_Min_Down_Time_Violation".format(Bin_or_Lin),
                )[prj, tmp]
            ),
        ]
        for (prj, tmp) in getattr(mod, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN))
    ]

    return results_columns, data


def export_linked_subproblem_inputs(
    mod,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    Bin_or_Lin,
    BIN_OR_LIN,
    bin_or_lin,
):
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
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                next_subproblem,
                stage,
                "inputs",
                "gen_commit_{}_linked_timepoint_params.tab".format(bin_or_lin),
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(
                [
                    "project",
                    "linked_timepoint",
                    "linked_commit",
                    "linked_startup",
                    "linked_shutdown",
                    "linked_provide_power_above_pmin",
                    "linked_upward_reserves",
                    "linked_downward_reserves",
                    "linked_ramp_up_rate_mw_per_tmp",
                    "linked_ramp_down_rate_mw_per_tmp",
                    "linked_provide_power_shutdown",
                    "linked_shutdown_ramp_rate_mw_per_tmp",
                    "linked_pmin_mw",
                    "linked_pmax_mw",
                ]
            )

            for p, tmp in sorted(
                getattr(mod, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN))
            ):
                if tmp in tmps_to_link:
                    writer.writerow(
                        [
                            p,
                            tmp_linked_tmp_dict[tmp],
                            max(
                                min(
                                    value(
                                        getattr(
                                            mod, "GenCommit{}_Commit".format(Bin_or_Lin)
                                        )[p, tmp]
                                    ),
                                    1,
                                ),
                                0,
                            ),
                            max(
                                min(
                                    value(
                                        getattr(
                                            mod,
                                            "GenCommit{}_Startup".format(Bin_or_Lin),
                                        )[p, tmp]
                                    ),
                                    1,
                                ),
                                0,
                            ),
                            max(
                                min(
                                    value(
                                        getattr(
                                            mod,
                                            "GenCommit{}_Shutdown".format(Bin_or_Lin),
                                        )[p, tmp]
                                    ),
                                    1,
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Provide_Power_Above_Pmin_MW".format(
                                            Bin_or_Lin
                                        ),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Upwards_Reserves_MW".format(
                                            Bin_or_Lin
                                        ),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Downwards_Reserves_MW".format(
                                            Bin_or_Lin
                                        ),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Ramp_Up_Rate_MW_Per_Tmp".format(
                                            Bin_or_Lin
                                        ),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Ramp_Down_Rate_MW_Per_Tmp".format(
                                            Bin_or_Lin
                                        ),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Provide_Power_Shutdown_MW".format(
                                            Bin_or_Lin
                                        ),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Shutdown_Ramp_Rate_MW_Per_Tmp".format(
                                            Bin_or_Lin
                                        ),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Pmin_MW".format(Bin_or_Lin),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                            max(
                                value(
                                    getattr(
                                        mod,
                                        "GenCommit{}_Pmax_MW".format(Bin_or_Lin),
                                    )[p, tmp]
                                ),
                                0,
                            ),
                        ]
                    )
            # Export params by project, timepoint, and startup type
            # Only write this file if there are data for these results to
            # avoid throwing an index error when trying to load these inputs
            # into the next subproblem
            if getattr(mod, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)):
                with open(
                    os.path.join(
                        scenario_directory,
                        next_subproblem,
                        stage,
                        "inputs",
                        "gen_commit_{}_linked_timepoint_str_type_params.tab".format(
                            bin_or_lin
                        ),
                    ),
                    "w",
                    newline="",
                ) as f:
                    writer = csv.writer(f, delimiter="\t", lineterminator="\n")
                    writer.writerow(
                        [
                            "project",
                            "linked_timepoint",
                            "startup_type",
                            "linked_provide_power_startup",
                            "linked_startup_ramp_rate_mw_per_tmp",
                        ]
                    )
                    for p, tmp, s in sorted(
                        getattr(
                            mod, "GEN_COMMIT_{}_OPR_TMPS_STR_TYPES".format(BIN_OR_LIN)
                        )
                    ):
                        if tmp in tmps_to_link:
                            writer.writerow(
                                [
                                    p,
                                    tmp_linked_tmp_dict[tmp],
                                    s,
                                    max(
                                        value(
                                            getattr(
                                                mod,
                                                "GenCommit{}_Provide_Power_Startup_By_ST_MW".format(
                                                    Bin_or_Lin
                                                ),
                                            )[p, tmp, s]
                                        ),
                                        0,
                                    ),
                                    max(
                                        value(
                                            getattr(
                                                mod,
                                                "GenCommit{}_Startup_Ramp_Rate_By_ST_MW_Per_Tmp".format(
                                                    Bin_or_Lin
                                                ),
                                            )[p, tmp, s]
                                        ),
                                        0,
                                    ),
                                ]
                            )


def save_duals(m, bin_or_lin):
    m.constraint_indices["GenCommit{}_Ramp_Up_Constraint".format(bin_or_lin)] = [
        "project",
        "timepoint",
        "dual",
    ]

    m.constraint_indices["GenCommit{}_Ramp_Down_Constraint".format(bin_or_lin)] = [
        "project",
        "timepoint",
        "dual",
    ]

    m.constraint_indices["GenCommit{}_Min_Up_Time_Constraint".format(bin_or_lin)] = [
        "project",
        "timepoint",
        "dual",
    ]

    m.constraint_indices["GenCommit{}_Min_Down_Time_Constraint".format(bin_or_lin)] = [
        "project",
        "timepoint",
        "dual",
    ]


def generic_constraint_column_dict(Bin_or_Lin):
    constraint_column_dict = {
        "GenCommit{}_Ramp_Up_Constraint".format(Bin_or_Lin): "ramp_up_dual",
        "GenCommit{}_Ramp_Down_Constraint".format(Bin_or_Lin): "ramp_down_dual",
        "GenCommit{}_Min_Up_Time_Constraint".format(Bin_or_Lin): "min_up_time_dual",
        "GenCommit{}_Min_Down_Time_Constraint".format(Bin_or_Lin): "min_down_time_dual",
    }

    return constraint_column_dict


def add_duals_to_dispatch_results(mod, Bin_or_Lin, BIN_OR_LIN):
    constraint_column_dict = generic_constraint_column_dict(Bin_or_Lin)
    results_columns = [
        constraint_column_dict[c] for c in sorted(constraint_column_dict.keys())
    ]

    data = []
    for prj, tmp in getattr(mod, "GEN_COMMIT_{}_OPR_TMPS".format(BIN_OR_LIN)):
        duals = []
        for c in sorted(constraint_column_dict.keys()):
            constraint_object = getattr(mod, c)
            if (prj, tmp) in constraint_object:
                duals.append(duals_wrapper(mod, constraint_object[prj, tmp]))
            else:
                duals.append(None)

        data.append([prj, tmp] + duals)

    return results_columns, data
