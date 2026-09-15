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
Per-unit manual overrides: the user_defined_unit_overrides table lets a
study force individual plants or generators into or out of the fleet and
carve them into their own aggregations and load zones, overriding what
the automated pipeline stages would decide. Like
user_defined_baa_overrides, this module ships only the MECHANISM — the
table is empty by default (a verified no-op) and the study's rows are
user data, loaded via the gridpath_load_raw_data manifest.

One row per plant/generator (generator_id '*' = every generator at the
plant; a generator-specific row wins over a '*' row, per column), with
three independent, nullable override columns:

* ``include`` — 1 force-includes the unit (it bypasses the
  characteristic filters: status/retirement selection, the planned-date
  window, the behind-the-meter exclusion), 0 force-excludes it, NULL
  leaves membership to the filters. A force-included unit must still
  have a user_defined_eia_gridpath_key row (its capacity/operational
  types come from there) and still pass the geographic scope — a unit
  outside the footprint or without a load zone at the chosen level needs
  the BA map fixed (gridpath_patch_eia_baa_codes, the custom-zone CSV)
  or a user_defined_baa_overrides row, not include=1. Step-specific
  filters (an operational-type filter, the EIA860M as-of-date snapshot)
  also still apply.
* ``aggregation`` — replaces the GEOGRAPHIC token in the unit's
  aggregate project name (e.g. ``Hydro_Hoover`` instead of
  ``Hydro_WALC``), carving the unit out of its map-derived aggregate.
  Whether the unit is aggregated at all remains governed by the
  project_aggregation mode and the key's agg_project column — under mode
  'none' every unit keeps its per-unit name and this column is inert.
* ``load_zone`` — replaces the unit's map-derived load zone in the
  project load-zone assignment (it does not change the unit's BA, so
  the footprint scope still applies). The value must match the zone
  vocabulary of the study's load-zone level — an override CSV written
  for one level does not transfer to another. A zone that exists only
  through overrides (a carve-out modeled as its own zone) will not be
  among the system zones the EIA930 load-zone step derives; the
  project-zone cross-check warns about it, and the zone must be added
  to the system side by hand.

The three columns compose per unit: e.g. an ``aggregation`` +
``load_zone`` pair carves a plant into its own aggregate in a specific
zone, while ``include`` alone just pins membership. Every unit that ends
up in one aggregated project must resolve to ONE load zone —
check_one_zone_per_project enforces this where zones are written (the
load-zones step) and audited.

The table is created empty on first use against a raw database that
predates it (see ensure_unit_overrides_table), so existing databases
keep working without a rebuild.
"""

from open_data_toolkit.geographic_scope import get_load_zone_str

# Mirror of the user_defined_unit_overrides DDL in raw_data_db_schema.sql
# (as CREATE TABLE IF NOT EXISTS, so pre-existing raw databases get the
# table on first use) — keep the two in sync
UNIT_OVERRIDES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS user_defined_unit_overrides
(
    plant_id_eia INTEGER,
    generator_id TEXT,
    include      INTEGER,
    aggregation  TEXT,
    load_zone    TEXT,
    reason       TEXT,
    PRIMARY KEY (plant_id_eia, generator_id)
);
"""


def ensure_unit_overrides_table(conn):
    """
    Create the (empty) user_defined_unit_overrides table if this raw
    database predates it, so the override subqueries never fail on a
    missing table. A rebuild is deliberately NOT required here — unlike a
    raw-data schema change, an empty overrides table is exactly
    equivalent to the table never having existed.
    """
    conn.execute(UNIT_OVERRIDES_TABLE_DDL)
    conn.commit()


def get_unit_override_sql(column, generators_table="raw_data_eia860_generators"):
    """
    Correlated scalar subquery resolving the *column* override
    ('include', 'aggregation', or 'load_zone') for the current unit of
    *generators_table*: the most specific row with a value in that column
    — a generator-specific row beats a '*' (whole-plant) row — or NULL
    when no row overrides that column. Overlapping rows can never
    duplicate generator rows (same pattern as MANUAL_BAA_OVERRIDE_SQL),
    and the per-column IS NOT NULL filter makes the three override
    columns independently composable across rows.
    """
    if column not in ("include", "aggregation", "load_zone"):
        raise ValueError(f"Unknown unit-override column '{column}'.")

    return f"""(
                SELECT o.{column}
                FROM user_defined_unit_overrides o
                WHERE o.plant_id_eia = {generators_table}.plant_id_eia
                AND (o.generator_id = {generators_table}.generator_id
                     OR o.generator_id = '*')
                AND o.{column} IS NOT NULL
                ORDER BY (o.generator_id = '*')
                LIMIT 1
            )"""


def get_project_load_zone_str(
    load_zone_level, footprint, generators_table="raw_data_eia860_generators"
):
    """
    The load zone assigned to a unit's project: its load_zone override if
    one exists, else the map-derived zone at the chosen level (see
    get_load_zone_str). Only the PROJECT-side zone assignment consults
    the overrides — the system and transmission steps stay purely
    map-driven.
    """
    map_zone_str = get_load_zone_str(
        load_zone_level=load_zone_level, footprint=footprint
    )
    override_sql = get_unit_override_sql(
        column="load_zone", generators_table=generators_table
    )
    return f"COALESCE({override_sql}, {map_zone_str})"


def check_one_zone_per_project(project_load_zones_df):
    """
    Fail loudly when any project maps to more than one load zone — the
    invariant every zone-assignment path must keep, whatever breaks it
    (an aggregation override without a matching load_zone override on
    every unit of the carve-out, a load_zone override on only some units
    of an aggregate, a future naming bug). Call BEFORE writing the
    load-zone CSV: a multi-zone project would otherwise ride into the
    inputs as duplicate rows and only fail at the GridPath database
    port. Expects a dataframe with 'project' and 'load_zone' columns;
    returns the offending projects (empty list on success).
    """
    zones_per_project = project_load_zones_df.groupby("project")["load_zone"].nunique()
    offenders = sorted(zones_per_project[zones_per_project > 1].index)
    if offenders:
        raise ValueError(
            f"Project(s) mapping to more than one load zone: "
            f"{', '.join(str(p) for p in offenders)}. Every unit of an "
            f"aggregated project must resolve to the same zone — check "
            f"the user_defined_unit_overrides rows for these units "
            f"(an 'aggregation' carve-out usually needs the same "
            f"'load_zone' on every row of the carve-out)."
        )
    return offenders
