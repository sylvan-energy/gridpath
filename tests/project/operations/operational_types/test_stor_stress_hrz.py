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


from importlib import import_module
import os.path
import sys
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data
from tests.project.operations.common_functions import get_project_operational_timepoints

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "project",
    "project.capacity.capacity",
    "project.availability.availability",
    "project.fuels",
    "project.operations",
]
NAME_OF_MODULE_BEING_TESTED = "project.operations.operational_types.stor_stress_hrz"
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


class TestStorStressHrz(unittest.TestCase):
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
        Test that the data loaded are as expected
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

        # Set: STOR_STRESS_HRZ
        expected_projects = ["Battery_Stress_Hrz"]
        actual_projects = sorted([p for p in instance.STOR_STRESS_HRZ])
        self.assertListEqual(expected_projects, actual_projects)

        # Set: STOR_STRESS_HRZ_OPR_TMPS
        expected_tmps = sorted(get_project_operational_timepoints(expected_projects))
        actual_tmps = sorted([tmp for tmp in instance.STOR_STRESS_HRZ_OPR_TMPS])
        self.assertListEqual(expected_tmps, actual_tmps)

        # Param: stor_stress_hrz_charging_efficiency
        expected_charging_efficiency = {"Battery_Stress_Hrz": 0.8}
        actual_charging_efficiency = {
            prj: instance.stor_stress_hrz_charging_efficiency[prj]
            for prj in instance.STOR_STRESS_HRZ
        }
        self.assertDictEqual(expected_charging_efficiency, actual_charging_efficiency)

        # Param: stor_stress_hrz_discharging_efficiency
        expected_discharging_efficiency = {"Battery_Stress_Hrz": 0.8}
        actual_discharging_efficiency = {
            prj: instance.stor_stress_hrz_discharging_efficiency[prj]
            for prj in instance.STOR_STRESS_HRZ
        }
        self.assertDictEqual(
            expected_discharging_efficiency, actual_discharging_efficiency
        )

        # Param: stor_stress_hrz_storage_efficiency (not specified, so the default
        # of 1 applies)
        expected_storage_efficiency = {"Battery_Stress_Hrz": 1}
        actual_storage_efficiency = {
            prj: instance.stor_stress_hrz_storage_efficiency[prj]
            for prj in instance.STOR_STRESS_HRZ
        }
        self.assertDictEqual(expected_storage_efficiency, actual_storage_efficiency)

        # Param: stor_stress_hrz_type ("stress" where specified in
        # stor_stress_hrz_horizon_types.tab, the "average" default elsewhere)
        expected_hrz_type = {
            ("day", 202001): "average",
            ("day", 202002): "stress",
            ("day", 203001): "average",
            ("day", 203002): "stress",
        }
        actual_hrz_type = {
            (bt, hrz): instance.stor_stress_hrz_type[bt, hrz]
            for (bt, hrz) in instance.BLN_TYPE_HRZS
            if bt == "day"
        }
        self.assertDictEqual(expected_hrz_type, actual_hrz_type)

        # Set: STOR_STRESS_HRZ_OPR_BT_HRZ
        # Battery_Stress_Hrz has specified capacity in 2020 only, so only the 2020
        # horizons are operational
        expected_opr_bt_hrz = [
            ("Battery_Stress_Hrz", "day", 202001),
            ("Battery_Stress_Hrz", "day", 202002),
        ]
        actual_opr_bt_hrz = sorted([x for x in instance.STOR_STRESS_HRZ_OPR_BT_HRZ])
        self.assertListEqual(expected_opr_bt_hrz, actual_opr_bt_hrz)

        # Set: STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ
        expected_stress_bt_hrz = [("Battery_Stress_Hrz", "day", 202002)]
        actual_stress_bt_hrz = sorted(
            [x for x in instance.STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ]
        )
        self.assertListEqual(expected_stress_bt_hrz, actual_stress_bt_hrz)

        # Set: STOR_STRESS_HRZ_AVG_OPR_BT_HRZ
        expected_avg_bt_hrz = [("Battery_Stress_Hrz", "day", 202001)]
        actual_avg_bt_hrz = sorted([x for x in instance.STOR_STRESS_HRZ_AVG_OPR_BT_HRZ])
        self.assertListEqual(expected_avg_bt_hrz, actual_avg_bt_hrz)

        # The average and stress sets partition STOR_STRESS_HRZ_OPR_BT_HRZ (their
        # union covers every operational horizon and they are disjoint)
        avg = set(instance.STOR_STRESS_HRZ_AVG_OPR_BT_HRZ)
        stress = set(instance.STOR_STRESS_HRZ_STRESS_OPR_BT_HRZ)
        self.assertSetEqual(avg | stress, set(instance.STOR_STRESS_HRZ_OPR_BT_HRZ))
        self.assertSetEqual(avg & stress, set())

        # Set: STOR_STRESS_HRZ_STRESS_OPR_TMPS (the timepoints of the stress
        # horizons)
        expected_stress_tmps = sorted(
            [
                ("Battery_Stress_Hrz", tmp)
                for tmp in instance.TMPS_BY_BLN_TYPE_HRZ["day", 202002]
            ]
        )
        actual_stress_tmps = sorted(
            [(prj, tmp) for (prj, tmp) in instance.STOR_STRESS_HRZ_STRESS_OPR_TMPS]
        )
        self.assertListEqual(expected_stress_tmps, actual_stress_tmps)

        # Set: STOR_STRESS_HRZ_AVG_PRJ_PRDS
        expected_avg_prj_prds = [("Battery_Stress_Hrz", 2020)]
        actual_avg_prj_prds = sorted([x for x in instance.STOR_STRESS_HRZ_AVG_PRJ_PRDS])
        self.assertListEqual(expected_avg_prj_prds, actual_avg_prj_prds)

        # Indexed Set: STOR_STRESS_HRZ_AVG_BT_HRZS_BY_PRJ_PRD
        expected_avg_bt_hrzs_by_prj_prd = {
            ("Battery_Stress_Hrz", 2020): [("day", 202001)]
        }
        actual_avg_bt_hrzs_by_prj_prd = {
            (prj, prd): sorted(
                [x for x in instance.STOR_STRESS_HRZ_AVG_BT_HRZS_BY_PRJ_PRD[prj, prd]]
            )
            for (prj, prd) in instance.STOR_STRESS_HRZ_AVG_PRJ_PRDS
        }
        self.assertDictEqual(
            expected_avg_bt_hrzs_by_prj_prd, actual_avg_bt_hrzs_by_prj_prd
        )


if __name__ == "__main__":
    unittest.main()
