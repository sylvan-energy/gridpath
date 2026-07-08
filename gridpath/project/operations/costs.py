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
The **gridpath.project.operations.costs** module is a project-level
module that adds to the formulation components that describe the
operations-related costs of projects (e.g. variable O&M costs, fuel costs,
startup and shutdown costs).

For the purpose, this module calls the respective method from the
operational type modules.
"""

from pyomo.environ import Set, Var, Expression, Constraint, NonNegativeReals, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import (
    get_required_subtype_modules,
    subset_init_by_set_membership,
)
from gridpath.project.operations.common_functions import (
    load_operational_type_modules,
)
from gridpath.common_functions import create_results_df
import gridpath.project.operations.operational_types as op_type_init
from gridpath.project import PROJECT_TIMEPOINT_DF


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
    | | :code:`VAR_OM_COST_SIMPLE_PRJ_OPR_TMPS`                               |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | The two-dimensional set of projects for which a simple variable O&M     |
    | cost is specified and their operational timepoints.                     |
    +-------------------------------------------------------------------------+
    | | :code:`VAR_OM_COST_CURVE_PRJS_OPR_TMPS_SGMS`                          |
    |                                                                         |
    | The three-dimensional set of projects for which a VOM cost curve is     |
    | specified along with the VOM curve segments and the project             |
    | operational timepoints.                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`VAR_OM_COST_CURVE_PRJS_OPR_TMPS`                               |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | The two-dimensional set of projects for which a VOM cost curve is       |
    | specified along with their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`VAR_OM_COST_ALL_PRJS_OPR_TMPS`                                 |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | The two-dimensional set of projects for which either or both a simple   |
    | VOM or a VOM curve is specified along with their operational            |
    | timepoints.                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`STARTUP_COST_PRJ_OPR_TMPS`                                     |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | The two-dimensional set of projects for which a startup cost is         |
    | specified along with their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`SHUTDOWN_COST_PRJ_OPR_TMPS`                                    |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | The two-dimensional set of projects for which a shutdown cost curve is  |
    | specified along with their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`VIOL_ALL_PRJ_OPR_TMPS`                                         |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | The two-dimensional set of projects for which an operational constraint |
    | can be violated along with their operational timepoints.                |
    +-------------------------------------------------------------------------+
    | | :code:`CURTAILMENT_COST_PRJ_OPR_TMPS`                                 |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | The two-dimensional set of projects for which an curtailment costs are  |
    | incurred along with their operational timepoints.                       |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Variable_OM_Curve_Cost`                                        |
    | | *Defined over*: :code:`VAR_OM_COST_CURVE_PRJS_OPR_TMPS`               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Variable cost in each operational timepoint of projects with a VOM cost |
    | curve.                                                                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Variable_OM_Curve_Constraint`                                  |
    | | *Defined over*: :code:`VAR_OM_COST_CURVE_PRJS_OPR_TMPS_SGMS`          |
    |                                                                         |
    | Determines variable cost from the project in each timepoint based on    |
    | its VOM curve.                                                          |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Variable_OM_Cost`                                              |
    | | *Defined over*: :code:`VAR_OM_COST_ALL_PRJS_OPR_TMPS`                 |
    |                                                                         |
    | This is the variable cost incurred in each operational timepoints for   |
    | projects for which either a simple VOM or a VOM curve is specified.     |
    | If both are specified, the two are additive. We obtain the simple VOM   |
    | by calling the *variable_om_cost_rule* method of a project's            |
    | *operational_type* module. We obtain the VOM curve cost by calling the  |
    | *variable_om_cost_by_ll_rule* method of a project's operational type,   |
    | using that to create the *Variable_OM_Curve_Constraint* on the          |
    | Variable_OM_Curve_Cost variable, and the using the variable in this     |
    | expression.                                                             |
    +-------------------------------------------------------------------------+
    | | :code:`Fuel_Cost`                                                     |
    | | *Defined over*: :code:`FUEL_PRJ_OPR_TMPS`                             |
    |                                                                         |
    | This expression defines the fuel cost of a project in all of its        |
    | operational timepoints by summing across fuel burn by fuel times each   |
    | fuel's price.                                                           |
    +-------------------------------------------------------------------------+
    | | :code:`Startup_Cost`                                                  |
    | | *Defined over*: :code:`STARTUP_COST_PRJ_OPR_TMPS`                     |
    |                                                                         |
    | This expression defines the startup cost of a project in all of its     |
    | operational timepoints. We obtain the expression by calling the         |
    | *startup_cost_rule* method of a project's *operational_type* module.    |
    +-------------------------------------------------------------------------+
    | | :code:`Shutdown_Cost`                                                 |
    | | *Defined over*: :code:`SHUTDOWN_COST_PRJ_OPR_TMPS`                    |
    |                                                                         |
    | This expression defines the shutdown cost of a project in all of its    |
    | operational timepoints. We obtain the expression by calling the         |
    | *shutdown_cost_rule* method of a project's *operational_type* module.   |
    +-------------------------------------------------------------------------+
    | | :code:`Operational_Violation_Cost`                                    |
    | | *Defined over*: :code:`VIOL_ALL_PRJ_OPR_TMPS`                         |
    |                                                                         |
    | This expression defines the operational constraint violation cost of a  |
    | project in all of its operational timepoints. We obtain the expression  |
    | by calling the *operational_violation_cost_rule* method of a project's  |
    | *operational_type* module.                                              |
    +-------------------------------------------------------------------------+
    | | :code:`Curtailment_Cost`                                              |
    | | *Defined over*: :code:`CURTAILMENT_COST_PRJ_OPR_TMPS`                 |
    |                                                                         |
    | This expression defines the curtailment cost of a project in all of its |
    | operational timepoints. We obtain the expression by calling the         |
    | *curtailment_cost_rule* method of a project's *operational_type* module.|
    +-------------------------------------------------------------------------+

    """

    # Dynamic Inputs
    ###########################################################################

    required_operational_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="operational_type",
    )

    imported_operational_modules = load_operational_type_modules(
        required_operational_modules
    )

    # Sets
    ###########################################################################

    m.VAR_OM_COST_SIMPLE_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.VAR_OM_COST_SIMPLE_PRJS,
        ),
    )

    m.VAR_OM_COST_BY_PRD_PRJS_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.VAR_OM_COST_BY_PRD_PRJS,
        ),
    )

    m.VAR_OM_COST_BY_TMP_PRJS_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.VAR_OM_COST_BY_TMP_PRJS,
        ),
    )

    m.VAR_OM_COST_CURVE_PRJS_OPR_TMPS_SGMS = Set(
        dimen=3,
        initialize=lambda mod: sorted(
            list(
                set(
                    (g, tmp, s)
                    for (g, tmp) in mod.PRJ_OPR_TMPS
                    for _g, p, s in mod.VAR_OM_COST_CURVE_PRJS_PRDS_SGMS
                    if g == _g and mod.period[tmp] == p
                )
            ),
        ),
    )

    m.VAR_OM_COST_CURVE_PRJS_OPR_TMPS = Set(
        dimen=2,
        within=m.PRJ_OPR_TMPS,
        initialize=lambda mod: sorted(
            list(
                set(
                    (g, tmp) for (g, tmp, s) in mod.VAR_OM_COST_CURVE_PRJS_OPR_TMPS_SGMS
                )
            ),
        ),
    )

    # All VOM projects
    m.VAR_OM_COST_ALL_PRJS_OPR_TMPS = Set(
        within=m.PRJ_OPR_TMPS,
        initialize=lambda mod: sorted(
            list(
                set(
                    mod.VAR_OM_COST_SIMPLE_PRJ_OPR_TMPS
                    | mod.VAR_OM_COST_BY_PRD_PRJS_OPR_TMPS
                    | mod.VAR_OM_COST_BY_TMP_PRJS_OPR_TMPS
                    | mod.VAR_OM_COST_CURVE_PRJS_OPR_TMPS
                )
            ),
        ),
    )

    m.STARTUP_COST_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.STARTUP_COST_PRJS,
        ),
    )

    m.SHUTDOWN_COST_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.SHUTDOWN_COST_PRJS,
        ),
    )

    m.VIOL_ALL_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="PRJ_OPR_TMPS", index=0, membership_set=mod.VIOL_ALL_PRJS
        ),
    )

    m.CURTAILMENT_COST_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.CURTAILMENT_COST_PRJS,
        ),
    )

    m.SOC_PENALTY_COST_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.SOC_PENALTY_COST_PRJS,
        ),
    )

    m.SOC_LAST_TMP_PENALTY_COST_PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.SOC_LAST_TMP_PENALTY_COST_PRJS,
        ),
    )

    # Variables
    ###########################################################################

    m.Variable_OM_Curve_Cost = Var(
        m.VAR_OM_COST_CURVE_PRJS_OPR_TMPS, within=NonNegativeReals
    )

    # Constraints
    ###########################################################################

    def variable_om_cost_curve_constraint_rule(mod, prj, tmp, s):
        """
        **Constraint Name**: GenCommitBin_Variable_OM_Constraint
        **Enforced Over**: GEN_COMMIT_BIN_VOM_PRJS_OPR_TMPS_SGMS

        Variable O&M cost by loading level is set by piecewise linear
        representation of the input/output curve (variable O&M cost vs.loading
        level).

        Note: we assume that when projects are derated for availability, the
        input/output curve is derated by the same amount. The implicit
        assumption is that when a generator is de-rated, some of its units
        are out rather than it being forced to run below minimum stable level
        at very costly operating points.
        """
        op_type = mod.operational_type[prj]
        if hasattr(
            imported_operational_modules[op_type], "variable_om_cost_by_ll_rule"
        ):
            var_cost_by_ll = imported_operational_modules[
                op_type
            ].variable_om_cost_by_ll_rule(mod, prj, tmp, s)
        else:
            var_cost_by_ll = op_type_init.variable_om_cost_by_ll_rule(mod, prj, tmp, s)

        return mod.Variable_OM_Curve_Cost[prj, tmp] >= var_cost_by_ll

    m.Variable_OM_Curve_Constraint = Constraint(
        m.VAR_OM_COST_CURVE_PRJS_OPR_TMPS_SGMS,
        rule=variable_om_cost_curve_constraint_rule,
    )

    # Expressions
    ###########################################################################

    def variable_om_cost_rule(mod, prj, tmp):
        """
        **Expression Name**: Variable_OM_Cost
        **Defined Over**: VAR_OM_COST_ALL_PRJS_OPR_TMPS

        This is the variable cost incurred in each operational timepoints for
        projects for which a simple VOM, a by-period VOM, or a VOM curve is
        specified.
        The three components are additive.
        """
        op_type = mod.operational_type[prj]

        # Simple VOM cost
        if prj in mod.VAR_OM_COST_SIMPLE_PRJS:
            if hasattr(imported_operational_modules[op_type], "variable_om_cost_rule"):
                var_cost_simple = imported_operational_modules[
                    op_type
                ].variable_om_cost_rule(mod, prj, tmp)
            else:
                var_cost_simple = op_type_init.variable_om_cost_rule(mod, prj, tmp)
        else:
            var_cost_simple = 0

        # By period VOM
        if prj in mod.VAR_OM_COST_BY_PRD_PRJS:
            if hasattr(
                imported_operational_modules[op_type], "variable_om_by_period_cost_rule"
            ):
                var_cost_by_prd = imported_operational_modules[
                    op_type
                ].variable_om_by_period_cost_rule(mod, prj, tmp)
            else:
                var_cost_by_prd = op_type_init.variable_om_by_period_cost_rule(
                    mod, prj, tmp
                )
        else:
            var_cost_by_prd = 0

        # By timepoint VOM
        if prj in mod.VAR_OM_COST_BY_TMP_PRJS:
            if hasattr(
                imported_operational_modules[op_type],
                "variable_om_by_timepoint_cost_rule",
            ):
                var_cost_by_tmp = imported_operational_modules[
                    op_type
                ].variable_om_by_timepoint_cost_rule(mod, prj, tmp)
            else:
                var_cost_by_tmp = op_type_init.variable_om_by_timepoint_cost_rule(
                    mod, prj, tmp
                )
        else:
            var_cost_by_tmp = 0

        # VOM curve cost
        if prj in mod.VAR_OM_COST_CURVE_PRJS:
            var_cost_curve = mod.Variable_OM_Curve_Cost[prj, tmp]
        else:
            var_cost_curve = 0

        # The three are additive
        return var_cost_simple + var_cost_by_prd + var_cost_by_tmp + var_cost_curve

    m.Variable_OM_Cost = Expression(
        m.VAR_OM_COST_ALL_PRJS_OPR_TMPS, rule=variable_om_cost_rule
    )

    def fuel_cost_rule(mod, prj, tmp):
        """
        **Expression Name**: Fuel_Cost
        **Defined Over**: FUEL_PRJS_OPR_TMPS

        Fuel cost based on fuels burn and each fuel's price (sum over fuels).
        """
        return sum(
            (
                mod.Total_Fuel_Burn_by_Fuel_MMBtu[prj, f, tmp]
                - mod.Project_Fuel_Contribution_by_Fuel[prj, f, tmp]
            )
            * mod.fuel_price_per_mmbtu[f, mod.period[tmp], mod.month[tmp]]
            for f in mod.FUELS_BY_PRJ[prj]
        )

    m.Fuel_Cost = Expression(m.FUEL_PRJ_OPR_TMPS, rule=fuel_cost_rule)

    def startup_cost_rule(mod, prj, tmp):
        """
        Startup costs are defined for some operational types while they are
        zero for others. Get the appropriate expression for each generator
        based on its operational type.
        """
        op_type = mod.operational_type[prj]

        if prj in mod.STARTUP_COST_SIMPLE_PRJS:
            if hasattr(
                imported_operational_modules[op_type], "startup_cost_simple_rule"
            ):
                startup_cost_simple = imported_operational_modules[
                    op_type
                ].startup_cost_simple_rule(mod, prj, tmp)
            else:
                startup_cost_simple = op_type_init.startup_cost_simple_rule(
                    mod, prj, tmp
                )
        else:
            startup_cost_simple = 0

        if prj in mod.STARTUP_BY_ST_PRJS:
            if hasattr(
                imported_operational_modules[op_type], "startup_cost_by_st_rule"
            ):
                startup_cost_by_st = imported_operational_modules[
                    op_type
                ].startup_cost_by_st_rule(mod, prj, tmp)
            else:
                startup_cost_by_st = op_type_init.startup_cost_by_st_rule(mod, prj, tmp)
        else:
            startup_cost_by_st = 0

        return startup_cost_simple + startup_cost_by_st

    m.Startup_Cost = Expression(m.STARTUP_COST_PRJ_OPR_TMPS, rule=startup_cost_rule)

    def shutdown_cost_rule(mod, prj, tmp):
        """
        Shutdown costs are defined for some operational types while they are
        zero for others. Get the appropriate expression for each generator
        based on its operational type.
        """
        op_type = mod.operational_type[prj]
        if hasattr(imported_operational_modules[op_type], "shutdown_cost_rule"):
            return imported_operational_modules[op_type].shutdown_cost_rule(
                mod, prj, tmp
            )
        else:
            return op_type_init.shutdown_cost_rule(mod, prj, tmp)

    m.Shutdown_Cost = Expression(m.SHUTDOWN_COST_PRJ_OPR_TMPS, rule=shutdown_cost_rule)

    def operational_violation_cost_rule(mod, prj, tmp):
        """
        Get any operational constraint violation costs.
        """
        op_type = mod.operational_type[prj]
        if hasattr(
            imported_operational_modules[op_type], "operational_violation_cost_rule"
        ):
            return imported_operational_modules[
                op_type
            ].operational_violation_cost_rule(mod, prj, tmp)
        else:
            return op_type_init.operational_violation_cost_rule(mod, prj, tmp)

    m.Operational_Violation_Cost = Expression(
        m.VIOL_ALL_PRJ_OPR_TMPS, rule=operational_violation_cost_rule
    )

    def curtailment_cost_rule(mod, prj, tmp):
        """
        Curtailment costs are defined for some operational types while they are
        zero for others. Get the appropriate expression for each generator
        based on its operational type.
        """
        op_type = mod.operational_type[prj]
        if hasattr(imported_operational_modules[op_type], "curtailment_cost_rule"):
            return imported_operational_modules[op_type].curtailment_cost_rule(
                mod, prj, tmp
            )
        else:
            return op_type_init.curtailment_cost_rule(mod, prj, tmp)

    m.Curtailment_Cost = Expression(
        m.CURTAILMENT_COST_PRJ_OPR_TMPS, rule=curtailment_cost_rule
    )

    def soc_penalty_cost_rule(mod, prj, tmp):
        """
        State of charge penalty costs are defined for some operational types while
        they are zero for others. Get the appropriate expression for each project
        based on its operational type.
        """
        op_type = mod.operational_type[prj]
        if hasattr(imported_operational_modules[op_type], "soc_penalty_cost_rule"):
            return imported_operational_modules[op_type].soc_penalty_cost_rule(
                mod, prj, tmp
            )
        else:
            return op_type_init.soc_penalty_cost_rule(mod, prj, tmp)

    m.SOC_Penalty_Cost = Expression(
        m.SOC_PENALTY_COST_PRJ_OPR_TMPS, rule=soc_penalty_cost_rule
    )

    def soc_last_tmp_penalty_cost_rule(mod, prj, tmp):
        """
        State of charge penalty costs are defined for some operational types while
        they are zero for others. Get the appropriate expression for each project
        based on its operational type.
        """
        op_type = mod.operational_type[prj]
        if hasattr(
            imported_operational_modules[op_type], "soc_last_tmp_penalty_cost_rule"
        ):
            return imported_operational_modules[op_type].soc_last_tmp_penalty_cost_rule(
                mod, prj, tmp
            )
        else:
            return op_type_init.soc_last_tmp_penalty_cost_rule(mod, prj, tmp)

    m.SOC_Penalty_Last_Tmp_Cost = Expression(
        m.SOC_LAST_TMP_PENALTY_COST_PRJ_OPR_TMPS, rule=soc_last_tmp_penalty_cost_rule
    )

    def peak_deviation_monthly_demand_charge_cost_rule(mod, prj, prd, mnth):
        """
        Demand charge for deviating from average power in each month
        """
        op_type = mod.operational_type[prj]
        if hasattr(
            imported_operational_modules[op_type],
            "peak_deviation_monthly_demand_charge_cost_rule",
        ):
            return imported_operational_modules[
                op_type
            ].peak_deviation_monthly_demand_charge_cost_rule(mod, prj, prd, mnth)
        else:
            return op_type_init.peak_deviation_monthly_demand_charge_cost_rule(
                mod, prj, prd, mnth
            )

    m.Peak_Deviation_Demand_Charge_Cost = Expression(
        m.PRJ_OPR_PRDS, m.MONTHS, rule=peak_deviation_monthly_demand_charge_cost_rule
    )


