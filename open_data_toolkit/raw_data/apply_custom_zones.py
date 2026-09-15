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
Apply Custom Zones
******************

Fill the ``custom_zone`` column of the ``raw_data_eia_baa_codes`` BA map
from a user-provided BA-to-zone CSV, enabling the ``custom`` load-zone
level: any grouping of BAs into zones (e.g. a six-zone WECC bubble
aggregation) instead of the map's built-in EIA930 region/interconnect
columns. All the load-zone-level machinery — project load zones and
aggregated-project naming, the system load zones, the transmission
topology (parallel BA pairs collapse into one line per custom-zone pair,
intra-zone links drop), and the NULL-zone scope guard — then works at
the custom level unchanged.

The CSV needs a BA-code column (``baa`` or ``ba``) and a ``zone``
column; other columns are ignored, except that rows with a non-empty
``eia930_subregion`` column (sub-BA detail, which a BA-level map cannot
represent) are skipped with a note. Each run RESETS the column first, so
the CSV is the complete mapping, reruns are idempotent, and switching
zone maps is just re-running with a different CSV. BAs the CSV does not
cover keep a NULL ``custom_zone`` and are excluded at the custom level
(the consuming steps warn about in-footprint exclusions); CSV rows whose
BA is not in the map — e.g. foreign external zones — are reported and
skipped.

The step adds the ``custom_zone`` column to raw databases created before
it existed, so no rebuild is needed.

Run this step after ``gridpath_load_raw_data`` (and
``gridpath_patch_eia_baa_codes``) and before any to-input-csvs step that
uses ``--load_zone_level custom``.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step apply_custom_zones --settings_csv PATH/TO/SETTINGS/CSV

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
* custom_zone_csv (path to the BA-to-zone CSV)

"""

import sys
from argparse import ArgumentParser

import pandas as pd

from db.common_functions import connect_to_database
from gridpath.common_functions import get_version_parser


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="./open_data_raw.db")
    parser.add_argument(
        "-czcsv",
        "--custom_zone_csv",
        required=True,
        help="CSV mapping BAs to custom zones: a 'baa' (or 'ba') column "
        "and a 'zone' column; other columns are ignored, and rows with a "
        "non-empty 'eia930_subregion' column are skipped (sub-BA detail "
        "cannot be represented in a BA-level map).",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def read_custom_zone_csv(custom_zone_csv):
    """
    Read and validate the BA-to-zone CSV: returns ({baa: zone},
    n_subregion_rows_skipped). Raises ValueError on a missing BA/zone
    column, an empty zone value, or a BA mapped to two different zones
    (duplicate rows with the SAME zone are tolerated).
    """
    df = pd.read_csv(custom_zone_csv, dtype=str, keep_default_na=False)

    ba_column = next((c for c in ("baa", "ba") if c in df.columns), None)
    if ba_column is None or "zone" not in df.columns:
        raise ValueError(
            f"{custom_zone_csv} must have a 'baa' (or 'ba') column and a "
            f"'zone' column; found: {', '.join(df.columns)}."
        )

    n_subregion_rows = 0
    if "eia930_subregion" in df.columns:
        subregion_rows = df["eia930_subregion"] != ""
        n_subregion_rows = int(subregion_rows.sum())
        df = df[~subregion_rows]

    zones_by_ba = {}
    for row in df.itertuples():
        baa = getattr(row, ba_column).strip()
        zone = row.zone.strip()
        if not baa:
            continue
        if not zone:
            raise ValueError(
                f"{custom_zone_csv}: BA '{baa}' has an empty zone value — "
                f"drop the row to leave the BA unmapped (excluded at the "
                f"custom level) or give it a zone."
            )
        if baa in zones_by_ba and zones_by_ba[baa] != zone:
            raise ValueError(
                f"{custom_zone_csv}: BA '{baa}' is mapped to two different "
                f"zones ('{zones_by_ba[baa]}' and '{zone}')."
            )
        zones_by_ba[baa] = zone

    return zones_by_ba, n_subregion_rows


def apply_custom_zones(conn, zones_by_ba, quiet=False):
    """
    Ensure the custom_zone column exists on raw_data_eia_baa_codes (added
    in place on raw databases that predate it), RESET it, and fill it
    from *zones_by_ba*. Returns (n_mapped, csv_bas_not_in_map).
    """
    c = conn.cursor()

    columns = {row[1] for row in c.execute("PRAGMA table_info(raw_data_eia_baa_codes)")}
    if "custom_zone" not in columns:
        c.execute("ALTER TABLE raw_data_eia_baa_codes ADD COLUMN custom_zone TEXT")
        if not quiet:
            print(
                "Added the custom_zone column to raw_data_eia_baa_codes "
                "(this raw database predates it)."
            )

    c.execute("UPDATE raw_data_eia_baa_codes SET custom_zone = NULL")

    n_mapped = 0
    csv_bas_not_in_map = []
    for baa, zone in zones_by_ba.items():
        c.execute(
            "UPDATE raw_data_eia_baa_codes SET custom_zone = ? WHERE baa = ?",
            (zone, baa),
        )
        if c.rowcount:
            n_mapped += 1
        else:
            csv_bas_not_in_map.append(baa)

    conn.commit()

    return n_mapped, csv_bas_not_in_map


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    zones_by_ba, n_subregion_rows = read_custom_zone_csv(
        custom_zone_csv=parsed_args.custom_zone_csv
    )

    conn = connect_to_database(db_path=parsed_args.database)
    try:
        n_mapped, csv_bas_not_in_map = apply_custom_zones(
            conn=conn, zones_by_ba=zones_by_ba, quiet=parsed_args.quiet
        )
        n_unmapped = (
            conn.cursor()
            .execute(
                "SELECT COUNT(*) FROM raw_data_eia_baa_codes "
                "WHERE custom_zone IS NULL"
            )
            .fetchone()[0]
        )
    finally:
        conn.close()

    if not parsed_args.quiet:
        zones = sorted(set(zones_by_ba.values()))
        print(
            f"Custom zones applied: {n_mapped} BAs mapped to "
            f"{len(zones)} zones ({', '.join(zones)}); {n_unmapped} map "
            f"BAs left unmapped (excluded at load-zone level 'custom')."
        )
        if n_subregion_rows:
            print(
                f"Note: skipped {n_subregion_rows} rows with a non-empty "
                f"eia930_subregion — sub-BA detail cannot be represented "
                f"in the BA-level map."
            )
        if csv_bas_not_in_map:
            print(
                f"Note: {len(csv_bas_not_in_map)} CSV BAs are not in "
                f"raw_data_eia_baa_codes and were skipped (expected for "
                f"external zones): {', '.join(csv_bas_not_in_map)}."
            )


if __name__ == "__main__":
    main()
