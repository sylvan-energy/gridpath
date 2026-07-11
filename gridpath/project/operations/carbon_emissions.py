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
Carbon emissions from each carbonaceous project.
"""

import csv
import os.path
from pyomo.environ import Expression, value

from db.common_functions import spin_on_database_lock
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.project import PROJECT_TIMEPOINT_DF


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
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Project_Carbon_Emissions`                                      |
    | | *Defined over*: :code:`FUEL_PRJ_OPR_TMPS`                             |
    |                                                                         |
    | The project's carbon emissions for each timepoint in which the project  |
    | could be operational. Note that this is an emissions *RATE* (per hour)  |
    | and should be multiplied by the timepoint duration and timepoint        |
    | weight to get the total emissions amount during that timepoint.         |
    +-------------------------------------------------------------------------+

    """
    # Expressions
    ###########################################################################

    def carbon_emissions_rule(mod, prj, tmp):
        """
        Emissions from each project based on operational type
        (and whether a project burns fuel). Multiply by the timepoint duration
        and timepoint weight to get the total emissions amount. Sum over all fuels
        times their carbon intensity to get total project carbon emissions
        """

        return (
            sum(
                (
                    mod.Total_Fuel_Burn_by_Fuel_MMBtu[prj, f, tmp]
                    - mod.Project_Fuel_Contribution_by_Fuel[prj, f, tmp]
                )
                * mod.co2_intensity_tons_per_mmbtu[f]
                for f in mod.FUELS_BY_PRJ[prj]
            )
            if prj in mod.FUEL_PRJS
            else (
                0
                + (
                    mod.Bulk_Power_Provision_MW[prj, tmp]
                    * mod.nonfuel_carbon_emissions_per_mwh[prj]
                )
                if prj in mod.NONFUEL_CARBON_EMISSIONS_PRJS
                else 0
            )
        )

    m.Project_Carbon_Emissions = Expression(m.PRJ_OPR_TMPS, rule=carbon_emissions_rule)


# Input-Output
###############################################################################


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
        "carbon_emissions_tons",
    ]
    data = [
        [
            prj,
            tmp,
            value(m.Project_Carbon_Emissions[prj, tmp]),
        ]
        for (prj, tmp) in m.PRJ_OPR_TMPS
    ]
    emissions_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PROJECT_TIMEPOINT_DF), emissions_df)


# Database
###############################################################################


def process_results(db, c, scenario_id, subscenarios, quiet):
    """
    Aggregate emissions by technology, period, and spinup_or_lookahead
    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("aggregate emissions by technology-period")

    # Delete old emissions by technology
    del_sql = """
        DELETE FROM results_project_carbon_emissions_by_technology_period 
        WHERE scenario_id = ?
        """
    spin_on_database_lock(
        conn=db, cursor=c, sql=del_sql, data=(scenario_id,), many=False
    )

    # Aggregate emissions by technology, period, and spinup_or_lookahead
    agg_sql = """
        INSERT INTO results_project_carbon_emissions_by_technology_period
        (scenario_id, subproblem_id, stage_id, period, load_zone, technology, 
        spinup_or_lookahead, carbon_emissions_tons)
        SELECT
        scenario_id, subproblem_id, stage_id, period, load_zone, technology, 
        spinup_or_lookahead, SUM(carbon_emissions_tons * timepoint_weight
        * number_of_hours_in_timepoint ) AS carbon_emissions_tons 
        FROM results_project_timepoint
        WHERE scenario_id = ?
        GROUP BY subproblem_id, stage_id, period, load_zone, technology, 
        spinup_or_lookahead
        ORDER BY subproblem_id, stage_id, period, load_zone, technology, 
        spinup_or_lookahead;"""
    spin_on_database_lock(
        conn=db, cursor=c, sql=agg_sql, data=(scenario_id,), many=False
    )
