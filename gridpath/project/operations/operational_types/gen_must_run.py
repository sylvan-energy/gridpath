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
This operational type describes must-run generators that produce constant
power equal to their capacity in all timepoints when they are available.

The available capacity can either be a set input (e.g. for the gen_spec
capacity_type) or a decision variable by period (e.g. for the gen_new_lin
capacity_type). This makes this operational type suitable for both production
simulation type problems and capacity expansion problems.

The heat rate is assumed to be constant and this operational type cannot
provide reserves (since there is no operable range, i.e. no headroom or
footroom).

Costs for this operational type include fuel costs and variable O&M costs.

"""

import csv
import os
import warnings
from pyomo.environ import (
    Constraint,
    Set,
    Param,
    NonNegativeReals,
    PositiveReals,
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
    get_projects_by_reserve,
    validate_idxs,
    validate_single_input,
)
from gridpath.auxiliary.dynamic_components import headroom_variables, footroom_variables
from gridpath.project.operations.reserves.reserve_aggregation import (
    headroom_provision_rule,
    footroom_provision_rule,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_optype_model_data,
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
    | | :code:`GEN_MUST_RUN`                                                  |
    |                                                                         |
    | The set of generators of the :code:`gen_must_run` operational type.     |
    +-------------------------------------------------------------------------+
    | | :code:`GEN_MUST_RUN_OPR_TMPS`                                         |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`gen_must_run`         |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`gen_must_run_aux_consumption_frac_capacity`                    |
    | | *Defined over*: :code:`GEN_MUST_RUN`                                  |
    | | *Within*: :code:`PercentFraction`                                     |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Auxiliary consumption as a fraction of capacity. This would be          |
    | incurred all timepoints when capacity is available.                     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`GenMustRun_No_Upward_Reserves_Constraint`                      |
    | | *Defined over*: :code:`GEN_MUST_RUN_OPR_TMPS`                         |
    |                                                                         |
    | Must-run projects cannot provide upward reserves.                       |
    +-------------------------------------------------------------------------+
    | | :code:`GenMustRun_No_Downward_Reserves_Constraint`                    |
    | | *Defined over*: :code:`GEN_MUST_RUN_OPR_TMPS`                         |
    |                                                                         |
    | Must-run projects cannot provide downward reserves.                     |
    +-------------------------------------------------------------------------+


    """

    # Sets
    ###########################################################################

    m.GEN_MUST_RUN = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "gen_must_run"
        ),
    )

    m.GEN_MUST_RUN_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.GEN_MUST_RUN
        ),
    )

    # Optional Params
    ###########################################################################

    m.gen_must_run_aux_consumption_frac_capacity = Param(
        m.GEN_MUST_RUN, within=PercentFraction, default=0
    )

    # Expressions
    ###########################################################################

    def auxiliary_consumption_rule(mod, g, tmp):
        """
        **Expression Name**: GenMustRun_Auxiliary_Consumption_MW
        **Defined Over**: GEN_MUST_RUN_OPR_TMPS
        """
        return (
            mod.Capacity_MW[g, mod.period[tmp]]
            * mod.Availability_Derate[g, tmp]
            * mod.gen_must_run_aux_consumption_frac_capacity[g]
        )

    m.GenMustRun_Auxiliary_Consumption_MW = Expression(
        m.GEN_MUST_RUN_OPR_TMPS, rule=auxiliary_consumption_rule
    )

    # Constraints
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

    m.GenMustRun_No_Upward_Reserves_Constraint = Constraint(
        m.GEN_MUST_RUN_OPR_TMPS, rule=no_upward_reserve_rule
    )

    # TODO: remove this constraint once input validation is in place that
    #  does not allow specifying a reserve_zone if 'gen_must_run' type
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

    m.GenMustRun_No_Downward_Reserves_Constraint = Constraint(
        m.GEN_MUST_RUN_OPR_TMPS, rule=no_downward_reserve_rule
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, g, tmp):
    """
    Power provision for must run generators is simply their capacity in all
    timepoints when they are operational minus any auxiliary power consumption.
    """
    return (
        mod.Capacity_MW[g, mod.period[tmp]] * mod.Availability_Derate[g, tmp]
        - mod.GenMustRun_Auxiliary_Consumption_MW[g, tmp]
    )


def fuel_burn_rule(mod, g, tmp):
    """ """
    return (
        mod.fuel_burn_slope_mmbtu_per_mwh[g, mod.period[tmp], 0]
        * mod.Capacity_MW[g, mod.period[tmp]]
        * mod.Availability_Derate[g, tmp]
    )


def power_delta_rule(mod, g, tmp):
    """ """
    return 0


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
        op_type="gen_must_run",
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
            value(mod.Capacity_MW[prj, mod.period[tmp]])
            * value(mod.Availability_Derate[prj, tmp]),
            value(mod.GenMustRun_Auxiliary_Consumption_MW[prj, tmp]),
        ]
        for (prj, tmp) in mod.GEN_MUST_RUN_OPR_TMPS
    ]

    optype_dispatch_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    return results_columns, optype_dispatch_df


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
    opchar_df = validate_opchars(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "gen_must_run",
    )

    # Other module specific validations

    c = conn.cursor()
    heat_rates = c.execute(
        """
        SELECT project, period, load_point_fraction
        FROM inputs_project_portfolios
        INNER JOIN
        (SELECT project, operational_type, heat_rate_curves_scenario_id
        FROM inputs_project_operational_chars
        WHERE project_operational_chars_scenario_id = {}
        AND operational_type = '{}') AS op_char
        USING(project)
        INNER JOIN
        (SELECT project, period, heat_rate_curves_scenario_id, load_point_fraction
        FROM inputs_project_heat_rate_curves) as heat_rates
        USING(project, heat_rate_curves_scenario_id)
        WHERE project_portfolio_scenario_id = {}
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            "gen_must_run",
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
        )
    )

    # Convert inputs to data frame
    hr_df = cursor_to_df(heat_rates)

    # Check that there is only one load point (constant heat rate)
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
        severity="Mid",
        errors=validate_single_input(
            df=hr_df,
            idx_col=["project", "period"],
            msg="gen_must_run can only have one load " "point (constant heat rate).",
        ),
    )

    # Check that the project does not show up in any of the
    # inputs_project_reserve_bas tables since gen_must_run can't provide any
    # reserves
    projects_by_reserve = get_projects_by_reserve(scenario_id, subscenarios, conn)
    for reserve, projects_w_ba in projects_by_reserve.items():
        if reserve == "inertia_reserves":
            continue
        table = "inputs_project_" + reserve + "_bas"
        reserve_errors = validate_idxs(
            actual_idxs=opchar_df["project"],
            invalid_idxs=projects_w_ba,
            msg="gen_must_run cannot provide {}.".format(reserve),
        )

        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table=table,
            severity="Mid",
            errors=reserve_errors,
        )
