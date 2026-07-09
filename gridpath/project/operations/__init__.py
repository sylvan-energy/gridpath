# Copyright 2016-2025 Blue Marble Analytics LLC.
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
The **gridpath.project.operations** package contains modules to describe the
operational capabilities, constraints, and costs of generation, storage,
and demand-side infrastructure 'projects' in the optimization problem.

In this package, we also create the project fuel burn and cost components to
be passed downstream for aggregation into the system-level constraints and
the objective function.

In the `__init__` module of the package, we specify fuel burn and cost
parameters for each project. The project's operational type uses these
parameters to determine the projects will incur fuel burn and cost in each
operational timepoint. All parameters are optional, i.e. each type can be
used without fuel or variable cost for example. Conversely, the user needs
to ensure that the specified functionality makes sense for the project's
operational type, e.g. even if startup costs are specified for a gen_var
project, that operational type uses the default method for startup costs,
which returns 0, as variable generators do not have the concept of startup
(see the documentation in operational_types.__init__ for the defaults and in
each individual operational type module). When incompatible parameters are
specified for an operational type, GridPath will flag a validation error and
throw a warning (but not an error) at runtime.
"""

import numpy as np
import os.path
import pandas as pd
from pyomo.environ import Set, Param, NonNegativeReals, Reals, PositiveReals

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import import_csv, directories_to_db_values
from gridpath.auxiliary.dynamic_components import headroom_variables, footroom_variables
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_values,
    get_expected_dtypes,
    validate_dtypes,
    validate_piecewise_curves,
    validate_startup_shutdown_rate_inputs,
)
from gridpath.project.common_functions import append_to_input_file
from gridpath.project.operations.operational_types.common_functions import (
    get_prj_temporal_index_opr_inputs_from_db,
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
    | | :code:`VAR_OM_COST_SIMPLE_PRJS`                                       |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which a simple variable O&M cost is specified.  |
    +-------------------------------------------------------------------------+
    | | :code:`VAR_OM_COST_CURVE_PRJS_PRDS_SGMS`                              |
    |                                                                         |
    | Three-dimensional set describing projects, their variable O&M cost      |
    | curve segment IDs, and the periods in which the project could be        |
    | operational.                                                            |
    +-------------------------------------------------------------------------+
    | | :code:`VAR_OM_COST_CURVE_PRJS`                                        |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which a variable O&M cost curve is specified.   |
    +-------------------------------------------------------------------------+
    | | :code:`VAR_OM_COST_ALL_PRJS`                                          |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which a simple variable O&M cost and/or a VOM   |
    | curve is specified.                                                     |
    +-------------------------------------------------------------------------+
    | | :code:`STARTUP_COST_SIMPLE_PRJS`                                      |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which a simple startup cost is specified.       |
    +-------------------------------------------------------------------------+
    | | :code:`STARTUP_BY_ST_PRJS_TYPES`                                      |
    |                                                                         |
    | Two-dimensional set describing projects and their startup types.        |
    | Startup types are ordered from hottest to coldest, e.g. if there are 3  |
    | startup types the hottest start is indicated by 1, and the coldest      |
    | start is indicated by 3.                                                |
    +-------------------------------------------------------------------------+
    | | :code:`STARTUP_BY_ST_PRJS`                                            |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which startup types are specified.              |
    +-------------------------------------------------------------------------+
    | | :code:`STARTUP_COST_PRJS`                                             |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | All projects for which startup costs are specified (this is the union   |
    | STARTUP_COST_SIMPLE_PRJS and STARTUP_BY_ST_PRJS.                        |
    +-------------------------------------------------------------------------+
    | | :code:`SHUTDOWN_COST_PRJS`                                            |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which a shutdown cost is specified.             |
    +-------------------------------------------------------------------------+
    | | :code:`FUEL_PRJ_FUELS`                                                |
    | | *Within*: :code:`m.PROJECTS * m.FUELS                                 |
    |                                                                         |
    | Projects that burn fuels along with the fuels they can burn. This will  |
    | determine emissions (via the fuels' carbon intensity) and fuel cost     |
    | (via the fuels' price).                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`FUEL_PRJS`                                                     |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which a fuel is specified.                      |
    +-------------------------------------------------------------------------+
    | | :code:`FUELS_BY_PRJ`                                                  |
    | | *Defined over*: :code:`FUEL_PRJS`                                     |
    | | *Within*: :code:`FUELS`                                               |
    |                                                                         |
    | The set of fuels that can be used by each fuel project.                 |
    +-------------------------------------------------------------------------+
    | | :code:`HR_CURVE_PRJS_PRDS_SGMS`                                       |
    |                                                                         |
    | Three-dimensional set describing projects, their heat rate curve        |
    | segment IDs, and the periods in which the project could be operational. |
    +-------------------------------------------------------------------------+
    | | :code:`HR_CURVE_PRJS`                                                 |
    | | *Within*: :code:`FUEL_PRJS`                                           |
    |                                                                         |
    | The set of projects for which a heat rate curve is specified.           |
    +-------------------------------------------------------------------------+
    | | :code:`STARTUP_FUEL_PRJS`                                             |
    | | *Within*: :code:`FUEL_PRJS`                                           |
    |                                                                         |
    | The set of projects for which startup fuel burn is specified.           |
    +-------------------------------------------------------------------------+
    | | :code:`RAMP_UP_VIOL_PRJS`                                             |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which ramp up constraints can be violated.      |
    +-------------------------------------------------------------------------+
    | | :code:`RAMP_DOWN_VIOL_PRJS`                                           |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which ramp down constraints can be violated.    |
    +-------------------------------------------------------------------------+
    | | :code:`MIN_UP_TIME_VIOL_PRJS`                                         |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which min up time constraints can be violated.  |
    +-------------------------------------------------------------------------+
    | | :code:`MIN_DOWN_TIME_VIOL_PRJS`                                       |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which min down time constraints can be violated.|
    +-------------------------------------------------------------------------+
    | | :code:`VIOL_ALL_PRJS`                                                 |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects for which an operational constraint can be violated.|
    +-------------------------------------------------------------------------+
    | | :code:`SOC_PENALTY_COST_PRJS`                                         |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects that incur cost if their state of charge is below   |
    | the maximum possible state of charge.                                   |
    +-------------------------------------------------------------------------+
    | | :code:`SOC_LAST_TMP_PENALTY_COST_PRJS`                                |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | The set of projects that incur cost if their state of charge is below   |
    | the maximum possible state of charge in the last tmp.                   |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`variable_om_cost_per_mwh`                                      |
    | | *Defined over*: :code:`VAR_OM_COST_SIMPLE_PRJS`                       |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's variable operations and maintenance cost per MWh of       |
    | power production. Do not specify if zero for memory efficiency.         |                                                      |
    +-------------------------------------------------------------------------+
    | | :code:`variable_om_cost_per_mwh_by_period`                            |
    | | *Defined over*: :code:`VAR_OM_COST_BY_PRD_PRJ_PRDS`                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's variable operations and maintenance cost per MWh of       |
    | power production (by period).                                           |
    +-------------------------------------------------------------------------+
    | | :code:`variable_om_cost_per_mwh_by_timepoint`                         |
    | | *Defined over*: :code:`VAR_OM_COST_BY_TMP_PRJ_TMPS`                   |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The project's variable operations and maintenance cost per MWh of       |
    | power production (by timepoint).                                        |
    +-------------------------------------------------------------------------+
    | | :code:`vom_slope_cost_per_mwh`                                        |
    | | *Defined over*: :code:`VAR_OM_COST_CURVE_PRJS_PRDS_SGMS`              |
    | | *Within*: :code:`PositiveReals`                                       |
    |                                                                         |
    | This param describes the slope of the piecewise linear variable O&M     |
    | cost for each project's variable O&M cost segment in each operational   |
    | period. The units are cost of variable O&M per MWh of electricity       |
    | generation.                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`vom_intercept_cost_per_mw_hr`                                  |
    | | *Defined over*: :code:`VAR_OM_COST_CURVE_PRJS_PRDS_SGMS`              |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | This param describes the intercept of the piecewise linear variable O&M |
    | cost for each project's variable O&M cost segment in each operational   |
    | period. The units are cost of variable O&M per MW of operational        |
    | capacity per hour (multiply by operational capacity and timepoint       |
    | duration to get actual cost).                                           |
    +-------------------------------------------------------------------------+
    | | :code:`startup_cost_per_mw`                                           |
    | | *Defined over*: :code:`STARTUP_COST_SIMPLE_PRJS`                      |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's startup cost per MW of capacity that is started up.       |
    +-------------------------------------------------------------------------+
    | | :code:`startup_cost_by_st_per_mw`                                     |
    | | *Defined over*: :code:`STARTUP_BY_ST_PRJS_TYPES`                      |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's startup cost per MW of capacity that is started up for a  |
    | for a given startup type.                                               |
    +-------------------------------------------------------------------------+
    | | :code:`shutdown_cost_per_mw`                                          |
    | | *Defined over*: :code:`SHUTDOWN_COST_PRJS`                            |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's shutdown cost per MW of capacity that is shut down.       |
    +-------------------------------------------------------------------------+
    | | :code:`shutdown_cost_per_mw`                                          |
    | | *Defined over*: :code:`HR_CURVE_PRJS_PRDS_SGMS`                       |
    | | *Within*: :code:`PositiveReals`                                       |
    |                                                                         |
    | This param describes the slope of the piecewise linear fuel burn for    |
    | each project's heat rate segment in each operational period. The units  |
    | are MMBtu of fuel burn per MWh of electricity generation.               |
    +-------------------------------------------------------------------------+
    | | :code:`fuel_burn_intercept_mmbtu_per_mw_hr`                           |
    | | *Defined over*: :code:`HR_CURVE_PRJS_PRDS_SGMS`                       |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | This param describes the intercept of the piecewise linear fuel burn    |
    | for each project's heat rate segment in each operational period. The    |
    | units are MMBtu of fuel burn per MW of operational capacity per hour    |
    | (multiply by operational capacity and timepoint duration to get fuel    |
    | burn in MMBtu).                                                         |
    +-------------------------------------------------------------------------+
    | | :code:`startup_fuel_mmbtu_per_mw`                                     |
    | | *Defined over*: :code:`STARTUP_FUEL_PRJS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's fuel expenditure per MW started up.                       |
    +-------------------------------------------------------------------------+
    | | :code:`ramp_up_violation_penalty`                                     |
    | | *Defined over*: :code:`RAMP_UP_VIOL_PRJS`                             |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's cost for violating its ramp up constraint per unit energy.|
    +-------------------------------------------------------------------------+
    | | :code:`ramp_down_violation_penalty`                                   |
    | | *Defined over*: :code:`RAMP_DOWN_VIOL_PRJS`                           |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's cost for violating its ramp down constraint per unit      |
    | energy.                                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`ramp_tuning_cost_per_mw`                                       |
    | | *Defined over*: :code:`PRJS`.                                         |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's cost on ramping (usually used for tuning dispatch).       |
    +-------------------------------------------------------------------------+
    | | :code:`min_up_time_violation_penalty`                                 |
    | | *Defined over*: :code:`MIN_UP_TIME_VIOL_PRJS`                         |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's cost for violating its min up time constraint per         |
    | violation instance.                                                     |
    +-------------------------------------------------------------------------+
    | | :code:`min_down_time_violation_penalty`                               |
    | | *Defined over*: :code:`MIN_DOWN_TIME_VIOL_PRJS`                       |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's cost for violating its min down time constraint per       |
    | violation instance.                                                     |
    +-------------------------------------------------------------------------+
    | | :code:`curtailment_cost_per_powerunithour`                            |
    | | *Defined over*: :code:`CURTAILMENT_COST_PRJS_PRDS`                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's cost of curtailment per power-unitXhour in a given period.|
    +-------------------------------------------------------------------------+
    | | :code:`soc_penalty_cost_per_energyunit`                               |
    | | *Defined over*: :code:`SOC_PENALTY_COST_PRJS`                         |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's cost per unit of energy below the maximum state of charge.|
    +-------------------------------------------------------------------------+
    | | :code:`soc_last_tmp_penalty_cost_per_energyunit`                      |
    | | *Defined over*: :code:`SOC_LAST_TMP_PENALTY_COST_PRJS`                |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's cost per unit of energy below the maximum state of charge |
    | in the last timepoint of the horizon.                                   |
    +-------------------------------------------------------------------------+
    """

    # Sets
    ###########################################################################
    # Variable O&M cost projects (simple)
    m.VAR_OM_COST_SIMPLE_PRJS = Set(within=m.PROJECTS)

    # Variable O&M cost by project and period
    m.VAR_OM_COST_BY_PRD_PRJ_PRDS = Set(dimen=2, within=m.PROJECTS * m.PERIODS)
    m.VAR_OM_COST_BY_PRD_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(set([prj for (prj, prd) in mod.VAR_OM_COST_BY_PRD_PRJ_PRDS]))
        ),
    )

    # Variable O&M cost by project and timepoint
    m.VAR_OM_COST_BY_TMP_PRJ_TMPS = Set(dimen=2, within=m.PROJECTS * m.TMPS)
    m.VAR_OM_COST_BY_TMP_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(set([prj for (prj, tmp) in mod.VAR_OM_COST_BY_TMP_PRJ_TMPS]))
        ),
    )

    # Variable O&M cost projects (by loading level)
    m.VAR_OM_COST_CURVE_PRJS_PRDS_SGMS = Set(dimen=3, ordered=True)
    m.VAR_OM_COST_CURVE_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(set([prj for (prj, p, s) in mod.VAR_OM_COST_CURVE_PRJS_PRDS_SGMS])),
        ),
    )

    m.VAR_OM_COST_ALL_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(set(mod.VAR_OM_COST_SIMPLE_PRJS | mod.VAR_OM_COST_CURVE_PRJS)),
        ),
    )

    # Startup cost projects (simple)
    m.STARTUP_COST_SIMPLE_PRJS = Set(within=m.PROJECTS)

    # Startup cost by startup type projects
    m.STARTUP_BY_ST_PRJS_TYPES = Set(dimen=2, ordered=True)
    m.STARTUP_BY_ST_PRJS = Set(
        initialize=lambda mod: sorted(
            list(set([p for (p, t) in mod.STARTUP_BY_ST_PRJS_TYPES]))
        )
    )

    # All startup cost projects
    m.STARTUP_COST_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(
                set(
                    [p for p in mod.STARTUP_COST_SIMPLE_PRJS]
                    + [p for p in mod.STARTUP_BY_ST_PRJS]
                )
            ),
        ),
    )

    # Shutdown cost projects
    m.SHUTDOWN_COST_PRJS = Set(within=m.PROJECTS)

    # Projects that burn fuel
    m.FUEL_PRJ_FUELS = Set(within=m.PROJECTS * m.FUELS)
    m.FUEL_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(set([prj for (prj, f) in mod.FUEL_PRJ_FUELS])),
        ),
    )
    m.FUELS_BY_PRJ = Set(
        m.FUEL_PRJS,
        within=m.FUELS,
        initialize=lambda mod, prj: [f for (p, f) in mod.FUEL_PRJ_FUELS if p == prj],
    )

    m.FUEL_PRJ_FUELS_FUEL_GROUP = Set(
        dimen=3,
        within=m.FUEL_PRJS * m.FUEL_GROUPS_FUELS,
        initialize=lambda mod: sorted(
            list(
                set(
                    (g, fg, f)
                    for (fg, f) in mod.FUEL_GROUPS_FUELS
                    for (g, _f) in mod.FUEL_PRJ_FUELS
                    if f == _f
                ),
            )
        ),
    )

    # Projects with heat rate curves (must be within FUEL_PRJS)
    m.HR_CURVE_PRJS_PRDS_SGMS = Set(dimen=3)

    m.HR_CURVE_PRJS = Set(
        within=m.FUEL_PRJS,
        initialize=lambda mod: sorted(
            list(set([prj for (prj, p, s) in mod.HR_CURVE_PRJS_PRDS_SGMS])),
        ),
    )

    # Fuel projects that incur fuel burn on startup
    m.STARTUP_FUEL_PRJS = Set(within=m.FUEL_PRJS)

    # Projects that allow operational constraint violations
    m.RAMP_UP_VIOL_PRJS = Set(within=m.PROJECTS)
    m.RAMP_DOWN_VIOL_PRJS = Set(within=m.PROJECTS)
    m.MIN_UP_TIME_VIOL_PRJS = Set(within=m.PROJECTS)
    m.MIN_DOWN_TIME_VIOL_PRJS = Set(within=m.PROJECTS)

    m.VIOL_ALL_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(
                set(
                    mod.RAMP_UP_VIOL_PRJS
                    | mod.RAMP_DOWN_VIOL_PRJS
                    | mod.MIN_UP_TIME_VIOL_PRJS
                    | mod.MIN_DOWN_TIME_VIOL_PRJS
                )
            ),
        ),
    )

    # Projects with cost of curtailment
    # Variable O&M cost by project and period
    m.CURTAILMENT_COST_PRJ_PRDS = Set(dimen=2, within=m.PROJECTS * m.PERIODS)
    m.CURTAILMENT_COST_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(set([prj for (prj, prd) in mod.CURTAILMENT_COST_PRJ_PRDS]))
        ),
    )

    # Projects with cost based on the state of charge
    m.SOC_PENALTY_COST_PRJS = Set(within=m.PROJECTS)
    m.SOC_LAST_TMP_PENALTY_COST_PRJS = Set(within=m.PROJECTS)

    # Projects with non-fuel carbon emissions
    m.NONFUEL_CARBON_EMISSIONS_PRJS = Set(within=m.PROJECTS)

    # Optional Params
    ###########################################################################
    m.variable_om_cost_per_mwh = Param(
        m.VAR_OM_COST_SIMPLE_PRJS, within=NonNegativeReals
    )

    m.variable_om_cost_per_mwh_by_period = Param(
        m.VAR_OM_COST_BY_PRD_PRJ_PRDS, within=NonNegativeReals
    )

    m.variable_om_cost_per_mwh_by_timepoint = Param(
        m.VAR_OM_COST_BY_TMP_PRJ_TMPS, within=Reals
    )

    m.vom_slope_cost_per_mwh = Param(
        m.VAR_OM_COST_CURVE_PRJS_PRDS_SGMS, within=NonNegativeReals
    )

    m.vom_intercept_cost_per_mw_hr = Param(
        m.VAR_OM_COST_CURVE_PRJS_PRDS_SGMS, within=Reals
    )

    m.startup_cost_per_mw = Param(m.STARTUP_COST_SIMPLE_PRJS, within=NonNegativeReals)

    m.startup_cost_by_st_per_mw = Param(
        m.STARTUP_BY_ST_PRJS_TYPES, within=NonNegativeReals
    )

    m.shutdown_cost_per_mw = Param(m.SHUTDOWN_COST_PRJS, within=NonNegativeReals)

    m.fuel_burn_slope_mmbtu_per_mwh = Param(
        m.HR_CURVE_PRJS_PRDS_SGMS, within=PositiveReals
    )

    m.fuel_burn_intercept_mmbtu_per_mw_hr = Param(
        m.HR_CURVE_PRJS_PRDS_SGMS, within=Reals
    )

    m.startup_fuel_mmbtu_per_mw = Param(m.STARTUP_FUEL_PRJS, within=NonNegativeReals)

    m.ramp_up_violation_penalty = Param(m.RAMP_UP_VIOL_PRJS, within=NonNegativeReals)

    m.ramp_down_violation_penalty = Param(
        m.RAMP_DOWN_VIOL_PRJS, within=NonNegativeReals
    )

    m.ramp_tuning_cost_per_mw = Param(m.PROJECTS, within=NonNegativeReals, default=0)

    m.min_up_time_violation_penalty = Param(
        m.MIN_UP_TIME_VIOL_PRJS, within=NonNegativeReals
    )

    m.min_down_time_violation_penalty = Param(
        m.MIN_DOWN_TIME_VIOL_PRJS, within=NonNegativeReals
    )

    m.curtailment_cost_per_powerunithour = Param(
        m.CURTAILMENT_COST_PRJ_PRDS, within=NonNegativeReals, default=0
    )

    m.soc_penalty_cost_per_energyunit = Param(
        m.SOC_PENALTY_COST_PRJS, within=NonNegativeReals
    )

    m.soc_last_tmp_penalty_cost_per_energyunit = Param(
        m.SOC_LAST_TMP_PENALTY_COST_PRJS, within=NonNegativeReals
    )

    m.nonfuel_carbon_emissions_per_mwh = Param(
        m.NONFUEL_CARBON_EMISSIONS_PRJS, within=NonNegativeReals
    )

    # Start list of headroom and footroom variables by project
    record_dynamic_components(
        d,
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    )


