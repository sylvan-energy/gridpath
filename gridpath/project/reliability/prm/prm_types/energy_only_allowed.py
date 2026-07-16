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
Projects that can be partly or fully 'energy-only,' i.e. some of the capacity
can have no PRM contribution (and therefore potentially incur a smaller cost),
or partly or fully deliverable
"""

import csv
import os.path
from pyomo.environ import (
    Var,
    Set,
    Constraint,
    NonNegativeReals,
    Expression,
    value,
)

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import import_csv

# TODO: rename deliverability_group_deliverability_cost_per_mw --> deliverability_group_deliverability_cost_per_mw_yr


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
    EOA: Energy-Only Allowed
    :param m:
    :param d:
    :return:
    """

    m.EOA_PRM_PROJECTS = Set(
        within=m.PRM_PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod=mod,
            set_name="PRM_PROJECTS",
            param_name="prm_type",
            param_value="energy_only_allowed",
        ),
    )

    m.EOA_PRM_PRJ_OPR_PRDS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRM_PRJ_OPR_PRDS",
            index=0,
            membership_set=mod.EOA_PRM_PROJECTS,
        ),
    )

    # We can allow the 'fully-deliverable' capacity to be different from the
    # total capacity since in some cases full deliverability may require
    # additional costs to be incurred (e.g. for transmission, etc.)
    m.Deliverable_Capacity_MW = Var(m.EOA_PRM_PRJ_OPR_PRDS, within=NonNegativeReals)

    def energy_only_capacity_init(mod, g, p):
        """ """
        return mod.Capacity_MW[g, p] - mod.Deliverable_Capacity_MW[g, p]

    m.Energy_Only_Capacity_MW = Expression(
        m.EOA_PRM_PRJ_OPR_PRDS, initialize=energy_only_capacity_init
    )

    def deliverable_capacity_constraint_rule(mod, g, p):
        """
        Deliverable capacity must be less than the project capacity.
        """
        return mod.Deliverable_Capacity_MW[g, p] <= mod.Capacity_MW[g, p]

    m.Deliverable_Less_Than_Total_Constraint = Constraint(
        m.EOA_PRM_PRJ_OPR_PRDS, rule=deliverable_capacity_constraint_rule
    )


def elcc_eligible_capacity_rule(mod, proj, period):
    """

    :param mod:
    :param proj:
    :param period:
    :return:
    """
    return mod.Deliverable_Capacity_MW[proj, period]


def export_results(
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

    :param m:
    :param d:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """

    # Energy-only vs deliverable capacity by project
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "project_deliverability.csv",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "project",
                "period",
                "prm_zone",
                "capacity_mw",
                "deliverable_capacity_mw",
                "energy_only_capacity_mw",
            ]
        )
        for prj, p in m.EOA_PRM_PRJ_OPR_PRDS:
            writer.writerow(
                [
                    prj,
                    p,
                    m.prm_zone[prj],
                    value(m.Capacity_MW[prj, p]),
                    value(m.Deliverable_Capacity_MW[prj, p]),
                    value(m.Energy_Only_Capacity_MW[prj, p]),
                ]
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
    :param subproblem:
    :param stage:
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
        which_results="project_deliverability",
    )


def process_model_results(db, c, scenario_id, subscenarios, quiet):
    """

    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("update energy-only capacities")

    # Figure out RPS zone for each project
    project_period_eocap = c.execute("""SELECT project, period, energy_only_capacity_mw
        FROM results_project_deliverability
            WHERE scenario_id = {};""".format(scenario_id)).fetchall()

    tables_to_update = ["results_project_elcc_simple", "results_project_elcc_surface"]

    results = []
    for row in project_period_eocap:
        results.append((row[2], scenario_id, row[0], row[1]))

    for table in tables_to_update:
        sql = """
            UPDATE {}
            SET energy_only_capacity_mw = ?
            WHERE scenario_id = ?
            AND project = ?
            AND period = ?;""".format(table)

        spin_on_database_lock(conn=db, cursor=c, sql=sql, data=results)

    # Aggregate costs by period and break out into spinup_or_lookahead.

    # Delete old resulst
    del_sql = """
        DELETE FROM 
        results_project_deliverability_groups_agg 
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Insert new results
    agg_sql = """
        INSERT INTO 
        results_project_deliverability_groups_agg
        (scenario_id, period, subproblem_id, stage_id,
        spinup_or_lookahead, fraction_of_hours_in_subproblem, 
        deliverable_capacity_cost)

        SELECT scenario_id, period, subproblem_id, stage_id,
        spinup_or_lookahead, fraction_of_hours_in_subproblem,
        (deliverable_capacity_cost * fraction_of_hours_in_subproblem) 
        AS deliverable_capacity_cost
        FROM spinup_or_lookahead_ratios

        -- Now that we have all scenario_id, subproblem_id, stage_id, period, 
        -- and spinup_or_lookahead combinations add the deliverable capacity 
        -- costs which will be derated by the fraction_of_hours_in_subproblem
        INNER JOIN
        (SELECT scenario_id, subproblem_id, stage_id, period, 
        SUM(deliverability_annual_cost_in_period) AS deliverable_capacity_cost
        FROM results_project_deliverability_groups
        WHERE scenario_id = ?
        GROUP BY scenario_id, subproblem_id, stage_id, period
        ) AS cap_table
        USING (scenario_id, subproblem_id, stage_id, period)
        ;"""

    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )
