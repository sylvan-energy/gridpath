# Copyright 2016-2025 Blue Marble Analytics LLC.
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

import csv
import warnings

import numpy as np
import os.path
import pandas as pd

from db.common_functions import spin_on_database_lock
from gridpath.auxiliary.validations import (
    get_projects,
    validate_idxs,
    write_validation_to_database,
)
from gridpath.project.common_functions import get_column_row_value

# The capacity columns of inputs_project_specified_capacity; a row with all
# of them NULL carries no capacity of any kind and is treated as if it were
# absent, i.e. the project is not operational in that period
SPEC_CAPACITY_COLUMNS = [
    "specified_capacity_mw",
    "specified_energy_mwh",
    "shaping_capacity_mw",
    "hyb_gen_specified_capacity_mw",
    "hyb_stor_specified_capacity_mw",
    "specified_stor_capacity_mwh",
    "fuel_production_capacity_fuelunitperhour",
    "fuel_release_capacity_fuelunitperhour",
    "fuel_storage_capacity_fuelunit",
]
SPEC_CAPACITY_PRESENT_SQL = "COALESCE({}) IS NOT NULL".format(
    ", ".join(SPEC_CAPACITY_COLUMNS)
)


def relevant_periods_by_project_vintage(
    future_trajectory_periods,
    period_start_year,
    period_end_year,
    vintage,
    lifetime_yrs,
    quiet=False,
):
    """
    :param future_trajectory_periods: the study periods in a list
    :param period_start_year: dictionary of the start year of a period
        by period
    :param period_end_year: dictionary of the end year of a period
        by period
    :param vintage: the project vintage
    :param lifetime_yrs: the project-vintage lifetime
    :param quiet: silence warnings if set to True
    :return: the operational or financial periods given the study periods and
        the project vintage and lifetime

    Note that this function relies on the correct future_trajectory_periods being
    passed to it. We need to pass all the periods that are "connected to"
    (on the same future trajectory) as the project vintage.

    Given the list of periods on the same future trajectory as the project's
    vintage and the project's lifetime (either the operational lifetime or the
    financial lifetime), this function returns the list of periods in which a
    project with this vintage and lifetime will be operational (based on the
    operational lifetime) or incurring an annualized capital cost (based on
    the financial lifetime) respectively. When a project is operational,
    it incurs annual fixed O&M costs.

    Two conditions must be met for a period to be operational / incurring costs for a
    project of a certain vintage:
    1) project vintage (i.e. first operational year) must be before or equal
    to the start year of the period
    2) project last lifetime year must be **after** the period end year.

    The end year of the period is exclusive (i.e. the last day of a period
    with end year 2030 is actually 2020-12-29). With the current
    formulation, a project with a 10 year lifetime of the 2020 vintage is
    assumed to be operational / incurring costs on 2020-01-01 and remain operational
    / incurring costs through 2029-12-31 (vintage 2020, last lifetime year 2030
    exclusive). It will be operational / incurring costs in a period with a start
    year of 2020 and end year of 2030.

    If either the vintage or the last lifetime year is within the period,
    the period is assumed to not be operational / incurring capital costs for the
    project.
    """
    # No relevant periods if vintage does not belong to the vintage's future
    # trajectory periods;
    # this shouldn't happen.
    relevant_periods = list()
    if vintage not in future_trajectory_periods:
        if not quiet:
            warnings.warn(
                f"Vintage {vintage} is not in the future trajectory periods. "
                f"This shouldn't happen."
            )
    else:
        first_lifetime_year = period_start_year[vintage]
        last_lifetime_year = period_start_year[vintage] + lifetime_yrs
        for p in future_trajectory_periods:
            if (
                first_lifetime_year <= period_start_year[p]
                and last_lifetime_year >= period_end_year[p]
            ):
                relevant_periods.append(p)

    return relevant_periods


def project_relevant_periods(
    project_vintages_set, relevant_periods_by_project_vintage_set
):
    """
    :param project_vintages_set: the possible project-vintages when capacity
        can be built
    :param relevant_periods_by_project_vintage_set: the project operational
        periods based on vintage
    :return: all study periods when the project could be operational

    Get the periods in which each project COULD be operational (or incurring
    capital costs) given all project-vintages and relevant periods by
    project-vintage (the lifetime is allowed to differ by vintage).
    """
    return sorted(
        list(
            set(
                (g, p)
                for (g, v) in project_vintages_set
                for p in relevant_periods_by_project_vintage_set[g, v]
            )
        )
    )


def project_vintages_relevant_in_period(
    project_vintage_set, relevant_periods_by_project_vintage_set, period
):
    """
    :param project_vintage_set: possible project-vintages when capacity
        could be built
    :param relevant_periods_by_project_vintage_set: the periods when
        project capacity of a particular vintage could be operational (or incurring
        capital costs)
    :param period: the period we're in
    :return: all vintages that could be operational (or incurring capital costs) in a
        period

    Get the project vintages that COULD be operational (or incurring capital costs) in
    each period.
    """
    project_vintages = list()
    for prj, v in project_vintage_set:
        if period in relevant_periods_by_project_vintage_set[prj, v]:
            project_vintages.append((prj, v))

    return project_vintages


# Specified projects common functions
def spec_get_inputs_from_database(conn, subscenarios, subproblem, capacity_type):
    """
    Get the various capacity and fixed cost parameters for projects with
    "specified" capacity types.
    """
    db_subproblem = subproblem if subproblem != "" else 1

    c = conn.cursor()
    spec_project_params = c.execute(f"""
        SELECT project,
        period,
        specified_capacity_mw,
        specified_energy_mwh,
        shaping_capacity_mw,
        hyb_gen_specified_capacity_mw,
        hyb_stor_specified_capacity_mw,
        specified_stor_capacity_mwh,
        fuel_production_capacity_fuelunitperhour,
        fuel_release_capacity_fuelunitperhour,
        fuel_storage_capacity_fuelunit,
        fixed_cost_per_mw_yr,
        fixed_cost_per_energy_mwh_yr,
        fixed_cost_per_shaping_mw_yr,
        hyb_gen_fixed_cost_per_mw_yr,
        hyb_stor_fixed_cost_per_mw_yr,
        fixed_cost_per_stor_mwh_yr,
        fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr,
        fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr,
        fuel_storage_capacity_fixed_cost_per_fuelunit_yr
        FROM inputs_project_portfolios
        CROSS JOIN
        (SELECT period
        FROM inputs_temporal_periods
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}) as relevant_periods
        INNER JOIN
        (SELECT project, period,
        specified_capacity_mw,
        specified_energy_mwh,
        shaping_capacity_mw,
        hyb_gen_specified_capacity_mw,
        hyb_stor_specified_capacity_mw,
        specified_stor_capacity_mwh,
        fuel_production_capacity_fuelunitperhour,
        fuel_release_capacity_fuelunitperhour,
        fuel_storage_capacity_fuelunit
        FROM inputs_project_specified_capacity
        WHERE project_specified_capacity_scenario_id = {subscenarios.PROJECT_SPECIFIED_CAPACITY_SCENARIO_ID}
        AND {SPEC_CAPACITY_PRESENT_SQL}) as capacity
        USING (project, period)
        LEFT JOIN -- operational periods are based on capacity; fixed costs are optional
        (SELECT project, period,
        fixed_cost_per_mw_yr, fixed_cost_per_energy_mwh_yr, 
        fixed_cost_per_shaping_mw_yr,
        hyb_gen_fixed_cost_per_mw_yr,
        hyb_stor_fixed_cost_per_mw_yr,
        fixed_cost_per_stor_mwh_yr,
        fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr,
        fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr,
        fuel_storage_capacity_fixed_cost_per_fuelunit_yr
        FROM inputs_project_specified_fixed_cost
        WHERE project_specified_fixed_cost_scenario_id = {subscenarios.PROJECT_SPECIFIED_FIXED_COST_SCENARIO_ID}) as fixed_om
        USING (project, period)
        WHERE project_portfolio_scenario_id = {subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID}
        AND capacity_type = '{capacity_type}'
        AND period in (
                  SELECT DISTINCT period
                  FROM inputs_temporal
                  WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
                  AND subproblem_id = {db_subproblem}
               )
        ;""")

    return spec_project_params


