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
Project aggregation: how the filtered fleet's units are grouped into
GridPath projects and what each project is named. This is the LAST stage
of the pipeline — it acts on units the geographic scope
(open_data_toolkit.geographic_scope) and characteristic filters
(open_data_toolkit.project.fleet.fleet_filters) have already selected, combining a
geographic grouping (the load zone at the chosen level) with an
operational-characteristics grouping (the technology base plus any
aggregation dimensions). get_project_name_str is the entry point; the
steps' GROUP BY project then does the aggregation, with per-unit rows
riding through as singleton groups in the keyed mode.
"""

from open_data_toolkit.geographic_scope import get_load_zone_str
from open_data_toolkit.project.fleet.ba_assignment import GENERATORS_TABLE_COLUMNS

DISAGG_PROJECT_NAME_STR = (
    "plant_id_eia || '__' || REPLACE(REPLACE(generator_id, ' ', '_'), '-', '_')"
)


# Which units get aggregated: 'none' = every unit is its own project (the
# default); 'agg_project_keyed' = only units whose user_defined_eia_gridpath_key
# row has agg_project set are aggregated (per-technology choice), the rest
# stay disaggregated; 'all' = everything is aggregated
PROJECT_AGGREGATION_CHOICES = ["none", "agg_project_keyed", "all"]

# Optional aggregation dimensions: named SQL expressions (over the joined
# generators/key/BA-map relations) whose values REFINE the
# technology-load-zone aggregate name — inserted between the technology base
# and the load zone, so they can only split technology-zone groups finer,
# never merge across technologies (each aggregate must stay homogeneous in
# capacity/operational type). A NULL value contributes nothing (no token, no
# separator): e.g. with the 'duration' dimension, storage aggregates become
# 'Batteries_4h_<zone>' while non-storage stays 'Gas_<zone>'. Free-text
# values get the same space/dash sanitization as disaggregated unit names.
# 'columns' lists the generator-table columns the expression needs, checked
# against GENERATORS_TABLE_COLUMNS so steps querying a table that lacks them
# fail loudly (every current dimension is carried by both the EIA860 and
# EIA860M tables). When adding a dimension, note that annual-form-only
# columns (see the raw_data_db_schema.sql note) are NULL at the
# monthly_update EIA860 vintage — a dimension built on them contributes
# nothing there.
AGGREGATION_DIMENSIONS = {
    # EIA's curated technology label (e.g. combined cycle vs combustion
    # turbine vs steam turbine; onshore vs offshore wind)
    "technology_description": {
        "expr": "REPLACE(REPLACE(technology_description, ' ', '_'), '-', '_')",
        "columns": ["technology_description"],
    },
    # Decade the generator came online, e.g. '1990s'
    "vintage_decade": {
        "expr": "CAST(CAST(STRFTIME('%Y', generator_operating_date) AS "
        "INTEGER) / 10 * 10 AS TEXT) || 's'",
        "columns": ["generator_operating_date"],
    },
    # Storage duration in hours (rounded), e.g. '4h'; NULL (no token) for
    # units with no energy storage capacity
    "duration": {
        "expr": "CAST(CAST(ROUND(energy_storage_capacity_mwh / capacity_mw) "
        "AS INTEGER) AS TEXT) || 'h'",
        "columns": ["energy_storage_capacity_mwh", "capacity_mw"],
    },
    # The EIA operational status code (e.g. split under-construction 'U'/'V'
    # aggregates from operating 'OP' ones)
    "status": {
        "expr": "operational_status_code",
        "columns": ["operational_status_code"],
    },
}


def add_project_aggregation_arguments(parser):
    """
    Add the shared ``--project_aggregation`` / ``--aggregation_dimensions``
    arguments to a project-level step's argument parser. Single-sourced
    here so the settings — and their --help menus, which list the
    available dimensions straight from AGGREGATION_DIMENSIONS — can't
    drift across the steps.
    """
    parser.add_argument(
        "-agg",
        "--project_aggregation",
        default="none",
        choices=PROJECT_AGGREGATION_CHOICES,
        help="Which units to aggregate (to the technology-load-zone level, "
        "split finer by any aggregation_dimensions): 'none' (the default) "
        "keeps every unit as its own project; 'agg_project_keyed' "
        "aggregates only units whose user_defined_eia_gridpath_key row has "
        "agg_project set, keeping the rest as units; 'all' aggregates "
        "everything. Must be set consistently across the project-level "
        "steps.",
    )
    parser.add_argument(
        "-aggdim",
        "--aggregation_dimensions",
        default="",
        help="Comma-separated aggregation dimensions refining the aggregate "
        "project names (inserted between the technology and the load zone), "
        "e.g. 'technology_description,vintage_decade'. Available "
        f"dimensions: {', '.join(AGGREGATION_DIMENSIONS)}. Must be set "
        "consistently across the project-level steps.",
    )


def get_aggregation_dimensions_sql(
    aggregation_dimensions, generators_table="raw_data_eia860_generators"
):
    """
    The SQL snippet appending the requested aggregation dimensions (a
    comma-separated string or an iterable of names from
    AGGREGATION_DIMENSIONS) to the aggregate project name. Unknown dimension
    names and dimensions whose columns the *generators_table* doesn't carry
    raise ValueError.
    """
    if isinstance(aggregation_dimensions, str):
        aggregation_dimensions = [
            d.strip() for d in aggregation_dimensions.split(",") if d.strip()
        ]

    table_columns = GENERATORS_TABLE_COLUMNS[generators_table]
    snippet = ""
    for dimension in aggregation_dimensions:
        if dimension not in AGGREGATION_DIMENSIONS:
            raise ValueError(
                f"Unknown aggregation dimension '{dimension}'. Available "
                f"dimensions: {', '.join(AGGREGATION_DIMENSIONS.keys())}."
            )
        missing = [
            c
            for c in AGGREGATION_DIMENSIONS[dimension]["columns"]
            if c not in table_columns
        ]
        if missing:
            raise ValueError(
                f"Aggregation dimension '{dimension}' needs column(s) "
                f"{', '.join(missing)}, which {generators_table} does not "
                f"carry — drop the dimension or use an EIA860-based step."
            )
        expr = AGGREGATION_DIMENSIONS[dimension]["expr"]
        snippet += f" || COALESCE('_' || {expr}, '')"

    return snippet


def get_agg_project_name_str(
    load_zone_level,
    footprint,
    aggregation_dimensions="",
    generators_table="raw_data_eia860_generators",
):
    """
    Aggregated projects are named
    <agg_project-or-technology>[_<dimension value>...]_<load_zone>, and are
    thereby aggregated at the chosen load-zone level (see get_load_zone_str
    for the 'all' level), split finer by any requested aggregation
    dimensions (see AGGREGATION_DIMENSIONS).
    """
    load_zone_str = get_load_zone_str(load_zone_level, footprint)
    dimensions_sql = get_aggregation_dimensions_sql(
        aggregation_dimensions=aggregation_dimensions,
        generators_table=generators_table,
    )
    return (
        "COALESCE(agg_project, gridpath_technology)"
        + dimensions_sql
        + " || '_' || "
        + load_zone_str
    )


def get_project_name_str(
    project_aggregation,
    load_zone_level,
    footprint,
    aggregation_dimensions="",
    generators_table="raw_data_eia860_generators",
):
    """
    The project-name SQL expression for the chosen *project_aggregation*
    mode (see PROJECT_AGGREGATION_CHOICES). With 'agg_project_keyed', units
    whose key row has agg_project set get the aggregate name and everything
    else keeps its per-unit name — the aggregated queries' GROUP BY project
    then leaves the per-unit rows as singleton groups, so their SUMs/values
    come through unchanged.
    """
    if project_aggregation not in PROJECT_AGGREGATION_CHOICES:
        raise ValueError(
            f"Unknown project_aggregation '{project_aggregation}'; must be "
            f"one of {', '.join(PROJECT_AGGREGATION_CHOICES)}."
        )

    if project_aggregation == "none":
        return DISAGG_PROJECT_NAME_STR

    agg_name_str = get_agg_project_name_str(
        load_zone_level=load_zone_level,
        footprint=footprint,
        aggregation_dimensions=aggregation_dimensions,
        generators_table=generators_table,
    )
    if project_aggregation == "all":
        return agg_name_str

    return (
        f"CASE WHEN agg_project IS NOT NULL THEN {agg_name_str} "
        f"ELSE {DISAGG_PROJECT_NAME_STR} END"
    )
