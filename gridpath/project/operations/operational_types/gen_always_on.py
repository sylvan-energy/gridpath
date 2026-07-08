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
This module describes the operations of generation projects that that must
produce power in all timepoints they are available; unlike the must-run
generators, however, they can vary power output between a pre-specified
minimum stable level (greater than 0) and their available capacity.

The available capacity can either be a set input (e.g. for the gen_spec
capacity_type) or a decision variable by period (e.g. for the gen_new_lin
capacity_type). This makes this operational type suitable for both production
simulation type problems and capacity expansion problems.

The optimization makes the dispatch decisions in every timepoint. Heat rate
degradation below full load is considered. Always-on projects can be allowed to
provide upward and/or downward reserves, subject to the available headroom and
footroom. Ramp limits can be optionally specified.

Costs for this operational type include fuel costs and variable O&M costs.

"""

import csv
import os.path
from pyomo.environ import (
    Param,
    Set,
    Var,
    NonNegativeReals,
    PercentFraction,
    Constraint,
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
from gridpath.project.common_functions import (
    check_if_boundary_type_and_first_timepoint,
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
    | | :code:`GEN_ALWAYS_ON`                                                 |
    |                                                                         |
    | The set of generators of the :code:`gen_always_on` operational type.    |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_ALWAYS_ON_OPR_TMPS`                                        |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_always_on`        |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_ALWAYS_ON_LINKED_TMPS`                                     |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_always_on`        |
    | operational type and their linked timepoints.                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_always_on_unit_size_mw`                                    |
    | | *Defined over*: :code:`GEN_ALWAYS_ON`                                 |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The MW size of a unit in this project (projects of the                  |
    | :code:`gen_always_on` type can represent a fleet of similar units).     |
    +-------------------------------------------------------------------------+
    | | :code:`gen_always_on_min_stable_level_fraction`                       |
    | | *Defined over*: :code:`GEN_ALWAYS_ON`                                 |
    | | *Within*: :code:`PercentFraction`                                     |
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
    | | :code:`gen_always_on_ramp_up_when_on_rate`                            |
    | | *Defined over*: :code:`GEN_ALWAYS_ON`                                 |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's upward ramp rate limit during operations, defined as a    |
    | fraction of its capacity per minute.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_always_on_ramp_down_when_on_rate`                          |
    | | *Defined over*: :code:`GEN_ALWAYS_ON`                                 |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The project's downward ramp rate limit during operations, defined as a  |
    | fraction of its capacity per minute.                                    |
    +-------------------------------------------------------------------------+
    | | :code:`gen_always_on_aux_consumption_frac_capacity`                   |
    | | *Defined over*: :code:`GEN_ALWAYS_ON`                                 |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of capacity. This would be          |
    | incurred in all timepoints when capacity is available.                  |
    +-------------------------------------------------------------------------+
    | | :code:`gen_always_on_aux_consumption_frac_power`                      |
    | | *Defined over*: :code:`GEN_ALWAYS_ON`                                 |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of gross power output.              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Linked Input Params                                                     |
    +=========================================================================+
    | | :code:`gen_always_on_linked_power`                                    |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_LINKED_TMPS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's power provision in the linked timepoints.                 |
    +-------------------------------------------------------------------------+
    | | :code:`gen_always_on_linked_upwards_reserves`                         |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_LINKED_TMPS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's upward reserve provision in the linked timepoints.        |
    +-------------------------------------------------------------------------+
    | | :code:`gen_always_on_linked_downwards_reserves`                       |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_LINKED_TMPS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's downward reserve provision in the linked timepoints.      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenAlwaysOn_Gross_Power_MW`                                    |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_OPR_TMPS`                        |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Power provision in MW from this project in each timepoint in which the  |
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`GenAlwaysOn_Auxiliary_Consumption_MW`                          |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_OPR_TMPS`                        |
    |                                                                         |
    | The project's auxiliary consumption (power consumed on-site and not     |
    | sent to the grid) in each timepoint.                                    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Power                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenAlwaysOn_Max_Power_Constraint`                              |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_OPR_TMPS`                        |
    |                                                                         |
    | Limits the power plus upward reserves to the available capacity.        |
    +-------------------------------------------------------------------------+
    | | :code:`GenAlwaysOn_Min_Power_Constraint`                              |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_OPR_TMPS`                        |
    |                                                                         |
    | Power provision minus downward reserves should exceed the minimum       |
    | stable level for the project.                                           |
    +-------------------------------------------------------------------------+
    | Ramps                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenAlwaysOn_Ramp_Up_Constraint`                                |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_OPR_TMPS`                        |
    |                                                                         |
    | Limits the allowed project upward ramp based on the                     |
    | :code:`gen_always_on_ramp_up_when_on_rate`.                             |
    +-------------------------------------------------------------------------+
    | | :code:`GenAlwaysOn_Ramp_Down_Constraint`                              |
    | | *Defined over*: :code:`GEN_ALWAYS_ON_OPR_TMPS`                        |
    |                                                                         |
    | Limits the allowed project downward ramp based on the                   |
    | :code:`gen_always_on_ramp_down_when_on_rate`.                           |
    +-------------------------------------------------------------------------+


    """

    # Sets
    ###########################################################################
    m.GEN_ALWAYS_ON = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_always_on"
        ),
    )

    m.GEN_ALWAYS_ON_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.GEN_ALWAYS_ON
        ),
    )

    m.GEN_ALWAYS_ON_LINKED_TMPS = Set(dimen=2)

    # Required Params
    ###########################################################################

    m.gen_always_on_unit_size_mw = Param(m.GEN_ALWAYS_ON, within=NonNegativeReals)

    m.gen_always_on_min_stable_level_fraction = Param(
        m.GEN_ALWAYS_ON, within=PercentFraction
    )

    # Optional Params
    ###########################################################################

    m.gen_always_on_ramp_up_when_on_rate = Param(
        m.GEN_ALWAYS_ON, within=PercentFraction, default=1
    )

    m.gen_always_on_ramp_down_when_on_rate = Param(
        m.GEN_ALWAYS_ON, within=PercentFraction, default=1
    )

    m.gen_always_on_aux_consumption_frac_capacity = Param(
        m.GEN_ALWAYS_ON, within=PercentFraction, default=0
    )

    m.gen_always_on_aux_consumption_frac_power = Param(
        m.GEN_ALWAYS_ON, within=PercentFraction, default=0
    )

    # Linked Params
    ###########################################################################

    m.gen_always_on_linked_power = Param(
        m.GEN_ALWAYS_ON_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_always_on_linked_upwards_reserves = Param(
        m.GEN_ALWAYS_ON_LINKED_TMPS, within=NonNegativeReals
    )

    m.gen_always_on_linked_downwards_reserves = Param(
        m.GEN_ALWAYS_ON_LINKED_TMPS, within=NonNegativeReals
    )

    # Variables
    ###########################################################################

    m.GenAlwaysOn_Gross_Power_MW = Var(
        m.GEN_ALWAYS_ON_OPR_TMPS, within=NonNegativeReals
    )

    # Expressions
    ###########################################################################
    # TODO: the reserve rules are the same in all modules, so should be
    #  consolidated
    def upwards_reserve_rule(mod, g, tmp):
        return headroom_provision_rule(d, mod, g, tmp)

    m.GenAlwaysOn_Upwards_Reserves_MW = Expression(
        m.GEN_ALWAYS_ON_OPR_TMPS, rule=upwards_reserve_rule
    )

    def downwards_reserve_rule(mod, g, tmp):
        return footroom_provision_rule(d, mod, g, tmp)

    m.GenAlwaysOn_Downwards_Reserves_MW = Expression(
        m.GEN_ALWAYS_ON_OPR_TMPS, rule=downwards_reserve_rule
    )

    def auxiliary_consumption_rule(mod, g, tmp):
        """
        **Expression Name**: GenAlwaysOn_Auxiliary_Consumption_MW
        **Defined Over**: GEN_ALWAYS_ON_OPR_TMPS
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * mod.gen_always_on_aux_consumption_frac_capacity[g]
            + mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
            * mod.gen_always_on_aux_consumption_frac_power[g]
        )

    m.GenAlwaysOn_Auxiliary_Consumption_MW = Expression(
        m.GEN_ALWAYS_ON_OPR_TMPS, rule=auxiliary_consumption_rule
    )

    # Constraints
    ###########################################################################

    m.GenAlwaysOn_Min_Power_Constraint = Constraint(
        m.GEN_ALWAYS_ON_OPR_TMPS, rule=min_power_rule
    )

    m.GenAlwaysOn_Max_Power_Constraint = Constraint(
        m.GEN_ALWAYS_ON_OPR_TMPS, rule=max_power_rule
    )

    m.GenAlwaysOn_Ramp_Up_Constraint = Constraint(
        m.GEN_ALWAYS_ON_OPR_TMPS, rule=ramp_up_rule
    )

    m.GenAlwaysOn_Ramp_Down_Constraint = Constraint(
        m.GEN_ALWAYS_ON_OPR_TMPS, rule=ramp_down_rule
    )


# Constraint Formulation Rules
###############################################################################


# Power
def min_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenAlwaysOn_Min_Power_Constraint
    **Enforced Over**: GEN_ALWAYS_ON_OPR_TMPS

    Power minus downward services cannot be below a minimum stable level.
    """
    return (
        mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
        - mod.GenAlwaysOn_Downwards_Reserves_MW[g, tmp]
        >= mod.Capacity_MW[g, mod.period[tmp]]
        * mod.Availability_Derate[g, tmp]
        * mod.gen_always_on_min_stable_level_fraction[g]
    )


def max_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenAlwaysOn_Max_Power_Constraint
    **Enforced Over**: GEN_ALWAYS_ON_OPR_TMPS

    Power plus upward services cannot exceed capacity.
    """
    return (
        mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
        + mod.GenAlwaysOn_Upwards_Reserves_MW[g, tmp]
        <= mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
    )


# Ramps
def ramp_up_rule(mod, g, tmp):
    """
    **Constraint Name**: GenAlwaysOn_Ramp_Up_Constraint
    **Enforced Over**: GEN_ALWAYS_ON_OPR_TMPS

    Difference between power generation of consecutive timepoints, adjusted
    for reserve provision in current and previous timepoint, has to obey
    ramp up rate limits.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    bt = mod.balancing_type_project[g]
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=bt,
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=bt,
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_power = mod.gen_always_on_linked_power[g, 0]
            prev_tmp_downwards_reserves = mod.gen_always_on_linked_downwards_reserves[
                g, 0
            ]
        else:
            prev = mod.prev_tmp[tmp, bt]
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[prev]
            prev_tmp_power = mod.GenAlwaysOn_Gross_Power_MW[g, prev]
            prev_tmp_downwards_reserves = mod.GenAlwaysOn_Downwards_Reserves_MW[g, prev]

        # If ramp rate limits, adjusted for timepoint duration, allow you to
        # ramp up the full operable range between timepoints, constraint won't
        # bind, so skip
        if mod.gen_always_on_ramp_up_when_on_rate[g] * 60 * prev_tmp_hrs_in_tmp >= (
            1 - mod.gen_always_on_min_stable_level_fraction[g]
        ):
            return Constraint.Skip
        else:
            return (
                mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
                + mod.GenAlwaysOn_Upwards_Reserves_MW[g, tmp]
                - (prev_tmp_power - prev_tmp_downwards_reserves)
                <= mod.gen_always_on_ramp_up_when_on_rate[g]
                * 60
                * prev_tmp_hrs_in_tmp
                * mod.Capacity_MW[g, mod.period[tmp]]
                * mod.Availability_Derate[g, tmp]
            )


def ramp_down_rule(mod, g, tmp):
    """
    **Constraint Name**: GenAlwaysOn_Ramp_Down_Constraint
    **Enforced Over**: GEN_ALWAYS_ON_OPR_TMPS

    Difference between power generation of consecutive timepoints, adjusted
    for reserve provision in current and previous timepoint, has to obey
    ramp down rate limits.

    We assume that a unit has to reach its setpoint at the start of the
    timepoint; as such, the ramping between 2 timepoints is assumed to
    take place during the duration of the first timepoint, and the
    ramp rate limit is adjusted for the duration of the first timepoint.
    """
    bt = mod.balancing_type_project[g]
    if check_if_boundary_type_and_first_timepoint(
        mod=mod,
        tmp=tmp,
        balancing_type=bt,
        boundary_type="linear",
    ):
        return Constraint.Skip
    else:
        if check_if_boundary_type_and_first_timepoint(
            mod=mod,
            tmp=tmp,
            balancing_type=bt,
            boundary_type="linked",
        ):
            prev_tmp_hrs_in_tmp = mod.hrs_in_linked_tmp[0]
            prev_tmp_power = mod.gen_always_on_linked_power[g, 0]
            prev_tmp_upwards_reserves = mod.gen_always_on_linked_upwards_reserves[g, 0]
        else:
            prev = mod.prev_tmp[tmp, bt]
            prev_tmp_hrs_in_tmp = mod.hrs_in_tmp[prev]
            prev_tmp_power = mod.GenAlwaysOn_Gross_Power_MW[g, prev]
            prev_tmp_upwards_reserves = mod.GenAlwaysOn_Upwards_Reserves_MW[g, prev]

        # If ramp rate limits, adjusted for timepoint duration, allow you to
        # ramp down the full operable range between timepoints, constraint
        # won't bind, so skip
        if mod.gen_always_on_ramp_down_when_on_rate[g] * 60 * prev_tmp_hrs_in_tmp >= (
            1 - mod.gen_always_on_min_stable_level_fraction[g]
        ):
            return Constraint.Skip
        else:
            return (
                mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
                - mod.GenAlwaysOn_Downwards_Reserves_MW[g, tmp]
                - (prev_tmp_power + prev_tmp_upwards_reserves)
                >= -mod.gen_always_on_ramp_down_when_on_rate[g]
                * 60
                * prev_tmp_hrs_in_tmp
                * mod.Capacity_MW[g, mod.period[tmp]]
                * mod.Availability_Derate[g, tmp]
            )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp):
    """
    Power provision for always-on generators is a variable constrained to be
    between the generator's minimum stable level and its capacity.
    """
    return (
        mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
        - mod.GenAlwaysOn_Auxiliary_Consumption_MW[g, tmp]
    )


