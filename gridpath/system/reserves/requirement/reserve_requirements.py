# Copyright 2016-2023 Blue Marble Analytics LLC.
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
import os.path
from pyomo.environ import (
    Param,
    Set,
    NonNegativeReals,
    PercentFraction,
    Reals,
    Expression,
)

from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import write_validation_to_database
from gridpath.system.load_balance.aggregate_load_modifier_power import (
    component_modified_load_mw,
)


def load_component_set_name(reserve_zone_load_zone_set):
    """
    :return: the name of the set of (reserve zone, load zone, load component)
        whose load is included in the reserve percentage requirement
    """
    return f"{reserve_zone_load_zone_set}_LOAD_CMPNTS"


def generic_add_model_components(
    m,
    d,
    reserve_zone_set,
    reserve_requirement_tmp_param,
    reserve_requirement_percent_param,
    reserve_zone_load_zone_set,
    ba_prj_req_contribution_set,
    prj_power_param,
    prj_capacity_param,
    reserve_requirement_expression,
):
    """
    :param m:
    :param d:
    :param reserve_zone_set:
    :param reserve_requirement_tmp_param:
    :param reserve_requirement_percent_param:
    :param reserve_zone_load_zone_set:
    :param ba_prj_req_contribution_set:
    :param prj_power_param:
    :param prj_capacity_param:
    :param reserve_requirement_expression:
    :return:

    Generic treatment of reserves. This function creates model components
    related to a particular reserve requirement, including
    1) the reserve requirement by zone and timepoint, if any
    2) the reserve requirement as a percent of load and map for which load
    to consider: a load zone's whole load (net of load modifiers) or one of
    its load components' load (its static load adjusted for distribution
    losses, net of the load_component_modifier and load_component_shift load
    modifiers linked to it)
    3) the contributions to the reserve requirement from projects: there are two
    types of these contributions, those based on the power output in the timepoint
    and those based on the project capacity.
    """

    # Magnitude of the requirement by reserve zone and timepoint
    # If not specified for a reserve zone - timepoint combination,
    # will default to 0
    setattr(
        m,
        reserve_requirement_tmp_param,
        Param(getattr(m, reserve_zone_set), m.TMPS, within=NonNegativeReals, default=0),
    )

    # Requirement as percentage of load
    setattr(
        m,
        reserve_requirement_percent_param,
        Param(getattr(m, reserve_zone_set), within=PercentFraction, default=0),
    )

    # Load zones included in the reserve percentage requirement
    setattr(
        m,
        reserve_zone_load_zone_set,
        Set(dimen=2, within=getattr(m, reserve_zone_set) * m.LOAD_ZONES),
    )

    # Load zone-load components whose load is included in the reserve
    # percentage requirement
    setattr(
        m,
        load_component_set_name(reserve_zone_load_zone_set),
        Set(
            dimen=3,
            within=getattr(m, reserve_zone_set) * m.LOAD_ZONE_LOAD_CMPNTS_ALL,
        ),
    )

    # Projects contributing to BA requirement based on power output in the timepoint
    # and on capacity in the period
    setattr(
        m,
        ba_prj_req_contribution_set,
        Set(dimen=2, within=getattr(m, reserve_zone_set) * m.PROJECTS),
    )

    setattr(
        m,
        prj_power_param,
        Param(getattr(m, ba_prj_req_contribution_set), within=Reals, default=0),
    )

    setattr(
        m,
        prj_capacity_param,
        Param(getattr(m, ba_prj_req_contribution_set), within=Reals, default=0),
    )

    def reserve_requirement_rule(mod, reserve_zone, tmp):
        # If we have a map of reserve zones to load zones, apply the percentage
        # target; if no map provided, the percentage_target is 0
        if getattr(mod, reserve_zone_load_zone_set):
            percentage_target = sum(
                getattr(mod, reserve_requirement_percent_param)[reserve_zone]
                * mod.LZ_Modified_Load_in_Tmp[lz, tmp]
                for (_reserve_zone, lz) in getattr(mod, reserve_zone_load_zone_set)
                if _reserve_zone == reserve_zone
            )
        else:
            percentage_target = 0

        # Load components' load, net of the load modifiers linked to them
        if getattr(mod, load_component_set_name(reserve_zone_load_zone_set)):
            percentage_target += sum(
                getattr(mod, reserve_requirement_percent_param)[reserve_zone]
                * component_modified_load_mw(mod, lz, tmp, cmp)
                for (_reserve_zone, lz, cmp) in getattr(
                    mod, load_component_set_name(reserve_zone_load_zone_set)
                )
                if _reserve_zone == reserve_zone
            )

        # Project contributions, if any projects in the respective set
        if getattr(mod, ba_prj_req_contribution_set):
            # Project contributions to requirement based on power output
            prj_pwr_contribution = sum(
                getattr(mod, prj_power_param)[reserve_zone, prj]
                * mod.Bulk_Power_Provision_MW[prj, tmp]
                for (_reserve_zone, prj) in getattr(mod, ba_prj_req_contribution_set)
                if _reserve_zone == reserve_zone
                if (prj, tmp) in mod.PRJ_OPR_TMPS
            )

            # Project contributions to requirement based on (available) capacity
            # We are not holding the extra reserves when projects are unavailable
            prj_cap_contribution = sum(
                getattr(mod, prj_capacity_param)[reserve_zone, prj]
                * mod.Capacity_MW[prj, mod.period[tmp]]
                * mod.Availability_Derate[prj, tmp]
                for (_reserve_zone, prj) in getattr(mod, ba_prj_req_contribution_set)
                if _reserve_zone == reserve_zone
                if (prj, tmp) in mod.PRJ_OPR_TMPS
            )
        else:
            prj_pwr_contribution = 0
            prj_cap_contribution = 0

        return (
            getattr(mod, reserve_requirement_tmp_param)[reserve_zone, tmp]
            + percentage_target
            + prj_pwr_contribution
            + prj_cap_contribution
        )

    setattr(
        m,
        reserve_requirement_expression,
        Expression(
            getattr(m, reserve_zone_set) * m.TMPS, rule=reserve_requirement_rule
        ),
    )


def generic_load_model_data(
    m,
    d,
    data_portal,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    reserve_requirement_param,
    reserve_zone_load_zone_set,
    reserve_requirement_percent_param,
    ba_prj_req_contribution_set,
    prj_power_param,
    prj_capacity_param,
    reserve_type,
):
    """

    :param m:
    :param d:
    :param data_portal:
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param reserve_requirement_param:
    :param reserve_zone_load_zone_set:
    :param reserve_requirement_percent_param
    :param ba_prj_req_contribution_set
    :param prj_power_param
    :param prj_capacity_param
    :param reserve_type:
    :return:
    """
    input_dir = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
    )

    # Load by-tmp requriement if input file was written
    by_tmp_req_filename = os.path.join(
        input_dir, "{}_tmp_requirement.tab".format(reserve_type)
    )
    if os.path.exists(by_tmp_req_filename):
        tmp_params_to_load = (
            (
                getattr(m, reserve_requirement_param),
                m.frequency_response_requirement_partial_mw,
            )
            if reserve_type == "frequency_response"
            else getattr(m, reserve_requirement_param)
        )
        data_portal.load(filename=by_tmp_req_filename, param=tmp_params_to_load)

    # If we have a reserve zone to load zone (or load zone-load component) map
    # input file, load it and the percent requirement; otherwise, initialize
    # the set as an empty list (the param defaults to 0)
    map_files_exist = False
    for set_name, map_filename in [
        (reserve_zone_load_zone_set, f"{reserve_type}_percent_map.tab"),
        (
            load_component_set_name(reserve_zone_load_zone_set),
            f"{reserve_type}_percent_load_component_map.tab",
        ),
    ]:
        map_filename = os.path.join(input_dir, map_filename)
        if os.path.exists(map_filename):
            map_files_exist = True
            data_portal.load(filename=map_filename, set=getattr(m, set_name))
        else:
            data_portal.data()[set_name] = {None: []}
    if map_files_exist:
        data_portal.load(
            filename=os.path.join(
                input_dir, "{}_percent_requirement.tab".format(reserve_type)
            ),
            param=getattr(m, reserve_requirement_percent_param),
        )

    # If we have a project contributions file, load it into the respective
    prj_contr_filename = os.path.join(
        input_dir, "{}_requirement_project_contributions.tab".format(reserve_type)
    )
    if os.path.exists(prj_contr_filename):
        data_portal.load(
            filename=prj_contr_filename,
            index=getattr(m, ba_prj_req_contribution_set),
            param=(getattr(m, prj_power_param), getattr(m, prj_capacity_param)),
        )
    else:
        data_portal.data()[ba_prj_req_contribution_set] = {None: []}


def generic_get_inputs_from_database(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    reserve_type,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
):
    """
    :param subscenarios:
    :param subproblem:
    :param stage:
    :param conn:
    :param reserve_type:
    :param reserve_type_ba_subscenario_id:
    :param reserve_type_req_subscenario_id:
    :return:
    """

    c = conn.cursor()

    partial_freq_resp_extra_column = (
        ", frequency_response_partial_mw"
        if reserve_type == "frequency_response"
        else ""
    )

    # By-timepoint requirement, read at the run's weather iteration for the
    # BAs whose requirement varies by it and at weather_iteration 0 otherwise
    check_requirement_iteration_config(
        weather_iteration=weather_iteration,
        conn=conn,
        reserve_type=reserve_type,
        reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
        reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
    )
    tmp_req = c.execute(
        get_tmp_requirement_sql(
            subscenarios=subscenarios,
            weather_iteration=weather_iteration,
            subproblem=subproblem,
            stage=stage,
            reserve_type=reserve_type,
            value_columns=f"{reserve_type}_mw{partial_freq_resp_extra_column}",
            reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
            reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
        )
    )

    c2 = conn.cursor()
    # Get any percentage requirement
    percentage_req = c2.execute(
        """
        SELECT {reserve_type}_ba, percent_load_req
        FROM inputs_system_{reserve_type}_percent
        JOIN
        (SELECT {reserve_type}_ba
        FROM inputs_geography_{reserve_type}_bas
        WHERE {reserve_type}_ba_scenario_id = {reserve_type_ba_subscenario_id}) as relevant_bas
        USING ({reserve_type}_ba)
        WHERE {reserve_type}_scenario_id = {reserve_type_req_subscenario_id}
        AND stage_id = {stage}
        """.format(
            reserve_type=reserve_type,
            reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
            reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
            stage=stage,
        )
    )

    # Get any reserve zone to load zone (and load component) mapping for the
    # percent target
    c3 = conn.cursor()
    lz_mapping = c3.execute(
        get_percent_map_sql(
            reserve_type=reserve_type,
            reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
            reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
        )
    )

    # Get any project contributions to the magnitude of the reserve requirement
    c4 = conn.cursor()
    project_contributions = c4.execute(
        """
        SELECT {reserve_type}_ba, project, percent_power_req, 
        percent_capacity_req
        FROM inputs_system_{reserve_type}_project
        JOIN (
        SELECT {reserve_type}_ba
        FROM inputs_geography_{reserve_type}_bas
        WHERE {reserve_type}_ba_scenario_id = {reserve_type_ba_subscenario_id}
        ) as relevant_bas
        USING ({reserve_type}_ba)
        JOIN (
        SELECT project
        FROM inputs_project_portfolios
        WHERE project_portfolio_scenario_id = (
                SELECT project_portfolio_scenario_id
                FROM scenarios
                WHERE scenario_id = {scenario_id}
            )
        ) as relevant_prj
        USING (project)
        WHERE {reserve_type}_scenario_id = {reserve_type_req_subscenario_id}
        AND stage_id = {stage}
        """.format(
            reserve_type=reserve_type,
            reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
            scenario_id=scenario_id,
            reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
            stage=stage,
        )
    )

    return tmp_req, percentage_req, lz_mapping, project_contributions


