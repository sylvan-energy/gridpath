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
This is a Tx-line-level module that adds to the formulation components that
describe the operations-related costs of transmission lines, namely hurdle
rate costs. Hurdle rate costs are currently applied on power sent across the
transmission line.
"""

import csv
import os.path
from pyomo.environ import Param, Var, Constraint, NonNegativeReals, Expression, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import (
    directories_to_db_values,
)
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    get_expected_dtypes,
    validate_dtypes,
    validate_values,
    validate_missing_inputs,
)
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
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`hurdle_rate_pos_dir_per_mwh`                                   |
    | | *Defined over*: :code:`TX_OPR_PRDS`                                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defaults to*: :code:`0`                                              |
    |                                                                         |
    | The transmission line's hurdle rate in $ per MWh for its positive       |
    | flows in each operational period.                                       |
    +-------------------------------------------------------------------------+
    | | :code:`hurdle_rate_neg_dir_per_mwh`                                   |
    | | *Defined over*: :code:`TX_OPR_PRDS`                                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Defaults to*: :code:`0`                                              |
    |                                                                         |
    | The transmission line's hurdle rate in $ per MWh for its negative       |
    | flows (i.e. against the line's defined direction) in each operational   |
    | period.                                                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Hurdle_Cost_Pos_Dir`                                           |
    | | *Defined over*: :code:`TX_OPR_TMPS`                                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The transmission line's hurdle costs in $ for its positive flows in     |
    | in each operational period.                                             |
    +-------------------------------------------------------------------------+
    | | :code:`Hurdle_Cost_Neg_Dir`                                           |
    | | *Defined over*: :code:`TX_OPR_TMPS`                                   |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The transmission line's hurdle costs in $ for its negative flows        |
    | (i.e. against the line's defined direction) in each operational         |
    | timepoint.                                                              |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Hurdle_Cost_Pos_Dir_Constraint`                                |
    | | *Enforced over*: :code:`TX_OPR_TMPS`                                  |
    |                                                                         |
    | The transmission line's positive direction hurdle cost should be larger |
    | than or equal to the line's hurdle rate multiplied by its transmission  |
    | flow in each operational timepoint. When line flows are negative, this  |
    | will set the the cost to zero.                                          |
    +-------------------------------------------------------------------------+
    | | :code:`Hurdle_Cost_Neg_Dir_Constraint`                                |
    | | *Enforced over*: :code:`TX_OPR_TMPS`                                  |
    |                                                                         |
    | The transmission line's negative direction hurdle cost should be larger |
    | than or equal to the line's hurdle rate multiplied by its negative      |
    | transmission flow in each operational timepoint. When line flows are    |
    | positive, this will set the cost to zero.                               |
    +-------------------------------------------------------------------------+


    """

    # Optional Input Params
    ###########################################################################

    m.hurdle_rate_pos_dir_per_mwh = Param(
        m.TX_LINES,
        m.PERIODS,  # TODO: chanage to TX_OPR_PRDS?
        within=NonNegativeReals,
        default=0,
    )

    m.hurdle_rate_neg_dir_per_mwh = Param(
        m.TX_LINES,
        m.PERIODS,  # TODO: chanage to TX_OPR_PRDS?
        within=NonNegativeReals,
        default=0,
    )

    # Variables
    ###########################################################################

    m.Hurdle_Cost_Pos_Dir = Var(m.TX_OPR_TMPS, within=NonNegativeReals)
    m.Hurdle_Cost_Neg_Dir = Var(m.TX_OPR_TMPS, within=NonNegativeReals)

    # Constraints
    ###########################################################################

    m.Hurdle_Cost_Pos_Dir_Constraint = Constraint(
        m.TX_OPR_TMPS, rule=hurdle_cost_pos_dir_rule
    )

    m.Hurdle_Cost_Neg_Dir_Constraint = Constraint(
        m.TX_OPR_TMPS, rule=hurdle_cost_neg_dir_rule
    )


# Constraint Formulation Rules
###############################################################################


def hurdle_cost_pos_dir_rule(mod, tx, tmp):
    """
    **Constraint Name**: Hurdle_Cost_Pos_Dir_Constraint
    **Enforced Over**: TX_OPR_TMPS

    Hurdle_Cost_Pos_Dir must be non-negative, so will be 0
    when Transmit_Power is negative (flow in the negative direction).
    """
    if mod.hurdle_rate_pos_dir_per_mwh[tx, mod.period[tmp]] == 0:
        return Constraint.Skip
    else:
        return (
            mod.Hurdle_Cost_Pos_Dir[tx, tmp]
            >= mod.Transmit_Power_MW[tx, tmp]
            * mod.hurdle_rate_pos_dir_per_mwh[tx, mod.period[tmp]]
        )


