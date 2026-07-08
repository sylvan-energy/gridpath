# Copyright 2021 (c) Crown Copyright, GC.
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

""" """

import csv
import os.path
import pandas as pd
from pyomo.environ import (
    Param,
    Set,
    NonNegativeReals,
    Expression,
    value,
    PositiveReals,
    Reals,
)

from gridpath.auxiliary.auxiliary import (
    cursor_to_df,
    subset_init_by_param_value,
    subset_init_by_set_membership,
)
from gridpath.auxiliary.db_interface import (
    update_prj_zone_column,
    determine_table_subset_by_start_and_column,
    import_csv,
    directories_to_db_values,
)
from gridpath.auxiliary.validations import write_validation_to_database, validate_idxs


def add_model_components(
    m,
    d,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    The following Pyomo model components are defined in this module:

    +-------------------------------------------------------------------------+
    | Sets                                                                    |
    +=========================================================================+
    | | :code:`CARBON_TAX_PRJS`                                               |
    | | *Within*: :code:`PROJECTS`                                            |
    |                                                                         |
    | Two set of carbonaceous projects we need to track for the carbon tax.   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`carbon_tax_zone`                                               |
    | | *Defined over*: :code:`CARBON_TAX_PRJS`                               |
    | | *Within*: :code:`CARBON_TAX_ZONES`                                    |
    |                                                                         |
    | This param describes the carbon tax zone for each carbon tax project.   |
    +-------------------------------------------------------------------------+
    | | :code:`carbon_tax_allowance`                                          |
    | | *Defined over*: :code:`CARBON_TAX_PRJS`, `FUEL_GROUPS`, `PERIODS`     |
    | | *Within*: :code:`NonNegativeReals`                                    |
    |                                                                         |
    | This param describes the carbon tax allowance for each carbon tax       |
    | project and fuel group.                                                 |
    +-------------------------------------------------------------------------+
    | | :code:`carbon_tax_allowance_average_heat_rate`                        |
    | | *Defined over*: :code:`CARBON_TAX_PRJS`, `PERIODS`                    |
    | | *Within*: :code:`PositiveReals`                                       |
    |                                                                         |
    | This param describes the average heat rate for each carbon tax          |
    | project used to calculate the carbon tax allowance.                     |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Sets                                                            |
    +=========================================================================+
    | | :code:`CARBON_TAX_PRJS_BY_CARBON_TAX_ZONE`                            |
    | | *Defined over*: :code:`CARBON_TAX_ZONES`                              |
    | | *Within*: :code:`CARBON_TAX_PRJS`                                     |
    |                                                                         |
    | Indexed set that describes the list of carbonaceous projects for each   |
    | carbon tax zone.                                                        |
    +-------------------------------------------------------------------------+
    | | :code:`CARBON_TAX_PRJ_OPR_TMPS`                                       |
    | | *Within*: :code:`PRJ_OPR_TMPS`                                        |
    |                                                                         |
    | Two-dimensional set that defines all project-timepoint combinations     |
    | when a carbon tax project can be operational.                           |
    +-------------------------------------------------------------------------+
    | | :code:`CARBON_TAX_PRJ_OPR_PRDS`                                       |
    | | *Within*: :code:`PRJ_OPR_PRDS`                                        |
    |                                                                         |
    | Two-dimensional set that defines all project-period combinations        |
    | when a carbon tax project can be operational.                           |
    +-------------------------------------------------------------------------+
    | | :code:`CARBON_TAX_PRJ_FUEL_GROUP_OPR_TMPS`                            |
    |                                                                         |
    | Two-dimensional set that defines all project-fuel_group-timepoint       |
    | combinations when a carbon tax project can be operational.              |
    +-------------------------------------------------------------------------+
    | | :code:`CARBON_TAX_PRJ_FUEL_GROUP_OPR_PRDS`                            |
    |                                                                         |
    | Two-dimensional set that defines all project-fuel_group-period          |
    | combinations when a carbon tax project can be operational.              |
    +-------------------------------------------------------------------------+

    """

    # Sets
    ###########################################################################

    m.CARBON_TAX_PRJS = Set(within=m.PROJECTS)

    m.CARBON_TAX_PRJ_OPR_TMPS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_TMPS",
            index=0,
            membership_set=mod.CARBON_TAX_PRJS,
        ),
    )

    m.CARBON_TAX_PRJ_FUEL_GROUP_OPR_TMPS = Set(
        dimen=3,
        initialize=lambda mod: sorted(
            list(
                set(
                    (g, fg, tmp)
                    for (g, tmp) in mod.CARBON_TAX_PRJ_OPR_TMPS
                    for _g, fg, f in mod.FUEL_PRJ_FUELS_FUEL_GROUP
                    if g == _g
                ),
            )
        ),
    )

    m.CARBON_TAX_PRJ_OPR_PRDS = Set(
        initialize=lambda mod: subset_init_by_set_membership(
            mod=mod,
            superset="PRJ_OPR_PRDS",
            index=0,
            membership_set=mod.CARBON_TAX_PRJS,
        ),
    )

    m.CARBON_TAX_PRJ_FUEL_GROUP_OPR_PRDS = Set(
        dimen=3,
        initialize=lambda mod: sorted(
            list(
                set(
                    (g, fg, p)
                    for (g, p) in mod.CARBON_TAX_PRJ_OPR_PRDS
                    for _g, fg, f in mod.FUEL_PRJ_FUELS_FUEL_GROUP
                    if g == _g
                ),
            )
        ),
    )

    # Input Params
    ###########################################################################

    m.carbon_tax_zone = Param(m.CARBON_TAX_PRJS, within=m.CARBON_TAX_ZONES)

    m.carbon_tax_allowance = Param(
        m.CARBON_TAX_PRJS, m.FUEL_GROUPS, m.PERIODS, within=Reals, default=0
    )

    m.carbon_tax_allowance_average_heat_rate = Param(
        m.CARBON_TAX_PRJS, m.PERIODS, within=PositiveReals
    )

    # Derived Sets
    ###########################################################################

    m.CARBON_TAX_PRJS_BY_CARBON_TAX_ZONE = Set(
        m.CARBON_TAX_ZONES,
        within=m.CARBON_TAX_PRJS,
        initialize=lambda mod, co2_z: subset_init_by_param_value(
            mod, "CARBON_TAX_PRJS", "carbon_tax_zone", co2_z
        ),
    )

    # Expressions
    ###########################################################################

    def carbon_tax_allowance_rule(mod, prj, fg, tmp):
        """
        Allowance from each project. Multiply by the timepoint duration,
        timepoint weight and power to get the total emissions allowance.
        """

        return (
            mod.carbon_tax_allowance[prj, fg, mod.period[tmp]]
            * mod.Opr_Fuel_Burn_by_Fuel_Group_MMBtu[prj, fg, tmp]
            / mod.carbon_tax_allowance_average_heat_rate[prj, mod.period[tmp]]
        )

    m.Project_Carbon_Tax_Allowance = Expression(
        m.CARBON_TAX_PRJ_FUEL_GROUP_OPR_TMPS, rule=carbon_tax_allowance_rule
    )


# Input-Output
###############################################################################


def load_model_data(
    m,
    d,
    data_portal,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """

    :param m:
    :param d:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """
    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "projects.tab",
        ),
        select=("project", "carbon_tax_zone"),
        param=(m.carbon_tax_zone,),
    )

    data_portal.data()["CARBON_TAX_PRJS"] = {
        None: list(data_portal.data()["carbon_tax_zone"].keys())
    }

    data_portal.load(
        filename=os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "project_carbon_tax_allowance.tab",
        ),
        select=("project", "fuel_group", "period", "carbon_tax_allowance_tco2_per_mwh"),
        param=m.carbon_tax_allowance,
    )

    # Average heat rate
    hr_curves_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "heat_rate_curves.tab",
    )
    periods_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "periods.tab",
    )
    carbon_tax_allowance_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "project_carbon_tax_allowance.tab",
    )

    if os.path.exists(hr_curves_file) and os.path.exists(carbon_tax_allowance_file):
        hr_df = pd.read_csv(hr_curves_file, sep="\t")
        projects = set(hr_df["project"].unique())

        input_col = "average_heat_rate_mmbtu_per_mwh"

        periods_df = pd.read_csv(periods_file, sep="\t")
        cta_df = pd.read_csv(carbon_tax_allowance_file, sep="\t")
        cta_df = cta_df[cta_df["project"].isin(projects)]

        periods = set(periods_df["period"])
        cta_projects = cta_df["project"].unique()

        average_heat_rate_curves_dict = {}

        for project in cta_projects:
            df_slice = hr_df[hr_df["project"] == project]
            slice_periods = set(df_slice["period"])

            if slice_periods == set([0]):
                p_iterable = [0]
            elif periods.issubset(slice_periods):
                p_iterable = periods
            else:
                raise ValueError("""{} for project '{}' isn't specified for all 
                    modelled periods. Set period to 0 if inputs are the 
                    same for each period or make sure all modelled periods 
                    are included.""".format(input_col, project))

            for period in p_iterable:
                df_slice_p = df_slice[df_slice["period"] == period]
                df_slice_p = df_slice_p.sort_values(by=["load_point_fraction"])
                average_heat_rate = df_slice_p[input_col].values[-1]

                # If period is 0, create same inputs for all periods
                if period == 0:
                    average_heat_rate_curves_dict.update(
                        {(project, p): average_heat_rate for p in periods}
                    )
                # If not, create inputs for just this period
                else:
                    average_heat_rate_curves_dict.update(
                        {(project, period): average_heat_rate}
                    )

        data_portal.data()[
            "carbon_tax_allowance_average_heat_rate"
        ] = average_heat_rate_curves_dict


# Database
###############################################################################


def get_inputs_from_database(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
):
    """
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    c1 = conn.cursor()
    project_zones = c1.execute(
        """SELECT project, carbon_tax_zone
        FROM
        -- Get projects from portfolio only
        (SELECT project
            FROM inputs_project_portfolios
            WHERE project_portfolio_scenario_id = {}
        ) as prj_tbl
        LEFT OUTER JOIN 
        -- Get carbon tax zones for those projects
        (SELECT project, carbon_tax_zone
            FROM inputs_project_carbon_tax_zones
            WHERE project_carbon_tax_zone_scenario_id = {}
        ) as prj_ct_zone_tbl
        USING (project)
        -- Filter out projects whose carbon tax zone is not one included in 
        -- our carbon_tax_zone_scenario_id
        WHERE carbon_tax_zone in (
                SELECT carbon_tax_zone
                    FROM inputs_geography_carbon_tax_zones
                    WHERE carbon_tax_zone_scenario_id = {}
        );
        """.format(
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.PROJECT_CARBON_TAX_ZONE_SCENARIO_ID,
            subscenarios.CARBON_TAX_ZONE_SCENARIO_ID,
        )
    )

    c2 = conn.cursor()
    project_carbon_tax_allowance = c2.execute(
        """SELECT project, period, fuel_group,
        carbon_tax_allowance_tco2_per_mwh
        FROM
        -- Get projects from portfolio only
        (SELECT project, fuel, fuel_group
            FROM inputs_project_portfolios
            INNER JOIN
                (SELECT project, project_fuel_scenario_id
                    FROM inputs_project_operational_chars
                    WHERE project_operational_chars_scenario_id = {}
                ) AS op_char
                USING(project)
            INNER JOIN
                inputs_project_fuels
                USING(project, project_fuel_scenario_id)
            INNER JOIN
                (SELECT fuel, fuel_group
                    FROM inputs_fuels
                    WHERE fuel_scenario_id = {}
                ) AS fuel_chars
                USING(fuel) 
            WHERE project_portfolio_scenario_id = {}
        ) as prj_fuels_tbl
        CROSS JOIN
            (SELECT period
            FROM inputs_temporal_periods
            WHERE temporal_scenario_id = {}) as relevant_periods 
        LEFT OUTER JOIN
        -- Get carbon tax allowance for those projects
            (SELECT project, period, fuel_group,
            carbon_tax_allowance_tco2_per_mwh
            FROM inputs_project_carbon_tax_allowance
            WHERE project_carbon_tax_allowance_scenario_id = {}) as prj_ct_allowance_tbl
        USING (project, fuel_group, period)
        WHERE project in (
                SELECT project
                    FROM inputs_project_carbon_tax_zones
                    WHERE project_carbon_tax_zone_scenario_id = {}
        );
        """.format(
            subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID,
            subscenarios.FUEL_SCENARIO_ID,
            subscenarios.PROJECT_PORTFOLIO_SCENARIO_ID,
            subscenarios.TEMPORAL_SCENARIO_ID,
            subscenarios.PROJECT_CARBON_TAX_ALLOWANCE_SCENARIO_ID,
            subscenarios.PROJECT_CARBON_TAX_ZONE_SCENARIO_ID,
        )
    )

    return project_zones, project_carbon_tax_allowance


def write_model_inputs(
    scenario_directory,
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
):
    """
    Get inputs from database and write out the model input
    projects.tab (to be precise, amend it) and project_carbon_tax_allowance.tab files.
    :param scenario_directory: string, the scenario directory
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    (
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
    ) = directories_to_db_values(
        weather_iteration, hydro_iteration, availability_iteration, subproblem, stage
    )

    project_zones, project_carbon_tax_allowance = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    # projects.tab
    # Make a dict for easy access
    prj_zone_dict = dict()
    for prj, zone in project_zones:
        prj_zone_dict[str(prj)] = "." if zone is None else str(zone)

    with open(
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
        "r",
    ) as projects_file_in:
        reader = csv.reader(projects_file_in, delimiter="\t", lineterminator="\n")

        new_rows = list()

        # Append column header
        header = next(reader)
        header.append("carbon_tax_zone")
        new_rows.append(header)

        # Append correct values
        for row in reader:
            # If project specified, check if BA specified or not
            if row[0] in list(prj_zone_dict.keys()):
                row.append(prj_zone_dict[row[0]])
                new_rows.append(row)
            # If project not specified, specify no BA
            else:
                row.append(".")
                new_rows.append(row)

    with open(
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
        "w",
        newline="",
    ) as projects_file_out:
        writer = csv.writer(projects_file_out, delimiter="\t", lineterminator="\n")
        writer.writerows(new_rows)

    # project_carbon_tax_allowance.tab
    ct_allowance_df = cursor_to_df(project_carbon_tax_allowance)
    if not ct_allowance_df.empty:
        ct_allowance_df = ct_allowance_df.fillna(".")
        fpath = os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "project_carbon_tax_allowance.tab",
        )
        ct_allowance_df.to_csv(fpath, index=False, sep="\t")


def process_results(db, c, scenario_id, subscenarios, quiet):
    """

    :param db:
    :param c:
    :param subscenarios:
    :param quiet:
    :return:
    """
    if not quiet:
        print("update carbon tax zones")

    tables_to_update = determine_table_subset_by_start_and_column(
        conn=db, tbl_start="results_project_", cols=["carbon_tax_zone"]
    )

    for tbl in tables_to_update:
        update_prj_zone_column(
            conn=db,
            scenario_id=scenario_id,
            subscenarios=subscenarios,
            subscenario="project_carbon_tax_zone_scenario_id",
            subsc_tbl="inputs_project_carbon_tax_zones",
            prj_tbl=tbl,
            col="carbon_tax_zone",
        )


def export_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    m,
    d,
):
    """

    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param m:
    :param d:
    :return:
    """
    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "project_carbon_tax_allowance.csv",
        ),
        "w",
        newline="",
    ) as carbon_tax_allowance_results_file:
        writer = csv.writer(carbon_tax_allowance_results_file)
        writer.writerow(
            [
                "project",
                "fuel_group",
                "timepoint",
                "period",
                "horizon",
                "timepoint_weight",
                "number_of_hours_in_timepoint",
                "carbon_tax_zone",
                "carbon_tax_allowance_tco2_per_mwh",
                "carbon_tax_allowance_average_heat_rate_mmbtu_per_mwh",
                "opr_fuel_burn_by_fuel_group_mmbtu",
                "carbon_tax_allowance_tons",
            ]
        )
        for p, fg, tmp in m.CARBON_TAX_PRJ_FUEL_GROUP_OPR_TMPS:
            writer.writerow(
                [
                    p,
                    fg,
                    tmp,
                    m.period[tmp],
                    m.horizon[tmp, m.balancing_type_project[p]],
                    m.tmp_weight[tmp],
                    m.hrs_in_tmp[tmp],
                    m.carbon_tax_zone[p],
                    m.carbon_tax_allowance[p, fg, m.period[tmp]],
                    m.carbon_tax_allowance_average_heat_rate[p, m.period[tmp]],
                    value(m.Opr_Fuel_Burn_by_Fuel_Group_MMBtu[p, fg, tmp]),
                    value(m.Project_Carbon_Tax_Allowance[p, fg, tmp]),
                ]
            )


def import_results_into_database(
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    c,
    db,
    results_directory,
    quiet,
):
    """
    :param scenario_id:
    :param c:
    :param db:
    :param results_directory:
    :param quiet:
    :return:
    """

    import_csv(
        conn=db,
        cursor=c,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        quiet=quiet,
        results_directory=results_directory,
        which_results="project_carbon_tax_allowance",
    )


# Validation
###############################################################################


def validate_inputs(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
):
    """
    Get inputs from database and validate the inputs
    :param subscenarios: SubScenarios object with all subscenario info
    :param subproblem:
    :param stage:
    :param conn: database connection
    :return:
    """

    project_zones, project_carbon_tax_allowance = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    # Convert input data into pandas DataFrame
    df = cursor_to_df(project_zones)
    zones_w_project = df["carbon_tax_zone"].unique()

    # Get the required carbon tax zones
    # TODO: make this into a function similar to get_projects()?
    #  could eventually centralize all these db query functions in one place
    c = conn.cursor()
    zones = c.execute("""SELECT carbon_tax_zone FROM inputs_geography_carbon_tax_zones
        WHERE carbon_tax_zone_scenario_id = {}
        """.format(subscenarios.CARBON_TAX_ZONE_SCENARIO_ID))
    zones = [z[0] for z in zones]  # convert to list

    # Check that each carbon tax zone has at least one project assigned to it
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_project_carbon_tax_zones",
        severity="High",
        errors=validate_idxs(
            actual_idxs=zones_w_project,
            req_idxs=zones,
            idx_label="carbon_tax_zone",
            msg="Each carbon tax zone needs at least 1 " "project assigned to it.",
        ),
    )

    # TODO: need validation that projects with carbon tax zones also have fuels
