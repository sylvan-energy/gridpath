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
Form EIA 860 Project Availability
*********************************

Create availability type CSV for a EIA860-based project portfolio. Availability
types are set to 'exogenous' for all projects with no exogenous profiles
specified (i.e., always available).

With ``seasonal_capacity_derates``, seasonal capacity ratings are also
written as monthly exogenous availability derates: EIA-860's net summer
and net winter capacity, expressed as fractions of nameplate capacity,
become ``availability_derate_monthly`` values for the summer months
(``summer_months``, default June–September, EIA's net-summer demonstration
window) and the winter months (``winter_months``, default December–February);
the remaining months stay at nameplate. Each project with a seasonal rating
that differs from nameplate gets a per-project CSV in the
``exogenous_monthly`` subdirectory of the output directory and its
``exogenous_availability_monthly_scenario_id`` filled in the main
availability CSV; projects whose ratings match nameplate (or whose seasonal
ratings are missing, which fall back to nameplate) carry no monthly derate.
For aggregated projects the derate is capacity-weighted across the group's
units. Derates above 1 are kept (winter ratings above nameplate occur, e.g.
for combustion turbines in cold, dense air).

By default, seasonal derates are only written for operational types whose
seasonal capability is not already modeled elsewhere: variable generators
(capacity-factor profiles) and hydro (energy budgets) are excluded, as is
storage (seasonal ratings match nameplate). The excluded types can be
changed with ``seasonal_derate_excluded_operational_types`` (an empty
value derates every type).

.. note:: EIA's net summer/winter ratings are net of station service while
    nameplate capacity is gross, so these derates also fold in auxiliary
    load — net dependable capacity, which is usually what dispatch against
    metered load wants. Don't stack a separate auxiliary-load adjustment
    on top.

.. note:: The query in this module is consistent with the project selection
    from ``eia860_to_project_portfolio_input_csvs``, which also documents
    what the EIA860 data vintage in the raw database means — in
    particular that the latest available vintage (the convert step's
    default) is PUDL's EIA860M-derived reconstruction of the in-progress
    report year, not an as-filed annual survey.

=====
Usage
=====

>>> gridpath_run_data_toolkit --single_step eia860_to_project_availability_input_csvs --settings_csv PATH/TO/SETTINGS/CSV

===================
Input prerequisites
===================

This module assumes the following raw input database tables have been populated:
    * raw_data_eia860_generators
    * user_defined_eia_gridpath_key

=========
Settings
=========
    * database
    * output_directory
    * study_year
    * footprint
    * include_retired
    * planned_inclusion
    * inactive_inclusion
    * include_planned_retirements
    * exclude_commercial_industrial_sectors
    * include_net_metered
    * require_plant_in_eia860_vintage
    * ba_source
    * load_zone_level
    * project_aggregation
    * aggregation_dimensions
    * aggregation_level
    * hybrid_treatment
    * project_availability_scenario_id
    * project_availability_scenario_name
    * seasonal_capacity_derates
    * summer_months
    * winter_months
    * seasonal_derate_excluded_operational_types
    * exogenous_availability_monthly_scenario_id
    * exogenous_availability_monthly_scenario_name

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys

from open_data_toolkit.project.fleet.step_common import (
    connect_and_check_scope,
    get_fleet_relation_sql_from_args,
    get_project_name_str_from_args,
    warn_on_fleet_data_gaps,
    add_shared_project_step_arguments,
)