def record_dynamic_components(
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    :param d: the dynamic components class object we'll be adding to
    :param scenario_directory: the base scenario directory
    :param stage: if horizon subproblems exist, the horizon name; NOT USED
    :param stage: if stage subproblems exist, the stage name; NOT USED

    Set the keys for the headroom and footroom variable
    dictionaries: the keys are all the projects included in the
    'projects.tab' input file. The values of these dictionaries are
    initially empty lists and will be populated later by each of included
    the reserve (e.g regulation up) modules. E.g. if the user has requested to
    model spinning reserves and project *r* has a value in the column
    associated with the spinning-reserves balancing area, then the name of
    project-level spinning-reserves-provision variable will be added to that
    project's list of variables in the 'headroom_variables' dictionary. For
    downward reserves, the associated variables are added to the
    'footroom_variables' dictionary.
    """

    project_df = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "projects.tab",
        ),
        sep="\t",
    )

    # Reserve variables
    # Will be determined based on whether the user has specified the
    # respective reserve module AND based on whether a reserve zone is
    # specified for a project in projects.tab
    # We need to make the dictionaries first; it is the lists for each key
    # that are populated by the modules
    setattr(d, headroom_variables, {r: [] for r in project_df.project})
    setattr(d, footroom_variables, {r: [] for r in project_df.project})


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
    :param d:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """
    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "projects.tab",
        ),
        select=(
            "project",
            "variable_om_cost_per_mwh",
            "startup_fuel_mmbtu_per_mw",
            "startup_cost_per_mw",
            "shutdown_cost_per_mw",
            "ramp_up_violation_penalty",
            "ramp_down_violation_penalty",
            "ramp_tuning_cost_per_mw",
            "min_up_time_violation_penalty",
            "min_down_time_violation_penalty",
            "soc_penalty_cost_per_energyunit",
            "soc_last_tmp_penalty_cost_per_energyunit",
            "nonfuel_carbon_emissions_per_mwh",
        ),
        param=(
            m.variable_om_cost_per_mwh,
            m.startup_fuel_mmbtu_per_mw,
            m.startup_cost_per_mw,
            m.shutdown_cost_per_mw,
            m.ramp_up_violation_penalty,
            m.ramp_down_violation_penalty,
            m.ramp_tuning_cost_per_mw,
            m.min_up_time_violation_penalty,
            m.min_down_time_violation_penalty,
            m.soc_penalty_cost_per_energyunit,
            m.soc_last_tmp_penalty_cost_per_energyunit,
            m.nonfuel_carbon_emissions_per_mwh,
        ),
    )

    # Get the periods for determining by-period params that apply to all
    # periods
    periods_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "periods.tab",
    )
    periods_df = pd.read_csv(periods_file, sep="\t")
    prd_set = set(periods_df["period"])

    timepoints_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "timepoints.tab",
    )
    timepoints_df = pd.read_csv(timepoints_file, sep="\t")
    tmp_set = set(timepoints_df["timepoint"])

    # Variable O&M by period and timepoint
    for prd_or_tmp_str in ["period", "timepoint"]:
        project_var_om_file = os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            f"project_variable_om_by_{prd_or_tmp_str}.tab",
        )
        if os.path.exists(project_var_om_file):
            var_om_df = pd.read_csv(project_var_om_file, sep="\t").set_index(
                ["project", prd_or_tmp_str]
            )
            var_om_prj_idx_list = []
            var_om_by_idx_dict = {}

            for idx, val in var_om_df.iterrows():
                prj, prd_or_tmp = idx
                if prd_or_tmp == 0:
                    if prd_or_tmp_str == "period":
                        set_to_use = prd_set
                    else:
                        set_to_use = tmp_set
                    for _prd_or_tmp in sorted(list(set_to_use)):
                        var_om_prj_idx_list.append((prj, _prd_or_tmp))
                        var_om_by_idx_dict[prj, _prd_or_tmp] = var_om_df.loc[
                            prj, prd_or_tmp
                        ][f"variable_om_cost_by_{prd_or_tmp_str}"]
                else:
                    var_om_prj_idx_list.append((prj, prd_or_tmp))
                    var_om_by_idx_dict[prj, prd_or_tmp] = var_om_df.loc[
                        prj, prd_or_tmp
                    ][f"variable_om_cost_by_{prd_or_tmp_str}"]
            set_name_prd_or_tmp = "PRD" if prd_or_tmp_str == "period" else "TMP"
            data_portal.data()[
                f"VAR_OM_COST_BY_{set_name_prd_or_tmp}_PRJ_{set_name_prd_or_tmp}S"
            ] = {None: var_om_prj_idx_list}
            data_portal.data()[
                f"variable_om_cost_per_mwh_by_{prd_or_tmp_str}"
            ] = var_om_by_idx_dict

    # Fuels
    project_fuels_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "project_fuels.tab",
    )
    if os.path.exists(project_fuels_file):
        data_portal.load(
            filename=project_fuels_file,
            select=("project", "fuel"),
            index=m.FUEL_PRJ_FUELS,
            param=(),
        )

    data_portal.data()["VAR_OM_COST_SIMPLE_PRJS"] = {
        None: list(data_portal.data()["variable_om_cost_per_mwh"].keys())
    }

    data_portal.data()["STARTUP_FUEL_PRJS"] = {
        None: list(data_portal.data()["startup_fuel_mmbtu_per_mw"].keys())
    }

    data_portal.data()["STARTUP_COST_SIMPLE_PRJS"] = {
        None: list(data_portal.data()["startup_cost_per_mw"].keys())
    }

    data_portal.data()["SHUTDOWN_COST_PRJS"] = {
        None: list(data_portal.data()["shutdown_cost_per_mw"].keys())
    }

    data_portal.data()["RAMP_UP_VIOL_PRJS"] = {
        None: list(data_portal.data()["ramp_up_violation_penalty"].keys())
    }

    data_portal.data()["RAMP_DOWN_VIOL_PRJS"] = {
        None: list(data_portal.data()["ramp_down_violation_penalty"].keys())
    }

    data_portal.data()["MIN_UP_TIME_VIOL_PRJS"] = {
        None: list(data_portal.data()["min_up_time_violation_penalty"].keys())
    }

    data_portal.data()["MIN_DOWN_TIME_VIOL_PRJS"] = {
        None: list(data_portal.data()["min_down_time_violation_penalty"].keys())
    }

    # Curtailment costs (by project/period)
    project_curtailment_cost_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "project_curtailment_cost.tab",
    )
    if os.path.exists(project_curtailment_cost_file):
        curtailment_df = pd.read_csv(project_curtailment_cost_file, sep="\t").set_index(
            ["project", "period"]
        )
        curtailment_prj_idx_list = []
        curtailment_by_idx_dict = {}

        for idx, val in curtailment_df.iterrows():
            prj, prd = idx
            if prd == 0:
                for _prd in sorted(list(prd_set)):
                    curtailment_prj_idx_list.append((prj, _prd))
                    curtailment_by_idx_dict[prj, _prd] = curtailment_df.loc[prj, prd][
                        "curtailment_cost_per_powerunithour"
                    ]
            else:
                curtailment_prj_idx_list.append((prj, prd))
                curtailment_by_idx_dict[prj, prd] = curtailment_df.loc[prj, prd][
                    "curtailment_cost_per_powerunithour"
                ]
        data_portal.data()[f"CURTAILMENT_COST_PRJ_PRDS"] = {
            None: curtailment_prj_idx_list
        }
        data_portal.data()[
            "curtailment_cost_per_powerunithour"
        ] = curtailment_by_idx_dict

    data_portal.data()["SOC_PENALTY_COST_PRJS"] = {
        None: list(data_portal.data()["soc_penalty_cost_per_energyunit"].keys())
    }

    data_portal.data()["SOC_LAST_TMP_PENALTY_COST_PRJS"] = {
        None: list(
            data_portal.data()["soc_last_tmp_penalty_cost_per_energyunit"].keys()
        )
    }

    data_portal.data()["NONFUEL_CARBON_EMISSIONS_PRJS"] = {
        None: list(data_portal.data()["nonfuel_carbon_emissions_per_mwh"].keys())
    }

    # VOM curves
    vom_curves_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "variable_om_curves.tab",
    )

    if os.path.exists(vom_curves_file):
        vom_df = pd.read_csv(vom_curves_file, sep="\t")
        vom_projects = set(vom_df["project"].unique())

        slope_dict, intercept_dict = get_slopes_intercept_by_project_period_segment(
            vom_df, "average_variable_om_cost_per_mwh", vom_projects, prd_set
        )
        vom_project_segments = list(slope_dict.keys())

        data_portal.data()["VAR_OM_COST_CURVE_PRJS_PRDS_SGMS"] = {
            None: vom_project_segments
        }
        data_portal.data()["vom_slope_cost_per_mwh"] = slope_dict
        data_portal.data()["vom_intercept_cost_per_mw_hr"] = intercept_dict

    # Startup chars
    startup_chars_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "startup_chars.tab",
    )

    if os.path.exists(startup_chars_file):
        df = pd.read_csv(startup_chars_file, sep="\t")

        # Note: the rank function requires at least one numeric input in the
        # down_time_cutoff_hours column (can't be all NULL/None).
        if len(df) > 0:
            df["startup_type_id"] = df.groupby("project")[
                "down_time_cutoff_hours"
            ].rank()

        startup_ramp_projects_types = list()
        startup_cost_dict = dict()
        for i, row in df.iterrows():
            project = row["project"]
            startup_type_id = row["startup_type_id"]
            startup_cost = row["startup_cost_per_mw"]

            startup_ramp_projects_types.append((project, startup_type_id))
            startup_cost_dict[(project, startup_type_id)] = float(startup_cost)

        data_portal.data()["STARTUP_BY_ST_PRJS_TYPES"] = {
            None: startup_ramp_projects_types
        }
        data_portal.data()["startup_cost_by_st_per_mw"] = startup_cost_dict

    # HR curves
    hr_curves_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "heat_rate_curves.tab",
    )
    project_fuels_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "project_fuels.tab",
    )

    # Get column names as a few columns will be optional;
    # won't load data if fuel column does not exist
    if os.path.exists(hr_curves_file) and os.path.exists(project_fuels_file):
        hr_df = pd.read_csv(hr_curves_file, sep="\t")
        projects = set(hr_df["project"].unique())

        pr_df = pd.read_csv(project_fuels_file, sep="\t", usecols=["project", "fuel"])
        pr_df = pr_df[(pr_df["fuel"] != ".") & (pr_df["project"].isin(projects))]

        fuel_projects = pr_df["project"].unique()

        slope_dict, intercept_dict = get_slopes_intercept_by_project_period_segment(
            hr_df, "average_heat_rate_mmbtu_per_mwh", fuel_projects, prd_set
        )

        fuel_project_segments = list(slope_dict.keys())

        data_portal.data()["HR_CURVE_PRJS_PRDS_SGMS"] = {None: fuel_project_segments}
        data_portal.data()["fuel_burn_slope_mmbtu_per_mwh"] = slope_dict
        data_portal.data()["fuel_burn_intercept_mmbtu_per_mw_hr"] = intercept_dict


