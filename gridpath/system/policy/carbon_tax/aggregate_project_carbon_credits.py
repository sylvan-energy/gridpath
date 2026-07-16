# Copyright 2016-2023 Blue Marble Analytics LLC
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
Aggregate carbon credits from the project-period level to the
carbon tax zone - period level.
"""

import os.path
from pyomo.environ import (
    Set,
    Expression,
    value,
    Param,
    PercentFraction,
    Constraint,
    NonNegativeReals,
)

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import carbon_tax_cost_components
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.carbon_tax import CARBON_TAX_ZONE_PRD_DF

Infinity = float("inf")


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
    """ """
    m.CARBON_TAX_ZONES_CARBON_CREDITS_ZONES = Set(
        within=m.CARBON_TAX_ZONES * m.CARBON_CREDITS_ZONES
    )

    m.purchase_credit_min_fraction = Param(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX,
        within=NonNegativeReals,
        default=Infinity,
    )

    m.purchase_credit_max_fraction = Param(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX,
        within=NonNegativeReals,
        default=Infinity,
    )

    def total_carbon_emissions_credits_rule(mod, tax_z, prd):
        """
        Purchased credits for projects in this carbon tax zone.
        We also need to check that we only count credits projects can
        purchase from credits zone that this carbon_tax zone maps to.
        """
        return sum(
            mod.Project_Purchase_Carbon_Credits[prj, z, prd]
            # Projects in this carbon tax zone
            for prj in mod.CARBON_TAX_PRJS_BY_CARBON_TAX_ZONE[tax_z]
            for z in mod.CARBON_CREDITS_ZONES
            if (prj, z, prd)
            in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS
            # Limit to projects in a credit zone mapped to this carbon_tax zone
            if (tax_z, z) in mod.CARBON_TAX_ZONES_CARBON_CREDITS_ZONES
        )

    m.Total_Carbon_Tax_Emissions_Credits = Expression(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX,
        rule=total_carbon_emissions_credits_rule,
    )

    def project_carbon_credit_max_rule(mod, tax_z, prd):
        txz_can_purchase = False
        for prj in mod.CARBON_TAX_PRJS_BY_CARBON_TAX_ZONE[tax_z]:
            for z in mod.CARBON_CREDITS_ZONES:
                if (
                    prj,
                    z,
                    prd,
                ) in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS:
                    if (tax_z, z) in mod.CARBON_TAX_ZONES_CARBON_CREDITS_ZONES:
                        txz_can_purchase = True
        if not txz_can_purchase:
            return Constraint.Skip

        if mod.purchase_credit_max_fraction[tax_z, prd] != Infinity:
            return (
                mod.Total_Carbon_Tax_Emissions_Credits[tax_z, prd]
                <= (
                    mod.Total_Carbon_Tax_Project_Emissions[tax_z, prd]
                    - mod.Total_Carbon_Tax_Project_Allowance[tax_z, prd]
                )
                * mod.purchase_credit_max_fraction[tax_z, prd]
            )
        else:
            return Constraint.Skip

    m.Max_Project_Carbon_Credits_Purchased_Constraint = Constraint(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX, rule=project_carbon_credit_max_rule
    )

    def project_carbon_credit_min_rule(mod, tax_z, prd):
        txz_can_purchase = False
        for prj in mod.CARBON_TAX_PRJS_BY_CARBON_TAX_ZONE[tax_z]:
            for z in mod.CARBON_CREDITS_ZONES:
                if (
                    prj,
                    z,
                    prd,
                ) in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS:
                    if (tax_z, z) in mod.CARBON_TAX_ZONES_CARBON_CREDITS_ZONES:
                        txz_can_purchase = True
        if not txz_can_purchase:
            return Constraint.Skip

        if mod.purchase_credit_min_fraction[tax_z, prd] != Infinity:
            return (
                mod.Total_Carbon_Tax_Emissions_Credits[tax_z, prd]
                >= (
                    mod.Total_Carbon_Tax_Project_Emissions[tax_z, prd]
                    - mod.Total_Carbon_Tax_Project_Allowance[tax_z, prd]
                )
                * mod.purchase_credit_min_fraction[tax_z, prd]
            )
        else:
            return Constraint.Skip

    m.Min_Project_Carbon_Credits_Purchased_Constraint = Constraint(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX, rule=project_carbon_credit_min_rule
    )

    def credit_cost_reduction(mod, z, prd):
        return -mod.Total_Carbon_Tax_Emissions_Credits[z, prd] * mod.carbon_tax[z, prd]

    m.Total_Carbon_Tax_Credit_Cost_Reduction = Expression(
        m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX, rule=credit_cost_reduction
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    This method adds project credits to carbon balance
    """

    getattr(dynamic_components, carbon_tax_cost_components).append(
        "Total_Carbon_Tax_Credit_Cost_Reduction"
    )


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
    mapping = c.execute(f"""SELECT carbon_tax_zone, carbon_credits_zone
        FROM inputs_system_carbon_tax_zones_carbon_credits_zones
        WHERE carbon_tax_zones_carbon_credits_zones_scenario_id = 
        {subscenarios.CARBON_TAX_ZONES_CARBON_CREDITS_ZONES_SCENARIO_ID}
        AND carbon_tax_zone in (
            SELECT carbon_tax_zone
            FROM inputs_geography_carbon_tax_zones
            WHERE carbon_tax_zone_scenario_id = {subscenarios.CARBON_TAX_ZONE_SCENARIO_ID}
        )
        AND carbon_credits_zone in (
            SELECT carbon_credits_zone
            FROM inputs_geography_carbon_credits_zones
            WHERE carbon_credits_zone_scenario_id = 
            {subscenarios.CARBON_CREDITS_ZONE_SCENARIO_ID}
        )
        ;
        """)

    c2 = conn.cursor()
    credit_limits = c2.execute(
        f"""SELECT project, carbon_tax_zone, period, purchase_credit_min_fraction, purchase_credit_max_fraction
        FROM
        (SELECT  project, period, purchase_credit_min_fraction, purchase_credit_max_fraction
        FROM inputs_project_carbon_credits_purchase_limits
        WHERE project_carbon_credits_purchase_limits_scenario_id = 
        {subscenarios.PROJECT_CARBON_CREDITS_PURCHASE_LIMITS_SCENARIO_ID}
        AND (
            period in (
            SELECT DISTINCT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            )
            OR period = 0 -- for all periods
            )
        AND project in (
            SELECT project
            FROM inputs_project_carbon_credits_purchase_zones
            WHERE project_carbon_credits_purchase_zone_scenario_id = 
            {subscenarios.PROJECT_CARBON_CREDITS_PURCHASE_ZONE_SCENARIO_ID}
        )   
        AND project in (
            SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = 
            {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            )) as prj_cc_limits_tbl
        LEFT OUTER JOIN
            -- Add project carbon tax zone based on project_carbon_tax_zone_scenario_id
            (SELECT project, carbon_tax_zone
            FROM inputs_project_carbon_tax_zones
            WHERE project_carbon_tax_zone_scenario_id = {subscenarios.PROJECT_CARBON_TAX_ZONE_SCENARIO_ID}) as prj_ct_zone_tbl
            USING(project)
        """
    )

    return mapping, credit_limits


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
    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )

    mapping, credit_limits = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )
    # carbon_tax_zones_carbon_credits_zone_mapping.tab
    df = cursor_to_df(mapping)
    df = df.fillna(".")
    fpath = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "carbon_tax_zones_carbon_credits_zone_mapping.tab",
    )
    if not df.empty:
        df.to_csv(fpath, index=False, sep="\t")

    # project_carbon_credits_purchase_limits.tab
    cred_lim_df = cursor_to_df(credit_limits)
    cred_lim_df = cred_lim_df.fillna(".")
    fpath = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "project_carbon_credits_purchase_limits.tab",
    )
    if not cred_lim_df.empty:
        cred_lim_df.to_csv(fpath, index=False, sep="\t")


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

    map_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "carbon_tax_zones_carbon_credits_zone_mapping.tab",
    )

    if os.path.exists(map_file):
        data_portal.load(
            filename=map_file,
            set=m.CARBON_TAX_ZONES_CARBON_CREDITS_ZONES,
        )

    cred_lim_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "project_carbon_credits_purchase_limits.tab",
    )

    if os.path.exists(cred_lim_file):
        data_portal.load(
            filename=cred_lim_file,
            select=(
                "carbon_tax_zone",
                "period",
                "purchase_credit_min_fraction",
                "purchase_credit_max_fraction",
            ),
            param=(m.purchase_credit_min_fraction, m.purchase_credit_max_fraction),
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
        "project_credits",
    ]
    data = [
        [z, p, value(m.Total_Carbon_Tax_Emissions_Credits[z, p])]
        for (z, p) in m.CARBON_TAX_ZONE_PERIODS_WITH_CARBON_TAX
    ]
    results_df = create_results_df(
        index_columns=["carbon_tax_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, CARBON_TAX_ZONE_PRD_DF), results_df)
