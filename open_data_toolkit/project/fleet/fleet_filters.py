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
Fleet filtering by generator characteristics: which units make the fleet,
based on what they ARE — operational status, operating/retirement dates
vs the study year, behind-the-meter sector, operational type — as opposed
to where they are (open_data_toolkit.geographic_scope) or how they are grouped
into projects (open_data_toolkit.project.fleet.aggregation). The
get_eia860(m)_sql_filter_string entry points compose the characteristic
filters with the geographic footprint filter into the WHERE clause the
EIA860(M)-based project steps share.
"""

from open_data_toolkit.geographic_scope import get_footprint_scope_sql
from open_data_toolkit.project.fleet.ba_assignment import get_generators_table_str
from open_data_toolkit.project.fleet.unit_overrides import get_unit_override_sql

# The operational-status-code tiers of not-yet-operational ("proposed")
# and existing-but-not-operating units. The annual EIA860 and EIA860M
# vocabularies are identical in current PUDL data (verified against
# v2026.7.2: OP/OA/OS/SB existing, P/L/T/U/V/TS/OT proposed, RE retired);
# 'CO' (under construction) and 'SC' (cold standby/deactivated, 3-6
# months to reactivate) are kept in their tiers for other vintages.
# Definitions per PUDL's core_eia__codes_operational_status.
UNDER_CONSTRUCTION_STATUS_CODES = ("CO", "U", "V", "TS")
PLANNED_PRE_CONSTRUCTION_STATUS_CODES = ("P", "L", "T", "OT", "PL")
PLANNED_INCLUSION_CHOICES = ("none", "under_construction", "all")

STANDBY_STATUS_CODES = ("SB",)  # available for service, not normally used
OUT_OF_SERVICE_SHORT_TERM_STATUS_CODES = ("OA",)  # back within next cal. year
OUT_OF_SERVICE_LONG_TERM_STATUS_CODES = ("OS", "SC")  # not expected back soon
INACTIVE_INCLUSION_CHOICES = (
    "none",
    "standby",
    "out_of_service_short_term",
    "all",
)

# Codes deliberately never included in a fleet, at any setting: cancelled
# ('CN'), indefinitely postponed / dropped from the resource plan ('IP'),
# and ozone-season-only emissions equipment ('OZ', never a generator)
NEVER_INCLUDED_STATUS_CODES = ("CN", "IP", "OZ")

# The EIA sectors whose generation is typically behind the meter, serving
# onsite commercial/industrial load: their output is netted out of the
# metered demand that EIA-930-derived load is built from, rather than
# appearing in any BA's generation telemetry (measured July 2026: these
# sectors dominate the large-unit capacity absent from every BA's EIA-930A
# Schedule 2). Modeling them as supply resources alongside 930-derived
# load can therefore double-count their energy — but the sector is an
# ownership-based proxy that also catches genuinely BA-metered exporting
# cogens, so the project steps KEEP these units by default and offer the
# blanket sector exclusion as the opt-in exclude_commercial_industrial_sectors setting (the
# per-generator net-metering flag and user_defined_unit_overrides are the
# sharper per-unit instruments). The annual
# generators table carries only sector_name_eia at monthly-update
# vintages (sector_id_eia is annual-form-only and NULL there); EIA860M
# carries only sector_id_eia — the id-to-name mapping below is the EIA
# standard, verified against v2026.7.2 unit counts. Units with a NULL
# sector cannot be classified and are KEPT (see warn_on_null_sector_rows).
# PUDL v2026.9.0 introduced a SECOND name vocabulary alongside the old one
# (both appear within a single vintage): the C&I sectors also appear as
# 'Commercial/Industrial NAICS (Non-)Cogen' (same ids 4-7), and the
# electric-power sectors as 'NAICS-22 (Non-)Cogen' (ids 2/3 — the IPP
# sectors, NOT behind-the-meter). The ids are stable; only names drift —
# ALL_KNOWN_SECTOR_NAMES + warn_on_uncovered_sector_names guard against
# the next rename silently breaking this classification.
COMMERCIAL_INDUSTRIAL_SECTOR_NAMES = (
    "Commercial CHP",
    "Commercial Non-CHP",
    "Industrial CHP",
    "Industrial Non-CHP",
    # the same four sectors under PUDL v2026.9.0's NAICS-style names
    "Commercial NAICS Cogen",
    "Commercial NAICS Non-Cogen",
    "Industrial NAICS Cogen",
    "Industrial NAICS Non-Cogen",
)
COMMERCIAL_INDUSTRIAL_SECTOR_IDS = (4, 5, 6, 7)

# Every sector_name_eia value the classification accounts for — the
# commercial/industrial names above plus the electric-power-industry
# sectors (never excluded). A name
# outside this set silently fails the sector IN test (the unit is then KEPT,
# like a NULL sector), so warn_on_uncovered_sector_names flags vocabulary
# changes in future dataset versions loudly.
ELECTRIC_POWER_SECTOR_NAMES = (
    "Electric Utility",
    "IPP Non-CHP",
    "IPP CHP",
    "NAICS-22 Non-Cogen",
    "NAICS-22 Cogen",
)
ALL_KNOWN_SECTOR_NAMES = (
    COMMERCIAL_INDUSTRIAL_SECTOR_NAMES + ELECTRIC_POWER_SECTOR_NAMES
)

# Which sector column to test in each generators table, per the vintage
# note above — used by the sector filter and by warn_on_null_sector_rows
SECTOR_COLUMN = {
    "raw_data_eia860_generators": "sector_name_eia",
    "raw_data_eia860m_generators": "sector_id_eia",
}

# The full status-code universe the tiers account for — everything here is
# either includable at some setting, retired ('RE', on include_retired), or
# deliberately excluded. warn_on_uncovered_status_codes flags any code in
# the data outside this set, so vocabulary changes in future dataset
# versions surface loudly instead of units silently dropping out.
ALL_KNOWN_STATUS_CODES = (
    ("OP", "RE")
    + UNDER_CONSTRUCTION_STATUS_CODES
    + PLANNED_PRE_CONSTRUCTION_STATUS_CODES
    + STANDBY_STATUS_CODES
    + OUT_OF_SERVICE_SHORT_TERM_STATUS_CODES
    + OUT_OF_SERVICE_LONG_TERM_STATUS_CODES
    + NEVER_INCLUDED_STATUS_CODES
)


def warn_on_uncovered_status_codes(conn, generators_table):
    """
    Warn — loudly, regardless of any quiet setting — when
    *generators_table* contains operational_status_code values (or NULLs)
    outside ALL_KNOWN_STATUS_CODES. Every status filter is an IN test
    against the known tiers, so an unrecognized code means those units are
    silently excluded from every fleet at every setting — the likely cause
    is a vocabulary change in a newer dataset version. Returns the list of
    (code, n_units, capacity_mw) found (empty if all codes are covered).
    """
    known_codes_str = ", ".join(f"'{c}'" for c in ALL_KNOWN_STATUS_CODES)
    uncovered = conn.cursor().execute(f"""
            SELECT operational_status_code, COUNT(*), SUM(capacity_mw)
            FROM {generators_table}
            WHERE operational_status_code IS NULL
            OR operational_status_code NOT IN ({known_codes_str})
            GROUP BY operational_status_code
            ORDER BY operational_status_code
            ;
            """).fetchall()

    if uncovered:
        uncovered_strs = [
            f"'{code}' ({n_units} units, {0 if mw is None else round(mw)} MW)"
            for code, n_units, mw in uncovered
        ]
        print(
            f"WARNING: {generators_table} contains operational_status_code "
            f"values not covered by the status-code tiers in "
            f"fleet_filters.py: {', '.join(uncovered_strs)}. "
            f"These units are excluded from every fleet regardless of the "
            f"include_retired/planned_inclusion/inactive_inclusion "
            f"settings — the dataset's status-code vocabulary may have "
            f"changed; update the tiers to cover the new codes."
        )

    return uncovered


def warn_on_null_sector_rows(conn, generators_table, sector_column):
    """
    Warn — loudly, regardless of any quiet setting — when
    *generators_table* has NULL values in *sector_column* while the
    behind-the-meter sector exclusion is active (exclude_commercial_industrial_sectors set).
    NULL-sector units
    cannot be classified and are KEPT in the fleet, so commercial/
    industrial capacity may
    leak through; an entirely NULL column almost certainly means the raw
    CSVs predate the July 2026 sector columns — re-run
    gridpath_pudl_to_gridpath_raw (after re-downloading with
    gridpath_get_pudl_data) to fill them. Callers should run this check
    only when exclude_commercial_industrial_sectors is set. Returns (n_null_units, null_mw,
    n_rows).
    """
    n_null, null_mw, n_rows = conn.cursor().execute(f"""
            SELECT SUM({sector_column} IS NULL),
                   SUM(CASE WHEN {sector_column} IS NULL
                       THEN capacity_mw ELSE 0 END),
                   COUNT(*)
            FROM {generators_table}
            ;
            """).fetchone()
    n_null = 0 if n_null is None else n_null
    null_mw = 0 if null_mw is None else null_mw

    if n_null:
        all_null_str = (
            " The column is entirely NULL — the raw data likely predates "
            "the July 2026 sector columns; re-run "
            "gridpath_pudl_to_gridpath_raw (after re-downloading with "
            "gridpath_get_pudl_data) to fill it."
            if n_null == n_rows
            else ""
        )
        print(
            f"WARNING: {generators_table} has {n_null} units "
            f"({round(null_mw)} MW) with NULL {sector_column}. These units "
            f"cannot be classified for the behind-the-meter exclusion and "
            f"are INCLUDED in the fleet, so behind-the-meter capacity may "
            f"leak through.{all_null_str}"
        )

    return n_null, null_mw, n_rows


def warn_on_uncovered_sector_names(conn, generators_table):
    """
    Warn — loudly, regardless of any quiet setting — when
    *generators_table* contains sector_name_eia values outside
    ALL_KNOWN_SECTOR_NAMES while the behind-the-meter sector exclusion is
    active. The sector test is an IN test against
    COMMERCIAL_INDUSTRIAL_SECTOR_NAMES, so an
    unrecognized name means those units silently pass the exclusion (kept,
    like NULL sectors) — the likely cause is a vocabulary change in a
    newer dataset version (PUDL v2026.9.0 renamed the sectors once
    already; the ids are stable but the annual table carries only names
    at monthly-update vintages). Callers should run this check only when
    exclude_commercial_industrial_sectors is set, and only for tables classified by name.
    Returns the list of (name, n_units, capacity_mw) found.
    """
    known_names_str = ", ".join(f"'{n}'" for n in ALL_KNOWN_SECTOR_NAMES)
    uncovered = conn.cursor().execute(f"""
            SELECT sector_name_eia, COUNT(*), SUM(capacity_mw)
            FROM {generators_table}
            WHERE sector_name_eia IS NOT NULL
            AND sector_name_eia NOT IN ({known_names_str})
            GROUP BY sector_name_eia
            ORDER BY sector_name_eia
            ;
            """).fetchall()

    if uncovered:
        uncovered_strs = [
            f"'{name}' ({n_units} units, {0 if mw is None else round(mw)} MW)"
            for name, n_units, mw in uncovered
        ]
        print(
            f"WARNING: {generators_table} contains sector_name_eia values "
            f"not covered by the sector vocabulary in fleet_filters.py: "
            f"{', '.join(uncovered_strs)}. Units with these sectors PASS "
            f"the behind-the-meter exclusion (they are kept) regardless of "
            f"what sector they really are — the dataset's sector "
            f"vocabulary may have changed; update COMMERCIAL_INDUSTRIAL_SECTOR_NAMES / "
            f"ELECTRIC_POWER_SECTOR_NAMES to cover the new names."
        )

    return uncovered


def warn_on_missing_planned_retirement_data(conn, generators_table):
    """
    Warn — loudly, regardless of any quiet setting — when
    *generators_table*'s planned_generator_retirement_date column is
    entirely NULL while the planned-retirement exclusion is active. There
    are always some units with filed retirement plans in real EIA data
    (~500 units nationally, Sep 2026), so an all-NULL column almost
    certainly means the raw CSVs predate the September 2026 addition of
    the column and the exclusion is silently doing nothing — re-run
    gridpath_pudl_to_gridpath_raw (the already-downloaded parquet files
    carry the column) to fill it. Callers should skip this check when
    include_planned_retirements is set. Returns (n_populated, n_rows).
    """
    n_populated, n_rows = conn.cursor().execute(f"""
            SELECT SUM(planned_generator_retirement_date IS NOT NULL),
                   COUNT(*)
            FROM {generators_table}
            ;
            """).fetchone()
    n_populated = 0 if n_populated is None else n_populated

    if n_rows and not n_populated:
        print(
            f"WARNING: planned retirements are being excluded, but "
            f"{generators_table} has NO planned_generator_retirement_date "
            f"values at all, so the exclusion will do nothing. The raw "
            f"data likely predates the September 2026 addition of the "
            f"column — re-run gridpath_pudl_to_gridpath_raw to fill it "
            f"(the downloaded PUDL parquet files already carry it)."
        )

    return n_populated, n_rows


# Mirror of the raw_data_eia860_solar DDL in raw_data_db_schema.sql (as
# CREATE TABLE IF NOT EXISTS, so pre-existing raw databases get the table
# on first use) — keep the two in sync
NET_METERING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS raw_data_eia860_solar
(
    version_num                          TEXT,
    report_date                          DATETIME,
    plant_id_eia                         INTEGER,
    generator_id                         TEXT,
    uses_net_metering_agreement          INTEGER,
    net_metering_capacity_mwdc           REAL,
    uses_virtual_net_metering_agreement  INTEGER,
    virtual_net_metering_capacity_mwdc   REAL,
    PRIMARY KEY (version_num, report_date, plant_id_eia, generator_id)
);
"""


def ensure_net_metering_table(conn):
    """
    Create the (empty) raw_data_eia860_solar table if this raw database
    predates it, so the net-metered exclusion's subquery never fails on a
    missing table. An empty table makes the exclusion a no-op — which
    warn_on_missing_net_metering_data reports loudly, since it usually
    means the solar CSV was never loaded rather than that no unit is
    net-metered.
    """
    conn.execute(NET_METERING_TABLE_DDL)
    conn.commit()


def warn_on_missing_net_metering_data(conn):
    """
    Warn — loudly, regardless of any quiet setting — when the net-metered
    exclusion is active but raw_data_eia860_solar is empty, making the
    exclusion silently do nothing (there are always net-metered solar
    units in real EIA data — ~1,100 nationally at the 2025 vintage). The
    usual cause is a raw database loaded before pudl_eia860_solar.csv
    existed (September 2026) — re-run gridpath_pudl_to_gridpath_raw and
    load the new CSV, or pass include_net_metered to accept the fleet
    including net-metered units. Callers should skip this check when
    include_net_metered is set. Returns the table's row count.
    """
    n_rows = (
        conn.cursor()
        .execute("SELECT COUNT(*) FROM raw_data_eia860_solar")
        .fetchone()[0]
    )

    if not n_rows:
        print(
            "WARNING: net-metered units are being excluded, but "
            "raw_data_eia860_solar is EMPTY, so the exclusion will do "
            "nothing. Load pudl_eia860_solar.csv (added to the convert "
            "step in September 2026 — re-run gridpath_pudl_to_gridpath_raw "
            "if the raw CSVs predate it), or pass include_net_metered to "
            "accept keeping net-metered units."
        )

    return n_rows


