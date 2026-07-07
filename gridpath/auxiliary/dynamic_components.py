# Copyright 2016-2023 Blue Marble Analytics LLC.
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
This module creates the DynamicComponents class, which contains the lists and
dictionaries of the names of dynamic optimization components. These are
components that are populated by GridPath modules based on the selected
features and the scenario input data.
"""

# Create global variables for the dynamic component names, so that we can
# more easily import the correct names into other modules
capacity_type_operational_period_sets = "capacity_type_operational_period_sets"
capacity_type_financial_period_sets = "capacity_type_financial_period_sets"

headroom_variables = "headroom_variables"
footroom_variables = "footroom_variables"
reserve_variable_derate_params = "reserve_variable_derate_params"
reserve_to_energy_adjustment_params = "reserve_to_energy_adjustment_params"
inertia_variable = "inertia_variable"

prm_cost_group_sets = "prm_cost_groups"
prm_cost_group_prm_type = "prm_cost_group_prm_type"

tx_capacity_type_operational_period_sets = "tx_capacity_type_operational_period_sets"
tx_capacity_type_financial_period_sets = "tx_capacity_type_financial_period_sets"

load_balance_production_components = "load_balance_production_components"
load_balance_consumption_components = "load_balance_consumption_components"

carbon_cap_balance_emission_components = "carbon_cap_balance_emission_components"
carbon_cap_balance_credit_components = "carbon_cap_balance_credit_components"

carbon_tax_cost_components = "carbon_tax_cost_components"

performance_standard_balance_emission_components = (
    "performance_standard_balance_emission_components"
)
performance_standard_balance_credit_components = (
    "performance_standard_balance_credit_components"
)

carbon_credits_balance_generation_components = (
    "carbon_credits_balance_generation_components"
)
carbon_credits_balance_purchase_components = (
    "carbon_credits_balance_purchase_components"
)

prm_balance_provision_components = "prm_balance_provision_components"
local_capacity_balance_provision_components = (
    "local_capacity_balance_provision_components"
)

fuel_burn_balance_components = "fuel_burn_balance_components"

policy_balance_contribution_components = "policy_balance_contribution_components"

cost_components = "cost_components"
revenue_components = "revenue_components"


class DynamicComponents(object):
    """
    Here we initialize the class object and its components that will contain
    the dynamic model components, i.e. lists and dictionary with the names
    of the optimization components that are populated based on whether features
    are selected (i.e. certain modules are called) and based on the scenario
    input data.
    """

    def __init__(self):
        """
        Initialize the dynamic components.
        """

        # ### Project sets and variables ### #
        # These are the names of the sets of project-operational_period and
        # project_financial_period by capacity type;
        # The respective sets will be joined to make the final
        # project-operational_period and project-financial_period sets that include
        # all projects
        # If called, the capacity-type modules will populate these lists with
        # the name of the respective set for the capacity type
        setattr(self, capacity_type_operational_period_sets, list())
        setattr(self, capacity_type_financial_period_sets, list())

        # PRM cost groups
        setattr(self, prm_cost_group_sets, list())
        setattr(self, prm_cost_group_prm_type, dict())

        # ### Operating reserves ### #
        # Headroom and footroom variables
        # These will include the project as keys and a list as value for
        # each project; the list could be empty if the project is not
        # providing any reserves, or will include the names of the
        # respective reserve-provision variable if the reserve-type is
        # modeled and a project can provide it
        setattr(self, headroom_variables, dict())
        setattr(self, footroom_variables, dict())
        setattr(self, inertia_variable, dict())

        # A reserve-provision derate parameter and a
        # reserve-to-energy-adjustment parameter could also be assigned to
        # project, so we make dictionaries that will link the
        # reserve-provision variable names to a derate-param name (i.e. the
        # regulation up variable will be linked to a regulation-up
        # parameter, the spinning-reserves variable will be linked to a
        # spinning reserves paramater, etc.)
        setattr(self, reserve_variable_derate_params, dict())
        setattr(self, reserve_to_energy_adjustment_params, dict())

        # ### Transmission sets and variables ### #
        setattr(self, tx_capacity_type_operational_period_sets, list())
        setattr(self, tx_capacity_type_financial_period_sets, list())

        # ### Constraint and objective function components ### #
        # Load balance constraint
        # Modules will add component names to these lists
        setattr(self, load_balance_production_components, list())
        setattr(self, load_balance_consumption_components, list())

        # Carbon cap constraint
        # Modules will add component names to these lists
        setattr(self, carbon_cap_balance_emission_components, list())
        setattr(self, carbon_cap_balance_credit_components, list())

        # Carbon tax cost constraint
        setattr(self, carbon_tax_cost_components, list())

        # Performance standard constraint
        setattr(self, performance_standard_balance_emission_components, list())
        setattr(self, performance_standard_balance_credit_components, list())

        # Carbon credits tracking
        # Modules will add component names to these lists
        setattr(self, carbon_credits_balance_generation_components, list())
        setattr(self, carbon_credits_balance_purchase_components, list())

        # PRM constraint
        # Modules will add component names to this list
        setattr(self, prm_balance_provision_components, list())

        # Local capacity constraint
        # Modules will add component names to this list
        setattr(self, local_capacity_balance_provision_components, list())

        # Fuel burn limit constraint
        # Modules will add component names to this list
        setattr(self, fuel_burn_balance_components, list())

        # Generic policy constraint
        # Modules will add component names to this list
        setattr(self, policy_balance_contribution_components, list())

        # Objective functions
        # Modules will add component names to this list
        setattr(self, cost_components, list())
        setattr(self, revenue_components, list())
