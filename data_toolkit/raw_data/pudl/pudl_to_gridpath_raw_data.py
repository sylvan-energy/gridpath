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
* `GridPath RA Toolkit <https://gridlab.org/gridpathratoolkit/>`__ variable generation profiles created for the 2026 Western RA Study: these include hourly wind profiles by WECC BA based on assumed 2026 wind buildout for weather years 2007-2014 and hourly solar profiles by WECC BA based on assumed 2026 buildout for weather years 1998-2019; see the study for how profiles were created and note the study was conducted in 2022.

First, the data must be converted to the GridPath raw data CSV format. For the
purpose, use the ``gridpath_pudl_to_gridpath_raw`` command.

This will query and process the per-table Parquet files downloaded in the
previous step in order to create the following files in the user-specified
raw data directory.

* pudl_eia860_generators.csv
* pudl_eia930_hourly_interchange.csv
* pudl_eiaaeo_fuel_prices.csv
* pudl_ra_toolkit_var_profiles.csv

For options, including the download and raw data directories as well query
filters see the --help menu. By default, we currently use 2026-01-01 as the
EIA860 reporting data and "western_electricity_coordinating_council" as the
EIA AEO electricity market to get data for.
"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import duckdb
import os.path
import pandas as pd
import sys

from db.utilities.common_functions import confirm
from data_toolkit.raw_data.pudl.download_data_from_pudl import PUDL_VERSION_DEFAULT

DOWNLOAD_DIRECTORY_DEFAULT = "./pudl_download"
RAW_DATA_DIRECTORY_DEFAULT = "./raw_data"
EIA860_DEFAULT_REPORT_DATE = "2026-01-01"
EIAAEO_DEFAULT_ELECTRICITY_MARKET = "western_electricity_coordinating_council"


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
        default=EIA860_DEFAULT_REPORT_DATE,
        help=f"Defaults to {EIA860_DEFAULT_REPORT_DATE}",
    )

    parser.add_argument(
        "-er",
        "--eia860_include_retired",
        default=False,
        action="store_true",
    )

    parser.add_argument(
        "-fr",
        "--eiaaeo_electricity_market_region",
        default=EIAAEO_DEFAULT_ELECTRICITY_MARKET,
        help=f"Defaults to {EIAAEO_DEFAULT_ELECTRICITY_MARKET}",
    )

    parser.add_argument(
        "-v_pudl",
        "--pudl_version",
        default=PUDL_VERSION_DEFAULT,
        help=f"The PUDL data release the downloaded files came from; stamped "
        f"into the version_num column of pudl_eia860_generators.csv. "
        f"Defaults to {PUDL_VERSION_DEFAULT}.",
    )

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def get_eia_generator_data_from_pudl_parquet(
    raw_data_directory,
    pudl_download_directory,
    report_date,
    exclude_retired,
    pudl_version,
):
    """
    Generator list from EIA860.
    """
    filepath = os.path.join(raw_data_directory, "pudl_eia860_generators.csv")

    if determine_proceed(filepath):
        print(f"Getting generator list from PUDL parquet files to {filepath}...")
        generators_parquet_path = os.path.join(
            pudl_download_directory, "core_eia860__scd_generators.parquet"
        )
        plants_parquet_path = os.path.join(
            pudl_download_directory, "core_eia860__scd_plants.parquet"
        )

        # Build the generator query
        exclude_retired_str = (
            "AND operational_status != 'retired'" if exclude_retired else ""
        )

        # Date columns are cast to VARCHAR so the CSV holds plain
        # 'YYYY-MM-DD' strings, as when these came from pudl.sqlite TEXT
        # columns; version_num is the PUDL release version (pudl.sqlite's
        # alembic_version table, the previous source, has no parquet
        # equivalent)
        query = f"""
            SELECT
                '{pudl_version}' AS version_num,
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
                CAST(current_planned_generator_operating_date AS VARCHAR)
                    AS current_planned_generator_operating_date,
                CAST(generator_retirement_date AS VARCHAR)
                    AS generator_retirement_date
            FROM read_parquet('{generators_parquet_path}') AS generators
            JOIN read_parquet('{plants_parquet_path}') AS plants
            USING (plant_id_eia, report_date)
            WHERE report_date = '{report_date}'
            {exclude_retired_str}
        """

        # Query the parquet files and save to CSV
        eia_gens = duckdb.sql(query).df()
        eia_gens.to_csv(
            filepath,
            index=False,
        )


