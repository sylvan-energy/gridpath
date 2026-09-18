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

import pandas as pd

from gridpath.auxiliary.db_interface import import_csv

LOAD_ZONE_TMP_DF = "load_zone_timepoint_df"


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

    # Zone-tmp DF
    lz_tmp_df = pd.DataFrame(
        columns=[
            "load_zone",
            "period",
            "timepoint",
            "discount_factor",
            "probability",
            "probability_weighted_discount_factor",
            "number_years_represented",
            "timepoint_weight",
            "number_of_hours_in_timepoint",
        ],
        data=[
            [
                z,
                m.period[tmp],
                tmp,
                m.discount_factor[m.period[tmp]],
                m.probability[m.period[tmp]],
                m.probability_weighted_discount_factor[m.period[tmp]],
                m.number_years_represented[m.period[tmp]],
                m.tmp_weight[tmp],
                m.hrs_in_tmp[tmp],
            ]
            for z in getattr(m, "LOAD_ZONES")
            for tmp in getattr(m, "TMPS")
        ],
    ).set_index(["load_zone", "timepoint"])

    lz_tmp_df.sort_index(inplace=True)

    # Add the dataframe to the dynamic components to pass to other modules
    setattr(d, LOAD_ZONE_TMP_DF, lz_tmp_df)


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
        which_results="system_load_zone_timepoint",
    )

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
        which_results="system_load_zone_timepoint_loss_of_load_summary",
    )

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
        which_results="system_load_zone_period_load_summary",
    )
