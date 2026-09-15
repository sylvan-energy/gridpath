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
GridPath can currenlty utilize a subset of the downloaded PUDL data,
including:

* `Form EIA-860 <https://www.eia.gov/electricity/data/eia860/>`__: generator-level specific information about existing and planned generators
* `Form EIA-930 <https://www.eia.gov/electricity/gridmonitor/about>`__: hourly operating data about the high-voltage bulk electric power grid in the Lower 48 states collected from the electricity balancing authorities (BAs) that operate the grid
* `EIA AEO <https://www.eia.gov/outlooks/aeo/>`__ Table 54 (Electric Power Projections by Electricity Market Module Region): fuel price forecasts

First, the data must be converted to the GridPath raw data CSV format. For the
purpose, use the ``gridpath_pudl_to_gridpath_raw`` command.

This will query and process the per-table Parquet files downloaded in the
previous step in order to create the following files in the user-specified
raw data directory.

* pudl_eia860_generators.csv
* pudl_eia860m_generators.csv
* pudl_eia923_plant_fuel_generation.csv
* pudl_eia930_hourly_interchange.csv
* pudl_eia930_net_generation_by_fuel.csv
* pudl_eia930_operations.csv
* pudl_eia_baa_codes.csv
* pudl_eiaaeo_fuel_prices.csv

Note the difference in how the two generator files handle data vintages.
EIA860 is the full annual survey: one authoritative snapshot of the fleet
per report year, so ``pudl_eia860_generators.csv`` is filtered to a single
vintage here, via the ``eia860_report_date`` setting. Know which KIND of
vintage you are selecting: report dates for completed years are actual
annual filings (``data_maturity = 'final'``), while the LATEST report
date — the default — is PUDL's RECONSTRUCTION of the in-progress report
year from EIA860M (``data_maturity = 'monthly_update'``): the fleet as
EIA's current monthly publication has it, relabeled to Jan 1 of the
report year. Its January label is a year marker, not an information
cutoff — the data is as fresh as the last EIA860M month PUDL ingested
(verified Aug 2026: the monthly_update vintage matched EIA's
then-current 860M publication exactly, unit for unit), but the
annual-form-only columns are NULL there, since no annual form has been
filed yet.

EIA860M itself is EIA860's monthly supplement — a lighter form tracking
status changes between annual filings (new units entering service,
retirements, slipped planned dates), which PUDL publishes as a
changelog: one row per generator per change, valid from *report_date*
until *valid_until_date*. Its dates are FILING dates: a snapshot
reconstructed "as of" a report date is the fleet as EIA had PUBLISHED it
by that month, not the fleet physically operating on that date — units
come online one to a few months before the filing that first reports
them (the event date is the separate ``generator_operating_date``
column). By default ``pudl_eia860m_generators.csv`` holds each
generator's LATEST changelog entry — the latest available fleet
snapshot, matching the default of the downstream ``eia860m_as_of_date``
setting (the latest report date in the data). With the
``eia860m_full_changelog`` setting, the full changelog is kept instead,
and downstream Data Toolkit steps can then reconstruct the fleet as of
any month via ``eia860m_as_of_date`` — e.g., set it to the report_date
column written here to align EIA860M-based inputs with the typically
older EIA860 vintage (with the default latest-only data, earlier as-of
dates would instead silently drop any generator whose last change came
after them). Either way, keep the *valid_until_date* column intact: the
downstream as-of filter uses it to exclude generators that VANISHED from
EIA's monthly files without ever filing a retirement (their last row
says operating forever; 330 units / 6.5 GW nationally as of Aug 2026,
some of them plant-ID remaps whose capacity would otherwise be double
counted). The two forms' status-code vocabularies differ: the annual
form collapses under-construction statuses into 'CO', while EIA860M
reports the granular 'U'/'V'/'TS' codes.

Besides the identifiers, status, capacity, and date columns the
downstream steps filter on, the generator CSVs carry generator-type
columns usable as aggregation dimensions (EIA's technology_description,
PUDL's simplified fuel_type_code_pudl, multi-fuel capability flags,
carbon capture, sector/cogen identification, ownership, and — via
PUDL's static generator entity table — the generator operating date and
CHP flag). Columns only reported on the full annual EIA860 form are
NULL when the selected report date is a monthly_update vintage (the
latest rows, which are EIA860M-derived). The
``eia860_annual_detail_report_date`` setting fills that gap without
giving up freshness: the fleet stays at the selected (latest) vintage
while those columns are backfilled per generator from a pinned as-filed
vintage, leaving NULLs only for generators too new to appear in it. The
resulting CSV therefore mixes vintages — its ``report_date`` column is
the fleet's, and the metadata trail records the detail vintage.

This step selects data VINTAGES only (the EIA860 report date, defaulting
to the latest available, the EIA860M latest-entries default vs the
full changelog, and the EIA923 start year); any further filtering —
operational status (e.g. retired units), region, etc. — deliberately
happens downstream in the to-input-csvs Data Toolkit steps (e.g. their
``include_retired`` setting), so the raw database holds the data as
published by PUDL. The one transformation beyond vintage selection: the
EIA930 hourly net generation by energy source is aggregated to MONTHLY
totals per BA and energy source here (BA-level reconciliation works with
monthly/annual totals, and the hourly rows would make the raw CSV
unmanageably large). For
options, including the download and raw data directories, see the --help
menu.

The settings used to create each file — including resolved defaults such as
the EIA860 report date actually used — are recorded in a
*data_metadata.csv* file in the raw data directory, along with the
arguments the run was given and a copy of the download metadata of the
PUDL files the run started from, so the full chain of how the raw data was
obtained travels with the data.
"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import duckdb
import os.path
import pandas as pd
import sys

