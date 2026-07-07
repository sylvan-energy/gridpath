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
This is a line-level module that adds to the formulation components that
describe the amount of power flowing on each line.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Expression, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import get_required_subtype_modules
from gridpath.common_functions import create_results_df
from gridpath.transmission.operations.common_functions import (
    load_tx_operational_type_modules,
)
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
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Transmit_Power_MW`                                        |
    | | *Defined over*: :code:`TX_OPR_TMPS`                                   |
    |                                                                         |
    | The power in MW sent on a transmission line (before losses).            |
    | A positive number means the power flows in the line's defined direction,|
    | while a negative number means it flows in the opposite direction.       |
    +-------------------------------------------------------------------------+
    | | :code:`Transmit_Power_MW`                                    |
    | | *Defined over*: :code:`TX_OPR_TMPS`                                   |
    |                                                                         |
    | The power in MW received via a transmission line (after losses).        |
    | A positive number means the power flows in the line's defined direction,|
    | while a negative number means it flows in the opposite direction.       |
    +-------------------------------------------------------------------------+
    | | :code:`Tx_Losses_MW`                                                  |
    | | *Defined over*: :code:`TX_OPR_TMPS`                                   |
    |                                                                         |
    | Total losses on the transmission line in MW, i.e. the sum of the        |
    | losses accounted for in the line's "from" and "to" load zones (only     |
    | one of which can be non-zero in a timepoint, depending on the flow      |
    | direction).                                                             |
    +-------------------------------------------------------------------------+

    """

    # Dynamic Inputs
    ###########################################################################

    required_operational_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="tx_operational_type",
        filename="transmission_lines",
    )

    imported_tx_operational_modules = load_tx_operational_type_modules(
        required_operational_modules
    )

    # TODO: should we add the module specific components here or in
    #  operational_types/__init__.py? Doing it in __init__.py to be consistent
    #  with projects/operations/power.py

    # Expressions
    ###########################################################################

    def transmit_power_rule(mod, tx, tmp):
        tx_op_type = mod.tx_operational_type[tx]
        return imported_tx_operational_modules[tx_op_type].transmit_power_rule(
            mod, tx, tmp
        )

    m.Transmit_Power_MW = Expression(m.TX_OPR_TMPS, rule=transmit_power_rule)

    def transmit_power_losses_lz_from_rule(mod, tx, tmp):
        tx_op_type = mod.tx_operational_type[tx]
        return imported_tx_operational_modules[
            tx_op_type
        ].transmit_power_losses_lz_from_rule(mod, tx, tmp)

    m.Tx_Losses_LZ_From_MW = Expression(
        m.TX_OPR_TMPS, rule=transmit_power_losses_lz_from_rule
    )

    def transmit_power_losses_lz_to_rule(mod, tx, tmp):
        tx_op_type = mod.tx_operational_type[tx]
        return imported_tx_operational_modules[
            tx_op_type
        ].transmit_power_losses_lz_to_rule(mod, tx, tmp)

    m.Tx_Losses_LZ_To_MW = Expression(
        m.TX_OPR_TMPS, rule=transmit_power_losses_lz_to_rule
    )

    def total_losses_rule(mod, tx, tmp):
        return mod.Tx_Losses_LZ_From_MW[tx, tmp] + mod.Tx_Losses_LZ_To_MW[tx, tmp]

    m.Tx_Losses_MW = Expression(m.TX_OPR_TMPS, rule=total_losses_rule)


# Input-Output
###############################################################################


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
    :param m: The Pyomo abstract model
    :param d: Dynamic components
    :return: Nothing
    """

    results_columns = [
        "transmission_flow_mw",
        "transmission_losses_lz_from",
        "transmission_losses_lz_to",
    ]

    data = [
        [
            tx,
            tmp,
            value(m.Transmit_Power_MW[tx, tmp]),
            value(m.Tx_Losses_LZ_From_MW[tx, tmp]),
            value(m.Tx_Losses_LZ_To_MW[tx, tmp]),
        ]
        for (tx, tmp) in m.TX_OPR_TMPS
    ]

    results_df = create_results_df(
        index_columns=["transmission_line", "period"],
        results_columns=results_columns,
        data=data,
    )

    for c in results_columns:
        getattr(d, TX_TIMEPOINT_DF)[c] = None
    getattr(d, TX_TIMEPOINT_DF).update(results_df)

    required_operational_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="tx_operational_type",
        filename="transmission_lines",
    )

    imported_operational_modules = load_tx_operational_type_modules(
        required_operational_modules
    )

    for optype_module in imported_operational_modules:
        if hasattr(
            imported_operational_modules[optype_module], "add_to_operations_results"
        ):
            # TODO: make sure the order of export results is the same between
            #  this module and the optype modules
            results_columns, optype_df = imported_operational_modules[
                optype_module
            ].add_to_operations_results(mod=m)
            for column in results_columns:
                if column not in getattr(d, TX_TIMEPOINT_DF):
                    getattr(d, TX_TIMEPOINT_DF)[column] = None
            getattr(d, TX_TIMEPOINT_DF).update(optype_df)


# Database
###############################################################################


def process_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate imports/exports by zone, period and spinup_or_lookahead
    (numbers are based on flows without accounting for losses!)
    TODO: add losses?
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate transmission imports exports")

    # Delete old results
    del_sql = """
        DELETE FROM results_transmission_imports_exports_agg
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Aggregate imports/exports by period, load zone, and spinup_or_lookahead
    agg_sql = """
        INSERT INTO results_transmission_imports_exports_agg
        (scenario_id, subproblem_id, stage_id, period, 
        load_zone, spinup_or_lookahead, imports, exports)
        
        SELECT scenario_id, subproblem_id, stage_id, period, load_zone,
        spinup_or_lookahead,
        (IFNULL(imports_pos_dir,0) + IFNULL(imports_neg_dir,0)) AS imports,
        (IFNULL(exports_pos_dir,0) + IFNULL(exports_neg_dir,0)) AS exports
        
        FROM (
        
        -- dummy required to make sure all load zones are included 
        -- (SQLite cannot do full outer join)
        
        SELECT DISTINCT scenario_id, subproblem_id, stage_id, period, load_zone,
        spinup_or_lookahead
        FROM (
            SELECT scenario_id, subproblem_id, stage_id, period, load_zone, 
            spinup_or_lookahead
            FROM (
                (SELECT DISTINCT scenario_id, subproblem_id, stage_id, period, 
                load_zone_to AS load_zone, spinup_or_lookahead
                FROM results_transmission_timepoint
                WHERE scenario_id = ?) AS dummy
                
                LEFT JOIN 
                
                (SELECT DISTINCT scenario_id, subproblem_id, stage_id, period, 
                load_zone_from AS load_zone, spinup_or_lookahead
                FROM results_transmission_timepoint
                WHERE scenario_id = ?) AS dummy2
                USING (scenario_id, subproblem_id, stage_id, period, load_zone,
                spinup_or_lookahead)
            ) AS left_join1
            
            UNION ALL
        
            SELECT scenario_id, subproblem_id, stage_id, period, load_zone,
            spinup_or_lookahead
            FROM (
                (SELECT DISTINCT scenario_id, subproblem_id, stage_id, period, 
                load_zone_from AS load_zone, spinup_or_lookahead
                FROM results_transmission_timepoint
                WHERE scenario_id = ?) AS dummy3
                
                LEFT JOIN 
                
                (SELECT DISTINCT scenario_id, subproblem_id, stage_id, period, 
                load_zone_to AS load_zone, spinup_or_lookahead
                FROM results_transmission_timepoint
                WHERE scenario_id = ?) AS dummy4
                USING (scenario_id, subproblem_id, stage_id, period, load_zone,
                spinup_or_lookahead)
            
            ) AS left_join2
        
        ) AS outer_join_table
        
        ) AS distinct_outer_join_table
                        
        LEFT JOIN
        
        (SELECT scenario_id, subproblem_id, stage_id, period, 
        load_zone_to AS load_zone, spinup_or_lookahead,
        SUM(transmission_flow_mw * timepoint_weight * 
        number_of_hours_in_timepoint) AS imports_pos_dir
        FROM results_transmission_timepoint
        WHERE transmission_flow_mw > 0
        AND scenario_id = ?
        GROUP BY scenario_id, subproblem_id, stage_id, period, load_zone, 
        spinup_or_lookahead) 
        AS imports_pos_dir
        USING (scenario_id, subproblem_id, stage_id, period, load_zone,
        spinup_or_lookahead)
        
        LEFT JOIN
        
        (SELECT scenario_id, subproblem_id, stage_id, period, 
        load_zone_from AS load_zone, spinup_or_lookahead,
        SUM(transmission_flow_mw * timepoint_weight * 
        number_of_hours_in_timepoint) AS exports_pos_dir
        FROM results_transmission_timepoint
        WHERE transmission_flow_mw > 0
        AND scenario_id = ?
        GROUP BY scenario_id, subproblem_id, stage_id, period, load_zone, 
        spinup_or_lookahead) 
        AS exports_pos_dir
        USING (scenario_id, subproblem_id, stage_id, period, load_zone,
        spinup_or_lookahead)
        
        LEFT JOIN
        
        (SELECT scenario_id, subproblem_id, stage_id, period, 
        load_zone_from AS load_zone, spinup_or_lookahead,
        -SUM(transmission_flow_mw * timepoint_weight * 
        number_of_hours_in_timepoint) AS imports_neg_dir
        FROM results_transmission_timepoint
        WHERE transmission_flow_mw < 0
        AND scenario_id = ?
        GROUP BY scenario_id, subproblem_id, stage_id, period, load_zone,
        spinup_or_lookahead) 
        AS imports_neg_dir
        USING (scenario_id, subproblem_id, stage_id,period, load_zone,
        spinup_or_lookahead)
        
        LEFT JOIN
        
        (SELECT scenario_id, subproblem_id, stage_id, period, 
        load_zone_to AS load_zone, spinup_or_lookahead,
        -SUM(transmission_flow_mw * timepoint_weight * 
        number_of_hours_in_timepoint) AS exports_neg_dir
        FROM results_transmission_timepoint
        WHERE transmission_flow_mw < 0
        AND scenario_id = ?
        GROUP BY scenario_id, subproblem_id, stage_id, period, load_zone,
        spinup_or_lookahead) 
        AS exports_neg_dir
        USING (scenario_id, subproblem_id, stage_id, period, load_zone,
        spinup_or_lookahead)
        
        ORDER BY subproblem_id, stage_id, period, load_zone, spinup_or_lookahead
        ;"""

    scenario_ids = tuple([scenario_id] * 8)
    spin_on_database_lock(conn=db, cursor=c, sql=agg_sql, data=scenario_ids, many=False)