def get_net_metering_filter_string(include_net_metered):
    """
    The net-metered exclusion part of the EIA860(M) filters: drop units
    the EIA860 solar supplement flags as operating under a net-metering
    agreement — net metering is a billing arrangement at a retail meter
    that runs net, so the flagged output is by definition netted out of
    the metered demand that EIA-930-derived load is built from, and
    modeling it as supply alongside that load double-counts its energy
    (the same physical concern as the opt-in behind-the-meter SECTOR
    exclusion, on per-generator, billing-based evidence rather than an
    ownership proxy). Empty with *include_net_metered*; a unit absent from
    raw_data_eia860_solar — any non-solar unit, and solar units newer
    than the loaded solar vintage — is never excluded.
    """
    if include_net_metered:
        return ""

    return """AND (plant_id_eia, generator_id) NOT IN (
         SELECT plant_id_eia, generator_id
         FROM raw_data_eia860_solar
         WHERE uses_net_metering_agreement = 1
     )"""


def get_allowed_status_codes(planned_inclusion, inactive_inclusion="none"):
    """
    The operational status codes allowed through the EIA860(M) filters.
    Currently operating ('OP') units are always allowed. The
    *planned_inclusion* level adds not-yet-operational tiers: units under
    construction or with construction complete ('CO'/'U'/'V'/'TS') at
    'under_construction' (the default level) and 'all'; planned units on
    which construction has not started ('P'/'L'/'T', plus the
    unclassified proposed code 'OT') at 'all' only. The
    *inactive_inclusion* level adds existing-but-not-operating tiers,
    cumulatively in order of how available the units are: standby units
    ('SB' — available for service but not normally used) at 'standby'
    and up; short-term out-of-service units ('OA' — expected back in
    service within the next calendar year) at 'out_of_service_short_term'
    and up; long-term out-of-service/deactivated units ('OS'/'SC' — not
    expected back within the next calendar year) at 'all' only. (Retired
    units ride on the include_retired flag instead — see
    get_retired_filter_string.)
    """
    if planned_inclusion not in PLANNED_INCLUSION_CHOICES:
        raise ValueError(
            f"Unknown planned_inclusion value '{planned_inclusion}'; must "
            f"be one of {PLANNED_INCLUSION_CHOICES}."
        )
    if inactive_inclusion not in INACTIVE_INCLUSION_CHOICES:
        raise ValueError(
            f"Unknown inactive_inclusion value '{inactive_inclusion}'; must "
            f"be one of {INACTIVE_INCLUSION_CHOICES}."
        )

    allowed_status_codes = ("OP",)
    if planned_inclusion in ("under_construction", "all"):
        allowed_status_codes += UNDER_CONSTRUCTION_STATUS_CODES
    if planned_inclusion == "all":
        allowed_status_codes += PLANNED_PRE_CONSTRUCTION_STATUS_CODES

    if inactive_inclusion in ("standby", "out_of_service_short_term", "all"):
        allowed_status_codes += STANDBY_STATUS_CODES
    if inactive_inclusion in ("out_of_service_short_term", "all"):
        allowed_status_codes += OUT_OF_SERVICE_SHORT_TERM_STATUS_CODES
    if inactive_inclusion == "all":
        allowed_status_codes += OUT_OF_SERVICE_LONG_TERM_STATUS_CODES

    return allowed_status_codes


def get_eia860_sql_filter_string(
    study_year,
    footprint,
    load_zone_level="baa",
    include_retired=False,
    planned_inclusion="under_construction",
    inactive_inclusion="none",
    include_planned_retirements=False,
    exclude_commercial_industrial_sectors=False,
    sector_column="sector_name_eia",
    sector_values=COMMERCIAL_INDUSTRIAL_SECTOR_NAMES,
    include_net_metered=False,
):
    """
    With *include_retired*, retired units are allowed through: the 'RE'
    status code is added to the allowed set and the retirement-date window
    (which would otherwise re-exclude anything retired before the end of
    the study year) is dropped. *planned_inclusion* selects which
    not-yet-operational units are included, always subject to the
    planned-operating-date window (on or before Jan 1 of the study year):
    'under_construction' (the default) includes units under construction
    or with construction complete; 'all' also includes planned units on
    which construction has not started; 'none' keeps only currently
    operating units. *inactive_inclusion* selects which
    existing-but-not-operating units are included, cumulatively:
    'standby' adds standby/backup units (available for service);
    'out_of_service_short_term' also adds units expected back in service
    within the next calendar year; 'all' also adds long-term
    out-of-service units; 'none' (the default) adds none of them. See
    get_allowed_status_codes for the code tiers.
    Units whose EIA-reported PLANNED retirement date falls before the
    end of the study year are also excluded by default;
    *include_planned_retirements* keeps them (see
    get_retired_filter_string). *exclude_commercial_industrial_sectors* opts into the
    blanket behind-the-meter SECTOR exclusion — dropping the
    commercial/industrial EIA sectors, whose output typically serves
    onsite load and is netted out of the metered demand that
    EIA-930-derived load is built from (see COMMERCIAL_INDUSTRIAL_SECTOR_NAMES; NULL-sector
    units are always kept). It is OFF by default: the sector is an
    ownership-based proxy that also catches BA-metered exporting cogens,
    so per-unit instruments (the default net-metered exclusion,
    user_defined_unit_overrides) are preferred.
    *load_zone_level* excludes units in BAs that have no load zone at
    that level (see get_footprint_scope_sql); zone-agnostic callers
    (fuels, heat rates) can keep the 'baa' default, since generating
    inputs for a superset of the portfolio's projects is harmless.

    The string is the composition, in pipeline-stage order, of the
    geographic filter (get_geographic_filter_string — WHERE the unit is)
    and the characteristics filter (get_characteristics_filter_string —
    WHAT the unit is); use those directly to apply one stage at a time
    (e.g. to see what each stage excludes).
    """
    geographic_filter_string = get_geographic_filter_string(
        footprint=footprint, load_zone_level=load_zone_level
    )
    characteristics_filter_string = get_characteristics_filter_string(
        study_year=study_year,
        include_retired=include_retired,
        planned_inclusion=planned_inclusion,
        inactive_inclusion=inactive_inclusion,
        include_planned_retirements=include_planned_retirements,
        exclude_commercial_industrial_sectors=exclude_commercial_industrial_sectors,
        sector_column=sector_column,
        sector_values=sector_values,
        include_net_metered=include_net_metered,
    )
    eia860_sql_filter_string = f"""
    {geographic_filter_string}
     AND {characteristics_filter_string}
    """

    return eia860_sql_filter_string


def get_geographic_filter_string(footprint, load_zone_level="baa"):
    """
    The geographic-scope part of the EIA860(M) filters (pipeline stage 1):
    the unit's (resolved) balancing authority is in the study footprint
    and has a load zone at the chosen load-zone level (see
    get_footprint_scope_sql). Everything about WHERE the unit is; nothing
    about what it is.
    """
    footprint_scope_sql = get_footprint_scope_sql(
        footprint=footprint, load_zone_level=load_zone_level
    )
    return f"""balancing_authority_code_eia in (
         SELECT baa
         FROM raw_data_eia_baa_codes
         WHERE {footprint_scope_sql}
     )"""


def get_characteristics_filter_string(
    study_year,
    include_retired=False,
    planned_inclusion="under_construction",
    inactive_inclusion="none",
    include_planned_retirements=False,
    exclude_commercial_industrial_sectors=False,
    sector_column="sector_name_eia",
    sector_values=COMMERCIAL_INDUSTRIAL_SECTOR_NAMES,
    include_net_metered=False,
):
    """
    The generator-characteristics part of the EIA860(M) filters (pipeline
    stage 2): the planned-operating-date window vs the study year, the
    operational-status / retirement-date selection (see
    get_retired_filter_string and the tier constants), the
    behind-the-meter sector exclusion (see get_commercial_industrial_filter_string), and
    the net-metered exclusion (see get_net_metering_filter_string).
    Everything about WHAT the unit is; nothing about where it is.
    """
    retired_filter_string = get_retired_filter_string(
        study_year=study_year,
        allowed_status_codes=get_allowed_status_codes(
            planned_inclusion=planned_inclusion,
            inactive_inclusion=inactive_inclusion,
        ),
        include_retired=include_retired,
        include_planned_retirements=include_planned_retirements,
    )
    commercial_industrial_filter_string = get_commercial_industrial_filter_string(
        exclude_commercial_industrial_sectors=exclude_commercial_industrial_sectors,
        sector_column=sector_column,
        sector_values=sector_values,
    )
    net_metering_filter_string = get_net_metering_filter_string(
        include_net_metered=include_net_metered
    )
    planned_date_window_string = get_planned_date_window_string(study_year=study_year)
    return f"""{planned_date_window_string}
     {retired_filter_string}
     {commercial_industrial_filter_string}
     {net_metering_filter_string}"""


