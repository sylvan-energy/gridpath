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


from collections import OrderedDict
from importlib import import_module
import logging
import os.path
import sys
import unittest

import pandas as pd
from pyomo.common.log import LoggingIntercept
from pyomo.repn import generate_standard_repn

from tests.common_functions import (
    create_abstract_model,
    add_components_and_load_data,
    stage_test_data_with_appended_rows,
)
from tests.project.operations.common_functions import get_project_operational_timepoints

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "test_data",
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
]

# Note that we are checking stor_losses inputs have been added by the
# policy_contribution module, which loops over all required compliance types
NAME_OF_MODULE_BEING_TESTED = "project.policy.policy_contribution"
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


class TestStorLossesComplianceType(unittest.TestCase):
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

    def test_contribution_is_net_discharge(self):
        """
        The contribution of a 'stor' project is its discharge minus its
        charge in every timepoint.
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

        stor_tmps = [tmp for (prj, tmp) in instance.STOR_OPR_TMPS if prj == "Battery"]
        self.assertTrue(stor_tmps)
        for tmp in stor_tmps:
            repn = generate_standard_repn(
                instance.Policy_Contribution_in_Timepoint[
                    "Battery", "RPS", "RPSZone1", tmp
                ]
            )
            self.assertTrue(repn.is_linear())
            self.assertEqual(0, repn.constant)
            self.assertDictEqual(
                {
                    f"Stor_Discharge_MW[Battery,{tmp}]": 1,
                    f"Stor_Charge_MW[Battery,{tmp}]": -1,
                },
                {
                    var.name: coef
                    for var, coef in zip(repn.linear_vars, repn.linear_coefs)
                },
            )

    def test_unsupported_operational_type_fails_at_model_build(self):
        """
        Assigning the compliance type to a project of an operational type it
        does not support (here 'stor_stress_hrz') raises an error naming the
        project when the model is built.
        """
        staged_dir = stage_test_data_with_appended_rows(
            self,
            TEST_DATA_DIRECTORY,
            "project_policy_zones.tab",
            [["Battery_Stress_Hrz", "RPS", "RPSZone1", "stor_losses"] + ["."] * 4],
        )
        m, data = add_components_and_load_data(
            prereq_modules=IMPORTED_PREREQ_MODULES,
            module_to_test=MODULE_BEING_TESTED,
            test_data_dir=staged_dir,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
        )
        # Pyomo logs the rule's exception before re-raising it
        with LoggingIntercept(module="pyomo.core", level=logging.ERROR):
            with self.assertRaisesRegex(
                ValueError, "Battery_Stress_Hrz of the stor_stress_hrz operational"
            ):
                m.create_instance(data)

    def test_validate_stor_losses_operational_types(self):
        """
        Validation reports each stor_losses row whose project is not of a
        supported operational type (or has no operational type), and no
        other row.
        """
        df = pd.DataFrame(
            columns=["project", "policy_name", "policy_zone", "compliance_type"],
            data=[
                ["Battery", "RPS", "RPSZone1", "stor_losses"],
                ["Battery_Stress_Hrz", "RPS", "RPSZone1", "stor_losses"],
                ["Unknown", "RPS", "RPSZone2", "stor_losses"],
                ["Wind", "RPS", "RPSZone1", "f_output"],
            ],
        )
        errors = MODULE_BEING_TESTED.validate_stor_losses_operational_types(
            df=df,
            operational_type_by_project={
                "Battery": "stor",
                "Battery_Stress_Hrz": "stor_stress_hrz",
                "Wind": "gen_var",
            },
        )
        self.assertEqual(2, len(errors))
        self.assertTrue(
            errors[0].startswith(
                "project:Battery_Stress_Hrz, policy:RPS, policy_zone:RPSZone1"
            )
        )
        self.assertIn("operational type is stor_stress_hrz", errors[0])
        self.assertTrue(
            errors[1].startswith("project:Unknown, policy:RPS, policy_zone:RPSZone2")
        )


if __name__ == "__main__":
    unittest.main()
