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
The **gridpath.project.capacity.capacity** module is a project-level
module that adds to the formulation components that describe the amount of
power that a project is providing in each study timepoint.
"""

import os.path
import pandas as pd
from pyomo.environ import Expression, value, Constraint

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import get_required_subtype_modules
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.project.operations.common_functions import (
    load_operational_type_modules,
    resolve_op_type_rules,
)
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
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Project_Power_Provision_MW`                                    |
    | | *Defined over*: :code:`PRJ_OPR_TMPS`                                  |
    |                                                                         |
    | Defines the power a project is producing in each of its operational     |
    | timepoints. The exact formulation of the expression depends             |
    | on the project's *operational_type*. For each project, we call its      |
    | *capacity_type* module's *power_provision_rule* method in order to      |
    | formulate the expression. E.g. a project of the  *gen_must_run*         |
    | operational_type will be producing power equal to its capacity while a  |
    | dispatchable project will have a variable in its power provision        |
    | expression. This expression will then be used by other modules.         |
    +-------------------------------------------------------------------------+
    | | :code:`Bulk_Power_Provision_MW`                                       |
    | | *Defined over*: :code:`PRJ_OPR_TMPS`                                  |
    |                                                                         |
    | Defines the power a project is producing in each of its operational     |
    | timepoints from the bulk system perspective (adjusted for distribution  |
    | losses.                                                                 |
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

    # Expressions
    ###########################################################################

    # Resolve each op type's power provision rule once
    power_provision_rule_by_op_type = resolve_op_type_rules(
        imported_operational_modules, "power_provision_rule", op_type_init
    )

    def project_power_provision_rule(mod, prj, tmp):
        """
        **Expression Name**: Project_Power_Provision_MW
        **Defined Over**: PRJ_OPR_TMPS

        Power provision is a variable for some generators, but not others; get
        the appropriate expression for each generator based on its operational
        type. This is a project-level variable that is not yet adjusted for
        distribution system losses to get bulk system equivalent power.
        """
        return power_provision_rule_by_op_type[mod.operational_type[prj]](mod, prj, tmp)

    m.Project_Power_Provision_MW = Expression(
        m.PRJ_OPR_TMPS, rule=project_power_provision_rule
    )

    def bulk_power_provision_rule(mod, prj, tmp):
        """
        This is power production from the perspective of the bulk system (
        project power production is multiplied by (1 +
        distribution_loss_adjustment_factor)). If a resource is producing power on the
        distribution side (and hence does not incur distribution losses),
        we'll adjust the power production from the bulk system perspective
        based on the distribution_loss_adjustment_factor. Similarly, if the resource is
        increasing demand on the distribution side (negative power production),
        a higher total demand will be seen on the bulk system side.
        """
        return mod.Project_Power_Provision_MW[prj, tmp] * (
            1 + mod.distribution_loss_adjustment_factor[prj]
        )

    m.Bulk_Power_Provision_MW = Expression(
        m.PRJ_OPR_TMPS, rule=bulk_power_provision_rule
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
    Export operations results.
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

    results_columns = ["project_power_mw", "power_mw"]
    data = [
        [
            prj,
            tmp,
            value(m.Project_Power_Provision_MW[prj, tmp]),
            value(m.Bulk_Power_Provision_MW[prj, tmp]),
        ]
        for (prj, tmp) in m.PRJ_OPR_TMPS
    ]
    results_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PROJECT_TIMEPOINT_DF), results_df)

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

    for optype_module in imported_operational_modules:
        if hasattr(
            imported_operational_modules[optype_module], "add_to_prj_tmp_results"
        ):
            results_columns, optype_df = imported_operational_modules[
                optype_module
            ].add_to_prj_tmp_results(mod=m)
            update_results_df(getattr(d, PROJECT_TIMEPOINT_DF), optype_df)


# Database
###############################################################################


def process_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate dispatch by technology
    Aggregate dispatch by technology and period
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate dispatch by technology")

    # Delete old dispatch by technology
    del_sql = """
        DELETE FROM results_project_dispatch_by_technology 
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Aggregate dispatch by technology
    agg_sql = """
        INSERT INTO results_project_dispatch_by_technology (
            scenario_id, 
            weather_iteration, 
            hydro_iteration, 
            availability_iteration, 
            subproblem_id,
            stage_id, 
            period, 
            timepoint, 
            timepoint_weight, 
            number_of_hours_in_timepoint, 
            spinup_or_lookahead,
            load_zone, 
            technology, 
            power_mw
            )
        SELECT
            scenario_id,
            weather_iteration, 
            hydro_iteration, 
            availability_iteration, 
            subproblem_id, 
            stage_id,
            period, 
            timepoint, 
            timepoint_weight, 
            number_of_hours_in_timepoint, 
            spinup_or_lookahead,
            load_zone, 
            technology, 
            sum(power_mw) AS power_mw
        FROM results_project_timepoint
        WHERE scenario_id = ?
        GROUP BY 
            weather_iteration, 
            hydro_iteration, 
            availability_iteration, 
            subproblem_id, 
            stage_id, 
            timepoint, 
            load_zone, 
            technology
        ORDER BY 
            weather_iteration, 
            hydro_iteration, 
            availability_iteration, 
            subproblem_id, 
            stage_id, 
            timepoint, 
            load_zone, 
            technology;"""
    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )

    if not quiet:
        print("aggregate dispatch by technology-period")

    # Delete old dispatch by technology
    del_sql = """
        DELETE FROM results_project_dispatch_by_technology_period 
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Aggregate dispatch by technology, period, and spinup_or_lookahead
    agg_sql = """
        INSERT INTO results_project_dispatch_by_technology_period (
            scenario_id, 
            weather_iteration, 
            hydro_iteration, 
            availability_iteration, 
            subproblem_id, 
            stage_id, 
            period, 
            load_zone, 
        technology, spinup_or_lookahead, energy_mwh)
        SELECT
            scenario_id, 
            weather_iteration, 
            hydro_iteration, 
            availability_iteration, 
            subproblem_id, 
            stage_id, 
            period, 
            load_zone, 
            technology, 
            spinup_or_lookahead,
            SUM(power_mw * timepoint_weight * number_of_hours_in_timepoint ) AS energy_mwh 
        FROM results_project_dispatch_by_technology
        WHERE scenario_id = ?
        GROUP BY 
            weather_iteration, 
            hydro_iteration, 
            availability_iteration, 
            subproblem_id, 
            stage_id, 
            period, 
            load_zone, 
            technology, 
            spinup_or_lookahead
        ORDER BY 
            weather_iteration, 
            hydro_iteration, 
            availability_iteration, 
            subproblem_id, 
            stage_id, 
            period, 
            load_zone, 
            technology, 
            spinup_or_lookahead
            ;
            """
    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )
