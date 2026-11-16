# Copyright 2016-2023 Blue Marble Analytics LLC.
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
Generic treatment of project-level reserve provision, shared by the
load-following, regulation, spinning-reserves and frequency-response modules.

A project is mapped to one or more balancing areas (BAs) of a reserve type.
The project's total provision, :code:`Provide_<Reserve>_MW`, is what its
operational type constrains (headroom/footroom). A project mapped to a single
BA contributes that total to the BA directly. A project mapped to several BAs
gets an allocation variable per BA that must sum to the total; the share of
the total that may be allocated to each BA can be capped with the
:code:`max_fraction_of_provision` input (defaults to 1, i.e. no cap).

A project's provision of a reserve can also be limited by the reserve's
response time with the optional :code:`<reserve>_ramp_rate` operational
characteristic (e.g. :code:`regulation_up_ramp_rate`). Despite its name, this
input has no time dimension: it is the maximum provision as a FRACTION OF THE
PROJECT'S ONLINE CAPACITY, i.e. the project's ramp rate (as a fraction of
capacity per minute) times the reserve product's response time (in minutes).
For example, a project that can ramp 1% of its capacity per minute can provide
up to 0.01 x 10 = 0.1 of its online capacity of a 10-minute product, so its
ramp rate input for that reserve would be 0.1. Values are expected to be
between 0 and 1; if not specified, provision is not limited. Note that this
differs from the operational ramp rate inputs (e.g.
:code:`ramp_up_when_on_rate`), which are fractions of capacity per minute.
The reserve's per-project inputs (this limit and the
:code:`<reserve>_derate`) only apply to the projects that can provide the
reserve; values for other projects are ignored.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import (
    Set,
    Param,
    Var,
    Constraint,
    NonNegativeReals,
    PercentFraction,
    value,
)

