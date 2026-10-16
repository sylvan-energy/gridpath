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
The *base* of a generic policy requirement: the output or capacity of a set
of projects that the requirement scales with (through the requirement's
``policy_requirement_f_base_coeff``), e.g. the generation an emissions
intensity standard applies to.

Which projects drive the requirement, and through which quantity, is part of
the requirement's definition and is specified here, separately from the
projects' contributions toward *meeting* the requirement (their compliance
types in ``project_policy_zones``). A project can drive the requirement
without contributing toward it and vice versa, as for the reserve
requirements, which can be a percentage of load plus a percentage of the
output or capacity of selected projects.
"""

import csv
import os.path

from pyomo.environ import Expression, Param, Reals, Set, value

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.auxiliary.dynamic_components import policy_balance_base_components
from gridpath.auxiliary.validations import (
    validate_columns,
    write_validation_to_database,
)
from gridpath.common_functions import create_results_df

# The base quantity of a project that a requirement can scale with: its
# output (energy over the horizon) or its capacity (in the horizon's period)
OUTPUT_BASE = "output"
CAPACITY_BASE = "capacity"
BASE_TYPES = [OUTPUT_BASE, CAPACITY_BASE]


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
    | | :code:`POLICY_ZONE_BASE_PRJS`                                         |
    |                                                                         |
    | Four-dimensional set of the projects whose base quantities a policy     |
    | zone's requirements scale with, and the base type (``output`` or        |
    | ``capacity``) of each: (policy, zone, project, base type).              |
    +-------------------------------------------------------------------------+
    | | :code:`OUTPUT_BASE_POLICY_ZONE_PRJ_OPR_TMPS`                          |
    |                                                                         |
    | The ``output`` base rows and the projects' operational timepoints.      |
    +-------------------------------------------------------------------------+
    | | :code:`CAPACITY_BASE_POLICY_ZONE_PRJ_OPR_PRDS`                        |
    |                                                                         |
    | The ``capacity`` base rows and the projects' operational periods.       |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Optional Input Params                                                   |
    +=========================================================================+
    | | :code:`policy_base_multiplier`                                        |
    | | *Defined over*: :code:`POLICY_ZONE_BASE_PRJS`                         |
    | | *Within*: :code:`Reals`                                               |
    | | *Default*: :code:`1`                                                  |
    |                                                                         |
    | The weight of the project's base quantity in the policy zone's base.    |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Total_Project_Policy_Zone_Base`                                |
    | | *Defined over*: :code:`POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ`          |
    |                                                                         |
    | The weighted output of the ``output`` base projects over the horizon    |
    | plus the weighted capacity of the ``capacity`` base projects in the     |
    | horizon's period. Added to the policy requirement's base components.    |
    +-------------------------------------------------------------------------+
    """

    m.POLICY_ZONE_BASE_PRJS = Set(dimen=4)

    m.policy_base_multiplier = Param(m.POLICY_ZONE_BASE_PRJS, within=Reals, default=1)

    def output_base_opr_tmps_init(mod):
        tmps_by_prj = {}
        for prj, tmp in mod.PRJ_OPR_TMPS:
            tmps_by_prj.setdefault(prj, []).append(tmp)

        return [
            (policy, zone, prj, tmp)
            for (policy, zone, prj, base_type) in mod.POLICY_ZONE_BASE_PRJS
            if base_type == OUTPUT_BASE
            for tmp in tmps_by_prj.get(prj, [])
        ]

    m.OUTPUT_BASE_POLICY_ZONE_PRJ_OPR_TMPS = Set(
        dimen=4, initialize=output_base_opr_tmps_init
    )

    m.CAPACITY_BASE_POLICY_ZONE_PRJ_OPR_PRDS = Set(
        dimen=4,
        initialize=lambda mod: [
            (policy, zone, prj, prd)
            for (policy, zone, prj, base_type) in mod.POLICY_ZONE_BASE_PRJS
            if base_type == CAPACITY_BASE
            for prd in mod.OPR_PRDS_BY_PRJ[prj]
        ],
    )

    # Group the base indices by requirement (policy, zone, balancing type,
    # horizon) in ONE pass over each set, so the aggregation rule below
    # doesn't rescan them for every requirement index
    def output_base_prj_tmps_by_req_init(mod):
        prj_tmps_by_req = {idx: [] for idx in mod.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ}
        for policy, zone, prj, tmp in mod.OUTPUT_BASE_POLICY_ZONE_PRJ_OPR_TMPS:
            for bt in mod.BLN_TYPES:
                idx = (policy, zone, bt, mod.horizon[tmp, bt])
                if idx in prj_tmps_by_req:
                    prj_tmps_by_req[idx].append((prj, tmp))

        return prj_tmps_by_req

    m.OUTPUT_BASE_PRJ_TMPS_BY_POLICY_ZONE_BLN_TYPE_HRZ = Set(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        dimen=2,
        initialize=output_base_prj_tmps_by_req_init,
    )

    def capacity_base_prjs_by_req_init(mod):
        prjs_by_req = {idx: [] for idx in mod.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ}
        reqs_by_policy_zone_prd = {}
        for policy, zone, bt, h in mod.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ:
            prd = mod.period[mod.last_hrz_tmp[bt, h]]
            reqs_by_policy_zone_prd.setdefault((policy, zone, prd), []).append(
                (policy, zone, bt, h)
            )
        for policy, zone, prj, prd in mod.CAPACITY_BASE_POLICY_ZONE_PRJ_OPR_PRDS:
            for idx in reqs_by_policy_zone_prd.get((policy, zone, prd), []):
                prjs_by_req[idx].append(prj)

        return prjs_by_req

    m.CAPACITY_BASE_PRJS_BY_POLICY_ZONE_BLN_TYPE_HRZ = Set(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ,
        initialize=capacity_base_prjs_by_req_init,
    )

    def total_base_rule(mod, policy, zone, bt, h):
        """
        The output base projects' weighted energy over the horizon plus the
        capacity base projects' weighted capacity in the horizon's period
        """
        prd = mod.period[mod.last_hrz_tmp[bt, h]]
        return sum(
            mod.policy_base_multiplier[policy, zone, prj, OUTPUT_BASE]
            * mod.Bulk_Power_Provision_MW[prj, tmp]
            * mod.hrs_in_tmp[tmp]
            * mod.tmp_weight[tmp]
            for (prj, tmp) in mod.OUTPUT_BASE_PRJ_TMPS_BY_POLICY_ZONE_BLN_TYPE_HRZ[
                policy, zone, bt, h
            ]
        ) + sum(
            mod.policy_base_multiplier[policy, zone, prj, CAPACITY_BASE]
            * mod.Capacity_MW[prj, prd]
            for prj in mod.CAPACITY_BASE_PRJS_BY_POLICY_ZONE_BLN_TYPE_HRZ[
                policy, zone, bt, h
            ]
        )

    m.Total_Project_Policy_Zone_Base = Expression(
        m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ, rule=total_base_rule
    )

    record_dynamic_components(dynamic_components=d)


