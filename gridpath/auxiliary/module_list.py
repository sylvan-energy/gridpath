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
This module contains:

1) the list of all GridPath modules;
2) the modules included in each optional feature;
3) the 'cross-feature' modules;
4) the method for determining the user-requested features for the scenarios;
5) the method for loading modules.
"""

from importlib import import_module
import os.path
import pandas as pd
import sys
import traceback

from gridpath.auxiliary.auxiliary import check_for_integer_subdirectories


def all_modules_list():
    """
    :return: list of all GridPath modules in order they are loaded

    This is the list of all GridPath modules in the order they would be
    loaded if all optional features were selected.
    """
    all_modules = [
        "temporal.operations.timepoints",
        "temporal.investment.periods",
        "temporal.operations.horizons",
        "temporal.investment.superperiods",
        "temporal.finalize",
        "geography.load_zones",
        "geography.load_following_up_balancing_areas",
        "geography.load_following_down_balancing_areas",
        "geography.regulation_up_balancing_areas",
        "geography.regulation_down_balancing_areas",
        "geography.frequency_response_balancing_areas",
        "geography.spinning_reserves_balancing_areas",
        "geography.inertia_reserves_balancing_areas",
        "geography.energy_target_zones",
        "geography.instantaneous_penetration_zones",
        "geography.transmission_target_zones",
        "geography.carbon_cap_zones",
        "geography.carbon_tax_zones",
        "geography.performance_standard_zones",
        "geography.carbon_credits_zones",
        "geography.fuel_burn_limit_balancing_areas",
        "geography.generic_policy",
        "geography.prm_zones",
        "geography.local_capacity_zones",
        "geography.markets",
        "geography.water_network",
        "system.markets.prices",
        "system.water.water_system_params",
        "system.water.water_nodes",
        "system.water.water_flows",
        "system.water.water_node_inflows_outflows",
        "system.water.reservoirs",
        "system.water.water_node_balance",
        "system.water.powerhouses",
        "system.load_balance",
        "system.load_balance.static_load_requirement",
        "project",
        "project.capacity",
        "project.capacity.capacity_types",
        "project.capacity.capacity",
        "project.capacity.potential",
        "project.capacity.capacity_groups",
        "project.capacity.relative_capacity",
        "project.capacity.costs",
        "project.availability.availability",
        "project.fuels",
        "project.operations",
        "project.operations.reserves.lf_reserves_up",
        "project.operations.reserves.lf_reserves_down",
        "project.operations.reserves.regulation_up",
        "project.operations.reserves.regulation_down",
        "project.operations.reserves.frequency_response",
        "project.operations.reserves.spinning_reserves",
        "project.operations.reserves.inertia_reserves",
        "project.operations.operational_types",
        "project.operations.reserves.op_type_dependent.lf_reserves_up",
        "project.operations.reserves.op_type_dependent.lf_reserves_down",
        "project.operations.reserves.op_type_dependent.regulation_up",
        "project.operations.reserves.op_type_dependent.regulation_down",
        "project.operations.reserves.op_type_dependent.frequency_response",
        "project.operations.reserves.op_type_dependent.spinning_reserves",
        "project.operations.reserves.op_type_dependent.inertia_reserves",
        "project.operations.power",
        "project.operations.cycle_select",
        "project.operations.supplemental_firing",
        "project.operations.cap_factor_limits",
        "project.operations.fix_commitment",
        "project.operations.fuel_burn",
        "project.operations.costs",
        "project.operations.tuning_costs",
        "project.operations.energy_target_contributions",
        "project.operations.instantaneous_penetration_contributions",
        "project.operations.carbon_emissions",
        "project.operations.carbon_cap",
        "project.operations.carbon_tax",
        "project.operations.performance_standard",
        "project.operations.carbon_credits",
        "project.operations.power_output_groups",
        "project.reliability.prm",
        "project.reliability.prm.prm_types",
        "project.reliability.prm.prm_simple",
        "project.reliability.prm.elcc_surface",
        "project.reliability.prm.group_costs",
        "project.reliability.local_capacity",
        "project.reliability.local_capacity.local_capacity_contribution",
        "project.consolidate_results",
        "project.summary_results",
        "transmission",
        "transmission.capacity",
        "transmission.capacity.capacity_types",
        "transmission.capacity.capacity",
        "transmission.capacity.costs",
        "transmission.capacity.consolidate_results",
        "transmission.capacity.capacity_groups",
        "transmission.availability.availability",
        "transmission.operations",
        "transmission.operations.operational_types",
        "transmission.operations.operations",
        "transmission.operations.transmission_flow_limits",
        "transmission.operations.consolidate_results",
        "transmission.operations.hurdle_costs",
        "transmission.operations.hurdle_costs_by_timepoint",
        "transmission.operations.simultaneous_flow_limits",
        "transmission.operations.carbon_emissions",
        "transmission.reliability.capacity_transfer_links",
        "transmission.operations.transmission_target_contributions",
        "system.load_balance.aggregate_project_power",
        "system.load_balance.aggregate_load_modifier_power",
        "system.load_balance.load_following",
        "system.load_balance.aggregate_transmission_power",
        "transmission.operations.tx_tuning_costs",
        "transmission.operations.tx_curtailment_costs",
        "system.markets.market_participation",
        "system.markets.fix_market_participation",
        "system.load_balance.aggregate_market_participation",
        "system.load_balance.load_balance",
        "system.load_balance.consolidate_results",
        "system.policy.energy_targets",
        "system.policy.energy_targets.period_energy_target",
        "system.policy.energy_targets.horizon_energy_target",
        "system.policy.instantaneous_penetration",
        "system.policy.transmission_targets",
        "system.policy.transmission_targets.transmission_target",
        "system.policy.carbon_cap",
        "system.policy.carbon_cap.carbon_cap",
        "system.policy.carbon_tax",
        "system.policy.carbon_tax.carbon_tax",
        "system.policy.performance_standard",
        "system.policy.performance_standard.performance_standard",
        "system.policy.fuel_burn_limits",
        "system.policy.fuel_burn_limits.fuel_burn_limits",
        "system.policy.generic_policy",
        "system.policy.generic_policy.generic_policy_requirements",
        "project.policy.policy_contribution",
        "system.reliability.prm",
        "system.reliability.prm.prm_requirement",
        "system.reliability.local_capacity",
        "system.reliability.local_capacity.local_capacity_requirement",
        "system.reserves.requirement.lf_reserves_up",
        "system.reserves.requirement.lf_reserves_down",
        "system.reserves.requirement.regulation_up",
        "system.reserves.requirement.regulation_down",
        "system.reserves.requirement.frequency_response",
        "system.reserves.requirement.spinning_reserves",
        "system.reserves.requirement.inertia_reserves",
        "system.policy.instantaneous_penetration.instantaneous_penetration_requirements",
        "system.reserves.aggregation.lf_reserves_up",
        "system.reserves.aggregation.regulation_up",
        "system.reserves.aggregation.lf_reserves_down",
        "system.reserves.aggregation.regulation_down",
        "system.reserves.aggregation.frequency_response",
        "system.reserves.aggregation.spinning_reserves",
        "system.reserves.aggregation.inertia_reserves",
        "system.reserves.balance.lf_reserves_up",
        "system.reserves.balance.regulation_up",
        "system.reserves.balance.lf_reserves_down",
        "system.reserves.balance.regulation_down",
        "system.reserves.balance.frequency_response",
        "system.reserves.balance.spinning_reserves",
        "system.reserves.balance.inertia_reserves",
        "system.policy.energy_targets.aggregate_period_energy_target_contributions",
        "system.policy.energy_targets.aggregate_horizon_energy_target_contributions",
        "system.policy.energy_targets.period_energy_target_balance",
        "system.policy.energy_targets.horizon_energy_target_balance",
        "system.policy.energy_targets.consolidate_results",
        "system.policy.instantaneous_penetration.instantaneous_penetration_aggregation",
        "system.policy.instantaneous_penetration.instantaneous_penetration_balance",
        "system.policy.transmission_targets"
        ".aggregate_transmission_target_contributions",
        "system.policy.transmission_targets.transmission_target_balance",
        "system.policy.transmission_targets.consolidate_results",
        "system.policy.carbon_cap.aggregate_project_carbon_emissions",
        "system.policy.carbon_cap.aggregate_project_carbon_credits",
        "system.policy.carbon_cap.aggregate_transmission_carbon_emissions",
        "system.policy.carbon_cap.carbon_balance",
        "system.policy.carbon_cap.consolidate_results",
        "system.policy.carbon_tax.aggregate_project_carbon_emissions",
        "system.policy.carbon_tax.aggregate_project_carbon_credits",
        "system.policy.carbon_tax.carbon_tax_costs",
        "system.policy.carbon_tax.consolidate_results",
        "system.policy.subsidies",
        "system.policy.performance_standard.aggregate_project_performance_standard",
        "system.policy.performance_standard.aggregate_project_carbon_credits",
        "system.policy.performance_standard.performance_standard_balance",
        "system.policy.performance_standard.consolidate_results",
        "system.policy.carbon_credits",
        "system.policy.carbon_credits.aggregate_project_carbon_credits",
        "system.policy.carbon_credits.sell_and_buy_credits",
        "system.policy.carbon_credits.carbon_credits_balance",
        "system.policy.carbon_credits.consolidate_results",
        "system.policy.fuel_burn_limits.aggregate_project_fuel_burn",
        "system.policy.fuel_burn_limits.fuel_burn_limit_balance",
        "system.policy.fuel_burn_limits.consolidate_results",
        "system.policy.generic_policy.aggregate_project_policy_contributions",
        "system.policy.generic_policy.policy_target_balance",
        "system.policy.generic_policy.consolidate_results",
        "system.reliability.prm.aggregate_project_simple_prm_contribution",
        "system.reliability.prm.capacity_contribution_transfers",
        "system.reliability.prm.elcc_surface",
        "system.reliability.prm.prm_balance",
        "system.reliability.prm.consolidate_results",
        "system.reliability.local_capacity.aggregate_local_capacity_contribution",
        "system.reliability.local_capacity.local_capacity_balance",
        "system.reliability.local_capacity.consolidate_results",
        "system.markets.volume",
        "objective.project.aggregate_capacity_costs",
        "objective.project.aggregate_prm_group_costs",
        "objective.project.aggregate_operational_costs",
        "objective.project.aggregate_operational_tuning_costs",
        "objective.transmission.aggregate_capacity_costs",
        "objective.transmission.aggregate_hurdle_costs",
        "objective.transmission.aggregate_tx_tuning_costs",
        "objective.transmission.aggregate_tx_curtailment_costs",
        "objective.system.aggregate_load_balance_penalties",
        "objective.system.reserve_violation_penalties.lf_reserves_up",
        "objective.system.reserve_violation_penalties.lf_reserves_down",
        "objective.system.reserve_violation_penalties.regulation_up",
        "objective.system.reserve_violation_penalties.regulation_down",
        "objective.system.reserve_violation_penalties.frequency_response",
        "objective.system.reserve_violation_penalties.spinning_reserves",
        "objective.system.reserve_violation_penalties.inertia_reserves",
        "objective.system.policy.aggregate_period_energy_target_violation_penalties",
        "objective.system.policy"
        ".aggregate_horizon_energy_target_violation_penalties",
        "objective.system.policy.aggregate_transmission_target_violation_penalties",
        "objective.system.policy.aggregate_instantaneous_penetration_violation_penalties",
        "objective.system.policy.aggregate_carbon_cap_violation_penalties",
        "objective.system.policy.aggregate_carbon_tax_costs",
        "objective.system.policy.aggregate_performance_standard_violation_penalties",
        "objective.system.policy.aggregate_fuel_burn_limit_violation_penalties",
        "objective.system.policy.aggregate_policy_target_violation_penalties",
        "objective.system.policy.aggregate_subsidies",
        "objective.system.policy.aggregate_carbon_credit_sales_and_purchases",
        "objective.system.reliability.prm.aggregate_capacity_transfer_costs",
        "objective.system.reliability.prm.aggregate_prm_violation_penalties",
        "objective.system.reliability.local_capacity"
        ".aggregate_local_capacity_violation_penalties",
        "objective.system.aggregate_market_revenue_and_costs",
        "objective.system.water.aggregate_reservoir_violation_penalty_costs",
        "objective.system.water.aggregate_flow_violation_penalty_costs",
        "objective.max_npv",
    ]
    return all_modules


def optional_modules_list():
    """
    :return: dictionary with the optional feature names as keys and a list
        of the modules included in each feature as values

    These are all of GridPath's optional modules grouped by features (features
    as the dictionary keys). Each of these modules belongs to only one feature.
    """
    optional_modules = {
        "transmission": [
            "transmission",
            "transmission.capacity",
            "transmission.capacity.capacity_types",
            "transmission.capacity.capacity",
            "transmission.capacity.costs",
            "transmission.capacity.consolidate_results",
            "transmission.capacity.capacity_groups",
            "transmission.availability.availability",
            "transmission.operations",
            "transmission.operations.operational_types",
            "transmission.operations.operations",
            "transmission.operations.transmission_flow_limits",
            "transmission.operations.consolidate_results",
            "system.load_balance.aggregate_transmission_power",
            "transmission.operations.tx_tuning_costs",
            "transmission.operations.tx_curtailment_costs",
            "objective.transmission.aggregate_capacity_costs",
            "objective.transmission.aggregate_tx_tuning_costs",
            "objective.transmission.aggregate_tx_curtailment_costs",
        ],
        "lf_reserves_up": [
            "geography.load_following_up_balancing_areas",
            "system.reserves.requirement.lf_reserves_up",
            "project.operations.reserves.lf_reserves_up",
            "project.operations.reserves.op_type_dependent.lf_reserves_up",
            "system.reserves.aggregation.lf_reserves_up",
            "system.reserves.balance.lf_reserves_up",
            "objective.system.reserve_violation_penalties.lf_reserves_up",
        ],
        "lf_reserves_down": [
            "geography.load_following_down_balancing_areas",
            "system.reserves.requirement.lf_reserves_down",
            "project.operations.reserves.lf_reserves_down",
            "project.operations.reserves.op_type_dependent.lf_reserves_down",
            "system.reserves.aggregation.lf_reserves_down",
            "system.reserves.balance.lf_reserves_down",
            "objective.system.reserve_violation_penalties.lf_reserves_down",
        ],
        "regulation_up": [
            "geography.regulation_up_balancing_areas",
            "system.reserves.requirement.regulation_up",
            "project.operations.reserves.regulation_up",
            "project.operations.reserves.op_type_dependent.regulation_up",
            "system.reserves.aggregation.regulation_up",
            "system.reserves.balance.regulation_up",
            "objective.system.reserve_violation_penalties.regulation_up",
        ],
        "regulation_down": [
            "geography.regulation_down_balancing_areas",
            "system.reserves.requirement.regulation_down",
            "project.operations.reserves.regulation_down",
            "system.reserves.aggregation.regulation_down",
            "project.operations.reserves.op_type_dependent.regulation_down",
            "system.reserves.balance.regulation_down",
            "objective.system.reserve_violation_penalties.regulation_down",
        ],
        "frequency_response": [
            "geography.frequency_response_balancing_areas",
            "system.reserves.requirement.frequency_response",
            "project.operations.reserves.frequency_response",
            "project.operations.reserves.op_type_dependent." "frequency_response",
            "system.reserves.aggregation.frequency_response",
            "system.reserves.balance.frequency_response",
            "objective.system.reserve_violation_penalties.frequency_response",
        ],
        "spinning_reserves": [
            "geography.spinning_reserves_balancing_areas",
            "system.reserves.requirement.spinning_reserves",
            "project.operations.reserves.spinning_reserves",
            "project.operations.reserves.op_type_dependent.spinning_reserves",
            "system.reserves.aggregation.spinning_reserves",
            "system.reserves.balance.spinning_reserves",
            "objective.system.reserve_violation_penalties.spinning_reserves",
        ],
        "inertia_reserves": [
            "geography.inertia_reserves_balancing_areas",
            "system.reserves.requirement.inertia_reserves",
            "project.operations.reserves.inertia_reserves",
            "project.operations.reserves.op_type_dependent.inertia_reserves",
            "system.reserves.aggregation.inertia_reserves",
            "system.reserves.balance.inertia_reserves",
            "objective.system.reserve_violation_penalties.inertia_reserves",
        ],
        "period_energy_target": [
            "system.policy.energy_targets.period_energy_target",
            "system.policy.energy_targets"
            ".aggregate_period_energy_target_contributions",
            "system.policy.energy_targets.period_energy_target_balance",
            "objective.system.policy"
            ".aggregate_period_energy_target_violation_penalties",
        ],
        "horizon_energy_target": [
            "system.policy.energy_targets.horizon_energy_target",
            "system.policy.energy_targets"
            ".aggregate_horizon_energy_target_contributions",
            "system.policy.energy_targets.horizon_energy_target_balance",
            "objective.system.policy"
            ".aggregate_horizon_energy_target_violation_penalties",
        ],
        "instantaneous_penetration": [
            "geography.instantaneous_penetration_zones",
            "system.policy.instantaneous_penetration.instantaneous_penetration_requirements",
            "project.operations.instantaneous_penetration_contributions",
            "system.policy.instantaneous_penetration.instantaneous_penetration_aggregation",
            "system.policy.instantaneous_penetration.instantaneous_penetration_balance",
            "objective.system.policy.aggregate_instantaneous_penetration_violation_penalties",
        ],
        "transmission_target": [
            "system.policy.transmission_targets.transmission_target",
            "system.policy.transmission_targets",
            "system.policy.transmission_targets"
            ".aggregate_transmission_target_contributions",
            "system.policy.transmission_targets.transmission_target_balance",
            "system.policy.transmission_targets.consolidate_results",
            "objective.system.policy"
            ".aggregate_transmission_target_violation_penalties",
        ],
        "carbon_cap": [
            "geography.carbon_cap_zones",
            "system.policy.carbon_cap",
            "system.policy.carbon_cap.carbon_cap",
            "project.operations.carbon_cap",
            "system.policy.carbon_cap.aggregate_project_carbon_emissions",
            "system.policy.carbon_cap.carbon_balance",
            "objective.system.policy.aggregate_carbon_cap_violation_penalties",
            "system.policy.carbon_cap.consolidate_results",
        ],
        "carbon_tax": [
            "geography.carbon_tax_zones",
            "system.policy.carbon_tax",
            "system.policy.carbon_tax.carbon_tax",
            "project.operations.carbon_tax",
            "system.policy.carbon_tax.aggregate_project_carbon_emissions",
            "system.policy.carbon_tax.carbon_tax_costs",
            "system.policy.carbon_tax.consolidate_results",
            "objective.system.policy.aggregate_carbon_tax_costs",
        ],
        "performance_standard": [
            "geography.performance_standard_zones",
            "system.policy.performance_standard",
            "system.policy.performance_standard.performance_standard",
            "project.operations.performance_standard",
            "system.policy.performance_standard.aggregate_project_performance_standard",
            "system.policy.performance_standard.performance_standard_balance",
            "system.policy.performance_standard.consolidate_results",
            "objective.system.policy.aggregate_performance_standard_violation_penalties",
        ],
        "carbon_credits": [
            "geography.carbon_credits_zones",
            "project.operations.carbon_credits",
            "system.policy.carbon_credits",
            "system.policy.carbon_credits.aggregate_project_carbon_credits",
            "system.policy.carbon_credits.sell_and_buy_credits",
            "system.policy.carbon_credits.carbon_credits_balance",
            "system.policy.carbon_credits.consolidate_results",
            "objective.system.policy.aggregate_carbon_credit_sales_and_purchases",
        ],
        "fuel_burn_limit": [
            "geography.fuel_burn_limit_balancing_areas",
            "system.policy.fuel_burn_limits",
            "system.policy.fuel_burn_limits.fuel_burn_limits",
            "system.policy.fuel_burn_limits.aggregate_project_fuel_burn",
            "system.policy.fuel_burn_limits.fuel_burn_limit_balance",
            "system.policy.fuel_burn_limits.consolidate_results",
            "objective.system.policy.aggregate_fuel_burn_limit_violation_penalties",
        ],
        "subsidies": [
            "system.policy.subsidies",
            "objective.system.policy.aggregate_subsidies",
        ],
        "policy": [
            "geography.generic_policy",
            "system.policy.generic_policy",
            "system.policy.generic_policy.generic_policy_requirements",
            "project.policy.policy_contribution",
            "system.policy.generic_policy.aggregate_project_policy_contributions",
            "system.policy.generic_policy.policy_target_balance",
            "objective.system.policy.aggregate_policy_target_violation_penalties",
            "system.policy.generic_policy.consolidate_results",
        ],
        "prm": [
            "geography.prm_zones",
            "system.reliability.prm",
            "system.reliability.prm.prm_requirement",
            "project.reliability.prm",
            "project.reliability.prm.prm_types",
            "project.reliability.prm.prm_simple",
            "system.reliability.prm.aggregate_project_simple_prm_contribution",
            "system.reliability.prm.prm_balance",
            "system.reliability.prm.consolidate_results",
            "objective.system.reliability.prm.aggregate_prm_violation_penalties",
        ],
        "local_capacity": [
            "geography.local_capacity_zones",
            "system.reliability.local_capacity",
            "system.reliability.local_capacity.local_capacity_requirement",
            "project.reliability.local_capacity",
            "project.reliability.local_capacity.local_capacity_contribution",
            "system.reliability.local_capacity"
            ".aggregate_local_capacity_contribution",
            "system.reliability.local_capacity.local_capacity_balance",
            "system.reliability.local_capacity.consolidate_results",
            "objective.system.reliability.local_capacity"
            ".aggregate_local_capacity_violation_penalties",
        ],
        "markets": [
            "geography.markets",
            "system.markets.prices",
            "system.markets.market_participation",
            "system.markets.volume",
            "system.load_balance.aggregate_market_participation",
            "objective.system.aggregate_market_revenue_and_costs",
        ],
        "water": [
            "geography.water_network",
            "system.water.water_system_params",
            "system.water.water_nodes",
            "system.water.water_flows",
            "system.water.water_node_inflows_outflows",
            "system.water.reservoirs",
            "system.water.water_node_balance",
            "system.water.powerhouses",
            "objective.system.water.aggregate_reservoir_violation_penalty_costs",
            "objective.system.water.aggregate_flow_violation_penalty_costs",
        ],
    }
    return optional_modules


def cross_feature_modules_list():
    """
    :return: dictionary with a tuple of features as keys and a list of
        modules to be included if all those features are selected as values

    Some modules depend on more than one feature, i.e. they are included
    only if multiple features are selected. These relationships are
    described in the 'cross_modules' dictionary here.
    """
    cross_modules = {
        ("transmission", "transmission_hurdle_rates"): [
            "transmission.operations.hurdle_costs",
        ],
        ("transmission", "transmission_hurdle_rates_by_timepoint"): [
            "transmission.operations.hurdle_costs_by_timepoint",
        ],
        ("transmission", "carbon_cap", "track_carbon_imports"): [
            "system.policy.carbon_cap" ".aggregate_transmission_carbon_emissions",
            "transmission.operations.carbon_emissions",
        ],
        ("transmission", "simultaneous_flow_limits"): [
            "transmission.operations.simultaneous_flow_limits"
        ],
        ("transmission", "prm", "capacity_transfers"): [
            "transmission.reliability.capacity_transfer_links",
            "system.reliability.prm.capacity_contribution_transfers",
            "objective.system.reliability.prm.aggregate_capacity_transfer_costs",
        ],
        ("prm", "elcc_surface"): [
            "project.reliability.prm.elcc_surface",
            "system.reliability.prm.elcc_surface",
        ],
        ("prm", "deliverability"): [
            "project.reliability.prm.group_costs",
            "objective.project.aggregate_prm_group_costs",
        ],
        ("carbon_cap", "carbon_credits"): [
            "system.policy.carbon_cap.aggregate_project_carbon_credits",
        ],
        ("performance_standard", "carbon_credits"): [
            "system.policy.performance_standard.aggregate_project_carbon_credits",
        ],
        ("carbon_tax", "carbon_credits"): [
            "system.policy.carbon_tax.aggregate_project_carbon_credits",
        ],
    }
    return cross_modules


def stage_feature_module_list():
    """
    :return: dictionary with a features as keys and a list of modules to be included
    if those features are selected AND there are stages as values
    """
    stage_feature_modules = {"markets": ["system.markets.fix_market_participation"]}

    return stage_feature_modules


def feature_shared_modules_list():
    """
    :return: dictionary with a tuple of features as keys and a list of
        modules to be included if either of those features is selected as
        values
    """
    shared_modules = {
        ("period_energy_target", "horizon_energy_target"): [
            "geography.energy_target_zones",
            "project.operations.energy_target_contributions",
            "system.policy.energy_targets",
            "system.policy.energy_targets.consolidate_results",
        ],
        ("transmission_target", "horizon_transmission_target"): [
            "geography.transmission_target_zones",
            "transmission.operations.transmission_target_contributions",
        ],
        ("transmission_hurdle_rates", "transmission_hurdle_rates_by_timepoint"): [
            "objective.transmission.aggregate_hurdle_costs",
        ],
    }

    return shared_modules


def feature_remove_modules_list():
    """
    :return: dictionary with the feature name as keys and a list of modules to be
    excluded if the feature is selected
    """

    feature_remove_modules = {}

    return feature_remove_modules


def determine_modules(
    features=None,
    scenario_directory=None,
    multi_stage=None,
):
    """
    :param features: List of requested features. Optional input; if
        not specified, function will try to load 'features.csv' file to
        determine the requested features.
    :param scenario_directory: the scenario directory, where we will look
        for the list of requested features. Optional input; if not specified,
        function will look for the 'features' input parameter
    :param multi_stage: Boolean. Optional input that determines whether the
        modules that fix variables are used (yes if True, no if False); if not
        specified, this function will check the scenario_directory to
        determine whether there are stage subdirectories (if there are not,
        the 'fix variables' modules are removed).
    :return: the list of modules -- a subset of all GridPath modules -- needed
        for a scenario. These are the module names, not the actual modules.

    This method determines which modules are needed for a scenario based on
    the features specified for the scenario. The features can be either
    directly specified as a list or by providing the directory where a
    'features.csv' file lists the requested features.

    We start with the list of all GridPath modules from *all_modules_list()*
    as the list of modules to use in the scenario. We then iterate over all
    optional features, which we get from the keys of the
    *optional_modules_list()* method above; if the feature is in the list of
    user-requested features, we do nothing; if it is not, we remove all of the
    feature's modules from the list of modules to use. Similarly, for the cross
    feature modules, which we get from the *cross_feature_module_list()* method,
    we check if all features they depend on are included and, if not, remove
    those modules from the list of modules to use.
    """
    requested_features = []
    if (scenario_directory is None) and (features is None):
        raise IOError("""Need to specify either 'scenario_directory', the
                      directory where 'features.csv' is saved, or 'features',
                      the list of requested features""")
    elif features is not None:
        requested_features = features
    elif scenario_directory is not None:
        features_file = os.path.join(scenario_directory, "features.csv")
        try:
            requested_features = pd.read_csv(features_file)["features"].tolist()
        except IOError:
            print(
                "ERROR! Features file {} not found in {}.".format(
                    features_file, scenario_directory
                )
            )
            sys.exit(1)

    # Remove any modules not requested by user
    # Start with the list of all modules
    modules_to_use = all_modules_list()

    # If we haven't explicitly specified whether this is a multi-stages
    # scenario, check the scenario directory to determine whether we have
    # multiple stages and remove the "fix variables" modules from the
    # modules_to_use list if not
    # Also remove the "fix variables modules" if the multi_stage argument is False
    remove_fix_variable_modules = False
    if multi_stage is None:
        subproblems = check_for_integer_subdirectories(scenario_directory)
        # Check if we have subproblems
        if subproblems:
            # If so, check if there are stages in the subproblem
            for subproblem in subproblems:
                stages = check_for_integer_subdirectories(
                    os.path.join(scenario_directory, subproblem)
                )
                # If we find stages in any subproblem, break out of the loop
                # and keep the "fix variables" modules
                if stages:
                    break
            else:
                remove_fix_variable_modules = True
        # If we make it here, we didn't find subproblems so we'll remove the
        # "fix variables" modules
        else:
            remove_fix_variable_modules = True
    # If multi_stages has been specified explicitly, decide whether to
    # remove the "fix variables" modules based on the value specified
    elif multi_stage is False:
        remove_fix_variable_modules = True

    if remove_fix_variable_modules:
        modules_to_use.remove("project.operations.fix_commitment")
        modules_to_use.remove("system.markets.fix_market_participation")

    # Remove modules associated with features that are not requested
    optional_modules = optional_modules_list()
    for feature in list(optional_modules.keys()):
        if feature not in requested_features:
            for m in optional_modules[feature]:
                modules_to_use.remove(m)

    # Remove shared modules if none of the features sharing those modules is
    # requested
    shared_modules = feature_shared_modules_list()
    for feature_group in shared_modules.keys():
        if not any(feature in requested_features for feature in feature_group):
            for m in shared_modules[feature_group]:
                modules_to_use.remove(m)

    # Some modules depend on more than one feature
    # We have to check if all features that the module depends on are
    # specified before removing it
    cross_feature_modules = cross_feature_modules_list()
    for feature_group in list(cross_feature_modules.keys()):
        if not all(feature in requested_features for feature in feature_group):
            for m in cross_feature_modules[feature_group]:
                modules_to_use.remove(m)

    # Remove "fix variables" modules, which should not be included when the feature is
    # not included even when there are stages
    stage_feature_modules = stage_feature_module_list()
    for feature in stage_feature_modules:
        if feature not in requested_features and not remove_fix_variable_modules:
            for m in stage_feature_modules[feature]:
                modules_to_use.remove(m)

    # Remove modules features explicitly ask to remove
    for feature in feature_remove_modules_list().keys():
        if feature in requested_features:
            for m in feature_remove_modules_list()[feature]:
                modules_to_use.remove(m)

    return modules_to_use


def load_modules(modules_to_use):
    """
    :param modules_to_use: a list of the names of the modules to use
    :return: list of imported modules (Python <class 'module'> objects)

    Load the requested modules and return them as a list of Python module
    objects.
    """
    loaded_modules = list()
    for m in modules_to_use:
        try:
            imported_module = import_module("." + m, package="gridpath")
            loaded_modules.append(imported_module)
        except ImportError:
            print("ERROR! Unable to import module " + str(m) + ".")
            traceback.print_exc()
            sys.exit(1)

    return loaded_modules