def get_planned_date_window_string(study_year):
    """
    The planned-operating-date part of the EIA860(M) filters, as a bare
    predicate: the unit's current planned operating date is on or before
    Jan 1 of the study year (or it has none, i.e. it is already
    operating).
    """
    return f"""(unixepoch(current_planned_generator_operating_date) <= unixepoch(
     '{study_year}-01-01') or current_planned_generator_operating_date IS NULL)"""


def get_eia860m_sql_filter_string(
    study_year,
    footprint,
    load_zone_level="baa",
    include_retired=False,
    planned_inclusion="under_construction",
    inactive_inclusion="none",
    include_planned_retirements=False,
    exclude_commercial_industrial_sectors=False,
    include_net_metered=False,
):
    """
    EIA860M equivalent of get_eia860_sql_filter_string, for use against
    raw_data_eia860m_generators. The status-code part is identical — the
    annual and monthly vocabularies match in current PUDL data (860M has
    no 'CO', but that code is harmless in the shared under-construction
    tier) — so this delegates; the only difference is the
    behind-the-meter sector column: 860M carries only the numeric
    sector_id_eia (the annual table's sector_name_eia is not on the
    monthly form).
    """
    return get_eia860_sql_filter_string(
        study_year=study_year,
        footprint=footprint,
        load_zone_level=load_zone_level,
        include_retired=include_retired,
        planned_inclusion=planned_inclusion,
        inactive_inclusion=inactive_inclusion,
        include_planned_retirements=include_planned_retirements,
        exclude_commercial_industrial_sectors=exclude_commercial_industrial_sectors,
        sector_column="sector_id_eia",
        sector_values=COMMERCIAL_INDUSTRIAL_SECTOR_IDS,
        include_net_metered=include_net_metered,
    )


def get_retired_filter_string(
    study_year,
    allowed_status_codes,
    include_retired,
    include_planned_retirements=False,
):
    """
    The operational-status / retirement-date part of the EIA860(M) filters:
    by default only *allowed_status_codes* units that don't retire before
    the end of the study year; with *include_retired*, retired ('RE') units
    are also allowed and the retirement-date window is dropped. Units
    whose EIA-reported PLANNED retirement date
    (planned_generator_retirement_date — a unit still operating, with a
    filed plan to retire) falls before the end of the study year are ALSO
    excluded by default — a study-year fleet would otherwise keep every
    unit EIA expects to retire before then (measured Sep 2026: 51 units /
    8.2 GW in a default western 2030 fleet). *include_planned_retirements*
    keeps them instead — planned retirement dates are softer commitments
    than filed retirements (they slip and get withdrawn), so a study may
    reasonably choose not to trust them. The planned-retirement window
    applies independently of *include_retired* (each setting owns its own
    clause).
    """
    status_codes_string = ", ".join(f"'{c}'" for c in allowed_status_codes)
    if include_retired:
        retired_filter_string = (
            f"AND operational_status_code in ({status_codes_string}, 'RE')"
        )
    else:
        retired_filter_string = f"""AND (unixepoch(generator_retirement_date) > unixepoch('{study_year}-12-31') or generator_retirement_date IS NULL)
     AND operational_status_code in ({status_codes_string})"""

    if not include_planned_retirements:
        retired_filter_string += f"""
     AND (unixepoch(planned_generator_retirement_date) > unixepoch('{study_year}-12-31') or planned_generator_retirement_date IS NULL)"""

    return retired_filter_string


def get_commercial_industrial_filter_string(
    exclude_commercial_industrial_sectors,
    sector_column="sector_name_eia",
    sector_values=COMMERCIAL_INDUSTRIAL_SECTOR_NAMES,
):
    """
    The behind-the-meter sector part of the EIA860(M) filters: with
    *exclude_commercial_industrial_sectors*, exclude units in the commercial/industrial EIA
    sectors (see COMMERCIAL_INDUSTRIAL_SECTOR_NAMES/COMMERCIAL_INDUSTRIAL_SECTOR_IDS), keeping NULL-sector
    units — they can't be classified, and silently dropping them would be
    worse than keeping them (warn_on_null_sector_rows makes them loud).
    Without it (the default), no sector filtering at all.
    """
    if not exclude_commercial_industrial_sectors:
        return ""

    sector_values_string = ", ".join(
        f"'{v}'" if isinstance(v, str) else str(v) for v in sector_values
    )
    return (
        f"AND ({sector_column} IS NULL "
        f"OR {sector_column} NOT IN ({sector_values_string}))"
    )