def validate_spec_capacity_coverage(
    conn,
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    gridpath_module,
    capacity_type,
):
    """
    Check the period coverage of the specified-capacity rows of the
    portfolio's projects of this capacity type and write the findings to the
    validation table.

    A project is operational in exactly the periods for which it has a row in
    ``inputs_project_specified_capacity`` with at least one capacity column
    filled in (a row with every capacity column NULL counts as absent).
    Leaving periods out is the intended way to model a project that retires,
    or comes online, within the study horizon, and a project may have no row
    at all in the periods of a given subproblem, so that one
    specified-capacity subscenario can serve runs over different horizons.
    Only a project with no row in any period of the subscenario is an error
    (High severity), as that is most likely a naming mismatch between the
    portfolio and the capacity inputs.
    Two Low-severity notes flag the cases worth a second look: a project
    with capacity in none of this subproblem's periods, which will not be
    in the model at all, and a project whose coverage of this subproblem's
    periods has a gap between two covered periods.

    :param conn: database connection
    :param scenario_id:
    :param subscenarios: SubScenarios object with all subscenario info
    :param weather_iteration:
    :param hydro_iteration:
    :param availability_iteration:
    :param subproblem:
    :param stage:
    :param gridpath_module: the name of the module running the validation
    :param capacity_type: the capacity type whose projects to check
    :return:
    """
    db_subproblem = subproblem if subproblem != "" else 1

    projects = get_projects(
        conn, scenario_id, subscenarios, "capacity_type", capacity_type
    )

    c = conn.cursor()
    # Rows with no capacity of any kind count as absent, as in
    # spec_get_inputs_from_database
    capacity_periods_sql = f"""
        SELECT project, period
        FROM inputs_project_specified_capacity
        WHERE project_specified_capacity_scenario_id =
        {subscenarios.PROJECT_SPECIFIED_CAPACITY_SCENARIO_ID}
        AND {SPEC_CAPACITY_PRESENT_SQL}
        ;"""
    periods_by_project = dict()
    for project, period in c.execute(capacity_periods_sql).fetchall():
        periods_by_project.setdefault(project, set()).add(period)

    # The same period scoping as spec_get_inputs_from_database
    subproblem_periods_sql = f"""
        SELECT DISTINCT period
        FROM inputs_temporal
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND subproblem_id = {db_subproblem}
        ORDER BY period
        ;"""
    subproblem_periods = [
        period for (period,) in c.execute(subproblem_periods_sql).fetchall()
    ]

    def write(severity, errors):
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=gridpath_module,
            db_table="inputs_project_specified_capacity",
            severity=severity,
            errors=errors,
        )

    # A project with no capacity row in any period is most likely a naming
    # mismatch between the portfolio and the capacity inputs
    write(
        severity="High",
        errors=validate_idxs(
            actual_idxs=list(periods_by_project.keys()),
            req_idxs=projects,
            idx_label="project",
            msg="Expected specified capacity in at least one period.",
        ),
    )

    not_operational = list()
    gaps = dict()
    for project in sorted(projects):
        if project not in periods_by_project:
            continue
        covered = [p for p in subproblem_periods if p in periods_by_project[project]]
        if not covered:
            not_operational.append(project)
            continue
        uncovered_between = [
            p
            for p in subproblem_periods
            if covered[0] < p < covered[-1] and p not in periods_by_project[project]
        ]
        if uncovered_between:
            gaps[project] = uncovered_between

    errors = list()
    if not_operational:
        errors.append(
            "No specified capacity in any period of this subproblem for "
            "project: {}. These projects will not be operational (i.e., "
            "they will not be in the model) in this subproblem.".format(not_operational)
        )
    if gaps:
        errors.append(
            "Non-contiguous specified capacity for project: {}. The periods "
            "listed have no capacity row but fall between periods that do; "
            "the project will not be operational in them.".format(gaps)
        )
    write(severity="Low", errors=errors)


