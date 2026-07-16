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

"""
This operational type is linked to a specific load component that it modifies
by removing the static load profile for this load component from the load
balance constraint and adding a modified load profile to the load balance
constraint that is determined as follows:
1)
"""

import os.path
from pyomo.environ import (
    Param,
    Set,
    Reals,
    Constraint,
    Var,
    Any,
    NonNegativeReals,
    Expression,
)
import warnings

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    get_projects_by_reserve,
    validate_idxs,
)
from gridpath.auxiliary.dynamic_components import headroom_variables, footroom_variables
from gridpath.project.operations.reserves.reserve_aggregation import (
    headroom_provision_rule,
    footroom_provision_rule,
)
from gridpath.project.common_functions import (
    check_if_first_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    load_var_profile_inputs,
    get_prj_temporal_index_opr_inputs_from_db,
    write_tab_file_model_inputs,
    validate_opchars,
    validate_var_profiles,
    load_optype_model_data,
    BT_HRZ_INDEX_QUERY_PARAMS,
)

Infinity = float("inf")


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
    | | :code:`LOAD_COMPONENT_SHIFT_PRJS`                                     |
    |                                                                         |
    | The set of generators of the :code:`load_component_shift`               |
    | operational type.                                                       |
    +-------------------------------------------------------------------------+
    | | :code:`LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS`                            |
    |                                                                         |
    | Two-dimensional set with generators of the                              |
    | :code:`load_component_shift` operational type and their operational     |
    | timepoints.                                                             |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`load_component_shift_fraction`                                 |
    | | *Defined over*: :code:`LOAD_COMPONENT_SHIFT_PRJS`                     |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The project's power output in each operational timepoint as a fraction  |
    | of its available capacity (i.e. the capacity factor).                   |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.LOAD_COMPONENT_SHIFT_PRJS = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "load_component_shift"
        ),
    )

    m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.LOAD_COMPONENT_SHIFT_PRJS,
        ),
    )

    # Derived sets
    m.LOAD_COMPONENT_SHIFT_PRJS_OPR_PRDS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_PRDS",
            index=0,
            membership_set=mod.LOAD_COMPONENT_SHIFT_PRJS,
        ),
    )

    m.LOAD_COMPONENT_SHIFT_PRJS_BT_HRZS = Set(
        dimen=3, within=m.LOAD_COMPONENT_SHIFT_PRJS * m.BLN_TYPE_HRZS
    )

    # Required Params
    ###########################################################################

    m.load_component_shift_linked_load_component = Param(
        m.LOAD_COMPONENT_SHIFT_PRJS,
        within=Any,
    )

    m.load_component_shift_min_load_mw = Param(
        m.LOAD_COMPONENT_SHIFT_PRJS_BT_HRZS, within=NonNegativeReals, default=0
    )

    m.load_component_shift_max_load_mw = Param(
        m.LOAD_COMPONENT_SHIFT_PRJS_BT_HRZS, within=NonNegativeReals, default=Infinity
    )

    # Derived params
    m.load_component_shift_load_component_peak_load_in_period = Param(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_PRDS,
        initialize=lambda mod, prj, prd: max(
            [
                mod.component_static_load_mw[
                    mod.load_zone[prj],
                    tmp,
                    mod.load_component_shift_linked_load_component[prj],
                ]
                for tmp in mod.TMPS_IN_PRD[prd]
            ]
        ),
    )

    # Optional params
    ###########################################################################
    m.load_component_shift_efficiency_factor = Param(
        m.LOAD_COMPONENT_SHIFT_PRJS, within=NonNegativeReals, default=1
    )

    # Variables
    ###########################################################################
    m.Load_Component_Shift_Fraction_Invested = Var(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_PRDS, bounds=(0, 1), initialize=0
    )

    m.Load_Component_Shift_Add_Load_MW = Var(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS, within=NonNegativeReals
    )

    # Derived Params
    ###########################################################################

    def bt_hrz_by_prj_tmp_init(mod):
        """
        Map each project-timepoint to the (bt, hrz) with specified bounds
        that contains it, if any.
        """
        bt_hrz_by_prj_tmp = {}
        for prj, bt, hrz in mod.LOAD_COMPONENT_SHIFT_PRJS_BT_HRZS:
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
                if (prj, tmp) not in mod.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS:
                    continue
                if (prj, tmp) in bt_hrz_by_prj_tmp:
                    raise ValueError(f"""More than one value per timepoints specified
                 for bounds for load_component_shift project {prj},
                 timepoint {tmp}. Please ensure you don't have
                 overlapping horizons.""")
                bt_hrz_by_prj_tmp[prj, tmp] = (bt, hrz)

        return bt_hrz_by_prj_tmp

    m.load_component_shift_bt_hrz_by_prj_tmp = Param(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS,
        within=Any,
        initialize=bt_hrz_by_prj_tmp_init,
        default=None,
    )

    # Expression
    ###########################################################################

    def load_component_shift_min_load_rule(mod, prj, tmp):
        bt_hrz = mod.load_component_shift_bt_hrz_by_prj_tmp[prj, tmp]

        # Check if bounds are specified for this timepoint; if not, set the
        # min to the static load (no shifting)
        if bt_hrz is not None:
            bt, hrz = bt_hrz
            tmp_val_min = mod.load_component_shift_min_load_mw[prj, bt, hrz]
        else:
            tmp_val_min = (
                mod.component_static_load_mw[
                    mod.load_zone[prj],
                    tmp,
                    mod.load_component_shift_linked_load_component[prj],
                ]
                * mod.Load_Component_Shift_Fraction_Invested[prj, mod.period[tmp]]
            )

        return tmp_val_min

    m.load_component_shift_min_load_mw_by_tmp = Expression(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS,
        rule=load_component_shift_min_load_rule,
    )

    def load_component_shift_max_load_rule(mod, prj, tmp):
        bt_hrz = mod.load_component_shift_bt_hrz_by_prj_tmp[prj, tmp]

        # Check if bounds are specified for this timepoint; if not, set the
        # max to the static load (no shifting)
        if bt_hrz is not None:
            bt, hrz = bt_hrz
            if mod.load_component_shift_max_load_mw[prj, bt, hrz] != Infinity:
                tmp_val_max = mod.load_component_shift_max_load_mw[prj, bt, hrz]
            else:
                tmp_val_max = mod.Capacity_MW[prj, mod.period[tmp]]
        else:
            tmp_val_max = (
                mod.component_static_load_mw[
                    mod.load_zone[prj],
                    tmp,
                    mod.load_component_shift_linked_load_component[prj],
                ]
                * mod.Load_Component_Shift_Fraction_Invested[prj, mod.period[tmp]]
            )

        return tmp_val_max

    m.load_component_shift_max_load_mw_by_tmp = Expression(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS,
        rule=load_component_shift_max_load_rule,
    )

    # Constraints
    ###########################################################################

    def fraction_invested_constraint_rule(mod, prj, prd):
        """
        Limits the capacity of this project to the peak load because
        Load_Component_Shift_Fraction_Invested is bounded to (0,1).
        """
        return (
            mod.Load_Component_Shift_Fraction_Invested[prj, prd]
            == mod.Capacity_MW[prj, prd]
            / mod.load_component_shift_load_component_peak_load_in_period[prj, prd]
        )

    m.Load_Component_Shift_Fraction_Invested_Constraint = Constraint(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_PRDS, rule=fraction_invested_constraint_rule
    )

    def energy_budget_rule(mod, prj, bt, hrz):
        """
        Sets the total energy consumption to equal the static load energy
        consumption for each horizon.
        """
        return (
            sum(
                # The load that can be shifted is proportional to the investment
                mod.component_static_load_mw[
                    mod.load_zone[prj],
                    tmp,
                    mod.load_component_shift_linked_load_component[prj],
                ]
                * mod.Load_Component_Shift_Fraction_Invested[prj, mod.period[tmp]]
                * mod.hrs_in_tmp[tmp]
                * mod.tmp_weight[tmp]
                for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            == sum(
                mod.Load_Component_Shift_Add_Load_MW[prj, tmp]
                * mod.hrs_in_tmp[tmp]
                * mod.tmp_weight[tmp]
                for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            * mod.load_component_shift_efficiency_factor[prj]
        )

    m.Load_Component_Shift_Energy_Balance_Constraint = Constraint(
        m.LOAD_COMPONENT_SHIFT_PRJS_BT_HRZS, rule=energy_budget_rule
    )

    def min_demand_rule(mod, prj, tmp):
        return (
            mod.Load_Component_Shift_Add_Load_MW[prj, tmp]
            >= mod.load_component_shift_min_load_mw_by_tmp[prj, tmp]
        )

    m.Load_Component_Shift_Min_Demand_Constraint = Constraint(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS, rule=min_demand_rule
    )

    def max_demand_rule(mod, prj, tmp):
        return (
            mod.Load_Component_Shift_Add_Load_MW[prj, tmp]
            <= mod.load_component_shift_max_load_mw_by_tmp[prj, tmp]
        )

    m.Load_Component_Shift_Max_Demand_Constraint = Constraint(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS, rule=max_demand_rule
    )

    def max_power_rule(mod, prj, tmp):
        return (
            mod.Load_Component_Shift_Add_Load_MW[prj, tmp]
            <= mod.Capacity_MW[prj, mod.period[tmp]]
        )

    m.Load_Component_Shift_Max_Power_Constraint = Constraint(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS, rule=max_power_rule
    )

    # TODO: remove this constraint once input validation is in place that
    #  does not allow specifying a reserve_zone for 'load_component_shift'
    #  type
    def no_upward_reserve_rule(mod, g, tmp):
        """
        **Constraint Name**: LoadComponentShift_No_Upward_Reserves_Constraint
        **Enforced Over**: LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS

        Upward reserves should be zero in every operational timepoint.
        """
        if getattr(d, headroom_variables)[g]:
            warnings.warn("""project {} is of the 'load_component_shift' operational 
                type and should not be assigned any upward reserve BAs since it 
                cannot provide  upward reserves. Please replace the upward 
                reserve BA for project {} with '.' (no value) in projects.tab. 
                Model will add  constraint to ensure project {} cannot provide 
                upward reserves
                """.format(g, g, g))
            return headroom_provision_rule(d, mod, g, tmp) == 0
        else:
            return Constraint.Skip

    m.LoadComponentShift_No_Upward_Reserves_Constraint = Constraint(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS, rule=no_upward_reserve_rule
    )

    # TODO: remove this constraint once input validation is in place that
    #  does not allow specifying a reserve_zone if 'load_component_shift' type
    def no_downward_reserve_rule(mod, g, tmp):
        """
        **Constraint Name**: LoadComponentShift_No_Downward_Reserves_Constraint
        **Enforced Over**: LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS

        Downward reserves should be zero in every operational timepoint.
        """
        if getattr(d, footroom_variables)[g]:
            warnings.warn("""project {} is of the 'load_component_shift' operational 
                type and should not be assigned any downward reserve BAs since 
                it cannot provide downward reserves. Please replace the
                downward reserve BA for project {} with '.' (no value) in 
                projects.tab. Model will add constraint to ensure project {} 
                cannot provide downward reserves.
                """.format(g, g, g))
            return footroom_provision_rule(d, mod, g, tmp) == 0
        else:
            return Constraint.Skip

    m.LoadComponentShift_No_Downward_Reserves_Constraint = Constraint(
        m.LOAD_COMPONENT_SHIFT_PRJS_OPR_TMPS, rule=no_downward_reserve_rule
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, prj, tmp):
    """
    Add static load to power production (remove from load) and subtract the
    shifted load (add to load).
    """

    return -mod.Load_Component_Shift_Add_Load_MW[prj, tmp] + (
        mod.component_static_load_mw[
            mod.load_zone[prj],
            tmp,
            mod.load_component_shift_linked_load_component[prj],
        ]
        * mod.Load_Component_Shift_Fraction_Invested[prj, mod.period[tmp]]
    )


def variable_om_cost_rule(mod, prj, tmp):
    """
    Must be defined rather than take the default, as Project_Power_Provision_MW
    for this operational type is negative downstream.
    """
    return (
        mod.Load_Component_Shift_Add_Load_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh[prj]
    )


def variable_om_by_period_cost_rule(mod, prj, tmp):
    """
    Must be defined rather than take the default, as Project_Power_Provision_MW
    for this operational type is negative downstream.
    """
    return (
        mod.Load_Component_Shift_Add_Load_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_period[prj, mod.period[tmp]]
    )


def variable_om_by_timepoint_cost_rule(mod, prj, tmp):
    """
    Must be defined rather than take the default, as Project_Power_Provision_MW
    for this operational type is negative downstream.
    """
    return (
        mod.Load_Component_Shift_Add_Load_MW[prj, tmp]
        * mod.variable_om_cost_per_mwh_by_timepoint[prj, tmp]
    )


def power_delta_rule(mod, prj, tmp):
    """
    This rule is only used in tuning costs, so fine to skip for linked
    horizon's first timepoint.
    """
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[prj]
    ) and (
        check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[prj],
            boundary_type="linear",
        )
        or check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[prj],
            boundary_type="linked",
        )
    ):
        pass
    else:
        return power_provision_rule(mod, prj, tmp) - power_provision_rule(
            mod, prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
        )


