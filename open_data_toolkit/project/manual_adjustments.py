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
Manual Adjustments
******************

The post-processing escape hatch of the project pipeline: patch gaps in
the ALREADY-GENERATED project input CSVs that the raw data cannot fill.
Run it after the other project-level steps, with the same shared settings
(so its queries name the same projects the other steps generated). Two
kinds of adjustment are made:

* **User-provided project files**: per the instructions in the
  ``files_to_copy_csv`` file, copy an existing per-project input CSV to
  serve as another project's inputs (e.g. give a project a neighbor's
  hydro characteristics when it has none of its own). The copies are
  written next to the generated files, named
  ``<new_project>-<id>-<name>_MANUAL_copy_from_<copy_project>_<id>.csv``
  so their provenance is visible.
* **Default storage durations**: EIA860 reports no energy capacity for
  some storage units, which leaves ``specified_stor_capacity_mwh`` NULL
  in the generated specified-capacity CSV. This step fills those NULLs
  (only those — existing values are never overwritten) with
  ``duration × specified_capacity_mw``, using the ``battery_duration``
  and ``pumped_storage_duration`` settings for battery (BA) and
  pumped-storage (PS) prime movers respectively.

Because its patches only ever update rows that already exist in the
generated CSVs, this step deliberately queries a SUPERSET fleet (e.g.
behind-the-meter units are always included, and it takes no
fleet-selection settings of its own) — extra units in its queries are
harmless, missing ones would silently leave gaps unpatched.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step manual_adjustments --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_eia860_generators
    * user_defined_eia_gridpath_key
    * raw_data_eia_baa_codes

=========
Settings
=========
    * database
    * files_to_copy_csv
    * capacity_specified_directory
    * project_specified_capacity_scenario_id
    * project_specified_capacity_scenario_name
    * study_year
    * footprint
    * ba_source
    * load_zone_level
    * project_aggregation
    * aggregation_dimensions
    * aggregation_level
    * battery_duration
    * pumped_storage_duration
"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import duckdb
import os.path
import shutil
import sys
import pandas as pd

from open_data_toolkit.project.fleet.fleet_filters import get_fleet_relation_sql
from open_data_toolkit.project.fleet.step_common import (
    connect_and_check_scope,
    get_project_name_str_from_args,
    add_shared_project_step_arguments,
)

# Storage durations
STORAGE_DURATION_DEFAULTS = {"BA": 1, "PS": 12}
SPEC_CAP_ID_DEFAULT = 1
SPEC_CAP_NAME_DEFAULT = "base"


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="../../open_data_raw.db")

    # Missing storage durations
    parser.add_argument(
        "-copy",
        "--files_to_copy_csv",
        default="../db/csvs_open_data/raw_data"
        "/user_defined_manual_adjustments_copy_files.csv",
    )

    # Missing storage durations
    parser.add_argument(
        "-cap_dir",
        "--capacity_specified_directory",
        default="../../csvs_open_data/project/capacity_specified",
    )
    parser.add_argument(
        "-cap_id",
        "--project_specified_capacity_scenario_id",
        default=SPEC_CAP_ID_DEFAULT,
    )
    parser.add_argument(
        "-cap_name",
        "--project_specified_capacity_scenario_name",
        default=SPEC_CAP_NAME_DEFAULT,
    )
    add_shared_project_step_arguments(parser=parser, fleet_selection=False)
    parser.add_argument(
        "-ba_dur",
        "--battery_duration",
        default=STORAGE_DURATION_DEFAULTS["BA"],
        help=f"Defaults to '{STORAGE_DURATION_DEFAULTS['PS']}'.",
    )
    parser.add_argument(
        "-ps_dur",
        "--pumped_storage_duration",
        default=STORAGE_DURATION_DEFAULTS["PS"],
        help=f"Defaults to '{STORAGE_DURATION_DEFAULTS['PS']}'.",
    )

    # Overwrite existing files
    parser.add_argument(
        "-o",
        "--overwrite",
        default=False,
        action="store_true",
        help="Overwrite existing CSV files.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def make_copy_files(
    new_file_directory,
    new_project,
    new_project_scenario_id,
    new_project_scenario_name,
    file_to_copy_directory,
    copy_project,
    copy_project_scenario_id,
    copy_project_scenario_name,
):

    file_to_copy = os.path.join(
        file_to_copy_directory,
        f"{copy_project}-{copy_project_scenario_id}-{copy_project_scenario_name}.csv",
    )

    new_file = os.path.join(
        new_file_directory,
        f"{new_project}-{new_project_scenario_id}-{new_project_scenario_name}_MANUAL_copy_from"
        f"_{copy_project}_{copy_project_scenario_id}.csv",
    )

    shutil.copyfile(file_to_copy, new_file)


