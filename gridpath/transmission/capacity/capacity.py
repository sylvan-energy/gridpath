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
describe the capacity of transmission lines that are available to the
optimization for each period. The capacity can be a fixed  number or an
expression with variables depending on the line's *capacity_type*. The
project capacity can then be used to constrain operations, contribute to
reliability constraints, etc. The module also adds transmission costs which
again depend on the line's *capacity_type*.
"""

import math
import os.path
import pandas as pd
from pyomo.environ import Set, Expression, value

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import (
    get_required_subtype_modules,
    join_sets,
)
from gridpath.common_functions import create_results_df
from gridpath.transmission import TX_PERIOD_DF
from gridpath.transmission.capacity.common_functions import (
    load_tx_capacity_type_modules,
)

from gridpath.auxiliary.dynamic_components import (
    tx_capacity_type_operational_period_sets,
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
    Before adding any components, this module will go through each relevant
    capacity type and add the module components for that capacity type.

    Then the following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`TX_OPR_PRDS`                                                   |
    |                                                                         |
    | Two-dimensional set of the transmission lines and their operational     |
    | periods (capacity exists and is available).                             |
    +-------------------------------------------------------------------------+
    | | :code:`TX_LINES_OPR_IN_PRD`                                           |
    | | *Defined over*: :code:`PERIODS`                                       |
    |                                                                         |
    | Indexed set of transmission lines operational in each period.           |
    +-------------------------------------------------------------------------+
    | | :code:`OPR_PRDS_BY_TX_LINE`                                           |
    | | *Defined over*: :code:`TX_LINES`                                      |
    |                                                                         |
    | Indexed set of operational period for each transmission line.           |
    +-------------------------------------------------------------------------+
    | | :code:`TX_OPR_TMPS`                                                   |
    |                                                                         |
    | Two-dimensional set of the transmission lines and their operational     |
    | timepoints, derived from :code:`TX_OPR_PRDS` and the timepoints in each |
    | period.                                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`TX_LINES_OPR_IN_TMP`                                           |
    | | *Defined over*: :code:`TIMEPOINTS`                                    |
    |                                                                         |
    | Indexed set of transmission lines operational in each timepoint.        |
    +-------------------------------------------------------------------------+
    | | :code:`TX_OPR_PRDS_W_MIN_LIMIT`                                       |
    |                                                                         |
    | Subset of :code:`TX_OPR_PRDS` for line-periods that have a lower flow   |
    | limit. A capacity type may declare a line-period unconstrained (no      |
    | limit) via :code:`min_limit_is_unconstrained_rule`; capacity types      |
    | without that method are always constrained (the default). The           |
    | operational types build their minimum-flow constraints over this        |
    | subset, so unconstrained line-periods get no such constraint.           |
    +-------------------------------------------------------------------------+
    | | :code:`TX_OPR_PRDS_W_MAX_LIMIT`                                       |
    |                                                                         |
    | Subset of :code:`TX_OPR_PRDS` for line-periods that have an upper flow  |
    | limit (analogous to :code:`TX_OPR_PRDS_W_MIN_LIMIT`, via                |
    | :code:`max_limit_is_unconstrained_rule`).                               |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Tx_Min_Capacity_MW`                                            |
    | | *Defined over*: :code:`TX_OPR_PRDS`                                   |
    |                                                                         |
    | The transmission line's minimum flow in MW (negative number indicates   |
    | flow in the opposite direction of the line's defined flow direction).   |
    | Depending on the capacity type, this can be a pre-specified amount or   |
    | a decision variable (with an associated cost).                          |
    +-------------------------------------------------------------------------+
    | | :code:`Tx_Max_Capacity_MW`                                            |
    | | *Defined over*: :code:`TX_OPR_PRDS`                                   |
    |                                                                         |
    | The transmission line's maximum flow in MW (negative number indicates   |
    | flow in the opposite direction of the line's defined flow direction).   |
    | Depending on the capacity type, this can be a pre-specified amount or   |
    | a decision variable (with an associated cost).                          |
    +-------------------------------------------------------------------------+

    """

    # Dynamic Inputs
    ###########################################################################
    required_tx_capacity_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="tx_capacity_type",
        filename="transmission_lines",
    )

    # Import needed transmission capacity type modules for expression rules
    imported_tx_capacity_modules = load_tx_capacity_type_modules(
        required_tx_capacity_modules
    )

    # Sets
    ###########################################################################

    m.TX_OPR_PRDS = Set(
        dimen=2,
        within=m.TX_LINES * m.PERIODS,
        initialize=lambda mod: join_sets(
            mod,
            getattr(d, tx_capacity_type_operational_period_sets),
        ),
    )  # assumes capacity types model components are already added!

    m.TX_LINES_OPR_IN_PRD = Set(
        m.PERIODS,
        initialize=lambda mod, period: sorted(
            list(set(tx for (tx, p) in mod.TX_OPR_PRDS if p == period)),
        ),
    )

    m.OPR_PRDS_BY_TX_LINE = Set(
        m.TX_LINES,
        initialize=lambda mod, tx: sorted(
            list(set(p for (l, p) in mod.TX_OPR_PRDS if l == tx)),
        ),
    )

    m.TX_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: [
            (tx, tmp)
            for tx in mod.TX_LINES
            for p in mod.OPR_PRDS_BY_TX_LINE[tx]
            for tmp in mod.TMPS_IN_PRD[p]
        ],
    )

    m.TX_LINES_OPR_IN_TMP = Set(
        m.TMPS,
        initialize=lambda mod, tmp: sorted(
            list(set(tx for (tx, t) in mod.TX_OPR_TMPS if t == tmp)),
        ),
    )

    # Expressions
    ###########################################################################

    def tx_min_capacity_rule(mod, tx, p):
        tx_cap_type = mod.tx_capacity_type[tx]
        return imported_tx_capacity_modules[tx_cap_type].min_transmission_capacity_rule(
            mod, tx, p
        )

    def tx_max_capacity_rule(mod, tx, p):
        tx_cap_type = mod.tx_capacity_type[tx]
        return imported_tx_capacity_modules[tx_cap_type].max_transmission_capacity_rule(
            mod, tx, p
        )

    m.Tx_Min_Capacity_MW = Expression(m.TX_OPR_PRDS, rule=tx_min_capacity_rule)

    m.Tx_Max_Capacity_MW = Expression(m.TX_OPR_PRDS, rule=tx_max_capacity_rule)

    # Sets of line-periods that have a lower / upper flow limit. A capacity
    # type may declare a line-period "unconstrained" (no flow limit) by
    # defining min_limit_is_unconstrained_rule / max_limit_is_unconstrained_rule
    # and returning True; capacity types without those methods are always
    # constrained (the default), so no line is ever silently left unbounded.
    # The operational types build their min/max flow constraints over these
    # subsets, skipping unconstrained line-periods entirely.
    def tx_min_limit_is_unconstrained(mod, tx, p):
        cap_type = mod.tx_capacity_type[tx]
        module = imported_tx_capacity_modules[cap_type]
        if hasattr(module, "min_limit_is_unconstrained_rule"):
            return module.min_limit_is_unconstrained_rule(mod, tx, p)
        return False

    def tx_max_limit_is_unconstrained(mod, tx, p):
        cap_type = mod.tx_capacity_type[tx]
        module = imported_tx_capacity_modules[cap_type]
        if hasattr(module, "max_limit_is_unconstrained_rule"):
            return module.max_limit_is_unconstrained_rule(mod, tx, p)
        return False

    m.TX_OPR_PRDS_W_MIN_LIMIT = Set(
        dimen=2,
        within=m.TX_OPR_PRDS,
        initialize=lambda mod: [
            (tx, p)
            for (tx, p) in mod.TX_OPR_PRDS
            if not tx_min_limit_is_unconstrained(mod, tx, p)
        ],
    )

    m.TX_OPR_PRDS_W_MAX_LIMIT = Set(
        dimen=2,
        within=m.TX_OPR_PRDS,
        initialize=lambda mod: [
            (tx, p)
            for (tx, p) in mod.TX_OPR_PRDS
            if not tx_max_limit_is_unconstrained(mod, tx, p)
        ],
    )


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

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    # First create the dataframe with main capacity results

    results_columns = [
        "min_mw",
        "max_mw",
    ]

    # An unconstrained line-period has an infinite capacity; report it as
    # NULL rather than the literal "inf" so the results stay numeric.
    def _finite_or_none(v):
        return None if math.isinf(v) else v

    data = [
        [
            tx_line,
            prd,
            _finite_or_none(value(m.Tx_Min_Capacity_MW[tx_line, prd])),
            _finite_or_none(value(m.Tx_Max_Capacity_MW[tx_line, prd])),
        ]
        for (tx_line, prd) in m.TX_OPR_PRDS
    ]

    results_df = create_results_df(
        index_columns=["transmission_line", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    for c in results_columns:
        getattr(d, TX_PERIOD_DF)[c] = None
    getattr(d, TX_PERIOD_DF).update(results_df)

    # Module-specific capacity results
    required_capacity_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="tx_capacity_type",
        filename="transmission_lines",
    )

    # Import needed transmission capacity type modules
    imported_capacity_modules = load_tx_capacity_type_modules(required_capacity_modules)

    for op_m in required_capacity_modules:
        if hasattr(imported_capacity_modules[op_m], "add_to_tx_period_results"):
            results_columns, optype_df = imported_capacity_modules[
                op_m
            ].add_to_tx_period_results(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                m,
                d,
            )
            for column in results_columns:
                if column not in getattr(d, TX_PERIOD_DF):
                    getattr(d, TX_PERIOD_DF)[column] = None
            getattr(d, TX_PERIOD_DF).update(optype_df)


def save_duals(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    instance,
    dynamic_components,
):
    # Save module-specific duals
    # Capacity type modules
    df = pd.read_csv(
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
        sep="\t",
        usecols=["transmission_line", "tx_capacity_type", "tx_operational_type"],
    )

    # Required capacity modules are the unique set of tx capacity types
    # This list will be used to know which capacity modules to load
    required_tx_capacity_modules = df.tx_capacity_type.unique()

    # Import needed transmission capacity type modules for expression rules
    imported_tx_capacity_modules = load_tx_capacity_type_modules(
        required_tx_capacity_modules
    )

    # Add any components specific to the operational modules
    for op_m in required_tx_capacity_modules:
        if hasattr(imported_tx_capacity_modules[op_m], "save_duals"):
            imported_tx_capacity_modules[op_m].save_duals(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                instance,
                dynamic_components,
            )


# Database
###############################################################################


def process_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate capacity costs by "to_zone" load zone, and break out into
    spinup_or_lookahead.
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate tx capacity costs by load zone")

    # Delete old resulst
    del_sql = """
        DELETE FROM results_transmission_costs_capacity_agg 
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Insert new results
    agg_sql = """
        INSERT INTO results_transmission_costs_capacity_agg
        (scenario_id, load_zone, period, subproblem_id, stage_id,
        spinup_or_lookahead, fraction_of_hours_in_subproblem, capacity_cost)

        SELECT scenario_id, load_zone, period, subproblem_id, stage_id,
        spinup_or_lookahead, fraction_of_hours_in_subproblem,
        (capacity_cost * fraction_of_hours_in_subproblem) AS capacity_cost
        FROM spinup_or_lookahead_ratios

        -- Add load_zones
        LEFT JOIN
        (SELECT scenario_id, load_zone
        FROM inputs_geography_load_zones
        INNER JOIN
        (SELECT scenario_id, load_zone_scenario_id FROM scenarios
        WHERE scenario_id = ?) AS scen_tbl
        USING (load_zone_scenario_id)
        ) AS lz_tbl
        USING (scenario_id)

        -- Now that we have all scenario_id, subproblem_id, stage_id, period, 
        -- load_zone, and spinup_or_lookahead combinations add the tx capacity 
        -- costs which will be derated by the fraction_of_hours_in_subproblem
        INNER JOIN
        (SELECT scenario_id, subproblem_id, stage_id, period, 
        load_zone_to AS load_zone,
        SUM(capacity_cost) AS capacity_cost
        FROM results_transmission_period
        GROUP BY scenario_id, subproblem_id, stage_id, period, load_zone
        ) AS cap_table
        USING (scenario_id, subproblem_id, stage_id, period, load_zone)
        ;"""

    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )
