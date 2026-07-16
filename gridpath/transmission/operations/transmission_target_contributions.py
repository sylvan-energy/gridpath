# Copyright 2022 (c) Crown Copyright, GC.
# Modifications copyright (c) 2023 Blue Marble Analytics.
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

import csv
import os.path
from pyomo.environ import (
    Param,
    Set,
    Expression,
    value,
    Var,
    NonNegativeReals,
    Reals,
    Boolean,
    Constraint,
)

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import (
    update_prj_zone_column,
    determine_table_subset_by_start_and_column,
    directories_to_db_values,
)
from gridpath.auxiliary.validations import write_validation_to_database, validate_idxs
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.transmission import TX_TIMEPOINT_DF


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
    | | :code:`TRANSMISSION_TARGET_TX_LINES`                                  |
    | | *Within*: :code:`TX_LINES`                                            |
    |                                                                         |
    | The set of all transmission-target-eligible tx lines.                   |
    +-------------------------------------------------------------------------+
    | | :code:`TRANSMISSION_TARGET_TX_OPR_TMPS`                               |
    |                                                                         |
    | Two-dimensional set that defines all tx_line-timepoint combinations     |
    | when an transmission-target-elgible tx_line can be operational.         |
    +-------------------------------------------------------------------------+
    | | :code:`TRANSMISSION_TARGET_TX_LINES_BY_TRANSMISSION_TARGET_ZONE`      |
    | | *Defined over*: :code:`TRANSMISSION_TARGET_ZONES`                     |
    | | *Within*: :code:`TRANSMISSION_TARGET_TX_LINES                         |
    |                                                                         |
    | Indexed set that describes the transmission-target tx_lines for each    |
    | transmission-target zone.                                               |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Input Params                                                            |
    +=========================================================================+
    | | :code:`transmission_target_zone`                                      |
    | | *Defined over*: :code:`TRANSMISSION_TARGET_TX_LINES`                  |
    | | *Within*: :code:`TRANSMISSION_TARGET_ZONES`                           |
    |                                                                         |
    | This param describes the transmission-target zone for each              |
    | transmission-target tx_line.                                            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Transmission_Target_Energy_MW`                                 |
    | | *Defined over*: :code:`TRANSMISSION_TARGET_TX_OPR_TMPS`               |
    |                                                                         |
    | Describes how many energy transferred for each                          |
    | transmission-target-eligible tx line in each timepoint.                 |
    +-------------------------------------------------------------------------+

    """
    # Sets
    ###########################################################################

    m.TRANSMISSION_TARGET_TX_LINES = Set(within=m.TX_LINES)

    m.TRANSMISSION_TARGET_TX_OPR_TMPS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="TX_OPR_TMPS",
            index=0,
            membership_set=mod.TRANSMISSION_TARGET_TX_LINES,
        ),
    )

    # Input Params
    ###########################################################################

    m.transmission_target_zone = Param(
        m.TRANSMISSION_TARGET_TX_LINES, within=m.TRANSMISSION_TARGET_ZONES
    )

    # Set to 1 if you want this line to contribute net flows
    m.contributes_net_flow_to_tx_target = Param(
        m.TRANSMISSION_TARGET_TX_LINES, within=Boolean, default=0
    )

    # Variables
    ###########################################################################
    m.Transmission_Target_Energy_MW_Pos_Dir = Var(
        m.TX_OPR_TMPS, within=NonNegativeReals
    )
    m.Transmission_Target_Energy_MW_Neg_Dir = Var(
        m.TX_OPR_TMPS, within=NonNegativeReals
    )

    m.Transmission_Target_Net_Energy_MW_Pos_Dir = Var(m.TX_OPR_TMPS, within=Reals)
    m.Transmission_Target_Net_Energy_MW_Neg_Dir = Var(m.TX_OPR_TMPS, within=Reals)

    # Derived Sets (requires input params)
    ###########################################################################

    m.TRANSMISSION_TARGET_TX_LINES_BY_TRANSMISSION_TARGET_ZONE = Set(
        m.TRANSMISSION_TARGET_ZONES,
        within=m.TRANSMISSION_TARGET_TX_LINES,
        initialize=determine_tx_target_tx_lines_by_tx_target_zone,
    )

    # Constraints
    ###########################################################################

    def transmit_power_pos_dir_rule(mod, tx, tmp):
        """ """
        if mod.contributes_net_flow_to_tx_target[tx]:
            return Constraint.Skip
        else:
            return (
                mod.Transmission_Target_Energy_MW_Pos_Dir[tx, tmp]
                == mod.TxSimpleBinary_Transmit_Power_Positive_Direction_MW[tx, tmp]
            )

    m.Transmission_Target_Energy_MW_Pos_Dir_Constraint = Constraint(
        m.TRANSMISSION_TARGET_TX_OPR_TMPS, rule=transmit_power_pos_dir_rule
    )

    def transmit_power_neg_dir_rule(mod, tx, tmp):
        """ """
        if mod.contributes_net_flow_to_tx_target[tx]:
            return Constraint.Skip
        else:
            return (
                mod.Transmission_Target_Energy_MW_Neg_Dir[tx, tmp]
                == mod.TxSimpleBinary_Transmit_Power_Negative_Direction_MW[tx, tmp]
            )

    m.Transmission_Target_Energy_MW_Neg_Dir_Constraint = Constraint(
        m.TRANSMISSION_TARGET_TX_OPR_TMPS, rule=transmit_power_neg_dir_rule
    )

    def transmit_power_pos_dir_net_rule(mod, tx, tmp):
        """ """
        if not mod.contributes_net_flow_to_tx_target[tx]:
            return Constraint.Skip
        else:
            return (
                mod.Transmission_Target_Net_Energy_MW_Pos_Dir[tx, tmp]
                == mod.Transmit_Power_MW[tx, tmp]
            )

    m.Transmission_Target_Net_Energy_MW_Pos_Dir_Constraint = Constraint(
        m.TRANSMISSION_TARGET_TX_OPR_TMPS, rule=transmit_power_pos_dir_net_rule
    )

    def transmit_power_neg_dir_net_rule(mod, tx, tmp):
        """ """
        if not mod.contributes_net_flow_to_tx_target[tx]:
            return Constraint.Skip
        else:
            return (
                mod.Transmission_Target_Net_Energy_MW_Neg_Dir[tx, tmp]
                == -mod.Transmit_Power_MW[tx, tmp]
            )

    m.Transmission_Target_Net_Energy_MW_Neg_Dir_Constraint = Constraint(
        m.TRANSMISSION_TARGET_TX_OPR_TMPS, rule=transmit_power_neg_dir_net_rule
    )


# Set Rules
###############################################################################


def determine_tx_target_tx_lines_by_tx_target_zone(mod, transmission_target_z):
    return [
        p
        for p in mod.TRANSMISSION_TARGET_TX_LINES
        if mod.transmission_target_zone[p] == transmission_target_z
    ]


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
            "transmission_lines.tab",
        ),
        select=(
            "transmission_line",
            "transmission_target_zone",
            "contributes_net_flow_to_tx_target",
        ),
        param=(m.transmission_target_zone, m.contributes_net_flow_to_tx_target),
    )

    data_portal.data()["TRANSMISSION_TARGET_TX_LINES"] = {
        None: list(data_portal.data()["transmission_target_zone"].keys())
    }


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
        "actual_flow_positive_direction",
        "actual_flow_negative_direction",
        "tx_flow_positive_direction",
        "tx_flow_negative_direction",
    ]
    data = [
        [
            tx,
            tmp,
            (
                value(m.TxSimpleBinary_Transmit_Power_Positive_Direction_MW[tx, tmp])
                if float(m.contributes_net_flow_to_tx_target[tx]) == 0
                else value(m.TxSimple_Transmit_Power_MW[tx, tmp])
            ),
            (
                value(m.TxSimpleBinary_Transmit_Power_Negative_Direction_MW[tx, tmp])
                if float(m.contributes_net_flow_to_tx_target[tx]) == 0
                else value(-m.TxSimple_Transmit_Power_MW[tx, tmp])
            ),
            (
                value(m.Transmission_Target_Energy_MW_Pos_Dir[tx, tmp])
                if float(m.contributes_net_flow_to_tx_target[tx]) == 0
                else value(m.Transmission_Target_Net_Energy_MW_Pos_Dir[tx, tmp])
            ),
            (
                value(m.Transmission_Target_Energy_MW_Neg_Dir[tx, tmp])
                if float(m.contributes_net_flow_to_tx_target[tx]) == 0
                else value(m.Transmission_Target_Net_Energy_MW_Neg_Dir[tx, tmp])
            ),
        ]
        for (tx, tmp) in m.TRANSMISSION_TARGET_TX_OPR_TMPS
    ]
    results_df = create_results_df(
        index_columns=["transmission_line", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, TX_TIMEPOINT_DF), results_df)


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

    # Get the transmission-target zones for transmission lines in our portfolio and with zones in our
    # Transmission target zone
    tx_lines_zones = c.execute(
        f"""SELECT transmission_line, transmission_target_zone, contributes_net_flow_to_tx_target
        FROM
        -- Get transmission lines from portfolio only
        (SELECT transmission_line
            FROM inputs_transmission_portfolios
            WHERE transmission_portfolio_scenario_id = {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}
        ) as tx_tbl
        LEFT OUTER JOIN 
        -- Get transmission_target zones for those transmission lines
        (SELECT transmission_line, transmission_target_zone, contributes_net_flow_to_tx_target
            FROM inputs_tx_line_transmission_target_zones
            WHERE tx_line_transmission_target_zone_scenario_id = {subscenarios.TX_LINE_TRANSMISSION_TARGET_ZONE_SCENARIO_ID}
        ) as tx_line_transmission_target_zone_tbl
        USING (transmission_line)
        -- Filter out transmission lines whose transmission-target zone is not one included in our 
        -- transmission_target_zone_scenario_id
        WHERE transmission_target_zone in (
                SELECT transmission_target_zone
                    FROM inputs_geography_transmission_target_zones
                    WHERE transmission_target_zone_scenario_id = {subscenarios.TRANSMISSION_TARGET_ZONE_SCENARIO_ID}
        );
        """
    )

    return tx_lines_zones


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

    tx_lines_zones = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # Make a dict for easy access
    tx_line_zone_dict = dict()
    for tx, zone, contr_net_flow in tx_lines_zones:
        tx_line_zone_dict[str(tx)] = (
            [".", "."]
            if zone is None
            else [str(zone), "." if contr_net_flow is None else contr_net_flow]
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
            "transmission_lines.tab",
        ),
        "r",
    ) as tx_lines_file_in:
        reader = csv.reader(tx_lines_file_in, delimiter="\t", lineterminator="\n")

        new_rows = list()

        # Append column header
        header = next(reader)
        header.extend(["transmission_target_zone", "contributes_net_flow_to_tx_target"])
        new_rows.append(header)

        # Append correct values
        for row in reader:
            # If tx line specified, check if BA specified or not
            if row[0] in list(tx_line_zone_dict.keys()):
                row.extend(tx_line_zone_dict[row[0]])
                new_rows.append(row)
            # If tx line not specified, specify null BA and params
            else:
                row.extend([".", "."])
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
            "transmission_lines.tab",
        ),
        "w",
        newline="",
    ) as tx_lines_file_out:
        writer = csv.writer(tx_lines_file_out, delimiter="\t", lineterminator="\n")
        writer.writerows(new_rows)


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

    # Get the transmission lines and transmission-target zones
    tx_lines_zones = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    # Convert input data into pandas DataFrame
    df = cursor_to_df(tx_lines_zones)
    zones_w_tx_line = df["transmission_target_zone"].unique()

    # Get the required transmission-target zones
    c = conn.cursor()
    zones = c.execute(
        """SELECT transmission_target_zone FROM inputs_geography_transmission_target_zones
        WHERE transmission_target_zone_scenario_id = {}
        """.format(
            subscenarios.TRANSMISSION_TARGET_ZONE_SCENARIO_ID
        )
    )
    zones = [z[0] for z in zones]  # convert to list

    # Check that each transmission-target zone has at least one transmission line assigned to it
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_tx_line_transmission_target_zones",
        severity="High",
        errors=validate_idxs(
            actual_idxs=zones_w_tx_line,
            req_idxs=zones,
            idx_label="transmission_target_zone",
            msg="Each transmission target zone needs at least 1 "
            "transmission line assigned to it.",
        ),
    )
