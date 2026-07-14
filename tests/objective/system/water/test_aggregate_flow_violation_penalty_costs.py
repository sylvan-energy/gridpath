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
]
NAME_OF_MODULE_BEING_TESTED = (
    "objective.system.water.aggregate_flow_violation_penalty_costs"
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


class TestFlowViolationPenaltyCostsAgg(unittest.TestCase):
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
        Fix all flow-violation variables at 1 and check that each penalty
        cost expression evaluates to the sum implied by the respective
        penalty cost parameter (i.e., that each expression is wired to the
        correct violation variables and cost parameter).
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
            instance.Water_Link_Min_Flow_Violation_Vol_per_Sec,
            instance.Water_Link_Max_Flow_Violation_Vol_per_Sec,
            instance.Water_Link_Hrz_Min_Flow_Violation_Avg_Vol_per_Sec,
            instance.Water_Link_Hrz_Max_Flow_Violation_Avg_Vol_per_Sec,
        ]:
            for idx in var:
                var[idx].value = 1

        # Per-timepoint min and max flow violation penalties; the violation
        # expressions are non-zero only where violations are allowed
        expected_min_penalty = sum(
            instance.allow_water_link_min_flow_violation[wl]
            * instance.min_flow_violation_penalty_cost[wl]
            * instance.hrs_in_tmp[dep_tmp]
            * instance.tmp_weight[dep_tmp]
            * instance.number_years_represented[instance.period[dep_tmp]]
            * instance.discount_factor[instance.period[dep_tmp]]
            for (wl, dep_tmp, arr_tmp) in instance.WATER_LINK_DEPARTURE_ARRIVAL_TMPS
        )
        self.assertAlmostEqual(
            expected_min_penalty,
            value(instance.Total_Min_Flow_Violation_Penalty_Cost),
            delta=1e-6 * abs(expected_min_penalty),
        )
        self.assertGreater(expected_min_penalty, 0)

        expected_max_penalty = sum(
            instance.allow_water_link_max_flow_violation[wl]
            * instance.max_flow_violation_penalty_cost[wl]
            * instance.hrs_in_tmp[dep_tmp]
            * instance.tmp_weight[dep_tmp]
            * instance.number_years_represented[instance.period[dep_tmp]]
            * instance.discount_factor[instance.period[dep_tmp]]
            for (wl, dep_tmp, arr_tmp) in instance.WATER_LINK_DEPARTURE_ARRIVAL_TMPS
        )
        self.assertAlmostEqual(
            expected_max_penalty,
            value(instance.Total_Max_Flow_Violation_Penalty_Cost),
            delta=1e-6 * abs(expected_max_penalty),
        )
        self.assertGreater(expected_max_penalty, 0)

        # Horizon-level min and max flow violation penalties
        expected_hrz_min_penalty = sum(
            instance.allow_water_link_hrz_min_flow_violation[wl]
            * instance.hrz_min_flow_violation_penalty_cost_per_hour[wl]
            * sum(
                instance.hrs_in_tmp[tmp]
                for tmp in instance.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            * instance.number_years_represented[
                instance.period[instance.last_hrz_tmp[bt, hrz]]
            ]
            * instance.discount_factor[instance.period[instance.last_hrz_tmp[bt, hrz]]]
            for (wl, bt, hrz) in instance.WATER_LINKS_W_BT_HRZ_MIN_FLOW_CONSTRAINT
        )
        self.assertAlmostEqual(
            expected_hrz_min_penalty,
            value(instance.Total_Hrz_Min_Flow_Violation_Penalty_Cost),
            delta=1e-6 * abs(expected_hrz_min_penalty),
        )
        self.assertGreater(expected_hrz_min_penalty, 0)

        expected_hrz_max_penalty = sum(
            instance.allow_water_link_hrz_max_flow_violation[wl]
            * instance.hrz_max_flow_violation_penalty_cost_per_hour[wl]
            * sum(
                instance.hrs_in_tmp[tmp]
                for tmp in instance.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
            )
            * instance.number_years_represented[
                instance.period[instance.last_hrz_tmp[bt, hrz]]
            ]
            * instance.discount_factor[instance.period[instance.last_hrz_tmp[bt, hrz]]]
            for (wl, bt, hrz) in instance.WATER_LINKS_W_BT_HRZ_MAX_FLOW_CONSTRAINT
        )
        self.assertAlmostEqual(
            expected_hrz_max_penalty,
            value(instance.Total_Hrz_Max_Flow_Violation_Penalty_Cost),
            delta=1e-6 * abs(expected_hrz_max_penalty),
        )
        self.assertGreater(expected_hrz_max_penalty, 0)


if __name__ == "__main__":
    unittest.main()