from db.utilities.common_functions import confirm
from open_data_toolkit.raw_data.common_functions import (
    DATA_PROVENANCE_FILENAME,
    copy_data_metadata,
    log_data_metadata,
    warn_on_mixed_pudl_versions,
)

DOWNLOAD_DIRECTORY_DEFAULT = "./pudl_download"
RAW_DATA_DIRECTORY_DEFAULT = "./raw_data"

# Columns collected only on the full annual EIA860 form, and therefore NULL
# in a monthly_update vintage (PUDL's EIA860M-derived reconstruction of the
# in-progress report year) — verified against v2026.7.2. The
# eia860_annual_detail_report_date setting backfills them onto the selected
# fleet from a pinned as-filed vintage; everything else (identities, status,
# capacities, dates, BA, sector NAME, and the aggregation-dimension columns)
# always comes from the selected report date, since it is populated at every
# vintage. Split by source table, as the two are joined separately.
ANNUAL_ONLY_GENERATOR_COLUMNS = (
    "minimum_load_mw",
    "energy_source_code_2",
    "can_burn_multiple_fuels",
    "can_cofire_fuels",
    "can_switch_oil_gas",
    "carbon_capture",
    "time_cold_shutdown_full_load_code",
    "ownership_code",
)
ANNUAL_ONLY_PLANT_COLUMNS = (
    "sector_id_eia",
    "ferc_cogen_status",
    "primary_purpose_id_naics",
)


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument(
        "-pudl",
        "--pudl_download_directory",
        default=DOWNLOAD_DIRECTORY_DEFAULT,
        help=f"Defaults to{DOWNLOAD_DIRECTORY_DEFAULT}",
    )
    parser.add_argument(
        "-d",
        "--raw_data_directory",
        default=RAW_DATA_DIRECTORY_DEFAULT,
        help=f"Defaults to {RAW_DATA_DIRECTORY_DEFAULT}",
    )

    parser.add_argument(
        "-rdate",
        "--eia860_report_date",
        default=None,
        help="EIA860 report date (YYYY-MM-DD) to pull generator data for. "
        "Defaults to the latest report date in the downloaded EIA860 data; "
        "a date with no rows is rejected (it would yield an empty CSV). "
        "NOTE the latest vintage is usually not an as-filed annual form "
        "but PUDL's reconstruction of the in-progress report year from "
        "EIA860M (data_maturity 'monthly_update'): as fresh as the last "
        "860M month PUDL ingested despite its Jan-1 label, but with the "
        "annual-form-only columns (sector_id_eia, multi-fuel flags, ...) "
        "NULL. Pin an earlier, as-filed vintage ('final') to get those "
        "columns at the cost of fleet staleness.",
    )

    parser.add_argument(
        "-adate",
        "--eia860_annual_detail_report_date",
        default=None,
        help="Backfill the annual-form-only generator columns (minimum "
        "load, multi-fuel and carbon-capture flags, second energy source, "
        "ownership, sector id, cogen status, NAICS purpose) from this "
        "as-filed EIA860 report date, per generator. The fleet — the row "
        "set and every always-populated column — still comes from "
        "--eia860_report_date, so this is how to combine an up-to-date "
        "fleet (the latest, EIA860M-derived vintage, where these columns "
        "are NULL) with annual detail: generators absent from the pinned "
        "vintage (typically those built since) simply keep NULLs. Pick a "
        "vintage whose data_maturity is 'final' or 'provisional'; the "
        "resulting CSV mixes vintages, which the metadata trail records.",
    )

    parser.add_argument(
        "-full",
        "--eia860m_full_changelog",
        default=False,
        action="store_true",
        help="Keep the full EIA860M changelog instead of the default of "
        "only each generator's latest entry (a current-fleet snapshot). "
        "The full changelog is needed for as-of-date reconstruction at "
        "earlier dates — with latest-only data, downstream as-of dates "
        "before a generator's last change drop that generator rather than "
        "resolve to its earlier state.",
    )

    parser.add_argument(
        "-y923",
        "--eia923_start_year",
        default=2018,
        type=int,
        help="Keep EIA923 monthly plant-fuel generation rows from this "
        "report year on. Defaults to 2018, when the EIA930 hourly "
        "generation-by-energy-source reporting the EIA923 actuals are "
        "reconciled against begins.",
    )

    parser.add_argument(
        "-v_pudl",
        "--pudl_version",
        default=None,
        help="The PUDL data release the downloaded files came from; stamped "
        "into the version_num column of the generator CSVs. Defaults to the "
        "version recorded in the download directory's data_metadata.csv "
        "(or 'unknown' if there is no metadata there).",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def determine_pudl_version(pudl_download_directory, pudl_version, source_file=None):
    """
    Default to the PUDL data release version recorded in the download
    directory's data_metadata.csv (i.e., the version the data on disk was
    actually downloaded as) if no version was specified. If *source_file*
    is given, use the latest entry for that specific file — files in the
    download directory can come from different releases if only some were
    re-downloaded later — otherwise use the latest entry overall. Falls
    back to "unknown" if there is no matching metadata (e.g., data obtained
    before metadata tracking was added).
    """
    if pudl_version is None:
        pudl_version = "unknown"
        metadata_filepath = os.path.join(
            pudl_download_directory, DATA_PROVENANCE_FILENAME
        )
        if os.path.exists(metadata_filepath):
            metadata = pd.read_csv(metadata_filepath, dtype=str)
            # Exclude run-level entries ("run_arguments" also carries a
            # pudl_version setting) — only rows describing actual
            # downloaded files count
            version_rows = metadata[
                (metadata["setting"] == "pudl_version")
                & (metadata["output_file"] != "run_arguments")
            ]
            if source_file is not None:
                version_rows = version_rows[version_rows["output_file"] == source_file]
            if not version_rows.empty:
                pudl_version = version_rows["value"].iloc[-1]

    return pudl_version


def get_available_eia860_report_dates(generators_parquet_path):
    """
    The EIA860 report dates (vintages) present in the downloaded generator
    data, as 'YYYY-MM-DD' strings in ascending order.
    """
    return [str(d) for (d,) in duckdb.sql(f"""
            SELECT DISTINCT CAST(report_date AS VARCHAR)
            FROM read_parquet('{generators_parquet_path}')
            ORDER BY 1
            """).fetchall()]


def determine_eia860_report_date(pudl_download_directory, eia860_report_date):
    """
    Default to the latest report date in the downloaded EIA860 generator
    data if no report date was specified; validate an explicitly requested
    one against the vintages actually present, since a report date with no
    rows would otherwise yield an empty generator CSV with no complaint.
    """
    generators_parquet_path = os.path.join(
        pudl_download_directory, "core_eia860__scd_generators.parquet"
    )
    available_report_dates = get_available_eia860_report_dates(
        generators_parquet_path=generators_parquet_path
    )

    if eia860_report_date is None:
        return available_report_dates[-1]

    if eia860_report_date not in available_report_dates:
        raise ValueError(
            f"eia860_report_date '{eia860_report_date}' is not an EIA860 "
            f"report date in the downloaded data, so the generator CSV "
            f"would come out empty. Available report dates: "
            f"{', '.join(available_report_dates)}."
        )

    return eia860_report_date


def warn_on_baa_coverage(
    raw_data_directory, pudl_download_directory, eia860_report_date
):
    """
    Warn about balancing authorities that will silently fall out of any
    region filter downstream: BAs that appear in the generator or
    interchange data but are missing from the EIA balancing-authority map
    (e.g., a newly registered BA the static code table hasn't caught up
    with), and non-retired generators with no BA at all. Findings are
    printed and recorded under ``output_file=run_warnings`` in the metadata
    trail. Datasets whose parquet files are not present are skipped.
    """
    codes_path = os.path.join(
        pudl_download_directory, "core_eia__codes_balancing_authorities.parquet"
    )
    if not os.path.exists(codes_path):
        return

    generators_path = os.path.join(
        pudl_download_directory, "core_eia860__scd_generators.parquet"
    )
    plants_path = os.path.join(
        pudl_download_directory, "core_eia860__scd_plants.parquet"
    )
    changelog_path = os.path.join(
        pudl_download_directory, "core_eia860m__changelog_generators.parquet"
    )
    interchange_path = os.path.join(
        pudl_download_directory, "core_eia930__hourly_interchange.parquet"
    )

    warnings_found = {}

    if os.path.exists(interchange_path):
        missing = [row[0] for row in duckdb.sql(f"""
                SELECT DISTINCT ba FROM (
                    SELECT balancing_authority_code_eia AS ba
                    FROM read_parquet('{interchange_path}')
                    UNION
                    SELECT balancing_authority_code_adjacent_eia
                    FROM read_parquet('{interchange_path}')
                )
                WHERE ba IS NOT NULL
                AND ba NOT IN (SELECT code FROM read_parquet('{codes_path}'))
                ORDER BY ba
                """).fetchall()]
        if missing:
            warnings_found["eia930_baas_missing_from_map"] = "; ".join(missing)

    if os.path.exists(generators_path) and os.path.exists(plants_path):
        missing = [row[0] for row in duckdb.sql(f"""
                SELECT DISTINCT p.balancing_authority_code_eia
                FROM read_parquet('{generators_path}') g
                JOIN read_parquet('{plants_path}') p
                USING (plant_id_eia, report_date)
                WHERE report_date = '{eia860_report_date}'
                AND p.balancing_authority_code_eia IS NOT NULL
                AND p.balancing_authority_code_eia NOT IN
                    (SELECT code FROM read_parquet('{codes_path}'))
                ORDER BY 1
                """).fetchall()]
        if missing:
            warnings_found["eia860_baas_missing_from_map"] = "; ".join(missing)

        n_units, capacity_mw = duckdb.sql(f"""
            SELECT count(*), COALESCE(sum(g.capacity_mw), 0)
            FROM read_parquet('{generators_path}') g
            JOIN read_parquet('{plants_path}') p
            USING (plant_id_eia, report_date)
            WHERE report_date = '{eia860_report_date}'
            AND p.balancing_authority_code_eia IS NULL
            AND g.operational_status != 'retired'
            """).fetchone()
        if n_units:
            warnings_found["eia860_null_baa_generators"] = (
                f"{n_units} non-retired units ({capacity_mw:,.0f} MW)"
            )

    if os.path.exists(changelog_path):
        missing = [row[0] for row in duckdb.sql(f"""
                SELECT DISTINCT balancing_authority_code_eia
                FROM read_parquet('{changelog_path}')
                WHERE balancing_authority_code_eia IS NOT NULL
                AND balancing_authority_code_eia NOT IN
                    (SELECT code FROM read_parquet('{codes_path}'))
                ORDER BY 1
                """).fetchall()]
        if missing:
            warnings_found["eia860m_baas_missing_from_map"] = "; ".join(missing)

        n_units, capacity_mw = duckdb.sql(f"""
            SELECT count(*), COALESCE(sum(capacity_mw), 0) FROM (
                SELECT * FROM read_parquet('{changelog_path}')
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY plant_id_eia, generator_id
                    ORDER BY report_date DESC
                ) = 1
            )
            WHERE balancing_authority_code_eia IS NULL
            AND operational_status != 'retired'
            """).fetchone()
        if n_units:
            warnings_found["eia860m_null_baa_generators"] = (
                f"{n_units} non-retired units ({capacity_mw:,.0f} MW)"
            )

    if warnings_found:
        for setting, value in warnings_found.items():
            print(
                f"WARNING ({setting}): {value} — these will not match any "
                f"region filter and will silently be excluded from the "
                f"generated inputs."
            )
        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="run_warnings",
            settings=warnings_found,
        )


