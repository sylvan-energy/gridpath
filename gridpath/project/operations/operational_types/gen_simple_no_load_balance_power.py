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
This operational type describes generators that can vary their output
between zero and full capacity in every timepoint in which they are available
(i.e. they have a power output variable but no commitment variables associated
with them). However, this power does not count toward the load balance
constraint, but may be used in other constraints such as policy requirements.
IMPORTANT: this is available ot be used with the generic policy package only,
not with the older policy packages.

Costs for this operational type include variable O&M costs.

"""

import csv
import os
import warnings

from pyomo.environ import (
    Set,
    Var,
    Constraint,
    NonNegativeReals,
    Param,
    PercentFraction,
    Expression,
    value,
)

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    cursor_to_df,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_single_input,
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
    | | :code:`GEN_SIMPLE_NO_LOAD_BALANCE_POWER`                              |
    |                                                                         |
    | The set of generators of the :code:`gen_simple_no_load_balance_power`   |
    |operational type.                                                        |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS`                     |
    |                                                                         |
    | Two-dimensional set with generators of the                              |
    | :code:`gen_simple_no_load_balance_power` operational type and their     |
    | operational timepoints.                                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`GenSimpleNoLoadBalancePower_Provide_Power_MW`                  |
    | | *Defined over*: :code:`GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS`     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Power provision in MW from this project in each timepoint in which the  |
    | project is operational (capacity exists and the project is available).  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Power                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`GenSimpleNoLoadBalancePower_Max_Power_Constraint`              |
    | | *Defined over*: :code:`GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS`     |
    |                                                                         |
    | Limits the power plus upward reserves to the available capacity.        |
    +-------------------------------------------------------------------------+
    | | :code:`GenSimpleNoLoadBalancePower_Min_Power_Constraint`              |
    | | *Defined over*: :code:`GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS`     |
    |                                                                         |
    | Power provision minus downward reserves should exceed the minimum       |
    | stable level for the project.                                           |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.GEN_SIMPLE_NO_LOAD_BALANCE_POWER = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_simple_no_load_balance_power"
        ),
    )

    m.GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.GEN_SIMPLE_NO_LOAD_BALANCE_POWER,
        ),
    )

    # Variables
    ###########################################################################

    m.GenSimpleNoLoadBalancePower_Provide_Power_MW = Var(
        m.GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS, within=NonNegativeReals
    )

    # Expressions
    ###########################################################################

    # TODO: remove this constraint once input validation is in place that
    #  does not allow specifying a reserve_zone if 'gen_must_run' type
    def no_upward_reserve_rule(mod, g, tmp):
        """
        **Constraint Name**: GenMustRun_No_Upward_Reserves_Constraint
        **Enforced Over**: GEN_MUST_RUN_OPR_TMPS

        Upward reserves should be zero in every operational timepoint.
        """
        if getattr(d, headroom_variables)[g]:
            warnings.warn("""project {} is of the 'gen_must_run' operational type and 
                should not be assigned any upward reserve BAs since it cannot 
                provide upward reserves. Please replace the upward reserve BA 
                for project {} with '.' (no value) in projects.tab. Model will 
                add constraint to ensure project {} cannot provide upward 
                reserves.
                """.format(g, g, g))
            return headroom_provision_rule(d, mod, g, tmp) == 0
        else:
            return Constraint.Skip

    m.GenSimpleNoLoadBalancePower_No_Upward_Reserves_Constraint = Constraint(
        m.GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS, rule=no_upward_reserve_rule
    )

    def no_downward_reserve_rule(mod, g, tmp):
        """
        **Constraint Name**: GenMustRun_No_Downward_Reserves_Constraint
        **Enforced Over**: GEN_MUST_RUN_OPR_TMPS

        Downward reserves should be zero in every operational timepoint.
        """
        if getattr(d, footroom_variables)[g]:
            warnings.warn("""project {} is of the 'gen_must_run' operational type and 
                should not be assigned any downward reserve BAs since it cannot
                provide upwards reserves. Please replace the downward reserve 
                BA for project {} with '.' (no value) in projects.tab. Model 
                will add constraint to ensure project {} cannot provide 
                downward reserves.
                """.format(g, g, g))
            return footroom_provision_rule(d, mod, g, tmp) == 0
        else:
            return Constraint.Skip

    m.GenSimpleNoLoadBalancePower_No_Downward_Reserves_Constraint = Constraint(
        m.GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS, rule=no_downward_reserve_rule
    )

    # Constraints
    ###########################################################################

    m.GenSimpleNoLoadBalancePower_Max_Power_Constraint = Constraint(
        m.GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS, rule=max_power_rule
    )


# Constraint Formulation Rules
###############################################################################


# Power
def max_power_rule(mod, g, tmp):
    """
    **Constraint Name**: GenSimpleNoLoadBalancePower_Max_Power_Constraint
    **Enforced Over**: GEN_SIMPLE_NO_LOAD_BALANCE_POWER_OPR_TMPS

    Power plus upward services cannot exceed capacity.
    """
    return (
        mod.GenSimpleNoLoadBalancePower_Provide_Power_MW[g, tmp]
        <= mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp):
    """
    Power does not count toward load balance.
    """
    return 0


def policy_power_provision_rule(mod, prj, policy_zone, policy, tmp):
    """
    Power does count toward generic policy. NOTE: this is only implemented in
    policy package, not in old RPS packages, etc.
    """
    return mod.GenSimpleNoLoadBalancePower_Provide_Power_MW[prj, tmp]


def variable_om_cost_rule(mod, g, tmp):
    """
    Variable cost is incurred on all power produced (including what's
    curtailed).
    """
    return (
        mod.GenSimpleNoLoadBalancePower_Provide_Power_MW[g, tmp]
        * mod.variable_om_cost_per_mwh[g]
    )


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.GenSimpleNoLoadBalancePower_Provide_Power_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """ """
    return (
        mod.GenSimpleNoLoadBalancePower_Provide_Power_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
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
            mod.GenSimpleNoLoadBalancePower_Provide_Power_MW[g, tmp]
            - mod.GenSimpleNoLoadBalancePower_Provide_Power_MW[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
        )


def capacity_providing_inertia_rule(mod, g, tmp):
    """
    Capacity providing inertia for GEN_MUST_RUN project is equal to the online
    capacity (this assumes that the amount of capacity that is operated is
    proportional to power output)
    """
    return mod.GenSimpleNoLoadBalancePower_Provide_Power_MW[g, tmp]


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

    projects = load_optype_model_data(
        mod=mod,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="gen_simple_no_load_balance_power",
    )
