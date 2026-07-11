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
Get carbon emissions on each 'carbonaceous' transmission line.

Carbon emissions are based on power sent on the transmission line.
"""

import csv
import os.path
from pyomo.environ import (
    Param,
    Set,
    Var,
    Constraint,
    Expression,
    NonNegativeReals,
    value,
)

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.auxiliary import subset_init_by_set_membership
from gridpath.auxiliary.db_interface import (
    directories_to_db_values,
)
from gridpath.auxiliary.dynamic_components import carbon_cap_balance_emission_components
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.transmission import TX_TIMEPOINT_DF
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
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
    | | :code:`CRB_TX_LINES`                                                  |
    |                                                                         |
    | The set of carbonaceous transmission lines, i.e. transmission lines     |
    | whose imports or exports should be accounted for in the carbon cap      |
    | calculations.                                                           |
    +-------------------------------------------------------------------------+
    | | :code:`CRB_TX_OPR_TMPS`                                               |
    |                                                                         |
    | Two-dimensional set of carbonaceous transmission lines and their        |
    | operational timepoints.                                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`tx_carbon_cap_zone`                                            |
    | | *Defined over*: :code:`CRB_TX_LINES`                                  |
    | | *Within*: :code:`CARBON_CAP_ZONES`                                    |
    |                                                                         |
    | The transmission line's carbon cap zone. The imports or exports for     |
    | that transmission line will count towards that zone's carbon cap.       |
    +-------------------------------------------------------------------------+
    | | :code:`carbon_cap_zone_import_direction`                              |
    | | *Defined over*: :code:`CRB_TX_LINES`                                  |
    | | *Within*: :code:`["positive", "negative"]`                            |
    |                                                                         |
    | The transmission line's import direction: "positive" ("negative")       |
    | indicates positive (negative) line flows are flows into the carbon cap  |
    | zone while negative (positive) line flows are flows out of the carbon   |
    | zone.                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`tx_co2_intensity_tons_per_mwh`                                 |
    | | *Defined over*: :code:`CRB_TX_LINES`                                  |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The transmission line's CO2-intensity in metric tonnes per MWh. This    |
    | param indicates how much emissions are added towards the carbon cap for |
    | every MWh transmitted into the carbon cap zone.                         |
    +-------------------------------------------------------------------------+
    | | :code:`tx_co2_intensity_tons_per_mwh_hourly`                          |
    | | *Defined over*: :code:`CRB_TX_OPR_TMPS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | The transmission line's CO2-intensity in metric tonnes per MWh for each |
    | timepoint. This param indicates how much emissions are added towards    |
    | the carbon cap for every MWh transmitted into the carbon cap zone for   |
    | each timepoint. Timepoint CO2-intensity and average CO2-intensity are   |
    | added together to get the total CO2-intensity for each timepoint.       |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Sets                                                            |
    +=========================================================================+
    | | :code:`CRB_TX_LINES_BY_CARBON_CAP_ZONE`                               |
    | | *Defined over*: :code:`CARBON_CAP_ZONES`                              |
    | | *Within*: :code:`CRB_TX_LINES`                                        |
    |                                                                         |
    | Indexed set that describes the carbonaceous transmission lines          |
    | associated with each carbon cap zone.                                   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`Import_Carbon_Emissions_Tons`                                  |
    | | *Defined over*: :code:`CRB_TX_OPR_TMPS`                               |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | Describes the amount of imported carbon emissions for each              |
    | carbonaceous transmission in each operational timepoint.                |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`Carbon_Emissions_Imports_Constraint`                           |
    | | *Enforced over*: :code:`CRB_TX_OPR_TMPS`                              |
    |                                                                         |
    | Constrains the amount of imported carbon emissions for each             |
    | carbonaceous transmission in each operational timepoint, based on the   |
    | :code:`tx_co2_intensity_tons_per_mwh` param and the transmitted power.  |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.CRB_TX_LINES = Set(within=m.TX_LINES)

    m.CRB_TX_OPR_TMPS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod, superset="TX_OPR_TMPS", index=0, membership_set=mod.CRB_TX_LINES
        ),
    )

    # Required Input Params
    ###########################################################################

    m.tx_carbon_cap_zone = Param(m.CRB_TX_LINES, within=m.CARBON_CAP_ZONES)

    m.carbon_cap_zone_import_direction = Param(
        m.CRB_TX_LINES, within=["positive", "negative"]
    )

    m.tx_co2_intensity_tons_per_mwh = Param(
        m.CRB_TX_LINES, within=NonNegativeReals, default=0
    )

    m.tx_co2_intensity_tons_per_mwh_hourly = Param(
        m.CRB_TX_OPR_TMPS, within=NonNegativeReals, default=0
    )

    # Derived Sets
    ###########################################################################

    m.CRB_TX_LINES_BY_CARBON_CAP_ZONE = Set(
        m.CARBON_CAP_ZONES,
        within=m.CRB_TX_LINES,
        initialize=lambda mod, co2_z: [
            tx for tx in mod.CRB_TX_LINES if mod.tx_carbon_cap_zone[tx] == co2_z
        ],
    )

    # Variables
    ###########################################################################

    m.Import_Carbon_Emissions_Tons = Var(m.CRB_TX_OPR_TMPS, within=NonNegativeReals)

    # Constraints
    ###########################################################################

    m.Carbon_Emissions_Imports_Constraint = Constraint(
        m.CRB_TX_OPR_TMPS, rule=carbon_emissions_imports_rule
    )


# Expression Rules
###############################################################################


def calculate_carbon_emissions_imports(mod, tx_line, timepoint):
    """
    **Expression Name**: N/A
    **Defined Over**: CRB_TX_OPR_TMPS

    In case of degeneracy where the *Import_Carbon_Emissions_Tons* variable
    can take a value larger than the actual import emissions (when the
    carbon cap is non-binding), we can post-process to figure out what the
    actual imported emissions are (e.g. instead of applying a tuning cost).
    """
    if (
        mod.carbon_cap_zone_import_direction[tx_line] == "positive"
        and value(mod.Transmit_Power_MW[tx_line, timepoint]) > 0
    ):
        return value(mod.Transmit_Power_MW[tx_line, timepoint]) * (
            mod.tx_co2_intensity_tons_per_mwh[tx_line]
            + mod.tx_co2_intensity_tons_per_mwh_hourly[tx_line, timepoint]
        )
    elif (
        mod.carbon_cap_zone_import_direction[tx_line] == "negative"
        and -value(mod.Transmit_Power_MW[tx_line, timepoint]) > 0
    ):
        return -value(mod.Transmit_Power_MW[tx_line, timepoint]) * (
            mod.tx_co2_intensity_tons_per_mwh[tx_line]
            + mod.tx_co2_intensity_tons_per_mwh_hourly[tx_line, timepoint]
        )
    else:
        return 0


# Constraint Formulation Rules
###############################################################################


def carbon_emissions_imports_rule(mod, tx, tmp):
    """
    **Constraint Name**: Carbon_Emissions_Imports_Constraint
    **Defined Over**: CRB_TX_OPR_TMPS

    Constrain the *Import_Carbon_Emissions_Tons* variable to be at least as
    large as the calculated imported carbon emissions for each transmission
    line, based on its CO2-intensity.
    """
    if mod.carbon_cap_zone_import_direction[tx] == "positive":
        return mod.Import_Carbon_Emissions_Tons[tx, tmp] >= mod.Transmit_Power_MW[
            tx, tmp
        ] * (
            mod.tx_co2_intensity_tons_per_mwh[tx]
            + mod.tx_co2_intensity_tons_per_mwh_hourly[tx, tmp]
        )
    elif mod.carbon_cap_zone_import_direction[tx] == "negative":
        return mod.Import_Carbon_Emissions_Tons[tx, tmp] >= -mod.Transmit_Power_MW[
            tx, tmp
        ] * (
            mod.tx_co2_intensity_tons_per_mwh[tx]
            + mod.tx_co2_intensity_tons_per_mwh_hourly[tx, tmp]
        )
    else:
        raise ValueError(
            "The parameter carbon_cap_zone_import_direction "
            "have a value of either 'positive' or "
            "'negative,' not {}.".format(mod.carbon_cap_zone_import_direction[tx])
        )


# Inputs-Outputs
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

    # load transmission_average_emissions.tab file
    average_emissions_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_average_emissions.tab",
    )

    data_portal.load(
        filename=average_emissions_file,
        select=(
            "transmission_line",
            "carbon_cap_zone",
            "import_direction",
            "tx_co2_intensity_tons_per_mwh",
        ),
        param=(
            m.tx_carbon_cap_zone,
            m.carbon_cap_zone_import_direction,
            m.tx_co2_intensity_tons_per_mwh,
        ),
    )

    data_portal.data()["CRB_TX_LINES"] = {
        None: list(data_portal.data()["tx_carbon_cap_zone"].keys())
    }

    # Check if timepoint emissions file exists before loading
    timepoint_emissions_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "transmission_timepoint_emissions.tab",
    )

    # If the timepoint emissions file exists, load the data and initialize the CRB_TX_OPR_TMPS set
    if os.path.exists(timepoint_emissions_file):
        data_portal.load(
            filename=timepoint_emissions_file,
            param=(m.tx_co2_intensity_tons_per_mwh_hourly),
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

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    results_columns = [
        "carbon_emission_imports_tons",
        "carbon_emission_imports_tons_degen",
    ]
    data = [
        [
            tx,
            tmp,
            value(m.Import_Carbon_Emissions_Tons[tx, tmp]),
            calculate_carbon_emissions_imports(m, tx, tmp),
        ]
        for (tx, tmp) in m.CRB_TX_OPR_TMPS
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

    sql_tzones = f"""
        SELECT transmission_line, carbon_cap_zone, import_direction, tx_co2_intensity_tons_per_mwh
        FROM inputs_transmission_carbon_cap_zones
        WHERE transmission_carbon_cap_zone_scenario_id = {subscenarios.TRANSMISSION_CARBON_CAP_ZONE_SCENARIO_ID}
        AND transmission_line IN (
            SELECT transmission_line
            FROM inputs_transmission_portfolios
            WHERE transmission_portfolio_scenario_id = {subscenarios.TRANSMISSION_PORTFOLIO_SCENARIO_ID}
        )
    """

    transmission_zones = c.execute(sql_tzones)

    c2 = conn.cursor()

    sql_tmp_emissions = f"""
        SELECT transmission_line, timepoint, tx_co2_intensity_tons_per_mwh_hourly
        FROM inputs_transmission_carbon_cap_timepoint_emissions
        WHERE (transmission_line, tmp_import_emissions_scenario_id) IN (
            SELECT transmission_line, tmp_import_emissions_scenario_id
            FROM inputs_transmission_carbon_cap_zones
            WHERE transmission_carbon_cap_zone_scenario_id = {subscenarios.TRANSMISSION_CARBON_CAP_ZONE_SCENARIO_ID}
        )
        AND (timepoint) IN (
            SELECT timepoint
            FROM inputs_temporal
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
        )  
    """

    tmp_import_emissions = c2.execute(sql_tmp_emissions)

    return transmission_zones, tmp_import_emissions


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
    Get inputs from database and write out the model inputs
    transmission_lines.tab file and the transmission_timepoint_emissions.tab file
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

    transmission_zones, tmp_import_emissions = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # write transmission_average_emissions.tab file
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="transmission_average_emissions.tab",
        data=transmission_zones,
        replace_nulls=True,
    )

    # write transmission_timepoint_emissions.tab file if there is data for the scenario ID
    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname="transmission_timepoint_emissions.tab",
        data=tmp_import_emissions,
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
    pass
    # Validation to be added
    # transmission_zones = get_inputs_from_database(
    #     scenario_id, subscenarios, subproblem, stage, conn)
