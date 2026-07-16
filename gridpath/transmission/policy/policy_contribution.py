# Copyright 2026 Sylvan Energy Analytics LLC.
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
Get contributions for each transmission line and policy. This mirrors the
project-side policy contributions (see
*gridpath.project.policy.policy_contribution*): each transmission line can
be mapped to policies/zones with a compliance type that determines how the
line contributes toward the policy requirement (e.g. its losses count
against the requirement via the *tx_losses* compliance type).
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Param, Set, Expression, value

from gridpath.auxiliary.auxiliary import (
    get_required_subtype_modules,
    load_subtype_modules,
)
from gridpath.auxiliary.db_interface import (
    directories_to_db_values,
    import_csv,
)
from gridpath.common_functions import create_results_df
import gridpath.transmission.policy.compliance_types as compliance_type_init

SUPPORTED_COMPLIANCE_TYPES = [
    "tx_losses",
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

    # Transmission policy contributions are optional; if the user has not
    # specified any transmission policy inputs (no
    # transmission_policy_zones.tab file), the components below are simply
    # empty and the policy feature functions as before, for projects only
    if tx_policy_zones_file_exists(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    ):
        required_compliance_modules = get_required_subtype_modules(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            which_type="compliance_type",
            filename="transmission_policy_zones",
        )
    else:
        required_compliance_modules = []

    imported_compliance_modules = load_subtype_modules(
        required_subtype_modules=required_compliance_modules,
        package="gridpath.transmission.policy.compliance_types",
        required_attributes=[],
    )

    m.TX_POLICY_ZONES = Set(dimen=3, within=m.TX_LINES * m.POLICIES_ZONES)
    m.tx_compliance_type = Param(
        m.TX_POLICY_ZONES,
        within=SUPPORTED_COMPLIANCE_TYPES,
    )

    # Add any components specific to the compliance type modules
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

    def tx_policy_zone_opr_tmps_init(mod):
        opr_tmps = list()
        for tx, policy, zone in mod.TX_POLICY_ZONES:
            for _tx, tmp in mod.TX_OPR_TMPS:
                if tx == _tx:
                    opr_tmps.append((tx, policy, zone, tmp))

        return opr_tmps

    m.TX_POLICY_ZONE_OPR_TMPS = Set(dimen=4, initialize=tx_policy_zone_opr_tmps_init)

    # Expressions
    ###########################################################################

    def contribution_in_timepoint(mod, tx, policy, zone, tmp):
        """ """
        compliance_type = mod.tx_compliance_type[tx, policy, zone]
        if hasattr(
            imported_compliance_modules[compliance_type], "contribution_in_timepoint"
        ):
            return imported_compliance_modules[
                compliance_type
            ].contribution_in_timepoint(mod, tx, policy, zone, tmp)
        else:
            return compliance_type_init.contribution_in_timepoint(
                mod, tx, policy, zone, tmp
            )

    m.Tx_Policy_Contribution_in_Timepoint = Expression(
        m.TX_POLICY_ZONE_OPR_TMPS, rule=contribution_in_timepoint
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
    # Transmission policy contributions are optional; nothing to load if the
    # user has not specified any transmission policy inputs
    if not tx_policy_zones_file_exists(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    ):
        return

    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "transmission_policy_zones.tab",
        ),
        index=m.TX_POLICY_ZONES,
        select=(
            "transmission_line",
            "policy_name",
            "policy_zone",
            "compliance_type",
        ),
        param=m.tx_compliance_type,
    )

    tx_df = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "transmission_policy_zones.tab",
        ),
        sep="\t",
        usecols=["transmission_line", "compliance_type"],
    )
    required_compliance_modules = [
        comp_type for comp_type in tx_df.compliance_type.unique()
    ]

    imported_compliance_modules = load_subtype_modules(
        required_subtype_modules=required_compliance_modules,
        package="gridpath.transmission.policy.compliance_types",
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


def tx_policy_zones_file_exists(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    return os.path.exists(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "transmission_policy_zones.tab",
        )
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

    if m.TX_POLICY_ZONE_OPR_TMPS and horizon_policies:
        results_columns = [
            "policy_contribution",
        ]
        data = [
            [
                tx,
                p,
                z,
                tmp,
                m.tmp_weight[tmp],
                m.hrs_in_tmp[tmp],
                m.period[tmp],
                value(m.Tx_Policy_Contribution_in_Timepoint[tx, p, z, tmp]),
            ]
            for (tx, p, z, tmp) in m.TX_POLICY_ZONE_OPR_TMPS
            if p in horizon_policies
        ]

        if data:
            results_df = create_results_df(
                index_columns=[
                    "transmission_line",
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
                    "transmission_policy_zone_timepoint.csv",
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

    # Get the policy zones for transmission lines in our portfolio and with
    # zones in our policy zone scenario
    transmission_policy_zones = c.execute(
        f"""SELECT transmission_line, policy_name, policy_zone, compliance_type
        FROM
        -- Get transmission lines from portfolio only
        (SELECT transmission_line
            FROM inputs_transmission_portfolios
            WHERE transmission_portfolio_scenario_id = {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}
        ) as tx_tbl
        LEFT OUTER JOIN
        -- Get policy zones for those transmission lines
        (SELECT transmission_line, policy_name, policy_zone, compliance_type
            FROM inputs_transmission_policy_zones
            WHERE transmission_policy_zone_scenario_id = {subscenarios.TRANSMISSION_POLICY_ZONE_SCENARIO_ID}
        ) as tx_policy_zone_tbl
        USING (transmission_line)
        -- Filter out transmission lines whose policy zone is not one
        -- included in our policy_zone_scenario_id
        WHERE (policy_name, policy_zone) in (
                SELECT policy_name, policy_zone
                    FROM inputs_geography_policy_zones
                    WHERE policy_zone_scenario_id = {subscenarios.POLICY_ZONE_SCENARIO_ID}
        );
        """
    )

    return transmission_policy_zones


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
    transmission_policy_zones = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    ).fetchall()

    # Transmission policy contributions are optional; only write the file if
    # the user has specified transmission policy inputs
    if not transmission_policy_zones:
        return

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "transmission_policy_zones.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "transmission_line",
                "policy_name",
                "policy_zone",
                "compliance_type",
            ]
        )

        for row in transmission_policy_zones:
            replace_nulls = ["." if i is None else i for i in row]
            writer.writerow(replace_nulls)


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
        os.path.join(results_directory, "transmission_policy_zone_timepoint.csv")
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
            which_results="transmission_policy_zone_timepoint",
        )
