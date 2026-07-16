# Copyright 2016-2024 Blue Marble Analytics LLC.
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

from pyomo.environ import (
    Param,
    Set,
    NonNegativeReals,
    Reals,
    Expression,
    Var,
    Constraint,
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
)

# TODO: possibly add shaping capacity to this module


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
    | | :code:`ENERGY_PROFILE`                                                |
    |                                                                         |
    | The set of generators of the :code:`energy_profile` operational type.   |
    +-------------------------------------------------------------------------+
    | | :code:`ENERGY_PROFILE_OPR_TMPS`                                       |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`energy_profile`       |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`energy_profile_energy_fraction`                                |
    | | *Defined over*: :code:`ENERGY_PROFILE`                                |
    | | *Within*: :code:`Reals`                                               |
    |                                                                         |
    | The project's power output in each operational timepoint as a fraction  |
    | of its available capacity (i.e. the capacity factor).                   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | | :code:`EnergyProfile_No_Upward_Reserves_Constraint`                  |
    | | *Defined over*: :code:`ENERGY_PROFILE_OPR_TMPS`                    |
    |                                                                         |
    | Variable must-take generator projects cannot provide upward reserves.   |
    +-------------------------------------------------------------------------+
    | | :code:`EnergyProfile_No_Downward_Reserves_Constraint`                |
    | | *Defined over*: :code:`ENERGY_PROFILE_OPR_TMPS`                    |
    |                                                                         |
    | Variable must-take generator projects cannot provide downward reserves. |
    +-------------------------------------------------------------------------+


    """

    # Sets
    ###########################################################################

    m.ENERGY_PROFILE = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "energy_profile"
        ),
    )

    m.ENERGY_PROFILE_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.ENERGY_PROFILE,
        ),
    )

    m.ENERGY_PROFILE_OPR_PRDS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_PRDS",
            index=0,
            membership_set=mod.ENERGY_PROFILE,
        ),
    )

    # Required Params
    ###########################################################################

    m.energy_profile_energy_fraction = Param(m.ENERGY_PROFILE_OPR_TMPS, within=Reals)
    m.energy_profile_peak_deviation_demand_charge = Param(
        m.ENERGY_PROFILE, m.PERIODS, m.MONTHS, within=NonNegativeReals, default=0
    )

    # Variables
    m.EnergyProfile_Provide_Power_MW = Var(
        m.ENERGY_PROFILE_OPR_TMPS, within=NonNegativeReals
    )
    m.EnergyProfile_Peak_Deviation_in_Month = Var(
        m.ENERGY_PROFILE_OPR_PRDS,
        m.MONTHS,
        within=NonNegativeReals,
        initialize=0,
    )

    # Constraints
    ###########################################################################

    def provide_power_min_constraint_rule(mod, prj, tmp):
        return mod.EnergyProfile_Provide_Power_MW[prj, tmp] >= mod.Energy_MWh[
            prj, mod.period[tmp]
        ] * mod.energy_profile_energy_fraction[prj, tmp] / (
            mod.hrs_in_tmp[tmp] * mod.tmp_weight[tmp]
        )

    m.EnergyProfile_Provide_Power_Min_Constraint = Constraint(
        m.ENERGY_PROFILE_OPR_TMPS, rule=provide_power_min_constraint_rule
    )

    def provide_power_max_constraint_rule(mod, prj, tmp):
        return (
            mod.EnergyProfile_Provide_Power_MW[prj, tmp]
            <= mod.Energy_MWh[prj, mod.period[tmp]]
            * mod.energy_profile_energy_fraction[prj, tmp]
            / (mod.hrs_in_tmp[tmp] * mod.tmp_weight[tmp])
            + mod.shaping_capacity_mw[prj, mod.period[tmp]]
        )

    m.EnergyProfile_Provide_Power_Max_Constraint = Constraint(
        m.ENERGY_PROFILE_OPR_TMPS, rule=provide_power_max_constraint_rule
    )

    def monthly_peak_deviation_rule(mod, prj, tmp):
        if mod.energy_profile_peak_deviation_demand_charge == 0:
            return Constraint.Skip
        else:
            return mod.EnergyProfile_Peak_Deviation_in_Month[
                prj, mod.period[tmp], mod.month[tmp]
            ] >= (
                mod.EnergyProfile_Provide_Power_MW[prj, tmp]
                - sum(
                    mod.EnergyProfile_Provide_Power_MW[prj, _tmp]
                    * mod.hrs_in_tmp[_tmp]
                    * mod.tmp_weight[_tmp]
                    for _tmp in mod.TMPS_IN_PRD[mod.period[tmp]]
                    if mod.month[tmp] == mod.month[_tmp]
                )
                / sum(
                    mod.hrs_in_tmp[_tmp] * mod.tmp_weight[_tmp]
                    for _tmp in mod.TMPS_IN_PRD[mod.period[tmp]]
                    if mod.month[tmp] == mod.month[_tmp]
                )
            )

    m.EnergyProfile_Peak_Deviation_in_Month_Constraint = Constraint(
        m.ENERGY_PROFILE_OPR_TMPS, rule=monthly_peak_deviation_rule
    )

    # TODO: remove this constraint once input validation is in place that
    #  does not allow specifying a reserve_zone if 'energy_profile' type
    def no_upward_reserve_rule(mod, g, tmp):
        """
        **Constraint Name**: EnergyProfile_No_Upward_Reserves_Constraint
        **Enforced Over**: ENERGY_PROFILE_OPR_TMPS

        Upward reserves should be zero in every operational timepoint.
        """
        if getattr(d, headroom_variables)[g]:
            warnings.warn("""project {} is of the 'energy_profile' operational 
                type and should not be assigned any upward reserve BAs since it 
                cannot provide  upward reserves. Please replace the upward 
                reserve BA for project {} with '.' (no value) in projects.tab. 
                Model will add  constraint to ensure project {} cannot provide 
                upward reserves
                """.format(g, g, g))
            return headroom_provision_rule(d, mod, g, tmp) == 0
        else:
            return Constraint.Skip

    m.EnergyProfile_No_Upward_Reserves_Constraint = Constraint(
        m.ENERGY_PROFILE_OPR_TMPS, rule=no_upward_reserve_rule
    )

    # TODO: remove this constraint once input validation is in place that
    #  does not allow specifying a reserve_zone if 'energy_profile' type
    def no_downward_reserve_rule(mod, g, tmp):
        """
        **Constraint Name**: EnergyProfile_No_Downward_Reserves_Constraint
        **Enforced Over**: ENERGY_PROFILE_OPR_TMPS

        Downward reserves should be zero in every operational timepoint.
        """
        if getattr(d, footroom_variables)[g]:
            warnings.warn("""project {} is of the 'energy_profile' operational 
                type and should not be assigned any downward reserve BAs since 
                it cannot provide downward reserves. Please replace the
                downward reserve BA for project {} with '.' (no value) in 
                projects.tab. Model will add constraint to ensure project {} 
                cannot provide downward reserves.
                """.format(g, g, g))
            return footroom_provision_rule(d, mod, g, tmp) == 0
        else:
            return Constraint.Skip

    m.EnergyProfile_No_Downward_Reserves_Constraint = Constraint(
        m.ENERGY_PROFILE_OPR_TMPS, rule=no_downward_reserve_rule
    )


# Operational Type Methods
###############################################################################


def power_provision_rule(mod, prj, tmp):
    """
    Power provision from energy_profile generators is their total energy for
    the period times the energy profile fraction for the timepoint,
    and converted to power via the hours in timepoint and timepoint weight
    parameters.
    """

    return mod.EnergyProfile_Provide_Power_MW[prj, tmp]


def peak_deviation_monthly_demand_charge_cost_rule(mod, prj, prd, mnth):
    return (
        mod.EnergyProfile_Peak_Deviation_in_Month[prj, prd, mnth]
        * mod.energy_profile_peak_deviation_demand_charge[prj, prd, mnth]
    )


def power_delta_rule(mod, g, tmp):
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=mod.balancing_type_project[g]
    ) and (
        check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linear",
        )
        or check_boundary_type(
            mod=mod,
            tmp=tmp,
            balancing_type=mod.balancing_type_project[g],
            boundary_type="linked",
        )
    ):
        pass
    else:
        return (
            mod.Energy_MWh[g, mod.period[tmp]]
            * mod.energy_profile_energy_fraction[g, tmp]
            / (mod.hrs_in_tmp[tmp] * mod.tmp_weight[tmp])
        ) - (
            mod.Energy_MWh[
                g, mod.period[mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            ]
            * mod.energy_profile_energy_fraction[
                g, mod.prev_tmp[tmp, mod.balancing_type_project[g]]
            ]
            / (
                mod.hrs_in_tmp[mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
                * mod.tmp_weight[mod.prev_tmp[tmp, mod.balancing_type_project[g]]]
            )
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
        op_type="energy_profile",
    )

    load_var_profile_inputs(
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="energy_profile",
        tab_filename="energy_profiles.tab",
        param_name="energy_fraction",
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

    prj_tmp_data = get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=subscenarios,
        weather_iteration=db_weather_iteration,
        hydro_iteration=db_hydro_iteration,
        availability_iteration=db_availability_iteration,
        subproblem=db_subproblem,
        stage=db_stage,
        conn=conn,
        op_type="energy_profile",
        table="inputs_project_energy_profiles",
        subscenario_id_column="energy_profile_scenario_id",
        data_column="energy_fraction",
    )

    return prj_tmp_data


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
    fname = "energy_profiles.tab"

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        fname,
        data,
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

    # Validate operational chars table inputs
    opchar_df = validate_opchars(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "energy_profile",
    )

    # Validate energy profiles input table
    energy_fraction_validation_error = validate_var_profiles(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "energy_profile",
        table="inputs_project_energy_profiles",
        subscenario_id_column="energy_profile_scenario_id",
        data_column="energy_fraction",
    )

    # Other module specific validations

    # Check that the project does not show up in any of the
    # inputs_project_reserve_bas tables since energy_profile can't
    # provide any reserves
    projects_by_reserve = get_projects_by_reserve(scenario_id, subscenarios, conn)
    for reserve, projects_w_ba in projects_by_reserve.items():
        table = "inputs_project_" + reserve + "_bas"
        reserve_errors = validate_idxs(
            actual_idxs=opchar_df["project"],
            invalid_idxs=projects_w_ba,
            msg="energy_profile cannot provide {}.".format(reserve),
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
            db_table=table,
            severity="Mid",
            errors=reserve_errors,
        )