from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_idxs,
    validate_values,
)
from gridpath.auxiliary.auxiliary import (
    check_list_items_are_unique,
    find_list_item_position,
    cursor_to_df,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import import_csv
from gridpath.auxiliary.dynamic_components import (
    reserve_variable_derate_params,
    reserve_to_energy_adjustment_params,
)
from gridpath.common_functions import (
    create_results_df,
    update_results_df,
    duals_wrapper,
    none_dual_type_error_wrapper,
)
from gridpath.project import PROJECT_TIMEPOINT_DF
from gridpath.project.operations.operational_types.common_functions import (
    write_tab_file_model_inputs,
)

MAX_FRACTION_COLUMN_NAME = "max_fraction_of_provision"
PROVISION_BY_BA_RESULTS_TABLE = "results_project_reserve_provision_by_ba"

_PRJ_BA_MAPS_CACHE_ATTR = "_gridpath_reserve_prj_ba_maps"


def project_bas_input_file_name(reserve_type):
    """
    :param reserve_type: the reserve module name, e.g. 'lf_reserves_up'
    :return: the name of the .tab file with the project-BA map for the reserve
    """
    return f"project_{reserve_type}_bas.tab"


def load_reserve_project_param_from_projects_file(
    data_portal, projects_file, project_bas_file, column_name, param
):
    """
    Load a per-project reserve input from a projects.tab column into a param
    indexed by the reserve's projects. projects.tab lists every project in the
    portfolio, so only the projects in the reserve's project-BA file are
    loaded (a value for a project that does not provide the reserve is
    ignored rather than failing the param's index check); "." = the param's
    default. Nothing is loaded if projects.tab has no such column.

    :param data_portal: the Pyomo DataPortal
    :param projects_file: path to projects.tab
    :param project_bas_file: path to the reserve's project-BA .tab file
    :param column_name: the projects.tab column
    :param param: the Pyomo param indexed by the reserve's projects
    """
    projects_df = pd.read_csv(projects_file, sep="\t", dtype=str, keep_default_na=False)
    if column_name not in projects_df.columns:
        return

    reserve_projects = set(
        pd.read_csv(project_bas_file, sep="\t", dtype=str, keep_default_na=False)[
            "project"
        ]
    )
    data_portal.data()[param.name] = {
        prj: float(val)
        for prj, val in zip(projects_df["project"], projects_df[column_name])
        if prj in reserve_projects and val != "."
    }


def provision_by_ba_results_file_name(reserve_type):
    """
    :param reserve_type: the reserve module name
    :return: the name (without extension) of the per-BA provision results
        CSV for the reserve type; all reserve types import into the same
        results table
    """
    return f"project_{reserve_type}_provision_by_ba"


def get_prj_ba_maps(mod, reserve_prj_bas_set):
    """
    :param mod: the model instance
    :param reserve_prj_bas_set: name of the (project, BA) set of the reserve
    :return: (bas_by_prj, prjs_by_ba) dictionaries of lists, in input order

    Built in a single pass over the set and cached on the instance, so the
    indexed-set initializers don't each rescan the set.
    """
    cache = getattr(mod, _PRJ_BA_MAPS_CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(mod, _PRJ_BA_MAPS_CACHE_ATTR, cache)
    if reserve_prj_bas_set not in cache:
        bas_by_prj = {}
        prjs_by_ba = {}
        for prj, ba in getattr(mod, reserve_prj_bas_set):
            bas_by_prj.setdefault(prj, []).append(ba)
            prjs_by_ba.setdefault(ba, []).append(prj)
        cache[reserve_prj_bas_set] = (bas_by_prj, prjs_by_ba)
    return cache[reserve_prj_bas_set]


def generic_record_dynamic_components(
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    headroom_or_footroom_dict,
    project_bas_input_file,
    reserve_provision_variable_name,
    reserve_provision_derate_param_name,
    reserve_to_energy_adjustment_param_name,
    reserve_bas_by_project_set_name,
    reserve_provision_by_ba_variable_name,
):
    """
    :param d: the DynamicComponents class we'll be populating
    :param scenario_directory: the base scenario directory
    :param stage: the horizon subproblem, not used here
    :param stage: the stage subproblem, not used here
    :param headroom_or_footroom_dict: the headroom or footroom dictionary
        with projects as keys and list of headroom or footroom variables,
        respectively, as values; the keys are populated in the
        *determine_dynamic_inputs* method of *gridpath.project.__init__*
    :param project_bas_input_file: the name of the input file that maps
        projects to the reserve's balancing areas
    :param reserve_provision_variable_name: the variable name for this
        reserve type
    :param reserve_provision_derate_param_name: the reserve-provision derate
        paramater name for this reserve type
    :param reserve_to_energy_adjustment_param_name: the
        reserve-to-energy-adjustment parameter name for this reserve type
    :param reserve_bas_by_project_set_name: the name of the indexed set of
        balancing areas by project for this reserve type
    :param reserve_provision_by_ba_variable_name: the name of the per-BA
        allocation variable for this reserve type

    This method populates the following 'dynamic components':

    * headroom_variables or footroom_variables
    * reserve_variable_derate_params
    * reserve_to_energy_adjustment_params

    The *headroom_variables* and *footroom_variables* components are populated
    based on the data in the project-BA input file of the reserve type.

    When this method is called, the module calling it will specify whether
    the respective reserve variable name should be added to the headroom or
    footroom dictionaries. For projects mapped to at least one balancing area
    of the reserve type, the respective reserve-provision variable name (the
    *reserve_provision_variable_name* specified by the reserve module calling
    this method) will be added to the project's list of headroom/footroom
    variables. These lists will then be passed to the 'add_model_components'
    method of the operational-modules and used to build the appropriate
    operational constraints for each project, usually named the 'max power
    rule' (power + upward reserves must be less than or equal to online
    capacity) and 'min power rule' (power - downward reserves must be greater
    than or equal to the minimum stable level) in the operational-type modules.

    Advanced GridPath functionality includes the ability to put a more
    stringent constraint on reserve-provision than the available
    headroom/footroom by de-rating how much of the available project
    headroom/footroom can be used for a certain reserve-type in the respective
    constraints in the *operational_type* modules. The
    *reserve_variable_derate_params* dynamic component dictionary is
    populated here; it has the project-level reserve provision variable as
    key and the derate param for the respective reserve variable as value.

    .. note:: Currently, these de-rates are only used in the *variable*
        operational type and we need to add them to other operational types.

    Advanced GridPath functionality also includes the ability to account for
    the energy effects of reserve-provision. For example, when providing
    regulation-up during a timepoint, projects will occasionally be called
    upon, so they will produce extra energy above what was schedule for the
    timepont. Similarly, if they are providing load-following down,
    they will occasionally be called upon to reduce their output, so will
    produce less energy than 'scheduled' for the timepoint. To account for
    this, the simplest treatment is to multiply the reserve-provision
    variables by a parameter and include that 'energy' in other constraints.
    We create a dictionary of the reserve-provision variables and the
    adjustment parameter name for each reserve-type requested by the user.
    The adjustment varies by balancing area, so the dictionary also records
    the names of the components needed to resolve a project's balancing
    area(s) and, for projects in several BAs, its per-BA allocation.

    .. note:: Currently, these adjustments are only used in the *variable*
        operational type and we need to add them to other operational types.
    """

    # Projects with at least one balancing area for the current reserve type
    # get the variable name for the current reserve type added to their list
    # of variables in the headroom/footroom dictionary
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            project_bas_input_file,
        ),
        "r",
    ) as project_bas_file:
        project_bas_file_reader = csv.reader(
            project_bas_file, delimiter="\t", lineterminator="\n"
        )
        headers = next(project_bas_file_reader)
        # Check that column names are not repeated
        check_list_items_are_unique(headers)
        project_column = find_list_item_position(headers, "project")[0]
        for row in project_bas_file_reader:
            generator = row[project_column]
            # If we have already added this generator to the head/footroom
            # variables dictionary, move on; otherwise, create the
            # dictionary item
            if generator not in getattr(d, headroom_or_footroom_dict).keys():
                getattr(d, headroom_or_footroom_dict)[generator] = list()
            # A project mapped to several BAs has several rows; its
            # provision variable is recorded once
            if (
                reserve_provision_variable_name
                not in getattr(d, headroom_or_footroom_dict)[generator]
            ):
                getattr(d, headroom_or_footroom_dict)[generator].append(
                    reserve_provision_variable_name
                )

    # The names of the headroom/footroom derate params for each reserve
    # variable
    # Will be used to get the right derate parameter name for each
    # reserve-provision variable
    # TODO: these de-rates are currently only used in the variable
    #  operational_type and must be added to other operational types
    getattr(d, reserve_variable_derate_params)[
        reserve_provision_variable_name
    ] = reserve_provision_derate_param_name

    # The names of the subhourly energy adjustment params for each reserve
    # variable along with the components needed to resolve the adjustment
    # for each project (adjustment can vary by reserve type and by balancing
    # area within each reserve type)
    # Will be used to get the right adjustment for each project providing a
    # particular reserve
    # TODO: these adjustments are currently only applied in the variable
    #  operational_type and must be added to other operational types
    getattr(d, reserve_to_energy_adjustment_params)[reserve_provision_variable_name] = (
        reserve_to_energy_adjustment_param_name,
        reserve_bas_by_project_set_name,
        reserve_provision_by_ba_variable_name,
    )