# Types whose seasonal capability is already modeled elsewhere — variable
# generators through their capacity-factor profiles, hydro through its
# energy budgets (a seasonal capacity derate on top would double-count) —
# or whose seasonal ratings match nameplate (storage): excluded from the
# seasonal capacity derates by default
DEFAULT_SEASONAL_DERATE_EXCLUDED_OP_TYPES = (
    "gen_var,gen_var_must_take,gen_hydro,gen_hydro_must_take,stor"
)


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    parser.add_argument("-db", "--database", default="../../open_data_raw.db")
    add_shared_project_step_arguments(parser=parser)
    parser.add_argument(
        "-avl_csv",
        "--output_directory",
        default="../../csvs_open_data/project/availability",
    )
    parser.add_argument("-avl_id", "--project_availability_scenario_id", default=1)
    parser.add_argument(
        "-avl_name", "--project_availability_scenario_name", default="no_derates"
    )
    parser.add_argument(
        "-szn",
        "--seasonal_capacity_derates",
        default=False,
        action="store_true",
        help="Also write EIA-860's net summer/winter capacity ratings as "
        "monthly exogenous availability derates (fractions of nameplate "
        "capacity, capacity-weighted for aggregated projects): a "
        "per-project CSV in the 'exogenous_monthly' subdirectory of the "
        "output directory for every project whose seasonal rating differs "
        "from nameplate, with its exogenous_availability_monthly_scenario_id "
        "filled in the main availability CSV. Missing seasonal ratings "
        "fall back to nameplate. Variable-generator, hydro, and storage "
        "operational types are excluded (their seasonal capability is "
        "modeled elsewhere or matches nameplate).",
    )
    parser.add_argument(
        "-szn_s",
        "--summer_months",
        default="6,7,8,9",
        help="Comma-separated months (1-12) that get the net-summer-capacity "
        "derate when --seasonal_capacity_derates is used. Defaults to "
        "June-September, EIA's net-summer demonstration window.",
    )
    parser.add_argument(
        "-szn_w",
        "--winter_months",
        default="12,1,2",
        help="Comma-separated months (1-12) that get the net-winter-capacity "
        "derate when --seasonal_capacity_derates is used. Defaults to "
        "December-February, EIA's net-winter demonstration window.",
    )
    parser.add_argument(
        "-szn_x",
        "--seasonal_derate_excluded_operational_types",
        default=DEFAULT_SEASONAL_DERATE_EXCLUDED_OP_TYPES,
        help="Comma-separated GridPath operational types (as mapped in "
        "user_defined_eia_gridpath_key) that do NOT get seasonal capacity "
        "derates. Defaults to the variable-generator, hydro, and storage "
        "types, whose seasonal capability is already modeled through "
        "capacity-factor profiles and energy budgets or matches nameplate. "
        "Pass an empty value to derate every operational type.",
    )
    parser.add_argument(
        "-mnth_id",
        "--exogenous_availability_monthly_scenario_id",
        default=1,
        help="The subscenario ID for the per-project monthly derate CSVs "
        "written with --seasonal_capacity_derates.",
    )
    parser.add_argument(
        "-mnth_name",
        "--exogenous_availability_monthly_scenario_name",
        default="summer_winter_ratings",
        help="The subscenario name for the per-project monthly derate CSVs "
        "written with --seasonal_capacity_derates.",
    )

    parser.add_argument("-q", "--quiet", default=False, action="store_true")

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def parse_month_list(months_str, setting_name):
    """
    Parse a comma-separated month-number setting into a list of ints,
    raising on anything outside 1-12 or duplicated.
    """
    tokens = [t.strip() for t in str(months_str).split(",") if t.strip()]
    try:
        months = [int(t) for t in tokens]
    except ValueError:
        raise ValueError(
            f"{setting_name} must be comma-separated month numbers, got "
            f"'{months_str}'"
        )
    if any(m < 1 or m > 12 for m in months):
        raise ValueError(f"{setting_name} months must be between 1 and 12: {months}")
    if len(set(months)) != len(months):
        raise ValueError(f"{setting_name} months must not repeat: {months}")

    return months


def get_seasonal_months(summer_months_setting, winter_months_setting):
    """
    Parse and cross-validate the summer/winter month settings; returns
    (summer_months, winter_months) as lists of ints.
    """
    summer_months = parse_month_list(summer_months_setting, "summer_months")
    winter_months = parse_month_list(winter_months_setting, "winter_months")
    overlap = sorted(set(summer_months) & set(winter_months))
    if overlap:
        raise ValueError(
            f"summer_months and winter_months must not overlap; both "
            f"contain: {overlap}"
        )

    return summer_months, winter_months


def get_seasonal_derate_op_type_filter_string(excluded_operational_types):
    """
    The extra WHERE clause keeping *excluded_operational_types* (a
    comma-separated setting value) out of the seasonal derates; empty
    string when nothing is excluded. Tokens are restricted to identifier
    characters since they are interpolated into SQL.
    """
    op_types = [
        t.strip() for t in str(excluded_operational_types).split(",") if t.strip()
    ]
    for op_type in op_types:
        if not all(c.isalnum() or c == "_" for c in op_type):
            raise ValueError(
                f"seasonal_derate_excluded_operational_types entries must "
                f"be operational-type names (letters, digits, "
                f"underscores), got '{op_type}'"
            )
    if not op_types:
        return ""

    quoted_op_types = ", ".join(f"'{op_type}'" for op_type in op_types)
    return f"gridpath_operational_type NOT IN ({quoted_op_types})"


