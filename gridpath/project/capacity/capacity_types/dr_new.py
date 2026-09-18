# Copyright 2016-2023 Blue Marble Analytics LLC.
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
This type is a custom implementation for GridPath projects in the California
Integrated Resource Planning proceeding (2018ish). It is outdated.

This capacity type describes a supply curve for new shiftable load (DR; demand
response) capacity. The supply curve does not have vintages, i.e. there are
no cost differences for capacity built in different periods. The cost for
new capacity is specified via a piecewise linear function of new capacity
build and constraint (cost is constrained to be greater than or equal to the
function).

The new capacity build variable has units of MWh. We then calculate the
power capacity based on the 'minimum duration' specified for the project,
e.g. if the minimum duration specified is N hours, then the MW capacity will
be the new build in MWh divided by N (the MWh capacity can't be discharged
in less than N hours, as the max power constraint will bind).
"""

import csv
import os.path
import pandas as pd
from pathlib import Path
from pyomo.environ import (
    Set,
    Param,
    Var,
    NonNegativeReals,
    value,
    Reals,
    Expression,
    Constraint,
)

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.dynamic_components import (
    capacity_type_operational_period_sets,
    capacity_type_financial_period_sets,
)
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_missing_inputs,
    validate_idxs,
    get_projects,
)
from gridpath.common_functions import create_results_df
from gridpath.project.capacity.capacity_types.common_methods import (
    read_results_file_generic,
    write_summary_results_generic,
    get_units,
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
    | | :code:`DR_NEW`                                                        |
    |                                                                         |
    | The list of :code:`dr_new` projects being modeled.                      |
    +-------------------------------------------------------------------------+
    | | :code:`DR_NEW_OPR_PRDS`                                               |
    |                                                                         |
    | Two-dimensional set of all :code:`dr_new` projects and their            |
    | operational periods. All periods for now.                               |
    +-------------------------------------------------------------------------+
    | | :code:`DR_NEW_FIN_PRDS`                                               |
    |                                                                         |
    | Two-dimensional set of all :code:`dr_new` projects and their            |
    | financial periods (annual costs incurred). All periods for now.         |
    +-------------------------------------------------------------------------+
    | | :code:`DR_NEW_PTS`                                                    |
    |                                                                         |
    | Two-dimensional set of all :code:`dr_new` projects and their supply     |
    | curve points.                                                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`dr_new_min_duration`                                           |
    | | *Defined over*: :code:`DR_NEW`                                        |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's duration in hours, i.e. how many hours the load can be    |
    | shifted.                                                                |
    +-------------------------------------------------------------------------+
    | | :code:`dr_new_min_cumulative_new_build_mwh`                           |
    | | *Defined over*: :code:`DR_NEW_OPR_PRDS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The minimum cumulative amount of shiftable load capacity (in MWh) that  |
    | must be built for a project by a certain period.                        |
    +-------------------------------------------------------------------------+
    | | :code:`dr_new_max_cumulative_new_build_mwh`                           |
    | | *Defined over*: :code:`DR_NEW_OPR_PRDS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The maximum cumulative amount of shiftable load capacity (in MWh) that  |
    | must be built for a project by a certain period.                        |
    +-------------------------------------------------------------------------+
    | | :code:`dr_new_supply_curve_slope`                                     |
    | | *Defined over*: :code:`DR_NEW_PTS`                                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's slope for each point (section) in the piecewise linear    |
    | supply cost curve, in $ per MWh.                                        |
    +-------------------------------------------------------------------------+
    | | :code:`dr_new_supply_curve_intercept`                                 |
    | | *Defined over*: :code:`DR_NEW_PTS`                                    |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's intercept for each point (section) in the piecewise       |
    | linear supply cost curve, in $.                                         |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`DRNew_Build_MWh`                                               |
    | | *Defined over*: :code:`DR_NEW_OPR_PRDS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Determines how much shiftable load capacity (in MWh) is built in each   |
    | operational period.                                                     |
    +-------------------------------------------------------------------------+
    | | :code:`DRNew_Cost`                                                    |
    | | *Defined over*: :code:`DR_NEW_OPR_PRDS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The cost of new shiftable load capacity in each operational period.     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`DRNew_Energy_Storage_Capacity_MWh`                             |
    | | *Defined over*: :code:`DR_NEW_OPR_PRDS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's total energy capacity (in MWh) in each operational period |
    | is the sum of the new-built energy capacity in all of the previous      |
    | periods.                                                                |
    +-------------------------------------------------------------------------+
    | | :code:`DRNew_Power_Capacity_MW`                                       |
    | | *Defined over*: :code:`DR_NEW_OPR_PRDS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The project's total power capacity (in MW) in each operational period   |
    | is equal to the total energy capacity in that period, divided by the    |
    | project's minimum duraiton (in hours).                                  |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`DRNew_Cost_Constraint`                                         |
    | | *Defined over*: :code:`DR_NEW_PTS*PERIODS`                            |
    |                                                                         |
    | Ensures that the project's cost in each operational period is larger    |
    | than the calculated piecewise linear cost in each segment. Only one     |
    | segment will bind at a time.                                            |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.DR_NEW = Set()

    m.DR_NEW_OPR_PRDS = Set(dimen=2, initialize=m.DR_NEW * m.PERIODS)
    m.DR_NEW_FIN_PRDS = Set(dimen=2, initialize=m.DR_NEW * m.PERIODS)

    m.DR_NEW_PTS = Set(dimen=2, within=m.DR_NEW * list(range(1, 1001)))

    # Required Params
    ###########################################################################

    m.dr_new_min_duration = Param(m.DR_NEW, within=NonNegativeReals)

    m.dr_new_min_cumulative_new_build_mwh = Param(
        m.DR_NEW, m.PERIODS, within=NonNegativeReals  # TODO: change to DR_NEW_OPR_PRDS?
    )

    m.dr_new_max_cumulative_new_build_mwh = Param(
        m.DR_NEW, m.PERIODS, within=NonNegativeReals  # TODO: change to DR_NEW_OPR_PRDS?
    )

    m.dr_new_supply_curve_slope = Param(m.DR_NEW_PTS, within=NonNegativeReals)

    m.dr_new_supply_curve_intercept = Param(m.DR_NEW_PTS, within=Reals)

    # Variables
    ###########################################################################

    m.DRNew_Build_MWh = Var(
        m.DR_NEW, m.PERIODS, within=NonNegativeReals  # TODO: change to DR_NEW_OPR_PRDS?
    )

    m.DRNew_Cost = Var(m.DR_NEW_OPR_PRDS, within=NonNegativeReals)

    # Expressions
    ###########################################################################

    m.DRNew_Energy_Storage_Capacity_MWh = Expression(
        m.DR_NEW_OPR_PRDS, rule=dr_new_energy_stor_capacity_rule
    )

    m.DRNew_Power_Capacity_MW = Expression(
        m.DR_NEW_OPR_PRDS, rule=dr_new_power_capacity_rule
    )

    # Constraints
    ###########################################################################

    m.DRNew_Cost_Constraint = Constraint(
        m.DR_NEW_PTS * m.PERIODS, rule=cost_rule  # TODO: define new set?
    )

    # Dynamic Components
    ###########################################################################

    # Add to list of sets we'll join to get the final PRJ_OPR_PRDS set
    getattr(d, capacity_type_operational_period_sets).append(
        "DR_NEW_OPR_PRDS",
    )

    # Add to list of sets we'll join to get the final PRJ_FIN_PRDS set
    getattr(d, capacity_type_financial_period_sets).append(
        "DR_NEW_FIN_PRDS",
    )


# Expression Rules
###############################################################################


def dr_new_energy_stor_capacity_rule(mod, g, p):
    """
    **Expression Name**: DRNew_Energy_Storage_Capacity_MWh
    **Defined Over**: DR_NEW_OPR_PRDS

    Total energy capacity in each period is the sum of all new build over the
    previous periods (including the current period). Previous periods are
    the periods on the path from the first period to this period, so on a
    stochastic scenario tree, build in a sibling branch does not count.

    Vintages = all periods
    """
    return sum(
        mod.DRNew_Build_MWh[g, prev_p]
        for prev_p in mod.FUTURE_TRAJECTORY_PREV_PERIODS_BY_PERIOD[p]
    )


def dr_new_power_capacity_rule(mod, g, p):
    """
    **Expression Name**: DRNew_Power_Capacity_MW
    **Defined Over**: DR_NEW_OPR_PRDS

    Vintages = all periods
    """
    return mod.DRNew_Energy_Storage_Capacity_MWh[g, p] / mod.dr_new_min_duration[g]


# Constraint Formulation Rules
###############################################################################


def cost_rule(mod, project, point, period):
    """
    **Constraint Name**: DRNew_Cost_Constraint
    **Enforced Over**: m.DR_NEW_PTS*m.PERIODS

    For each segment on the piecewise linear curve, the cost variable is
    constrained to be equal to or larger than the calculated value on the
    curve. Depending on the cumulative build (*DRNew_Energy_Storage_Capacity_MWh*)
    only one segment is active at a time. The supply curve is assumed to be
    convex, i.e. costs increase at an increasing rate as you move up the
    curve.
    """
    return (
        mod.DRNew_Cost[project, period]
        >= mod.dr_new_supply_curve_slope[project, point]
        * mod.DRNew_Energy_Storage_Capacity_MWh[project, period]
        + mod.dr_new_supply_curve_intercept[project, point]
    )


# Capacity Type Methods
###############################################################################


def capacity_rule(mod, g, p):
    """
    The total power capacity of dr_new operational in period p.
    """
    return mod.DRNew_Power_Capacity_MW[g, p]


def energy_stor_capacity_rule(mod, g, p):
    """
    The total energy capacity of dr_new operational in period p.
    """
    return mod.DRNew_Energy_Storage_Capacity_MWh[g, p]


def capacity_cost_rule(mod, g, p):
    """ """
    return mod.DRNew_Cost[g, p]


def new_capacity_rule(mod, g, p):
    """
    New capacity built at project g in period p.
    """
    return mod.DRNew_Power_Capacity_MW[g, p]


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
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """

    def determine_projects():
        projects = list()
        max_fraction = dict()

        df = pd.read_csv(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "projects.tab",
            ),
            sep="\t",
            usecols=["project", "capacity_type", "minimum_duration_hours"],
        )
        for r in zip(df["project"], df["capacity_type"], df["minimum_duration_hours"]):
            if r[1] == "dr_new":
                projects.append(r[0])
                max_fraction[r[0]] = float(r[2])

        return projects, max_fraction

    data_portal.data()["DR_NEW"] = {None: determine_projects()[0]}
    data_portal.data()["dr_new_min_duration"] = determine_projects()[1]

    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "new_shiftable_load_supply_curve.tab",
        ),
        index=m.DR_NEW_PTS,
        select=("project", "point", "slope", "intercept"),
        param=(m.dr_new_supply_curve_slope, m.dr_new_supply_curve_intercept),
    )

    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "new_shiftable_load_supply_curve_potential.tab",
        ),
        param=(
            m.dr_new_min_cumulative_new_build_mwh,
            m.dr_new_max_cumulative_new_build_mwh,
        ),
    )