def get_percent_map_sql(
    reserve_type, reserve_type_ba_subscenario_id, reserve_type_req_subscenario_id
):
    """
    :return: SQL selecting the ({reserve_type}_ba, load_zone, load_component)
        rows of the percent requirement map for the scenario's BAs; a NULL
        load_component stands for the load zone's whole load
    """
    return f"""
        SELECT DISTINCT {reserve_type}_ba, load_zone, load_component
        FROM inputs_system_{reserve_type}_percent_lz_map
        JOIN
        (SELECT {reserve_type}_ba
        FROM inputs_geography_{reserve_type}_bas
        WHERE {reserve_type}_ba_scenario_id = {reserve_type_ba_subscenario_id}
        ) as relevant_bas
        USING ({reserve_type}_ba)
        WHERE {reserve_type}_scenario_id = {reserve_type_req_subscenario_id}
        """


def get_unknown_percent_map_load_components(
    subscenarios,
    conn,
    reserve_type,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
):
    """
    :return: list of (BA, load_zone, load_component) of percent map rows
        naming a load component that is not among the scenario's load
        components for that load zone
    """
    return conn.execute(f"""
        SELECT {reserve_type}_ba, load_zone, load_component
        FROM ({get_percent_map_sql(
            reserve_type,
            reserve_type_ba_subscenario_id,
            reserve_type_req_subscenario_id,
        )})
        WHERE load_component IS NOT NULL
        AND (load_zone, load_component) NOT IN (
            SELECT load_zone, load_component
            FROM inputs_system_load_components
            WHERE load_components_scenario_id = (
                SELECT load_components_scenario_id
                FROM inputs_system_load
                WHERE load_scenario_id = {subscenarios.LOAD_SCENARIO_ID}
                )
            )
        ORDER BY {reserve_type}_ba, load_zone, load_component
        ;""").fetchall()


def get_double_counted_percent_map_load_zones(
    conn,
    reserve_type,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
):
    """
    :return: list of (BA, load_zone) whose percent map includes both the
        load zone's whole load and some of its load components, i.e. counts
        those load components twice
    """
    map_sql = get_percent_map_sql(
        reserve_type, reserve_type_ba_subscenario_id, reserve_type_req_subscenario_id
    )
    return conn.execute(f"""
        SELECT {reserve_type}_ba, load_zone
        FROM ({map_sql})
        WHERE load_component IS NULL
        AND ({reserve_type}_ba, load_zone) IN (
            SELECT {reserve_type}_ba, load_zone
            FROM ({map_sql})
            WHERE load_component IS NOT NULL
            )
        ORDER BY {reserve_type}_ba, load_zone
        ;""").fetchall()


def get_requirement_iteration_config_sql(
    reserve_type, reserve_type_ba_subscenario_id, reserve_type_req_subscenario_id
):
    """
    :return: SQL selecting ({reserve_type}_ba, varies_by_weather_iteration)
        for the BAs of the scenario's reserve BA subscenario

    Whether a BA's by-timepoint requirement varies by weather iteration
    comes from inputs_system_{reserve_type}_iterations; a BA without a row
    does not, i.e. its rows sit at weather_iteration 0.
    """
    return f"""
        SELECT ba.{reserve_type}_ba,
        COALESCE(it.varies_by_weather_iteration, 0)
            AS varies_by_weather_iteration
        FROM inputs_geography_{reserve_type}_bas AS ba
        LEFT JOIN inputs_system_{reserve_type}_iterations AS it
        ON it.{reserve_type}_ba = ba.{reserve_type}_ba
        AND it.{reserve_type}_scenario_id = {reserve_type_req_subscenario_id}
        WHERE ba.{reserve_type}_ba_scenario_id = {reserve_type_ba_subscenario_id}
    """


