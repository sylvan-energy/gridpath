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


from collections import OrderedDict
from importlib import import_module
import os.path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest

import pandas as pd

from gridpath.auxiliary.db_interface import import_csv
from gridpath.transmission import TX_TIMEPOINT_DF
from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")
DB_SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "db", "db_schema.sql"
)

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.carbon_cap_zones",
    "system.policy.carbon_cap.carbon_cap",
    "transmission",
    "transmission.capacity",
    "transmission.capacity.capacity_types",
    "transmission.capacity.capacity",
    "transmission.availability.availability",
    "transmission.operations.operational_types",
    "transmission.operations.operations",
]
NAME_OF_MODULE_BEING_TESTED = "transmission.operations.hurdle_costs_by_timepoint"
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


class TestTxHurdleCosts(unittest.TestCase):
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

        # Param: hurdle_rate_pos_dir_per_mwh
        data = []
        for period in ["2020", "2030"]:
            for day in ["01", "02"]:
                for hour in range(24):
                    str_hour = "0" + str(hour + 1)
                    timepoint = int(f"{period}{day}{str_hour[-2:]}")
                    data = data + [
                        (("Tx1", timepoint), 5),
                        (("Tx2", timepoint), 0),
                        (("Tx3", timepoint), 0),
                        (
                            ("Tx_New", timepoint),
                            0 if str(timepoint).startswith("2020") else 1,
                        ),
                        (("Tx_binary_1", timepoint), 0),
                    ]
        expected_hurdle_rate_pos = OrderedDict(sorted(data))
        actual_hurdle_rate_pos = OrderedDict(
            sorted(
                [
                    ((tx, tmp), instance.hurdle_rate_by_tmp_pos_dir_per_mwh[tx, tmp])
                    for (tx, tmp) in instance.TX_OPR_TMPS
                ]
            )
        )
        self.assertDictEqual(expected_hurdle_rate_pos, actual_hurdle_rate_pos)

        # Param: hurdle_rate_neg_dir_per_mwh
        data = []
        for period in ["2020", "2030"]:
            for day in ["01", "02"]:
                for hour in range(24):
                    str_hour = "0" + str(hour + 1)
                    timepoint = int(f"{period}{day}{str_hour[-2:]}")
                    data = data + [
                        (("Tx1", timepoint), 6),
                        (("Tx2", timepoint), 0),
                        (("Tx3", timepoint), 0),
                        (
                            ("Tx_New", timepoint),
                            0 if str(timepoint).startswith("2020") else 1,
                        ),
                        (("Tx_binary_1", timepoint), 0),
                    ]

        expected_hurdle_rate_neg = OrderedDict(sorted(data))
        actual_hurdle_rate_neg = OrderedDict(
            sorted(
                [
                    ((tx, tmp), instance.hurdle_rate_by_tmp_neg_dir_per_mwh[tx, tmp])
                    for (tx, tmp) in instance.TX_OPR_TMPS
                ]
            )
        )
        self.assertDictEqual(expected_hurdle_rate_neg, actual_hurdle_rate_neg)

    def test_export_results_import_into_database(self):
        """
        Test that the transmission-timepoint results exported by this module
        can be imported into the results_transmission_timepoint table
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
        for v in instance.Hurdle_Cost_By_Tmp_Pos_Dir.values():
            v.set_value(1.5)
        for v in instance.Hurdle_Cost_By_Tmp_Neg_Dir.values():
            v.set_value(2.5)

        tx_tmps = sorted(instance.TX_OPR_TMPS)
        d = SimpleNamespace()
        setattr(
            d,
            TX_TIMEPOINT_DF,
            pd.DataFrame(
                index=pd.MultiIndex.from_tuples(
                    tx_tmps, names=["transmission_line", "timepoint"]
                )
            ),
        )
        MODULE_BEING_TESTED.export_results(
            scenario_directory="",
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
            m=instance,
            d=d,
        )

        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with open(DB_SCHEMA_FILE) as f:
            conn.executescript(f.read())

        with tempfile.TemporaryDirectory() as results_directory:
            getattr(d, TX_TIMEPOINT_DF).to_csv(
                os.path.join(results_directory, "transmission_timepoint.csv")
            )
            import_csv(
                conn=conn,
                cursor=conn.cursor(),
                scenario_id=1,
                weather_iteration="",
                hydro_iteration="",
                availability_iteration="",
                subproblem="",
                stage="",
                quiet=True,
                results_directory=results_directory,
                which_results="transmission_timepoint",
            )

        expected_rows = [(tx, tmp, 1.5, 2.5) for (tx, tmp) in tx_tmps]
        actual_rows = conn.execute("""SELECT transmission_line, timepoint,
            hurdle_cost_by_timepoint_positive_direction, hurdle_cost_by_timepoint_negative_direction
            FROM results_transmission_timepoint
            ORDER BY transmission_line, timepoint""").fetchall()
        self.assertListEqual(expected_rows, actual_rows)
