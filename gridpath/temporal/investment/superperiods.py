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
Superperiods are combinations of periods over which variable and constraints
can be defined.
"""

import csv
from itertools import combinations
import os.path

from pyomo.environ import Set, Param, PositiveIntegers, NonNegativeReals

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    get_expected_dtypes,
    validate_dtypes,
    validate_values,
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
    | | :code:`SUPERPERIOD_PERIODS`                                           |
    | | *Within*: :code:`PositiveIntegers`                                    |
    |                                                                         |
    | The list of all superperiods being modeled.                             |
    +-------------------------------------------------------------------------+
    """

    # Sets
    ###########################################################################

    m.SUPERPERIOD_PERIODS = Set(dimen=2, within=PositiveIntegers * m.PERIODS)

    m.SUPERPERIODS = Set(
        within=PositiveIntegers,
        initialize=lambda mod: sorted(
            list(set([s_p for (s_p, p) in mod.SUPERPERIOD_PERIODS])),
        ),
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
    input_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "superperiods.tab",
    )

    if os.path.exists(input_file):
        data_portal.load(
            filename=input_file,
            set=m.SUPERPERIOD_PERIODS,
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

    c = conn.cursor()

    superperiod_periods = c.execute(f"""
        SELECT superperiod, period
        FROM inputs_temporal_superperiods 
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND period in (
            SELECT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        );""")

    return superperiod_periods


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
    periods.tab file.
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

    superperiod_periods = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    ).fetchall()

    if superperiod_periods:
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "superperiods.tab",
            ),
            "w",
            newline="",
        ) as periods_tab_file:
            writer = csv.writer(periods_tab_file, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(
                [
                    "superperiod",
                    "period",
                ]
            )

            for row in superperiod_periods:
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

    superperiod_periods = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    ).fetchall()

    c = conn.cursor()
    prev_period_by_period = dict(c.execute(f"""
            SELECT period, prev_period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND prev_period IS NOT NULL;
            """).fetchall())

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_temporal_superperiods",
        severity="High",
        errors=validate_superperiods_on_single_trajectory(
            superperiod_periods, prev_period_by_period
        ),
    )


def validate_superperiods_on_single_trajectory(
    superperiod_periods, prev_period_by_period
):
    """
    Check that no superperiod spans sibling branches of the period tree.

    :param superperiod_periods: list of (superperiod, period) tuples
    :param prev_period_by_period: dict of prev_period by period for the
        periods with a prev_period specified (empty for a deterministic
        problem, in which case all periods are on one trajectory)
    :return: list of error strings (empty if the inputs are valid)

    Quantities aggregated over a superperiod (e.g. subsidy program budgets)
    would double-count alternative futures if the superperiod included
    periods from different branches, so every pair of periods in a
    superperiod must be on the same trajectory, i.e. one must be an
    ancestor of the other.
    """
    if not prev_period_by_period:
        return []

    def ancestors_and_self(period):
        found = [period]
        while period in prev_period_by_period:
            period = prev_period_by_period[period]
            if period in found:
                break  # a cycle; reported by the periods validation
            found.append(period)
        return set(found)

    periods_by_superperiod = {}
    for superperiod, period in superperiod_periods:
        periods_by_superperiod.setdefault(superperiod, []).append(period)

    errors = []
    for superperiod, periods in sorted(periods_by_superperiod.items()):
        trajectory = {p: ancestors_and_self(p) for p in periods}
        for p1, p2 in combinations(sorted(periods), 2):
            if p1 not in trajectory[p2] and p2 not in trajectory[p1]:
                errors.append(
                    f"Superperiod {superperiod} includes periods {p1} and {p2}, "
                    f"which are on different branches of the period tree; a "
                    f"superperiod must lie on a single trajectory"
                )

    return errors
