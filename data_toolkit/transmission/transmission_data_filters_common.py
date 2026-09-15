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

from data_toolkit.geographic_scope import (
    LOAD_ZONE_LEVEL_COLUMNS,
    get_footprint_scope_sql,
)


def get_endpoint_zone_sqls(footprint, load_zone_level):
    """
    The SQL expressions for an interchange link's two endpoint load zones,
    with the BA map joined as baa_key_from/baa_key_to. At the 'all' level
    both endpoints resolve to the single footprint zone (the *footprint*
    filter value), so every link is intra-zone and the transmission
    network is empty — a single-zone model has no transmission.
    """
    if load_zone_level == "all":
        return f"'{footprint}'", f"'{footprint}'"

    zone_column = LOAD_ZONE_LEVEL_COLUMNS[load_zone_level]

    return f"baa_key_from.{zone_column}", f"baa_key_to.{zone_column}"


def get_all_links_sql(footprint, load_zone_level):
    """
    The directed zone-pair links observed in the EIA930 interchange data:
    each interchange BA pair with both endpoints in the scope (see
    get_footprint_scope_sql — the *footprint* value matches either the EIA930
    region or the interconnect of the BA map, or is 'all') is mapped to
    its endpoints' load zones at the chosen level, and intra-zone links
    are dropped — so at the aggregated ('region' and 'interconnect')
    levels, parallel BA pairs between the same two zones collapse into
    one link, and links between BAs of the same zone disappear. At the
    'all' level every link is intra-zone, so no links result (see
    get_endpoint_zone_sqls).
    """
    from_zone_sql, to_zone_sql = get_endpoint_zone_sqls(
        footprint=footprint, load_zone_level=load_zone_level
    )
    from_scope_sql = get_footprint_scope_sql(
        footprint=footprint, load_zone_level=load_zone_level, table_alias="baa_key_from"
    )
    to_scope_sql = get_footprint_scope_sql(
        footprint=footprint, load_zone_level=load_zone_level, table_alias="baa_key_to"
    )

    all_links_sql = f"""
        SELECT DISTINCT
            {from_zone_sql},
            {to_zone_sql}
        FROM raw_data_eia930_hourly_interchange
        JOIN raw_data_eia_baa_codes AS baa_key_from
            ON balancing_authority_code_eia = baa_key_from.baa
        JOIN raw_data_eia_baa_codes AS baa_key_to
            ON balancing_authority_code_adjacent_eia = baa_key_to.baa
        WHERE {from_scope_sql}
        AND {to_scope_sql}
        AND {from_zone_sql} != {to_zone_sql}
        ORDER BY 1, 2
        ;
        """

    return all_links_sql


def get_interchange_relation_str(footprint, load_zone_level, max_value_exclude):
    """
    The relation for the transmission-capacity query to read hourly
    interchange from, with data-cleaning applied per reported BA-pair value
    (abs(value) <= *max_value_exclude*). At the 'baa' level, simply the
    cleaned raw table (per-BA-pair sums are exact regardless of scope). At
    the aggregated ('region' and 'interconnect') levels, hourly flows are
    SUMMED across the in-scope BA pairs connecting each zone pair
    (intra-zone pairs dropped), so the derived capacity limit is the
    maximum OBSERVED SIMULTANEOUS zone-to-zone transfer — not the
    (optimistic) sum of the individual BA pairs' maxima. The scope filter
    (see get_footprint_scope_sql) keeps flows of out-of-scope BAs — e.g.
    generation-only BAs with no value in the level's map column — out of
    the zone-pair sums, consistent with those BAs being excluded from the
    model. Aliased back to the raw table's name so the capacity query
    works unchanged at any level.
    """
    if load_zone_level == "baa":
        return f"""(
            SELECT * FROM raw_data_eia930_hourly_interchange
            WHERE abs(interchange_reported_mwh) <= {max_value_exclude}
        ) AS raw_data_eia930_hourly_interchange"""

    from_zone_sql, to_zone_sql = get_endpoint_zone_sqls(
        footprint=footprint, load_zone_level=load_zone_level
    )
    from_scope_sql = get_footprint_scope_sql(
        footprint=footprint, load_zone_level=load_zone_level, table_alias="baa_key_from"
    )
    to_scope_sql = get_footprint_scope_sql(
        footprint=footprint, load_zone_level=load_zone_level, table_alias="baa_key_to"
    )

    return f"""(
        SELECT
            datetime_pst_he,
            {from_zone_sql} AS balancing_authority_code_eia,
            {to_zone_sql} AS balancing_authority_code_adjacent_eia,
            SUM(interchange_reported_mwh) AS interchange_reported_mwh
        FROM raw_data_eia930_hourly_interchange
        JOIN raw_data_eia_baa_codes AS baa_key_from
            ON raw_data_eia930_hourly_interchange.balancing_authority_code_eia
                = baa_key_from.baa
        JOIN raw_data_eia_baa_codes AS baa_key_to
            ON raw_data_eia930_hourly_interchange.balancing_authority_code_adjacent_eia
                = baa_key_to.baa
        WHERE abs(interchange_reported_mwh) <= {max_value_exclude}
        AND {from_scope_sql}
        AND {to_scope_sql}
        AND {from_zone_sql} != {to_zone_sql}
        GROUP BY datetime_pst_he, {from_zone_sql},
            {to_zone_sql}
    ) AS raw_data_eia930_hourly_interchange"""


def get_unique_tx_lines(all_links):
    unique_tx_lines = []
    for link in all_links:
        if f"{link[1]}_{link[0]}" not in unique_tx_lines:
            unique_tx_lines.append(f"{link[0]}_{link[1]}")

    return unique_tx_lines