def get_eia860m_as_of_date_filter_string(as_of_date):
    """
    Reduce the raw_data_eia860m_generators changelog to a snapshot of the
    fleet as EIA had published it as of *as_of_date* (a FILING date, not
    an event date — see the EIA860M step's docstring for the
    distinction): for each generator, keep its latest changelog row with
    report_date on or before that date, PROVIDED the row was still valid
    then (valid_until_date on or after the as-of date, or open/NULL).
    Generators first reported after *as_of_date* have no qualifying row
    and drop out; generators that VANISHED from EIA's monthly files
    before the as-of date without ever filing a retirement — their last
    row says operating forever, but EIA's own current publication no
    longer carries them (330 units / 6.5 GW nationally, measured Aug
    2026) — are excluded by the valid_until_date condition. A row whose
    valid_until_date reaches the changelog's last report_date is treated
    as still current even for a later *as_of_date*, so an as-of date
    beyond the data's end degrades to the latest available snapshot
    instead of dropping the whole fleet.
    """
    eia860m_as_of_date_filter_string = f"""
    (raw_data_eia860m_generators.plant_id_eia,
     raw_data_eia860m_generators.generator_id,
     raw_data_eia860m_generators.report_date) IN (
        SELECT plant_id_eia, generator_id, MAX(report_date)
        FROM raw_data_eia860m_generators
        WHERE report_date <= '{as_of_date}'
        AND (valid_until_date IS NULL
             OR valid_until_date >= '{as_of_date}'
             OR valid_until_date >= (SELECT MAX(report_date)
                                     FROM raw_data_eia860m_generators))
        GROUP BY plant_id_eia, generator_id
    )
    """

    return eia860m_as_of_date_filter_string


def get_fleet_relation_sql(
    ba_source,
    study_year,
    footprint,
    load_zone_level="baa",
    include_retired=False,
    planned_inclusion="under_construction",
    inactive_inclusion="none",
    include_planned_retirements=False,
    exclude_commercial_industrial_sectors=False,
    include_net_metered=False,
    generators_table="raw_data_eia860_generators",
    join_ba_map=True,
    extra_joins="",
    extra_where="",
):
    """
    The canonical FROM/JOIN/WHERE block selecting the study fleet — the
    single place the pipeline's selection stages compose, in order:

    0. BA assignment: the generator relation with
       balancing_authority_code_eia resolved (get_generators_table_str —
       overrides over EIA-930A over EIA-860), joined to
       user_defined_eia_gridpath_key (units without a key row drop out)
       and, unless *join_ba_map* is False (zone-agnostic steps like fuels
       and heat rates), to the raw_data_eia_baa_codes BA map for the
       load-zone columns;
    1. geographic filtering: the footprint/load-zone-level scope
       (get_geographic_filter_string);
    2. characteristic filtering: status, dates vs the study year,
       behind-the-meter sectors (get_characteristics_filter_string).

    Steps put their SELECT list (with the stage-3 project-name expression
    from open_data_toolkit.project.fleet.aggregation) on top of this relation and
    append GROUP BY project when aggregating. *extra_joins* is inserted
    after the standard joins (e.g. the fuel step's fuel-region key);
    *extra_where* is ANDed after the fleet filter (e.g. the EIA860M
    as-of-date snapshot filter or an operational-type filter). The
    EIA860M generators table gets the 860M filter variant automatically.

    Per-unit include/exclude overrides (user_defined_unit_overrides, see
    open_data_toolkit.project.fleet.unit_overrides) apply to the
    characteristics stage only: include=1 bypasses it, include=0 fails
    it, and the geographic filter, the key join, and any *extra_where*
    still apply either way. An empty overrides table (the default) is a
    no-op.
    """
    if generators_table == "raw_data_eia860m_generators":
        sector_column = "sector_id_eia"
        sector_values = COMMERCIAL_INDUSTRIAL_SECTOR_IDS
    else:
        sector_column = "sector_name_eia"
        sector_values = COMMERCIAL_INDUSTRIAL_SECTOR_NAMES

    geographic_filter_string = get_geographic_filter_string(
        footprint=footprint, load_zone_level=load_zone_level
    )
    characteristics_filter_string = get_characteristics_filter_string(
        study_year=study_year,
        include_retired=include_retired,
        planned_inclusion=planned_inclusion,
        inactive_inclusion=inactive_inclusion,
        include_planned_retirements=include_planned_retirements,
        exclude_commercial_industrial_sectors=exclude_commercial_industrial_sectors,
        sector_column=sector_column,
        sector_values=sector_values,
        include_net_metered=include_net_metered,
    )
    include_override_sql = get_unit_override_sql(
        column="include", generators_table=generators_table
    )
    fleet_filter_string = f"""
    {geographic_filter_string}
     AND COALESCE(({include_override_sql}) = 1, ({characteristics_filter_string}
    ))
    """

    generators_str = get_generators_table_str(
        ba_source=ba_source, generators_table=generators_table
    )

    ba_map_join_sql = (
        """
    JOIN raw_data_eia_baa_codes ON
            balancing_authority_code_eia = raw_data_eia_baa_codes.baa"""
        if join_ba_map
        else ""
    )
    extra_where_sql = f"\n     AND {extra_where}" if extra_where else ""

    return f"""FROM {generators_str}
    JOIN user_defined_eia_gridpath_key ON
            {generators_table}.prime_mover_code =
            user_defined_eia_gridpath_key.prime_mover_code
            AND energy_source_code_1 = energy_source_code{ba_map_join_sql}{extra_joins}
     WHERE 1 = 1
     AND {fleet_filter_string}{extra_where_sql}"""


