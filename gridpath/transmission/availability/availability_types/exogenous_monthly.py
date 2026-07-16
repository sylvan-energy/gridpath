# Copyright 2016-2025 Blue Marble Analytics LLC.
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
For each transmisison line assigned this *availability type*, the user may
specify an (un)availability schedule, i.e. a capacity derate for each
timepoint in which the line may be operated. If fully derated in a given
timepoint, the available transmission capacity will be 0 in that timepoint
and all operational decision variables will therefore also be constrained to 0 in the
optimization.

"""

import csv
import os.path
from pyomo.environ import Param, Set, NonNegativeReals

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    get_expected_dtypes,
    validate_dtypes,
    validate_values,
    validate_missing_inputs,
)
from gridpath.project.common_functions import determine_project_subset

# The exogenous monthly derates are fixed input data, so the
# availability derate is a constant in the model
DERATE_IS_CONSTANT = True


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
    | | :code:`TX_AVL_EXOG_MNTH`                                              |
    |                                                                         |
    | The set of transmission lines of the :code:`exogenous_monthly`          |
    | availability type.                                                      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`tx_avl_exog_mnth_derate`                                       |
    | | *Defined over*: :code:`TX_AVL_EXOG_MNTH_OPR_TMPS`                     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The pre-specified availability derate (e.g. for maintenance/planned     |
    | outages). Defaults to 1 if not specified. Availaibility can also be     |
    | more than 1.                                                            |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.TX_AVL_EXOG_MNTH = Set(within=m.TX_LINES)

    # Required Params
    ###########################################################################

    m.tx_avl_exog_mnth_derate = Param(
        m.TX_AVL_EXOG_MNTH, m.MONTHS, within=NonNegativeReals, default=1
    )


# Availability Type Methods
###############################################################################


def availability_derate_rule(mod, g, tmp):
    """ """
    return mod.tx_avl_exog_mnth_derate[g, mod.month[tmp]]


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
    # Figure out which lines have this availability type
    # TODO: move determine_project_subset and rename, as we're using for tx too
    tx_subset = determine_project_subset(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        column="tx_availability_type",
        type="exogenous_monthly",
        prj_or_tx="transmission_line",
    )

    data_portal.data()["TX_AVL_EXOG_MNTH"] = {None: tx_subset}

    # Availability derates
    # Get any derates from the tx_availability.tab file if it exists;
    # if it does not exist, all transmission lines will get 1 as a derate; if
    # it does exist but tx lines are not specified in it, they will also get 1
    # assigned as their derate
    # The test examples do not currently have a
    # transmission_availability_exogenous.tab, but use the default instead
    availability_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_availability_exogenous_monthly.tab",
    )

    if os.path.exists(availability_file):
        data_portal.load(filename=availability_file, param=m.tx_avl_exog_mnth_derate)


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
    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :return:
    """

    sql = f"""
        SELECT transmission_line, month, availability_derate
        -- Select only lines, periods, timepoints from the relevant 
        -- portfolio, relevant opchar scenario id, operational type, 
        -- and temporal scenario id
        FROM 
            (SELECT transmission_line
            FROM inputs_transmission_portfolios
            WHERE transmission_portfolio_scenario_id = {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}
            ) as tx_portfolio
        -- Of the lines in the portfolio, select only those that are in 
        -- this transmission_availability_scenario_id and have 'exogenous' as 
        -- their availability type and a non-null 
        -- exogenous_availability_scenario_id, i.e. they have 
        -- timepoint-level availability inputs in the 
        -- inputs_transmission_availability_exogenous table
        INNER JOIN (
            SELECT transmission_line, exogenous_availability_scenario_id
            FROM inputs_transmission_availability
            WHERE transmission_availability_scenario_id = {subscenarios.TRANSMISSION_AVAILABILITY_SCENARIO_ID}
            AND availability_type = 'exogenous_monthly'
            AND exogenous_availability_scenario_id IS NOT NULL
            ) AS avail_char
        USING (transmission_line)
        -- Now that we have the relevant lines and timepoints, get the 
        -- respective availability_derate (and no others) from 
        -- inputs_transmission_availability_exogenous
        left outer JOIN
            inputs_transmission_availability_exogenous
        USING (exogenous_availability_scenario_id, transmission_line)
        WHERE stage_id = {stage}
        AND month != 0  -- exclude month=0 (timepoint availability)
        AND month in (
            SELECT DISTINCT month
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
            )
        ;
    """

    c = conn.cursor()
    availabilities = c.execute(sql)

    return availabilities


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
    :param scenario_directory:
    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
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

    availabilities = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    ).fetchall()

    if availabilities:
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                "inputs",
                "transmission_availability_exogenous_monthly.tab",
            ),
            "w",
            newline="",
        ) as availability_tab_file:
            writer = csv.writer(
                availability_tab_file, delimiter="\t", lineterminator="\n"
            )

            writer.writerow(["transmission_line", "month", "availability_derate"])

            for row in availabilities:
                row = ["." if i is None else i for i in row]
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
    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :return:
    """
    availabilities = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    df = cursor_to_df(availabilities)
    idx_cols = ["transmission_line", "timepoint"]
    value_cols = ["availability_derate"]

    # Check data types availability
    expected_dtypes = get_expected_dtypes(
        conn,
        [
            "inputs_transmission_availability",
            "inputs_transmission_availability_exogenous",
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
        db_table="inputs_transmission_availability_exogenous",
        severity="High",
        errors=dtype_errors,
    )

    # Check for missing inputs
    msg = (
        "If not specified, availability is assumed to be 100%. If you "
        "don't want to specify any availability derates, simply leave the "
        "exogenous_availability_scenario_id empty and this message will "
        "disappear."
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
        db_table="inputs_transmission_availability_exogenous",
        severity="Low",
        errors=validate_missing_inputs(df, value_cols, idx_cols, msg),
    )

    # Check for correct sign
    if "availability" not in error_columns:
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table="inputs_transmission_availability_exogenous",
            severity="Low",
            errors=validate_values(df, value_cols, min=0),
        )