def add_to_project_period_results(
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
    Export new DR results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """
    results_columns = [
        "new_build_mw",
        "new_build_mwh",
    ]
    data = [
        [
            prj,
            prd,
            value(m.DRNew_Build_MWh[prj, prd] / m.dr_new_min_duration[prj]),
            value(m.DRNew_Build_MWh[prj, prd]),
        ]
        for (prj, prd) in m.DR_NEW_OPR_PRDS
    ]
    captype_df = create_results_df(
        index_columns=["project", "period"],
        results_columns=results_columns,
        data=data,
    )

    return results_columns, captype_df


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

    if subscenarios.PROJECT_NEW_POTENTIAL_SCENARIO_ID is None:
        raise ValueError(
            "Maximum potential must be specified for new "
            "shiftable load supply curve projects."
        )

    c1 = conn.cursor()
    min_max_builds = c1.execute(
        """SELECT project, period, 
        min_cumulative_new_build_mwh, max_cumulative_new_build_mwh
        FROM inputs_project_portfolios
        CROSS JOIN
        (SELECT period
        FROM inputs_temporal_periods
        WHERE temporal_scenario_id = {}) as relevant_periods
        LEFT OUTER JOIN
        (SELECT project, period,
        min_cumulative_new_build_mw, min_cumulative_new_build_mwh,
        max_cumulative_new_build_mw, max_cumulative_new_build_mwh
        FROM inputs_project_new_potential
        WHERE project_new_potential_scenario_id = {}) as potential
        USING (project, period) 
        WHERE project_portfolio_scenario_id = {}
        AND capacity_type = '{}';""".format(
            subscenarios.TEMPORAL_SCENARIO_ID,
            subscenarios.PROJECT_NEW_POTENTIAL_SCENARIO_ID,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            "dr_new",
        )
    )

    c2 = conn.cursor()
    supply_curve_count = c2.execute(
        """SELECT project, COUNT(DISTINCT(supply_curve_scenario_id))
        FROM inputs_project_portfolios
        LEFT OUTER JOIN inputs_project_new_cost
        USING (project)
        WHERE project_portfolio_scenario_id = {}
        AND project_new_cost_scenario_id = {}
        AND capacity_type = '{}'
        GROUP BY project;""".format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_NEW_COST_SCENARIO_ID,
            "dr_new",
        )
    )

    c3 = conn.cursor()
    supply_curve_id = c3.execute(
        """SELECT DISTINCT supply_curve_scenario_id
        FROM inputs_project_portfolios
        LEFT OUTER JOIN inputs_project_new_cost
        USING (project)
        WHERE project_portfolio_scenario_id = {}
        AND project_new_cost_scenario_id = {}
        AND project = 'Shift_DR';""".format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_NEW_COST_SCENARIO_ID,
        )
    ).fetchone()[0]

    c4 = conn.cursor()
    supply_curve = c4.execute(
        """SELECT project, supply_curve_point, supply_curve_slope, 
        supply_curve_intercept
        FROM inputs_project_shiftable_load_supply_curve
        WHERE supply_curve_scenario_id = {}""".format(supply_curve_id)
    )

    return min_max_builds, supply_curve_count, supply_curve_id, supply_curve


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
    new_shiftable_load_supply_curve_potential.tab and
    new_shiftable_load_supply_curve.tab files

    Max potential is required for this module, so
    PROJECT_NEW_POTENTIAL_SCENARIO_ID can't be NULL

    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    (
        min_max_builds,
        supply_curve_count,
        supply_curve_id,
        supply_curve,
    ) = get_model_inputs_from_database(
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
            "new_shiftable_load_supply_curve_potential.tab",
        ),
        "w",
        newline="",
    ) as potentials_tab_file:
        writer = csv.writer(potentials_tab_file, delimiter="\t", lineterminator="\n")

        writer.writerow(
            [
                "project",
                "period",
                "min_cumulative_new_build_mwh",
                "max_cumulative_new_build_mwh",
            ]
        )

        for row in min_max_builds:
            replace_nulls = ["." if i is None else i for i in row]
            writer.writerow(replace_nulls)

    # Supply curve
    # No supply curve periods for now, so check that we have only specified
    # a single supply curve for all periods in inputs_project_new_cost
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "new_shiftable_load_supply_curve.tab",
        ),
        "w",
        newline="",
    ) as supply_curve_tab_file:
        writer = csv.writer(supply_curve_tab_file, delimiter="\t", lineterminator="\n")

        writer.writerow(["project", "point", "slope", "intercept"])

        for proj in supply_curve_count:
            project = proj[0]
            if proj[1] > 1:
                raise ValueError(
                    "Only a single supply curve can be specified "
                    "for project {} because no vintages have "
                    "been implemented for "
                    "'dr_new' capacity "
                    "type.".format(project)
                )
            else:
                for row in supply_curve:
                    writer.writerow(row)


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

    (
        min_max_builds,
        supply_curve_count,
        supply_curve_id,
        supply_curve,
    ) = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )
    projects = get_projects(conn, scenario_id, subscenarios, "capacity_type", "dr_new")

    # Convert input data into pandas DataFrame
    df = cursor_to_df(min_max_builds)
    df_sc = cursor_to_df(supply_curve)

    dr_projects = df_sc["project"].unique()

    # Check for missing project potential inputs
    cols = ["min_cumulative_new_build_mwh", "max_cumulative_new_build_mwh"]
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
        errors=validate_missing_inputs(df, cols),
    )

    # Check for missing supply curve inputs
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_shiftable_load_supply_curve",
        severity="High",
        errors=validate_idxs(
            actual_idxs=dr_projects, req_idxs=projects, idx_label="project"
        ),
    )