def spec_write_tab_file(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    spec_project_params,
):
    spec_params_filepath = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "spec_capacity_period_params.tab",
    )
    # If spec_capacity_period_params.tab file already exists, append
    # rows to it
    if os.path.isfile(spec_params_filepath):
        with open(spec_params_filepath, "a") as f:
            writer_a = csv.writer(f, delimiter="\t", lineterminator="\n")
            write_from_query(spec_project_params=spec_project_params, writer=writer_a)
    # If spec_capacity_period_params.tab file does not exist,
    # write header first, then add input data
    else:
        with open(spec_params_filepath, "w", newline="") as f:
            writer_w = csv.writer(f, delimiter="\t", lineterminator="\n")
            # Write header
            writer_w.writerow(
                [
                    "project",
                    "period",
                    "specified_capacity_mw",
                    "specified_energy_mwh",
                    "shaping_capacity_mw",
                    "hyb_gen_specified_capacity_mw",
                    "hyb_stor_specified_capacity_mw",
                    "specified_stor_capacity_mwh",
                    "fuel_production_capacity_fuelunitperhour",
                    "fuel_release_capacity_fuelunitperhour",
                    "fuel_storage_capacity_fuelunit",
                    "fixed_cost_per_mw_yr",
                    "fixed_cost_per_energy_mwh_yr",
                    "fixed_cost_per_shaping_mw_yr",
                    "hyb_gen_fixed_cost_per_mw_yr",
                    "hyb_stor_fixed_cost_per_mw_yr",
                    "fixed_cost_per_stor_mwh_yr",
                    "fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr",
                    "fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr",
                    "fuel_storage_capacity_fixed_cost_per_fuelunit_yr",
                ]
            )

            # Write input data
            write_from_query(spec_project_params=spec_project_params, writer=writer_w)


def write_from_query(spec_project_params, writer):
    """
    Helper function for writing the spec project param inputs to avoid
    redundant code in spec_write_tab_file().
    """
    for row in spec_project_params:
        [
            project,
            period,
            specified_capacity_mw,
            specified_energy_mwh,
            shaping_capacity_mw,
            hyb_gen_specified_capacity_mw,
            hyb_stor_specified_capacity_mw,
            specified_stor_capacity_mwh,
            fuel_prod_cap,
            fuel_rel_cap,
            fuel_stor_cap,
            fixed_cost_per_mw_yr,
            fixed_cost_per_energy_mwh_yr,
            fixed_cost_per_shaping_mw_yr,
            hyb_gen_fixed_cost_per_mw_yr,
            hyb_stor_fixed_cost_per_mw_yr,
            fixed_cost_per_stor_mwh_yr,
            fuel_prod_fom,
            fuel_rel_fom,
            fuel_stor_fom,
        ] = row
        writer.writerow(
            [
                project,
                period,
                specified_capacity_mw,
                specified_energy_mwh,
                shaping_capacity_mw,
                hyb_gen_specified_capacity_mw,
                hyb_stor_specified_capacity_mw,
                specified_stor_capacity_mwh,
                fuel_prod_cap,
                fuel_rel_cap,
                fuel_stor_cap,
                fixed_cost_per_mw_yr,
                fixed_cost_per_energy_mwh_yr,
                fixed_cost_per_shaping_mw_yr,
                hyb_gen_fixed_cost_per_mw_yr,
                hyb_stor_fixed_cost_per_mw_yr,
                fixed_cost_per_stor_mwh_yr,
                fuel_prod_fom,
                fuel_rel_fom,
                fuel_stor_fom,
            ]
        )


