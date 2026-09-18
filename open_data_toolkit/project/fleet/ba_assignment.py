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
Balancing-authority assignment: which BA each generator belongs to. This
resolves BEFORE any filtering or aggregation — the geographic footprint
filter (open_data_toolkit.geographic_scope) and the load-zone mapping both act
on the BA this module assigns. The precedence is manual overrides
(user_defined_baa_overrides) over the EIA-930A operational inventory over
the EIA-860 plant-reported value; get_generators_table_str packages the
resolution as a drop-in relation the generator queries select FROM.
"""

# All columns of the generator tables EXCEPT balancing_authority_code_eia
# (which get_generators_table_str may replace with the EIA-930A assignment)
GENERATORS_TABLE_COLUMNS = {
    "raw_data_eia860_generators": [
        "version_num",
        "report_date",
        "plant_id_eia",
        "generator_id",
        "operational_status_code",
        "operational_status",
        "capacity_mw",
        "summer_capacity_mw",
        "winter_capacity_mw",
        "minimum_load_mw",
        "energy_storage_capacity_mwh",
        "prime_mover_code",
        "energy_source_code_1",
        "energy_source_code_2",
        "fuel_type_code_pudl",
        "technology_description",
        "can_burn_multiple_fuels",
        "can_cofire_fuels",
        "can_switch_oil_gas",
        "carbon_capture",
        "time_cold_shutdown_full_load_code",
        "ownership_code",
        "utility_id_eia",
        "sector_id_eia",
        "sector_name_eia",
        "ferc_cogen_status",
        "primary_purpose_id_naics",
        "associated_combined_heat_power",
        "generator_operating_date",
        "current_planned_generator_operating_date",
        "generator_retirement_date",
        "planned_generator_retirement_date",
    ],
    "raw_data_eia860m_generators": [
        "version_num",
        "report_date",
        "valid_until_date",
        "plant_id_eia",
        "generator_id",
        "operational_status_code",
        "operational_status",
        "capacity_mw",
        "summer_capacity_mw",
        "winter_capacity_mw",
        "energy_storage_capacity_mwh",
        "prime_mover_code",
        "energy_source_code_1",
        "fuel_type_code_pudl",
        "technology_description",
        "sector_id_eia",
        "generator_operating_date",
        "current_planned_generator_operating_date",
        "generator_retirement_date",
        "planned_generator_retirement_date",
    ],
}


# The manual generator -> BA override lookup (see
# user_defined_baa_overrides in raw_data_db_schema.sql): the BA a user has
# pinned this generator to, or NULL if there is no override for it. A
# generator-specific row wins over a plant-wide '*' row. Written as a
# correlated scalar subquery so overlapping rows can never duplicate a
# generator, and so an empty override table simply yields NULL everywhere.
MANUAL_BAA_OVERRIDE_SQL = """(
                SELECT o.balancing_authority_code_eia
                FROM user_defined_baa_overrides o
                WHERE o.plant_id_eia = g.plant_id_eia
                AND (o.generator_id = g.generator_id OR o.generator_id = '*')
                ORDER BY (o.generator_id = '*')
                LIMIT 1
            )"""


# The EIA-930A assignment pieces of get_generators_table_str, exposed for
# the fleet audit (which shows each unit's BA per source alongside the
# resolved value). EIA930A_ASSIGNMENT_JOIN_SQL joins one row per unit
# (first_ba = alphabetically first reporting BA, bas = all of them);
# EIA930A_RESOLVED_BA_CASE_SQL keeps the EIA-860 BA when EIA-930A doesn't
# cover the unit or agrees with it (dual-BA units), else takes first_ba.
EIA930A_RESOLVED_BA_CASE_SQL = """CASE
                WHEN eia930a.plant_id_eia IS NULL
                    THEN g.balancing_authority_code_eia
                WHEN ',' || eia930a.bas || ',' LIKE
                    '%,' || g.balancing_authority_code_eia || ',%'
                    THEN g.balancing_authority_code_eia
                ELSE eia930a.first_ba
            END"""
EIA930A_ASSIGNMENT_JOIN_SQL = """
        LEFT JOIN (
            SELECT plant_id_eia, generator_id,
                MIN(ba) AS first_ba,
                GROUP_CONCAT(DISTINCT ba) AS bas
            FROM raw_data_eia930a_generators
            WHERE schedule IN (2, 3)
            AND plant_id_eia IS NOT NULL AND generator_id IS NOT NULL
            GROUP BY plant_id_eia, generator_id
        ) eia930a
        ON eia930a.plant_id_eia = g.plant_id_eia
        AND eia930a.generator_id = g.generator_id"""


def add_ba_source_argument(parser):
    """
    Add the shared ``--ba_source`` argument to a project-level step's
    argument parser. Single-sourced here (like the fleet-selection,
    geographic-scope, and aggregation argument helpers) so the setting and
    its --help text can't drift across the steps; it must be set
    consistently across the EIA860(M)-based project steps.
    """
    parser.add_argument(
        "-bas",
        "--ba_source",
        default="eia930a",
        choices=["eia860", "eia930a"],
        help="Source for each generator's balancing-authority assignment: "
        "'eia930a' (the default) prefers the operational BA from the "
        "EIA-930A generator inventory (raw_data_eia930a_generators), "
        "falling back to the EIA-860 assignment for units not in it — "
        "including when that table is empty, so the default behaves like "
        "'eia860' until EIA-930A data is loaded; 'eia860' uses the EIA-860 "
        "plant-reported assignment only.",
    )


def get_generators_table_str(ba_source, generators_table="raw_data_eia860_generators"):
    """
    The relation for the generator queries to select FROM: a subquery
    exposing the generator table's columns — aliased back to the table's
    name, so all existing references keep working — with
    balancing_authority_code_eia resolved from, in order of precedence:

    1. the OPTIONAL manual overrides in user_defined_baa_overrides (see
       the schema comment there), which apply under either *ba_source*;
    2. with ba_source 'eia930a' (the default), the OPERATIONAL BA
       assignment from the EIA-930A generator inventory (schedules 2 and
       3). For the handful of units two BAs both report (joint
       ownership/pseudo-ties), the EIA-860 assignment is kept if it is one
       of them; otherwise the alphabetically first EIA-930A BA is used,
       for determinism;
    3. the EIA-860 plant-reported assignment — the only source used with
       ba_source 'eia860', and the fallback for units EIA-930A does not
       cover (including when raw_data_eia930a_generators is empty, so the
       default behaves like 'eia860' until EIA-930A data is loaded).

    With no overrides loaded and no EIA-930A data, every branch resolves
    to the EIA-860 assignment, i.e. the raw table's own column.
    """
    columns_str = ",\n            ".join(
        f"g.{c}" for c in GENERATORS_TABLE_COLUMNS[generators_table]
    )

    if ba_source == "eia860":
        ba_source_sql = "g.balancing_authority_code_eia"
        eia930a_join_sql = ""
    else:
        ba_source_sql = EIA930A_RESOLVED_BA_CASE_SQL
        eia930a_join_sql = EIA930A_ASSIGNMENT_JOIN_SQL

    return f"""(
        SELECT
            {columns_str},
            COALESCE(
            {MANUAL_BAA_OVERRIDE_SQL},
            {ba_source_sql}
            ) AS balancing_authority_code_eia
        FROM {generators_table} g{eia930a_join_sql}
    ) AS {generators_table}"""