def get_annual_detail_sql(
    generators_parquet_path, plants_parquet_path, annual_detail_report_date
):
    """
    Where the annual-form-only columns come from: returns
    (generator_column_source, plant_column_source, join_sql). Without
    *annual_detail_report_date* they come from the selected vintage's own
    rows (sources 'generators'/'plants', no extra join). With it, they
    come from an as-filed vintage joined per generator, so the fleet stays
    at the selected vintage while carrying annual detail where it exists.
    Raises ValueError if the requested detail vintage has no rows, since
    the LEFT JOIN would otherwise silently NULL every one of these
    columns.
    """
    if annual_detail_report_date is None:
        return "generators", "plants", ""

    available_report_dates = get_available_eia860_report_dates(
        generators_parquet_path=generators_parquet_path
    )
    if annual_detail_report_date not in available_report_dates:
        raise ValueError(
            f"eia860_annual_detail_report_date "
            f"'{annual_detail_report_date}' is not an EIA860 report date in "
            f"the downloaded data, so the annual-form-only columns would "
            f"all come back NULL. Available report dates: "
            f"{', '.join(available_report_dates)}."
        )

    detail_columns_str = ",\n                    ".join(
        [f"generators.{c}" for c in ANNUAL_ONLY_GENERATOR_COLUMNS]
        + [f"plants.{c}" for c in ANNUAL_ONLY_PLANT_COLUMNS]
    )
    annual_detail_join_sql = f"""
            LEFT JOIN (
                SELECT generators.plant_id_eia, generators.generator_id,
                    {detail_columns_str}
                FROM read_parquet('{generators_parquet_path}') AS generators
                JOIN read_parquet('{plants_parquet_path}') AS plants
                USING (plant_id_eia, report_date)
                WHERE report_date = '{annual_detail_report_date}'
            ) AS annual_detail
            ON generators.plant_id_eia = annual_detail.plant_id_eia
            AND generators.generator_id = annual_detail.generator_id"""

    return "annual_detail", "annual_detail", annual_detail_join_sql