FUEL_FILTER_STR = (
    """gridpath_operational_type IN ('gen_commit_bin', 'gen_commit_lin')"""
)
HEAT_RATE_FILTER_STR = (
    """gridpath_operational_type IN ('gen_commit_bin', 'gen_commit_lin')"""
)
STOR_FILTER_STR = """gridpath_operational_type = 'stor'"""
VAR_GEN_FILTER_STR = """gridpath_operational_type IN ('gen_var', 'gen_var_must_take')"""
HYDRO_FILTER_STR = (
    """gridpath_operational_type IN ('gen_hydro', 'gen_hydro_must_take')"""
)


def add_fleet_selection_arguments(parser):
    """
    Add the shared fleet-selection arguments — ``--include_retired``,
    ``--planned_inclusion``, ``--inactive_inclusion``,
    ``--include_planned_retirements``, ``--exclude_commercial_industrial_sectors``,
    ``--include_net_metered`` — to a project-level step's argument parser.
    Single-sourced here (like add_project_aggregation_arguments) so the
    settings and their --help texts can't drift across the steps; they
    must be set consistently across the EIA860(M)-based project steps.
    """
    parser.add_argument(
        "-incl_ret",
        "--include_retired",
        default=False,
        action="store_true",
        help="Also include retired units: allow the 'RE' operational "
        "status code and don't exclude units for retiring before the "
        "end of the study year.",
    )
    parser.add_argument(
        "-pln",
        "--planned_inclusion",
        default="under_construction",
        choices=list(PLANNED_INCLUSION_CHOICES),
        help="Which not-yet-operational units to include, always subject "
        "to the planned-operating-date window (on or before Jan 1 of the "
        "study year): 'under_construction' (the default) includes units "
        "under construction or with construction complete; 'all' also "
        "includes planned units on which construction has not started; "
        "'none' keeps only currently operating units.",
    )
    parser.add_argument(
        "-inact",
        "--inactive_inclusion",
        default="none",
        choices=list(INACTIVE_INCLUSION_CHOICES),
        help="Which existing-but-not-operating units to include, "
        "cumulatively: 'standby' adds standby/backup units (available "
        "for service but not normally used); 'out_of_service_short_term' "
        "also adds out-of-service units expected back in service within "
        "the next calendar year; 'all' also adds long-term out-of-service "
        "units; 'none' (the default) adds none of them.",
    )
    parser.add_argument(
        "-incl_pret",
        "--include_planned_retirements",
        default=False,
        action="store_true",
        help="Also include units whose EIA-reported PLANNED retirement "
        "date (a unit still operating, with a filed plan to retire) falls "
        "before the end of the study year. Such units are excluded by "
        "default — the study-year fleet should not count capacity EIA "
        "expects to be gone by then — but planned retirement dates are "
        "softer commitments than filed retirements (they slip and get "
        "withdrawn), so a study may choose not to trust them. Units with "
        "no planned retirement date are always kept.",
    )
    parser.add_argument(
        "-xci",
        "--exclude_commercial_industrial_sectors",
        default=False,
        action="store_true",
        help="Exclude ALL units in the commercial/industrial EIA sectors "
        f"({', '.join(COMMERCIAL_INDUSTRIAL_SECTOR_NAMES)}) — a purely "
        "SECTOR-based (ownership) classification; EIA-860 has no explicit "
        "behind-the-meter field. Much of these sectors' output serves "
        "onsite load — netted out of the metered demand that "
        "EIA-930-derived load is built from — so counting it as supply "
        "double-counts its energy; but the sector proxy also catches "
        "genuinely BA-metered exporting cogens, so this blanket exclusion "
        "is OFF by default in favor of the per-unit instruments (the "
        "default net-metered exclusion and user_defined_unit_overrides). "
        "Units with no sector in the raw data are always kept.",
    )
    parser.add_argument(
        "-nm",
        "--include_net_metered",
        default=False,
        action="store_true",
        help="Also include units the EIA860 solar supplement flags as "
        "operating under a net-metering agreement (raw_data_eia860_solar). "
        "These are excluded by default: net metering is a billing "
        "arrangement at a retail meter that runs net, so the flagged "
        "output is BY DEFINITION netted out of the metered demand that "
        "EIA-930-derived load is built from, and counting it as supply "
        "would double-count its energy. The flag is per-generator and "
        "mostly marks small distributed solar in the utility/IPP sectors. "
        "Units absent from the solar table (non-solar units, and solar "
        "units newer than the loaded solar vintage) are always kept; an "
        "empty table makes the exclusion a no-op (warned loudly).",
    )
