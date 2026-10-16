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
]
NAME_OF_MODULE_BEING_TESTED = "system.policy.generic_policy.policy_requirement_base"
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


class TestPolicyRequirementBase(unittest.TestCase):
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

        # Set: POLICY_ZONE_BASE_PRJS (Wind drives the Carbon requirement
        # without contributing toward it)
        expected_base_prjs = sorted(
            [
                ("Carbon", "CarbonZone1", "Gas_CT", "output"),
                ("Carbon", "CarbonZone1", "Coal", "capacity"),
                ("Carbon", "CarbonZone1", "Wind", "output"),
            ]
        )
        self.assertListEqual(expected_base_prjs, sorted(instance.POLICY_ZONE_BASE_PRJS))

        # Param: policy_base_multiplier (unspecified defaults to 1)
        expected_multiplier = {
            ("Carbon", "CarbonZone1", "Gas_CT", "output"): 1,
            ("Carbon", "CarbonZone1", "Coal", "capacity"): 0.5,
            ("Carbon", "CarbonZone1", "Wind", "output"): 1,
        }
        actual_multiplier = {
            idx: instance.policy_base_multiplier[idx]
            for idx in instance.POLICY_ZONE_BASE_PRJS
        }
        self.assertDictEqual(expected_multiplier, actual_multiplier)

        # Sets: OUTPUT_BASE_POLICY_ZONE_PRJ_OPR_TMPS and
        # CAPACITY_BASE_POLICY_ZONE_PRJ_OPR_PRDS
        expected_output_base = sorted(
            ("Carbon", "CarbonZone1", prj, tmp)
            for (prj, tmp) in instance.PRJ_OPR_TMPS
            if prj in ["Gas_CT", "Wind"]
        )
        self.assertTrue(expected_output_base)
        self.assertListEqual(
            expected_output_base,
            sorted(instance.OUTPUT_BASE_POLICY_ZONE_PRJ_OPR_TMPS),
        )
        expected_capacity_base = sorted(
            ("Carbon", "CarbonZone1", "Coal", prd)
            for prd in instance.OPR_PRDS_BY_PRJ["Coal"]
        )
        self.assertTrue(expected_capacity_base)
        self.assertListEqual(
            expected_capacity_base,
            sorted(instance.CAPACITY_BASE_POLICY_ZONE_PRJ_OPR_PRDS),
        )

        # Expression: Total_Project_Policy_Zone_Base is the output-base
        # projects' weighted energy over the horizon plus the capacity-base
        # projects' weighted capacity in the horizon's period; the RPS policy
        # has no base projects
        base = instance.Total_Project_Policy_Zone_Base
        for h in [2020, 2030]:
            self.assertEqual(
                linear_repn(0), linear_repn(base["RPS", "RPSZone1", "year", h])
            )

            expected = (
                sum(
                    instance.Bulk_Power_Provision_MW[prj, tmp]
                    * instance.hrs_in_tmp[tmp]
                    * instance.tmp_weight[tmp]
                    for prj in ["Gas_CT", "Wind"]
                    for tmp in instance.TMPS_BY_BLN_TYPE_HRZ["year", h]
                    if (prj, tmp) in instance.PRJ_OPR_TMPS
                )
                + 0.5 * instance.Capacity_MW["Coal", h]
            )
            self.assertTrue(linear_coefficients_by_var(expected))
            self.assertEqual(
                linear_repn(expected),
                linear_repn(base["Carbon", "CarbonZone1", "year", h]),
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