# Database
###############################################################################


def get_inputs_from_database(
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
    proj_opchar = c.execute(
        """
        SELECT project, variable_om_cost_per_mwh,
        min_stable_level_fraction, unit_size_mw,
        startup_cost_per_mw, shutdown_cost_per_mw,
        startup_fuel_mmbtu_per_mw,
        startup_plus_ramp_up_rate,
        shutdown_plus_ramp_down_rate,
        ramp_up_when_on_rate,
        ramp_down_when_on_rate,
        ramp_up_violation_penalty,
        ramp_down_violation_penalty,
        ramp_tuning_cost_per_mw,
        min_up_time_hours, min_up_time_violation_penalty,
        min_down_time_hours, min_down_time_violation_penalty,
        allow_startup_shutdown_power,
        storage_efficiency, charging_efficiency, discharging_efficiency,
        charging_capacity_multiplier, discharging_capacity_multiplier,
        minimum_duration_hours, maximum_duration_hours,
        aux_consumption_frac_capacity, aux_consumption_frac_power,
        last_commitment_stage, cap_factor_default,
        powerunithour_per_fuelunit, soc_penalty_cost_per_energyunit,
        soc_last_tmp_penalty_cost_per_energyunit,
        max_losses_in_hrz_frac_stor_energy_capacity,
        partial_availability_threshold,
        nonfuel_carbon_emissions_per_mwh,
        powerhouse, generator_efficiency, linked_load_component,
        efficiency_factor, energy_requirement_factor, 
        losses_factor_in_energy_target, losses_factor_curtailment, 	
        upward_reserves_to_soc_depletion
        -- Get only the subset of projects in the portfolio with their 
        -- capacity types based on the project_portfolio_scenario_id 
        FROM
        (SELECT project, capacity_type
        FROM inputs_project_portfolios
        WHERE project_portfolio_scenario_id = {}) as portfolio_tbl
        LEFT OUTER JOIN
        -- Select the operational characteristics based on the 
        -- project_operational_chars_scenario_id
        inputs_project_operational_chars
        USING (project)
        WHERE project_operational_chars_scenario_id = {}
        ;
        """.format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
        )
    )

    var_om_by_prd_c = conn.cursor()
    var_om_by_prd = var_om_by_prd_c.execute(f"""
        SELECT project, period, variable_om_cost_by_period
        FROM inputs_project_portfolios
        -- select the correct operational characteristics subscenario
        INNER JOIN
        (SELECT project, variable_om_cost_by_period_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
        ) AS op_char
        USING(project)
        -- select only heat curves of matching projects
        INNER JOIN
        inputs_project_variable_om_cost_by_period
        USING(project, variable_om_cost_by_period_scenario_id)
        -- Get only the subset of projects in the portfolio based on the 
        -- project_portfolio_scenario_id 
        WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        AND (
            period in (
            SELECT DISTINCT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            )
            OR period = 0 -- for all periods
            )
        """)

    var_om_by_tmp = get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        conn=conn,
        op_type="all",
        table="inputs_project_variable_om_cost_by_timepoint",
        subscenario_id_column="variable_om_cost_by_timepoint_scenario_id",
        data_column="variable_om_cost_by_timepoint",
        exclude_stage=True,
    )

    c5 = conn.cursor()
    fuels = c5.execute(
        """
        SELECT project, fuel, min_fraction_in_fuel_blend, max_fraction_in_fuel_blend
        FROM inputs_project_portfolios
        -- select the correct operational characteristics subscenario
        INNER JOIN
        (SELECT project, project_fuel_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {}
        ) AS op_char
        USING(project)
        -- select only heat curves of matching projects
        INNER JOIN
        inputs_project_fuels
        USING(project, project_fuel_scenario_id)
        -- Get only the subset of projects in the portfolio based on the 
        -- project_portfolio_scenario_id 
        WHERE project_portfolio_scenario_id = {}
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    c2 = conn.cursor()
    heat_rates = c2.execute(
        """
        SELECT project, period,
        load_point_fraction, average_heat_rate_mmbtu_per_mwh
        FROM inputs_project_portfolios
        -- select the correct operational characteristics subscenario
        INNER JOIN
        (SELECT project, heat_rate_curves_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {}
        ) AS op_char
        USING(project)
        -- select only heat curves of matching projects
        INNER JOIN
        inputs_project_heat_rate_curves
        USING(project, heat_rate_curves_scenario_id)
        -- Get only the subset of projects in the portfolio based on the 
        -- project_portfolio_scenario_id 
        WHERE project_portfolio_scenario_id = {}
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    c3 = conn.cursor()
    vom_curves = c3.execute(
        """
        SELECT project, period,  
        load_point_fraction, average_variable_om_cost_per_mwh
        FROM inputs_project_portfolios
        -- select the correct operational characteristics subscenario
        INNER JOIN
        (SELECT project, variable_om_curves_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {}
        ) AS op_char
        USING(project)
        -- select only variable OM curves inputs with matching projects
        INNER JOIN
        inputs_project_variable_om_curves
        USING(project, variable_om_curves_scenario_id)
        WHERE project_portfolio_scenario_id = {}
        -- Get only the subset of projects in the portfolio based on the 
        -- project_portfolio_scenario_id 
        AND variable_om_curves_scenario_id is not Null
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    c4 = conn.cursor()
    startup_chars = c4.execute(
        """
        SELECT project, 
        down_time_cutoff_hours, startup_plus_ramp_up_rate, startup_cost_per_mw
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, startup_chars_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {}
        ) AS op_char
        USING(project)
        INNER JOIN
        inputs_project_startup_chars
        USING(project, startup_chars_scenario_id)
        WHERE project_portfolio_scenario_id = {}
        AND startup_chars_scenario_id is not Null
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    c6 = conn.cursor()
    cycle_selection = c6.execute(
        """
        SELECT project, cycle_selection_project
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, cycle_selection_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {project_opchar_scenario_id}
        ) AS op_char
        USING (project)
        INNER JOIN
        inputs_project_cycle_selection
        USING(project, cycle_selection_scenario_id)
        WHERE project_portfolio_scenario_id = {project_portfolio_scenario_id}
        AND cycle_selection_scenario_id IS NOT NULL
        """.format(
            project_opchar_scenario_id=subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            project_portfolio_scenario_id=subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    c7 = conn.cursor()
    cap_factor_limits = c7.execute(
        """
        SELECT project, balancing_type_horizon, horizon, min_cap_factor, max_cap_factor
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, cap_factor_limits_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {project_opchar_scenario_id}
        ) AS op_char
        USING (project)
        INNER JOIN
        inputs_project_cap_factor_limits
        USING(project, cap_factor_limits_scenario_id)
        JOIN
        (SELECT balancing_type_horizon, horizon
        FROM inputs_temporal_horizons
        WHERE temporal_scenario_id = {temporal_scenario_id}) as relevant_horizons
        USING (balancing_type_horizon, horizon)
        WHERE project_portfolio_scenario_id = {project_portfolio_scenario_id}
        AND cap_factor_limits_scenario_id IS NOT NULL
        """.format(
            temporal_scenario_id=subscenarios.TEMPORAL_SCENARIO_ID,
            project_opchar_scenario_id=subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            project_portfolio_scenario_id=subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    c8 = conn.cursor()
    supplemental_firing = c8.execute(
        """
        SELECT project, supplemental_firing_project
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, supplemental_firing_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {project_opchar_scenario_id}
        ) AS op_char
        USING (project)
        INNER JOIN
        inputs_project_supplemental_firing
        USING(project, supplemental_firing_scenario_id)
        WHERE project_portfolio_scenario_id = {project_portfolio_scenario_id}
        AND supplemental_firing_scenario_id IS NOT NULL
        """.format(
            project_opchar_scenario_id=subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            project_portfolio_scenario_id=subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    curtailment_c = conn.cursor()
    curtailment_cost = curtailment_c.execute(f"""
        SELECT project, period, curtailment_cost_per_powerunithour
        FROM inputs_project_portfolios
        -- select the correct operational characteristics subscenario
        INNER JOIN
        (SELECT project, curtailment_cost_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
        ) AS op_char
        USING(project)
        -- select only matching projects
        INNER JOIN
        inputs_project_curtailment_cost
        USING (project, curtailment_cost_scenario_id)
        -- Get only the subset of projects in the portfolio based on the 
        -- project_portfolio_scenario_id 
        WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        AND ((
            period in (
            SELECT DISTINCT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            )
            AND period in (
                  SELECT DISTINCT period
                  FROM inputs_temporal
                  WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                  AND subproblem_id = {subproblem}
               )
            )
            OR period = 0 -- for all periods
            )
        """)

    n_startup_c = conn.cursor()
    n_startup_limits = n_startup_c.execute(f"""
        SELECT project, balancing_type_horizon, horizon, max_n_startups
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, n_startup_limit_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
        ) AS op_char
        USING (project)
        INNER JOIN
        inputs_project_n_startup_limits
        USING (project, n_startup_limit_scenario_id)
        JOIN
        (SELECT balancing_type_horizon, horizon
        FROM inputs_temporal_horizons
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND (balancing_type_horizon, horizon) in (
            SELECT DISTINCT balancing_type_horizon, horizon
            FROM inputs_temporal_horizon_timepoints
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
        )) as relevant_horizons
        USING (balancing_type_horizon, horizon)
        WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        AND n_startup_limit_scenario_id IS NOT NULL
        """)

    return (
        proj_opchar,
        var_om_by_prd,
        var_om_by_tmp,
        fuels,
        heat_rates,
        vom_curves,
        startup_chars,
        cycle_selection,
        cap_factor_limits,
        supplemental_firing,
        curtailment_cost,
        n_startup_limits,
    )


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
    Get inputs from database and write out the model inputs
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
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

    (
        proj_opchar,
        var_om_by_prd,
        var_om_by_tmp,
        fuels,
        heat_rate_curves,
        vom_curves,
        startup_chars,
        cycle_selection,
        cap_factor_limits,
        supplemental_firing,
        curtailment_cost,
        n_startup_limits,
    ) = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    inputs_directory = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
    )

    # Update the projects.tab file
    new_columns = [
        "variable_om_cost_per_mwh",
        "min_stable_level_fraction",
        "unit_size_mw",
        "startup_cost_per_mw",
        "shutdown_cost_per_mw",
        "startup_fuel_mmbtu_per_mw",
        "startup_plus_ramp_up_rate",
        "shutdown_plus_ramp_down_rate",
        "ramp_up_when_on_rate",
        "ramp_down_when_on_rate",
        "ramp_up_violation_penalty",
        "ramp_down_violation_penalty",
        "ramp_tuning_cost_per_mw",
        "min_up_time_hours",
        "min_up_time_violation_penalty",
        "min_down_time_hours",
        "min_down_time_violation_penalty",
        "allow_startup_shutdown_power",
        "storage_efficiency",
        "charging_efficiency",
        "discharging_efficiency",
        "charging_capacity_multiplier",
        "discharging_capacity_multiplier",
        "minimum_duration_hours",
        "maximum_duration_hours",
        "aux_consumption_frac_capacity",
        "aux_consumption_frac_power",
        "last_commitment_stage",
        "cap_factor_default",
        "powerunithour_per_fuelunit",
        "soc_penalty_cost_per_energyunit",
        "soc_last_tmp_penalty_cost_per_energyunit",
        "max_losses_in_hrz_frac_stor_energy_capacity",
        "partial_availability_threshold",
        "nonfuel_carbon_emissions_per_mwh",
        "powerhouse",
        "generator_efficiency",
        "linked_load_component",
        "efficiency_factor",
        "energy_requirement_factor",
        "losses_factor_in_energy_target",
        "losses_factor_curtailment",
        "upward_reserves_to_soc_depletion",
    ]

    append_to_input_file(
        inputs_directory=inputs_directory,
        input_file="projects.tab",
        query_results=proj_opchar,
        index_n_columns=1,
        new_column_names=new_columns,
    )

    # Write var cost by period file
    var_om_by_prd_df = cursor_to_df(var_om_by_prd)
    write_additional_opchar_file(
        opchar_df=var_om_by_prd_df,
        inputs_directory=inputs_directory,
        filename="project_variable_om_by_period.tab",
    )

    # Write var cost by tmp file
    var_om_by_tmp_df = cursor_to_df(var_om_by_tmp)
    write_additional_opchar_file(
        opchar_df=var_om_by_tmp_df,
        inputs_directory=inputs_directory,
        filename="project_variable_om_by_timepoint.tab",
    )

    # Write fuels file
    fuels_df = cursor_to_df(fuels)
    write_additional_opchar_file(
        opchar_df=fuels_df,
        inputs_directory=inputs_directory,
        filename="project_fuels.tab",
    )

    # Write heat rates file
    hr_df = cursor_to_df(heat_rate_curves)
    write_additional_opchar_file(
        opchar_df=hr_df,
        inputs_directory=inputs_directory,
        filename="heat_rate_curves.tab",
    )

    # Write VOM file
    vom_df = cursor_to_df(vom_curves)
    write_additional_opchar_file(
        opchar_df=vom_df,
        inputs_directory=inputs_directory,
        filename="variable_om_curves.tab",
    )

    # Write startup chars file
    su_df = cursor_to_df(startup_chars)
    write_additional_opchar_file(
        opchar_df=su_df, inputs_directory=inputs_directory, filename="startup_chars.tab"
    )

    # Write the cycle selection file
    cs_df = cursor_to_df(cycle_selection)
    write_additional_opchar_file(
        opchar_df=cs_df,
        inputs_directory=inputs_directory,
        filename="cycle_selection.tab",
    )

    # Write the cap_factor_limits file
    cfl_df = cursor_to_df(cap_factor_limits)
    write_additional_opchar_file(
        opchar_df=cfl_df,
        inputs_directory=inputs_directory,
        filename="cap_factor_limits.tab",
    )

    # Write the supplemental firing file
    sf_df = cursor_to_df(supplemental_firing)
    write_additional_opchar_file(
        opchar_df=sf_df,
        inputs_directory=inputs_directory,
        filename="supplemental_firing.tab",
    )

    # Write curtailment cost by period file
    curtailment_cost_df = cursor_to_df(curtailment_cost)
    write_additional_opchar_file(
        opchar_df=curtailment_cost_df,
        inputs_directory=inputs_directory,
        filename="project_curtailment_cost.tab",
    )

    # Startup limits
    startup_limits_df = cursor_to_df(n_startup_limits)
    write_additional_opchar_file(
        opchar_df=startup_limits_df,
        inputs_directory=inputs_directory,
        filename="startup_limits.tab",
    )


def import_results_into_database(
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    c,
    db,
    results_directory,
    quiet,
):
    """

    :param scenario_id:
    :param c:
    :param db:
    :param results_directory:
    :param quiet:
    :return:
    """
    import_csv(
        conn=db,
        cursor=c,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        quiet=quiet,
        results_directory=results_directory,
        which_results="project_timepoint",
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

    # Get the project input data
    (
        proj_opchar,
        var_om_by_prd,
        var_om_by_tmp,
        fuels,
        heat_rates,
        vom_curves,
        startup_chars,
        cycle_select,
        cap_factor_limits,
        supplemental_firing,
        curtailment_cost,
        n_startup_limits,
    ) = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    # Convert input data into DataFrame
    prj_df = cursor_to_df(proj_opchar)

    # Check data types operational chars:
    expected_dtypes = get_expected_dtypes(conn, ["inputs_project_operational_chars"])

    dtype_errors, error_columns = validate_dtypes(prj_df, expected_dtypes)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_operational_chars",
        severity="High",
        errors=dtype_errors,
    )

    # Check valid numeric columns are non-negative
    numeric_columns = [c for c in prj_df.columns if expected_dtypes[c] == "numeric"]
    valid_numeric_columns = set(numeric_columns) - set(error_columns)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_operational_chars",
        severity="High",
        errors=validate_values(prj_df, valid_numeric_columns, min=0),
    )

    # Check min_stable_level_fraction within (0, 1]
    if "min_stable_level_fraction" not in error_columns:
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_project_operational_chars",
            severity="Mid",
            errors=validate_values(
                prj_df, ["min_stable_level_fraction"], min=0, max=1, strict_min=True
            ),
        )

    # Convert input data into DataFrame
    hr_df = cursor_to_df(heat_rates)

    # Check data types heat_rates:
    expected_dtypes = get_expected_dtypes(conn, ["inputs_project_heat_rate_curves"])
    dtype_errors, error_columns = validate_dtypes(hr_df, expected_dtypes)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_heat_rate_curves",
        severity="High",
        errors=dtype_errors,
    )

    # Check valid numeric columns in heat rates are non-negative
    numeric_columns = [c for c in hr_df.columns if expected_dtypes[c] == "numeric"]
    valid_numeric_columns = set(numeric_columns) - set(error_columns)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_heat_rate_curves",
        severity="High",
        errors=validate_values(hr_df, valid_numeric_columns, min=0),
    )

    # TODO: make this work w new structure
    # Check for consistency between fuel and heat rate curve inputs:
    # Projects with fuel should have a heat rate scenario specified with
    # associated inputs in the hr curves table, and vice versa for projects
    # with no fuel.
    # fuel_mask = pd.notna(prj_df["fuel"])
    # prjs_w_fuel = prj_df["project"][fuel_mask]
    # prjs_wo_fuel = prj_df["project"][~fuel_mask]
    # prjs_w_hr = hr_df["project"].unique()  # prjs w hr inputs and matching hr id
    # write_validation_to_database(
    #     conn=conn,
    #     scenario_id=scenario_id,
    #     subproblem_id=subproblem,
    #     stage_id=stage,
    #     gridpath_module=__name__,
    #     db_table="inputs_project_operational_chars, inputs_project_heat_rate_curves",
    #     severity="High",
    #     errors=validate_idxs(actual_idxs=prjs_w_hr,
    #                          req_idxs=prjs_w_fuel,
    #                          invalid_idxs=prjs_wo_fuel,
    #                          msg="Projects with(out) fuel should (not) have "
    #                              "heat rate scenario specified, and should "
    #                              "(not) have inputs for that project-scenario "
    #                              "in the heat rate curves inputs table.")
    # )

    # Check that specified heat rate curves inputs are valid:
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_heat_rate_curves",
        severity="High",
        errors=validate_piecewise_curves(
            df=hr_df,
            x_col="load_point_fraction",
            slope_col="average_heat_rate_mmbtu_per_mwh",
            y_name="fuel burn",
        ),
    )

    # Validate VOM curves
    vom_df = cursor_to_df(vom_curves)

    # Check data types
    expected_dtypes = get_expected_dtypes(conn, ["inputs_project_variable_om_curves"])

    dtype_errors, error_columns = validate_dtypes(vom_df, expected_dtypes)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_variable_om_curves",
        severity="High",
        errors=dtype_errors,
    )

    # Check valid numeric columns in variable OM are non-negative
    numeric_columns = [c for c in vom_df.columns if expected_dtypes[c] == "numeric"]
    valid_numeric_columns = set(numeric_columns) - set(error_columns)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_variable_om_curves",
        severity="High",
        errors=validate_values(vom_df, valid_numeric_columns, min=0),
    )

    # Check that specified vom curves inputs are valid:
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_variable_om_curves",
        severity="High",
        errors=validate_piecewise_curves(
            df=vom_df,
            x_col="load_point_fraction",
            slope_col="average_variable_om_cost_per_mwh",
            y_name="variable O&M cost",
        ),
    )

    # Validate startup chars
    # Convert input data to DataFrame
    su_df = cursor_to_df(startup_chars)

    # Get the number of hours in the timepoint (take min if it varies)
    c = conn.cursor()
    tmp_durations = c.execute(
        """SELECT number_of_hours_in_timepoint
           FROM inputs_temporal
           WHERE temporal_scenario_id = {}
           AND subproblem_id = {}
           AND stage_id = {};""".format(
            subscenarios.TEMPORAL_SCENARIO_ID, subproblem, stage
        )
    ).fetchall()
    hrs_in_tmp = min(tmp_durations)

    # Check startup shutdown rate inputs
    # TODO: figure out why we need the df in the validation and refactor this
    cols = [
        "project",
        "variable_om_cost_per_mwh",
        "operational_type",
        "min_stable_level_fraction",
        "unit_size_mw",
        "startup_cost_per_mw",
        "shutdown_cost_per_mw",
        "startup_fuel_mmbtu_per_mw",
        "startup_plus_ramp_up_rate",
        "shutdown_plus_ramp_down_rate",
        "ramp_up_when_on_rate",
        "ramp_down_when_on_rate",
        "min_up_time_hours, min_down_time_hours",
        "storage_efficiency",
        "charging_efficiency",
        "discharging_efficiency",
        "charging_capacity_multiplier",
        "discharging_capacity_multiplier",
        "minimum_duration_hours",
        "maximum_duration_hours",
        "max_losses_in_hrz_frac_stor_energy_capacity",
        "aux_consumption_frac_capacity",
        "aux_consumption_frac_power",
        "cap_factor_default",
        "partial_availability_threshold",
        "nonfuel_carbon_emissions_per_mwh",
        "powerhouse",
        "generator_efficiency",
        "linked_load_component",
        "efficiency_factor",
        "energy_requirement_factor",
        "losses_factor_in_energy_target",
        "losses_factor_curtailment",
        "upward_reserves_to_soc_depletion",
    ]

    sql = """SELECT {}
        FROM inputs_project_portfolios
        INNER JOIN
        inputs_project_operational_chars
        USING (project)
        WHERE project_portfolio_scenario_id = {}
        AND project_operational_chars_scenario_id = {};
        """.format(
        ",".join(cols),
        subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
    )

    opchar_df = pd.read_sql(sql, conn)

    su_errors = validate_startup_shutdown_rate_inputs(opchar_df, su_df, hrs_in_tmp)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_operational_chars, inputs_project_startup_chars",
        severity="High",
        errors=su_errors,
    )

    # TODO: Check that specified vom scenarios actually have inputs in the vom
    #  table --> would need to get list of projects w vom curve scenario

    # TODO: check that if there is a "0" for the period for a given
    #  project there are zeroes everywhere for that project.

    # TODO: check that there is no overlap between simple and by-type
    #  startup cost