def add_battery_durations(
    conn,
    project_name_str,
    fleet_relation_sql,
    study_year,
    csv_location,
    subscenario_id,
    subscenario_name,
    tech_dur_dict,
    aggregate_projects=False,
):
    duckdb_conn = duckdb.connect(database=":memory:")
    spec_cap_df = pd.read_csv(
        os.path.join(csv_location, f"{subscenario_id}_" f"{subscenario_name}.csv")
    )

    spec_cap_updated_df = duckdb_conn.sql(
        """CREATE TABLE spec_cap_table AS SELECT * FROM spec_cap_df;"""
    )

    for tech in tech_dur_dict.keys():
        group_by = "GROUP BY project" if aggregate_projects else ""
        sql = f"""
            SELECT {project_name_str} AS project,
            {study_year} as period
            {fleet_relation_sql}
            AND raw_data_eia860_generators.prime_mover_code = '{tech}'
            {group_by}
            ;
        """
        relevant_projects_df = pd.read_sql(sql, conn)

        if not relevant_projects_df.empty:
            spec_cap_updated_df = duckdb_conn.sql(f"""
                CREATE TABLE {tech}_relevant_projects_table
                AS SELECT * FROM relevant_projects_df
                ;
                --SELECT * FROM relevant_projects_table;
                UPDATE spec_cap_table
                SET specified_stor_capacity_mwh = {tech_dur_dict[tech]}*specified_capacity_mw
                WHERE (project, period) IN (SELECT (project, period) FROM {tech}_relevant_projects_table)
                AND specified_stor_capacity_mwh IS NULL
                ;
                """)

    spec_cap_updated_df = duckdb_conn.sql("""
        SELECT * FROM spec_cap_table
        ;
        """).df()

    spec_cap_updated_df.to_csv(
        os.path.join(csv_location, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args)

    if not parsed_args.quiet:
        print("Making manual adjustments")

    project_name_str = get_project_name_str_from_args(parsed_args)

    conn = connect_and_check_scope(parsed_args)

    # Add missing project files
    copy_files_df = pd.read_csv(parsed_args.files_to_copy_csv, index_col=False)
    for index, row in copy_files_df.iterrows():
        make_copy_files(
            new_file_directory=row["new_file_directory"],
            new_project=row["new_project"],
            new_project_scenario_id=row["new_project_scenario_id"],
            new_project_scenario_name=row["new_project_scenario_name"],
            file_to_copy_directory=row["file_to_copy_directory"],
            copy_project=row["copy_project"],
            copy_project_scenario_id=row["copy_project_scenario_id"],
            copy_project_scenario_name=row["copy_project_scenario_name"],
        )

    # Add missing storage durations
    tech_dur_dict = {
        "BA": parsed_args.battery_duration,
        "PS": parsed_args.pumped_storage_duration,
    }

    add_battery_durations(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=get_fleet_relation_sql(
            ba_source=parsed_args.ba_source,
            study_year=parsed_args.study_year,
            footprint=parsed_args.footprint,
            # the battery-duration patch is UPDATE-only against existing
            # CSV rows, so a superset fleet is harmless — and required if
            # the CSVs were generated with include_btm_plants,
            # include_planned_retirements, or include_net_metered
            include_btm_plants=True,
            include_planned_retirements=True,
            include_net_metered=True,
        ),
        study_year=parsed_args.study_year,
        csv_location=parsed_args.capacity_specified_directory,
        subscenario_id=parsed_args.project_specified_capacity_scenario_id,
        subscenario_name=parsed_args.project_specified_capacity_scenario_name,
        tech_dur_dict=tech_dur_dict,
        aggregate_projects=parsed_args.project_aggregation != "none",
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
