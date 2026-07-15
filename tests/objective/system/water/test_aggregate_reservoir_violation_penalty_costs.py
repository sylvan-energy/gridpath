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

from pyomo.environ import value

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_data"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.water_network",
    "system.water.water_system_params",
    "system.water.water_nodes",
    "system.water.water_flows",
    "system.water.water_node_inflows_outflows",
    "system.water.reservoirs",
]
NAME_OF_MODULE_BEING_TESTED = (
    "objective.system.water.aggregate_reservoir_violation_penalty_costs"
)
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


class TestReservoirViolationPenaltyCostsAgg(unittest.TestCase):
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

    def test_penalty_cost_expressions(self):
        """
        Fix all reservoir-violation variables at 1 and check that each
        penalty cost expression evaluates to the sum implied by the
        respective penalty cost parameter — in particular that target
        release violations are priced with target_release_violation_cost,
        min storage violations with min_volume_violation_cost, and max
        storage violations with max_volume_violation_cost (the fixture
        values of these parameters are all distinct, so crossed wires
        produce different totals).
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

        for var in [
            instance.Target_Release_Violation_VolUnit,
            instance.Min_Reservoir_Storage_Violation,
            instance.Max_Reservoir_Storage_Violation,
        ]:
            for idx in var:
                var[idx].value = 1

        expected_release_penalty = sum(
            instance.target_release_violation_cost[r]
            * instance.number_years_represented[
                instance.period[instance.last_hrz_tmp[bt, hrz]]
            ]
            * instance.discount_factor[instance.period[instance.last_hrz_tmp[bt, hrz]]]
            for (
                r,
                bt,
                hrz,
            ) in instance.WATER_NODE_RESERVOIR_BT_HRZS_WITH_TOTAL_RELEASE_REQUIREMENTS
        )
        self.assertAlmostEqual(
            expected_release_penalty,
            value(instance.Total_Release_Violation_Penalty_Cost),
            delta=1e-6 * abs(expected_release_penalty),
        )
        self.assertGreater(expected_release_penalty, 0)

        expected_min_storage_penalty = sum(
            instance.min_volume_violation_cost[r]
            * instance.hrs_in_tmp[tmp]
            * instance.tmp_weight[tmp]
            * instance.number_years_represented[instance.period[tmp]]
            * instance.discount_factor[instance.period[tmp]]
            for r in instance.WATER_NODES_W_RESERVOIRS
            for tmp in instance.TMPS
        )
        self.assertAlmostEqual(
            expected_min_storage_penalty,
            value(instance.Total_Min_Water_Storage_Violation_Penalty_Cost),
            delta=1e-6 * abs(expected_min_storage_penalty),
        )
        self.assertGreater(expected_min_storage_penalty, 0)

        expected_max_storage_penalty = sum(
            instance.max_volume_violation_cost[r]
            * instance.hrs_in_tmp[tmp]
            * instance.tmp_weight[tmp]
            * instance.number_years_represented[instance.period[tmp]]
            * instance.discount_factor[instance.period[tmp]]
            for r in instance.WATER_NODES_W_RESERVOIRS
            for tmp in instance.TMPS
        )
        self.assertAlmostEqual(
            expected_max_storage_penalty,
            value(instance.Total_Max_Water_Storage_Violation_Penalty_Cost),
            delta=1e-6 * abs(expected_max_storage_penalty),
        )
        self.assertGreater(expected_max_storage_penalty, 0)


if __name__ == "__main__":
    unittest.main()