def get_eiaaeo_fuel_data_from_pudl_parquet(
    raw_data_directory, pudl_download_directory, eiaaeo_electricity_market_region
):
    """ """
    filepath = os.path.join(raw_data_directory, "pudl_eiaaeo_fuel_prices.csv")

    if determine_proceed(filepath):
        print(f"Getting fuel prices from PUDL parquet files to {filepath}...")
        fuel_prices_parquet_path = os.path.join(
            pudl_download_directory,
            "core_eiaaeo__yearly_projected_fuel_cost_in_electric_sector_by_type"
            ".parquet",
        )

        query = f"""
                SELECT * FROM read_parquet('{fuel_prices_parquet_path}')
                WHERE electricity_market_module_region_eiaaeo LIKE '%{eiaaeo_electricity_market_region}%'
                ORDER BY report_year, electricity_market_module_region_eiaaeo,
                model_case_eiaaeo, fuel_type_eiaaeo, projection_year
            """

        # Query the parquet file and save to CSV
        fuel_prices_df = duckdb.sql(query).df()

        fuel_prices_df.to_csv(
            filepath,
            index=False,
        )


# TODO: confirm hour-ending vs hour-starting with Catalyst
def convert_ra_toolkit_profiles_to_csv(raw_data_directory, pudl_download_directory):
    """ """

    filepath = os.path.join(raw_data_directory, "pudl_ra_toolkit_var_profiles.csv")
    if determine_proceed(filepath):
        print(f"Converting RA Toolkit profiles to CSV {filepath}...")
        parquet_path = os.path.join(
            pudl_download_directory,
            "out_gridpathratoolkit__hourly_available_capacity_factor.parquet",
        )
        df = duckdb.sql(f"SELECT * FROM read_parquet('{parquet_path}')").df()

        df["datetime_pst_he"] = df["datetime_utc"] - pd.Timedelta(hours=8)
        df["year_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).year
        df["month_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).month
        df["day_of_month_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).day
        df["hour_of_day_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).hour

        df["datetime_pst_hs"] = df["datetime_utc"] - pd.Timedelta(hours=9)
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

        # Go from HE timestamps to 1-24 timepoint indexing
        df.loc[
            df["hour_of_day"] == 0,
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

        df = df.rename(
            columns={"aggregation_group": "unit", "capacity_factor": "cap_factor"}
        )
        cols = df.columns.tolist()
        cols = cols[13:17] + cols[1:3]
        df = df[cols]

        df.to_csv(
            filepath,
            sep=",",
            index=False,
        )


def convert_eia930_hourly_interchange_to_csv(
    raw_data_directory, pudl_download_directory
):

    filepath = os.path.join(raw_data_directory, "pudl_eia930_hourly_interchange.csv")

    if determine_proceed(filepath):
        print(f"Converting hourly interchange data to CSV {filepath}...")
        parquet_path = os.path.join(
            pudl_download_directory, "core_eia930__hourly_interchange.parquet"
        )
        df = duckdb.sql(f"SELECT * FROM read_parquet('{parquet_path}')").df()

        df["datetime_pst_he"] = df["datetime_utc"] - pd.Timedelta(hours=8)
        df["year_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).year
        df["month_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).month
        df["day_of_month_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).day
        df["hour_of_day_he"] = pd.DatetimeIndex(df["datetime_pst_he"]).hour

        df["datetime_pst_hs"] = df["datetime_utc"] - pd.Timedelta(hours=9)
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

        # Go from HE timestamps to 1-24 timepoint indexing
        df.loc[
            df["hour_of_day"] == 0,
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

    ### Get only the data we need from the PUDL parquet files ### #
    # Generator list
    get_eia_generator_data_from_pudl_parquet(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        report_date=parsed_args.eia860_report_date,
        exclude_retired=not parsed_args.eia860_include_retired,
        pudl_version=parsed_args.pudl_version,
    )

    # Fuel costs
    get_eiaaeo_fuel_data_from_pudl_parquet(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
        eiaaeo_electricity_market_region=parsed_args.eiaaeo_electricity_market_region,
    )

    # ### RA Toolkit profiles ### #
    convert_ra_toolkit_profiles_to_csv(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
    )

    # ### EIA930 hourly interchange ### #
    convert_eia930_hourly_interchange_to_csv(
        raw_data_directory=parsed_args.raw_data_directory,
        pudl_download_directory=parsed_args.pudl_download_directory,
    )


if __name__ == "__main__":
    main()
