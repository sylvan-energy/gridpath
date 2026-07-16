# Copyright 2016-2025 Blue Marble Analytics LLC.
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

"""
This is a project-level module that adds to the formulation components that
describe the capacity of projects that are available to the optimization for
each period. For example, the capacity can be a fixed number or an
expression with variables depending on the project's *capacity_type*. The
project capacity can then be used to constrain operations, contribute to
reliability constraints, etc.
"""

import os.path
import pandas as pd
from pyomo.environ import Set, Expression, value

from gridpath.auxiliary.auxiliary import (
    get_required_subtype_modules,
    join_sets,
)
from gridpath.auxiliary.dynamic_components import capacity_type_operational_period_sets
from gridpath.common_functions import create_results_df, update_results_df
from gridpath.project.capacity.common_functions import (
    load_project_capacity_type_modules,
)
from gridpath.project import PROJECT_PERIOD_DF
import gridpath.project.capacity.capacity_types as cap_type_init


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
    First, we iterate over all required *capacity_types* modules (this is the
    set of distinct project capacity types in the list of projects specified
    by the user) and add the components specific to the respective
    *capacity_type* module. We do this by calling the
    *add_model_components* method of the capacity_type module if
    the method exists.

    Then, the following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`PRJ_OPR_PRDS`                                                  |
    | | *Within*: :code:`PROJECTS x PERIODS`                                  |
    |                                                                         |
    | Two-dimensional set that defines all project-period combinations when   |
    | a project can be operational (i.e. either has specified capacity or     |
    | can be build). This set is created by joining sets added by the         |
    | capacity_type modules (which is done before loading this module),       |
    | as how operational periods are determined differs by capacity type.     |
    +-------------------------------------------------------------------------+
    | | :code:`OPR_PRDS_BY_PRJ`                                               |
    | | *Defined over*: :code:`PROJECTS`                                      |
    |                                                                         |
    | Indexed set that describes the possible operational periods for each    |
    | project.                                                                |
    +-------------------------------------------------------------------------+
    | | :code:`PRJ_OPR_TMPS`                                                  |
    |                                                                         |
    | Two-dimensional set that defines all project-timepoint combinations     |
    | when a project can be operational.                                      |
    +-------------------------------------------------------------------------+
    | | :code:`OPR_PRJS_IN_TMP`                                               |
    | | *Defined over*: :code:`TMPS`                                          |
    |                                                                         |
    | Indexed set that describes all projects that could be operational in    |
    | each timepoint.                                                         |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Expressions                                                             |
    +=========================================================================+
    | | :code:`Capacity_MW`                                                   |
    | | *Defined over*: :code:`PRJ_OPR_PRDS`                                  |
    |                                                                         |
    | Defines the project capacity in each period (in which the project can   |
    | exist) in the model. The exact formulation of the expression depends on |
    | the project's capacity_type. For each project, we call its              |
    | capacity_type module's capacity_rule method in order to formulate the   |
    | expression. E.g. a project of the gen_spec capacity_type will have a    |
    | have a pre-specified capacity whereas a project of the gen_new_lin      |
    | capacity_type will have a model variable (or sum of variables) as its   |
    | Capacity_MW.                                                            |
    +-------------------------------------------------------------------------+
    | | :code:`Energy_Storage_Capacity_MWh`                                   |
    | | *Defined over*: :code:`PRJ_OPR_PRDS`                                  |
    |                                                                         |
    | Defines the project's energy capacity in each period (in which the      |
    | project can exist). The exact formulation of the expression depends on  |
    | the project's capacity_type. For each project, we call its              |
    | capacity_type module's energy_stor_capacity_rule method in order to     |
    | formulate the expression.                                               |
    +-------------------------------------------------------------------------+

    """

    # Dynamic Inputs
    ###########################################################################

    required_capacity_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="capacity_type",
    )

    # Import needed capacity type modules
    imported_capacity_modules = load_project_capacity_type_modules(
        required_capacity_modules
    )

    # Add any components specific to the capacity type modules
    for op_m in required_capacity_modules:
        imp_op_m = imported_capacity_modules[op_m]
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

    # Sets
    ###########################################################################

    m.PRJ_OPR_PRDS = Set(
        dimen=2,
        within=m.PROJECTS * m.PERIODS,
        initialize=lambda mod: join_sets(
            mod,
            getattr(d, capacity_type_operational_period_sets),
        ),
    )  # assumes capacity types model components are already added!

    m.OPR_PRDS_BY_PRJ = Set(
        m.PROJECTS,
        initialize=lambda mod, project: operational_periods_by_project(
            prj=project, project_operational_periods=mod.PRJ_OPR_PRDS
        ),
    )

    m.PRJ_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: [
            (g, tmp)
            for g in mod.PROJECTS
            for p in mod.OPR_PRDS_BY_PRJ[g]
            for tmp in mod.TMPS_IN_PRD[p]
        ],
    )

    m.OPR_PRJS_IN_TMP = Set(
        m.TMPS,
        initialize=op_gens_by_tmp,
    )

    # Expressions
    ###########################################################################

    def capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "capacity_rule"):
            return imported_capacity_modules[cap_type].capacity_rule(mod, prj, prd)
        else:
            return cap_type_init.capacity_rule(mod, prj, prd)

    m.Capacity_MW = Expression(m.PRJ_OPR_PRDS, rule=capacity_rule)

    def energy_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "energy_rule"):
            return imported_capacity_modules[cap_type].energy_rule(mod, prj, prd)
        else:
            return cap_type_init.energy_rule(mod, prj, prd)

    m.Energy_MWh = Expression(m.PRJ_OPR_PRDS, rule=energy_rule)

    def hyb_gen_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "hyb_gen_capacity_rule"):
            return imported_capacity_modules[cap_type].hyb_gen_capacity_rule(
                mod, prj, prd
            )
        else:
            return cap_type_init.hyb_gen_capacity_rule(mod, prj, prd)

    m.Hyb_Gen_Capacity_MW = Expression(m.PRJ_OPR_PRDS, rule=hyb_gen_capacity_rule)

    def hyb_stor_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "hyb_stor_capacity_rule"):
            return imported_capacity_modules[cap_type].hyb_stor_capacity_rule(
                mod, prj, prd
            )
        else:
            return cap_type_init.hyb_stor_capacity_rule(mod, prj, prd)

    m.Hyb_Stor_Capacity_MW = Expression(m.PRJ_OPR_PRDS, rule=hyb_stor_capacity_rule)

    def energy_stor_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "energy_stor_capacity_rule"):
            return imported_capacity_modules[cap_type].energy_stor_capacity_rule(
                mod, prj, prd
            )
        else:
            return cap_type_init.energy_stor_capacity_rule(mod, prj, prd)

    m.Energy_Storage_Capacity_MWh = Expression(
        m.PRJ_OPR_PRDS, rule=energy_stor_capacity_rule
    )

    def fuel_prod_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "fuel_prod_capacity_rule"):
            return imported_capacity_modules[cap_type].fuel_prod_capacity_rule(
                mod, prj, prd
            )
        else:
            return cap_type_init.fuel_prod_capacity_rule(mod, prj, prd)

    m.Fuel_Production_Capacity_FuelUnitPerHour = Expression(
        m.PRJ_OPR_PRDS, rule=fuel_prod_capacity_rule
    )

    def fuel_release_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "fuel_release_capacity_rule"):
            return imported_capacity_modules[cap_type].fuel_release_capacity_rule(
                mod, prj, prd
            )
        else:
            return cap_type_init.fuel_release_capacity_rule(mod, prj, prd)

    m.Fuel_Release_Capacity_FuelUnitPerHour = Expression(
        m.PRJ_OPR_PRDS, rule=fuel_release_capacity_rule
    )

    def fuel_storage_capacity_rule(mod, prj, prd):
        cap_type = mod.capacity_type[prj]
        if hasattr(imported_capacity_modules[cap_type], "fuel_storage_capacity_rule"):
            return imported_capacity_modules[cap_type].fuel_storage_capacity_rule(
                mod, prj, prd
            )
        else:
            return cap_type_init.fuel_storage_capacity_rule(mod, prj, prd)

    m.Fuel_Storage_Capacity_FuelUnit = Expression(
        m.PRJ_OPR_PRDS, rule=fuel_storage_capacity_rule
    )


# Set Rules
###############################################################################


def op_gens_by_tmp(mod):
    """
    Figure out which generators are operational in each timepoint.
    """
    tmp_to_projects = {}
    for g, tmp in mod.PRJ_OPR_TMPS:
        tmp_to_projects.setdefault(tmp, set()).add(g)

    for tmp in tmp_to_projects:
        tmp_to_projects[tmp] = list(tmp_to_projects[tmp])

    return tmp_to_projects


def operational_periods_by_project(prj, project_operational_periods):
    """ """
    return sorted(
        list(
            set(
                period
                for (project, period) in project_operational_periods
                if project == prj
            )
        )
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
    """ """
    required_capacity_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="capacity_type",
    )

    # Import needed capacity type modules
    imported_capacity_modules = load_project_capacity_type_modules(
        required_capacity_modules
    )
    for op_m in required_capacity_modules:
        if hasattr(imported_capacity_modules[op_m], "load_model_data"):
            imported_capacity_modules[op_m].load_model_data(
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


# TODO: move this to gridpath.project.capacity.__init__?
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
    Export capacity results.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """

    results_columns = [
        "capacity_mw",
        "energy_mwh",
        "hyb_gen_capacity_mw",
        "hyb_stor_capacity_mw",
        "stor_energy_capacity_mwh",
        "fuel_prod_capacity_fuelunitperhour",
        "fuel_rel_capacity_fuelunitperhour",
        "fuel_stor_capacity_fuelunit",
    ]
    data = [
        [
            prj,
            prd,
            value(m.Capacity_MW[prj, prd]),
            value(m.Energy_MWh[prj, prd]),
            value(m.Hyb_Gen_Capacity_MW[prj, prd]),
            value(m.Hyb_Stor_Capacity_MW[prj, prd]),
            value(m.Energy_Storage_Capacity_MWh[prj, prd]),
            value(m.Fuel_Production_Capacity_FuelUnitPerHour[prj, prd]),
            value(m.Fuel_Release_Capacity_FuelUnitPerHour[prj, prd]),
            value(m.Fuel_Storage_Capacity_FuelUnit[prj, prd]),
        ]
        for (prj, prd) in m.PRJ_OPR_PRDS
    ]
    results_df = create_results_df(
        index_columns=["project", "period"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PROJECT_PERIOD_DF), results_df)

    # Module-specific capacity results
    required_capacity_modules = get_required_subtype_modules(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        which_type="capacity_type",
    )

    # Import needed capacity type modules
    imported_capacity_modules = load_project_capacity_type_modules(
        required_capacity_modules
    )
    for op_m in required_capacity_modules:
        if hasattr(imported_capacity_modules[op_m], "add_to_project_period_results"):
            results_columns, optype_df = imported_capacity_modules[
                op_m
            ].add_to_project_period_results(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                m,
                d,
            )
            update_results_df(getattr(d, PROJECT_PERIOD_DF), optype_df)