def get_eia_generator_data_from_pudl_parquet(
    raw_data_directory,
    pudl_download_directory,
    report_date,
    pudl_version,
    annual_detail_report_date=None,
    quiet=False,
):
    """
    Generator list from EIA860: the full single-vintage snapshot, with no
    further filtering — operational-status, region, etc. filtering happens
    downstream in the to-input-csvs Data Toolkit steps.

    With *annual_detail_report_date*, the FLEET (row set and every
    always-populated column) still comes from *report_date*, but the
    annual-form-only columns are backfilled from that as-filed vintage —
    so a fresh monthly_update fleet can carry annual detail for the units
    that existed at the pinned vintage, NULL for newer ones. See
    ANNUAL_ONLY_GENERATOR_COLUMNS / ANNUAL_ONLY_PLANT_COLUMNS. (The extra
    join may also emit the rows in a different order; the raw-data loader
    appends by column name, so that is immaterial.)
    """
    filepath = os.path.join(raw_data_directory, "pudl_eia860_generators.csv")

    if determine_proceed(filepath):
        if not quiet:
            print(
                f"Getting generator list (report date {report_date}) from PUDL "
                f"parquet files to {filepath}..."
            )
        # A backfilled CSV mixes vintages, which the data itself does not
        # show (its report_date column is the fleet vintage) — say so, and
        # record it in the metadata trail below
        if annual_detail_report_date is not None and not quiet:
            print(
                f"    annual-form-only columns backfilled from the "
                f"{annual_detail_report_date} vintage (NULL for generators "
                f"absent from it)"
            )
        generators_parquet_path = os.path.join(
            pudl_download_directory, "core_eia860__scd_generators.parquet"
        )
        plants_parquet_path = os.path.join(
            pudl_download_directory, "core_eia860__scd_plants.parquet"
        )
        entity_parquet_path = os.path.join(
            pudl_download_directory, "core_eia__entity_generators.parquet"
        )
        if not os.path.exists(entity_parquet_path):
            raise FileNotFoundError(
                f"{entity_parquet_path} not found. The generator entity "
                f"table was added to the PUDL download list in July 2026 "
                f"(it provides the generator operating date and CHP flag); "
                f"re-run gridpath_get_pudl_data to download it."
            )

        # The annual-form-only columns come either from the selected
        # vintage's own rows (the default) or, with
        # annual_detail_report_date, from the pinned as-filed vintage
        gen_detail_src, plant_detail_src, annual_detail_join_sql = (
            get_annual_detail_sql(
                generators_parquet_path=generators_parquet_path,
                plants_parquet_path=plants_parquet_path,
                annual_detail_report_date=annual_detail_report_date,
            )
        )

        # Date columns are cast to VARCHAR so the CSV holds plain
        # 'YYYY-MM-DD' strings, as when these came from pudl.sqlite TEXT
        # columns; version_num is the PUDL release version (pudl.sqlite's
        # alembic_version table, the previous source, has no parquet
        # equivalent). The annual-form-only columns (see
        # ANNUAL_ONLY_GENERATOR_COLUMNS / ANNUAL_ONLY_PLANT_COLUMNS) are
        # NULL in a monthly_update vintage unless backfilled; note
        # sector_name_eia is NOT one of them (it IS populated there).
        query = f"""
            SELECT
                '{pudl_version}' AS version_num,
                CAST(report_date AS VARCHAR) AS report_date,
                generators.plant_id_eia,
                generators.generator_id,
                operational_status_code,
                operational_status,
                balancing_authority_code_eia,
                capacity_mw,
                summer_capacity_mw,
                winter_capacity_mw,
                {gen_detail_src}.minimum_load_mw AS minimum_load_mw,
                energy_storage_capacity_mwh,
                prime_mover_code,
                energy_source_code_1,
                {gen_detail_src}.energy_source_code_2 AS energy_source_code_2,
                fuel_type_code_pudl,
                technology_description,
                {gen_detail_src}.can_burn_multiple_fuels
                    AS can_burn_multiple_fuels,
                {gen_detail_src}.can_cofire_fuels AS can_cofire_fuels,
                {gen_detail_src}.can_switch_oil_gas AS can_switch_oil_gas,
                {gen_detail_src}.carbon_capture AS carbon_capture,
                {gen_detail_src}.time_cold_shutdown_full_load_code
                    AS time_cold_shutdown_full_load_code,
                {gen_detail_src}.ownership_code AS ownership_code,
                generators.utility_id_eia,
                {plant_detail_src}.sector_id_eia AS sector_id_eia,
                sector_name_eia,
                {plant_detail_src}.ferc_cogen_status AS ferc_cogen_status,
                {plant_detail_src}.primary_purpose_id_naics
                    AS primary_purpose_id_naics,
                associated_combined_heat_power,
                CAST(generator_operating_date AS VARCHAR)
                    AS generator_operating_date,
                CAST(current_planned_generator_operating_date AS VARCHAR)
                    AS current_planned_generator_operating_date,
                CAST(generator_retirement_date AS VARCHAR)
                    AS generator_retirement_date,
                CAST(planned_generator_retirement_date AS VARCHAR)
                    AS planned_generator_retirement_date
            FROM read_parquet('{generators_parquet_path}') AS generators
            JOIN read_parquet('{plants_parquet_path}') AS plants
            USING (plant_id_eia, report_date)
            LEFT JOIN read_parquet('{entity_parquet_path}') AS entity
            ON generators.plant_id_eia = entity.plant_id_eia
            AND generators.generator_id = entity.generator_id{annual_detail_join_sql}
            WHERE report_date = '{report_date}'
        """

        # Query the parquet files and save to CSV
        eia_gens = duckdb.sql(query).df()
        eia_gens.to_csv(
            filepath,
            index=False,
        )

        settings = {
            "eia860_report_date": report_date,
            "pudl_version": pudl_version,
        }
        if annual_detail_report_date is not None:
            settings["eia860_annual_detail_report_date"] = annual_detail_report_date
        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="pudl_eia860_generators.csv",
            settings=settings,
        )


