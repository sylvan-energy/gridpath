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

from pyomo.environ import Expression, NonNegativeReals, Param

from gridpath.auxiliary.auxiliary import (
    get_required_subtype_modules,
    load_subtype_modules,
)
from gridpath.transmission import DEFAULT_TX_AVAILABILITY_TYPE


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

    :param m:
    :param d:
    :return:
    """
    # Import needed availability type modules
    required_availability_modules = list(
        set(
            list(
                get_required_subtype_modules(
                    scenario_directory=scenario_directory,
                    weather_iteration=weather_iteration,
                    hydro_iteration=hydro_iteration,
                    availability_iteration=availability_iteration,
                    subproblem=subproblem,
                    stage=stage,
                    filename="transmission_lines",
                    which_type="tx_availability_type",
                )
            )
            + [DEFAULT_TX_AVAILABILITY_TYPE]
        )
    )

    # Remove "." (i.e. transmission_lines with no availability type specified,
    # which will default to the default availability type, "exogenous")
    required_availability_modules = [
        r for r in required_availability_modules if r != "."
    ]

    imported_availability_modules = load_availability_type_modules(
        required_availability_modules
    )

    # First, add any components specific to the availability type modules
    for op_m in required_availability_modules:
        imp_op_m = imported_availability_modules[op_m]
        if hasattr(imp_op_m, "add_model_components"):
            imp_op_m.add_model_components(
                m,
                d,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            )

    # Resolve each availability type's derate rule once, not per index
    derate_rule_by_type = {
        avl_type: imported_availability_modules[avl_type].availability_derate_rule
        for avl_type in required_availability_modules
    }

    # If every required availability type produces a constant derate (no
    # variables in the derate), make the derate component a Param rather
    # than an Expression: an immutable Param value is inlined as a plain
    # number in the consuming expressions and constraints, which makes
    # them smaller and faster to build than storing a reference into an
    # Expression component
    all_derates_constant = all(
        getattr(imported_availability_modules[avl_type], "DERATE_IS_CONSTANT", False)
        for avl_type in required_availability_modules
    )

    def availability_derate_rule(mod, tx, tmp):
        """

        :param mod:
        :param tx:
        :param tmp:
        :return:
        """
        return derate_rule_by_type[mod.tx_availability_type[tx]](mod, tx, tmp)

    if all_derates_constant:
        m.Tx_Availability_Derate = Param(
            m.TX_OPR_TMPS,
            within=NonNegativeReals,
            initialize=availability_derate_rule,
        )
    else:
        m.Tx_Availability_Derate = Expression(
            m.TX_OPR_TMPS, rule=availability_derate_rule
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
    required_availability_modules = list(
        set(
            list(
                get_required_subtype_modules(
                    scenario_directory=scenario_directory,
                    weather_iteration=weather_iteration,
                    hydro_iteration=hydro_iteration,
                    availability_iteration=availability_iteration,
                    subproblem=subproblem,
                    stage=stage,
                    filename="transmission_lines",
                    which_type="tx_availability_type",
                )
            )
            + [DEFAULT_TX_AVAILABILITY_TYPE]
        )
    )

    # Remove "." (i.e. projects with no availability type specified,
    # which will default to the default availability type, "exogenous")
    required_availability_modules = [
        r for r in required_availability_modules if r != "."
    ]

    imported_availability_modules = load_availability_type_modules(
        required_availability_modules
    )
    for avl_m in required_availability_modules:
        if hasattr(imported_availability_modules[avl_m], "load_model_data"):
            imported_availability_modules[avl_m].load_model_data(
                m,
                d,
                data_portal,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
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

    Export availability results.
    """

    # Module-specific capacity results
    required_availability_modules = list(
        set(
            list(
                get_required_subtype_modules(
                    scenario_directory=scenario_directory,
                    weather_iteration=weather_iteration,
                    hydro_iteration=hydro_iteration,
                    availability_iteration=availability_iteration,
                    subproblem=subproblem,
                    stage=stage,
                    which_type="tx_availability_type",
                    filename="transmission_lines",
                )
            )
            + [DEFAULT_TX_AVAILABILITY_TYPE]
        )
    )

    # Remove "." (i.e. projects with no availability type specified,
    # which will default to the default availability type, "exogenous")
    required_availability_modules = [
        r for r in required_availability_modules if r != "."
    ]

    imported_availability_modules = load_availability_type_modules(
        required_availability_modules
    )
    for op_m in required_availability_modules:
        if hasattr(imported_availability_modules[op_m], "export_results"):
            imported_availability_modules[op_m].export_results(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                m,
                d,
            )