def generic_add_model_components(
    m,
    d,
    reserve_projects_set,
    reserve_prj_bas_set,
    reserve_bas_by_prj_set,
    reserve_prjs_by_ba_set,
    reserve_multi_ba_prjs_set,
    reserve_multi_ba_prj_ba_opr_tmps_set,
    reserve_max_fraction_param,
    reserve_provision_derate_param,
    reserve_balancing_areas_set,
    reserve_project_operational_timepoints_set,
    reserve_provision_variable_name,
    reserve_provision_by_ba_variable_name,
    reserve_ba_allocation_constraint,
    reserve_max_fraction_constraint,
    reserve_to_energy_adjustment_param,
):
    """
    :param m:
    :param d:
    :param reserve_projects_set: projects that can provide the reserve
    :param reserve_prj_bas_set: two-dimensional set of (project, BA)
    :param reserve_bas_by_prj_set: the BAs of each reserve project
    :param reserve_prjs_by_ba_set: the reserve projects of each BA
    :param reserve_multi_ba_prjs_set: the reserve projects in several BAs
    :param reserve_multi_ba_prj_ba_opr_tmps_set: three-dimensional set of
        (project, BA, timepoint) over the projects in several BAs
    :param reserve_max_fraction_param: cap on the share of a project's
        total provision allocated to a BA
    :param reserve_provision_derate_param:
    :param reserve_balancing_areas_set:
    :param reserve_project_operational_timepoints_set:
    :param reserve_provision_variable_name: the project's total provision
    :param reserve_provision_by_ba_variable_name: the per-BA allocation of the
        total for projects in several BAs
    :param reserve_ba_allocation_constraint: allocations sum to the total
    :param reserve_max_fraction_constraint: allocation <= cap x total
    :param reserve_to_energy_adjustment_param:

    Reserve-related components that will be used by the operational_type
    modules (the total provision variable and the derate) and by the
    system-level aggregation (the per-BA contributions).
    """

    setattr(
        m,
        reserve_prj_bas_set,
        Set(dimen=2, within=m.PROJECTS * getattr(m, reserve_balancing_areas_set)),
    )

    # Projects in input order, once each
    setattr(
        m,
        reserve_projects_set,
        Set(
            within=m.PROJECTS,
            initialize=lambda mod: list(
                dict.fromkeys(prj for (prj, ba) in getattr(mod, reserve_prj_bas_set))
            ),
        ),
    )

    setattr(
        m,
        reserve_bas_by_prj_set,
        Set(
            getattr(m, reserve_projects_set),
            within=getattr(m, reserve_balancing_areas_set),
            initialize=lambda mod, prj: get_prj_ba_maps(mod, reserve_prj_bas_set)[0][
                prj
            ],
        ),
    )

    setattr(
        m,
        reserve_prjs_by_ba_set,
        Set(
            getattr(m, reserve_balancing_areas_set),
            within=getattr(m, reserve_projects_set),
            initialize=lambda mod, ba: get_prj_ba_maps(mod, reserve_prj_bas_set)[1].get(
                ba, []
            ),
        ),
    )

    setattr(
        m,
        reserve_multi_ba_prjs_set,
        Set(
            within=getattr(m, reserve_projects_set),
            initialize=lambda mod: [
                prj
                for prj in getattr(mod, reserve_projects_set)
                if len(getattr(mod, reserve_bas_by_prj_set)[prj]) > 1
            ],
        ),
    )

    setattr(
        m,
        reserve_project_operational_timepoints_set,
        Set(
            dimen=2,
            initialize=lambda mod: subset_init_by_set_membership(
                mod=mod,
                superset="PRJ_OPR_TMPS",
                index=0,
                membership_set=getattr(mod, reserve_projects_set),
            ),
        ),
    )

    def multi_ba_prj_ba_opr_tmps_init(mod):
        multi_ba_prjs = getattr(mod, reserve_multi_ba_prjs_set)
        bas_by_prj = getattr(mod, reserve_bas_by_prj_set)
        return [
            (prj, ba, tmp)
            for (prj, tmp) in getattr(mod, reserve_project_operational_timepoints_set)
            if prj in multi_ba_prjs
            for ba in bas_by_prj[prj]
        ]

    setattr(
        m,
        reserve_multi_ba_prj_ba_opr_tmps_set,
        Set(dimen=3, initialize=multi_ba_prj_ba_opr_tmps_init),
    )

    # Cap on the share of the project's total provision that can be allocated
    # to each of its BAs; defaults to 1 (no cap); only meaningful for
    # projects in several BAs
    setattr(
        m,
        reserve_max_fraction_param,
        Param(getattr(m, reserve_prj_bas_set), within=PercentFraction, default=1),
    )

    # The project's total provision; constrained by the operational types
    setattr(
        m,
        reserve_provision_variable_name,
        Var(
            getattr(m, reserve_project_operational_timepoints_set),
            within=NonNegativeReals,
        ),
    )

    # Allocation of the total to each BA for projects in several BAs
    setattr(
        m,
        reserve_provision_by_ba_variable_name,
        Var(
            getattr(m, reserve_multi_ba_prj_ba_opr_tmps_set),
            within=NonNegativeReals,
        ),
    )

    def ba_allocation_rule(mod, prj, tmp):
        """
        A multi-BA project's allocations sum to its total provision; skipped
        for single-BA projects, whose total contributes to their BA directly.
        """
        if prj not in getattr(mod, reserve_multi_ba_prjs_set):
            return Constraint.Skip
        provision_by_ba = getattr(mod, reserve_provision_by_ba_variable_name)
        return (
            sum(
                provision_by_ba[prj, ba, tmp]
                for ba in getattr(mod, reserve_bas_by_prj_set)[prj]
            )
            == getattr(mod, reserve_provision_variable_name)[prj, tmp]
        )

    setattr(
        m,
        reserve_ba_allocation_constraint,
        Constraint(
            getattr(m, reserve_project_operational_timepoints_set),
            rule=ba_allocation_rule,
        ),
    )

    def max_fraction_rule(mod, prj, ba, tmp):
        """
        The allocation to a BA can't exceed the capped share of the total;
        skipped at the default cap of 1 (implied by the allocation constraint
        and the non-negativity of the allocations).
        """
        max_fraction = getattr(mod, reserve_max_fraction_param)[prj, ba]
        if max_fraction >= 1:
            return Constraint.Skip
        return (
            getattr(mod, reserve_provision_by_ba_variable_name)[prj, ba, tmp]
            <= max_fraction * getattr(mod, reserve_provision_variable_name)[prj, tmp]
        )

    setattr(
        m,
        reserve_max_fraction_constraint,
        Constraint(
            getattr(m, reserve_multi_ba_prj_ba_opr_tmps_set), rule=max_fraction_rule
        ),
    )

    # Headroom/footroom derate -- this is how much extra footroom or
    # headroom must be available in order to provide 1 unit of up or down
    # reserves respectively
    # For example, if the derate is 0.5, the required headroom for providing
    # upward reserves is 1/0.5=2 -- twice the reserve that can be provided
    # Defaults to 1 if not specified
    # This param is used by the operational_type modules
    setattr(
        m,
        reserve_provision_derate_param,
        Param(getattr(m, reserve_projects_set), within=PercentFraction, default=1),
    )

    # Energy adjustment from subhourly reserve provision
    # (e.g. for storage state of charge or how much variable RPS energy is
    # delivered because of subhourly reserve provision)
    # This is an optional param, which will default to 0 if not specified
    # This param is used by the operational_type modules
    setattr(
        m,
        reserve_to_energy_adjustment_param,
        Param(
            getattr(m, reserve_balancing_areas_set), within=PercentFraction, default=0
        ),
    )


