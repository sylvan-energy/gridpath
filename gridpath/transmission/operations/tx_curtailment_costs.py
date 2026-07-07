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
This is a Tx-line-level module that applies a curtailment cost to
transmission losses, analogous to how curtailment cost is applied to
round-trip storage losses (see the *stor* operational type). This is to
prevent unwanted behavior such as the optimization using transmission losses
to avoid curtailment cost, which happen because losses are calculated based
on a >= constraint.

Losses are taken from the operational-type-agnostic ``Tx_Losses_LZ_From_MW`` and
``Tx_Losses_LZ_To_MW`` expressions, so this applies to losses regardless of
which operational type produced them (currently *tx_simple* and
*tx_simple_binary*).
"""

import os.path
import pandas as pd
from pyomo.environ import Set, Param, Expression, NonNegativeReals

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)


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
    | | :code:`TX_CURTAILMENT_COST_TX_LINE_PRDS`                              |
    | | *Within*: :code:`TX_LINES x PERIODS`                                  |
    |                                                                         |
    | The two-dimensional set of transmission lines for which a curtailment   |
    | cost is incurred along with the periods in which it applies.            |
    +-------------------------------------------------------------------------+
    | | :code:`TX_CURTAILMENT_COST_TX_LINES`                                  |
    | | *Within*: :code:`TX_LINES`                                            |
    |                                                                         |
    | The set of transmission lines for which a curtailment cost is incurred  |
    | in at least one period.                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`TX_CURTAILMENT_COST_TX_LINE_OPR_TMPS`                          |
    | | *Within*: :code:`TX_OPR_TMPS`                                         |
    |                                                                         |
    | The two-dimensional set of curtailment-cost transmission lines and      |
    | their operational timepoints.                                           |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Params                                                                  |
    +=========================================================================+
    | | :code:`tx_curtailment_cost_per_powerunithour`                         |
    | | *Defined over*: :code:`TX_CURTAILMENT_COST_TX_LINE_PRDS`              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The transmission line's cost of curtailment per power-unit-hour of      |
    | losses in a given period.                                               |
    +-------------------------------------------------------------------------+
    | | :code:`tx_losses_factor_curtailment`                                  |
    | | *Defined over*: :code:`TX_LINES`                                      |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The fraction of transmission losses that count against curtailment.     |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.TX_CURTAILMENT_COST_TX_LINE_PRDS = Set(dimen=2, within=m.TX_LINES * m.PERIODS)
    m.TX_CURTAILMENT_COST_TX_LINES = Set(
        within=m.TX_LINES,
        initialize=lambda mod: sorted(
            list(set([tx for (tx, prd) in mod.TX_CURTAILMENT_COST_TX_LINE_PRDS]))
        ),
    )

    m.TX_CURTAILMENT_COST_TX_LINE_OPR_TMPS = Set(
        dimen=2,
        within=m.TX_OPR_TMPS,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="TX_OPR_TMPS",
            index=0,
            membership_set=mod.TX_CURTAILMENT_COST_TX_LINES,
        ),
    )

    # Params
    ###########################################################################

    m.tx_curtailment_cost_per_powerunithour = Param(
        m.TX_CURTAILMENT_COST_TX_LINE_PRDS, within=NonNegativeReals, default=0
    )

    m.tx_losses_factor_curtailment = Param(m.TX_LINES, default=1)

    # Expressions
    ###########################################################################

    def tx_curtailment_cost_rule(mod, line, tmp):
        """
        Apply curtailment cost to transmission losses to avoid using them as
        a way to avoid curtailment cost of variable projects (increasing
        load and making the VERs look like they have been delivered). This
        is similar to the storage round-trip-loss curtailment cost (see the
        *stor* operational type).

        Downstream this is summed over all timepoints, so losses on the line
        (from either flow direction) will incur the curtailment cost. By
        default all losses incur the curtailment cost, but this can be
        derated with the tx_losses_factor_curtailment parameter (default of
        1).
        """
        return (
            (mod.Tx_Losses_LZ_From_MW[line, tmp] + mod.Tx_Losses_LZ_To_MW[line, tmp])
            * mod.tx_curtailment_cost_per_powerunithour[line, mod.period[tmp]]
            * mod.tx_losses_factor_curtailment[line]
        )

    m.Tx_Curtailment_Cost = Expression(
        m.TX_CURTAILMENT_COST_TX_LINE_OPR_TMPS, rule=tx_curtailment_cost_rule
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

    # Losses-factor-curtailment derate, by transmission line (from
    # transmission_lines.tab, alongside the other operational chars)
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
    tx_lines_df = pd.read_csv(
        tx_lines_file,
        sep="\t",
        usecols=["transmission_line", "tx_losses_factor_curtailment"],
    )
    losses_factor_curtailment_raw = dict(
        zip(
            tx_lines_df["transmission_line"],
            tx_lines_df["tx_losses_factor_curtailment"],
        )
    )
    data_portal.data()["tx_losses_factor_curtailment"] = {
        line: float(losses_factor_curtailment_raw[line])
        for line in losses_factor_curtailment_raw
        if losses_factor_curtailment_raw[line] != "."
    }

    # Curtailment costs (by transmission line/period)
    tx_curtailment_cost_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_curtailment_cost.tab",
    )
    if os.path.exists(tx_curtailment_cost_file):
        periods_file = os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "periods.tab",
        )
        periods_df = pd.read_csv(periods_file, sep="\t")
        prd_set = set(periods_df["period"])

        curtailment_df = pd.read_csv(tx_curtailment_cost_file, sep="\t").set_index(
            ["transmission_line", "period"]
        )
        curtailment_tx_idx_list = []
        curtailment_by_idx_dict = {}

        for idx, val in curtailment_df.iterrows():
            tx, prd = idx
            if prd == 0:
                for _prd in sorted(list(prd_set)):
                    curtailment_tx_idx_list.append((tx, _prd))
                    curtailment_by_idx_dict[tx, _prd] = curtailment_df.loc[tx, prd][
                        "tx_curtailment_cost_per_powerunithour"
                    ]
            else:
                curtailment_tx_idx_list.append((tx, prd))
                curtailment_by_idx_dict[tx, prd] = curtailment_df.loc[tx, prd][
                    "tx_curtailment_cost_per_powerunithour"
                ]
        data_portal.data()["TX_CURTAILMENT_COST_TX_LINE_PRDS"] = {
            None: curtailment_tx_idx_list
        }
        data_portal.data()[
            "tx_curtailment_cost_per_powerunithour"
        ] = curtailment_by_idx_dict


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
    tx_curtailment_cost = c.execute(f"""
        SELECT transmission_line, period, tx_curtailment_cost_per_powerunithour
        FROM inputs_transmission_portfolios
        -- select the correct operational characteristics subscenario
        INNER JOIN
        (SELECT transmission_line, tx_curtailment_cost_scenario_id
        FROM inputs_transmission_operational_chars
        WHERE transmission_operational_chars_scenario_id = {subscenarios.TRANSMISSION_OPERATIONAL_CHARS_SCENARIO_ID}
        ) AS op_char
        USING (transmission_line)
        -- select only matching transmission lines
        INNER JOIN
        inputs_transmission_curtailment_cost
        USING (transmission_line, tx_curtailment_cost_scenario_id)
        -- Get only the subset of transmission lines in the portfolio based
        -- on the transmission_portfolio_scenario_id
        WHERE transmission_portfolio_scenario_id = {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}
        AND ((
            period in (
            SELECT DISTINCT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            )
            AND period in (
                  SELECT DISTINCT period
                  FROM inputs_temporal
                  WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                  AND subproblem_id = {subproblem}
               )
            )
            OR period = 0 -- for all periods
            )
        """)

    return tx_curtailment_cost


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
    transmission_curtailment_cost.tab file.
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

    tx_curtailment_cost = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="transmission_curtailment_cost.tab",
        data=tx_curtailment_cost,
        replace_nulls=True,
    )
