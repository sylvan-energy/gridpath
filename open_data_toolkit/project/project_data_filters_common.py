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
Compatibility re-export shim. The shared project-pipeline helpers that
used to live here were split by pipeline stage (August 2026):

* open_data_toolkit.project.fleet.ba_assignment — which BA each generator belongs to
  (manual overrides over EIA-930A over EIA-860);
* open_data_toolkit.geographic_scope — the study footprint and load-zone
  levels (also consumed by the system and transmission steps);
* open_data_toolkit.project.fleet.fleet_filters — filtering by generator
  characteristics (status tiers, date windows vs the study year,
  behind-the-meter sectors, operational types);
* open_data_toolkit.project.fleet.aggregation — grouping the filtered units into
  named GridPath projects.

Import from those modules directly in new code; every name is re-exported
here so existing imports keep working.
"""

from open_data_toolkit.geographic_scope import (
    LOAD_ZONE_LEVEL_COLUMNS,
    LOAD_ZONE_LEVEL_CHOICES,
    check_custom_zone_level_ready,
    get_footprint_options,
    report_footprint_type,
    get_all_lzs_sql,
    warn_on_project_load_zones_missing_from_system,
    get_footprint_scope_sql,
    get_load_zone_str,
)
from open_data_toolkit.project.fleet.ba_assignment import (
    GENERATORS_TABLE_COLUMNS,
    MANUAL_BAA_OVERRIDE_SQL,
    get_generators_table_str,
)
from open_data_toolkit.project.fleet.fleet_filters import (
    UNDER_CONSTRUCTION_STATUS_CODES,
    PLANNED_PRE_CONSTRUCTION_STATUS_CODES,
    PLANNED_INCLUSION_CHOICES,
    STANDBY_STATUS_CODES,
    OUT_OF_SERVICE_SHORT_TERM_STATUS_CODES,
    OUT_OF_SERVICE_LONG_TERM_STATUS_CODES,
    INACTIVE_INCLUSION_CHOICES,
    NEVER_INCLUDED_STATUS_CODES,
    BTM_SECTOR_NAMES,
    BTM_SECTOR_IDS,
    ALL_KNOWN_STATUS_CODES,
    warn_on_uncovered_status_codes,
    warn_on_null_sector_rows,
    warn_on_missing_planned_retirement_data,
    get_allowed_status_codes,
    get_eia860_sql_filter_string,
    get_eia860m_sql_filter_string,
    get_retired_filter_string,
    get_btm_filter_string,
    get_eia860m_as_of_date_filter_string,
    FUEL_FILTER_STR,
    HEAT_RATE_FILTER_STR,
    STOR_FILTER_STR,
    VAR_GEN_FILTER_STR,
    HYDRO_FILTER_STR,
    add_fleet_selection_arguments,
)
from open_data_toolkit.project.fleet.aggregation import (
    DISAGG_PROJECT_NAME_STR,
    PROJECT_AGGREGATION_CHOICES,
    AGGREGATION_DIMENSIONS,
    add_project_aggregation_arguments,
    get_aggregation_dimensions_sql,
    get_agg_project_name_str,
    get_project_name_str,
)

__all__ = [
    "LOAD_ZONE_LEVEL_COLUMNS",
    "LOAD_ZONE_LEVEL_CHOICES",
    "check_custom_zone_level_ready",
    "get_footprint_options",
    "report_footprint_type",
    "get_all_lzs_sql",
    "warn_on_project_load_zones_missing_from_system",
    "get_footprint_scope_sql",
    "get_load_zone_str",
    "GENERATORS_TABLE_COLUMNS",
    "MANUAL_BAA_OVERRIDE_SQL",
    "get_generators_table_str",
    "UNDER_CONSTRUCTION_STATUS_CODES",
    "PLANNED_PRE_CONSTRUCTION_STATUS_CODES",
    "PLANNED_INCLUSION_CHOICES",
    "STANDBY_STATUS_CODES",
    "OUT_OF_SERVICE_SHORT_TERM_STATUS_CODES",
    "OUT_OF_SERVICE_LONG_TERM_STATUS_CODES",
    "INACTIVE_INCLUSION_CHOICES",
    "NEVER_INCLUDED_STATUS_CODES",
    "BTM_SECTOR_NAMES",
    "BTM_SECTOR_IDS",
    "ALL_KNOWN_STATUS_CODES",
    "warn_on_uncovered_status_codes",
    "warn_on_null_sector_rows",
    "warn_on_missing_planned_retirement_data",
    "get_allowed_status_codes",
    "get_eia860_sql_filter_string",
    "get_eia860m_sql_filter_string",
    "get_retired_filter_string",
    "get_btm_filter_string",
    "get_eia860m_as_of_date_filter_string",
    "FUEL_FILTER_STR",
    "HEAT_RATE_FILTER_STR",
    "STOR_FILTER_STR",
    "VAR_GEN_FILTER_STR",
    "HYDRO_FILTER_STR",
    "add_fleet_selection_arguments",
    "DISAGG_PROJECT_NAME_STR",
    "PROJECT_AGGREGATION_CHOICES",
    "AGGREGATION_DIMENSIONS",
    "add_project_aggregation_arguments",
    "get_aggregation_dimensions_sql",
    "get_agg_project_name_str",
    "get_project_name_str",
]