def fuel_burn_by_ll_rule(mod, g, tmp, s):
    """ """
    return (
        mod.fuel_burn_slope_mmbtu_per_mwh[g, mod.period[tmp], s]
        * mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
        + mod.fuel_burn_intercept_mmbtu_per_mw_hr[g, mod.period[tmp], s]
        * mod.Availability_Derate[g, tmp]
        * mod.Capacity_MW[g, mod.period[tmp]]
    )


def variable_om_cost_by_ll_rule(mod, g, tmp, s):
    """
    Variable O&M cost has two components which are additive:
    1. A fixed variable O&M rate (cost/MWh) that doesn't change with loading
       levels: :code:`gen_always_on_variable_om_cost_per_mwh`.
    2. A variable variable O&M rate that changes with the loading level,
       similar to the heat rates. The idea is to represent higher variable cost
       rates at lower loading levels. This is captured in the
       :code:`GenAlwaysOn_Variable_OM_Cost_By_LL` decision variable. If no
       varxiable O&M curve inputs are provided, this component will be zero.

    Most users will only use the first component, which is specified in the
    operational characteristics table.  Only operational types with
    commitment decisions can have the second component.
    """
    return (
        mod.vom_slope_cost_per_mwh[g, mod.period[tmp], s]
        * mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
        + mod.vom_intercept_cost_per_mw_hr[g, mod.period[tmp], s]
        * mod.Availability_Derate[g, tmp]
        * mod.Capacity_MW[g, mod.period[tmp]]
    )


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
        return (
            mod.GenAlwaysOn_Gross_Power_MW[g, tmp]
            - mod.GenAlwaysOn_Gross_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        )


