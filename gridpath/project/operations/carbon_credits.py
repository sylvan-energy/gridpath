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

""" """

import csv
import os.path
from pyomo.environ import Param, Set, NonNegativeReals, Var, Constraint, value

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_param_value,
    get_required_subtype_modules,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.common_functions import create_results_df
from gridpath.project import PROJECT_PERIOD_DF
from gridpath.project.operations.common_functions import load_operational_type_modules
import gridpath.project.operations.operational_types as op_type_init

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
    """
    The following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`CARBON_CREDITS_PRJS`                                               |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | Two set of carbonaceous projects we need to track for the carbon credits.   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`carbon_credits_zone`                                           |
    | | *Defined over*: :code:`CARBON_CREDITS_PRJS`                           |
    | | *Within*: :code:`CARBON_CREDITS_ZONES`                                |
    |                                                                         |
    | This param describes the carbon credits zone for each carbon credits    |
    | project.                                                                |
    +-------------------------------------------------------------------------+
    | | :code:`intensity_threshold_emissions_toCO2_per_MWh`                   |
    | | *Defined over*: :code:`CARBON_CREDITS_PRJ_OPR_PRDS`                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | This param describes the intensity-based emissions threshold for each   |
    | carbon credits project. Additive with the absolute emissions threshold. |
    +-------------------------------------------------------------------------+
    | | :code:`absolute_threshold_emissions_toCO2`                            |
    | | *Defined over*: :code:`CARBON_CREDITS_PRJ_OPR_PRDS`                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | This param describes the absolute emissions threshold for each carbon   |
    | credits project. Additive with the relative emissions threshold.        |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Sets                                                            |
    +=========================================================================+
    | | :code:`CARBON_CREDITS_PRJS_BY_CARBON_CREDITS_ZONE`                    |
    | | *Defined over*: :code:`CARBON_CREDITS_ZONES`                          |
    | | *Within*: :code:`CARBON_CREDITS_PRJS`                                 |
    |                                                                         |
    | Indexed set that describes the list of carbonaceous projects for each   |
    | carbon credits zone.                                                    |
    +-------------------------------------------------------------------------+
    | | :code:`CARBON_CREDITS_PRJ_OPR_TMPS`                                   |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | Two-dimensional set that defines all project-timepoint combinations     |
    | when a carbon credits project can be operational.                       |
    +-------------------------------------------------------------------------+
    | | :code:`CARBON_CREDITS_PRJ_OPR_PRDS`                                   |
    | | *Within*: :code:`PRJ_OPR_PRDS`                                        |
    |                                                                         |
    | Two-dimensional set that defines all project-period combinations        |
    | when a carbon credits project can be operational.                       |
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

    m.CARBON_CREDITS_GENERATION_PRJS = Set(within=m.PROJECTS)

    m.CARBON_CREDITS_GENERATION_PRJ_OPR_TMPS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.CARBON_CREDITS_GENERATION_PRJS,
        ),
    )

    m.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_PRDS",
            index=0,
            membership_set=mod.CARBON_CREDITS_GENERATION_PRJS,
        ),
    )

    m.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES = Set(
        dimen=2, within=m.PROJECTS * m.CARBON_CREDITS_ZONES
    )

    # Input Params
    ###########################################################################

    m.carbon_credits_generation_zone = Param(
        m.CARBON_CREDITS_GENERATION_PRJS, within=m.CARBON_CREDITS_ZONES
    )

    m.intensity_threshold_emissions_toCO2_per_MWh = Param(
        m.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS,
        within=NonNegativeReals,
        default=Infinity,
    )

    m.absolute_threshold_emissions_toCO2 = Param(
        m.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS,
        within=NonNegativeReals,
        default=Infinity,
        validate=lambda mod, value, prj, prd: (
            value == Infinity
            if mod.intensity_threshold_emissions_toCO2_per_MWh[prj, prd] < Infinity
            else value <= Infinity
        ),  # pick one of intensity-based and absolute thresholds
    )

    # Derived Sets
    ###########################################################################

    m.CARBON_CREDITS_GENERATION_PRJS_BY_CARBON_CREDITS_ZONE = Set(
        m.CARBON_CREDITS_ZONES,
        within=m.CARBON_CREDITS_GENERATION_PRJS,
        initialize=lambda mod, z: subset_init_by_param_value(
            mod, "CARBON_CREDITS_GENERATION_PRJS", "carbon_credits_generation_zone", z
        ),
    )

    m.CARBON_CREDITS_PURCHASE_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: sorted(
            list(
                set(
                    [
                        prj
                        for (
                            prj,
                            z,
                        ) in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES
                    ]
                )
            ),
        ),
    )

    m.CARBON_CREDITS_PURCHASE_PRJS_BY_CARBON_CREDITS_ZONE = Set(
        m.CARBON_CREDITS_ZONES,
        within=m.PROJECTS,
        initialize=lambda mod, cc_z: [
            prj
            for (prj, z) in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES
            if cc_z == z
        ],
    )

    m.CARBON_CREDITS_PURCHASE_PRJS_OPR_TMPS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.CARBON_CREDITS_PURCHASE_PRJS,
        ),
    )

    m.CARBON_CREDITS_PURCHASE_PRJS_OPR_PRDS = Set(
        within=m.PRJ_OPR_PRDS,
        initialize=lambda mod: [
            (prj, prd)
            for (prj, prd) in mod.PRJ_OPR_PRDS
            if prj in mod.CARBON_CREDITS_PURCHASE_PRJS
        ],
    )

    m.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_TMPS = Set(
        dimen=3,
        initialize=lambda mod: sorted(
            list(
                set(
                    (prj, z, tmp)
                    for (prj, tmp) in mod.CARBON_CREDITS_PURCHASE_PRJS_OPR_TMPS
                    for (
                        _prj,
                        z,
                    ) in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES
                    if prj == _prj
                ),
            )
        ),
    )

    m.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS = Set(
        dimen=3,
        initialize=lambda mod: sorted(
            list(
                set(
                    (prj, z, prd)
                    for (prj, prd) in mod.CARBON_CREDITS_PURCHASE_PRJS_OPR_PRDS
                    for (
                        _prj,
                        z,
                    ) in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES
                    if prj == _prj
                ),
            )
        ),
    )

    # Variables
    ###########################################################################

    m.Project_Carbon_Credits_Generated = Var(
        m.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS, within=NonNegativeReals
    )

    m.Project_Purchase_Carbon_Credits = Var(
        m.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS,
        within=NonNegativeReals,
    )

    # Constraints
    ###########################################################################

    def generated_credits_rule(mod, prj, prd):
        """
        The credits generated by each project.
        """
        op_type = mod.operational_type[prj]
        total_power_provision_in_prd = sum(
            (
                imported_operational_modules[op_type].power_provision_rule(mod, p, tmp)
                if hasattr(
                    imported_operational_modules[op_type], "power_provision_rule"
                )
                else op_type_init.power_provision_rule(mod, p, tmp)
            )
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (p, tmp) in mod.CARBON_CREDITS_GENERATION_PRJ_OPR_TMPS
            if mod.period[tmp] == prd and p == prj
        )

        var1 = mod.intensity_threshold_emissions_toCO2_per_MWh[prj, prd]
        var2 = mod.absolute_threshold_emissions_toCO2[prj, prd]
        if (var1 == Infinity) and (var2 == Infinity):
            return mod.Project_Carbon_Credits_Generated[prj, prd] == 0
        elif var1 == Infinity:
            return mod.Project_Carbon_Credits_Generated[prj, prd] <= (
                mod.absolute_threshold_emissions_toCO2[prj, prd]
                - sum(
                    mod.Project_Carbon_Emissions[p, tmp]
                    * mod.hrs_in_tmp[tmp]
                    * mod.tmp_weight[tmp]
                    for (p, tmp) in mod.CARBON_CREDITS_GENERATION_PRJ_OPR_TMPS
                    if mod.period[tmp] == prd and p == prj
                )
            )
        elif var2 == Infinity:
            return mod.Project_Carbon_Credits_Generated[prj, prd] <= (
                total_power_provision_in_prd
                * mod.intensity_threshold_emissions_toCO2_per_MWh[prj, prd]
                - sum(
                    mod.Project_Carbon_Emissions[p, tmp]
                    * mod.hrs_in_tmp[tmp]
                    * mod.tmp_weight[tmp]
                    for (p, tmp) in mod.CARBON_CREDITS_GENERATION_PRJ_OPR_TMPS
                    if mod.period[tmp] == prd and p == prj
                )
            )
        else:
            return mod.Project_Carbon_Credits_Generated[prj, prd] <= (
                total_power_provision_in_prd
                * mod.intensity_threshold_emissions_toCO2_per_MWh[prj, prd]
                + mod.absolute_threshold_emissions_toCO2[prj, prd]
                - sum(
                    mod.Project_Carbon_Emissions[p, tmp]
                    * mod.hrs_in_tmp[tmp]
                    * mod.tmp_weight[tmp]
                    for (p, tmp) in mod.CARBON_CREDITS_GENERATION_PRJ_OPR_TMPS
                    if mod.period[tmp] == prd and p == prj
                )
            )

    m.Project_Carbon_Credits_Generated_Constraint = Constraint(
        m.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS, rule=generated_credits_rule
    )

    def purchased_credits_rule(mod, prj, z, prd):
        """
        The credits purchased by each project.
        """
        return mod.Project_Purchase_Carbon_Credits[prj, z, prd] <= (
            sum(
                mod.Project_Carbon_Emissions[p, tmp]
                * mod.hrs_in_tmp[tmp]
                * mod.tmp_weight[tmp]
                for (
                    p,
                    z_,
                    tmp,
                ) in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_TMPS
                if mod.period[tmp] == prd and p == prj and z == z_
            )
        )

    m.Project_Carbon_Credits_Purchased_Constraint = Constraint(
        m.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS,
        rule=purchased_credits_rule,
    )


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
        select=("project", "carbon_credits_generation_zone"),
        param=(m.carbon_credits_generation_zone,),
    )

    data_portal.data()["CARBON_CREDITS_GENERATION_PRJS"] = {
        None: list(data_portal.data()["carbon_credits_generation_zone"].keys())
    }

    prj_carbon_credits_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        str(subproblem),
        str(stage),
        "inputs",
        "project_carbon_credits.tab",
    )
    if os.path.exists(prj_carbon_credits_file):
        data_portal.load(
            filename=prj_carbon_credits_file,
            param=(
                m.intensity_threshold_emissions_toCO2_per_MWh,
                m.absolute_threshold_emissions_toCO2,
            ),
        )

    prj_carbon_credits_purchase_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        str(subproblem),
        str(stage),
        "inputs",
        "project_carbon_credits_purchase_zones.tab",
    )
    if os.path.exists(prj_carbon_credits_purchase_file):
        data_portal.load(
            filename=prj_carbon_credits_purchase_file,
            set=m.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES,
        )


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

    c1 = conn.cursor()
    project_generation_zones = c1.execute(f"""SELECT project, carbon_credits_zone
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get carbon credits zones for those projects
        (SELECT project, carbon_credits_zone
            FROM inputs_project_carbon_credits_generation_zones
            WHERE project_carbon_credits_generation_zone_scenario_id = {subscenarios.PROJECT_CARBON_CREDITS_GENERATION_ZONE_SCENARIO_ID}
        ) as prj_cc_gen_zone_tbl
        USING (project)
        -- Filter out projects whose carbon credits zone is not one included in 
        -- our carbon_credits_zone_scenario_id
        WHERE carbon_credits_zone in (
                SELECT carbon_credits_zone
                    FROM inputs_geography_carbon_credits_zones
                    WHERE carbon_credits_zone_scenario_id = {subscenarios.CARBON_CREDITS_ZONE_SCENARIO_ID}
        );
        """)

    c2 = conn.cursor()
    project_carbon_credits = c2.execute(f"""SELECT project, period,
        intensity_threshold_emissions_toCO2_per_MWh,
        absolute_threshold_emissions_toCO2
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        ) as prj_fuels_tbl
        CROSS JOIN
            (SELECT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            ) as relevant_periods 
        LEFT OUTER JOIN
        -- Get carbon credits for those projects
            (SELECT project, period,
                intensity_threshold_emissions_toCO2_per_MWh,
                absolute_threshold_emissions_toCO2
            FROM inputs_project_carbon_credits
            WHERE project_carbon_credits_scenario_id = {subscenarios.PROJECT_CARBON_CREDITS_SCENARIO_ID}) as prj_ct_tbl
        USING (project, period)
        WHERE project in (
                SELECT project
                    FROM inputs_project_carbon_credits_generation_zones
                    WHERE project_carbon_credits_generation_zone_scenario_id = {subscenarios.PROJECT_CARBON_CREDITS_GENERATION_ZONE_SCENARIO_ID}
        );
        """)

    c3 = conn.cursor()
    project_purchase_zones = c3.execute(f"""SELECT project, carbon_credits_zone
            FROM
            -- Get projects from portfolio only
            (SELECT project
                FROM inputs_project_portfolios
                WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
            ) as prj_tbl
            LEFT OUTER JOIN 
            -- Get carbon credits zones for those projects
            (SELECT project, carbon_credits_zone
                FROM inputs_project_carbon_credits_purchase_zones
                WHERE project_carbon_credits_purchase_zone_scenario_id = {subscenarios.PROJECT_CARBON_CREDITS_PURCHASE_ZONE_SCENARIO_ID}
            ) as prj_cc_gen_zone_tbl
            USING (project)
            -- Filter out projects whose carbon credits zone is not one included in 
            -- our carbon_credits_zone_scenario_id
            WHERE carbon_credits_zone in (
                    SELECT carbon_credits_zone
                        FROM inputs_geography_carbon_credits_zones
                        WHERE carbon_credits_zone_scenario_id = {subscenarios.CARBON_CREDITS_ZONE_SCENARIO_ID}
            );
            """)

    return project_generation_zones, project_carbon_credits, project_purchase_zones


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
    projects.tab (to be precise, amend it) and project_carbon_credits.tab files.
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
        project_generation_zones,
        project_carbon_credits,
        project_purchase_zones,
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

    # projects.tab
    # Make a dict for easy access
    prj_zone_dict = dict()
    for prj, zone in project_generation_zones:
        prj_zone_dict[str(prj)] = "." if zone is None else str(zone)

    with open(
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
        "r",
    ) as projects_file_in:
        reader = csv.reader(projects_file_in, delimiter="\t", lineterminator="\n")

        new_rows = list()

        # Append column header
        header = next(reader)
        header.append("carbon_credits_generation_zone")
        new_rows.append(header)

        # Append correct values
        for row in reader:
            # If project specified, check if BA specified or not
            if row[0] in list(prj_zone_dict.keys()):
                row.append(prj_zone_dict[row[0]])
                new_rows.append(row)
            # If project not specified, specify no BA
            else:
                row.append(".")
                new_rows.append(row)

    with open(
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
        "w",
        newline="",
    ) as projects_file_out:
        writer = csv.writer(projects_file_out, delimiter="\t", lineterminator="\n")
        writer.writerows(new_rows)

    # project_carbon_credits.tab
    ct_df = cursor_to_df(project_carbon_credits)
    if not ct_df.empty:
        ct_df = ct_df.fillna(".")
        fpath = os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "project_carbon_credits.tab",
        )
        ct_df.to_csv(fpath, index=False, sep="\t")

    # project_carbon_credits_purchase_zones.tab
    prj_cc_purchase_df = cursor_to_df(project_purchase_zones)
    if not prj_cc_purchase_df.empty:
        prj_cc_purchase_df = prj_cc_purchase_df.fillna(".")
        fpath = os.path.join(
            scenario_directory,
            str(subproblem),
            str(stage),
            "inputs",
            "project_carbon_credits_purchase_zones.tab",
        )
        prj_cc_purchase_df.to_csv(fpath, index=False, sep="\t")


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

    # Carbon credits generated
    results_columns = [
        "carbon_credits_zone",
        "carbon_credits_generated_tCO2",
    ]
    data = [
        [
            prj,
            prd,
            m.carbon_credits_generation_zone[prj],
            value(m.Project_Carbon_Credits_Generated[prj, prd]),
        ]
        for (prj, prd) in m.CARBON_CREDITS_GENERATION_PRJ_OPR_PRDS
    ]

    results_df = create_results_df(
        index_columns=["project", "period"],
        results_columns=results_columns,
        data=data,
    )

    for c in results_columns:
        getattr(d, PROJECT_PERIOD_DF)[c] = None
    getattr(d, PROJECT_PERIOD_DF).update(results_df)

    # Carbon credits purchase
    with open(
        os.path.join(
            scenario_directory,
            str(subproblem),
            str(stage),
            "results",
            "project_carbon_credits_purchase.csv",
        ),
        "w",
        newline="",
    ) as project_carbon_credits_purchase_results_file:
        writer = csv.writer(project_carbon_credits_purchase_results_file)
        writer.writerow(
            [
                "project",
                "period",
                "discount_factor",
                "number_years_represented",
                "carbon_credit_zone",
                "carbon_credits_purchased_tCO2",
            ]
        )
        for prj, z, prd in m.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS:
            writer.writerow(
                [
                    prj,
                    prd,
                    m.discount_factor[prd],
                    m.number_years_represented[prd],
                    z,
                    value(m.Project_Purchase_Carbon_Credits[prj, z, prd]),
                ]
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
    pass
