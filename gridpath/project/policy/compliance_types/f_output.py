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

import csv
import os.path
from pyomo.environ import Param, Reals, Set, Expression

from gridpath.auxiliary.auxiliary import get_required_subtype_modules
from gridpath.project.operations.common_functions import load_operational_type_modules


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
    """ """
    m.FOUTPUT_PROJECT_POLICY_ZONES = Set(dimen=3, within=m.PROJECT_POLICY_ZONES)
    m.f_slope = Param(m.FOUTPUT_PROJECT_POLICY_ZONES, within=Reals, default=0)
    m.f_intercept = Param(m.FOUTPUT_PROJECT_POLICY_ZONES, within=Reals, default=0)

    def zero_intercept_with_zero_capacity_rule(mod, prj, policy, zone, prd):
        if prd not in mod.OPR_PRDS_BY_PRJ[prj]:
            return 0
        else:
            return mod.f_intercept[prj, policy, zone] * mod.Capacity_MW[prj, prd]

    m.F_Intercept_Expression = Expression(
        m.FOUTPUT_PROJECT_POLICY_ZONES,
        m.PERIODS,
        initialize=zero_intercept_with_zero_capacity_rule,
    )

    # Get any non-standard policy contributions (not Bulk_Power_Provision_MW)
    required_operational_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="operational_type",
    )

    imported_operational_modules = load_operational_type_modules(
        required_operational_modules
    )

    def prj_policy_zone_opr_tmps_init(mod):
        tmps_by_prj = {}
        for prj, tmp in mod.PRJ_OPR_TMPS:
            tmps_by_prj.setdefault(prj, []).append(tmp)

        return [
            (prj, policy, zone, tmp)
            for (prj, policy, zone) in mod.FOUTPUT_PROJECT_POLICY_ZONES
            for tmp in tmps_by_prj.get(prj, [])
        ]

    m.FOUTPUT_PRJ_POLICY_ZONE_OPR_TMPS = Set(
        dimen=4, initialize=prj_policy_zone_opr_tmps_init
    )

    def policy_power_provision_rule(mod, prj, policy_zone, policy, tmp):
        """
        If a policy power provision rule is specified in the operational
        type, use that; otherwise, use the Bulk_Power_Provision_MW for the
        project.
        """
        gen_op_type = mod.operational_type[prj]
        if hasattr(
            imported_operational_modules[gen_op_type], "policy_power_provision_rule"
        ):
            return imported_operational_modules[
                gen_op_type
            ].policy_power_provision_rule(mod, prj, policy_zone, policy, tmp)
        else:
            return mod.Bulk_Power_Provision_MW[prj, tmp]

    m.F_Output_Policy_Power_Provision_MW = Expression(
        m.FOUTPUT_PRJ_POLICY_ZONE_OPR_TMPS, rule=policy_power_provision_rule
    )


# Compliance type methods
def contribution_in_timepoint(mod, prj, policy, zone, tmp):
    """ """
    return (
        mod.f_slope[prj, policy, zone]
        * mod.F_Output_Policy_Power_Provision_MW[prj, policy, zone, tmp]
        + mod.F_Intercept_Expression[prj, policy, zone, mod.period[tmp]]
    )


# IO
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

    project_subset = list()
    f_slope_dict = {}
    f_intercept_dict = {}

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "project_policy_zones.tab",
        ),
        "r",
    ) as f:
        reader = csv.reader(f, delimiter="\t", lineterminator="\n")
        next(reader)
        for row in reader:
            if row[3] == "f_output":
                project_subset.append((row[0], row[1], row[2]))
                f_slope_dict[(row[0], row[1], row[2])] = float(row[4])
                f_intercept_dict[(row[0], row[1], row[2])] = float(row[5])

    data_portal.data()["FOUTPUT_PROJECT_POLICY_ZONES"] = {None: project_subset}
    data_portal.data()["f_slope"] = f_slope_dict
    data_portal.data()["f_intercept"] = f_intercept_dict
