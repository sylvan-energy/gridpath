# Copyright 2016-2024 Blue Marble Analytics LLC.
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

""" """

import os.path
import pandas as pd
from pyomo.environ import value

from gridpath.auxiliary.db_interface import import_csv


def export_summary_results(
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
    Export the project-period summary: delivered bulk energy, the equivalent
    capacity factor and the capacity components of every project in every
    operational period.

    Each project-period sums over the project's own operational timepoints in
    the period (:code:`TMPS_IN_PRD`), so the export is linear in the number of
    project-timepoints. :code:`PRJ_OPR_TMPS` is built from
    :code:`PRJ_OPR_PRDS` and :code:`TMPS_IN_PRD`, so every such (project,
    timepoint) pair is a valid index.
    """
    # Represented hours per period, computed once per period
    hrs_in_prd = {
        prd: sum(m.hrs_in_tmp[tmp] * m.tmp_weight[tmp] for tmp in m.TMPS_IN_PRD[prd])
        for prd in m.PERIODS
    }

    rows = []
    for prj, prd in m.PRJ_OPR_PRDS:
        delivered_mwh = sum(
            value(m.Bulk_Power_Provision_MW[prj, tmp])
            * m.hrs_in_tmp[tmp]
            * m.tmp_weight[tmp]
            for tmp in m.TMPS_IN_PRD[prd]
        )
        capacity_mw = value(m.Capacity_MW[prj, prd])
        cap_factor_equivalent = (
            delivered_mwh / (capacity_mw * hrs_in_prd[prd]) if capacity_mw > 0 else None
        )
        rows.append(
            [
                prj,
                prd,
                m.capacity_type[prj],
                m.operational_type[prj],
                m.technology[prj],
                m.load_zone[prj],
                delivered_mwh,
                cap_factor_equivalent,
                capacity_mw,
                value(m.Energy_MWh[prj, prd]),
                value(m.Hyb_Gen_Capacity_MW[prj, prd]),
                value(m.Hyb_Stor_Capacity_MW[prj, prd]),
                value(m.Energy_Storage_Capacity_MWh[prj, prd]),
                value(m.Fuel_Production_Capacity_FuelUnitPerHour[prj, prd]),
                value(m.Fuel_Release_Capacity_FuelUnitPerHour[prj, prd]),
                value(m.Fuel_Storage_Capacity_FuelUnit[prj, prd]),
            ]
        )

    project_summary_df = pd.DataFrame(
        columns=[
            "project",
            "period",
            "capacity_type",
            "operational_type",
            "technology",
            "load_zone",
            "total_delivered_bulk_power_mwh",
            "cap_factor_equivalent",
            "capacity_mw",
            "energy_mwh",
            "hyb_gen_capacity_mw",
            "hyb_stor_capacity_mw",
            "stor_energy_capacity_mwh",
            "fuel_prod_capacity_fuelunitperhour",
            "fuel_rel_capacity_fuelunitperhour",
            "fuel_stor_capacity_fuelunit",
        ],
        data=rows,
    ).set_index(["project", "period"])

    project_summary_df.sort_index(inplace=True)

    project_summary_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "project_period_summary.csv",
        ),
        sep=",",
        index=True,
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
        which_results="project_period_summary",
    )