def warn_on_missing_seasonal_rating_data(conn):
    """
    Warn — loudly, regardless of any quiet setting — when seasonal
    capacity derates are requested but raw_data_eia860_generators has NO
    net summer/winter capacity values at all: every derate would fall
    back to nameplate and no monthly CSVs would be written. Real EIA data
    carries the ratings on nearly every unit (see the raw-table
    population), so an all-NULL column means the raw CSVs were loaded
    without those columns (the loader fills missing CSV columns with
    NULL) — re-run gridpath_pudl_to_gridpath_raw and reload. Returns
    (n_populated, n_rows).
    """
    n_populated, n_rows = conn.cursor().execute("""
            SELECT SUM(summer_capacity_mw IS NOT NULL
                       OR winter_capacity_mw IS NOT NULL),
                   COUNT(*)
            FROM raw_data_eia860_generators
            ;
            """).fetchone()
    n_populated = 0 if n_populated is None else n_populated

    if n_rows and not n_populated:
        print(
            "WARNING: seasonal capacity derates were requested, but "
            "raw_data_eia860_generators has NO summer_capacity_mw or "
            "winter_capacity_mw values at all, so every derate will fall "
            "back to nameplate and no monthly derate CSVs will be "
            "written. The raw CSVs were likely loaded without those "
            "columns — re-run gridpath_pudl_to_gridpath_raw and reload "
            "the raw data."
        )

    return n_populated, n_rows


def get_seasonal_derates(conn, project_name_str, derate_relation_sql):
    """
    Per-project summer and winter capacity derates: net seasonal capacity
    over nameplate, capacity-weighted across each project's units, with
    missing seasonal ratings falling back to nameplate (a unit without a
    rating contributes at nameplate, not zero). Returns a dataframe with
    columns project, summer_derate, winter_derate.
    """
    sql = f"""
    SELECT {project_name_str} AS project,
    SUM(capacity_mw) AS capacity_mw,
    SUM(COALESCE(summer_capacity_mw, capacity_mw)) AS summer_capacity_mw,
    SUM(COALESCE(winter_capacity_mw, capacity_mw)) AS winter_capacity_mw
    {derate_relation_sql}
    GROUP BY project
    ORDER BY project
    """
    df = pd.read_sql(sql, conn)

    # A project with no (or zero) nameplate capacity gets no derate
    for season in ["summer", "winter"]:
        df[f"{season}_derate"] = (
            (df[f"{season}_capacity_mw"] / df["capacity_mw"])
            .where(df["capacity_mw"] > 0)
            .fillna(1.0)
            .round(6)
        )

    return df[["project", "summer_derate", "winter_derate"]]


def write_monthly_derate_csvs(
    derates_df,
    summer_months,
    winter_months,
    csv_location,
    subscenario_id,
    subscenario_name,
):
    """
    Write a <project>-<id>-<name>.csv into the exogenous_monthly
    subdirectory for every project with a seasonal derate different from
    1, with month rows only for the seasons that differ (unlisted months
    default to 1 in the model). Returns the list of projects that got a
    file (their exogenous_availability_monthly_scenario_id must be set in
    the main availability CSV — the two must match exactly, or the CSV
    port fails on the dangling reference).
    """
    monthly_dir = os.path.join(csv_location, "exogenous_monthly")

    projects_with_derates = []
    for row in derates_df.itertuples(index=False):
        month_rows = sorted(
            [(m, row.summer_derate) for m in summer_months if row.summer_derate != 1]
            + [(m, row.winter_derate) for m in winter_months if row.winter_derate != 1]
        )
        if not month_rows:
            continue
        # The CSV port parses per-project filenames on the FIRST hyphen,
        # so a project name containing one can't carry a per-project CSV.
        # The disaggregated name expression already replaces hyphens, so
        # this can only come from a user-supplied custom-zone or
        # agg_project name — fail loudly rather than write a file the
        # port would silently misattribute
        if "-" in row.project:
            raise ValueError(
                f"Project name '{row.project}' contains a hyphen, which "
                "the per-project CSV filename convention "
                "(<project>-<id>-<name>.csv) cannot carry. Rename the "
                "custom zone or agg_project value without hyphens to use "
                "seasonal capacity derates."
            )
        os.makedirs(monthly_dir, exist_ok=True)
        pd.DataFrame(
            month_rows, columns=["month", "availability_derate_monthly"]
        ).to_csv(
            os.path.join(
                monthly_dir, f"{row.project}-{subscenario_id}-{subscenario_name}.csv"
            ),
            index=False,
        )
        projects_with_derates.append(row.project)

    return projects_with_derates