def spec_determine_inputs(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    capacity_type,
):
    # Determine the relevant projects
    project_list = list()

    df = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "projects.tab",
        ),
        sep="\t",
        usecols=["project", "capacity_type"],
    )

    for row in zip(df["project"], df["capacity_type"]):
        if row[1] == capacity_type:
            project_list.append(row[0])

    # Determine the operational periods & params for each project/period
    project_period_list = list()
    spec_capacity_mw_dict = dict()
    specified_energy_mwh_dict = dict()
    shaping_capacity_mw_dict = dict()
    hyb_gen_spec_capacity_mw_dict = dict()
    hyb_stor_spec_capacity_mw_dict = dict()
    spec_capacity_mwh_dict = dict()
    spec_fuel_prod_cap_dict = dict()
    spec_fuel_rel_cap_dict = dict()
    spec_fuel_stor_cap_dict = dict()
    spec_fixed_cost_per_mw_yr_dict = dict()
    fixed_cost_per_energy_mwh_yr_dict = dict()
    fixed_cost_per_shaping_mw_yr_dict = dict()
    hyb_gen_spec_fixed_cost_per_mw_yr_dict = dict()
    hyb_stor_spec_fixed_cost_per_mw_yr_dict = dict()
    spec_fixed_cost_per_stor_mwh_yr_dict = dict()
    spec_fuel_prod_fixed_cost_dict = dict()
    spec_fuel_rel_fixed_cost_dict = dict()
    spec_fuel_stor_fixed_cost_dict = dict()

    df = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "spec_capacity_period_params.tab",
        ),
        sep="\t",
    )

    for row in zip(
        df["project"],
        df["period"],
        df["specified_capacity_mw"],
        df["specified_energy_mwh"],
        df["shaping_capacity_mw"],
        df["hyb_gen_specified_capacity_mw"],
        df["hyb_stor_specified_capacity_mw"],
        df["specified_stor_capacity_mwh"],
        df["fuel_production_capacity_fuelunitperhour"],
        df["fuel_release_capacity_fuelunitperhour"],
        df["fuel_storage_capacity_fuelunit"],
        df["fixed_cost_per_mw_yr"],
        df["fixed_cost_per_energy_mwh_yr"],
        df["fixed_cost_per_shaping_mw_yr"],
        df["hyb_gen_fixed_cost_per_mw_yr"],
        df["hyb_stor_fixed_cost_per_mw_yr"],
        df["fixed_cost_per_stor_mwh_yr"],
        df["fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr"],
        df["fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr"],
        df["fuel_storage_capacity_fixed_cost_per_fuelunit_yr"],
    ):
        if row[0] in project_list:
            project_period_list.append((row[0], row[1]))
            spec_capacity_mw_dict[(row[0], row[1])] = row[2]
            specified_energy_mwh_dict[(row[0], row[1])] = row[3]
            shaping_capacity_mw_dict[(row[0], row[1])] = row[4]
            hyb_gen_spec_capacity_mw_dict[(row[0], row[1])] = row[5]
            hyb_stor_spec_capacity_mw_dict[(row[0], row[1])] = row[6]
            spec_capacity_mwh_dict[(row[0], row[1])] = row[7]
            spec_fuel_prod_cap_dict[(row[0], row[1])] = row[8]
            spec_fuel_rel_cap_dict[(row[0], row[1])] = row[9]
            spec_fuel_stor_cap_dict[(row[0], row[1])] = row[10]
            spec_fixed_cost_per_mw_yr_dict[(row[0], row[1])] = row[11]
            fixed_cost_per_energy_mwh_yr_dict[(row[0], row[1])] = row[12]
            fixed_cost_per_shaping_mw_yr_dict[(row[0], row[1])] = row[13]
            hyb_gen_spec_fixed_cost_per_mw_yr_dict[(row[0], row[1])] = row[14]
            hyb_stor_spec_fixed_cost_per_mw_yr_dict[(row[0], row[1])] = row[15]
            spec_fixed_cost_per_stor_mwh_yr_dict[(row[0], row[1])] = row[16]
            spec_fuel_prod_fixed_cost_dict[(row[0], row[1])] = row[17]
            spec_fuel_rel_fixed_cost_dict[(row[0], row[1])] = row[18]
            spec_fuel_stor_fixed_cost_dict[(row[0], row[1])] = row[19]

    # A project with no rows here (none in the subproblem's periods, or only
    # rows with every capacity column blank) is simply not operational in
    # this subproblem, e.g. it retires before, or comes online after, the
    # subproblem's periods; validate_spec_capacity_coverage reports it

    # For fixed costs, remove the NAs (set to "."); these default to zero in
    # the model formulation
    def remove_nan_values_from_dict(d):
        return {k: v for k, v in d.items() if not np.isnan(v)}

    main_dict = dict()
    main_dict["specified_capacity_mw"] = spec_capacity_mw_dict
    main_dict["specified_energy_mwh"] = specified_energy_mwh_dict
    main_dict["shaping_capacity_mw"] = remove_nan_values_from_dict(
        shaping_capacity_mw_dict
    )
    main_dict["hyb_gen_specified_capacity_mw"] = hyb_gen_spec_capacity_mw_dict
    main_dict["hyb_stor_specified_capacity_mw"] = hyb_stor_spec_capacity_mw_dict
    main_dict["specified_stor_capacity_mwh"] = spec_capacity_mwh_dict
    main_dict["fuel_production_capacity_fuelunitperhour"] = spec_fuel_prod_cap_dict
    main_dict["fuel_release_capacity_fuelunitperhour"] = spec_fuel_rel_cap_dict
    main_dict["fuel_storage_capacity_fuelunit"] = spec_fuel_stor_cap_dict

    main_dict["fixed_cost_per_mw_yr"] = remove_nan_values_from_dict(
        spec_fixed_cost_per_mw_yr_dict
    )
    main_dict["fixed_cost_per_energy_mwh_yr"] = remove_nan_values_from_dict(
        fixed_cost_per_energy_mwh_yr_dict
    )
    main_dict["fixed_cost_per_shaping_mw_yr"] = remove_nan_values_from_dict(
        fixed_cost_per_shaping_mw_yr_dict
    )
    main_dict["hyb_gen_fixed_cost_per_mw_yr"] = remove_nan_values_from_dict(
        hyb_gen_spec_fixed_cost_per_mw_yr_dict
    )
    main_dict["hyb_stor_fixed_cost_per_mw_yr"] = remove_nan_values_from_dict(
        hyb_stor_spec_fixed_cost_per_mw_yr_dict
    )
    main_dict["fixed_cost_per_stor_mwh_yr"] = remove_nan_values_from_dict(
        spec_fixed_cost_per_stor_mwh_yr_dict
    )
    main_dict["fuel_production_capacity_fixed_cost_per_fuelunitperhour_yr"] = (
        remove_nan_values_from_dict(spec_fuel_prod_fixed_cost_dict)
    )

    main_dict["fuel_release_capacity_fixed_cost_per_fuelunitperhour_yr"] = (
        remove_nan_values_from_dict(spec_fuel_rel_fixed_cost_dict)
    )

    main_dict["fuel_storage_capacity_fixed_cost_per_fuelunit_yr"] = (
        remove_nan_values_from_dict(spec_fuel_stor_fixed_cost_dict)
    )

    return project_period_list, main_dict


def read_results_file_generic(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    capacity_type,
):
    """
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param capacity_type:
    :return:
    """

    # Get the results CSV as dataframe
    df = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "project_period.csv",
        )
    )

    # Filter by capacity type and aggregate by technology
    capacity_results_agg_df = (
        df.loc[df["capacity_type"] == capacity_type]
        .groupby(by=["load_zone", "technology", "period"], as_index=True)
        .sum(numeric_only=True)
    )

    return capacity_results_agg_df


def write_summary_results_generic(
    results_df, columns, summary_results_file, title, empty_title
):
    # Rename column header
    results_df.columns = columns

    with open(summary_results_file, "a") as outfile:
        outfile.write(f"\n--> {title} <--\n")
        if results_df.empty:
            outfile.write(f"{empty_title}\n")
        else:
            results_df.to_string(outfile, float_format="{:,.2f}".format)
            outfile.write("\n")


def get_units(scenario_directory):
    units_df = pd.read_csv(
        os.path.join(scenario_directory, "units.csv"), index_col="metric"
    )
    power_unit = units_df.loc["power", "unit"]
    energy_unit = units_df.loc["energy", "unit"]
    fuel_unit = units_df.loc["fuel_energy", "unit"]

    return power_unit, energy_unit, fuel_unit
