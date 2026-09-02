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

""" """

import os.path
import pandas as pd

from ra_toolkit.common_methods import create_csv_generic


def create_load_scenario_csv(
    output_directory,
    load_scenario_id,
    load_scenario_name,
    load_components_scenario_id,
    load_levels_scenario_id,
    overwrite_load_scenario_csv,
):
    filename = os.path.join(
        output_directory,
        f"{load_scenario_id}_{load_scenario_name}.csv",
    )

    df = pd.DataFrame(
        {
            "load_components_scenario_id": [load_components_scenario_id],
            "load_levels_scenario_id": [load_levels_scenario_id],
        }
    )

    create_csv_generic(filename=filename, df=df, overwrite=overwrite_load_scenario_csv)


def create_load_components_scenario_csv(
    conn,
    output_directory,
    load_component_name,
    load_components_scenario_id,
    load_components_scenario_name,
    overwrite_load_components_csv,
):
    filename = os.path.join(
        output_directory,
        "load_components",
        f"{load_components_scenario_id}_{load_components_scenario_name}.csv",
    )

    query = f"""
            SELECT load_zone, 
            '{load_component_name}' AS load_component, 
            NULL AS load_level_default, 
            NULL AS load_component_distribution_loss_adjustment_factor
            FROM user_defined_load_zone_units
            ;
            """

    # Put into a dataframe and add to file
    df = pd.read_sql(query, con=conn)

    # Save CSV
    create_csv_generic(
        filename=filename, df=df, overwrite=overwrite_load_components_csv
    )
