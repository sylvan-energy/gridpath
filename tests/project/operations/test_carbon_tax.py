# Copyright 2021 (c) Crown Copyright, GC.
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
import pandas as pd

from tests.common_functions import create_abstract_model, add_components_and_load_data
from tests.project.operations.common_functions import get_project_operational_timepoints

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.markets",
    "system.markets.prices",
    "geography.carbon_tax_zones",
    "system.policy.carbon_tax.carbon_tax",
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
    "system.load_balance.static_load_requirement",
    "project.capacity.potential",
    "project.operations.operational_types",
    "project.operations.power",
    "project.operations.fuel_burn",
]
NAME_OF_MODULE_BEING_TESTED = "project.operations.carbon_tax"
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


class TestCarbonTaxEmissions(unittest.TestCase):
    """ """

    maxDiff = None

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

        # Set: CARBON_TAX_PRJS
        expected_carbon_tax_projects = sorted(
            [
                "Gas_CCGT",
                "Coal",
                "Gas_CT",
                "Gas_CCGT_New",
                "Gas_CCGT_New_Binary",
                "Gas_CT_New",
                "Gas_CCGT_z2",
                "Coal_z2",
                "Gas_CT_z2",
                "Disp_Binary_Commit",
                "Disp_Cont_Commit",
                "Disp_No_Commit",
                "Clunky_Old_Gen",
                "Clunky_Old_Gen2",
                "Gen_Strike_Price",
            ]
        )
        actual_carbon_tax_projects = sorted([p for p in instance.CARBON_TAX_PRJS])
        self.assertListEqual(expected_carbon_tax_projects, actual_carbon_tax_projects)

        # Param: carbon_tax_zone
        expected_ct_zone_by_prj = OrderedDict(
            sorted(
                {
                    "Gas_CCGT": "Carbon_Tax_Zone1",
                    "Coal": "Carbon_Tax_Zone1",
                    "Gas_CT": "Carbon_Tax_Zone1",
                    "Gas_CCGT_New": "Carbon_Tax_Zone1",
                    "Gas_CCGT_New_Binary": "Carbon_Tax_Zone1",
                    "Gas_CT_New": "Carbon_Tax_Zone1",
                    "Gas_CCGT_z2": "Carbon_Tax_Zone2",
                    "Coal_z2": "Carbon_Tax_Zone2",
                    "Gas_CT_z2": "Carbon_Tax_Zone2",
                    "Disp_Binary_Commit": "Carbon_Tax_Zone1",
                    "Disp_Cont_Commit": "Carbon_Tax_Zone1",
                    "Disp_No_Commit": "Carbon_Tax_Zone1",
                    "Clunky_Old_Gen": "Carbon_Tax_Zone1",
                    "Clunky_Old_Gen2": "Carbon_Tax_Zone1",
                    "Gen_Strike_Price": "Carbon_Tax_Zone1",
                }.items()
            )
        )
        actual_ct_zone_by_prj = OrderedDict(
            sorted(
                {
                    p: instance.carbon_tax_zone[p] for p in instance.CARBON_TAX_PRJS
                }.items()
            )
        )
        self.assertDictEqual(expected_ct_zone_by_prj, actual_ct_zone_by_prj)

        # Set: CARBON_TAX_PRJS_BY_CARBON_TAX_ZONE
        expected_prj_by_zone = OrderedDict(
            sorted(
                {
                    "Carbon_Tax_Zone1": sorted(
                        [
                            "Gas_CCGT",
                            "Coal",
                            "Gas_CT",
                            "Gas_CCGT_New",
                            "Gas_CCGT_New_Binary",
                            "Gas_CT_New",
                            "Disp_Binary_Commit",
                            "Disp_Cont_Commit",
                            "Disp_No_Commit",
                            "Clunky_Old_Gen",
                            "Clunky_Old_Gen2",
                            "Gen_Strike_Price",
                        ]
                    ),
                    "Carbon_Tax_Zone2": sorted(["Gas_CCGT_z2", "Coal_z2", "Gas_CT_z2"]),
                }.items()
            )
        )
        actual_prj_by_zone = OrderedDict(
            sorted(
                {
                    z: sorted(
                        [p for p in instance.CARBON_TAX_PRJS_BY_CARBON_TAX_ZONE[z]]
                    )
                    for z in instance.CARBON_TAX_ZONES
                }.items()
            )
        )
        self.assertDictEqual(expected_prj_by_zone, actual_prj_by_zone)

        # Set: CARBON_TAX_PRJ_OPR_TMPS
        expected_carb_tax_prj_op_tmp = sorted(
            get_project_operational_timepoints(expected_carbon_tax_projects)
        )

        actual_carb_tax_prj_op_tmp = sorted(
            [(prj, tmp) for (prj, tmp) in instance.CARBON_TAX_PRJ_OPR_TMPS]
        )
        self.assertListEqual(expected_carb_tax_prj_op_tmp, actual_carb_tax_prj_op_tmp)

        # Param: carbon_tax_allowance
        expected_carbon_tax_allowance = OrderedDict(
            sorted(
                {
                    ("Gas_CCGT", "Gas", 2020): 10,
                    ("Gas_CCGT", "Blended", 2020): 3,
                    ("Coal", "Solid", 2020): 8,
                    ("Gas_CT", "Gas", 2020): 10,
                    ("Gas_CCGT_New", "Gas", 2020): 10,
                    ("Gas_CCGT_New_Binary", "Gas", 2020): 10,
                    ("Gas_CCGT_z2", "Gas", 2020): 10,
                    ("Coal_z2", "Solid", 2020): 8,
                    ("Gas_CT_z2", "Gas", 2020): 10,
                    ("Disp_Binary_Commit", "Gas", 2020): 10,
                    ("Disp_Cont_Commit", "Gas", 2020): 10,
                    ("Disp_No_Commit", "Gas", 2020): 10,
                    ("Clunky_Old_Gen", "Solid", 2020): 8,
                    ("Clunky_Old_Gen2", "Solid", 2020): 8,
                    ("Gas_CCGT", "Gas", 2030): 5,
                    ("Gas_CCGT", "Blended", 2030): 1,
                    ("Coal", "Solid", 2030): 3,
                    ("Gas_CT", "Gas", 2030): 5,
                    ("Gas_CCGT_New", "Gas", 2030): 5,
                    ("Gas_CCGT_New_Binary", "Gas", 2030): 5,
                    ("Gas_CT_New", "Gas", 2030): 5,
                    ("Gas_CCGT_z2", "Gas", 2030): 5,
                    ("Coal_z2", "Solid", 2030): 3,
                    ("Gas_CT_z2", "Gas", 2030): 5,
                    ("Disp_Binary_Commit", "Gas", 2030): 5,
                    ("Disp_Cont_Commit", "Gas", 2030): 5,
                    ("Disp_No_Commit", "Gas", 2030): 5,
                    ("Clunky_Old_Gen", "Solid", 2030): 3,
                    ("Clunky_Old_Gen2", "Solid", 2030): 3,
                    ("Gen_Strike_Price", "Gas", 2020): 0.01,
                    ("Gen_Strike_Price", "Gas", 2030): 0.005,
                }.items()
            )
        )
        actual_carbon_tax_allowance = OrderedDict(
            sorted(
                {
                    (prj, fg, p): instance.carbon_tax_allowance[prj, fg, p]
                    for (prj, fg, p) in instance.CARBON_TAX_PRJ_FUEL_GROUP_OPR_PRDS
                }.items()
            )
        )
        self.assertDictEqual(expected_carbon_tax_allowance, actual_carbon_tax_allowance)

        # Set: CARBON_TAX_PRJ_OPR_PRDS
        expected_carbon_tax_prj_op_p = sorted(
            [
                ("Clunky_Old_Gen", 2020),
                ("Clunky_Old_Gen", 2030),
                ("Gen_Strike_Price", 2020),
                ("Gen_Strike_Price", 2030),
                ("Clunky_Old_Gen2", 2030),
                ("Clunky_Old_Gen2", 2020),
                ("Coal", 2020),
                ("Coal", 2030),
                ("Coal_z2", 2020),
                ("Coal_z2", 2030),
                ("Disp_Binary_Commit", 2020),
                ("Disp_Binary_Commit", 2030),
                ("Disp_Cont_Commit", 2020),
                ("Disp_Cont_Commit", 2030),
                ("Disp_No_Commit", 2020),
                ("Disp_No_Commit", 2030),
                ("Gas_CCGT", 2020),
                ("Gas_CCGT", 2030),
                ("Gas_CCGT_New", 2020),
                ("Gas_CCGT_New", 2030),
                ("Gas_CCGT_New_Binary", 2020),
                ("Gas_CCGT_New_Binary", 2030),
                ("Gas_CCGT_z2", 2020),
                ("Gas_CCGT_z2", 2030),
                ("Gas_CT", 2020),
                ("Gas_CT", 2030),
                ("Gas_CT_New", 2030),
                ("Gas_CT_z2", 2020),
                ("Gas_CT_z2", 2030),
            ]
        )
        actual_carbon_tax_prj_op_p = sorted(
            [(prj, p) for (prj, p) in instance.CARBON_TAX_PRJ_OPR_PRDS]
        )
        self.assertListEqual(expected_carbon_tax_prj_op_p, actual_carbon_tax_prj_op_p)

        # Param: carbon_tax_allowance_average_heat_rate
        expected_carbon_tax_allowance_average_heat_rate = OrderedDict(
            sorted(
                {
                    ("Gas_CCGT", 2020): 256,
                    ("Coal", 2020): 506,
                    ("Gas_CT", 2020): 88.13333,
                    ("Gas_CCGT_New", 2020): 256,
                    ("Gas_CCGT_New_Binary", 2020): 256,
                    ("Gas_CT_New", 2020): 88.13333,
                    ("Gas_CCGT_z2", 2020): 256,
                    ("Coal_z2", 2020): 506,
                    ("Gas_CT_z2", 2020): 88.13333,
                    ("Disp_Binary_Commit", 2020): 88.13333,
                    ("Disp_Cont_Commit", 2020): 88.13333,
                    ("Disp_No_Commit", 2020): 8,
                    ("Clunky_Old_Gen", 2020): 842.33333,
                    ("Clunky_Old_Gen2", 2020): 842.33333,
                    ("Gas_CCGT", 2030): 256,
                    ("Coal", 2030): 506,
                    ("Gas_CT", 2030): 88.13333,
                    ("Gas_CCGT_New", 2030): 256,
                    ("Gas_CCGT_New_Binary", 2030): 256,
                    ("Gas_CT_New", 2030): 88.13333,
                    ("Gas_CCGT_z2", 2030): 256,
                    ("Coal_z2", 2030): 506,
                    ("Gas_CT_z2", 2030): 88.13333,
                    ("Disp_Binary_Commit", 2030): 88.13333,
                    ("Disp_Cont_Commit", 2030): 88.13333,
                    ("Disp_No_Commit", 2030): 8,
                    ("Clunky_Old_Gen", 2030): 842.33333,
                    ("Clunky_Old_Gen2", 2030): 842.33333,
                    ("Gen_Strike_Price", 2020): 1.1,
                    ("Gen_Strike_Price", 2030): 1.1,
                }.items()
            )
        )
        actual_carbon_tax_allowance_average_heat_rate = OrderedDict(
            sorted(
                {
                    (prj, p): instance.carbon_tax_allowance_average_heat_rate[prj, p]
                    for prj in instance.CARBON_TAX_PRJS
                    for p in instance.PERIODS
                }.items()
            )
        )
        self.assertDictEqual(
            expected_carbon_tax_allowance_average_heat_rate,
            actual_carbon_tax_allowance_average_heat_rate,
        )

        # Set: CARBON_TAX_PRJ_FUEL_GROUP_OPR_TMPS
        fuels_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "fuels.tab"),
            sep="\t",
        )
        prj_fuels_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "project_fuels.tab"),
            sep="\t",
        )
        fuel_group_fuels = list(
            fuels_df[["fuel_group", "fuel"]].to_records(index=False)
        )
        fuel_group_fuels = sorted([tuple(i) for i in fuel_group_fuels])
        fuel_project_fuels = list(
            prj_fuels_df[["project", "fuel"]].to_records(index=False)
        )
        fuel_project_fuels = sorted([tuple(i) for i in fuel_project_fuels])
        fuel_prj_fuels_fuel_group = sorted(
            [
                (prj, fg, f)
                for (prj, f) in fuel_project_fuels
                for (fg, _f) in fuel_group_fuels
                if f == _f
            ]
        )
        expected_carb_tax_prj_fuel_group_op_tmp = sorted(
            [
                (prj, fg, tmp)
                for (prj, tmp) in expected_carb_tax_prj_op_tmp
                for (_prj, fg, f) in fuel_prj_fuels_fuel_group
                if prj == _prj
            ]
        )

        actual_carb_tax_prj_fuel_group_op_tmp = sorted(
            [
                (p, fg, tmp)
                for (p, fg, tmp) in instance.CARBON_TAX_PRJ_FUEL_GROUP_OPR_TMPS
            ]
        )

        self.assertListEqual(
            expected_carb_tax_prj_fuel_group_op_tmp,
            actual_carb_tax_prj_fuel_group_op_tmp,
        )

        # Set: CARBON_TAX_PRJ_FUEL_GROUP_OPR_PRDS
        expected_carb_tax_prj_fuel_group_op_p = sorted(
            [
                (prj, fg, p)
                for (prj, p) in expected_carbon_tax_prj_op_p
                for (_prj, fg, f) in fuel_prj_fuels_fuel_group
                if prj == _prj
            ]
        )

        actual_carb_tax_prj_fuel_group_op_p = sorted(
            [
                (prj, fg, p)
                for (prj, fg, p) in instance.CARBON_TAX_PRJ_FUEL_GROUP_OPR_PRDS
            ]
        )

        self.assertListEqual(
            expected_carb_tax_prj_fuel_group_op_p, actual_carb_tax_prj_fuel_group_op_p
        )


if __name__ == "__main__":
    unittest.main()