def get_slopes_intercept_by_project_period_segment(df, input_col, projects, periods):
    """
    Given a DataFrame with the average heat rates or variable O&M curves by
    load point fraction for each project in each period, calculate the slope
    and intercept for the fuel burn or variable O&M cost curves for the
    segments defined by the load points (for each project and period). If the
    period in the DataFrame is zero, set the same slope and intercept for each
    of the modeling periods.
    fractions.

    :param df: DataFrame with columns [project, period, load_point_fraction,
        input_col]
    :param input_col: string with the name of the column in the DataFrame that
        has the average heat rate or variable O&M rate.
    :param projects: list of all the projects to be included
    :param periods: set of all the modeling periods to  be included
    :return: (slope_dict, intercept_dict), with slope_dict and
        intercept_dict a dictionary of the fuel burn / variable O&M cost slope
        and intercept by (project, period, segment).

    """

    slope_dict = {}
    intercept_dict = {}

    for project in projects:
        df_slice = df[df["project"] == project]
        slice_periods = set(df_slice["period"])

        if slice_periods == {0}:
            p_iterable = [0]
        elif periods.issubset(slice_periods):
            p_iterable = periods
        else:
            raise ValueError("""{} for project '{}' isn't specified for all 
                modeled periods. Set period to 0 if inputs are the 
                same for each period or make sure all modelled periods 
                are included.""".format(input_col, project))

        for period in p_iterable:
            df_slice_p = df_slice[df_slice["period"] == period]
            df_slice_p = df_slice_p.sort_values(by=["load_point_fraction"])
            load_points = df_slice_p["load_point_fraction"].values
            averages = df_slice_p[input_col].values

            slopes, intercepts = calculate_slope_intercept(
                project, load_points, averages
            )
            sgms = range(len(slopes))

            # If period is 0, create same inputs for all periods
            if period == 0:
                slope_dict.update(
                    {
                        (project, p, sgms[i]): slope
                        for i, slope in enumerate(slopes)
                        for p in periods
                    }
                )
                intercept_dict.update(
                    {
                        (project, p, sgms[i]): intercept
                        for i, intercept in enumerate(intercepts)
                        for p in periods
                    }
                )
            # If not, create inputs for just this period
            else:
                slope_dict.update(
                    {
                        (project, period, sgms[i]): slope
                        for i, slope in enumerate(slopes)
                    }
                )
                intercept_dict.update(
                    {
                        (project, period, sgms[i]): intercept
                        for i, intercept in enumerate(intercepts)
                    }
                )

    return slope_dict, intercept_dict