# Input-Output
###############################################################################


def export_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    m,
    d,
):
    """
    Export operations results. Note: fuel cost includes startup fuel as well
    if applicable, in which case this is startup fuel cost is additional to
    the startup costs reported here.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    The Pyomo abstract model
    :param d:
    Dynamic components
    :return:
    Nothing
    """

    results_columns = [
        "variable_om_cost",
        "fuel_cost",
        "startup_cost",
        "shutdown_cost",
        "operational_violation_cost",
        "curtailment_cost",
        "soc_penalty_cost",
        "soc_last_tmp_penalty_cost",
    ]
    data = [
        [
            prj,
            tmp,
            (
                value(m.Variable_OM_Cost[prj, tmp])
                if prj in m.VAR_OM_COST_ALL_PRJS
                else None
            ),
            value(m.Fuel_Cost[prj, tmp]) if prj in m.FUEL_PRJS else None,
            value(m.Startup_Cost[prj, tmp]) if prj in m.STARTUP_COST_PRJS else None,
            value(m.Shutdown_Cost[prj, tmp]) if prj in m.SHUTDOWN_COST_PRJS else None,
            (
                value(m.Operational_Violation_Cost[prj, tmp])
                if prj in m.VIOL_ALL_PRJ_OPR_TMPS
                else None
            ),
            (
                value(m.Curtailment_Cost[prj, tmp])
                if prj in m.CURTAILMENT_COST_PRJS
                else None
            ),
            (
                value(m.SOC_Penalty_Cost[prj, tmp])
                if prj in m.SOC_PENALTY_COST_PRJS
                else None
            ),
            (
                value(m.SOC_Penalty_Last_Tmp_Cost[prj, tmp])
                if prj in m.SOC_LAST_TMP_PENALTY_COST_PRJS
                else None
            ),
        ]
        for (prj, tmp) in m.PRJ_OPR_TMPS
    ]
    results_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    for c in results_columns:
        getattr(d, PROJECT_TIMEPOINT_DF)[c] = None
    getattr(d, PROJECT_TIMEPOINT_DF).update(results_df)

    # for prj, prd in m.PRJ_OPR_PRDS:
    #     for mnth in m.MONTHS:
    #         print(value(m.Peak_Deviation_Demand_Charge_Cost[prj, prd, mnth]))


# Database
###############################################################################


def process_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate costs by zone and period
    TODO: by technology too?
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate costs")

    # Delete old results
    del_sql = """
        DELETE FROM results_project_costs_operations_agg
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Aggregate operational costs by period and load zone
    agg_sql = """
        INSERT INTO results_project_costs_operations_agg
        (scenario_id, subproblem_id, stage_id, period, 
        load_zone, spinup_or_lookahead, 
        variable_om_cost, fuel_cost, startup_cost, shutdown_cost)
        SELECT scenario_id, subproblem_id, stage_id, period, load_zone,
        spinup_or_lookahead,
        SUM(variable_om_cost * timepoint_weight * number_of_hours_in_timepoint)
        AS variable_om_cost,
        SUM(fuel_cost * timepoint_weight * number_of_hours_in_timepoint)
        AS fuel_cost,
        SUM(startup_cost * timepoint_weight) AS startup_cost,
        SUM(shutdown_cost * timepoint_weight) AS shutdown_cost
        FROM results_project_timepoint
        WHERE scenario_id = ?
        GROUP BY subproblem_id, stage_id, period, load_zone, spinup_or_lookahead
        ORDER BY subproblem_id, stage_id, period, load_zone, spinup_or_lookahead
        ;"""
    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )
