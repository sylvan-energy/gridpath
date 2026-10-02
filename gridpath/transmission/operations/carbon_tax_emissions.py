# Copyright 2026 Sylvan Energy Analytics LLC
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
Emissions imported over transmission lines into carbon tax zones. See
:code:`gridpath.transmission.operations.carbon_emissions_common` for the
components (with ``CARBON_TAX`` / ``carbon_tax`` / ``Carbon_Tax`` as the
policy names) and :code:`gridpath.system.policy.import_emissions` for the
accounting.
"""

from gridpath.system.policy.import_emissions import CARBON_TAX
from gridpath.transmission.operations import carbon_emissions_common as common


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
    common.generic_add_model_components(m, d, CARBON_TAX)


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
    common.generic_load_model_data(
        m,
        d,
        data_portal,
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        CARBON_TAX,
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
    common.generic_export_results(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        m,
        d,
        CARBON_TAX,
    )


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
    return common.generic_get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        CARBON_TAX,
    )


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
    common.generic_write_model_inputs(
        scenario_directory,
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        CARBON_TAX,
    )


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
    common.generic_validate_inputs(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        CARBON_TAX,
        __name__,
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
    common.generic_import_results_into_database(
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
        CARBON_TAX,
    )