def calculate_slope_intercept(project, load_points, heat_rates):
    """
    Calculates slope and intercept for a set of load points and corresponding
    average heat rates or variable O&M rates.
    Note that the intercept will be normalized to the
    operational capacity (Pmax) and the timepoint duration.
    :param project: the project name (for error messages)
    :param load_points: NumPy array with the loading points in fraction of Pmax
    :param heat_rates: NumPy array with the corresponding *average* heat rates
    in MMBtu per MWh or variable O&M in cost/MWh
    :return: slopes, intercepts: tuple with the array of slopes and intercepts
    for each segment. If more than one loading point, the array will have
    one less element than the amount of load points.

    """

    n_points = len(load_points)

    # Data checks
    assert len(load_points) == len(heat_rates)
    if np.any(load_points <= 0) or np.any(heat_rates <= 0):
        raise ValueError("""
            Load points and average heat rates should be positive
            numbers. Check heat rate curve inputs for project '{}'.
            """.format(project))
    if n_points == 0:
        raise ValueError("""
            Model requires at least one load point and one average
            heat rate input for each fuel project. It seems like
            there are no heat rate inputs for project '{}'.
            """.format(project))

    # if just one point, assume constant heat rate (no intercept)
    if n_points == 1:
        slopes = np.array([heat_rates[0]])
        intercepts = np.array([0])
    else:
        fuel_burn = load_points * heat_rates
        incr_loads = np.diff(load_points)
        incr_fuel_burn = np.diff(fuel_burn)
        slopes = incr_fuel_burn / incr_loads
        intercepts = fuel_burn[:-1] - slopes * load_points[:-1]

        # Data Checks
        if np.any(incr_loads <= 0):
            raise ValueError("""
                Load points in curve should be strictly
                increasing. Check curve inputs for project '{}'.
                """.format(project))
        if np.any(incr_fuel_burn <= 0):
            raise ValueError("""
                Total fuel burn or variable O&M cost should be strictly 
                increasing between load points. Check heat rate curve inputs
                for project '{}'.
                """.format(project))
        if np.any(np.diff(slopes) <= 0):
            raise ValueError("""
                The fuel burn or variable O&M cost as a function of power 
                output should be a convex function, i.e. the incremental 
                heat rate or variable O&M rate should
                be positive and strictly increasing. Check curve inputs for 
                project '{}'.
                """.format(project))

    return slopes, intercepts


def write_additional_opchar_file(opchar_df, inputs_directory, filename):
    """
    Write input tab file to the multi-dimensional operating characterstics from a
    dataframe.
    """
    if not opchar_df.empty:
        opchar_df = opchar_df.fillna(".")
        fpath = os.path.join(inputs_directory, filename)
        opchar_df.to_csv(fpath, index=False, sep="\t")