def get_eia860m_generator_data_from_pudl_parquet(
    raw_data_directory,
    pudl_download_directory,
    pudl_version,
    latest_only=True,
    quiet=False,
):
    """
    Generator data from the EIA860M (monthly) changelog, in which each row
    is one generator change, valid from report_date until valid_until_date.
    By default (*latest_only*), only each generator's latest changelog
    entry is kept — the latest available fleet snapshot. With
    *latest_only* off (the eia860m_full_changelog setting), the full
    changelog is kept instead, which allows downstream steps to
    reconstruct the fleet as of any month; latest-only data gives up that
    flexibility — a downstream as-of date before a generator's last change
    drops the generator (no earlier row to resolve to) rather than
    resolving to its state at that date, so with the default data use
    as-of dates at or after the changelog's end (the downstream default).

    No other filtering happens here — operational-status (e.g. retired),
    region, etc. filtering happens downstream in the to-input-csvs Data
    Toolkit steps.
    """
    filepath = os.path.join(raw_data_directory, "pudl_eia860m_generators.csv")

    if determine_proceed(filepath):
        if not quiet:
            print(
                f"Getting EIA860M generator changelog from PUDL parquet files "
                f"to {filepath}..."
            )
        changelog_parquet_path = os.path.join(
            pudl_download_directory, "core_eia860m__changelog_generators.parquet"
        )

        latest_only_str = (
            """QUALIFY ROW_NUMBER() OVER (
                PARTITION BY plant_id_eia, generator_id
                ORDER BY report_date DESC
            ) = 1"""
            if latest_only
            else ""
        )

        # Date columns are cast to VARCHAR so the CSV holds plain
        # 'YYYY-MM-DD' strings (same convention as pudl_eia860_generators.csv)
        query = f"""
            SELECT
                '{pudl_version}' AS version_num,
                CAST(report_date AS VARCHAR) AS report_date,
                CAST(valid_until_date AS VARCHAR) AS valid_until_date,
                plant_id_eia,
                generator_id,
                operational_status_code,
                operational_status,
                balancing_authority_code_eia,
                capacity_mw,
                summer_capacity_mw,
                winter_capacity_mw,
                energy_storage_capacity_mwh,
                prime_mover_code,
                energy_source_code_1,
                fuel_type_code_pudl,
                technology_description,
                sector_id_eia,
                CAST(generator_operating_date AS VARCHAR)
                    AS generator_operating_date,
                CAST(current_planned_generator_operating_date AS VARCHAR)
                    AS current_planned_generator_operating_date,
                CAST(generator_retirement_date AS VARCHAR)
                    AS generator_retirement_date,
                CAST(planned_generator_retirement_date AS VARCHAR)
                    AS planned_generator_retirement_date
            FROM read_parquet('{changelog_parquet_path}')
            {latest_only_str}
            ORDER BY plant_id_eia, generator_id, report_date
        """

        # Query the parquet file and save to CSV
        eia860m_gens = duckdb.sql(query).df()
        eia860m_gens.to_csv(
            filepath,
            index=False,
        )

        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="pudl_eia860m_generators.csv",
            settings={
                "latest_only": latest_only,
                "pudl_version": pudl_version,
            },
        )


