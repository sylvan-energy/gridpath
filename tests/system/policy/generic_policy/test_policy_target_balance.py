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


from collections import OrderedDict
from importlib import import_module
import os.path
import sys
import unittest

from pyomo.repn import generate_standard_repn

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.markets",
    "system.markets.prices",
    "system.load_balance.static_load_requirement",
    "geography.generic_policy",
    "system.policy.generic_policy.generic_policy_requirements",
    "geography.water_network",
    "system.water.water_system_params",
    "system.water.water_nodes",
    "system.water.water_flows",
    "system.water.water_node_inflows_outflows",
    "system.water.reservoirs",
    "system.water.water_node_balance",
    "system.water.powerhouses",
    "project",
    "project.capacity.capacity",
    "project.availability.availability",
    "project.fuels",
    "project.operations",
    "project.capacity.potential",
    "project.operations.operational_types",
    "project.operations.power",
    "project.operations.fuel_burn",
    "project.operations.carbon_emissions",
    "project.policy.policy_contribution",
    "system.policy.generic_policy.policy_requirement_base",
    "system.policy.generic_policy.aggregate_project_policy_contributions",
]
NAME_OF_MODULE_BEING_TESTED = "system.policy.generic_policy.policy_target_balance"
IMPORTED_PREREQ_MODULES = list()
for mdl in PREREQUISITE_MODULE_NAMES:
    try:
        imported_module = import_module("." + str(mdl), package="gridpath")
        IMPORTED_PREREQ_MODULES.append(imported_module)
    except ImportError:
        print("ERROR! Module " + str(mdl) + " not found.")
        sys.exit(1)
# Import the module we'll test
try:
    MODULE_BEING_TESTED = import_module(
        "." + NAME_OF_MODULE_BEING_TESTED, package="gridpath"
    )
except ImportError:
    print("ERROR! Couldn't import module " + NAME_OF_MODULE_BEING_TESTED + " to test.")


class TestAggregateProjectPolicyContributions(unittest.TestCase):
    """ """

    def test_add_model_components(self):
        """
        Test that there are no errors when adding model components
        :return:
        """
        create_abstract_model(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_load_model_data(self):
        """
        Test that data are loaded with no errors
        :return:
        """
        add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )

    def test_data_loaded_correctly(self):
        """
        Test components initialized with data as expected
        :return:
        """
        m, data = add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=TEST_DATA_DIRECTORY,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        instance = m.create_instance(data)

        # The 'min' RPS requirement is a floor on the contributions and the
        # 'max' Carbon requirement a ceiling. Pyomo stores both as
        # body <= 0: 'requirement - contributions' for the RPS (whose zone
        # does not allow violations, so no shortage variable enters) and
        # 'contributions - overage - requirement' for the Carbon policy
        # (whose zone does allow violations).
        # The Carbon 2020 requirement also scales with its base projects'
        # quantities (Gas_CT's and Wind's output and half of Coal's capacity)
        # through the base coefficient; the other requirements have no base
        # term.
        constraint = instance.Policy_Requirement_Constraint
        contributions = (
            instance.Total_Policy_Zone_Tmp_Contributions_from_All_Sources_Expression
        )
        requirement = instance.Policy_Zone_Horizon_Requirement
        base = instance.Total_Policy_Zone_Base_from_All_Sources_Expression
        base_coeff = instance.policy_requirement_f_base_coeff
        for h in [2020, 2030]:
            rps = ("RPS", "RPSZone1", "year", h)
            self.assertTrue(linear_coefficients_by_var(contributions[rps]))
            self.assertEqual(0, base_coeff[rps])
            self.assertEqual(
                linear_repn(requirement[rps] - contributions[rps]),
                linear_repn(constraint[rps].body),
            )

            carbon = ("Carbon", "CarbonZone1", "year", h)
            self.assertTrue(linear_coefficients_by_var(contributions[carbon]))
            self.assertEqual(
                linear_repn(
                    contributions[carbon]
                    - instance.Policy_Target_Overage[carbon]
                    - requirement[carbon]
                    - base_coeff[carbon] * base[carbon]
                ),
                linear_repn(constraint[carbon].body),
            )

        carbon_2020 = ("Carbon", "CarbonZone1", "year", 2020)
        self.assertEqual(0.5, base_coeff[carbon_2020])
        self.assertTrue(linear_coefficients_by_var(base[carbon_2020]))
        self.assertEqual(
            linear_repn(instance.Policy_Zone_Horizon_Total_Requirement[carbon_2020]),
            linear_repn(requirement[carbon_2020] + 0.5 * base[carbon_2020]),
        )


def linear_coefficients_by_var(expr):
    """
    The linear coefficient of each variable in the expression, keyed by the
    variable's name.
    """
    repn = generate_standard_repn(expr)
    return {var.name: coef for var, coef in zip(repn.linear_vars, repn.linear_coefs)}


def linear_repn(expr):
    """
    The constant and the linear coefficients by variable name of the
    expression, for comparing two linear expressions.
    """
    return (
        generate_standard_repn(expr).constant,
        linear_coefficients_by_var(expr),
    )


if __name__ == "__main__":
    unittest.main()
