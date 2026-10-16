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
    "transmission",
    "transmission.capacity",
    "transmission.capacity.capacity_types",
    "transmission.capacity.capacity",
    "transmission.availability.availability",
    "transmission.operations.operational_types",
    "transmission.operations.operations",
    "geography.transmission_target_zones",
    "system.policy.transmission_targets.transmission_target",
]
NAME_OF_MODULE_BEING_TESTED = (
    "transmission.operations.transmission_target_contributions"
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


class TestTxTargetContributions(unittest.TestCase):
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

        # Set: TRANSMISSION_TARGET_TX_LINES
        expected_tx_lines = sorted(["Tx_binary_1"])
        actual_tx_lines = sorted(tx for tx in instance.TRANSMISSION_TARGET_TX_LINES)
        self.assertListEqual(expected_tx_lines, actual_tx_lines)

        # Param: transmission_target_zone
        expected_zone = OrderedDict(sorted({"Tx_binary_1": "Tx_Target_Zone1"}.items()))
        actual_zone = OrderedDict(
            sorted(
                {
                    tx: instance.transmission_target_zone[tx]
                    for tx in instance.TRANSMISSION_TARGET_TX_LINES
                }.items()
            )
        )
        self.assertDictEqual(expected_zone, actual_zone)

        # Param: contributes_net_flow_to_tx_target
        expected_net_flow = OrderedDict(sorted({"Tx_binary_1": 1}.items()))
        actual_net_flow = OrderedDict(
            sorted(
                {
                    tx: instance.contributes_net_flow_to_tx_target[tx]
                    for tx in instance.TRANSMISSION_TARGET_TX_LINES
                }.items()
            )
        )
        self.assertDictEqual(expected_net_flow, actual_net_flow)

        # Set: TRANSMISSION_TARGET_TX_OPR_TMPS
        expect_tx_op_tmp = sorted(
            [
                ("Tx_binary_1", 20200101),
                ("Tx_binary_1", 20200102),
                ("Tx_binary_1", 20200103),
                ("Tx_binary_1", 20200104),
                ("Tx_binary_1", 20200105),
                ("Tx_binary_1", 20200106),
                ("Tx_binary_1", 20200107),
                ("Tx_binary_1", 20200108),
                ("Tx_binary_1", 20200109),
                ("Tx_binary_1", 20200110),
                ("Tx_binary_1", 20200111),
                ("Tx_binary_1", 20200112),
                ("Tx_binary_1", 20200113),
                ("Tx_binary_1", 20200114),
                ("Tx_binary_1", 20200115),
                ("Tx_binary_1", 20200116),
                ("Tx_binary_1", 20200117),
                ("Tx_binary_1", 20200118),
                ("Tx_binary_1", 20200119),
                ("Tx_binary_1", 20200120),
                ("Tx_binary_1", 20200121),
                ("Tx_binary_1", 20200122),
                ("Tx_binary_1", 20200123),
                ("Tx_binary_1", 20200124),
                ("Tx_binary_1", 20200201),
                ("Tx_binary_1", 20200202),
                ("Tx_binary_1", 20200203),
                ("Tx_binary_1", 20200204),
                ("Tx_binary_1", 20200205),
                ("Tx_binary_1", 20200206),
                ("Tx_binary_1", 20200207),
                ("Tx_binary_1", 20200208),
                ("Tx_binary_1", 20200209),
                ("Tx_binary_1", 20200210),
                ("Tx_binary_1", 20200211),
                ("Tx_binary_1", 20200212),
                ("Tx_binary_1", 20200213),
                ("Tx_binary_1", 20200214),
                ("Tx_binary_1", 20200215),
                ("Tx_binary_1", 20200216),
                ("Tx_binary_1", 20200217),
                ("Tx_binary_1", 20200218),
                ("Tx_binary_1", 20200219),
                ("Tx_binary_1", 20200220),
                ("Tx_binary_1", 20200221),
                ("Tx_binary_1", 20200222),
                ("Tx_binary_1", 20200223),
                ("Tx_binary_1", 20200224),
                ("Tx_binary_1", 20300101),
                ("Tx_binary_1", 20300102),
                ("Tx_binary_1", 20300103),
                ("Tx_binary_1", 20300104),
                ("Tx_binary_1", 20300105),
                ("Tx_binary_1", 20300106),
                ("Tx_binary_1", 20300107),
                ("Tx_binary_1", 20300108),
                ("Tx_binary_1", 20300109),
                ("Tx_binary_1", 20300110),
                ("Tx_binary_1", 20300111),
                ("Tx_binary_1", 20300112),
                ("Tx_binary_1", 20300113),
                ("Tx_binary_1", 20300114),
                ("Tx_binary_1", 20300115),
                ("Tx_binary_1", 20300116),
                ("Tx_binary_1", 20300117),
                ("Tx_binary_1", 20300118),
                ("Tx_binary_1", 20300119),
                ("Tx_binary_1", 20300120),
                ("Tx_binary_1", 20300121),
                ("Tx_binary_1", 20300122),
                ("Tx_binary_1", 20300123),
                ("Tx_binary_1", 20300124),
                ("Tx_binary_1", 20300201),
                ("Tx_binary_1", 20300202),
                ("Tx_binary_1", 20300203),
                ("Tx_binary_1", 20300204),
                ("Tx_binary_1", 20300205),
                ("Tx_binary_1", 20300206),
                ("Tx_binary_1", 20300207),
                ("Tx_binary_1", 20300208),
                ("Tx_binary_1", 20300209),
                ("Tx_binary_1", 20300210),
                ("Tx_binary_1", 20300211),
                ("Tx_binary_1", 20300212),
                ("Tx_binary_1", 20300213),
                ("Tx_binary_1", 20300214),
                ("Tx_binary_1", 20300215),
                ("Tx_binary_1", 20300216),
                ("Tx_binary_1", 20300217),
                ("Tx_binary_1", 20300218),
                ("Tx_binary_1", 20300219),
                ("Tx_binary_1", 20300220),
                ("Tx_binary_1", 20300221),
                ("Tx_binary_1", 20300222),
                ("Tx_binary_1", 20300223),
                ("Tx_binary_1", 20300224),
            ]
        )
        actual_tx_op_tmp = sorted(
            [(tx, tmp) for (tx, tmp) in instance.TRANSMISSION_TARGET_TX_OPR_TMPS]
        )
        self.assertListEqual(expect_tx_op_tmp, actual_tx_op_tmp)

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
        for var, val in (
            (instance.Transmission_Target_Energy_MW_Pos_Dir, 1.0),
            (instance.Transmission_Target_Energy_MW_Neg_Dir, 2.0),
            (instance.Transmission_Target_Net_Energy_MW_Pos_Dir, 3.0),
            (instance.Transmission_Target_Net_Energy_MW_Neg_Dir, 4.0),
        ):
            for v in var.values():
                v.set_value(val)

        tx_tmps = sorted(instance.TRANSMISSION_TARGET_TX_OPR_TMPS)
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

        # Lines that contribute net flows report the net energy variables
        expected_rows = [
            (
                tx,
                tmp,
                instance.transmission_target_zone[tx],
                3.0 if instance.contributes_net_flow_to_tx_target[tx] else 1.0,
                4.0 if instance.contributes_net_flow_to_tx_target[tx] else 2.0,
            )
            for (tx, tmp) in tx_tmps
        ]
        actual_rows = conn.execute("""SELECT transmission_line, timepoint,
            transmission_target_zone,
            transmission_target_energy_positive_direction_mw,
            transmission_target_energy_negative_direction_mw
            FROM results_transmission_timepoint
            ORDER BY transmission_line, timepoint""").fetchall()
        self.assertListEqual(expected_rows, actual_rows)


if __name__ == "__main__":
    unittest.main()