def record_dynamic_components(dynamic_components):
    """
    :param dynamic_components:

    Add the projects' base quantities to the policy requirement's base.
    """
    getattr(dynamic_components, policy_balance_base_components).append(
        "Total_Project_Policy_Zone_Base"
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
    The base projects file is only written when there are any; without it,
    the base set is empty.
    """
    base_projects_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "policy_requirement_base_projects.tab",
    )
    if os.path.exists(base_projects_file):
        data_portal.load(
            filename=base_projects_file,
            index=m.POLICY_ZONE_BASE_PRJS,
            param=m.policy_base_multiplier,
        )
    else:
        data_portal.data()["POLICY_ZONE_BASE_PRJS"] = {None: []}


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
    Each base project's base quantity in each of the policy zone's requirement
    horizons (energy in MWh for the output base, capacity in MW for the
    capacity base), before and after the project's multiplier.
    """
    if not m.POLICY_ZONE_BASE_PRJS:
        return

    data = []
    for policy, zone, bt, h in m.POLICIES_ZONE_BLN_TYPE_HRZS_WITH_REQ:
        prd = m.period[m.last_hrz_tmp[bt, h]]
        output_by_prj = {}
        for prj, tmp in m.OUTPUT_BASE_PRJ_TMPS_BY_POLICY_ZONE_BLN_TYPE_HRZ[
            policy, zone, bt, h
        ]:
            output_by_prj[prj] = (
                output_by_prj.get(prj, 0)
                + value(m.Bulk_Power_Provision_MW[prj, tmp])
                * m.hrs_in_tmp[tmp]
                * m.tmp_weight[tmp]
            )
        for prj, base in output_by_prj.items():
            multiplier = m.policy_base_multiplier[policy, zone, prj, OUTPUT_BASE]
            data.append(
                [policy, zone, bt, h, prj, OUTPUT_BASE, multiplier, base]
                + [multiplier * base]
            )
        for prj in m.CAPACITY_BASE_PRJS_BY_POLICY_ZONE_BLN_TYPE_HRZ[
            policy, zone, bt, h
        ]:
            multiplier = m.policy_base_multiplier[policy, zone, prj, CAPACITY_BASE]
            base = value(m.Capacity_MW[prj, prd])
            data.append(
                [policy, zone, bt, h, prj, CAPACITY_BASE, multiplier, base]
                + [multiplier * base]
            )

    if not data:
        return

    results_df = create_results_df(
        index_columns=[
            "policy_name",
            "policy_zone",
            "balancing_type_horizon",
            "horizon",
            "project",
            "base_type",
        ],
        results_columns=["base_multiplier", "base_in_hrz", "weighted_base_in_hrz"],
        data=data,
    )
    results_df.to_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "project_policy_requirement_base.csv",
        ),
        sep=",",
        index=True,
    )


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
    The base projects of the requirement subscenario, for the projects in the
    portfolio and the policy zones in the policy zone subscenario.
    """
    c = conn.cursor()
    base_projects = c.execute(f"""SELECT policy_name, policy_zone, project, base_type,
        base_multiplier
        FROM inputs_system_policy_requirements_base_projects
        JOIN
        (SELECT project
        FROM inputs_project_portfolios
        WHERE project_portfolio_scenario_id =
        {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}) as portfolio_prjs
        USING (project)
        JOIN
        (SELECT policy_name, policy_zone
        FROM inputs_geography_policy_zones
        WHERE policy_zone_scenario_id = {subscenarios.POLICY_ZONE_SCENARIO_ID})
        as relevant_zones
        USING (policy_name, policy_zone)
        WHERE policy_requirement_scenario_id =
        {subscenarios.POLICY_REQUIREMENT_SCENARIO_ID}
        ;""")

    return base_projects


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
    The base type must be one of the supported types.
    """
    base_projects = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )
    df = cursor_to_df(base_projects)
    if df.empty:
        return

    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_system_policy_requirements_base_projects",
        severity="High",
        errors=validate_columns(df, "base_type", valids=BASE_TYPES),
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
    """
    Write the base projects to policy_requirement_base_projects.tab, only if
    there are any.
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
    base_projects = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    ).fetchall()

    if not base_projects:
        return

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "policy_requirement_base_projects.tab",
        ),
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["policy_name", "policy_zone", "project", "base_type", "base_multiplier"]
        )
        for row in base_projects:
            writer.writerow(["." if i is None else i for i in row])


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
    Import the base projects' results, if any.
    """
    if not os.path.exists(
        os.path.join(results_directory, "project_policy_requirement_base.csv")
    ):
        return

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
        which_results="project_policy_requirement_base",
    )
