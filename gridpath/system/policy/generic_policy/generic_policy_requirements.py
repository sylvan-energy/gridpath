# Copyright 2016-2024 Blue Marble Analytics LLC.
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
# See the License for the gitspecific language governing permissions and
# limitations under the License.

"""
Requirements for each policy and policy zone
"""

import csv
import os.path

from pyomo.environ import Set, Param, Reals, NonNegativeReals, Expression, value, Any

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.common_functions import create_results_df, update_results_df

from gridpath.system.policy.generic_policy import POLICY_ZONE_PRD_DF, POLICY_MH_DF


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

    m.POLICIES = Set(
        within=Any,
        initialize=lambda mod: sorted(list(set([p for (p, z) in mod.POLICIES_ZONES]))),
    )
    m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ = Set(
        dimen=4, within=m.POLICIES_ZONES * m.BLN_TYPE_HRZS
    )

    # Target specified as a scalar
    m.policy_requirement = Param(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, within=Reals, default=0
    )

    # Target specified as a function of load
    m.policy_requirement_f_load_coeff = Param(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        within=NonNegativeReals,
        default=0,
    )

    # Load zones included in the function of load policy requirement
    m.POLICIES_ZONE_LOAD_ZONES = Set(dimen=3, within=m.POLICIES_ZONES * m.LOAD_ZONES)
    m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ = Set(dimen=5)
    m.policy_month_hour_requirement = Param(
        m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ, within=NonNegativeReals, default=0
    )
    m.POLICIES_ZONE_LOAD_ZONES_MONTH_HOUR = Set(dimen=5)

    def policy_requirement_rule(mod, policy_name, policy_zone, bt, h):
        """
        The policy target consists of two additive components: an energy term
        and a 'percent of load x load' term, where a mapping between the policy
        zone and the load zones whose load to consider must be specified.
        Either the energy target or the percent target can be omitted (they
        default to 0). If a mapping is not specified, the
        'percent of load x load' is 0.
        """
        # If we have a map of policy zones to load zones, apply the percentage
        # target; if no map provided, the fraction_target is 0
        if mod.POLICIES_ZONE_LOAD_ZONES:
            total_bt_horizon_load_modifier_adjusted_load = sum(
                mod.LZ_Modified_Load_in_Tmp[lz, tmp]
                * mod.hrs_in_tmp[tmp]
                * mod.tmp_weight[tmp]
                for (
                    _policy_name,
                    _policy_requirement_zone,
                    lz,
                ) in mod.POLICIES_ZONE_LOAD_ZONES
                if (_policy_name, _policy_requirement_zone)
                == (policy_name, policy_zone)
                for tmp in mod.TMPS
                if tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
            )
            fraction_target = (
                mod.policy_requirement_f_load_coeff[policy_name, policy_zone, bt, h]
                * total_bt_horizon_load_modifier_adjusted_load
            )
        else:
            fraction_target = 0

        return mod.policy_requirement[policy_name, policy_zone, bt, h] + fraction_target

    m.Policy_Zone_Horizon_Requirement = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        rule=policy_requirement_rule,
    )

    def policy_month_hour_requirement_rule(
        mod, policy_name, policy_zone, period, mn, hr
    ):
        return mod.policy_month_hour_requirement[
            policy_name, policy_zone, period, mn, hr
        ]

    m.Policy_Zone_Month_Hour_Requirement = Expression(
        m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ,
        rule=policy_month_hour_requirement_rule,
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
    input_dir = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
    )

    horizon_policy_zones = set()
    month_hour_policy_zones = set()

    # Load horizon requirements if present
    policy_requirements_file = os.path.join(input_dir, "policy_requirements.tab")
    if os.path.exists(policy_requirements_file):
        data_portal.load(
            filename=policy_requirements_file,
            index=m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
            param=(m.policy_requirement, m.policy_requirement_f_load_coeff),
            select=(
                "policy_name",
                "policy_zone",
                "balancing_type",
                "horizon",
                "policy_requirement",
                "policy_requirement_f_load_coeff",
            ),
        )
        with open(policy_requirements_file, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                horizon_policy_zones.add((row["policy_name"], row["policy_zone"]))
    else:
        data_portal.data()["POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ"] = {None: []}

    # Load month-hour requirements if present
    mh_requirements_file = os.path.join(input_dir, "policy_month_hour_requirements.tab")
    if os.path.exists(mh_requirements_file):
        data_portal.load(
            filename=mh_requirements_file,
            index=m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ,
            param=m.policy_month_hour_requirement,
        )
        with open(mh_requirements_file, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                month_hour_policy_zones.add((row["policy_name"], row["policy_zone"]))
    else:
        data_portal.data()["POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ"] = {None: []}

    # Validate no policy name appears in both horizon and month-hour requirements
    horizon_policies = {p for (p, z) in horizon_policy_zones}
    month_hour_policies = {p for (p, z) in month_hour_policy_zones}
    overlap = horizon_policies.intersection(month_hour_policies)
    if overlap:
        overlap_fmt = ", ".join(sorted(overlap))
        raise ValueError(
            "A policy can be either horizon or month-hour based, not both. "
            f"Found overlaps for: {overlap_fmt}"
        )

    data_portal.data()["POLICIES_ZONE_LOAD_ZONES_MONTH_HOUR"] = {None: []}

    # Load zone map for horizon percent-of-load targets if present
    map_filename = os.path.join(input_dir, "policy_zone_load_zone_map.tab")
    if os.path.exists(map_filename):
        data_portal.load(filename=map_filename, set=m.POLICIES_ZONE_LOAD_ZONES)
    else:
        data_portal.data()["POLICIES_ZONE_LOAD_ZONES"] = {None: []}


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
    policy_requirements = c.execute(
        """SELECT policy_name, policy_zone, balancing_type_horizon, horizon, 
        policy_requirement, policy_requirement_f_load_coeff
        FROM inputs_system_policy_requirements
        JOIN
        (SELECT balancing_type_horizon, horizon
        FROM inputs_temporal_horizons
        WHERE temporal_scenario_id = {}) as relevant_horizons
        USING (balancing_type_horizon, horizon)
        JOIN
        (SELECT policy_zone
        FROM inputs_geography_policy_zones
        WHERE policy_zone_scenario_id = {}) as relevant_zones
        using (policy_zone)
        WHERE policy_requirement_scenario_id = {}
        AND subproblem_id = {}
        AND stage_id = {};
        """.format(
            subscenarios.TEMPORAL_SCENARIO_ID,
            subscenarios.POLICY_ZONE_SCENARIO_ID,
            subscenarios.POLICY_REQUIREMENT_SCENARIO_ID,
            subproblem,
            stage,
        )
    )

    # Get any policy zone to load zone mapping for the percent target
    c2 = conn.cursor()
    lz_mapping = c2.execute(
        """SELECT policy_name, policy_zone, load_zone
        FROM inputs_system_policy_requirements_load_zone_map
        JOIN
        (SELECT policy_name, policy_zone
        FROM inputs_geography_policy_zones
        WHERE policy_zone_scenario_id = {}) as relevant_zones
        USING (policy_name, policy_zone)
        WHERE policy_requirement_scenario_id = {}
        """.format(
            subscenarios.POLICY_ZONE_SCENARIO_ID,
            subscenarios.POLICY_REQUIREMENT_SCENARIO_ID,
        )
    )

    c3 = conn.cursor()
    month_hour_policy_requirements = c3.execute(
        """SELECT policy_name, policy_zone, period, policy_month, policy_hour,
        policy_requirement
        FROM inputs_system_policy_month_hour_requirements
        JOIN
        (SELECT DISTINCT period
        FROM inputs_temporal
        WHERE temporal_scenario_id = {}
        AND subproblem_id = {}
        AND stage_id = {}) as relevant_periods
        USING (period)
        JOIN
        (SELECT policy_zone
        FROM inputs_geography_policy_zones
        WHERE policy_zone_scenario_id = {}) as relevant_zones
        using (policy_zone)
        WHERE policy_requirement_scenario_id = {};
        """.format(
            subscenarios.TEMPORAL_SCENARIO_ID,
            subproblem,
            stage,
            subscenarios.POLICY_ZONE_SCENARIO_ID,
            subscenarios.POLICY_REQUIREMENT_SCENARIO_ID,
        )
    )

    return policy_requirements, lz_mapping, month_hour_policy_requirements


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
    # Validation to be added
    # policy_requirements = get_inputs_from_database(
    #     scenario_id, subscenarios, subproblem, stage, conn)


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
    policy_requirements.tab file.
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
        policy_requirements,
        lz_mapping,
        month_hour_policy_requirements,
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

    horizon_rows = [row for row in policy_requirements]
    if horizon_rows:
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "policy_requirements.tab",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(
                [
                    "policy_name",
                    "policy_zone",
                    "balancing_type",
                    "horizon",
                    "policy_requirement",
                    "policy_requirement_f_load_coeff",
                ]
            )

            for row in horizon_rows:
                # It's OK if targets are not specified; they default to 0
                writer.writerow(["." if i is None else i for i in row])

    month_hour_rows = [row for row in month_hour_policy_requirements]
    if month_hour_rows:
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "policy_month_hour_requirements.tab",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(
                [
                    "policy_name",
                    "policy_zone",
                    "period",
                    "policy_month",
                    "policy_hour",
                    "policy_requirement",
                ]
            )
            for row in month_hour_rows:
                replace_nulls = ["." if i is None else i for i in row]
                writer.writerow(replace_nulls)

    # Write the policy-zone to load zone map file for the policy percent
    # target if there are any mappings only
    policy_zone_lz_map_list = [row for row in lz_mapping]
    if policy_zone_lz_map_list:
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "policy_zone_load_zone_map.tab",
            ),
            "w",
            newline="",
        ) as policy_zone_lz_map_tab_file:
            writer = csv.writer(
                policy_zone_lz_map_tab_file, delimiter="\t", lineterminator="\n"
            )

            # Write header
            writer.writerow(["policy_name", "policy_zone", "load_zone"])
            for row in policy_zone_lz_map_list:
                writer.writerow(["." if i is None else i for i in row])


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

    if m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ:
        results_columns = [
            "policy_requirement",
        ]
        data = [
            [
                p,
                z,
                bt,
                h,
                m.policy_requirement[p, z, bt, h],
            ]
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

    if m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ:
        results_columns = ["policy_month_hour_requirement"]
        data = [
            [p, z, prd, mn, hr, m.policy_month_hour_requirement[p, z, prd, mn, hr]]
            for (p, z, prd, mn, hr) in m.POLICIES_ZONE_PRDS_MONTH_HOURS_WITH_REQ
        ]
        results_df = create_results_df(
            index_columns=[
                "policy_name",
                "policy_zone",
                "period",
                "policy_month",
                "policy_hour",
            ],
            results_columns=results_columns,
            data=data,
        )
        update_results_df(getattr(d, POLICY_MH_DF), results_df)
