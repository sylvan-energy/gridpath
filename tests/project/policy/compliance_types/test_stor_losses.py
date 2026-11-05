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
import os.path
import sys
import unittest

from pyomo.repn import generate_standard_repn

from tests.common_functions import create_abstract_model, add_components_and_load_data
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

    def test_contribution_is_net_discharge_for_each_storage_type(self):
        """
        The contribution is net discharge (discharge minus charge) expressed
        through the operational type's own variables: Battery is a 'stor'
        project, Battery_Stress_Hrz a 'stor_stress_hrz' project, which has no
        discharge variable in average-condition horizons.
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

        def linear_terms(prj, tmp):
            repn = generate_standard_repn(
                instance.Policy_Contribution_in_Timepoint[prj, "RPS", "RPSZone1", tmp]
            )
            self.assertTrue(repn.is_linear())
            self.assertEqual(0, repn.constant)
            return {
                var.name: coef for var, coef in zip(repn.linear_vars, repn.linear_coefs)
            }

        # stor: discharge minus charge in every timepoint
        stor_tmps = [tmp for (prj, tmp) in instance.STOR_OPR_TMPS if prj == "Battery"]
        self.assertTrue(stor_tmps)
        for tmp in stor_tmps:
            self.assertDictEqual(
                {
                    f"Stor_Discharge_MW[Battery,{tmp}]": 1,
                    f"Stor_Charge_MW[Battery,{tmp}]": -1,
                },
                linear_terms("Battery", tmp),
            )

        # stor_stress_hrz: discharge minus charge in stress timepoints, charge
        # only in average-condition timepoints
        prj = "Battery_Stress_Hrz"
        all_tmps = [t for (p, t) in instance.STOR_STRESS_HRZ_OPR_TMPS if p == prj]
        stress_tmps = [
            t for (p, t) in instance.STOR_STRESS_HRZ_STRESS_OPR_TMPS if p == prj
        ]
        average_tmps = [t for t in all_tmps if t not in stress_tmps]
        self.assertTrue(stress_tmps)
        self.assertTrue(average_tmps)
        for tmp in stress_tmps:
            self.assertDictEqual(
                {
                    f"StorStressHrz_Discharge_MW[{prj},{tmp}]": 1,
                    f"StorStressHrz_Charge_MW[{prj},{tmp}]": -1,
                },
                linear_terms(prj, tmp),
            )
        for tmp in average_tmps:
            self.assertDictEqual(
                {f"StorStressHrz_Charge_MW[{prj},{tmp}]": -1},
                linear_terms(prj, tmp),
            )


if __name__ == "__main__":
    unittest.main()