def get_tmp_requirement_sql(
    subscenarios,
    weather_iteration,
    subproblem,
    stage,
    reserve_type,
    value_columns,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
):
    """
    :param value_columns: str, the comma-separated requirement columns to
        select after the BA and timepoint
    :return: SQL selecting the by-timepoint requirement of the scenario's
        BAs for the subproblem and stage's timepoints, at the run's weather
        iteration for the BAs whose requirement varies by it and at
        weather_iteration 0 otherwise
    """
    # cfg must be the outer loop so the requirement table's primary key is
    # searched with the weather iteration, which depends on
    # cfg.varies_by_weather_iteration; CROSS JOIN fixes SQLite's join order
    # (see the outage derates in
    # gridpath.project.availability.availability_types.exogenous)
    return f"""
        SELECT {reserve_type}_ba, timepoint, {value_columns}
        FROM ({get_requirement_iteration_config_sql(
            reserve_type,
            reserve_type_ba_subscenario_id,
            reserve_type_req_subscenario_id,
        )}) AS cfg
        CROSS JOIN inputs_system_{reserve_type}
        USING ({reserve_type}_ba)
        INNER JOIN
        (SELECT stage_id, timepoint
        FROM inputs_temporal
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND subproblem_id = {subproblem}
        AND stage_id = {stage}) as relevant_timepoints
        USING (stage_id, timepoint)
        WHERE {reserve_type}_scenario_id = {reserve_type_req_subscenario_id}
        AND weather_iteration = CASE WHEN cfg.varies_by_weather_iteration
            THEN {weather_iteration} ELSE 0 END
        AND stage_id = {stage}
        """


def get_bas_varying_by_weather(
    conn,
    reserve_type,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
):
    """
    :return: sorted list of the scenario's BAs whose by-timepoint
        requirement is flagged to vary by weather iteration
    """
    return [ba for (ba,) in conn.execute(f"""
            SELECT {reserve_type}_ba
            FROM ({get_requirement_iteration_config_sql(
                reserve_type,
                reserve_type_ba_subscenario_id,
                reserve_type_req_subscenario_id,
            )})
            WHERE varies_by_weather_iteration
            ORDER BY {reserve_type}_ba
            ;""").fetchall()]


def check_requirement_iteration_config(
    weather_iteration,
    conn,
    reserve_type,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
):
    """
    Raise if a BA's requirement varies by weather iteration but the run has
    none (weather_iteration 0), the same guard the outage availability
    derates apply.
    """
    if weather_iteration != 0:
        return

    offending = get_bas_varying_by_weather(
        conn=conn,
        reserve_type=reserve_type,
        reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
        reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
    )
    if offending:
        raise ValueError(
            f"The {reserve_type} requirements of BAs {offending} vary by "
            f"weather iteration but the run has weather_iteration=0. BAs "
            f"should not vary by weather iteration when the scenario has none."
        )


def get_unread_requirement_rows(
    conn,
    reserve_type,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
):
    """
    :return: list of (BA, weather_iteration) of by-timepoint requirement
        rows at a non-zero weather iteration of BAs whose requirement is not
        flagged to vary by it; such rows are never read
    """
    # cfg must be the outer loop (see get_tmp_requirement_sql) so only the
    # unflagged BAs' rows are searched; weather_iteration > 0 and < 0 are
    # separate index ranges (SQLite searches "!= 0" by scanning all the BA's
    # rows)
    return conn.execute(
        "\nUNION\n".join(f"""
        SELECT {reserve_type}_ba, weather_iteration
        FROM ({get_requirement_iteration_config_sql(
            reserve_type,
            reserve_type_ba_subscenario_id,
            reserve_type_req_subscenario_id,
        )}) AS cfg
        CROSS JOIN inputs_system_{reserve_type}
        USING ({reserve_type}_ba)
        WHERE {reserve_type}_scenario_id = {reserve_type_req_subscenario_id}
        AND NOT cfg.varies_by_weather_iteration
        AND weather_iteration {comparison} 0
        """ for comparison in (">", "<"))
        + f"ORDER BY {reserve_type}_ba, weather_iteration;"
    ).fetchall()


