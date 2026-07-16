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
Map transmission lines to energy target zones. Lines mapped to a zone have
their losses (the :code:`Tx_Losses_MW` expression) counted against the
zone's energy target, analogous to how storage round-trip losses count
against the target via the *stor* operational type's rec_provision_rule.

Transmission energy-target contributions are optional: if the user has not
specified any transmission energy target inputs (no
:code:`energy_target_zone` column in :code:`transmission_lines.tab`), the
components below are simply empty and the energy target features function
as before, for projects only.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Param, Set

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values


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
    | | :code:`ENERGY_TARGET_TX_LINES`                                        |
    | | *Within*: :code:`TX_LINES`                                           |
    |                                                                         |
    | The set of transmission lines whose losses count against an energy      |
    | target.                                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`ENERGY_TARGET_TX_OPR_TMPS`                                     |
    | | *Within*: :code:`TX_OPR_TMPS`                                        |
    |                                                                         |
    | Two-dimensional set of energy-target transmission lines and their       |
    | operational timepoints.                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`ENERGY_TARGET_TX_LINES_BY_ENERGY_TARGET_ZONE`                  |
    | | *Defined over*: :code:`ENERGY_TARGET_ZONES`                           |
    | | *Within*: :code:`ENERGY_TARGET_TX_LINES`                              |
    |                                                                         |
    | Indexed set that describes the energy-target transmission lines for     |
    | each energy-target zone.                                                |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Input Params                                                            |
    +=========================================================================+
    | | :code:`tx_energy_target_zone`                                         |
    | | *Defined over*: :code:`ENERGY_TARGET_TX_LINES`                        |
    | | *Within*: :code:`ENERGY_TARGET_ZONES`                                 |
    |                                                                         |
    | The energy-target zone against which the transmission line's losses     |
    | count.                                                                  |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.ENERGY_TARGET_TX_LINES = Set(within=m.TX_LINES)

    m.ENERGY_TARGET_TX_OPR_TMPS = Set(
        within=m.TX_OPR_TMPS,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="TX_OPR_TMPS",
            index=0,
            membership_set=mod.ENERGY_TARGET_TX_LINES,
        ),
    )

    # Input Params
    ###########################################################################

    m.tx_energy_target_zone = Param(
        m.ENERGY_TARGET_TX_LINES, within=m.ENERGY_TARGET_ZONES
    )

    # Derived Sets (requires input params)
    ###########################################################################

    m.ENERGY_TARGET_TX_LINES_BY_ENERGY_TARGET_ZONE = Set(
        m.ENERGY_TARGET_ZONES,
        within=m.ENERGY_TARGET_TX_LINES,
        initialize=lambda mod, z: [
            tx
            for tx in mod.ENERGY_TARGET_TX_LINES
            if mod.tx_energy_target_zone[tx] == z
        ],
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
    tx_lines_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_lines.tab",
    )

    # Transmission energy-target contributions are optional; nothing to load
    # if the user has not specified any transmission energy target inputs
    # (no energy_target_zone column in transmission_lines.tab)
    header = pd.read_csv(tx_lines_file, sep="\t", nrows=0).columns
    if "energy_target_zone" not in header:
        return

    data_portal.load(
        filename=tx_lines_file,
        select=("transmission_line", "energy_target_zone"),
        param=(m.tx_energy_target_zone,),
    )

    data_portal.data()["ENERGY_TARGET_TX_LINES"] = {
        None: list(data_portal.data()["tx_energy_target_zone"].keys())
    }


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

    # Get the energy-target zones for transmission lines in our portfolio
    # and with zones in our energy target zone scenario
    tx_line_zones = c.execute(f"""SELECT transmission_line, energy_target_zone
        FROM
        -- Get transmission lines from portfolio only
        (SELECT transmission_line
            FROM inputs_transmission_portfolios
            WHERE transmission_portfolio_scenario_id = {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}
        ) as tx_tbl
        LEFT OUTER JOIN
        -- Get energy_target zones for those transmission lines
        (SELECT transmission_line, energy_target_zone
            FROM inputs_transmission_energy_target_zones
            WHERE transmission_energy_target_zone_scenario_id = {subscenarios.TRANSMISSION_ENERGY_TARGET_ZONE_SCENARIO_ID}
        ) as tx_energy_target_zone_tbl
        USING (transmission_line)
        -- Filter out transmission lines whose energy-target zone is not one
        -- included in our energy_target_zone_scenario_id
        WHERE energy_target_zone in (
                SELECT energy_target_zone
                    FROM inputs_geography_energy_target_zones
                    WHERE energy_target_zone_scenario_id = {subscenarios.ENERGY_TARGET_ZONE_SCENARIO_ID}
        );
        """)

    return tx_line_zones


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
    transmission_lines.tab file (to be precise, amend it).
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
    tx_line_zones = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    ).fetchall()

    # Transmission energy-target contributions are optional; only add the
    # energy_target_zone column to transmission_lines.tab if the user has
    # specified transmission energy target inputs
    if not tx_line_zones:
        return

    # Make a dict for easy access
    tx_zone_dict = dict()
    for tx, zone in tx_line_zones:
        tx_zone_dict[str(tx)] = "." if zone is None else str(zone)

    tx_lines_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_lines.tab",
    )

    with open(tx_lines_file, "r") as tx_file_in:
        reader = csv.reader(tx_file_in, delimiter="\t", lineterminator="\n")

        new_rows = list()

        # Append column header
        header = next(reader)
        header.append("energy_target_zone")
        new_rows.append(header)

        # Append correct values
        for row in reader:
            # If tx line specified, check if zone specified or not
            if row[0] in list(tx_zone_dict.keys()):
                row.append(tx_zone_dict[row[0]])
                new_rows.append(row)
            # If tx line not specified, specify no zone
            else:
                row.append(".")
                new_rows.append(row)

    with open(tx_lines_file, "w", newline="") as tx_file_out:
        writer = csv.writer(tx_file_out, delimiter="\t", lineterminator="\n")
        writer.writerows(new_rows)