# Inputs-Outputs
###############################################################################


def load_model_data(
    mod,
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
    :param mod:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """

    # Load data from projects.tab and get the list of projects of this type
    projects = load_optype_model_data(
        mod=mod,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="load_component_shift",
    )

    # Load data
    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "load_component_shift_bounds.tab",
        ),
        index=mod.LOAD_COMPONENT_SHIFT_PRJS_BT_HRZS,
        param=(
            mod.load_component_shift_min_load_mw,
            mod.load_component_shift_max_load_mw,
        ),
    )


# Database
###############################################################################


def get_model_inputs_from_database(
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
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return: cursor object with query results
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

    prj_bt_hrz_data = get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=subscenarios,
        weather_iteration=db_weather_iteration,
        hydro_iteration=db_hydro_iteration,
        availability_iteration=db_availability_iteration,
        subproblem=db_subproblem,
        stage=db_stage,
        conn=conn,
        op_type="load_component_shift",
        table="inputs_project_load_component_shift_bounds",
        subscenario_id_column="load_component_shift_bounds_scenario_id",
        data_column="min_load_mw, max_load_mw",
        opr_index_dict=BT_HRZ_INDEX_QUERY_PARAMS,
        exclude_stage=True,
    )

    return prj_bt_hrz_data


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
    Get inputs from database and write out the model input
    variable_generator_profiles.tab file.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    data = get_model_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )
    fname = "load_component_shift_bounds.tab"

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname,
        data,
        replace_nulls=True,
    )


# Validation
###############################################################################


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
    Get inputs from database and validate the inputs
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    pass
