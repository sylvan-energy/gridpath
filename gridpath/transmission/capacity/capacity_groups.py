# Copyright 2022 (c) Crown Copyright, GC.
# Modifications Copyright 2023 Blue Marble Analytics LLC.
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
Minimum and maximum new and total capacity by period and transmission line group.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import Set, Param, Constraint, NonNegativeReals, Expression, value

from gridpath.auxiliary.auxiliary import get_required_subtype_modules
from gridpath.auxiliary.db_interface import import_csv, directories_to_db_values
import gridpath.transmission.capacity.capacity_types as cap_type_init
from gridpath.transmission.capacity.common_functions import (
    load_tx_capacity_type_modules,
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
    | | :code:`TX_CAPACITY_GROUP_PERIODS`                                     |
    |                                                                         |
    | A two-dimensional set of group-period combinations for which there may  |
    | be group capacity requirements.                                         |
    +-------------------------------------------------------------------------+
    | | :code:`TX_CAPACITY_GROUPS`                                            |
    |                                                                         |
    | The groups of transmission lines for which there may be group capacity  |
    | requirements.                                                           |
    +-------------------------------------------------------------------------+
    | | :code:`TX_IN_TX_CAPACITY_GROUP`                                       |
    |                                                                         |
    | The list of transmission lines by capacity group.                       |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`tx_capacity_group_new_capacity_min`                            |
    | | *Defined over*: :code:`TX_CAPACITY_GROUP_PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`0`                                                  |
    |                                                                         |
    | The minimum amount of capacity (in MW) that must be built at            |
    | transmission lines in this group in a given period.                     |
    +-------------------------------------------------------------------------+
    | | :code:`tx_capacity_group_new_capacity_max`                            |
    | | *Defined over*: :code:`TX_CAPACITY_GROUP_PERIODS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`inf`                                                |
    |                                                                         |
    | The maximum amount of capacity (in MW) that may be built at             |
    | transmission lines in this group in a given period.                     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Tx_Group_New_Capacity_in_Period`                               |
    | | *Defined over*: :code:`TX_CAPACITY_GROUP_PERIODS`                     |
    |                                                                         |
    | The new capacity built at transmission lines in this group in this      |
    | period.                                                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Max_Tx_Group_Build_in_Period_Constraint`                       |
    | | *Defined over*: :code:`TX_CAPACITY_GROUP_PERIODS`                     |
    |                                                                         |
    | Limits the amount of new build in each group in each period.            |
    +-------------------------------------------------------------------------+
    | | :code:`Min_Tx_Group_Build_in_Period_Constraint`                       |
    | | *Defined over*: :code:`TX_CAPACITY_GROUP_PERIODS`                     |
    |                                                                         |
    | Requires a certain amount of new build in each group in each period.    |
    +-------------------------------------------------------------------------+

    """

    # Sets
    m.TX_CAPACITY_GROUP_PERIODS = Set(dimen=2)

    m.TX_CAPACITY_GROUPS = Set(
        initialize=lambda mod: sorted(
            list(set([g for (g, p) in mod.TX_CAPACITY_GROUP_PERIODS]))
        )
    )

    m.TX_IN_TX_CAPACITY_GROUP = Set(m.TX_CAPACITY_GROUPS, within=m.TX_LINES)

    # Params
    m.tx_capacity_group_new_capacity_min = Param(
        m.TX_CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=0
    )
    m.tx_capacity_group_new_capacity_max = Param(
        m.TX_CAPACITY_GROUP_PERIODS, within=NonNegativeReals, default=float("inf")
    )

    # Import needed capacity type modules
    required_tx_capacity_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        filename="transmission_lines",
        which_type="tx_capacity_type",
    )

    imported_tx_capacity_modules = load_tx_capacity_type_modules(
        required_tx_capacity_modules
    )

    # Get the new and total capacity in the group for the respective
    # expressions
    def new_capacity_rule(mod, tx, prd):
        cap_type = mod.tx_capacity_type[tx]
        # The tx capacity type modules check if this period is a "vintage" for
        # this project and return 0 if not
        if hasattr(imported_tx_capacity_modules[cap_type], "new_capacity_rule"):
            return imported_tx_capacity_modules[cap_type].new_capacity_rule(
                mod, tx, prd
            )
        else:
            return cap_type_init.new_capacity_rule(mod, tx, prd)

    # Expressions
    def tx_group_new_capacity_rule(mod, grp, prd):
        return sum(
            new_capacity_rule(mod, tx, prd) for tx in mod.TX_IN_TX_CAPACITY_GROUP[grp]
        )

    m.Tx_Group_New_Capacity_in_Period = Expression(
        m.TX_CAPACITY_GROUP_PERIODS, rule=tx_group_new_capacity_rule
    )

    # Constraints
    # Limit the min and max amount of new build in a group-period
    m.Max_Tx_Group_Build_in_Period_Constraint = Constraint(
        m.TX_CAPACITY_GROUP_PERIODS, rule=new_capacity_max_rule
    )

    m.Min_Tx_Group_Build_in_Period_Constraint = Constraint(
        m.TX_CAPACITY_GROUP_PERIODS, rule=new_capacity_min_rule
    )


# Constraint Formulation Rules
###############################################################################
def new_capacity_max_rule(mod, grp, prd):
    if mod.tx_capacity_group_new_capacity_max[grp, prd] == float("inf"):
        return Constraint.Feasible
    else:
        return (
            mod.Tx_Group_New_Capacity_in_Period[grp, prd]
            <= mod.tx_capacity_group_new_capacity_max[grp, prd]
        )


def new_capacity_min_rule(mod, grp, prd):
    if mod.tx_capacity_group_new_capacity_min[grp, prd] == 0:
        return Constraint.Feasible
    else:
        return (
            mod.Tx_Group_New_Capacity_in_Period[grp, prd]
            >= mod.tx_capacity_group_new_capacity_min[grp, prd]
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
    """ """
    # Only load data if the input files were written; otherwise, we won't
    # initialize the components in this module

    req_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_capacity_group_requirements.tab",
    )
    if os.path.exists(req_file):
        data_portal.load(
            filename=req_file,
            index=m.TX_CAPACITY_GROUP_PERIODS,
            param=(
                m.tx_capacity_group_new_capacity_min,
                m.tx_capacity_group_new_capacity_max,
            ),
        )

    tx_file = os.path.join(
        scenario_directory,
        subproblem,
        stage,
        "inputs",
        "transmission_capacity_group_transmission_lines.tab",
    )
    if os.path.exists(tx_file):
        tx_groups_df = pd.read_csv(tx_file, delimiter="\t")
        tx_groups_dict = {
            g: v["transmission_line"].tolist()
            for g, v in tx_groups_df.groupby("transmission_capacity_group")
        }
        data_portal.data()["TX_IN_TX_CAPACITY_GROUP"] = tx_groups_dict


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
    """ """
    req_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_capacity_group_requirements.tab",
    )
    tx_file = os.path.join(
        scenario_directory,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_capacity_group_transmission_lines.tab",
    )

    if os.path.exists(req_file) and os.path.exists(tx_file):
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "results",
                "transmission_group_capacity.csv",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "transmission_capacity_group",
                    "period",
                    "new_capacity",
                    "transmission_capacity_group_new_capacity_min",
                    "transmission_capacity_group_new_capacity_max",
                ]
            )
            for grp, prd in sorted(m.TX_CAPACITY_GROUP_PERIODS):
                writer.writerow(
                    [
                        grp,
                        prd,
                        value(m.Tx_Group_New_Capacity_in_Period[grp, prd]),
                        m.tx_capacity_group_new_capacity_min[grp, prd],
                        m.tx_capacity_group_new_capacity_max[grp, prd],
                    ]
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
    cap_grp_reqs = c1.execute("""
        SELECT transmission_capacity_group, period,
        transmission_capacity_group_new_capacity_min, transmission_capacity_group_new_capacity_max
        FROM inputs_transmission_capacity_group_requirements
        WHERE transmission_capacity_group_requirement_scenario_id = {}
        """.format(subscenarios.TRANSMISSION_CAPACITY_GROUP_REQUIREMENT_SCENARIO_ID))

    c2 = conn.cursor()
    cap_grp_tx = c2.execute(
        """
        SELECT DISTINCT transmission_capacity_group, transmission_line
        FROM
        (SELECT transmission_line FROM inputs_transmission_portfolios
        WHERE transmission_portfolio_scenario_id = {}) AS prj_tbl
        INNER JOIN 
        (SELECT transmission_capacity_group, transmission_line
        FROM inputs_transmission_capacity_groups
        WHERE transmission_capacity_group_scenario_id = {})
        AS cap_group_tbl
        USING (transmission_line);
        """.format(
            subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID,
            subscenarios.TRANSMISSION_CAPACITY_GROUP_SCENARIO_ID,
        )
    )

    return cap_grp_reqs, cap_grp_tx


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
    """ """

    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )

    cap_grp_reqs, cap_grp_tx = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # Write the input files only if a subscenario is specified
    if subscenarios.TRANSMISSION_CAPACITY_GROUP_REQUIREMENT_SCENARIO_ID != "NULL":
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "transmission_capacity_group_requirements.tab",
            ),
            "w",
            newline="",
        ) as req_file:
            writer = csv.writer(req_file, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(
                [
                    "transmission_capacity_group",
                    "period",
                    "transmission_capacity_group_new_capacity_min",
                    "transmission_capacity_group_new_capacity_max",
                ]
            )

            for row in cap_grp_reqs:
                replace_nulls = ["." if i is None else i for i in row]
                writer.writerow(replace_nulls)

    if subscenarios.TRANSMISSION_CAPACITY_GROUP_SCENARIO_ID != "NULL":
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "transmission_capacity_group_transmission_lines.tab",
            ),
            "w",
            newline="",
        ) as prj_file:
            writer = csv.writer(prj_file, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(["transmission_capacity_group", "transmission_line"])

            for row in cap_grp_tx:
                writer.writerow(row)


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
    which_results = "transmission_group_capacity"

    if os.path.exists(
        os.path.join(
            results_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            f"{which_results}.csv",
        )
    ):
        import_csv(
            conn=db,
            cursor=c,
            scenario_id=scenario_id,
            subproblem=subproblem,
            stage=stage,
            quiet=quiet,
            results_directory=results_directory,
            which_results=which_results,
        )
