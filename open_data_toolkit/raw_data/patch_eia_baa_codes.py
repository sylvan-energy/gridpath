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

"""
Patch EIA BA Map
****************

Fill documented source-data gaps in the ``raw_data_eia_baa_codes`` BA map
(PUDL's ``core_eia__codes_balancing_authorities``). BAs with no value in a
load-zone level's map column are excluded from that level's zones, and BAs
missing from the map entirely drop out of the transmission topology — so
these gaps silently remove real capacity and interchange links. The
patched values were verified against EIA's EIA-930 reference tables
(July 2026):

* ``GRID`` (Gridforce Energy Management; generation-only): the source has
  its interconnect (western) but no region — EIA's reference tables say
  NW. Without the patch, its 930A-assigned units (~1.9 GW) drop out at the
  'region' load-zone level.
* ``AVRN`` (Avangrid Renewables; generation-only): region NW in the
  source, but no interconnect — western (Pacific Northwest).
* ``GLHB`` (GridLiance, retired 2022; generation-only): region MIDW in the
  source, but no interconnect — eastern (Midwest).
* ``SIKE`` (Sikeston Board of Municipal Utilities; generation-only,
  active since June 2025): missing from the source table entirely (it
  lags EIA), so its interchange links to AECI/MISO/SPA/SWPP silently
  drop out of the transmission topology. Inserted with EIA's reference
  values (region MIDW, eastern interconnect).

The islanded Hawaii/Alaska BAs (HECO, GRIS, CEA) are deliberately NOT
patched: they do not participate in EIA-930 at all, so leaving their
region/interconnect empty correctly keeps them out of interchange-based
footprints.

Updates only fill NULL columns and the SIKE row is only inserted if
absent, so reruns are no-ops and a future PUDL release that fixes the
source data takes precedence over the patch.

Run this step right after ``gridpath_load_raw_data`` and before any of
the to-input-csvs steps — they all scope footprints and assign load zones
through the map.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step patch_eia_baa_codes --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database table has been
populated:

* raw_data_eia_baa_codes

=========
Settings
=========

* database

"""

import sys
from argparse import ArgumentParser

from db.common_functions import connect_to_database
from gridpath.common_functions import get_version_parser

# (baa, column, value): fill NULL *column* for *baa*
BAA_UPDATE_PATCHES = [
    ("GRID", "region", "NW"),
    ("AVRN", "interconnect", "western"),
    ("GLHB", "interconnect", "eastern"),
]

# Full rows for BAs missing from the source table, in raw_data_eia_baa_codes
# column order: (baa, region, region_name, interconnect, retirement_date,
# is_generation_only, timezone)
BAA_INSERT_PATCHES = [
    ("SIKE", "MIDW", "Midwest", "eastern", None, 1, "America/Chicago"),
]


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="./open_data_raw.db")

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def apply_baa_map_patches(conn, quiet=False):
    """
    Apply the documented BA-map patches: fill the NULL columns of
    BAA_UPDATE_PATCHES and insert any missing BAA_INSERT_PATCHES rows.
    Reports what was applied vs already in place; returns the number of
    rows changed.
    """
    c = conn.cursor()
    n_changed = 0

    for baa, column, value in BAA_UPDATE_PATCHES:
        c.execute(
            f"UPDATE raw_data_eia_baa_codes SET {column} = ? "
            f"WHERE baa = ? AND {column} IS NULL",
            (value, baa),
        )
        n_changed += c.rowcount
        if not quiet:
            outcome = (
                f"set to '{value}'"
                if c.rowcount
                else "already set in the source data (patch skipped)"
            )
            print(f"BA map patch: {baa} {column} {outcome}.")

    for row in BAA_INSERT_PATCHES:
        c.execute(
            "INSERT OR IGNORE INTO raw_data_eia_baa_codes "
            "(baa, region, region_name, interconnect, retirement_date, "
            "is_generation_only, timezone) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            row,
        )
        n_changed += c.rowcount
        if not quiet:
            outcome = (
                "inserted"
                if c.rowcount
                else "already in the source data (patch skipped)"
            )
            print(f"BA map patch: {row[0]} row {outcome}.")

    conn.commit()

    return n_changed


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Patching the EIA BA map")

    conn = connect_to_database(db_path=parsed_args.database)

    apply_baa_map_patches(conn=conn, quiet=parsed_args.quiet)

    conn.close()


if __name__ == "__main__":
    main()