def get_bas_missing_weather_slice(
    subscenarios,
    weather_iteration,
    subproblem,
    stage,
    conn,
    reserve_type,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
):
    """
    :return: sorted list of the BAs flagged to vary by weather iteration
        that have no by-timepoint requirement rows at the run's weather
        iteration in the subproblem and stage; their requirement would
        silently be 0 (the parameter default) in every timepoint
    """
    if weather_iteration == 0:
        return []

    flagged = get_bas_varying_by_weather(
        conn=conn,
        reserve_type=reserve_type,
        reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
        reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
    )
    with_rows = set(
        ba
        for (ba, *_) in conn.execute(
            get_tmp_requirement_sql(
                subscenarios=subscenarios,
                weather_iteration=weather_iteration,
                subproblem=subproblem,
                stage=stage,
                reserve_type=reserve_type,
                value_columns="1",
                reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
                reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
            )
        ).fetchall()
    )
    return [ba for ba in flagged if ba not in with_rows]


def generic_validate_inputs(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    reserve_type,
    reserve_type_ba_subscenario_id,
    reserve_type_req_subscenario_id,
    gridpath_module,
):
    """
    Validate the weather iteration keying of the by-timepoint requirement:
    BAs flagged to vary by weather iteration in a run without weather
    iterations, BAs flagged to vary that have no rows at the run's weather
    iteration, and rows at a non-zero weather iteration of BAs not flagged
    to vary by it (never read). Validate the percent requirement map: load
    components that are not among the scenario's load components for the
    load zone, and load zones mapped both whole and by load component.
    """
    db_table = f"inputs_system_{reserve_type}"
    common_kwargs = dict(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=gridpath_module,
        db_table=db_table,
        severity="High",
    )
    req_kwargs = dict(
        conn=conn,
        reserve_type=reserve_type,
        reserve_type_ba_subscenario_id=reserve_type_ba_subscenario_id,
        reserve_type_req_subscenario_id=reserve_type_req_subscenario_id,
    )

    if weather_iteration == 0:
        flagged = get_bas_varying_by_weather(**req_kwargs)
        no_iterations_errors = (
            [
                f"BAs {flagged} are flagged in {db_table}_iterations to vary "
                f"by weather iteration but the scenario has no weather "
                f"iterations."
            ]
            if flagged
            else []
        )
    else:
        no_iterations_errors = []
    write_validation_to_database(errors=no_iterations_errors, **common_kwargs)

    write_validation_to_database(
        errors=[
            f"BA {ba} is flagged to vary by weather iteration but has no "
            f"{db_table} rows at weather_iteration {weather_iteration}, so "
            f"its requirement would be 0 in every timepoint."
            for ba in get_bas_missing_weather_slice(
                subscenarios=subscenarios,
                weather_iteration=weather_iteration,
                subproblem=subproblem,
                stage=stage,
                **req_kwargs,
            )
        ],
        **common_kwargs,
    )

    write_validation_to_database(
        errors=[
            f"BA {ba} has rows at weather_iteration {w} but is not flagged "
            f"to vary by weather iteration in {db_table}_iterations, so they "
            f"are never read."
            for ba, w in get_unread_requirement_rows(**req_kwargs)
        ],
        **common_kwargs,
    )

    map_table = f"inputs_system_{reserve_type}_percent_lz_map"
    map_kwargs = dict(common_kwargs, db_table=map_table)
    write_validation_to_database(
        errors=[
            f"BA {ba}'s percent requirement includes load component {cmp} of "
            f"load zone {lz}, which is not among the scenario's load "
            f"components for that load zone."
            for ba, lz, cmp in get_unknown_percent_map_load_components(
                subscenarios=subscenarios, **req_kwargs
            )
        ],
        **map_kwargs,
    )
    write_validation_to_database(
        errors=[
            f"BA {ba}'s percent requirement includes both the whole load of "
            f"load zone {lz} (empty load_component) and some of its load "
            f"components, so those load components are counted twice."
            for ba, lz in get_double_counted_percent_map_load_zones(**req_kwargs)
        ],
        **map_kwargs,
    )