def get_eia_baa_codes_from_pudl_parquet(
    raw_data_directory, pudl_download_directory, quiet=False
):
    """
    The EIA balancing-authority map, from PUDL's static
    core_eia__codes_balancing_authorities table: one row per BA (the PUDL
    'code' column, written as 'baa') with its EIA930 region
    (balancing_authority_region_code_eia, written as 'region' — the
    study-scope region filter of the to-input-csvs steps), its
    interconnection (interconnect_code_eia, written as 'interconnect'),
    and its retirement date / generation-only flag / timezone. No
    filtering and no vintage — the table is a static code map.
    """
    filepath = os.path.join(raw_data_directory, "pudl_eia_baa_codes.csv")

    if determine_proceed(filepath):
        if not quiet:
            print(
                f"Getting the EIA balancing-authority map from PUDL parquet "
                f"files to {filepath}..."
            )
        baa_codes_parquet_path = os.path.join(
            pudl_download_directory, "core_eia__codes_balancing_authorities.parquet"
        )

        query = f"""
            SELECT
                code AS baa,
                balancing_authority_region_code_eia AS region,
                balancing_authority_region_name_eia AS region_name,
                interconnect_code_eia AS interconnect,
                CAST(balancing_authority_retirement_date AS VARCHAR)
                    AS retirement_date,
                is_generation_only,
                report_timezone AS timezone
            FROM read_parquet('{baa_codes_parquet_path}')
            ORDER BY baa
        """

        baa_codes = duckdb.sql(query).df()
        baa_codes.to_csv(
            filepath,
            index=False,
        )

        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="pudl_eia_baa_codes.csv",
            settings={"source_file": os.path.basename(baa_codes_parquet_path)},
        )


def get_eiaaeo_fuel_data_from_pudl_parquet(
    raw_data_directory,
    pudl_download_directory,
    quiet=False,
):
    """
    The full EIA AEO fuel price table, with no filtering — the fuel input
    steps scope regions downstream via the user_defined_eiaaeo_region_key
    mapping (and pick the report year there).
    """
    filepath = os.path.join(raw_data_directory, "pudl_eiaaeo_fuel_prices.csv")

    if determine_proceed(filepath):
        if not quiet:
            print(f"Getting fuel prices from PUDL parquet files to {filepath}...")
        fuel_prices_parquet_path = os.path.join(
            pudl_download_directory,
            "core_eiaaeo__yearly_projected_fuel_cost_in_electric_sector_by_type"
            ".parquet",
        )

        query = f"""
                SELECT * FROM read_parquet('{fuel_prices_parquet_path}')
                ORDER BY report_year, electricity_market_module_region_eiaaeo,
                model_case_eiaaeo, fuel_type_eiaaeo, projection_year
            """

        # Query the parquet file and save to CSV
        fuel_prices_df = duckdb.sql(query).df()

        fuel_prices_df.to_csv(
            filepath,
            index=False,
        )

        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="pudl_eiaaeo_fuel_prices.csv",
            settings={"source_file": os.path.basename(fuel_prices_parquet_path)},
        )


