# Copyright 2016-2023 Blue Marble Analytics.
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

import os.path
import pandas as pd

from gridpath.auxiliary.db_interface import import_csv

ENERGY_TARGET_ZONE_PRD_DF = "energy_target_zone_period_df"
ENERGY_TARGET_ZONE_HRZ_DF = "energy_target_zone_horizon_df"


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
    # First create the results dataframes
    # Other modules will update these dataframe with actual results
    # The results dataframes are by index

    # Zone-period DF
    target_types = {
        "period": {
            "set": "ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET",
            "df": ENERGY_TARGET_ZONE_PRD_DF,
            "exists": hasattr(m, "ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET"),
            "columns": [
                "energy_target_zone",
                "period",
                "discount_factor",
                "number_years_represented",
            ],
            "data": (
                [
                    [
                        z,
                        p,
                        m.discount_factor[p],
                        m.number_years_represented[p],
                    ]
                    for (z, p) in getattr(
                        m, "ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET"
                    )
                ]
                if hasattr(m, "ENERGY_TARGET_ZONE_PERIODS_WITH_ENERGY_TARGET")
                else []
            ),
            "index": ["energy_target_zone", "period"],
        },
        "horizon": {
            "set": "ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET",
            "df": ENERGY_TARGET_ZONE_HRZ_DF,
            "exists": hasattr(m, "ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET"),
            "columns": [
                "energy_target_zone",
                "balancing_type_horizon",
                "horizon",
            ],
            "data": (
                [
                    [
                        z,
                        bt,
                        h,
                    ]
                    for (z, bt, h) in getattr(
                        m, "ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET"
                    )
                ]
                if hasattr(m, "ENERGY_TARGET_ZONE_BLN_TYPE_HRZS_WITH_ENERGY_TARGET")
                else []
            ),
            "index": ["energy_target_zone", "balancing_type_horizon", "horizon"],
        },
    }
    for target_type in target_types.keys():
        if target_types[target_type]["exists"]:
            df = pd.DataFrame(
                columns=target_types[target_type]["columns"],
                data=target_types[target_type]["data"],
            ).set_index(target_types[target_type]["index"])

            df.sort_index(inplace=True)

            # Add the dataframe to the dynamic components to pass to other modules
            setattr(d, target_types[target_type]["df"], df)


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
    :param c:
    :param db:
    :param results_directory:
    :param quiet:
    :return:
    """
    which_results_list = ["system_period_energy_target", "system_horizon_energy_target"]

    for which_results in which_results_list:
        if os.path.exists(os.path.join(results_directory, f"{which_results}.csv")):
            import_csv(
                conn=db,
                cursor=c,
                scenario_id=scenario_id,
                weather_iteration=weather_iteration,
                hydro_iteration=hydro_iteration,
                availability_iteration=availability_iteration,
                subproblem=subproblem,
                stage=stage,
                quiet=quiet,
                results_directory=results_directory,
                which_results=which_results,
            )