def hurdle_cost_neg_dir_rule(mod, tx, tmp):
    """
    **Constraint Name**: Hurdle_Cost_Neg_Dir_Constraint
    **Enforced Over**: TX_OPR_TMPS

    Hurdle_Cost_Neg_Dir must be non-negative, so will be 0
    when Transmit_Power is positive (flow in the positive direction).
    """
    if mod.hurdle_rate_neg_dir_per_mwh[tx, mod.period[tmp]] == 0:
        return Constraint.Skip
    else:
        return (
            mod.Hurdle_Cost_Neg_Dir[tx, tmp]
            >= -mod.Transmit_Power_MW[tx, tmp]
            * mod.hurdle_rate_neg_dir_per_mwh[tx, mod.period[tmp]]
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
            "transmission_hurdle_rates.tab",
        ),
        select=(
            "transmission_line",
            "period",
            "hurdle_rate_positive_direction_per_mwh",
            "hurdle_rate_negative_direction_per_mwh",
        ),
        param=(m.hurdle_rate_pos_dir_per_mwh, m.hurdle_rate_neg_dir_per_mwh),
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
    Export transmission operational cost results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m: The Pyomo abstract model
    :param d: Dynamic components
    :return: Nothing
    """

    results_columns = [
        "hurdle_cost_positive_direction",
        "hurdle_cost_negative_direction",
    ]
    data = [
        [tx, tmp, m.Hurdle_Cost_Pos_Dir[tx, tmp], m.Hurdle_Cost_Neg_Dir[tx, tmp]]
        for (tx, tmp) in m.TX_OPR_TMPS
    ]
    cost_df = create_results_df(
        index_columns=["transmission_line", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, TX_TIMEPOINT_DF), cost_df)


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
    hurdle_rates = c.execute(
        """SELECT transmission_line, period, 
        hurdle_rate_positive_direction_per_mwh,
        hurdle_rate_negative_direction_per_mwh
        FROM inputs_transmission_portfolios
        CROSS JOIN
            (SELECT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {}) AS relevant_periods 
        LEFT OUTER JOIN
            (SELECT transmission_line, period, 
            hurdle_rate_positive_direction_per_mwh,
            hurdle_rate_negative_direction_per_mwh
            FROM inputs_transmission_hurdle_rates
            WHERE transmission_hurdle_rate_scenario_id = {}) AS relevant_hrs
        USING (transmission_line, period)
        WHERE transmission_portfolio_scenario_id = {};
        """.format(
            subscenarios.TEMPORAL_SCENARIO_ID,
            subscenarios.TRANSMISSION_HURDLE_RATE_SCENARIO_ID,
            subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID,
        )
    )

    return hurdle_rates


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
    transmission_hurdle_rates.tab file.
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

    hurdle_rates = get_inputs_from_database(
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
            "transmission_hurdle_rates.tab",
        ),
        "w",
        newline="",
    ) as sim_flows_file:
        writer = csv.writer(sim_flows_file, delimiter="\t", lineterminator="\n")

        # Write header
        writer.writerow(
            [
                "transmission_line",
                "period",
                "hurdle_rate_positive_direction_per_mwh",
                "hurdle_rate_negative_direction_per_mwh",
            ]
        )

        for row in hurdle_rates:
            replace_nulls = ["." if i is None else i for i in row]
            writer.writerow(replace_nulls)


def process_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate costs by zone and period. Costs are allocated to the destination
    zone. I.e. positive direction hurdle costs are allocated to the to-zone
    while negative direction hurdle costs are allocated to the from-zone.
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate hurdle costs")

    # Delete old results
    del_sql = """
        DELETE FROM results_transmission_hurdle_costs_agg
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Aggregate hurdle costs by period, load zone, and spinup_or_lookahead
    agg_sql = """
        INSERT INTO results_transmission_hurdle_costs_agg
        (scenario_id, subproblem_id, stage_id, period, load_zone, 
        spinup_or_lookahead, tx_hurdle_cost)
        
        SELECT scenario_id, subproblem_id, stage_id, period, load_zone, 
        spinup_or_lookahead,
        (pos_dir_hurdle_cost + neg_dir_hurdle_cost) AS tx_hurdle_cost
        
        FROM
        
        (SELECT scenario_id, subproblem_id, stage_id, period, 
        load_zone_to AS load_zone, spinup_or_lookahead,
        SUM(hurdle_cost_positive_direction * timepoint_weight * 
        number_of_hours_in_timepoint) AS pos_dir_hurdle_cost
        FROM results_transmission_timepoint
        WHERE scenario_id = ?
        GROUP BY subproblem_id, stage_id, period, load_zone, spinup_or_lookahead
        ORDER BY subproblem_id, stage_id, period, load_zone, spinup_or_lookahead
        ) AS pos_dir_hurdle_costs
        
        INNER JOIN
        
        (SELECT scenario_id, subproblem_id, stage_id, period, 
        load_zone_from AS load_zone, spinup_or_lookahead,
        SUM(hurdle_cost_negative_direction * timepoint_weight * 
        number_of_hours_in_timepoint) AS neg_dir_hurdle_cost
        FROM results_transmission_timepoint
        WHERE scenario_id = ?
        GROUP BY subproblem_id, stage_id, period, load_zone, spinup_or_lookahead
        ORDER BY subproblem_id, stage_id, period, load_zone, spinup_or_lookahead
        ) AS neg_dir_hurdle_costs
        
        USING (scenario_id, subproblem_id, stage_id, period, load_zone, 
        spinup_or_lookahead)
        ;"""

    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id, scenario_id), many=False
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

    hurdle_rates = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    df = cursor_to_df(hurdle_rates)

    # Get expected dtypes
    expected_dtypes = get_expected_dtypes(
        conn=conn, tables=["inputs_transmission_hurdle_rates"]
    )

    # Check dtypes
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
        db_table="inputs_transmission_hurdle_rates",
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
        db_table="inputs_transmission_hurdle_rates",
        severity="High",
        errors=validate_values(df, valid_numeric_columns, "transmission_line", min=0),
    )

    # Check that all binary new build tx lines are available in >=1 vintage
    msg = (
        "Expected hurdle rates specified for each modeling period when "
        "transmission hurdle rates feature is on."
    )
    cols = [
        "hurdle_rate_positive_direction_per_mwh",
        "hurdle_rate_negative_direction_per_mwh",
    ]
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_transmission_hurdle_rates",
        severity="Low",
        errors=validate_missing_inputs(
            df=df, col=cols, idx_col=["transmission_line", "period"], msg=msg
        ),
    )