# Database
###############################################################################


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
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:

    Get inputs from database and write out the model input .tab files
    """
    c = conn.cursor()
    # Load in the required capacity type modules

    required_availability_type_modules = get_required_availability_type_modules(
        scenario_id, c
    )

    imported_availability_type_modules = load_availability_type_modules(
        required_availability_type_modules
    )

    # Get module-specific inputs
    for op_m in required_availability_type_modules:
        if hasattr(imported_availability_type_modules[op_m], "write_model_inputs"):
            imported_availability_type_modules[op_m].write_model_inputs(
                scenario_directory,
                scenario_id,
                subscenarios,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                conn,
            )


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
    """

    :param scenario_id:
    :param subproblem:
    :param stage:
    :param c:
    :param db:
    :param results_directory:
    :param quiet:
    :return:
    """

    # Load in the required availability type modules
    required_availability_type_modules = get_required_availability_type_modules(
        scenario_id, c
    )
    imported_availability_modules = load_availability_type_modules(
        required_availability_type_modules
    )

    # Import module-specific results
    for op_m in required_availability_type_modules:
        if hasattr(imported_availability_modules[op_m], "import_results_into_database"):
            imported_availability_modules[op_m].import_results_into_database(
                scenario_id, subproblem, stage, c, db, results_directory, quiet
            )


# Auxiliary functions
###############################################################################
def get_required_availability_type_modules(scenario_id, c):
    """
    :param scenario_id: user-specified scenario ID
    :param c: database cursor
    :return: List of the required capacity type submodules

    Get the required availability type submodules based on the database inputs
    for the specified scenario_id. Required modules are the unique set of
    tx line availability types in the scenario's portfolio. Get the list
    based on the transmission_availability_scenario_id of the scenario_id.

    This list will be used to know for which availability type submodules we
    should validate inputs, get inputs from database , or save results to
    database.

    Note: once we have determined the dynamic components, this information
    will also be stored in the DynamicComponents class object.
    """

    transmission_portfolio_scenario_id = c.execute(
        """SELECT transmission_portfolio_scenario_id 
        FROM scenarios 
        WHERE scenario_id = {}""".format(scenario_id)
    ).fetchone()[0]

    transmission_availability_scenario_id = c.execute(
        """SELECT transmission_availability_scenario_id 
        FROM scenarios 
        WHERE scenario_id = {}""".format(scenario_id)
    ).fetchone()[0]

    if transmission_availability_scenario_id is not None:
        required_availability_type_modules = list(
            set(
                [p[0] for p in c.execute(f"""
                        SELECT DISTINCT availability_type 
                        FROM 
                        (SELECT transmission_line FROM inputs_transmission_portfolios
                        WHERE transmission_portfolio_scenario_id = {transmission_portfolio_scenario_id}) as prj_tbl
                        LEFT OUTER JOIN
                        (SELECT transmission_line, availability_type
                        FROM inputs_transmission_availability
                        WHERE transmission_availability_scenario_id = {transmission_availability_scenario_id}) as av_type_tbl
                        USING (transmission_line)""").fetchall()]
                + [DEFAULT_TX_AVAILABILITY_TYPE]
            )
        )
    else:
        # If no transmission_line availability scenario is specified, then we only use
        # the default availability type module
        required_availability_type_modules = [DEFAULT_TX_AVAILABILITY_TYPE]

    # Remove None (i.e. transmission_lines with no availability type specified,
    # which will default to the default availability type, "exogenous")
    required_availability_type_modules = [
        r for r in required_availability_type_modules if r is not None
    ]

    return required_availability_type_modules


def load_availability_type_modules(required_availability_types):
    """

    :param required_availability_types:
    :return:
    """
    return load_subtype_modules(
        required_subtype_modules=required_availability_types,
        package="gridpath.transmission.availability.availability_types",
        required_attributes=["availability_derate_rule"],
    )
