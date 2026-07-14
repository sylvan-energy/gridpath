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

"""
This operational type shapes energy on a horizon basis based on a min, max,
average energy and its slice of the full potential of a project. It can only
be paired with the energy_new_lin capacity type and must have a potential
associated with it based on which the slice will be determined. Operating
cahractersitcs are based on the full potential. This type limits total energy
over the period to the Energy_MWh for the project.

"""

import csv
import os.path

import pandas as pd
from pyomo.environ import (
    Var,
    Set,
    Param,
    Constraint,
    Expression,
    NonNegativeReals,
    PercentFraction,
    value,
    NonNegativeReals,
)
import warnings

from gridpath.auxiliary.auxiliary import (
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.dynamic_components import headroom_variables, footroom_variables
from gridpath.project.common_functions import (
    check_if_boundary_type_and_first_timepoint,
    check_if_first_timepoint,
    check_boundary_type,
)
from gridpath.project.operations.operational_types.common_functions import (
    # get_monthly_avg_power_expression,  # for the commented-out peak-deviation constraint
    load_optype_model_data,
    load_hydro_opchars,
    write_tab_file_model_inputs,
    check_for_tmps_to_link,
    validate_opchars,
    validate_hydro_opchars,
    get_prj_temporal_index_opr_inputs_from_db,
    BT_HRZ_INDEX_QUERY_PARAMS,
)
from gridpath.common_functions import create_results_df


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
    | | :code:`ENERGY_SLICE_HRZ_SHAPING`                                           |
    |                                                                         |
    | The set of generators of the :code:`energy_slice_hrz_shaping` operational    |
    | type.                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS`                                  |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`energy_slice_hrz_shaping`  |
    | operational type and their operational horizons.                        |
    +-------------------------------------------------------------------------+
    | | :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_TMPS`                                  |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`energy_slice_hrz_shaping`  |
    | operational type and their operational timepoints.                      |
    +-------------------------------------------------------------------------+
    | | :code:`ENERGY_SLICE_HRZ_SHAPING_LINKED_TMPS`                               |
    |                                                                         |
    | Two-dimensional set with generators of the :code:`energy_slice_hrz_shaping`  |
    | operational type and their linked timepoints.                           |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`energy_slice_hrz_shaping_max_power`                                  |
    | | *Defined over*: :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS`                |
    | | *Within*: :code:`NonNegativeReals`                                               |
    |                                                                         |
    | The project's maximum power output in each operational horizon as a     |
    | fraction of its available capacity.                                     |
    +-------------------------------------------------------------------------+
    | | :code:`energy_slice_hrz_shaping_min_power`                                  |
    | | *Defined over*: :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS`                |
    | | *Within*: :code:`NonNegativeReals`                                               |
    |                                                                         |
    | The project's minimum power output in each operational horizon          |
    +-------------------------------------------------------------------------+
    | | :code:`energy_slice_hrz_shaping_hrz_energy`                              |
    | | *Defined over*: :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS`                |
    | | *Within*: :code:`NonNegativeReals`                                               |
    |                                                                         |
    | The project's avarage power output in each operational horizon.         |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Variables                                                               |
    +=========================================================================+
    | | :code:`EnergySliceHrzShaping_Provide_Power_MW`                                     |
    | | *Defined over*: :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_TMPS`                   |
    | | *Within*: :code:`NonNegativeReals`                                               |
    |                                                                         |
    | Power provision in MW from this project in each timepoint in which the  |
    | project is operational.                                                 |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Constraints                                                             |
    +=========================================================================+
    | Power                                                                   |
    +-------------------------------------------------------------------------+
    | | :code:`EnergySliceHrzShaping_Max_Power_Constraint`                         |
    | | *Defined over*: :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS`                |
    |                                                                         |
    | Limits power to :code:`energy_slice_hrz_shaping_max_power`.                   |
    +-------------------------------------------------------------------------+
    | | :code:`EnergySliceHrzShaping_Min_Power_Constraint`                         |
    | | *Defined over*: :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS`                |
    |                                                                         |
    | Power provision should exceed a certain level                           |
    | :code:`energy_slice_hrz_shaping_min_power`                                    |
    +-------------------------------------------------------------------------+
    | | :code:`EnergySliceHrzShaping_Energy_Budget_Constraint`                     |
    | | *Defined over*: :code:`ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS`                |
    |                                                                         |
    | The project's average power in each operational horizon, should match   |
    | the specified :code:`energy_slice_hrz_shaping_hrz_energy`.           |
    +-------------------------------------------------------------------------+

    """
    # Sets
    ###########################################################################

    m.ENERGY_SLICE_HRZ_SHAPING = Set(
        within=m.PROJECTS,
        initialize=lambda mod: subset_init_by_param_value(
            mod, "PROJECTS", "operational_type", "energy_slice_hrz_shaping"
        ),
    )

    m.ENERGY_SLICE_HRZ_SHAPING_OPR_PRDS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_PRDS",
            index=0,
            membership_set=mod.ENERGY_SLICE_HRZ_SHAPING,
        ),
    )

    m.ENERGY_SLICE_HRZ_SHAPING_OPR_TMPS = Set(
        dimen=2,
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.ENERGY_SLICE_HRZ_SHAPING,
        ),
    )

    # Note this is not derived from operational periods
    m.ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS = Set(dimen=3)

    m.ENERGY_SLICE_HRZ_SHAPING_LINKED_TMPS = Set(dimen=2)

    # Required Params
    ###########################################################################

    m.energy_slice_hrz_shaping_hrz_energy = Param(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS, within=NonNegativeReals
    )

    m.energy_slice_hrz_shaping_min_power = Param(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS, within=NonNegativeReals
    )

    m.energy_slice_hrz_shaping_max_power = Param(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS, within=NonNegativeReals
    )

    # NOTE: the peak-deviation demand charge feature is not wired up for this
    # operational type -- there is no tab-file or database load path for the
    # demand charge param, so it is always at its default of 0 and the
    # components below could never affect the model. They are commented out
    # until the input wiring is added; see energy_load_following for a fully
    # wired-up implementation of the same feature.
    # m.energy_slice_hrz_shaping_peak_deviation_demand_charge = Param(
    #     m.ENERGY_SLICE_HRZ_SHAPING,
    #     m.PERIODS,
    #     m.MONTHS,
    #     within=NonNegativeReals,
    #     default=0,
    # )

    # Expressions
    def slice_init(mod, prj, prd):
        if mod.max_total_energy[prj, prd] == float("inf"):
            raise ValueError(
                f"The 'energy_slice_hrz_shaping' operational "
                f"type requires that a potential be specified for "
                f"the project for the calculation of the slice. "
                f"Check project {prj}, period {prd} total energy "
                f"potential inputs."
            )
        return mod.Energy_MWh[prj, prd] / mod.max_total_energy[prj, prd]

    # TODO: export this value
    m.EnergySliceHrzShaping_Slice = Expression(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_PRDS, initialize=slice_init
    )

    # Variables
    ###########################################################################

    m.EnergySliceHrzShaping_Provide_Power_MW = Var(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_TMPS, within=NonNegativeReals
    )

    # m.EnergySliceHrzShaping_Peak_Deviation_in_Month = Var(
    #     m.ENERGY_SLICE_HRZ_SHAPING_OPR_PRDS,
    #     m.MONTHS,
    #     within=NonNegativeReals,
    #     initialize=0,
    # )

    # Constraints
    ###########################################################################

    def total_energy_constraint(mod, prj, prd):
        """
        This constraint is somewhat redundant, but here to prevent degeneracy
        issues when Energy_MWh does not have a cost associated it and could
        be set arbitrarily high.
        """
        return (
            sum(
                mod.EnergySliceHrzShaping_Provide_Power_MW[prj, tmp]
                * mod.hrs_in_tmp[tmp]
                * mod.tmp_weight[tmp]
                for tmp in mod.TMPS_IN_PRD[prd]
            )
            == mod.Energy_MWh[prj, prd]
        )

    m.EnergySliceHrzShaping_Total_Energy_in_Period_Constraint = Constraint(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_PRDS, rule=total_energy_constraint
    )

    def max_power_rule(mod, prj, tmp):
        """
        **Constraint Name**: EnergySliceHrzShaping_Max_Power_Constraint
        **Enforced Over**: ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS
        """
        return (
            mod.EnergySliceHrzShaping_Provide_Power_MW[prj, tmp]
            <= mod.EnergySliceHrzShaping_Slice[prj, mod.period[tmp]]
            * mod.energy_slice_hrz_shaping_max_power[
                prj,
                mod.balancing_type_project[prj],
                mod.horizon[tmp, mod.balancing_type_project[prj]],
            ]
        )

    def min_power_rule(mod, prj, tmp):
        """
        **Constraint Name**: EnergySliceHrzShaping_Min_Power_Constraint
        **Enforced Over**: ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS
        """
        return (
            mod.EnergySliceHrzShaping_Provide_Power_MW[prj, tmp]
            >= mod.EnergySliceHrzShaping_Slice[prj, mod.period[tmp]]
            * mod.energy_slice_hrz_shaping_min_power[
                prj,
                mod.balancing_type_project[prj],
                mod.horizon[tmp, mod.balancing_type_project[prj]],
            ]
        )

    def energy_budget_rule(mod, prj, bt, h):
        """
        **Constraint Name**: EnergySliceHrzShaping_Energy_Budget_Constraint
        **Enforced Over**: ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS
        """
        return (
            sum(
                mod.EnergySliceHrzShaping_Provide_Power_MW[prj, tmp]
                * mod.hrs_in_tmp[tmp]
                * mod.tmp_weight[tmp]
                for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
            )
            == mod.EnergySliceHrzShaping_Slice[prj, mod.hrz_period[bt, h]]
            * mod.energy_slice_hrz_shaping_hrz_energy[prj, bt, h]
        )

    m.EnergySliceHrzShaping_Max_Power_Constraint = Constraint(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_TMPS, rule=max_power_rule
    )

    m.EnergySliceHrzShaping_Min_Power_Constraint = Constraint(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_TMPS, rule=min_power_rule
    )

    m.EnergySliceHrzShaping_Energy_Budget_Constraint = Constraint(
        m.ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS, rule=energy_budget_rule
    )

    # Demand charge
    # def monthly_peak_deviation_rule(mod, prj, tmp):
    #     prd = mod.period[tmp]
    #     mnth = mod.month[tmp]
    #     if (
    #         mod.energy_slice_hrz_shaping_peak_deviation_demand_charge[prj, prd, mnth]
    #         == 0
    #     ):
    #         return Constraint.Skip
    #     else:
    #         return mod.EnergySliceHrzShaping_Peak_Deviation_in_Month[
    #             prj, prd, mnth
    #         ] >= (
    #             mod.EnergySliceHrzShaping_Provide_Power_MW[prj, tmp]
    #             - get_monthly_avg_power_expression(
    #                 mod, "EnergySliceHrzShaping_Provide_Power_MW", prj, prd, mnth
    #             )
    #         )
    #
    # m.EnergySliceHrzShaping_Peak_Deviation_in_Month_Constraint = Constraint(
    #     m.ENERGY_SLICE_HRZ_SHAPING_OPR_TMPS, rule=monthly_peak_deviation_rule
    # )


# Operational Type Methods
###############################################################################
def power_provision_rule(mod, prj, tmp):
    """
    Power provision from must-take hydro.
    """
    return mod.EnergySliceHrzShaping_Provide_Power_MW[prj, tmp]


# NOTE: the peak-deviation demand charge feature is not wired up for this
# operational type -- there is no tab-file or database load path for the
# demand charge param, so it is always at its default of 0 and the
# components below could never affect the model. They are commented out
# until the input wiring is added; see energy_load_following for a fully
# wired-up implementation of the same feature.
# def peak_deviation_monthly_demand_charge_cost_rule(mod, prj, prd, mnth):
#     return (
#         mod.EnergySliceHrzShaping_Peak_Deviation_in_Month[prj, prd, mnth]
#         * mod.energy_slice_hrz_shaping_peak_deviation_demand_charge[prj, prd, mnth]
#     )


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
        return (
            mod.EnergySliceHrzShaping_Provide_Power_MW[prj, tmp]
            - mod.EnergySliceHrzShaping_Provide_Power_MW[
                prj, mod.prev_tmp[tmp, mod.balancing_type_project[prj]]
            ]
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

    :param m:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """

    # Determine list of projects load params from projects.tab (if any)
    projects = load_optype_model_data(
        mod=m,
        data_portal=data_portal,
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        op_type="energy_slice_hrz_shaping",
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
            "energy_slice_hrz_shaping_params.tab",
        ),
        index=m.ENERGY_SLICE_HRZ_SHAPING_OPR_BT_HRZS,
        param=(
            m.energy_slice_hrz_shaping_hrz_energy,
            m.energy_slice_hrz_shaping_min_power,
            m.energy_slice_hrz_shaping_max_power,
        ),
    )

    # # Linked timepoint params
    # linked_inputs_filename = os.path.join(
    #     scenario_directory,
    #     subproblem,
    #     stage,
    #     "inputs",
    #     "energy_slice_hrz_shaping_linked_timepoint_params.tab",
    # )
    # if os.path.exists(linked_inputs_filename):
    #     data_portal.load(
    #         filename=linked_inputs_filename,
    #         index=m.ENERGY_SLICE_HRZ_SHAPING_LINKED_TMPS,
    #         param=(m.energy_slice_hrz_shaping_linked_power,),
    #     )


