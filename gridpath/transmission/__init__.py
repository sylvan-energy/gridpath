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
The **gridpath.transmission** package adds transmission-line-level
components to the model formulation.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Set, Param

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    get_expected_dtypes,
    get_load_zones,
    validate_dtypes,
    validate_columns,
    validate_values,
    validate_missing_inputs,
)
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)

DEFAULT_TX_AVAILABILITY_TYPE = "exogenous"
TX_PERIOD_DF = "transmission_period_df"
TX_TIMEPOINT_DF = "transmission_timepoint_df"


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
    | | :code:`TX_LINES`                                                      |
    |                                                                         |
    | The set of transmission lines to be modeled.                            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`tx_capacity_type`                                              |
    | | *Defined over*: :code:`TX_LINES`                                      |
    | | *Within*: :code:`["tx_new_lin", "tx_spec"]`                           |
    |                                                                         |
    | The transmission line's capacity type. This will determine how the      |
    | capacity of the line is modeled, e.g. as a specified number or as a     |
    | decision variable in the optimization.                                  |
    +-------------------------------------------------------------------------+
    | | :code:`tx_availability_type`                                          |
    | | *Defined over*: :code:`TX_LINES`                                      |
    | | *Within*: :code:`["exogenous", "exogenous_monthly"]`                  |
    | | *Default*: :code:`"exogenous"`                                        |
    |                                                                         |
    | The transmission line's availability type.                              |
    +-------------------------------------------------------------------------+
    +-------------------------------------------------------------------------+
    | | :code:`tx_operational_type`                                           |
    | | *Defined over*: :code:`TX_LINES`                                      |
    | | *Within*: :code:`["tx_dcopf", "tx_simple"]`                           |
    |                                                                         |
    | The transmission line's operational type. This will determine how the   |
    | operations of the line are modeled, e.g. through a simple linear        |
    | transport model or power flow using DC OPF assumptions.                 |
    +-------------------------------------------------------------------------+
    | | :code:`load_zone_from`                                                |
    | | *Defined over*: :code:`TX_LINES`                                      |
    | | *Within*: :code:`LOAD_ZONES`                                          |
    |                                                                         |
    | The transmission line's starting load zone (the power flow can go both  |
    | directions, but each line has a defined direction).                     |
    +-------------------------------------------------------------------------+
    | | :code:`load_zone_to`                                                  |
    | | *Defined over*: :code:`TX_LINES`                                      |
    | | *Within*: :code:`LOAD_ZONES`                                          |
    |                                                                         |
    | The transmission line's ending load zone (the power flow can go both    |
    | directions, but each line has a defined direction).                     |
    +-------------------------------------------------------------------------+


    """

    # Sets
    ###########################################################################

    m.TX_LINES = Set()

    # Required Input Params
    ###########################################################################

    m.tx_capacity_type = Param(m.TX_LINES, within=["tx_new_lin", "tx_spec"])
    m.tx_availability_type = Param(
        m.TX_LINES,
        within=["exogenous", "exogenous_monthly"],
        default=DEFAULT_TX_AVAILABILITY_TYPE,
    )
    m.tx_operational_type = Param(
        m.TX_LINES, within=["tx_dcopf", "tx_simple", "tx_simple_binary"]
    )
    m.load_zone_from = Param(m.TX_LINES, within=m.LOAD_ZONES)
    m.load_zone_to = Param(m.TX_LINES, within=m.LOAD_ZONES)


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
            "tx_capacity_type",
            "tx_availability_type",
            "tx_operational_type",
            "load_zone_from",
            "load_zone_to",
        ),
        index=m.TX_LINES,
        param=(
            m.tx_capacity_type,
            m.tx_availability_type,
            m.tx_operational_type,
            m.load_zone_from,
            m.load_zone_to,
        ),
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
    Export operations results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    The Pyomo abstract model
    :param d:
    Dynamic components
    :return:
    Nothing
    """

    # First create the results dataframes
    # Other modules will update these dataframe with actual results
    # The results dataframes are by index

    # Project-period DF
    tx_period_df = pd.DataFrame(
        columns=[
            "transmission_line",
            "period",
            "tx_capacity_type",
            "tx_availability_type",
            "tx_operational_type",
            "load_zone_from",
            "load_zone_to",
        ],
        data=[
            [
                tx,
                prd,
                m.tx_capacity_type[tx],
                m.tx_availability_type[tx],
                m.tx_operational_type[tx],
                m.load_zone_from[tx],
                m.load_zone_to[tx],
            ]
            for (tx, prd) in m.TX_OPR_PRDS
        ],
    ).set_index(["transmission_line", "period"])

    tx_period_df.sort_index(inplace=True)

    # Add the dataframe to the dynamic components to pass to other modules
    setattr(d, TX_PERIOD_DF, tx_period_df)

    # Project-timepoint DF
    tx_timepoint_df = pd.DataFrame(
        columns=[
            "transmission_line",
            "timepoint",
            "period",
            "tx_capacity_type",
            "tx_availability_type",
            "tx_operational_type",
            "timepoint_weight",
            "number_of_hours_in_timepoint",
            "load_zone_from",
            "load_zone_to",
        ],
        data=[
            [
                tx,
                tmp,
                m.period[tmp],
                m.tx_capacity_type[tx],
                m.tx_availability_type[tx],
                m.tx_operational_type[tx],
                m.tmp_weight[tmp],
                m.hrs_in_tmp[tmp],
                m.load_zone_from[tx],
                m.load_zone_to[tx],
            ]
            for (tx, tmp) in m.TX_OPR_TMPS
        ],
    ).set_index(["transmission_line", "timepoint"])

    tx_timepoint_df.sort_index(inplace=True)

    # Add the dataframe to the dynamic components to pass to other modules
    setattr(d, TX_TIMEPOINT_DF, tx_timepoint_df)


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

    # TODO: we might want to get the reactance in the tx_dcopf
    #  tx_operational_type rather than here (see also comment in project/init)
    c = conn.cursor()
    transmission_lines = c.execute(f"""
        SELECT transmission_line, capacity_type AS tx_capacity_type,
        availability_type AS tx_availability_type, operational_type AS
        tx_operational_type,
        load_zone_from, load_zone_to, tx_simple_loss_factor,
        losses_tuning_cost_per_mw, reactance_ohms, tx_losses_factor_curtailment
        FROM
        -- Get only the subset of projects in the portfolio with their 
        -- capacity types based on the project_portfolio_scenario_id 
        (SELECT transmission_line, capacity_type
        FROM inputs_transmission_portfolios
        WHERE transmission_portfolio_scenario_id = {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}) as portfolio_tbl
        -- Get the load_zones for these transmission_lines depending on the
        -- transmission_load_zone_scenario_id
        LEFT OUTER JOIN
        (SELECT transmission_line, load_zone_from, load_zone_to
        FROM inputs_transmission_load_zones
        WHERE transmission_load_zone_scenario_id = {subscenarios.TRANSMISSION_LOAD_ZONE_SCENARIO_ID}) as prj_load_zones
        USING (transmission_line)
        LEFT OUTER JOIN
        -- Get the availability types for these transmission_lines depending on the
        -- transmission_availability_scenario_id
        (SELECT transmission_line, availability_type
        FROM inputs_transmission_availability
        WHERE transmission_availability_scenario_id = {subscenarios.TRANSMISSION_AVAILABILITY_SCENARIO_ID}) as prj_av_types
        USING (transmission_line)
        LEFT OUTER JOIN
        -- Get the operational type, balancing_type, technology, 
        -- and variable cost for these transmission_lines depending on the 
        -- transmission_operational_chars_scenario_id
        (SELECT transmission_line, operational_type,
            tx_simple_loss_factor, losses_tuning_cost_per_mw, reactance_ohms,
            tx_losses_factor_curtailment
            FROM inputs_transmission_operational_chars
            WHERE transmission_operational_chars_scenario_id = {subscenarios.TRANSMISSION_OPERATIONAL_CHARS_SCENARIO_ID}) as prj_chars
        USING (transmission_line)
        ;""")

    # TODO: allow Tx lines with no load zones from and to specified, that are only
    #  used for say, reliability capacity exchanges; they would need a different
    #  operational type (no power transfer); the decisions also won't be made at the
    #  transmission line level, but the capacity will limit the aggregate transfer
    #  between PRM zones, so there won't be flow variables

    return transmission_lines


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

    transmission_lines = get_inputs_from_database(
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
        fname="transmission_lines.tab",
        data=transmission_lines,
        replace_nulls=True,
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

    c = conn.cursor()

    # Get the transmission inputs
    transmission_lines = get_inputs_from_database(
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
    df_before_rename = cursor_to_df(transmission_lines)
    df = df_before_rename.rename(
        columns={
            "tx_capacity_type": "capacity_type",
            "tx_availability_type": "availability_type",
            "tx_operational_type": "operational_type",
        }
    )

    # Check data types:
    expected_dtypes = get_expected_dtypes(
        conn,
        [
            "inputs_transmission_portfolios",
            "inputs_transmission_availability",
            "inputs_transmission_load_zones",
            "inputs_transmission_operational_chars",
        ],
    )

    dtype_errors, error_columns = validate_dtypes(df, expected_dtypes)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_transmission_portfolios, "
        "inputs_transmission_load_zones, "
        "inputs_transmission_operational_chars",
        severity="High",
        errors=dtype_errors,
    )

    # Check valid numeric columns are non-negative
    numeric_columns = [c for c in df.columns if expected_dtypes[c] == "numeric"]
    valid_numeric_columns = set(numeric_columns) - set(error_columns)

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_transmission_operational_chars",
        severity="High",
        errors=validate_values(df, valid_numeric_columns, min=0),
    )

    # Ensure we're not combining incompatible capacity and operational types
    cols = ["capacity_type", "operational_type"]
    invalid_combos = c.execute("""
        SELECT {} FROM mod_tx_capacity_and_tx_operational_type_invalid_combos
        """.format(",".join(cols))).fetchall()
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_transmission_operational_chars, inputs_tranmission_portfolios",
        severity="High",
        errors=validate_columns(df, cols, invalids=invalid_combos),
    )

    # Check reactance > 0
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_transmission_operational_chars",
        severity="High",
        errors=validate_values(df, ["reactance_ohms"], min=0, strict_min=True),
    )

    # Check that all portfolio tx lines are present in the opchar inputs
    msg = (
        "All tx lines in the portfolio should have an operational type "
        "specified in the inputs_transmission_operational_chars table."
    )
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_transmission_operational_chars",
        severity="High",
        errors=validate_missing_inputs(
            df, ["operational_type"], idx_col="transmission_line", msg=msg
        ),
    )

    # Check that all portfolio tx lines are present in the load zone inputs
    msg = (
        "All tx lines in the portfolio should have a load zone from/to "
        "specified in the inputs_transmission_load_zones table."
    )
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_transmission_load_zones",
        severity="High",
        errors=validate_missing_inputs(
            df, ["load_zone_from", "load_zone_to"], idx_col="transmission_line", msg=msg
        ),
    )

    # Check that all tx load zones are part of the active load zones
    load_zones = get_load_zones(conn, subscenarios)
    for col in ["load_zone_from", "load_zone_to"]:
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_transmission_load_zones",
            severity="High",
            errors=validate_columns(df, col, valids=load_zones),
        )