def write_percent_map_files(inputs_dir, reserve_type, percent_map):
    """
    :param percent_map: list of (BA, load_zone, load_component) rows; a None
        load_component stands for the load zone's whole load

    Write the reserve zone to whole load zone map ({reserve_type}_percent_map.tab)
    and the reserve zone to load zone-load component map
    ({reserve_type}_percent_load_component_map.tab), each only if it has rows.
    """
    for filename, header, rows in [
        (
            f"{reserve_type}_percent_map.tab",
            ["ba", "load_zone"],
            [(ba, lz) for (ba, lz, cmp) in percent_map if cmp is None],
        ),
        (
            f"{reserve_type}_percent_load_component_map.tab",
            ["ba", "load_zone", "load_component"],
            [(ba, lz, cmp) for (ba, lz, cmp) in percent_map if cmp is not None],
        ),
    ]:
        if rows:
            with open(
                os.path.join(inputs_dir, filename), "w", newline=""
            ) as percent_map_file:
                writer = csv.writer(
                    percent_map_file, delimiter="\t", lineterminator="\n"
                )
                writer.writerow(header)
                for row in rows:
                    writer.writerow(row)


def generic_write_model_inputs(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    timepoint_req,
    percent_req,
    percent_map,
    project_contributions,
    reserve_type,
):
    """
    Get inputs from database and write out the model input
    lf_reserves_down_requirement.tab file.
    :param scenario_directory: string, the scenario directory
    :param subproblem:
    :param stage:
    :param timepoint_req:
    :param percent_req:
    :param percent_map:
    :param project_contributions:
    :param reserve_type:
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

    inputs_dir = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
    )

    # Write the by-timepoint requirement file if by-tmp requirement specified
    timepoint_req = timepoint_req.fetchall()
    if timepoint_req:
        with open(
            os.path.join(inputs_dir, "{}_tmp_requirement.tab".format(reserve_type)),
            "w",
            newline="",
        ) as tmp_req_file:
            writer = csv.writer(tmp_req_file, delimiter="\t", lineterminator="\n")

            # Write header
            extra_column = (
                ["partial_requirement"] if reserve_type == "frequency_response" else []
            )
            writer.writerow(["ba", "timepoint", "requirement"] + extra_column)

            for row in timepoint_req:
                writer.writerow(row)

    # Write the percent requirement files only if there's a mapping; whole
    # load zones and load components go in separate map files
    percent_map = percent_map.fetchall()
    if percent_map:
        with open(
            os.path.join(inputs_dir, "{}_percent_requirement.tab".format(reserve_type)),
            "w",
            newline="",
        ) as percent_req_file:
            writer = csv.writer(percent_req_file, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(["ba", "percent_requirement"])

            for row in percent_req:
                writer.writerow(row)

        write_percent_map_files(
            inputs_dir=inputs_dir,
            reserve_type=reserve_type,
            percent_map=percent_map,
        )

    # Project contributions to the magnitude requirement
    project_contributions = project_contributions.fetchall()

    prj_contributions = False
    for ba, prj, pwr, cap in project_contributions:
        if pwr is not None or cap is not None:
            prj_contributions = True

    if prj_contributions:
        with open(
            os.path.join(
                inputs_dir,
                "{}_requirement_project_contributions.tab".format(reserve_type),
            ),
            "w",
            newline="",
        ) as prj_file:
            writer = csv.writer(prj_file, delimiter="\t", lineterminator="\n")

            # Write header
            writer.writerow(
                ["ba", "project", "percent_power_req", "percent_capacity_req"]
            )
            for ba, prj, pwr, cap in project_contributions:
                if pwr is None:
                    pwr = "."
                if cap is None:
                    cap = "."
                writer.writerow([ba, prj, pwr, cap])
