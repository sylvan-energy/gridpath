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
Capacity transfers between PRM zones.

Note that the capacity transfer variable is not at the transmission line level -- it
is defined at the "capacity transfer link" level, with the transmission line topology
used to limit total transfers on each link.

"""

import csv
import os.path
import pandas as pd
from pyomo.environ import (
    Set,
    Param,
    Var,
    Constraint,
    NonNegativeReals,
    Expression,
    value,
)

from db.common_functions import spin_on_database_lock, spin_on_database_lock_generic
from gridpath.auxiliary.db_interface import (
    directories_to_db_values,
)
from gridpath.auxiliary.dynamic_components import prm_balance_provision_components
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
    The following Pyomo model components are defined in this module:

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`min_transfer_powerunit`                                       |
    | | *Defined over*: :code:`PRM_ZONES_CAPACITY_TRANSFER_ZONES, PERIODS`    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Minimum capacity transfer between zones in period.                      |
    +-------------------------------------------------------------------------+
    | | :code:`max_transfer_powerunit`                                       |
    | | *Defined over*: :code:`PRM_ZONES_CAPACITY_TRANSFER_ZONES, PERIODS`    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`infinity`                                                  |
    |                                                                         |
    | Maximum capacity transfer between zones in period.                      |
    +-------------------------------------------------------------------------+
    | | :code:`capacity_transfer_cost_per_powerunit_yr`                       |
    | | *Defined over*: :code:`PRM_ZONES_CAPACITY_TRANSFER_ZONES, PERIODS`    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Minimum capacity transfer between zones in period.                      |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`PRM_TX_LINES`                                                  |
    |                                                                         |
    | The set of PRM-relevant transmission lines.                             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`prm_zone_from`                                                 |
    | | *Defined over*: :code:`PRM_TX_LINES`                                  |
    | | *Within*: :code:`PRM_ZONES`                                           |
    |                                                                         |
    | The transmission line's starting PRM zone.                              |
    +-------------------------------------------------------------------------+
    | | :code:`prm_zone_to`                                                  |
    | | *Defined over*: :code:`TX_LINES`                                      |
    | | *Within*: :code:`PRM_ZONES`                                           |
    |                                                                         |
    | The transmission line's ending PRM zone.                                |
    +-------------------------------------------------------------------------+
    """
    # Exogenous param limits
    m.min_transfer_powerunit = Param(
        m.PRM_ZONES_CAPACITY_TRANSFER_ZONES,
        m.PERIODS,
        within=NonNegativeReals,
        default=0,
    )
    m.max_transfer_powerunit = Param(
        m.PRM_ZONES_CAPACITY_TRANSFER_ZONES,
        m.PERIODS,
        within=NonNegativeReals,
        default=float("inf"),
    )

    # Costs
    m.capacity_transfer_cost_per_powerunit_yr = Param(
        m.PRM_ZONES_CAPACITY_TRANSFER_ZONES,
        m.PERIODS,
        within=NonNegativeReals,
        default=0,
    )

    # Endogenous limits based on transmission links
    m.PRM_TX_LINES = Set(within=m.TX_LINES)

    m.prm_zone_from = Param(m.PRM_TX_LINES, within=m.PRM_ZONES)
    m.prm_zone_to = Param(m.PRM_TX_LINES, within=m.PRM_ZONES)

    # Transfers between pairs of zones in each period
    m.Transfer_Capacity_Contribution = Var(
        m.PRM_ZONES_CAPACITY_TRANSFER_ZONES,
        m.PERIODS,
        within=NonNegativeReals,
        initialize=0,
    )

    # ### Constraints ### #
    # Constraint based on the params
    def min_transfer_constraint_rule(mod, prm_z_from, prm_z_to, prd):
        return (
            mod.Transfer_Capacity_Contribution[prm_z_from, prm_z_to, prd]
            >= mod.min_transfer_powerunit[prm_z_from, prm_z_to, prd]
        )

    m.Capacity_Transfer_Min_Limit_Constraint = Constraint(
        m.PRM_ZONES_CAPACITY_TRANSFER_ZONES,
        m.PERIODS,
        rule=min_transfer_constraint_rule,
    )

    def max_transfer_constraint_rule(mod, prm_z_from, prm_z_to, prd):
        return (
            mod.Transfer_Capacity_Contribution[prm_z_from, prm_z_to, prd]
            <= mod.max_transfer_powerunit[prm_z_from, prm_z_to, prd]
        )

    m.Capacity_Transfer_Max_Limit_Constraint = Constraint(
        m.PRM_ZONES_CAPACITY_TRANSFER_ZONES,
        m.PERIODS,
        rule=max_transfer_constraint_rule,
    )

    # Constrain based on the available transmission
    def transfer_tx_limits_constraint_rule(mod, prm_z_from, prm_z_to, prd):
        # Sum of max capacity of lines with prm_zone_to == z plus
        # Negative sum of min capacity of lines with prm_zone_from == z
        return mod.Transfer_Capacity_Contribution[prm_z_from, prm_z_to, prd] <= sum(
            mod.Tx_Max_Capacity_MW[tx, op]
            for (tx, op) in mod.TX_OPR_PRDS
            if op == prd
            and tx in mod.PRM_TX_LINES
            and mod.prm_zone_from[tx] == prm_z_from
            and mod.prm_zone_to[tx] == prm_z_to
        ) + -sum(
            mod.Tx_Min_Capacity_MW[tx, op]
            for (tx, op) in mod.TX_OPR_PRDS
            if op == prd
            and tx in mod.PRM_TX_LINES
            and mod.prm_zone_from[tx] == prm_z_to
            and mod.prm_zone_to[tx] == prm_z_from
        )

    m.Capacity_Transfer_Tx_Limits_Constraint = Constraint(
        m.PRM_ZONES_CAPACITY_TRANSFER_ZONES,
        m.PERIODS,
        rule=transfer_tx_limits_constraint_rule,
    )

    # Constrain to simple capacity contributions only (no contribution from ELCC
    # surface)
    m.PRM_FROM_ZONES = Set(
        within=m.PRM_ZONES,
        initialize=lambda mod: sorted(
            list(set([z for (z, z_to) in mod.PRM_ZONES_CAPACITY_TRANSFER_ZONES])),
        ),
    )

    def transfer_simple_capacity_only_rule(mod, prm_z, prd):
        return (
            sum(
                mod.Transfer_Capacity_Contribution[prm_z_from, prm_z_to, prd]
                for (prm_z_from, prm_z_to) in mod.PRM_ZONES_CAPACITY_TRANSFER_ZONES
                if prm_z_from == prm_z
            )
            <= mod.Total_PRM_Simple_Contribution_MW[prm_z, prd]
        )

    m.Transfer_Simple_Contributions_Only_Constraint = Constraint(
        m.PRM_FROM_ZONES, m.PERIODS, rule=transfer_simple_capacity_only_rule
    )

    ####################################################################################
    # Get the total transfers for each zone to add to the PRM balance
    def total_transfers_from_init(mod, z, prd):
        return -sum(
            mod.Transfer_Capacity_Contribution[z, t_z, prd]
            for (zone, t_z) in mod.PRM_ZONES_CAPACITY_TRANSFER_ZONES
            if zone == z
        )

    m.Total_Transfers_from_PRM_Zone = Expression(
        m.PRM_ZONES, m.PERIODS, initialize=total_transfers_from_init
    )

    def total_transfers_to_init(mod, t_z, prd):
        return sum(
            mod.Transfer_Capacity_Contribution[z, t_z, prd]
            for (z, to_zone) in mod.PRM_ZONES_CAPACITY_TRANSFER_ZONES
            if to_zone == t_z
        )

    m.Total_Transfers_to_PRM_Zone = Expression(
        m.PRM_ZONES, m.PERIODS, initialize=total_transfers_to_init
    )

    # Add to PRM balance constraint
    getattr(d, prm_balance_provision_components).append("Total_Transfers_from_PRM_Zone")
    getattr(d, prm_balance_provision_components).append("Total_Transfers_to_PRM_Zone")

    # Costs incurred to transfer capacity; this is at the link-level; costs
    # will be aggregated in the objective function module
    def capacity_transfer_costs_rule(m, prm_z_from, prm_z_to, prd):
        return (
            m.Transfer_Capacity_Contribution[prm_z_from, prm_z_to, prd]
            * m.capacity_transfer_cost_per_powerunit_yr[prm_z_from, prm_z_to, prd]
        )

    m.Capacity_Transfer_Costs_Per_Yr_in_Period = Expression(
        m.PRM_ZONES_CAPACITY_TRANSFER_ZONES,
        m.PERIODS,
        initialize=capacity_transfer_costs_rule,
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
    :param stage:
    :param stage:
    :return:
    """
    # TODO: select only relevant columns once costs are added to this file
    #  and rename file
    limits_tab_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "prm_capacity_transfer_params.tab",
    )
    if os.path.exists(limits_tab_file):
        data_portal.load(
            filename=limits_tab_file,
            param=(
                m.min_transfer_powerunit,
                m.max_transfer_powerunit,
                m.capacity_transfer_cost_per_powerunit_yr,
            ),
        )

    prm_transmission_lines_tab_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "prm_transmission_lines.tab",
    )
    if os.path.exists(prm_transmission_lines_tab_file):
        data_portal.load(
            filename=prm_transmission_lines_tab_file,
            index=m.PRM_TX_LINES,
            param=(
                m.prm_zone_from,
                m.prm_zone_to,
            ),
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
    limits = c1.execute(f"""
        SELECT prm_zone, prm_capacity_transfer_zone, period, 
        min_transfer_powerunit, max_transfer_powerunit, capacity_transfer_cost_per_powerunit_yr
        FROM inputs_transmission_prm_capacity_transfer_params
        JOIN
        (SELECT prm_zone, prm_capacity_transfer_zone
        FROM inputs_transmission_prm_capacity_transfers
        WHERE prm_capacity_transfer_scenario_id = {subscenarios.PRM_CAPACITY_TRANSFER_SCENARIO_ID}) as relevant_zones
        using (prm_zone, prm_capacity_transfer_zone)
        WHERE prm_capacity_transfer_params_scenario_id = 
        {subscenarios.PRM_CAPACITY_TRANSFER_PARAMS_SCENARIO_ID}
        AND prm_zone IN
        (SELECT prm_zone FROM inputs_geography_prm_zones
        WHERE prm_zone_scenario_id = {subscenarios.PRM_ZONE_SCENARIO_ID})
        AND prm_capacity_transfer_zone IN
        (SELECT prm_zone FROM inputs_geography_prm_zones
        WHERE prm_zone_scenario_id = {subscenarios.PRM_ZONE_SCENARIO_ID});
        """)

    c2 = conn.cursor()
    transmission_lines = c2.execute(
        """SELECT transmission_line, prm_zone_from, prm_zone_to
            FROM inputs_transmission_prm_zones
            WHERE transmission_prm_zone_scenario_id = {prm_z}
        AND transmission_line IN
        (SELECT transmission_line FROM inputs_transmission_portfolios
        WHERE transmission_portfolio_scenario_id = {portfolio})
        AND prm_zone_from IN
        (SELECT prm_zone FROM inputs_geography_prm_zones
        WHERE prm_zone_scenario_id = {prm_zone})
        AND prm_zone_to IN
        (SELECT prm_zone FROM inputs_geography_prm_zones
        WHERE prm_zone_scenario_id = {prm_zone});""".format(
            prm_z=subscenarios.TRANSMISSION_PRM_ZONE_SCENARIO_ID,
            portfolio=subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID,
            prm_zone=subscenarios.PRM_ZONE_SCENARIO_ID,
        )
    )

    # TODO: allow Tx lines with no PRM zones from and to specified, that are only
    #  used for say, reliability capacity exchanges; they would need a different
    #  operational type (no power transfer); the decisions also won't be made at the
    #  transmission line level, but the capacity will limit the aggregate transfer
    #  between PRM zones, so there won't be flow variables

    return limits, transmission_lines


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
    transmission_lines.tab file.
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

    limits, transmission_lines = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    limits = limits.fetchall()
    if limits:
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "prm_capacity_transfer_params.tab",
            ),
            "w",
            newline="",
        ) as limits_tab_file:
            writer = csv.writer(limits_tab_file, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(
                [
                    "prm_zone",
                    "prm_capacity_transfer_zone",
                    "period",
                    "min_transfer_powerunit",
                    "max_transfer_powerunit",
                    "capacity_transfer_cost_per_powerunit_yr",
                ]
            )

            for row in limits:
                replace_nulls = ["." if i is None else i for i in row]
                writer.writerow(replace_nulls)

    transmission_lines = transmission_lines.fetchall()
    if transmission_lines:
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "prm_transmission_lines.tab",
            ),
            "w",
            newline="",
        ) as transmission_lines_tab_file:
            writer = csv.writer(
                transmission_lines_tab_file, delimiter="\t", lineterminator="\n"
            )

            # Write header
            writer.writerow(
                [
                    "transmission_line",
                    "prm_zone_from",
                    "prm_zone_to",
                ]
            )

            for row in transmission_lines:
                replace_nulls = ["." if i is None else i for i in row]
                writer.writerow(replace_nulls)


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
        "capacity_contribution_transferred_from_mw",
        "capacity_contribution_transferred_to_mw",
    ]
    data = [
        [
            z,
            p,
            value(m.Total_Transfers_from_PRM_Zone[z, p]),
            value(m.Total_Transfers_to_PRM_Zone[z, p]),
        ]
        for (z, p) in m.PRM_ZONE_PERIODS_WITH_REQUIREMENT
    ]
    results_df = create_results_df(
        index_columns=["prm_zone", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PRM_ZONE_PRD_DF), results_df)

    # PRM zone to PRM zone capacity transfers
    with open(
        os.path.join(
            scenario_directory,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "capacity_contribution_transfers.csv",
        ),
        "w",
        newline="",
    ) as results_file:
        writer = csv.writer(results_file)
        writer.writerow(
            [
                "prm_zone_from",
                "prm_zone_to",
                "period",
                "capacity_transfer_mw",
                "capacity_transfer_cost_per_yr_in_period",
            ]
        )
        for z, t_z, p in m.Transfer_Capacity_Contribution:
            writer.writerow(
                [
                    z,
                    t_z,
                    p,
                    value(m.Transfer_Capacity_Contribution[z, t_z, p]),
                    value(m.Capacity_Transfer_Costs_Per_Yr_in_Period[z, t_z, p]),
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
    :param c:
    :param db:
    :param results_directory:
    :param quiet:
    :return:
    """
    if not quiet:
        print("PRM capacity transfers")

    df = pd.read_csv(
        os.path.join(results_directory, "capacity_contribution_transfers.csv")
    )
    df["scenario_id"] = scenario_id
    df["subproblem_id"] = subproblem
    df["stage_id"] = stage

    spin_on_database_lock_generic(
        command=df.to_sql(
            name="results_system_capacity_transfers",
            con=db,
            if_exists="append",
            index=False,
        )
    )