def get_project_availability(
    conn,
    project_name_str,
    fleet_relation_sql,
    csv_location,
    subscenario_id,
    subscenario_name,
    aggregate_projects=False,
    monthly_scenario_id=None,
    projects_with_monthly_derates=None,
):
    # NOTE: the aggregated branch used to omit the
    # exogenous_availability_monthly_scenario_id column (drift between the
    # two branches), which would have failed the exact-column-match CSV
    # port; both modes now write the full column set
    group_by_sql = "GROUP BY project" if aggregate_projects else ""
    sql = f"""
    SELECT {project_name_str} AS project,
    'exogenous' AS availability_type,
    NULL AS exogenous_availability_independent_scenario_id,
    NULL AS exogenous_availability_weather_scenario_id,
    NULL AS exogenous_availability_independent_bt_hrz_scenario_id,
    NULL AS exogenous_availability_weather_bt_hrz_scenario_id,
    NULL AS exogenous_availability_monthly_scenario_id,
    NULL AS endogenous_availability_scenario_id
    {fleet_relation_sql}
    {group_by_sql}
    """

    df = pd.read_sql(sql, conn)
    if projects_with_monthly_derates:
        mask = df["project"].isin(projects_with_monthly_derates)
        if mask.any():
            df.loc[mask, "exogenous_availability_monthly_scenario_id"] = int(
                monthly_scenario_id
            )
    df.to_csv(
        os.path.join(csv_location, f"{subscenario_id}_" f"{subscenario_name}.csv"),
        index=False,
    )


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)

    if not parsed_args.quiet:
        print("Creating project availability inputs")

    os.makedirs(parsed_args.output_directory, exist_ok=True)

    project_name_str = get_project_name_str_from_args(parsed_args)
    fleet_relation_sql = get_fleet_relation_sql_from_args(parsed_args)
    if parsed_args.seasonal_capacity_derates:
        # Validate the month settings before any database work
        summer_months, winter_months = get_seasonal_months(
            summer_months_setting=parsed_args.summer_months,
            winter_months_setting=parsed_args.winter_months,
        )
        derate_relation_sql = get_fleet_relation_sql_from_args(
            parsed_args,
            extra_where=get_seasonal_derate_op_type_filter_string(
                parsed_args.seasonal_derate_excluded_operational_types
            ),
        )

    conn = connect_and_check_scope(parsed_args)
    warn_on_fleet_data_gaps(conn=conn, parsed_args=parsed_args)

    projects_with_monthly_derates = None
    if parsed_args.seasonal_capacity_derates:
        warn_on_missing_seasonal_rating_data(conn=conn)
        derates_df = get_seasonal_derates(
            conn=conn,
            project_name_str=project_name_str,
            derate_relation_sql=derate_relation_sql,
        )
        projects_with_monthly_derates = write_monthly_derate_csvs(
            derates_df=derates_df,
            summer_months=summer_months,
            winter_months=winter_months,
            csv_location=parsed_args.output_directory,
            subscenario_id=parsed_args.exogenous_availability_monthly_scenario_id,
            subscenario_name=parsed_args.exogenous_availability_monthly_scenario_name,
        )

    get_project_availability(
        conn=conn,
        project_name_str=project_name_str,
        fleet_relation_sql=fleet_relation_sql,
        csv_location=parsed_args.output_directory,
        subscenario_id=parsed_args.project_availability_scenario_id,
        subscenario_name=parsed_args.project_availability_scenario_name,
        aggregate_projects=parsed_args.project_aggregation != "none",
        monthly_scenario_id=parsed_args.exogenous_availability_monthly_scenario_id,
        projects_with_monthly_derates=projects_with_monthly_derates,
    )

    conn.close()


if __name__ == "__main__":
    main()
