# Copyright 2016-2024 Blue Marble Analytics LLC.
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
Get contributions for each project and policy
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Param, Set, Expression, value, Reals

from gridpath.auxiliary.auxiliary import (
    get_required_subtype_modules,
    load_subtype_modules,
)
from gridpath.auxiliary.db_interface import (
    directories_to_db_values,
    import_csv,
)
from gridpath.common_functions import create_results_df
import gridpath.project.policy.compliance_types as compliance_type_init

SUPPORTED_COMPLIANCE_TYPES = [
    "f_output",
    "f_capacity",
    "flat_horizon",
    "stor_losses",
    "sod_flat_block",
    "sod_exceedance",
    "sod_stor",
]


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

    # Dynamic Inputs
    ###########################################################################

    required_compliance_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="compliance_type",
        filename="project_policy_zones",
    )

    imported_compliance_modules = load_subtype_modules(
        required_subtype_modules=required_compliance_modules,
        package="gridpath.project.policy.compliance_types",
        required_attributes=[],
    )

    m.PROJECT_POLICY_ZONES = Set(dimen=3, within=m.PROJECTS * m.POLICIES_ZONES)
    m.compliance_type = Param(
        m.PROJECT_POLICY_ZONES,
        within=SUPPORTED_COMPLIANCE_TYPES,
    )

    # Add any components specific to the PRM modules
    for comp_m in required_compliance_modules:
        imp_comp_m = imported_compliance_modules[comp_m]
        if hasattr(imp_comp_m, "add_model_components"):
            imp_comp_m.add_model_components(
                m,
                d,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            )

    def prj_policy_zone_opr_tmps_init(mod):
        tmps_by_prj = {}
        for prj, tmp in mod.PRJ_OPR_TMPS:
            tmps_by_prj.setdefault(prj, []).append(tmp)

        return [
            (prj, policy, zone, tmp)
            for (prj, policy, zone) in mod.PROJECT_POLICY_ZONES
            for tmp in tmps_by_prj.get(prj, [])
        ]

    m.PRJ_POLICY_ZONE_OPR_TMPS = Set(dimen=4, initialize=prj_policy_zone_opr_tmps_init)

    # (project, policy, zone, period, month, hour) for month-hour requirements.
    # Completely decoupled from timepoints — SOD-type compliance types use this.
    def prj_policy_zone_prds_month_hours_init(mod):
        return [
            (prj, policy, zone, prd, mn, hr)
            for (prj, policy, zone) in mod.PROJECT_POLICY_ZONES
            for (p, z, prd, mn, hr) in mod.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ
            if p == policy and z == zone
        ]

    m.PRJ_POLICY_ZONE_PRDS_MONTH_HOURS = Set(
        dimen=6, initialize=prj_policy_zone_prds_month_hours_init
    )

    # Expressions
    ###########################################################################

    def contribution_in_timepoint(mod, prj, policy, zone, tmp):
        """ """
        compliance_type = mod.compliance_type[prj, policy, zone]
        if hasattr(
            imported_compliance_modules[compliance_type], "contribution_in_timepoint"
        ):
            return imported_compliance_modules[
                compliance_type
            ].contribution_in_timepoint(mod, prj, policy, zone, tmp)
        else:
            return compliance_type_init.contribution_in_timepoint(
                mod, prj, policy, zone, tmp
            )

    m.Policy_Contribution_in_Timepoint = Expression(
        m.PRJ_POLICY_ZONE_OPR_TMPS, rule=contribution_in_timepoint
    )

    # def contribution_in_horizon(mod, prj, policy, bt, h):
    #     """
    #     """
    #     op_type = mod.operational_type[prj]
    #     if hasattr(imported_compliance_modules[op_type], "contribution_in_horizon"):
    #         return imported_compliance_modules[op_type].contribution_in_horizon(
    #             mod, prj, policy, bt, h
    #         )
    #     else:
    #         return compliance_type_init.contribution_in_horizon(mod, prj, policy, bt, h)
    #
    # m.Policy_Contribution_in_Horizon = Expression(
    #     m.PRJ_POLICY_ZONE_OPR_TMPSS, rule=contribution_in_horizon
    # )

    def contribution_in_month_hour(mod, prj, policy, zone, prd, mn, hr):
        """
        SOD-type contribution per (period, month, hour), completely decoupled
        from operational timepoints. Non-SOD types default to 0.
        """
        compliance_type = mod.compliance_type[prj, policy, zone]
        if hasattr(
            imported_compliance_modules[compliance_type], "contribution_in_month_hour"
        ):
            return imported_compliance_modules[
                compliance_type
            ].contribution_in_month_hour(mod, prj, policy, zone, prd, mn, hr)
        else:
            return compliance_type_init.contribution_in_month_hour(
                mod, prj, policy, zone, prd, mn, hr
            )

    m.Policy_Contribution_in_Month_Hour = Expression(
        m.PRJ_POLICY_ZONE_PRDS_MONTH_HOURS, rule=contribution_in_month_hour
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
            "project_policy_zones.tab",
        ),
        index=m.PROJECT_POLICY_ZONES,
        select=(
            "project",
            "policy_name",
            "policy_zone",
            "compliance_type",
        ),
        param=m.compliance_type,
    )

    project_df = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "project_policy_zones.tab",
        ),
        sep="\t",
        usecols=["project", "compliance_type"],
    )
    required_compliance_modules = [
        comp_type for comp_type in project_df.compliance_type.unique()
    ]

    imported_compliance_modules = load_subtype_modules(
        required_subtype_modules=required_compliance_modules,
        package="gridpath.project.policy.compliance_types",
        required_attributes=[],
    )

    for comp_m in required_compliance_modules:
        if hasattr(imported_compliance_modules[comp_m], "load_model_data"):
            imported_compliance_modules[comp_m].load_model_data(
                m,
                d,
                data_portal,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
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

    horizon_policies = set(
        p for (p, z, bt, h) in m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
    )

    if m.PRJ_POLICY_ZONE_OPR_TMPS and horizon_policies:
        results_columns = [
            "policy_contribution",
        ]
        data = [
            [
                prj,
                p,
                z,
                tmp,
                m.tmp_weight[tmp],
                m.hrs_in_tmp[tmp],
                m.period[tmp],
                value(m.Policy_Contribution_in_Timepoint[prj, p, z, tmp]),
            ]
            for (prj, p, z, tmp) in m.PRJ_POLICY_ZONE_OPR_TMPS
            if p in horizon_policies
        ]

        if data:
            results_df = create_results_df(
                index_columns=[
                    "project",
                    "policy_name",
                    "policy_zone",
                    "timepoint",
                    "timepoint_weight",
                    "hours_in_timepoint",
                    "period",
                ],
                results_columns=results_columns,
                data=data,
            )

            results_df.to_csv(
                os.path.join(
                    scenario_directory,
                    weather_iteration,
                    hydro_iteration,
                    availability_iteration,
                    subproblem,
                    stage,
                    "results",
                    "project_policy_zone_timepoint.csv",
                ),
                sep=",",
                index=True,
            )

    # Month-hour contributions (SOD-type compliance types only)
    if m.PRJ_POLICY_ZONE_PRDS_MONTH_HOURS:
        mh_data = [
            [
                prj,
                p,
                z,
                prd,
                mn,
                hr,
                value(m.Policy_Contribution_in_Month_Hour[prj, p, z, prd, mn, hr]),
            ]
            for (prj, p, z, prd, mn, hr) in m.PRJ_POLICY_ZONE_PRDS_MONTH_HOURS
        ]
        mh_results_df = create_results_df(
            index_columns=[
                "project",
                "policy_name",
                "policy_zone",
                "period",
                "policy_month",
                "policy_hour",
            ],
            results_columns=["contribution_mw"],
            data=mh_data,
        )
        mh_results_df.to_csv(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "results",
                "project_policy_month_hour_contributions.csv",
            ),
            sep=",",
            index=True,
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

    c = conn.cursor()

    # Get the energy-target zones for project in our portfolio and with zones in our
    # Energy target zone
    project_policy_zones = c.execute(
        f"""SELECT project, policy_name, policy_zone, compliance_type,
        f_slope, f_intercept, exceedance_values_scenario_id, sod_stor_rte
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        ) as prj_tbl
        LEFT OUTER JOIN
        -- Get energy_target zones for those projects
        (SELECT project, policy_name, policy_zone, compliance_type,
        f_slope, f_intercept, exceedance_values_scenario_id, sod_stor_rte
            FROM inputs_project_policy_zones
            WHERE project_policy_zone_scenario_id = {subscenarios.PROJECT_POLICY_ZONE_SCENARIO_ID}
        ) as prj_energy_target_zone_tbl
        USING (project)
        -- Filter out projects whose RPS zone is not one included in our
        -- energy_target_zone_scenario_id
        WHERE (policy_name, policy_zone) in (
                SELECT policy_name, policy_zone
                    FROM inputs_geography_policy_zones
                    WHERE policy_zone_scenario_id = {subscenarios.POLICY_ZONE_SCENARIO_ID}
        );
        """
    )

    return project_policy_zones


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
    project_policy_zones = get_inputs_from_database(
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
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "project_policy_zones.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "project",
                "policy_name",
                "policy_zone",
                "compliance_type",
                "f_slope",
                "f_intercept",
                "exceedance_values_scenario_id",
                "sod_stor_rte",
            ]
        )

        for row in project_policy_zones:
            replace_nulls = ["." if i is None else i for i in row]
            writer.writerow(replace_nulls)

    project_policy_zone_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "project_policy_zones.tab",
    )
    project_df = pd.read_csv(
        project_policy_zone_file,
        sep="\t",
        usecols=["compliance_type"],
    )
    required_compliance_modules = [
        comp_type for comp_type in project_df.compliance_type.dropna().unique()
    ]
    imported_compliance_modules = load_subtype_modules(
        required_subtype_modules=required_compliance_modules,
        package="gridpath.project.policy.compliance_types",
        required_attributes=[],
    )
    for comp_m in required_compliance_modules:
        if hasattr(imported_compliance_modules[comp_m], "write_model_inputs"):
            imported_compliance_modules[comp_m].write_model_inputs(
                scenario_directory=scenario_directory,
                scenario_id=scenario_id,
                subscenarios=subscenarios,
                weather_iteration=weather_iteration,
                hydro_iteration=hydro_iteration,
                availability_iteration=availability_iteration,
                subproblem=subproblem,
                stage=stage,
                conn=conn,
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
    if os.path.exists(
        os.path.join(results_directory, "project_policy_zone_timepoint.csv")
    ):
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
            which_results="project_policy_zone_timepoint",
        )

    if os.path.exists(
        os.path.join(results_directory, "project_policy_month_hour_contributions.csv")
    ):
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
            which_results="project_policy_month_hour_contributions",
        )
