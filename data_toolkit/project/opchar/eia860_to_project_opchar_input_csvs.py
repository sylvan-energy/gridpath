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


"""
Form EIA 860 Projects User-Defined Operating Characteristics
************************************************************

Create opchar CSV for a EIA860-based project portfolio. Note that most of
operating characteristics are user-defined in the
user_defined_eia_gridpath_key table and will take default values until more
detailed data are available.

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``, which also documents
    what the EIA860 data vintage in the raw database means — in
    particular that the latest available vintage (the convert step's
    default) is PUDL's EIA860M-derived reconstruction of the in-progress
    report year, not an as-filed annual survey.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_opchar_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_eia860_generators
    * user_defined_eia_gridpath_key

=========
Settings
=========
    * database
    * output_directory
    * study_year
    * footprint
    * include_retired
    * planned_inclusion
    * inactive_inclusion
    * include_planned_retirements
    * include_btm_plants
    * ba_source
    * load_zone_level
    * project_aggregation
    * aggregation_dimensions
    * project_operational_chars_scenario_id
    * project_operational_chars_scenario_name
    * project_fuel_scenario_id
    * variable_generator_profile_scenario_id
    * hydro_operational_chars_scenario_id

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from data_toolkit.project.fleet.fleet_filters import (
    VAR_GEN_FILTER_STR,
    HYDRO_FILTER_STR,
    FUEL_FILTER_STR,
    HEAT_RATE_FILTER_STR,
    STOR_FILTER_STR,
)
from data_toolkit.project.fleet.step_common import (
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    warn_on_fleet_data_gaps,
    add_shared_project_step_arguments,
)

# TODO: add var costs, startup and shutdown costs, and startup fuel use


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="../../open_data_raw.db")
    add_shared_project_step_arguments(parser=parser)
    parser.add_argument(
        "-o",
        "--output_directory",
        default="../../csvs_open_data/project/opchar",
    )
    parser.add_argument(
        "-opchar_id", "--project_operational_chars_scenario_id", default=1
    )
    parser.add_argument(
        "-opchar_name",
        "--project_operational_chars_scenario_name",
        default="wecc_plants_opchar",
    )
    parser.add_argument("-fuel_id", "--project_fuel_scenario_id", default=1)
    parser.add_argument("-hr_id", "--heat_rate_curves_scenario_id", default=1)
    parser.add_argument(
        "-var_id", "--variable_generator_profile_scenario_id", default=1
    )
    parser.add_argument("-hy_id", "--hydro_operational_chars_scenario_id", default=1)
    parser.add_argument(
        "-hydro_bt",
        "--hydro_balancing_type",
        default=None,
        help="Override balancing_type_project for hydro projects. "
        "If not specified, uses gridpath_balancing_type from the key table.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_project_opchar(
    conn,
    project_name_str,
    fleet_relation_sql,
    fuel_filter_str,
    heat_rate_filter_str,
    stor_filter_str,
    var_gen_filter_str,
    hydro_filter_str,
    csv_location,
    subscenario_id,
    subscenario_name,
    fuel_id,
    hr_id,
    var_id,
    hy_id,
    aggregate_projects=False,
    hydro_balancing_type=None,
):
    # Variable gen and hydro get different opchar columns (profile / hydro
    # opchar scenario IDs), so the query is a UNION of three branches split
    # by the operational-type filter strings

    non_var_opchars_str = make_opchar_sql_str(
        technology="gridpath_technology",
        operational_type="gridpath_operational_type",
        balancing_type_project="gridpath_balancing_type",
        variable_om_cost_per_mwh="default_variable_om_cost_per_mwh",
        project_fuel_scenario_id=f"""CASE WHEN {fuel_filter_str} THEN {fuel_id} ELSE 
        NULL END""",
        heat_rate_curves_scenario_id=f"""CASE WHEN {heat_rate_filter_str} 
        THEN {hr_id} ELSE NULL END""",
        min_stable_level_fraction=f"""CASE WHEN {heat_rate_filter_str} THEN min_load_fraction ELSE NULL END""",
        storage_efficiency=f"""CASE WHEN {stor_filter_str} THEN default_storage_efficiency ELSE NULL END""",
        charging_efficiency=f"""CASE WHEN {stor_filter_str} THEN default_charging_efficiency ELSE NULL END""",
        discharging_efficiency=f"""CASE WHEN {stor_filter_str} THEN 
        default_discharging_efficiency ELSE NULL END""",
    )

    var_opchars_str = make_opchar_sql_str(
        technology="gridpath_technology",
        operational_type="gridpath_operational_type",
        balancing_type_project="gridpath_balancing_type",
        variable_om_cost_per_mwh="default_variable_om_cost_per_mwh",
        variable_generator_profile_scenario_id=f"{var_id}",
    )

    hydro_bt_expr = (
        f"'{hydro_balancing_type}'"
        if hydro_balancing_type
        else "gridpath_balancing_type"
    )
    hydro_opchars_str = make_opchar_sql_str(
        technology="gridpath_technology",
        operational_type="gridpath_operational_type",
        balancing_type_project=hydro_bt_expr,
        variable_om_cost_per_mwh="default_variable_om_cost_per_mwh",
        hydro_operational_chars_scenario_id=f"{hy_id}",
    )

    group_by_sql = "GROUP BY project" if aggregate_projects else ""
    sql = f"""
     SELECT {project_name_str} AS project,
         {non_var_opchars_str}
     {fleet_relation_sql}
     AND NOT {var_gen_filter_str}
     AND NOT {hydro_filter_str}
     {group_by_sql}
     -- Variable gen (different opchar columns, e.g. the profile scenario)
     UNION
     SELECT {project_name_str} AS project,
         {var_opchars_str}
     {fleet_relation_sql}
     AND {var_gen_filter_str}
     {group_by_sql}
     -- Hydro (different opchar columns, e.g. the hydro opchar scenario)
     UNION
     SELECT {project_name_str} AS project,
         {hydro_opchars_str}
     {fleet_relation_sql}
     AND {hydro_filter_str}
     {group_by_sql}
     ;
     """

    df = pd.read_sql(sql, conn)

    # Enforce integer for ID columns
    # Can add column names to the list
    # Note that this must be 'Int64'
    df[["variable_generator_profile_scenario_id"]] = df[
        ["variable_generator_profile_scenario_id"]
    ].astype("Int64")

    df.to_csv(
        os.path.join(csv_location, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )


def make_opchar_sql_str(
    technology="NULL",
    operational_type="NULL",
    balancing_type_project="NULL",
    load_modifier_flag="NULL",
    distribution_loss_adjustment_factor="NULL",
    variable_om_cost_per_mwh="NULL",
    variable_om_cost_by_period_scenario_id="NULL",
    variable_om_cost_by_timepoint_scenario_id="NULL",
    variable_om_cost_by_timepoint_tmp_map_scenario_id="NULL",
    project_fuel_scenario_id="NULL",
    heat_rate_curves_scenario_id="NULL",
    variable_om_curves_scenario_id="NULL",
    startup_chars_scenario_id="NULL",
    min_stable_level_fraction="NULL",
    unit_size_mw="NULL",
    startup_cost_per_mw="NULL",
    shutdown_cost_per_mw="NULL",
    startup_fuel_mmbtu_per_mw="NULL",
    startup_plus_ramp_up_rate="NULL",
    shutdown_plus_ramp_down_rate="NULL",
    ramp_up_when_on_rate="NULL",
    ramp_up_when_on_rate_monthly_adjustment_scenario_id="NULL",
    ramp_down_when_on_rate="NULL",
    ramp_down_when_on_rate_monthly_adjustment_scenario_id="NULL",
    ramp_up_violation_penalty="NULL",
    ramp_down_violation_penalty="NULL",
    bt_hrz_ramp_up_rate_limit_scenario_id="NULL",
    bt_hrz_ramp_down_rate_limit_scenario_id="NULL",
    total_ramp_up_limit_scenario_id="NULL",
    total_ramp_down_limit_scenario_id="NULL",
    ramp_tuning_cost_per_mw="NULL",
    min_up_time_hours="NULL",
    min_up_time_violation_penalty="NULL",
    min_down_time_hours="NULL",
    min_down_time_violation_penalty="NULL",
    cycle_selection_scenario_id="NULL",
    supplemental_firing_scenario_id="NULL",
    allow_startup_shutdown_power="NULL",
    storage_efficiency="NULL",
    charging_efficiency="NULL",
    discharging_efficiency="NULL",
    charging_capacity_multiplier="NULL",
    discharging_capacity_multiplier="NULL",
    soc_penalty_cost_per_energyunit="NULL",
    soc_last_tmp_penalty_cost_per_energyunit="NULL",
    max_losses_in_hrz_frac_stor_energy_capacity="NULL",
    flex_load_static_profile_scenario_id="NULL",
    minimum_duration_hours="NULL",
    maximum_duration_hours="NULL",
    aux_consumption_frac_capacity="NULL",
    aux_consumption_frac_power="NULL",
    last_commitment_stage="NULL",
    n_startup_limit_scenario_id="NULL",
    variable_generator_profile_scenario_id="NULL",
    variable_generator_profile_tmp_map_scenario_id="NULL",
    cap_factor_default="NULL",
    curtailment_cost_scenario_id="NULL",
    hydro_operational_chars_scenario_id="NULL",
    hydro_operational_chars_hrz_map_scenario_id="NULL",
    hydro_budget_allocation_scenario_id="NULL",
    hydro_budget_allocation_hrz_map_scenario_id="NULL",
    energy_profile_scenario_id="NULL",
    energy_profile_tmp_map_scenario_id="NULL",
    energy_hrz_shaping_scenario_id="NULL",
    energy_hrz_shaping_hrz_map_scenario_id="NULL",
    energy_slice_hrz_shaping_scenario_id="NULL",
    energy_slice_hrz_shaping_hrz_map_scenario_id="NULL",
    base_net_requirement_scenario_id="NULL",
    peak_deviation_demand_charge_scenario_id="NULL",
    lf_reserves_up_derate="NULL",
    lf_reserves_down_derate="NULL",
    regulation_up_derate="NULL",
    regulation_down_derate="NULL",
    frequency_response_derate="NULL",
    spinning_reserves_derate="NULL",
    inertia_reserves_derate="NULL",
    lf_reserves_up_ramp_rate="NULL",
    lf_reserves_down_ramp_rate="NULL",
    regulation_up_ramp_rate="NULL",
    regulation_down_ramp_rate="NULL",
    frequency_response_ramp_rate="NULL",
    spinning_reserves_ramp_rate="NULL",
    inertia_constant_sec="NULL",
    powerunithour_per_fuelunit="NULL",
    cap_factor_limits_scenario_id="NULL",
    partial_availability_threshold="NULL",
    stor_exog_state_of_charge_scenario_id="NULL",
    stor_exog_state_of_charge_tmp_map_scenario_id="NULL",
    nonfuel_carbon_emissions_per_mwh="NULL",
    powerhouse="NULL",
    generator_efficiency="NULL",
    linked_load_component="NULL",
    load_modifier_profile_scenario_id="NULL",
    load_modifier_profile_tmp_map_scenario_id="NULL",
    load_component_shift_bounds_scenario_id="NULL",
    load_component_shift_bounds_hrz_map_scenario_id="NULL",
    efficiency_factor="NULL",
    energy_requirement_factor="NULL",
    losses_factor_in_energy_target="NULL",
    losses_factor_curtailment="NULL",
    upward_reserves_to_soc_depletion="NULL",
    reserves_setpoint_duration_hours="NULL",
    energy_budget_balancing_type="NULL",
):
    """ """

    opchar_sql_str = f"""
     {technology} AS technology,
     {operational_type} AS operational_type,
     {balancing_type_project} AS balancing_type_project,
     {load_modifier_flag} AS load_modifier_flag,
     {distribution_loss_adjustment_factor} AS distribution_loss_adjustment_factor,
     {variable_om_cost_per_mwh} AS variable_om_cost_per_mwh,
     {variable_om_cost_by_period_scenario_id} AS variable_om_cost_by_period_scenario_id,
     {variable_om_cost_by_timepoint_scenario_id} AS 
     variable_om_cost_by_timepoint_scenario_id,	
     {variable_om_cost_by_timepoint_tmp_map_scenario_id} AS variable_om_cost_by_timepoint_tmp_map_scenario_id,
     {project_fuel_scenario_id} AS project_fuel_scenario_id,
     {heat_rate_curves_scenario_id} AS heat_rate_curves_scenario_id,	
     {variable_om_curves_scenario_id} AS variable_om_curves_scenario_id,
     {startup_chars_scenario_id} AS startup_chars_scenario_id,	
     {min_stable_level_fraction} AS min_stable_level_fraction,
     {unit_size_mw} AS unit_size_mw,
     {startup_cost_per_mw} AS startup_cost_per_mw,	
     {shutdown_cost_per_mw} AS shutdown_cost_per_mw,
     {startup_fuel_mmbtu_per_mw} AS startup_fuel_mmbtu_per_mw,	
     {startup_plus_ramp_up_rate} AS startup_plus_ramp_up_rate,
     {shutdown_plus_ramp_down_rate} AS shutdown_plus_ramp_down_rate,
     {ramp_up_when_on_rate} AS ramp_up_when_on_rate,
     {ramp_up_when_on_rate_monthly_adjustment_scenario_id} AS 
     ramp_up_when_on_rate_monthly_adjustment_scenario_id,
     {ramp_down_when_on_rate} AS ramp_down_when_on_rate,
      {ramp_down_when_on_rate_monthly_adjustment_scenario_id} AS 
     ramp_down_when_on_rate_monthly_adjustment_scenario_id,		
     {ramp_up_violation_penalty} AS ramp_up_violation_penalty,
     {ramp_down_violation_penalty} AS ramp_down_violation_penalty,
     {bt_hrz_ramp_up_rate_limit_scenario_id} AS 
     bt_hrz_ramp_up_rate_limit_scenario_id,
     {bt_hrz_ramp_down_rate_limit_scenario_id} AS 
     bt_hrz_ramp_down_rate_limit_scenario_id,
     {total_ramp_up_limit_scenario_id} AS total_ramp_up_limit_scenario_id,
     {total_ramp_down_limit_scenario_id} AS total_ramp_down_limit_scenario_id,
     {ramp_tuning_cost_per_mw} AS ramp_tuning_cost_per_mw,
     {min_up_time_hours} AS min_up_time_hours,
     {min_up_time_violation_penalty} AS min_up_time_violation_penalty,	
     {min_down_time_hours} AS min_down_time_hours,
     {min_down_time_violation_penalty} AS min_down_time_violation_penalty,	
     {cycle_selection_scenario_id} AS cycle_selection_scenario_id,
     {supplemental_firing_scenario_id} AS supplemental_firing_scenario_id,	
     {allow_startup_shutdown_power} AS allow_startup_shutdown_power,
     {storage_efficiency} AS storage_efficiency,	
     {charging_efficiency} AS charging_efficiency,
     {discharging_efficiency} AS discharging_efficiency,	
     {charging_capacity_multiplier} AS charging_capacity_multiplier,
     {discharging_capacity_multiplier} AS discharging_capacity_multiplier,	
     {soc_penalty_cost_per_energyunit} AS soc_penalty_cost_per_energyunit,
     {soc_last_tmp_penalty_cost_per_energyunit} AS soc_last_tmp_penalty_cost_per_energyunit,
     {max_losses_in_hrz_frac_stor_energy_capacity} AS 
     max_losses_in_hrz_frac_stor_energy_capacity,
     {flex_load_static_profile_scenario_id} AS flex_load_static_profile_scenario_id,
     {minimum_duration_hours} AS minimum_duration_hours,	
     {maximum_duration_hours} AS maximum_duration_hours,
     {aux_consumption_frac_capacity} AS aux_consumption_frac_capacity,	
     {aux_consumption_frac_power} AS aux_consumption_frac_power,
     {last_commitment_stage} AS last_commitment_stage,
     {n_startup_limit_scenario_id} AS n_startup_limit_scenario_id,
     {variable_generator_profile_scenario_id} AS variable_generator_profile_scenario_id,
     {variable_generator_profile_tmp_map_scenario_id} AS variable_generator_profile_tmp_map_scenario_id,
     {cap_factor_default} AS cap_factor_default,
     {curtailment_cost_scenario_id} AS curtailment_cost_scenario_id,	
     {hydro_operational_chars_scenario_id} AS hydro_operational_chars_scenario_id,
     {hydro_operational_chars_hrz_map_scenario_id} AS hydro_operational_chars_hrz_map_scenario_id,
     {hydro_budget_allocation_scenario_id} AS hydro_budget_allocation_scenario_id,
     {hydro_budget_allocation_hrz_map_scenario_id} AS hydro_budget_allocation_hrz_map_scenario_id,
     {energy_profile_scenario_id} AS "energy_profile_scenario_id",
     {energy_profile_tmp_map_scenario_id} AS energy_profile_tmp_map_scenario_id,
     {energy_hrz_shaping_scenario_id} AS "energy_hrz_shaping_scenario_id",
     {energy_hrz_shaping_hrz_map_scenario_id} AS energy_hrz_shaping_hrz_map_scenario_id,
     {energy_slice_hrz_shaping_scenario_id} AS 
     "energy_slice_hrz_shaping_scenario_id",
     {energy_slice_hrz_shaping_hrz_map_scenario_id} AS energy_slice_hrz_shaping_hrz_map_scenario_id,
     {base_net_requirement_scenario_id} AS "base_net_requirement_scenario_id",
     {peak_deviation_demand_charge_scenario_id} AS 
     "peak_deviation_demand_charge_scenario_id",
     {lf_reserves_up_derate} AS lf_reserves_up_derate,	
     {lf_reserves_down_derate} AS lf_reserves_down_derate,
     {regulation_up_derate} AS regulation_up_derate,	
     {regulation_down_derate} AS regulation_down_derate,
     {frequency_response_derate} AS frequency_response_derate,	
     {spinning_reserves_derate} AS spinning_reserves_derate,
     {inertia_reserves_derate} AS inertia_reserves_derate,
     {lf_reserves_up_ramp_rate} AS lf_reserves_up_ramp_rate,	
     {lf_reserves_down_ramp_rate} AS lf_reserves_down_ramp_rate,
     {regulation_up_ramp_rate} AS regulation_up_ramp_rate,
     {regulation_down_ramp_rate} AS regulation_down_ramp_rate,
     {frequency_response_ramp_rate} AS frequency_response_ramp_rate,
     {spinning_reserves_ramp_rate} AS spinning_reserves_ramp_rate,
     {inertia_constant_sec} AS inertia_constant_sec,
     {powerunithour_per_fuelunit} AS powerunithour_per_fuelunit,
     {cap_factor_limits_scenario_id} AS cap_factor_limits_scenario_id,
     {partial_availability_threshold} AS partial_availability_threshold,
     {stor_exog_state_of_charge_scenario_id} AS stor_exog_state_of_charge_scenario_id,
     {stor_exog_state_of_charge_tmp_map_scenario_id} AS stor_exog_state_of_charge_tmp_map_scenario_id,
     {nonfuel_carbon_emissions_per_mwh} AS nonfuel_carbon_emissions_per_mwh,
     {powerhouse} AS powerhouse,
     {generator_efficiency} AS generator_efficiency,
     {linked_load_component} AS linked_load_component,
     {load_modifier_profile_scenario_id} AS load_modifier_profile_scenario_id,
     {load_modifier_profile_tmp_map_scenario_id} AS load_modifier_profile_tmp_map_scenario_id,
     {load_component_shift_bounds_scenario_id} AS 
     load_component_shift_bounds_scenario_id,
     {load_component_shift_bounds_hrz_map_scenario_id} AS load_component_shift_bounds_hrz_map_scenario_id,
     {efficiency_factor} AS efficiency_factor,
     {energy_requirement_factor} AS energy_requirement_factor,
     {losses_factor_in_energy_target} AS losses_factor_in_energy_target,
     {losses_factor_curtailment} AS losses_factor_curtailment,
     {upward_reserves_to_soc_depletion} AS upward_reserves_to_soc_depletion,
     {reserves_setpoint_duration_hours} AS reserves_setpoint_duration_hours,
     {energy_budget_balancing_type} AS energy_budget_balancing_type
    """

    return opchar_sql_str


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project opchar inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    get_project_opchar(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        fuel_filter_str=FUEL_FILTER_STR,
        heat_rate_filter_str=HEAT_RATE_FILTER_STR,
        stor_filter_str=STOR_FILTER_STR,
        var_gen_filter_str=VAR_GEN_FILTER_STR,
        hydro_filter_str=HYDRO_FILTER_STR,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_operational_chars_scenario_id,
        subscenario_name=parsed_args.project_operational_chars_scenario_name,
        fuel_id=parsed_args.project_fuel_scenario_id,
        hr_id=parsed_args.heat_rate_curves_scenario_id,
        var_id=parsed_args.variable_generator_profile_scenario_id,
        hy_id=parsed_args.hydro_operational_chars_scenario_id,
        aggregate_projects=parsed_args.project_aggregation != "none",
        hydro_balancing_type=parsed_args.hydro_balancing_type,
    )

    conn.close()


if __name__ == "__main__":
    main()
