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
Total ELCC of projects on ELCC surface
"""

import csv
import os.path
from pyomo.environ import (
    Param,
    Var,
    Set,
    NonNegativeReals,
    Constraint,
    Expression,
    value,
)

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import (
    prm_balance_provision_components,
    cost_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.reliability.prm import PRM_ZONE_PRD_DF


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

    :param m:
    :param d:
    :return:
    """

    # Surface can change by prm_zone and period
    # Limit surface to 1000 facets
    m.ELCC_SURFACE_PRM_ZONE_PERIOD_FACETS = Set(
        dimen=4, within=m.ELCC_SURFACE_PRM_ZONE_PERIODS * list(range(1, 1001))
    )

    # The intercept for the prm_zone/period/facet combination
    m.elcc_surface_intercept = Param(
        m.ELCC_SURFACE_PRM_ZONE_PERIOD_FACETS, within=NonNegativeReals
    )

    # Endogenous dynamic ELCC surface
    m.Dynamic_ELCC_MW = Var(m.ELCC_SURFACE_PRM_ZONE_PERIODS, within=NonNegativeReals)

    def elcc_surface_rule(mod, surface, prm_zone, period, facet):
        """

        :param mod:
        :param prm_zone:
        :param period:
        :param facet:
        :return:
        """
        return (
            mod.Dynamic_ELCC_MW[surface, prm_zone, period]
            <= sum(
                mod.ELCC_Surface_Contribution_MW[s, prj, period, facet]
                for (s, prj) in mod.ELCC_SURFACE_PROJECTS_BY_PRM_ZONE[prm_zone]
                if s == surface
                # This is redundant since since ELCC_Surface_Contribution_MW
                # is 0 for non-operational periods, but keep here for
                # extra safety
                and period in mod.OPR_PRDS_BY_PRJ[prj]
            )
            + mod.elcc_surface_intercept[surface, prm_zone, period, facet]
            * mod.prm_peak_load_mw[surface, prm_zone, period]
        )

    # Dynamic ELCC piecewise constraint
    m.Dynamic_ELCC_Constraint = Constraint(
        m.ELCC_SURFACE_PRM_ZONE_PERIOD_FACETS, rule=elcc_surface_rule
    )

    def total_contribution_from_all_surfaces_init(mod, prm_zone, period):
        return sum(
            mod.Dynamic_ELCC_MW[surface, z, p]
            for (surface, z, p) in mod.ELCC_SURFACE_PRM_ZONE_PERIODS
            if z == prm_zone and p == period
        )

    m.Total_Contribution_from_ELCC_Surfaces = Expression(
        m.PRM_ZONE_PERIODS_WITH_REQUIREMENT,
        initialize=total_contribution_from_all_surfaces_init,
    )

    # Add to emission imports to carbon balance
    getattr(d, prm_balance_provision_components).append(
        "Total_Contribution_from_ELCC_Surfaces"
    )


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
    # PRM zone-period-facet
    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "prm_zone_surface_facets_and_intercept.tab",
        ),
        index=m.ELCC_SURFACE_PRM_ZONE_PERIOD_FACETS,
        param=m.elcc_surface_intercept,
        select=(
            "elcc_surface_name",
            "prm_zone",
            "period",
            "facet",
            "elcc_surface_intercept",
        ),
    )


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

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """
    results_columns = [
        "elcc_surface_mw",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_Contribution_from_ELCC_Surfaces[z, p]),
        ]
        for (z, p) in m.PRM_ZONE_PERIODS_WITH_REQUIREMENT
    ]
    results_df = create_results_df(
        index_columns=["prm_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PRM_ZONE_PRD_DF), results_df)

    # By ELCC surface results
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "prm_elcc_surface.csv",
        ),
        "w",
        newline="",
    ) as results_file:
        writer = csv.writer(results_file)
        writer.writerow(["elcc_surface_name", "prm_zone", "period", "elcc_mw"])
        for s, z, p in m.ELCC_SURFACE_PRM_ZONE_PERIODS:
            writer.writerow([s, z, p, value(m.Dynamic_ELCC_MW[s, z, p])])


def save_duals(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    instance,
    dynamic_components,
):
    instance.constraint_indices["Dynamic_ELCC_Constraint"] = [
        "surface_name",
        "prm_zone",
        "period",
        "facet",
        "dual",
    ]


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
    :param c: database cursor
    :return:
    """
    c = conn.cursor()
    # The intercepts for the surface
    intercepts = c.execute(
        """
        SELECT elcc_surface_name, prm_zone, period, facet, elcc_surface_intercept
        FROM
        (SELECT prm_zone
        FROM inputs_geography_prm_zones
        WHERE prm_zone_scenario_id = {prm_zone}) as prm_zone_tbl
        CROSS JOIN
        (SELECT period
        FROM inputs_temporal_periods
        WHERE temporal_scenario_id = {temporal}) as period_tbl
        -- Join to the normalization params
        LEFT OUTER JOIN
        inputs_system_prm_zone_elcc_surface
        USING (prm_zone, period)
        WHERE elcc_surface_scenario_id = {elcc_surface}
        """.format(
            prm_zone=subscenarios.PRM_ZONE_SCENARIO_ID,
            temporal=subscenarios.TEMPORAL_SCENARIO_ID,
            elcc_surface=subscenarios.ELCC_SURFACE_SCENARIO_ID,
        )
    )

    return intercepts


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

    # intercepts = get_inputs_from_database(
    #     scenario_id, subscenarios, subproblem, stage, conn)

    # do stuff here to validate inputs


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
    Get inputs from database and write out the model input
    prm_zone_surface_facets_and_intercept.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param c: database cursor
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

    intercepts = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    with open(
        os.path.join(
            scenario_directory,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "prm_zone_surface_facets_and_intercept.tab",
        ),
        "w",
        newline="",
    ) as intercepts_file:
        writer = csv.writer(intercepts_file, delimiter="\t", lineterminator="\n")

        # Writer header
        writer.writerow(
            [
                "elcc_surface_name",
                "prm_zone",
                "period",
                "facet",
                "elcc_surface_intercept",
            ]
        )
        # Write data
        for row in intercepts:
            writer.writerow(row)
