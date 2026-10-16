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
Carbon credits purchased by the projects mapped to a policy zone, from the
carbon credits zones mapped to that policy zone, reduce the policy's
contributions (e.g. an emissions cap or an emissions intensity standard is
met net of purchased credits, as for the carbon cap and the performance
standard). The credits are purchased per period; a horizon's credits are
those of its period.
"""

import csv
import os.path

from pyomo.environ import Set, Expression, value

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import (
    policy_balance_contribution_components,
)
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.system.policy.generic_policy import POLICY_ZONE_PRD_DF


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
    | | :code:`POLICIES_ZONES_CARBON_CREDITS_ZONES`                           |
    | | *Within*: :code:`POLICIES_ZONES * CARBON_CREDITS_ZONES`               |
    |                                                                         |
    | The carbon credits zones whose credits count toward each policy zone.   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Total_Policy_Carbon_Credits`                                   |
    | | *Defined over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`          |
    |                                                                         |
    | The credits purchased in the horizon's period, from the mapped credits  |
    | zones, by the projects mapped to the policy zone.                       |
    +-------------------------------------------------------------------------+
    | | :code:`Total_Policy_Carbon_Credits_Contribution`                      |
    | | *Defined over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`          |
    |                                                                         |
    | The negative of the credits, added to the policy's contributions.       |
    +-------------------------------------------------------------------------+
    """
    m.POLICIES_ZONES_CARBON_CREDITS_ZONES = Set(
        dimen=3, within=m.POLICIES_ZONES * m.CARBON_CREDITS_ZONES
    )

    # The credit purchases (project, credits zone, period) that count toward
    # each requirement index, grouped in one pass
    def purchases_by_policy_zone_bln_type_hrz_init(mod):
        prjs_by_policy_zone = {}
        for prj, policy, zone in mod.PROJECT_POLICY_ZONES:
            prjs_by_policy_zone.setdefault((policy, zone), []).append(prj)
        credits_zones_by_policy_zone = {}
        for policy, zone, z in mod.POLICIES_ZONES_CARBON_CREDITS_ZONES:
            credits_zones_by_policy_zone.setdefault((policy, zone), []).append(z)

        purchases_by_req = {}
        for policy, zone, bt, h in mod.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ:
            prd = mod.period[mod.last_hrz_tmp[bt, h]]
            purchases_by_req[policy, zone, bt, h] = [
                (prj, z, prd)
                for prj in prjs_by_policy_zone.get((policy, zone), [])
                for z in credits_zones_by_policy_zone.get((policy, zone), [])
                if (prj, z, prd)
                in mod.CARBON_CREDITS_PURCHASE_PRJS_CARBON_CREDITS_ZONES_OPR_PRDS
            ]

        return purchases_by_req

    m.CARBON_CREDITS_PURCHASES_BY_POLICY_ZONE_BLN_TYPE_HRZ = Set(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        dimen=3,
        initialize=purchases_by_policy_zone_bln_type_hrz_init,
    )

    def total_carbon_credits_rule(mod, policy, zone, bt, h):
        return sum(
            mod.Project_Purchase_Carbon_Credits[prj, z, prd]
            for (
                prj,
                z,
                prd,
            ) in mod.CARBON_CREDITS_PURCHASES_BY_POLICY_ZONE_BLN_TYPE_HRZ[
                policy, zone, bt, h
            ]
        )

    m.Total_Policy_Carbon_Credits = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, rule=total_carbon_credits_rule
    )

    m.Total_Policy_Carbon_Credits_Contribution = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        rule=lambda mod, policy, zone, bt, h: -mod.Total_Policy_Carbon_Credits[
            policy, zone, bt, h
        ],
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    Purchased credits reduce the contributions toward the policy requirement.
    """
    getattr(dynamic_components, policy_balance_contribution_components).append(
        "Total_Policy_Carbon_Credits_Contribution"
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
    map_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "policy_zones_carbon_credits_zone_mapping.tab",
    )
    if os.path.exists(map_file):
        data_portal.load(filename=map_file, set=m.POLICIES_ZONES_CARBON_CREDITS_ZONES)
    else:
        data_portal.data()["POLICIES_ZONES_CARBON_CREDITS_ZONES"] = {None: []}


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
    results_columns = ["carbon_credits"]
    data = [
        [p, z, bt, h, value(m.Total_Policy_Carbon_Credits[p, z, bt, h])]
        for (p, z, bt, h) in m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ
    ]
    results_df = create_results_df(
        index_columns=[
            "policy_name",
            "policy_zone",
            "balancing_type_horizon",
            "horizon",
        ],
        results_columns=results_columns,
        data=data,
    )
    update_results_df(getattr(d, POLICY_ZONE_PRD_DF), results_df)


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
    The mapping, limited to the scenario's policy zones and carbon credits
    zones.
    """
    c = conn.cursor()
    mapping = c.execute(f"""
        SELECT policy_name, policy_zone, carbon_credits_zone
        FROM inputs_system_policy_zones_carbon_credits_zones
        WHERE policy_zones_carbon_credits_zones_scenario_id =
            {subscenarios.POLICY_ZONES_CARBON_CREDITS_ZONES_SCENARIO_ID}
        AND (policy_name, policy_zone) IN (
            SELECT policy_name, policy_zone
            FROM inputs_geography_policy_zones
            WHERE policy_zone_scenario_id = {subscenarios.POLICY_ZONE_SCENARIO_ID}
        )
        AND carbon_credits_zone IN (
            SELECT carbon_credits_zone
            FROM inputs_geography_carbon_credits_zones
            WHERE carbon_credits_zone_scenario_id =
                {subscenarios.CARBON_CREDITS_ZONE_SCENARIO_ID}
        );
        """)

    return mapping


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
    Write the mapping to policy_zones_carbon_credits_zone_mapping.tab, only
    if there are any rows.
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
    rows = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    ).fetchall()
    if not rows:
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
            "policy_zones_carbon_credits_zone_mapping.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["policy_name", "policy_zone", "carbon_credits_zone"])
        writer.writerows(rows)