def export_results(
    mod,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param mod:
    :param d:
    :return:
    """

    # Dispatch results added to project_timepoint.csv via add_to_prj_tmp_results()

    # If there's a linked_subproblems_map CSV file, check which of the
    # current subproblem TMPS we should export results for to link to the
    # next subproblem
    tmps_to_link, tmp_linked_tmp_dict = check_for_tmps_to_link(
        scenario_directory=scenario_directory, subproblem=subproblem, stage=stage
    )

    # If the list of timepoints to link is not empty, write the linked
    # timepoint results for this module in the next subproblem's input
    # directory
    if tmps_to_link:
        next_subproblem = str(int(subproblem) + 1)

        # Export params by project and timepoint
        with open(
            os.path.join(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                next_subproblem,
                stage,
                "inputs",
                "energy_slice_hrz_shaping_linked_timepoint_params.tab",
            ),
            "w",
            newline="",
        ) as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(
                [
                    "project",
                    "linked_timepoint",
                    "linked_provide_power",
                ]
            )
            for p, tmp in sorted(mod.ENERGY_SLICE_HRZ_SHAPING_OPR_TMPS):
                if tmp in tmps_to_link:
                    writer.writerow(
                        [
                            p,
                            tmp_linked_tmp_dict[tmp],
                            max(
                                value(
                                    mod.EnergySliceHrzShaping_Provide_Power_MW[p, tmp]
                                ),
                                0,
                            ),
                        ]
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
        op_type="energy_slice_hrz_shaping",
        table="inputs_project_energy_slice_hrz_shaping",
        subscenario_id_column="energy_slice_hrz_shaping_scenario_id",
        data_column="hrz_energy, min_power, max_power",
        opr_index_dict=BT_HRZ_INDEX_QUERY_PARAMS,
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
    hydro_conventional_horizon_params.tab file.
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
    fname = "energy_slice_hrz_shaping_params.tab"

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
    validate_opchars(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
        "energy_slice_hrz_shaping",
    )