def provision_to_ba_terms(
    mod,
    reserve_prjs_by_ba_set,
    reserve_multi_ba_prjs_set,
    reserve_provision_variable_name,
    reserve_provision_by_ba_variable_name,
):
    """
    :param mod: the model instance
    :return: {ba: [(project, variable component, index prefix), ...]}

    For each BA, the variable and index prefix of each project's contribution
    to it: the total provision variable (prefix (prj,)) for single-BA
    projects and the allocation variable (prefix (prj, ba)) for multi-BA
    projects; the caller appends the timepoint. Resolved once per reserve
    type rather than once per (BA, timepoint).
    """
    provision = getattr(mod, reserve_provision_variable_name)
    provision_by_ba = getattr(mod, reserve_provision_by_ba_variable_name)
    multi_ba_prjs = getattr(mod, reserve_multi_ba_prjs_set)
    prjs_by_ba = getattr(mod, reserve_prjs_by_ba_set)
    return {
        ba: [
            (
                (prj, provision_by_ba, (prj, ba))
                if prj in multi_ba_prjs
                else (prj, provision, (prj,))
            )
            for prj in prjs_by_ba[ba]
        ]
        for ba in prjs_by_ba
    }


def generic_load_model_data(
    m,
    d,
    data_portal,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    project_bas_input_file,
    derate_column_name,
    reserve_prj_bas_set,
    reserve_max_fraction_param,
    reserve_provision_derate_param,
    reserve_to_energy_adjustment_param,
    reserve_balancing_areas_input_file,
):
    """

    :param m:
    :param d:
    :param data_portal:
    :param scenario_directory:
    :param stage:
    :param stage:
    :param project_bas_input_file:
    :param derate_column_name:
    :param reserve_prj_bas_set:
    :param reserve_max_fraction_param:
    :param reserve_provision_derate_param:
    :param reserve_to_energy_adjustment_param:
    :param reserve_balancing_areas_input_file:
    :return:
    """

    # Project-BA map and the per-BA caps ("." = default of 1)
    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            project_bas_input_file,
        ),
        index=getattr(m, reserve_prj_bas_set),
        param=getattr(m, reserve_max_fraction_param),
    )

    # Import reserve provision headroom/footroom de-rate parameter only if
    # column is present
    # Otherwise, the de-rate param goes to its default of 1
    projects_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "projects.tab",
    )
    load_reserve_project_param_from_projects_file(
        data_portal=data_portal,
        projects_file=projects_file,
        project_bas_file=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            project_bas_input_file,
        ),
        column_name=derate_column_name,
        param=getattr(m, reserve_provision_derate_param),
    )

    # Load reserve provision subhourly energy adjustment (e.g. for storage
    # state of charge adjustment or delivered variable RPS energy adjustment)
    # if specified; otherwise it will default to 0
    ba_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        reserve_balancing_areas_input_file,
    )
    ba_file_header = pd.read_csv(ba_file, sep="\t", header=None, nrows=1).values[0]

    if "reserve_to_energy_adjustment" in ba_file_header:
        data_portal.load(
            filename=ba_file,
            select=("balancing_area", "reserve_to_energy_adjustment"),
            param=getattr(m, reserve_to_energy_adjustment_param),
        )