def convert_eia930_hourly_interchange_to_csv(
    raw_data_directory, pudl_download_directory, quiet=False
):

    filepath = os.path.join(raw_data_directory, "pudl_eia930_hourly_interchange.csv")

    if determine_proceed(filepath):
        if not quiet:
            print(f"Converting hourly interchange data to CSV {filepath}...")
        parquet_path = os.path.join(
            pudl_download_directory, "core_eia930__hourly_interchange.parquet"
        )
        df = duckdb.sql(f"SELECT * FROM read_parquet('{parquet_path}')").df()

        df["datetime_pst_he"] = df["datetime_utc"] - pd.to_timedelta(8, unit="h")
        df["year_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).year
        df["month_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).month
        df["day_of_month_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).day
        df["hour_of_day_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).hour

        df["datetime_pst_hs"] = df["datetime_utc"] - pd.to_timedelta(9, unit="h")
        df["year_hs"] = pd.DatetimeIndex(df["datetime_pst_hs"]).year
        df["month_hs"] = pd.DatetimeIndex(df["datetime_pst_hs"]).month
        df["day_of_month_hs"] = pd.DatetimeIndex(df["datetime_pst_hs"]).day
        df["hour_of_day_hs"] = pd.DatetimeIndex(df["datetime_pst_hs"]).hour

        # Populate initial values based on HE; use int64 to avoid
        # LossySetitemError on pandas 2.x when overwriting with HS values
        df["year"] = df["year_he"].astype("int64")
        df["month"] = df["month_he"].astype("int64")
        df["day_of_month"] = df["day_of_month_he"].astype("int64")
        df["hour_of_day"] = df["hour_of_day_he"].astype("int64")

        # Go from HE timestamps to 1-24 timepoint indexing; skip if there
        # are no midnight rows — pandas 3.0 raises on assigning a
        # full-length frame to an empty .loc selection
        midnight_mask = df["hour_of_day"] == 0
        if midnight_mask.any():
            df.loc[
                midnight_mask,
                ["year", "month", "day_of_month", "hour_of_day"],
            ] = pd.DataFrame(
                {
                    "year": df["year_hs"],
                    "month": df["month_hs"],
                    "day_of_month": df["day_of_month_hs"],
                    "hour_of_day": 24,
                },
                index=df.index,
            )

        cols = df.columns.tolist()
        cols = cols[0:5] + cols[14:18]
        df = df[cols]

        df.to_csv(
            filepath,
            sep=",",
            index=False,
        )

        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="pudl_eia930_hourly_interchange.csv",
            settings={"source_file": os.path.basename(parquet_path)},
        )


def convert_eia930_net_generation_to_csv(
    raw_data_directory, pudl_download_directory, quiet=False
):
    """
    EIA930 net generation by BA and energy source, aggregated from hourly
    to MONTHLY totals (the one transformation this step applies beyond
    vintage selection — the hourly rows would make the raw CSV
    unmanageably large, and BA-level reconciliation works with
    monthly/annual totals). Hours are assigned to
    months on the same PST hour-ending clock the hourly interchange
    conversion uses. The energy-source vocabulary is kept as published —
    including the overlapping subcategories (e.g.
    wind_wo_integrated_battery_storage alongside wind) — so consumers
    must filter to the main categories to avoid double counting.
    """
    filepath = os.path.join(
        raw_data_directory, "pudl_eia930_net_generation_by_fuel.csv"
    )

    if determine_proceed(filepath):
        if not quiet:
            print(
                f"Converting EIA930 net generation by energy source to "
                f"monthly CSV {filepath}..."
            )
        parquet_path = os.path.join(
            pudl_download_directory,
            "core_eia930__hourly_net_generation_by_energy_source.parquet",
        )

        # PST hour-ending: hour 0 UTC-8 belongs to the previous day's hour
        # 24, i.e. subtracting one more second before truncating to the
        # month gives the hour-ending month label
        query = f"""
            SELECT
                balancing_authority_code_eia,
                EXTRACT(year FROM datetime_pst_he_label) AS year,
                EXTRACT(month FROM datetime_pst_he_label) AS month,
                generation_energy_source,
                SUM(net_generation_reported_mwh)
                    AS net_generation_reported_mwh,
                SUM(net_generation_adjusted_mwh)
                    AS net_generation_adjusted_mwh,
                SUM(net_generation_imputed_eia_mwh)
                    AS net_generation_imputed_eia_mwh
            FROM (
                SELECT *,
                    datetime_utc - INTERVAL 8 HOUR - INTERVAL 1 SECOND
                        AS datetime_pst_he_label
                FROM read_parquet('{parquet_path}')
            )
            GROUP BY 1, 2, 3, 4
            ORDER BY 1, 2, 3, 4
        """

        df = duckdb.sql(query).df()
        df.to_csv(
            filepath,
            index=False,
        )

        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="pudl_eia930_net_generation_by_fuel.csv",
            settings={"source_file": os.path.basename(parquet_path)},
        )


def convert_eia930_operations_to_csv(
    raw_data_directory, pudl_download_directory, quiet=False
):
    """
    EIA930 per-BA net generation, interchange and demand, aggregated from
    hourly to MONTHLY totals on the same PST hour-ending clock the other
    hourly conversions use (see
    ``convert_eia930_net_generation_to_csv`` for why the aggregation
    happens here).

    EIA derives demand as net generation minus net interchange, so the
    three columns should satisfy that identity. Testing it is only
    meaningful on hours where all three are reported: a BA can be missing
    interchange for hours it reports generation for, and summing the
    columns over different hour sets breaks the identity spuriously (in
    2024 this would have manufactured a 9 TWh residual for CISO, whose
    interchange covers 6,552 of its 8,736 reported-demand hours). Each
    column is therefore written twice — summed over every hour, and
    summed over complete hours only — plus the per-column non-null hour
    counts. Because both sums are linear over the same hour set, the
    identity residual is just the difference of the three complete-hours
    columns.
    """
    filepath = os.path.join(raw_data_directory, "pudl_eia930_operations.csv")

    if determine_proceed(filepath):
        if not quiet:
            print(
                f"Converting EIA930 hourly operations to monthly CSV " f"{filepath}..."
            )
        parquet_path = os.path.join(
            pudl_download_directory,
            "core_eia930__hourly_operations.parquet",
        )

        complete_hour_sql = """
            net_generation_reported_mwh IS NOT NULL
            AND interchange_reported_mwh IS NOT NULL
            AND demand_reported_mwh IS NOT NULL
        """
        query = f"""
            SELECT
                balancing_authority_code_eia,
                EXTRACT(year FROM datetime_pst_he_label) AS year,
                EXTRACT(month FROM datetime_pst_he_label) AS month,
                SUM(net_generation_reported_mwh)
                    AS net_generation_reported_mwh,
                SUM(interchange_reported_mwh) AS interchange_reported_mwh,
                SUM(demand_reported_mwh) AS demand_reported_mwh,
                SUM(demand_adjusted_mwh) AS demand_adjusted_mwh,
                SUM(CASE WHEN {complete_hour_sql}
                        THEN net_generation_reported_mwh END)
                    AS net_generation_complete_hours_mwh,
                SUM(CASE WHEN {complete_hour_sql}
                        THEN interchange_reported_mwh END)
                    AS interchange_complete_hours_mwh,
                SUM(CASE WHEN {complete_hour_sql}
                        THEN demand_reported_mwh END)
                    AS demand_complete_hours_mwh,
                COUNT(*) AS hours,
                COUNT(net_generation_reported_mwh)
                    AS hours_net_generation_reported,
                COUNT(interchange_reported_mwh) AS hours_interchange_reported,
                COUNT(demand_reported_mwh) AS hours_demand_reported,
                SUM(CASE WHEN {complete_hour_sql} THEN 1 ELSE 0 END)
                    AS hours_complete
            FROM (
                SELECT *,
                    datetime_utc - INTERVAL 8 HOUR - INTERVAL 1 SECOND
                        AS datetime_pst_he_label
                FROM read_parquet('{parquet_path}')
            )
            GROUP BY 1, 2, 3
            ORDER BY 1, 2, 3
        """

        df = duckdb.sql(query).df()
        df.to_csv(
            filepath,
            index=False,
        )

        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="pudl_eia930_operations.csv",
            settings={"source_file": os.path.basename(parquet_path)},
        )


def convert_eia923_generation_fuel_to_csv(
    raw_data_directory, pudl_download_directory, start_year, quiet=False
):
    """
    EIA923 monthly plant-level generation actuals by energy source and
    prime mover, from PUDL's combined generation-fuel table (which,
    unlike the core table, includes nuclear plants). Rows are kept from
    *start_year* on (a vintage selection; the default matches the start
    of the EIA930 generation-by-energy-source reporting these actuals
    are reconciled against) — no other filtering happens here.
    """
    filepath = os.path.join(raw_data_directory, "pudl_eia923_plant_fuel_generation.csv")

    if determine_proceed(filepath):
        if not quiet:
            print(
                f"Converting EIA923 plant-fuel generation (from "
                f"{start_year} on) to CSV {filepath}..."
            )
        parquet_path = os.path.join(
            pudl_download_directory,
            "out_eia923__monthly_generation_fuel_combined.parquet",
        )

        query = f"""
            SELECT
                plant_id_eia,
                CAST(report_date AS VARCHAR) AS report_date,
                energy_source_code,
                fuel_type_code_pudl,
                prime_mover_code,
                net_generation_mwh,
                data_maturity
            FROM read_parquet('{parquet_path}')
            WHERE report_date >= '{start_year}-01-01'
            ORDER BY plant_id_eia, report_date, energy_source_code,
                prime_mover_code
        """

        df = duckdb.sql(query).df()
        df.to_csv(
            filepath,
            index=False,
        )

        log_data_metadata(
            directory=raw_data_directory,
            script="pudl_to_gridpath_raw_data",
            output_file="pudl_eia923_plant_fuel_generation.csv",
            settings={
                "eia923_start_year": start_year,
                "source_file": os.path.basename(parquet_path),
            },
        )


def determine_proceed(filepath):
    proceed = True
    if os.path.exists(filepath):
        proceed = confirm(
            f"WARNING: The file {filepath} already exists. This will overwrite "
            f"the previous file. Are you sure?"
        )

    return proceed


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    os.makedirs(parsed_args.raw_data_directory, exist_ok=True)

    # Record the arguments this run was given (defaults show up as empty /
    # unresolved values; the per-file entries below record resolved values)
    # and carry forward the metadata of the downloaded data we start from
    log_data_metadata(
        directory=parsed_args.raw_data_directory,
        script="pudl_to_gridpath_raw_data",
        output_file="run_arguments",
        settings=vars(parsed_args),
    )
    copy_data_metadata(
        from_directory=parsed_args.pudl_download_directory,
        to_directory=parsed_args.raw_data_directory,
    )
    warn_on_mixed_pudl_versions(
        pudl_download_directory=parsed_args.pudl_download_directory,
        log_directory=parsed_args.raw_data_directory,
        script="pudl_to_gridpath_raw_data",
    )

    ### Get only the data we need from the PUDL parquet files ### #
    # Generator list
    eia860_report_date = determine_eia860_report_date(
        pudl_download_directory=parsed_args.pudl_download_directory,
        eia860_report_date=parsed_args.eia860_report_date,
    )
    warn_on_baa_coverage(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        eia860_report_date=eia860_report_date,
    )
    get_eia_generator_data_from_pudl_parquet(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        report_date=eia860_report_date,
        pudl_version=determine_pudl_version(
            pudl_download_directory=parsed_args.pudl_download_directory,
            pudl_version=parsed_args.pudl_version,
            source_file="core_eia860__scd_generators.parquet",
        ),
        annual_detail_report_date=parsed_args.eia860_annual_detail_report_date,
        quiet=parsed_args.quiet,
    )

    # Generator changelog from EIA860M
    get_eia860m_generator_data_from_pudl_parquet(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        latest_only=not parsed_args.eia860m_full_changelog,
        pudl_version=determine_pudl_version(
            pudl_download_directory=parsed_args.pudl_download_directory,
            pudl_version=parsed_args.pudl_version,
            source_file="core_eia860m__changelog_generators.parquet",
        ),
        quiet=parsed_args.quiet,
    )

    # Balancing-authority map
    get_eia_baa_codes_from_pudl_parquet(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        quiet=parsed_args.quiet,
    )

    # Fuel costs
    get_eiaaeo_fuel_data_from_pudl_parquet(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        quiet=parsed_args.quiet,
    )

    # ### EIA930 hourly interchange ### #
    convert_eia930_hourly_interchange_to_csv(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        quiet=parsed_args.quiet,
    )

    # ### EIA930 net generation by energy source (monthly) ### #
    convert_eia930_net_generation_to_csv(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        quiet=parsed_args.quiet,
    )

    # ### EIA930 per-BA operations: generation, interchange, demand ### #
    convert_eia930_operations_to_csv(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        quiet=parsed_args.quiet,
    )

    # ### EIA923 plant-fuel generation actuals ### #
    convert_eia923_generation_fuel_to_csv(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        start_year=parsed_args.eia923_start_year,
        quiet=parsed_args.quiet,
    )


if __name__ == "__main__":
    main()
