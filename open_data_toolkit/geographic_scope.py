# Copyright 2016-2024 Blue Marble Analytics LLC.
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
Geographic scope: which balancing authorities are in the study footprint,
and what load zone each one maps to at the chosen load-zone level. This is
the first filtering stage of the EIA-derived input pipeline — everything
here is about WHERE a generator (or interchange link, or load) is, based
on the raw_data_eia_baa_codes BA map; nothing here looks at generator
characteristics (see open_data_toolkit.project.fleet.fleet_filters) or at how units
are aggregated into projects (see open_data_toolkit.project.fleet.aggregation). The
project, system, and transmission steps all consume this module, which is
why it lives at the open_data_toolkit level.
"""

# The raw_data_eia_baa_codes column holding the load zone at each
# load-zone level; the 'all' level uses no map column — the whole
# (footprint-filtered) dataset becomes a single zone named after the
# --footprint value. The 'custom' level reads the user-defined
# custom_zone column, populated from a BA-to-zone CSV by
# gridpath_apply_custom_zones (BAs it leaves NULL are excluded at that
# level, like any NULL zone column).
LOAD_ZONE_LEVEL_COLUMNS = {
    "baa": "baa",
    "region": "region",
    "interconnect": "interconnect",
    "custom": "custom_zone",
}

# The accepted --load_zone_level values, single-sourced so the steps'
# choices lists can't drift from the column map above
LOAD_ZONE_LEVEL_CHOICES = tuple(LOAD_ZONE_LEVEL_COLUMNS) + ("all",)


def add_footprint_argument(parser):
    """
    Add the shared ``--footprint`` argument — the study scope, applied
    before any aggregation — to a step's argument parser. Single-sourced
    here (like add_load_zone_level_argument) so the setting and its
    --help text can't drift across the steps; it must be set consistently
    across the steps generating one study's inputs.
    """
    parser.add_argument(
        "-fp",
        "--footprint",
        default="western",
        help="The study footprint: an EIA930 region or interconnect value "
        "from the BA map (e.g. 'CAL' or 'western'), or 'all' for no "
        "footprint filter (every mapped BA with a load zone at the chosen "
        "load-zone level). Defaults to 'western'.",
    )


def add_load_zone_level_argument(parser):
    """
    Add the shared ``--load_zone_level`` argument — the zone resolution
    within the footprint — to a step's argument parser. Single-sourced
    here (like add_footprint_argument) so the setting, its choices, and
    its --help text can't drift across the steps; it must be set
    consistently across the steps generating one study's inputs. Steps
    that are zone-agnostic (the fuel and heat-rate steps, whose inputs
    are joined against the portfolio downstream) deliberately do not take
    it.
    """
    parser.add_argument(
        "-lzl",
        "--load_zone_level",
        default="baa",
        choices=list(LOAD_ZONE_LEVEL_CHOICES),
        help="The level at which to assign project load zones and to name "
        "(and thereby aggregate) any aggregated projects (see the "
        "project_aggregation setting): each "
        "generator's BA, or its BA's EIA930 region or interconnect from "
        "the BA map; 'all' makes the whole footprint selected by --footprint "
        "a single zone named after the --footprint value; 'custom' uses the "
        "user-defined zones applied by gridpath_apply_custom_zones (BAs "
        "without a custom zone are excluded). Must be set "
        "consistently across the project-level steps. Defaults to 'baa'.",
    )


def check_custom_zone_level_ready(conn, load_zone_level, footprint):
    """
    Fail loudly when the 'custom' load-zone level is requested but the
    custom_zone column is missing from raw_data_eia_baa_codes (a raw
    database from before the column existed) or no in-footprint BA has a
    value (gridpath_apply_custom_zones was never run against this
    database) — either would otherwise surface as empty outputs or a
    cryptic SQL error. Also warns — regardless of any quiet setting —
    about in-footprint BAs with no custom zone, since they are silently
    excluded at this level. No-op at every other level. Returns the list
    of unmapped in-footprint BAs.
    """
    if load_zone_level != "custom":
        return []

    columns = {
        row[1]
        for row in conn.cursor().execute("PRAGMA table_info(raw_data_eia_baa_codes)")
    }
    if "custom_zone" not in columns:
        raise ValueError(
            "load_zone_level 'custom' needs the custom_zone column on "
            "raw_data_eia_baa_codes, which this raw database predates — "
            "run gridpath_apply_custom_zones (it adds the column and "
            "fills it from your BA-to-zone CSV)."
        )

    in_footprint_sql = (
        "1 = 1" if footprint == "all" else f"'{footprint}' IN (region, interconnect)"
    )
    unmapped = [baa for (baa,) in conn.cursor().execute(f"""
            SELECT baa FROM raw_data_eia_baa_codes
            WHERE {in_footprint_sql} AND custom_zone IS NULL
            ORDER BY baa
            ;
            """)]
    n_mapped = conn.cursor().execute(f"""
        SELECT COUNT(*) FROM raw_data_eia_baa_codes
        WHERE {in_footprint_sql} AND custom_zone IS NOT NULL
        ;
        """).fetchone()[0]
    if n_mapped == 0:
        raise ValueError(
            "load_zone_level 'custom' is requested but no in-footprint BA "
            "has a custom_zone value in raw_data_eia_baa_codes — run "
            "gridpath_apply_custom_zones against this database first."
        )
    if unmapped:
        print(
            f"WARNING: {len(unmapped)} in-footprint BAs have no "
            f"custom_zone in raw_data_eia_baa_codes and are EXCLUDED at "
            f"load-zone level 'custom': {', '.join(unmapped)}. If any "
            f"should be in the model, add them to the custom-zone CSV and "
            f"re-run gridpath_apply_custom_zones."
        )

    return unmapped


def get_footprint_options(conn):
    """
    The values the --footprint argument accepts, from the BA map: a list of
    (footprint_type, footprint, n_bas) tuples — one per distinct EIA930
    region and interconnect in raw_data_eia_baa_codes, ordered by type and
    value. (The special value 'all' — no footprint filter — is always
    accepted and not included here.)
    """
    c = conn.cursor()
    footprint_options = c.execute("""
        SELECT 'interconnect' AS footprint_type,
            interconnect AS footprint,
            COUNT(*) AS n_bas
        FROM raw_data_eia_baa_codes
        WHERE interconnect IS NOT NULL
        GROUP BY interconnect
        UNION ALL
        SELECT 'region', region, COUNT(*)
        FROM raw_data_eia_baa_codes
        WHERE region IS NOT NULL
        GROUP BY region
        ORDER BY footprint_type, footprint
        ;
        """).fetchall()

    return footprint_options


def report_footprint_type(conn, footprint, quiet=False):
    """
    Report which type of footprint the *footprint* value matched in the BA
    map — an EIA930 region or an interconnect (the filter accepts either
    vocabulary without the user having to say which) — or that it is the
    special value 'all' (no footprint filter). A value matching neither
    column is reported loudly regardless of *quiet*, since it scopes every
    query to zero BAs and all outputs will be empty.
    """
    if footprint == "all":
        if not quiet:
            print("Footprint 'all': no footprint filter (all mapped BAs).")
        return

    c = conn.cursor()
    n_region_bas = c.execute(
        "SELECT COUNT(*) FROM raw_data_eia_baa_codes WHERE region = ?",
        (footprint,),
    ).fetchone()[0]
    n_interconnect_bas = c.execute(
        "SELECT COUNT(*) FROM raw_data_eia_baa_codes WHERE interconnect = ?",
        (footprint,),
    ).fetchone()[0]

    if n_region_bas and n_interconnect_bas:
        print(
            f"WARNING: footprint '{footprint}' matches both an EIA930 "
            f"region ({n_region_bas} BAs) and an interconnect "
            f"({n_interconnect_bas} BAs) in the BA map; BAs of both are "
            f"in scope."
        )
    elif n_region_bas:
        if not quiet:
            print(
                f"Footprint '{footprint}' is an EIA930 region "
                f"({n_region_bas} BAs in the BA map)."
            )
    elif n_interconnect_bas:
        if not quiet:
            print(
                f"Footprint '{footprint}' is an interconnect "
                f"({n_interconnect_bas} BAs in the BA map)."
            )
    else:
        print(
            f"WARNING: footprint '{footprint}' matches no EIA930 region or "
            f"interconnect in the BA map (raw_data_eia_baa_codes) — no BAs "
            f"are in scope and all outputs will be empty."
        )


def get_all_lzs_sql(load_zone_str, footprint_scope_sql):
    """
    The system load zones for a footprint: the DISTINCT zones (at the
    chosen level, per *load_zone_str*) of the in-scope BAs observed on
    either side of the EIA930 interchange data. This is the single source
    of the system load-zone set — used both by eia930_load_zone_input_csvs
    to create the load-zone inputs and by the project-side cross-check
    (warn_on_project_load_zones_missing_from_system).
    """
    all_lzs_sql = f"""
        SELECT DISTINCT {load_zone_str} from (
            SELECT DISTINCT balancing_authority_code_eia as baa
            FROM raw_data_eia930_hourly_interchange
            UNION
            SELECT DISTINCT balancing_authority_code_adjacent_eia as ba
            FROM raw_data_eia930_hourly_interchange
            ) AS distinct_baa_tbl
        LEFT OUTER JOIN
        raw_data_eia_baa_codes
        USING (baa)
        WHERE {footprint_scope_sql}
        ;
        """

    return all_lzs_sql


def warn_on_project_load_zones_missing_from_system(
    conn, footprint, load_zone_level, project_load_zones, quiet=False
):
    """
    Warn — regardless of *quiet* — when any of *project_load_zones* is not
    among the system load zones that eia930_load_zone_input_csvs derives
    for the same footprint and load-zone level (the zones of the
    footprint's interchange-observed BAs). Such projects would reference a
    zone with no load balance and only fail much later, at model load.
    The known case is islanded BAs (HECO, GRIS, CEA — in the BA map but
    never in the interchange data), which bite with ``--footprint all
    --load_zone_level baa``. Skipped when no interchange data is loaded,
    since the system zones may then come from elsewhere entirely. Returns
    the sorted list of missing zones (empty if none or skipped).
    """
    c = conn.cursor()
    interchange_data_loaded = c.execute(
        "SELECT EXISTS (SELECT 1 FROM raw_data_eia930_hourly_interchange)"
    ).fetchone()[0]
    if not interchange_data_loaded:
        if not quiet:
            print(
                "Skipping the project-zone vs system-zone cross-check: no "
                "EIA930 interchange data loaded."
            )
        return []

    system_load_zones = {
        zone
        for (zone,) in c.execute(
            get_all_lzs_sql(
                load_zone_str=get_load_zone_str(
                    load_zone_level=load_zone_level, footprint=footprint
                ),
                footprint_scope_sql=get_footprint_scope_sql(
                    footprint=footprint, load_zone_level=load_zone_level
                ),
            )
        ).fetchall()
    }

    missing_zones = sorted(set(project_load_zones) - system_load_zones)
    if missing_zones:
        print(
            f"WARNING: the following project load zones are not among the "
            f"system load zones the eia930_load_zone step derives for this "
            f"footprint and load-zone level (no BA of these zones appears "
            f"in the EIA930 interchange data): {', '.join(missing_zones)}. "
            f"Projects in them will reference load zones with no load "
            f"balance and fail at model load unless the zones are added "
            f"another way."
        )

    return missing_zones


def get_footprint_scope_sql(
    footprint, load_zone_level="baa", table_alias="raw_data_eia_baa_codes"
):
    """
    The SQL condition scoping raw_data_eia_baa_codes rows (referenced as
    *table_alias*) to the study footprint: the *footprint* value matches
    either the BA's EIA930 region or its interconnect, or is the special
    value 'all' (no footprint filter — every mapped BA). BAs with no value
    in the chosen load-zone level's map column are always excluded, since
    they cannot be assigned a load zone: foreign and generation-only BAs
    may lack a region and/or an interconnect in the map, and would
    otherwise leak NULL load zones into the outputs. At the 'all' level
    every mapped BA belongs to the single footprint zone, so only map
    membership (a non-NULL baa) is required.
    """
    zone_guard_column = LOAD_ZONE_LEVEL_COLUMNS[
        "baa" if load_zone_level == "all" else load_zone_level
    ]
    zone_not_null_sql = f"{table_alias}.{zone_guard_column} IS NOT NULL"

    if footprint == "all":
        return zone_not_null_sql

    return (
        f"'{footprint}' IN ({table_alias}.region, {table_alias}.interconnect) "
        f"AND {zone_not_null_sql}"
    )


def get_load_zone_str(load_zone_level, footprint):
    """
    The SQL expression for a generator's load zone at the chosen level:
    its BA, or its BA's EIA930 region or interconnect, from the BA map
    (queries using this must join raw_data_eia_baa_codes on the generator's
    balancing_authority_code_eia). At the 'all' level the whole footprint
    is a single zone named after the *footprint* filter value — so e.g.
    ``--footprint western --load_zone_level all`` produces, for that
    interconnect, the same zone that ``--load_zone_level interconnect``
    produces on the unfiltered data.
    """
    if load_zone_level == "all":
        return f"'{footprint}'"

    return f"raw_data_eia_baa_codes.{LOAD_ZONE_LEVEL_COLUMNS[load_zone_level]}"