def generic_export_results(
    m,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    module_name,
    reserve_project_operational_timepoints_set,
    reserve_provision_variable_name,
    reserve_bas_by_prj_set,
    reserve_multi_ba_prj_ba_opr_tmps_set,
    reserve_provision_by_ba_variable_name,
    reserve_max_fraction_param,
    reserve_max_fraction_constraint,
):
    """
    Export project-level reserves results: the project's balancing area (for
    projects in a single BA) and total provision into the project-timepoint
    results, and the per-BA allocations of projects in several BAs (with the
    cap on each and its dual, where the cap constraint was built) into
    their own results file.
    :param m:
    :param d:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param module_name:
    :param reserve_project_operational_timepoints_set:
    :param reserve_provision_variable_name:
    :param reserve_bas_by_prj_set:
    :param reserve_multi_ba_prj_ba_opr_tmps_set:
    :param reserve_provision_by_ba_variable_name:
    :param reserve_max_fraction_param:
    :param reserve_max_fraction_constraint:
    :return:
    """

    results_columns = [
        f"{module_name}_ba",
        f"{module_name}_reserve_provision_mw",
    ]

    bas_by_prj = getattr(m, reserve_bas_by_prj_set)
    data = [
        [
            prj,
            tmp,
            bas_by_prj[prj].first() if len(bas_by_prj[prj]) == 1 else None,
            value(getattr(m, reserve_provision_variable_name)[prj, tmp]),
        ]
        for (prj, tmp) in getattr(m, reserve_project_operational_timepoints_set)
    ]

    results_df = create_results_df(
        index_columns=["project", "timepoint"],
        results_columns=results_columns,
        data=data,
    )

    update_results_df(getattr(d, PROJECT_TIMEPOINT_DF), results_df)

    # Per-BA allocations of projects in several BAs
    provision_by_ba = getattr(m, reserve_provision_by_ba_variable_name)
    max_fraction = getattr(m, reserve_max_fraction_param)
    max_fraction_constraint = getattr(m, reserve_max_fraction_constraint)
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            f"{provision_by_ba_results_file_name(module_name)}.csv",
        ),
        "w",
        newline="",
    ) as results_file:
        writer = csv.writer(results_file)
        writer.writerow(
            [
                "reserve_type",
                "project",
                "timepoint",
                "balancing_area",
                "reserve_provision_mw",
                "max_fraction_of_provision",
                "max_fraction_dual",
                "max_fraction_marginal_price_per_mw",
            ]
        )
        for prj, ba, tmp in getattr(m, reserve_multi_ba_prj_ba_opr_tmps_set):
            # The cap constraint is only built below the default cap of 1
            if (prj, ba, tmp) in max_fraction_constraint:
                dual = duals_wrapper(m, max_fraction_constraint[prj, ba, tmp])
                marginal_price = none_dual_type_error_wrapper(
                    dual, m.tmp_objective_coefficient[tmp]
                )
            else:
                dual, marginal_price = None, None
            writer.writerow(
                [
                    module_name,
                    prj,
                    tmp,
                    ba,
                    value(provision_by_ba[prj, ba, tmp]),
                    max_fraction[prj, ba],
                    dual,
                    marginal_price,
                ]
            )


