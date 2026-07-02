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
This capacity type describes transmission lines that are available to the
optimization without having to incur an investment cost, e.g. existing
lines or lines that will be built in the future and whose capital costs
we want to ignore (in the objective function). A specified transmission line
can be available in all periods, or in some periods only, with no
restriction on the order and combination of periods. The two transmission
line directions may have different specified capacities, e.g. a line from
Zone 1 to Zone 2 with a minimum flow capacity of -1,000 MW and a maximum flow
capacity of 1,200 MW can transmit up to 1,000 MW from Zone 2 to Zone 1 and
up to 1,200 MW from Zone 1 to Zone 2.

"""

import csv
import os.path
import pandas as pd
from statistics import mean

from pyomo.environ import Set, Param, Reals, NonNegativeReals

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.dynamic_components import (
    tx_capacity_type_operational_period_sets,
)
from gridpath.auxiliary.validations import (
    get_tx_lines,
    get_expected_dtypes,
    write_validation_to_database,
    validate_dtypes,
    validate_idxs,
    validate_column_monotonicity,
)

# A specified transmission line whose min (max) capacity is left blank in the
# inputs is treated as having no lower (upper) flow limit. The capacity params
# default to these sentinels, and the operational types skip the corresponding
# flow-limit constraint when the capacity is infinite (see
# min/max_limit_is_unconstrained_rule below).
Negative_Infinity = float("-inf")
Infinity = float("inf")


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
    | | :code:`TX_SPEC_OPR_PRDS`                                              |
    |                                                                         |
    | Two-dimensional set of transmission line-period combinations that       |
    | helps describe the transmission capacity available in a given period.   |
    | This set is added to the list of sets to join to get the final          |
    | :code:`TX_OPR_PRDS` set defined in                                      |
    | **gridpath.transmission.capacity.capacity**.                            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`tx_spec_min_cap_mw`                                            |
    | | *Defined over*: :code:`TX_SPEC_OPR_PRDS`                              |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The transmission line's specified minimum flow capacity (in MW) in      |
    | each operational period. A negative number designates flow in the       |
    | opposite direction of the defined line flow direction.                  |
    +-------------------------------------------------------------------------+
    | | :code:`tx_spec_max_cap_mw`                                            |
    | | *Defined over*: :code:`TX_SPEC_OPR_PRDS`                              |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The transmission line's specified maximum flow capacity (in MW) in      |
    | each operational period. A negative number designates flow in the       |
    | opposite direction of the defined line flow direction.                  |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`tx_spec_fixed_cost_per_mw_yr`                                  |
    | | *Defined over*: :code:`TX_SPEC_OPR_PRDS`                              |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | Fixed cost to be incurred in each operational period. Multiplied by the |
    | average of the absolute values of the min and max line capacity.        |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.TX_SPEC_OPR_PRDS = Set(dimen=2)

    # Required Params
    ###########################################################################

    # Optional caps: a blank min (max) in the inputs leaves the param at
    # -inf (+inf), which the operational type reads as "no lower (upper)
    # flow limit" and skips the corresponding constraint.
    m.tx_spec_min_cap_mw = Param(
        m.TX_SPEC_OPR_PRDS, within=Reals, default=Negative_Infinity
    )
    m.tx_spec_max_cap_mw = Param(
        m.TX_SPEC_OPR_PRDS, within=Reals, default=Infinity
    )
    m.tx_spec_fixed_cost_per_mw_yr = Param(
        m.TX_SPEC_OPR_PRDS, within=NonNegativeReals, default=0
    )

    # Dynamic Components
    ###########################################################################

    getattr(d, tx_capacity_type_operational_period_sets).append("TX_SPEC_OPR_PRDS")


# Transmission Capacity Type Methods
###############################################################################


def min_transmission_capacity_rule(mod, tx, p):
    return mod.tx_spec_min_cap_mw[tx, p]


def max_transmission_capacity_rule(mod, tx, p):
    return mod.tx_spec_max_cap_mw[tx, p]


def min_limit_is_unconstrained_rule(mod, tx, p):
    """Whether this line-period has no lower flow limit (blank min in inputs)."""
    return mod.tx_spec_min_cap_mw[tx, p] == Negative_Infinity


def max_limit_is_unconstrained_rule(mod, tx, p):
    """Whether this line-period has no upper flow limit (blank max in inputs)."""
    return mod.tx_spec_max_cap_mw[tx, p] == Infinity


def fixed_cost_rule(mod, g, p):
    """
    The fixed cost of Tx lines of the *tx_spec* capacity type is a
    pre-specified number equal to the average capacity times the per-mw fixed
    cost for each of the project's operational periods.

    A line with no flow limit (infinite min or max capacity) has no
    meaningful capacity to cost, so its fixed cost is zero.
    """
    if (
        mod.tx_spec_min_cap_mw[g, p] == Negative_Infinity
        or mod.tx_spec_max_cap_mw[g, p] == Infinity
    ):
        return 0
    return (
        mean([abs(mod.tx_spec_min_cap_mw[g, p]), abs(mod.tx_spec_max_cap_mw[g, p])])
        * mod.tx_spec_fixed_cost_per_mw_yr[g, p]
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
    # min and max capacities are optional (a blank cell means "no flow limit
    # in that direction"), so we cannot use a single data_portal.load() that
    # ties index membership to parsing every param column. Instead we read the
    # file manually, build TX_SPEC_OPR_PRDS from *every* row, and populate the
    # capacity params per-cell, skipping blanks so they fall back to the
    # ±Infinity defaults. This mirrors
    # transmission/operations/transmission_flow_limits.py.
    capacities_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "specified_transmission_line_capacities.tab",
    )

    df = pd.read_csv(capacities_file, sep="\t")

    opr_prds = []
    min_cap = {}
    max_cap = {}
    fixed_cost = {}
    for _, row in df.iterrows():
        tx = row["transmission_line"]
        prd = int(row["period"])
        opr_prds.append((tx, prd))
        # "." (or a blank read as NaN) leaves the param at its ±inf default.
        min_val = row["specified_tx_min_mw"]
        if str(min_val) != "." and pd.notna(min_val):
            min_cap[(tx, prd)] = float(min_val)
        max_val = row["specified_tx_max_mw"]
        if str(max_val) != "." and pd.notna(max_val):
            max_cap[(tx, prd)] = float(max_val)
        fc_val = row["fixed_cost_per_mw_yr"]
        if str(fc_val) != "." and pd.notna(fc_val):
            fixed_cost[(tx, prd)] = float(fc_val)

    data_portal.data()["TX_SPEC_OPR_PRDS"] = {None: opr_prds}
    data_portal.data()["tx_spec_min_cap_mw"] = min_cap
    data_portal.data()["tx_spec_max_cap_mw"] = max_cap
    data_portal.data()["tx_spec_fixed_cost_per_mw_yr"] = fixed_cost


# Database
###############################################################################


def get_model_inputs_from_database(
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
    db_subproblem = subproblem if subproblem != "" else 1
    c = conn.cursor()
    tx_capacities = c.execute(f"""SELECT transmission_line, period, min_mw, max_mw, 
        fixed_cost_per_mw_yr
        FROM inputs_transmission_portfolios
        CROSS JOIN
        (SELECT period
        FROM inputs_temporal_periods
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}) as relevant_periods
        INNER JOIN
        (SELECT transmission_line, period, min_mw, max_mw, fixed_cost_per_mw_yr
        FROM inputs_transmission_specified_capacity
        WHERE transmission_specified_capacity_scenario_id = {subscenarios.TRANSMISSION_SPECIFIED_CAPACITY_SCENARIO_ID} ) as capacity
        USING (transmission_line, period)
        WHERE transmission_portfolio_scenario_id = {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}
        AND period in (
                  SELECT DISTINCT period
                  FROM inputs_temporal
                  WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                  AND subproblem_id = {db_subproblem}
               )
        ;""")

    return tx_capacities


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
    specified_transmission_line_capacities.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    tx_capacities = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
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
            "specified_transmission_line_capacities.tab",
        ),
        "w",
        newline="",
    ) as existing_tx_capacity_tab_file:
        writer = csv.writer(
            existing_tx_capacity_tab_file, delimiter="\t", lineterminator="\n"
        )

        # Write header
        writer.writerow(
            [
                "transmission_line",
                "period",
                "specified_tx_min_mw",
                "specified_tx_max_mw",
                "fixed_cost_per_mw_yr",
            ]
        )

        for row in tx_capacities:
            replace_nulls = ["." if i is None else i for i in row]
            writer.writerow(replace_nulls)


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

    tx_capacities = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    tx_lines = get_tx_lines(conn, scenario_id, subscenarios, "capacity_type", "tx_spec")

    # Convert input data into pandas DataFrame and extract data
    df = cursor_to_df(tx_capacities)
    spec_tx_lines = df["transmission_line"].unique()

    # Get expected dtypes
    expected_dtypes = get_expected_dtypes(
        conn=conn, tables=["inputs_transmission_specified_capacity"]
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
        db_table="inputs_transmission_specified_capacity",
        severity="High",
        errors=dtype_errors,
    )

    # Ensure tx_line capacity is specified in at least 1 period
    msg = "Expected specified capacity for at least one period."
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_transmission_specified_capacity",
        severity="High",
        errors=validate_idxs(
            actual_idxs=spec_tx_lines,
            req_idxs=tx_lines,
            idx_label="transmission_line",
            msg=msg,
        ),
    )

    # Note: min_mw and max_mw are intentionally NOT checked for missing
    # values here -- a blank in either column is a valid input meaning "no
    # flow limit in that direction" (the capacity param falls back to its
    # ±Infinity default).

    # check that min <= max (validate_column_monotonicity drops NaN rows, so
    # lines with a blank/unconstrained min or max are skipped)
    cols = ["min_mw", "max_mw"]
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_new_potential",
        severity="High",
        errors=validate_column_monotonicity(
            df=df, cols=cols, idx_col=["project", "period"]
        ),
    )
