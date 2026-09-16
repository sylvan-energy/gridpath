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
The scaffolding every EIA860(M)-based project step's ``main`` runs before
its own query: resolve the shared settings into the project-name
expression and the fleet relation, connect to the raw database, and run
the standard scope checks and data-gap warnings. Single-sourced here so
the sequence — and the reasoning behind its ordering — lives in one place
instead of being copied into every step.

The steps call these in the following order, which matters:

1. :func:`get_project_name_str_from_args` and
   :func:`get_fleet_relation_sql_from_args` BEFORE connecting. Both
   validate settings (unknown aggregation dimensions, dimensions the
   generators table can't support, bad status tiers), so a settings error
   fails before any database work — and can't leak the connection.
2. :func:`connect_and_check_scope`, which connects and then reports what
   the footprint value matched and verifies the custom load-zone level is
   usable — checks about WHERE the study is.
3. :func:`warn_on_fleet_data_gaps`, the raw-data quality warnings about
   the units themselves (unknown status codes, NULL sectors).

Steps whose fleet relation depends on something read from the database
(the EIA860M step's default as-of date) necessarily build it after step 2 —
and, because the 'hybrid' aggregation dimension embeds the fleet relation
in the project name (a unit pairs only against IN-FLEET partners), such a
step builds the project name after step 2 too, passing its fleet-relation
overrides to :func:`get_project_name_str_from_args`.

The wrappers pull the shared settings off the parsed arguments by name, so
a step that omits one of them — the fuel and heat-rate steps take no
``--load_zone_level``, being zone-agnostic — gets the underlying
function's default and skips the checks that setting drives.
"""

from open_data_toolkit.geographic_scope import (
    add_footprint_argument,
    add_load_zone_level_argument,
    check_aggregation_level_refines_zone_level,
    check_custom_zone_level_ready,
    report_footprint_type,
)
from open_data_toolkit.project.fleet.aggregation import (
    add_project_aggregation_arguments,
    get_project_name_str,
)
from open_data_toolkit.project.fleet.ba_assignment import add_ba_source_argument
from open_data_toolkit.project.fleet.fleet_filters import (
    warn_on_missing_planned_retirement_data,
    SECTOR_COLUMN,
    add_fleet_selection_arguments,
    ensure_energy_storage_table,
    ensure_net_metering_table,
    get_fleet_relation_sql,
    get_hybrid_pairing_expr,
    warn_on_missing_energy_storage_data,
    warn_on_missing_net_metering_data,
    warn_on_null_sector_rows,
    warn_on_uncovered_sector_names,
    warn_on_uncovered_status_codes,
)
from open_data_toolkit.project.fleet.unit_overrides import (
    ensure_unit_overrides_table,
)
from db.common_functions import connect_to_database

EIA860_GENERATORS_TABLE = "raw_data_eia860_generators"
EIA860M_GENERATORS_TABLE = "raw_data_eia860m_generators"

# The get_fleet_relation_sql settings read off a step's parsed arguments.
# A step that does not define one of these keeps the underlying
# function's default for it — the zone-agnostic fuel and heat-rate steps
# take no --load_zone_level, so they scope at the default 'baa' level.
FLEET_RELATION_SETTINGS = (
    "ba_source",
    "study_year",
    "footprint",
    "load_zone_level",
    "include_retired",
    "planned_inclusion",
    "inactive_inclusion",
    "include_planned_retirements",
    "exclude_commercial_industrial_sectors",
    "include_net_metered",
)

# The settings the EIA860(M)-based project steps SHARE — the ones that
# decide which units become which projects, and therefore must agree
# across every step generating one study's inputs. Grouped by the switch
# that turns each group on in add_shared_project_step_arguments, which is
# the single place they are declared; get_shared_project_step_settings
# below reports the resulting names, so the orchestrator's
# settings-consistency check reads the same source the parsers do.
STUDY_SETTINGS = ("study_year",)
SCOPE_SETTINGS = ("footprint", "ba_source")
ZONE_SETTINGS = ("load_zone_level",)
FLEET_SELECTION_SETTINGS = (
    "include_retired",
    "planned_inclusion",
    "inactive_inclusion",
    "include_planned_retirements",
    "exclude_commercial_industrial_sectors",
    "include_net_metered",
)
AGGREGATION_SETTINGS = (
    "project_aggregation",
    "aggregation_dimensions",
    "aggregation_level",
)


def add_shared_project_step_arguments(
    parser, zone_aware=True, fleet_selection=True, aggregation=True
):
    """
    Add EVERY setting the EIA860(M)-based project steps share, in one
    call. A step must not assemble this set itself: the settings have to
    agree across the steps generating one study's inputs (they decide
    which units become which projects), and a step that takes a subset —
    or hand-rolls one argument with a drifted default — produces inputs
    for a different fleet than its siblings, which nothing downstream
    catches. ``tests/test_open_data_toolkit/project/fleet/test_shared_arguments``
    pins each step to the profile it declares here.

    The three switches are the only legitimate variation, and each has
    exactly the steps it exists for:

    * ``zone_aware=False`` — the fuel and heat-rate steps, which assign no
      load zones (their inputs are joined against the portfolio
      downstream), so they take no ``--load_zone_level``;
    * ``aggregation=False`` — the same two steps, which write one CSV per
      unit-level project name and so never aggregate;
    * ``fleet_selection=False`` — the manual-adjustments step, which
      patches already-generated CSVs against a deliberately superset
      fleet rather than selecting one.

    ``--study_year``, ``--footprint`` and ``--ba_source`` have no switch:
    every project step needs all three.
    """
    parser.add_argument("-y", "--study_year", default=2026)
    add_footprint_argument(parser=parser)

    if fleet_selection:
        add_fleet_selection_arguments(parser=parser)

    add_ba_source_argument(parser=parser)

    if zone_aware:
        add_load_zone_level_argument(parser=parser)

    if aggregation:
        add_project_aggregation_arguments(parser=parser)


def get_shared_project_step_settings(
    zone_aware=True, fleet_selection=True, aggregation=True
):
    """
    The setting names add_shared_project_step_arguments adds for the same
    switches — the single source for anything that needs to know what the
    project steps share without building a parser (the orchestrator's
    settings-consistency check, and the tests that pin each step's
    profile).
    """
    settings = STUDY_SETTINGS + SCOPE_SETTINGS
    if fleet_selection:
        settings += FLEET_SELECTION_SETTINGS
    if zone_aware:
        settings += ZONE_SETTINGS
    if aggregation:
        settings += AGGREGATION_SETTINGS

    return settings


def requests_hybrid_dimension(parsed_args):
    """
    Whether the step's parsed arguments request the 'hybrid' aggregation
    dimension — i.e. whether the project names need the runtime-built
    hybrid-pairing expression. False in the disaggregated ('none') mode,
    where dimensions never apply.
    """
    if getattr(parsed_args, "project_aggregation", "none") == "none":
        return False
    dimensions = getattr(parsed_args, "aggregation_dimensions", "")
    if isinstance(dimensions, str):
        dimensions = [d.strip() for d in dimensions.split(",") if d.strip()]

    return "hybrid" in dimensions


def get_project_name_str_from_args(
    parsed_args, generators_table=EIA860_GENERATORS_TABLE, **fleet_overrides
):
    """
    The stage-3 project-name expression for a step's parsed arguments (see
    open_data_toolkit.project.fleet.aggregation.get_project_name_str). Call before
    connecting: it validates the aggregation settings.

    When the 'hybrid' aggregation dimension is requested, this also builds
    the hybrid-pairing expression it needs, embedding the step's fleet
    relation (a unit pairs only against IN-FLEET partners) — pass the same
    *fleet_overrides* the step passes to get_fleet_relation_sql_from_args
    so the two agree, and call this AFTER any override only the database
    can supply is known (the EIA860M step's as-of-date filter).
    """
    hybrid_pairing_expr = None
    if requests_hybrid_dimension(parsed_args):
        hybrid_pairing_expr = get_hybrid_pairing_expr(
            generators_table=generators_table,
            fleet_relation_sql=get_fleet_relation_sql_from_args(
                parsed_args, generators_table=generators_table, **fleet_overrides
            ),
        )

    return get_project_name_str(
        project_aggregation=parsed_args.project_aggregation,
        load_zone_level=parsed_args.load_zone_level,
        footprint=parsed_args.footprint,
        aggregation_dimensions=parsed_args.aggregation_dimensions,
        generators_table=generators_table,
        aggregation_level=getattr(parsed_args, "aggregation_level", None),
        hybrid_pairing_expr=hybrid_pairing_expr,
    )


def get_fleet_relation_sql_from_args(parsed_args, **overrides):
    """
    The canonical FROM/JOIN/WHERE block selecting the study fleet for a
    step's parsed arguments (see
    open_data_toolkit.project.fleet.fleet_filters.get_fleet_relation_sql). Call
    before connecting: it validates the fleet-selection settings.

    Any get_fleet_relation_sql keyword can be passed as an *override* for
    what a step does differently — the EIA860M generators table and its
    as-of-date filter, the zone-agnostic steps' ``join_ba_map=False`` and
    operational-type filters.
    """
    kwargs = {
        setting: getattr(parsed_args, setting)
        for setting in FLEET_RELATION_SETTINGS
        if hasattr(parsed_args, setting)
    }
    kwargs.update(overrides)

    return get_fleet_relation_sql(**kwargs)


def connect_and_check_scope(parsed_args):
    """
    Connect to the raw database and run the geographic-scope checks:
    report whether the footprint value matched a region or an interconnect
    (and warn loudly if neither, since every output would then be empty),
    and, for a step that takes a load-zone level, verify the custom level
    is usable and that any requested aggregation level refines the
    load-zone level. Returns the connection; the caller closes it — except
    when a check fails, where this closes it before raising (the checks
    are the only database work that happens before a step's caller has the
    connection to close).
    """
    conn = connect_to_database(db_path=parsed_args.database)

    try:
        # The fleet relation references user_defined_unit_overrides
        # unconditionally (raw_data_eia860_solar when the net-metered
        # exclusion is on, and raw_data_eia860_energy_storage when hybrid
        # pairing is — the fleet audit's hybrid columns always); create
        # them empty on databases that predate them
        ensure_unit_overrides_table(conn=conn)
        ensure_net_metering_table(conn=conn)
        ensure_energy_storage_table(conn=conn)
        report_footprint_type(
            conn=conn, footprint=parsed_args.footprint, quiet=parsed_args.quiet
        )
        if hasattr(parsed_args, "load_zone_level"):
            check_custom_zone_level_ready(
                conn=conn,
                load_zone_level=parsed_args.load_zone_level,
                footprint=parsed_args.footprint,
            )
            check_aggregation_level_refines_zone_level(
                conn=conn,
                aggregation_level=getattr(parsed_args, "aggregation_level", None),
                load_zone_level=parsed_args.load_zone_level,
                footprint=parsed_args.footprint,
            )
    except Exception:
        conn.close()
        raise

    return conn


def warn_on_fleet_data_gaps(
    conn, parsed_args, generators_table=EIA860_GENERATORS_TABLE
):
    """
    Warn about raw-data gaps that would silently distort the fleet
    selection: operational status codes the filter tiers don't account
    for; when behind-the-meter units are being excluded, units with no
    sector to classify them by; when planned retirements are being
    excluded, an entirely empty planned-retirement column (which makes
    that exclusion silently inert); and when the 'hybrid' aggregation
    dimension is in use, an empty energy-storage supplement table (which
    silently degrades pairing to plant co-location only). All warn
    regardless of any quiet setting, by design.
    """
    warn_on_uncovered_status_codes(conn=conn, generators_table=generators_table)

    if getattr(parsed_args, "exclude_commercial_industrial_sectors", False):
        warn_on_null_sector_rows(
            conn=conn,
            generators_table=generators_table,
            sector_column=SECTOR_COLUMN[generators_table],
        )
        if SECTOR_COLUMN[generators_table] == "sector_name_eia":
            warn_on_uncovered_sector_names(conn=conn, generators_table=generators_table)

    if not getattr(parsed_args, "include_planned_retirements", True):
        warn_on_missing_planned_retirement_data(
            conn=conn, generators_table=generators_table
        )

    if not getattr(parsed_args, "include_net_metered", True):
        warn_on_missing_net_metering_data(conn=conn)

    if requests_hybrid_dimension(parsed_args):
        warn_on_missing_energy_storage_data(conn=conn)