def generic_import_results_into_database(
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
    module_name,
):
    """
    Import the per-BA allocations of projects in several BAs; all reserve
    types share one results table.
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
        which_results=provision_by_ba_results_file_name(module_name),
        results_table=PROVISION_BY_BA_RESULTS_TABLE,
    )


def generic_get_inputs_from_database(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    reserve_type,
    project_ba_subscenario_id,
    ba_subscenario_id,
    extra_columns=(),
):
    """

    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :param reserve_type:
    :param project_ba_subscenario_id:
    :param ba_subscenario_id:
    :param extra_columns: further columns of the project-BA table to select
    :return: cursor over (project, BA, max_fraction_of_provision[, extras]) --
        one row per project-BA pair, only for BAs in the reserve's BA
        subscenario -- and a cursor over the project derates
    """
    # Get project BAs
    columns = ", ".join(
        ["project", f"{reserve_type}_ba", MAX_FRACTION_COLUMN_NAME]
        + list(extra_columns)
    )
    c1 = conn.cursor()
    project_bas = c1.execute(f"""
        SELECT {columns}
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        ) as prj_tbl
        INNER JOIN 
        -- Get BAs for those projects
        (SELECT {columns}
            FROM inputs_project_{reserve_type}_bas
            WHERE project_{reserve_type}_ba_scenario_id = {project_ba_subscenario_id}
        ) as prj_ba_tbl
        USING (project)
        -- Filter out BAs not included in our reserve_ba_scenario_id
        WHERE {reserve_type}_ba in (
                SELECT {reserve_type}_ba
                    FROM inputs_geography_{reserve_type}_bas
                    WHERE {reserve_type}_ba_scenario_id = {ba_subscenario_id}
        )
        ORDER BY project, {reserve_type}_ba;
        """)

    # Get headroom/footroom derate
    c2 = conn.cursor()
    project_derates = c2.execute(
        """
        SELECT project, {}_derate
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get derates for those projects
        (SELECT project, {}_derate
            FROM inputs_project_operational_chars
            WHERE project_operational_chars_scenario_id = {}
        ) as prj_derate_tbl
        USING (project);
        """.format(
            reserve_type,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            reserve_type,
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
        )
    )

    return project_bas, project_derates


def generic_validate_project_bas(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    reserve_type,
    project_ba_subscenario_id,
    ba_subscenario_id,
):
    """

    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :param reserve_type:
    :param project_ba_subscenario_id:
    :param ba_subscenario_id:
    :return:
    """

    project_bas, prj_derates = generic_get_inputs_from_database(
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        conn=conn,
        reserve_type=reserve_type,
        project_ba_subscenario_id=project_ba_subscenario_id,
        ba_subscenario_id=ba_subscenario_id,
    )

    # Convert input data into pandas DataFrame
    df = cursor_to_df(project_bas)
    df_derate = cursor_to_df(prj_derates).dropna()
    ba_col = "{}_ba".format(reserve_type)
    bas_w_project = df[ba_col].unique()
    projects_w_ba = df["project"].unique()
    projects_w_derate = df_derate["project"].unique()

    # Get the required reserve bas
    c = conn.cursor()
    bas = c.execute(
        """SELECT {}_ba FROM inputs_geography_{}_bas
        WHERE {}_ba_scenario_id = {}
        """.format(
            reserve_type,
            reserve_type,
            reserve_type,
            ba_subscenario_id,
        )
    )
    bas = [b[0] for b in bas]  # convert to list

    prj_ba_table = "inputs_project_{}_bas".format(reserve_type)

    # Check that each reserve BA has at least one project assigned to it
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table=prj_ba_table,
        severity="High",
        errors=validate_idxs(
            actual_idxs=bas_w_project,
            req_idxs=bas,
            idx_label=ba_col,
            msg="Each reserve BA needs at least 1 " "project assigned to it.",
        ),
    )

    # Check that all projects w derates have a BA specified
    msg = "Project has a reserve derate specified but no relevant BA."
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_operational_chars",
        severity="Low",
        errors=validate_idxs(
            actual_idxs=projects_w_ba,
            req_idxs=projects_w_derate,
            idx_label="project",
            msg=msg,
        ),
    )

    # Check the per-BA caps of projects in several BAs: each in (0, 1] and
    # summing to at least 1 per project (a project whose caps sum to less
    # than 1 can't provide any reserves at all)
    df_multi = df[df.groupby("project")["project"].transform("size") > 1].copy()
    df_multi[MAX_FRACTION_COLUMN_NAME] = (
        df_multi[MAX_FRACTION_COLUMN_NAME].astype(float).fillna(1)
    )
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table=prj_ba_table,
        severity="High",
        errors=validate_values(
            df_multi,
            MAX_FRACTION_COLUMN_NAME,
            idx_col=["project", ba_col],
            min=0,
            max=1,
            strict_min=True,
        ),
    )

    fraction_sums = df_multi.groupby("project")[MAX_FRACTION_COLUMN_NAME].sum()
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table=prj_ba_table,
        severity="High",
        errors=[
            "project(s) '{}': {} sums to {} over the project's BAs; it must "
            "sum to at least 1 or the project can't provide any reserves".format(
                prj, MAX_FRACTION_COLUMN_NAME, total
            )
            for prj, total in fraction_sums.items()
            if total < 1
        ],
    )


def generic_write_model_inputs(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    reserve_type,
    project_bas,
    prj_derates,
    derate_column_name,
    extra_project_columns=(),
):
    """
    Write the project-BA map to its own .tab file and amend projects.tab
    with the derate column.

    :param scenario_directory: string, the scenario directory
    :param reserve_type: the reserve module name
    :param project_bas: cursor over (project, BA, max_fraction_of_provision)
    :param prj_derates: cursor over (project, derate)
    :param derate_column_name: the derate column to add to projects.tab
    :param extra_project_columns: (column name, {project: value}) pairs of
        further per-project columns to amend projects.tab with (before the
        derate column); projects without a value get "."
    :return:
    """

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        project_bas_input_file_name(reserve_type),
        project_bas,
        replace_nulls=True,
    )

    # Make a dict for easy access
    prj_derate_dict = dict()
    for prj, derate in prj_derates:
        prj_derate_dict[str(prj)] = "." if derate is None else str(derate)

    # Add params to projects file
    projects_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "projects.tab",
    )
    with open(projects_file, "r") as projects_file_in:
        reader = csv.reader(projects_file_in, delimiter="\t", lineterminator="\n")

        new_rows = list()

        # Append column headers
        header = next(reader)
        for column_name, _ in extra_project_columns:
            header.append(column_name)
        header.append(derate_column_name)
        new_rows.append(header)

        # Append correct values
        for row in reader:
            for _, values_by_project in extra_project_columns:
                row.append(values_by_project.get(row[0], "."))
            # If project specified, check if derate specified or not
            # If project not specified, specify no derate
            row.append(prj_derate_dict.get(row[0], "."))

            # Add resulting row to new_rows list
            new_rows.append(row)

    with open(projects_file, "w", newline="") as projects_file_out:
        writer = csv.writer(projects_file_out, delimiter="\t", lineterminator="\n")
        writer.writerows(new_rows)