def capacity_providing_inertia_rule(mod, g, tmp):
    """
    Capacity providing inertia for GEN_MUST_RUN project is equal to the online
    capacity
    """
    return mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]


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
        op_type="gen_always_on",
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
        "gen_always_on_linked_timepoint_params.tab",
    )
    if os.path.exists(linked_inputs_filename):
        data_portal.load(
            filename=linked_inputs_filename,
            index=mod.GEN_ALWAYS_ON_LINKED_TMPS,
            param=(
                mod.gen_always_on_linked_power,
                mod.gen_always_on_linked_upwards_reserves,
                mod.gen_always_on_linked_downwards_reserves,
            ),
        )


def add_to_prj_tmp_results(mod):
    results_columns = [
        "gross_power_mw",
        "auxiliary_consumption_mw",
    ]
    data = [
        [
            prj,
            tmp,
            value(mod.GenAlwaysOn_Gross_Power_MW[prj, tmp]),
            value(mod.GenAlwaysOn_Auxiliary_Consumption_MW[prj, tmp]),
        ]
        for (prj, tmp) in mod.GEN_ALWAYS_ON_OPR_TMPS
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
                "gen_always_on_linked_timepoint_params.tab",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(
                [
                    "project",
                    "linked_timepoint",
                    "linked_provide_power",
                    "linked_upward_reserves",
                    "linked_downward_reserves",
                ]
            )
            for p, tmp in sorted(mod.GEN_ALWAYS_ON_OPR_TMPS):
                if tmp in tmps_to_link:
                    writer.writerow(
                        [
                            p,
                            tmp_linked_tmp_dict[tmp],
                            max(value(mod.GenAlwaysOn_Gross_Power_MW[p, tmp]), 0),
                            max(value(mod.GenAlwaysOn_Upwards_Reserves_MW[p, tmp]), 0),
                            max(
                                value(mod.GenAlwaysOn_Downwards_Reserves_MW[p, tmp]), 0
                            ),
                        ]
                    )


# Database
###############################################################################


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
        "gen_always_on",
    )
