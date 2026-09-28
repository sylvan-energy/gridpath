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
import pandas as pd
import sys
import unittest

from tests.common_functions import create_abstract_model, add_components_and_load_data

TEST_DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "test_data")

# Import prerequisite modules
PREREQUISITE_MODULE_NAMES = [
    "temporal.operations.timepoints",
    "temporal.investment.periods",
    "temporal.operations.horizons",
    "geography.load_zones",
    "geography.markets",
    "system.markets.prices",
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
    "system.markets.market_participation",
]
NAME_OF_MODULE_BEING_TESTED = "system.markets.volume"
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
    volume = MODULE_BEING_TESTED
except ImportError:
    print("ERROR! Couldn't import module " + NAME_OF_MODULE_BEING_TESTED + " to test.")


class TestMarketVolume(unittest.TestCase):
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

    def test_initialized_components(self):
        """
        Create components; check they are initialized with data as expected
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

        # Set: MARKET_GROUP_MARKETS and the sets derived from it
        groups_df = pd.read_csv(
            os.path.join(TEST_DATA_DIRECTORY, "inputs", "market_groups.tab"), sep="\t"
        )
        expected_group_markets = sorted(
            groups_df[["market_group", "market"]].itertuples(index=False, name=None)
        )
        self.assertListEqual(
            expected_group_markets, sorted(instance.MARKET_GROUP_MARKETS)
        )
        self.assertListEqual(
            sorted(set(groups_df["market_group"])), sorted(instance.MARKET_GROUPS)
        )
        for group, members in groups_df.groupby("market_group"):
            self.assertListEqual(
                sorted(members["market"]),
                sorted(instance.MARKETS_BY_MARKET_GROUP[group]),
                msg=group,
            )

        # The three limit resolutions: the fixture file, the index columns
        # the set is keyed on, and the params with their defaults
        resolutions = [
            (
                "market_volume_tmp.tab",
                "MARKET_GROUP_TMPS_W_LIMIT",
                ["timepoint"],
                [
                    ("max_market_sales", float("inf")),
                    ("max_market_purchases", float("inf")),
                    ("max_final_market_sales", float("inf")),
                    ("max_final_market_purchases", float("inf")),
                ],
            ),
            (
                "market_volume_hrz.tab",
                "MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT",
                ["balancing_type_horizon", "horizon"],
                [
                    ("max_market_sales_in_hrz", float("inf")),
                    ("max_market_purchases_in_hrz", float("inf")),
                    ("max_market_sales_in_hrz_include_storage_losses", 0),
                ],
            ),
            (
                "market_volume_prd.tab",
                "MARKET_GROUP_PRDS_W_LIMIT",
                ["period"],
                [
                    ("max_market_sales_in_prd", float("inf")),
                    ("max_market_purchases_in_prd", float("inf")),
                    ("max_market_sales_in_prd_include_storage_losses", 0),
                ],
            ),
        ]

        limited_groups = set()
        for filename, set_name, index_columns, params in resolutions:
            df = pd.read_csv(
                os.path.join(TEST_DATA_DIRECTORY, "inputs", filename), sep="\t"
            )
            key_columns = ["market_group"] + index_columns
            # Keep the file's row order so each index lines up with its
            # limits below
            row_idxs = list(df[key_columns].itertuples(index=False, name=None))
            self.assertListEqual(
                sorted(row_idxs), sorted(getattr(instance, set_name)), msg=set_name
            )
            limited_groups |= set(df["market_group"])

            for param_name, default in params:
                # The '.' placeholders make the limit columns object dtype;
                # coerce so an unspecified limit reads as NaN and maps to
                # the model's default
                limits = pd.to_numeric(df[param_name], errors="coerce")
                expected = OrderedDict(
                    sorted(
                        {
                            idx: (default if pd.isna(limit) else limit)
                            for idx, limit in zip(row_idxs, limits)
                        }.items()
                    )
                )
                actual = OrderedDict(
                    sorted(
                        {
                            idx: getattr(instance, param_name)[idx]
                            for idx in getattr(instance, set_name)
                        }.items()
                    )
                )
                self.assertDictEqual(expected, actual, msg=param_name)

        # Set: MARKET_GROUPS_W_LIMITS, the groups the position expressions
        # are built for
        self.assertListEqual(
            sorted(limited_groups), sorted(instance.MARKET_GROUPS_W_LIMITS)
        )

        # Set: MARKET_VOLUME_LIMIT_STOR_PRJS, the projects whose losses the
        # include_storage_losses limits are based on
        expected_stor_prjs = sorted(
            prj for prj in instance.PROJECTS if instance.operational_type[prj] == "stor"
        )
        self.assertListEqual(
            expected_stor_prjs, sorted(instance.MARKET_VOLUME_LIMIT_STOR_PRJS)
        )
        self.assertGreater(
            len(expected_stor_prjs),
            0,
            msg="the fixture must have a 'stor' project for the storage-loss "
            "term of the sales limits to be exercised",
        )

        # Constraints are built only where a limit is finite
        for constraint_name, set_name, param_name in [
            (
                "Max_Market_Group_Sales_Constraint",
                "MARKET_GROUP_TMPS_W_LIMIT",
                "max_market_sales",
            ),
            (
                "Max_Market_Group_Final_Sales_Constraint",
                "MARKET_GROUP_TMPS_W_LIMIT",
                "max_final_market_sales",
            ),
            (
                "Max_Market_Group_Sales_in_Hrz_Constraint",
                "MARKET_GROUP_BLN_TYPE_HRZS_W_LIMIT",
                "max_market_sales_in_hrz",
            ),
            (
                "Max_Market_Group_Purchases_in_Prd_Constraint",
                "MARKET_GROUP_PRDS_W_LIMIT",
                "max_market_purchases_in_prd",
            ),
        ]:
            self.assertListEqual(
                sorted(
                    idx
                    for idx in getattr(instance, set_name)
                    if getattr(instance, param_name)[idx] != float("inf")
                ),
                sorted(getattr(instance, constraint_name)),
                msg=constraint_name,
            )

        # A group's position is the sum over the markets it contains, so the
        # group of every hub covers every (load zone, market) pair
        self.assertListEqual(
            sorted(instance.LZ_MARKETS),
            sorted(volume.lz_markets_in_group(instance, "All_Hubs")),
        )


if __name__ == "__main__":
    unittest.main()
