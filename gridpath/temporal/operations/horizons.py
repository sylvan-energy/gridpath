# Copyright 2016-2025 Blue Marble Analytics LLC.
# Copyright 2026 Blue Marble Analytics LLC.
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
GridPath organizes timepoints into *balancing types* and *horizons* that
describe how *timepoints* are grouped together when making operational
decisions, with some operational constraints enforced over the *horizon* for
each *balancing type*, e.g. hydro budgets or storage energy balance. As a
simple example, in the case of modeling a full year with 8760 timepoints, we
could have three *balancing types*: a day, a month, and a year; there would
then be 365 *horizons* of the *balancing type* 'day,' 12 *horizons* of the
*balancing type* 'month,' and 1 *horizon* of the *balancing type* 'year.'
Within each balancing types, horizons are modeled as independent from each
other for operational purposes (i.e operational decisions made on one
horizon do not affect those made on another horizon). Generator and storage
resources in GridPath are also assigned *balancing types*: a hydro plant
of the *balancing type* 'day' would have to meet an energy budget constraint
on each of the 365 'day' *horizons* whereas one of the *balancing type*
'year' would only have a single energy budget constraint grouping all 8760
timepoints.

Each *horizon* has boundary condition that can be 'circular,' 'linear,'
or 'linked.' With the 'circular' approach, the last timepoint of the
horizon is considered the previous timepoint for the first timepoint of the
horizon (for the purposes of functionality such as ramp constraints or
tracking storage state of charge). If the boundary is 'linear,' then we
ignore constraints relating to the previous timepoint in the first timepoint
of a horizon. If the boundary is 'linked,' then we use the last timepoint of
the previous horizon as the previous timepoint for the first timepoint of a
horizon (this can only be done when running multiple subproblems and inputs
must be specified appropriately).
"""

import csv
import os.path
import warnings

from pyomo.environ import Set, Param, PositiveIntegers

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    get_expected_dtypes,
    validate_dtypes,
    validate_values,
    validate_single_input,
    validate_missing_inputs,
)
from gridpath.project import write_tab_file_model_inputs

BUILTIN_HORIZON_TYPES = [
    "subproblem_circular",
    "subproblem_period_circular",
    "subproblem_linear",
    "subproblem_period_linear",
    "subproblem_linked",
    "subproblem_period_linked",
]


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
    | | :code:`BLN_TYPE_HRZS`                                                 |
    |                                                                         |
    | Two dimensional set of balancing types and their associated horizons.   |
    | Balancing types are strings, e.g. year, month, week, day, whereas       |
    | horizons must be non-negative integers.                                 |
    +-------------------------------------------------------------------------+
    | | :code:`TMPS_BY_BLN_TYPE_HRZ`                                          |
    | | *Defined over*: :code:`BLN_TYPE_HRZS`                                 |
    |                                                                         |
    | Ordered, indexed set that describes the the horizons associated with    |
    | each balancing type. The timepoins within a horizon-balancing type      |
    | are ordered.                                                            |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Sets                                                            |
    +=========================================================================+
    | | :code:`BLN_TYPES`                                                     |
    |                                                                         |
    | The list of all balancing types.                                        |
    +-------------------------------------------------------------------------+
    | | :code:`HRZS_BY_BLN_TYPE`                                              |
    | | *Defined over*: :code:`BLN_TYPES`                                     |
    |                                                                         |
    | Ordered, indexed set that describes the horizons associated with        |
    | each balancing type. The horizons within a balancing type are ordered.  |
    +-------------------------------------------------------------------------+
    | | :code:`TMPS_BLN_TYPES`                                                |
    |                                                                         |
    | Two-dimensional set of all timepoints along with the balancing types    |
    | each timepoint belongs to.                                              |
    +-------------------------------------------------------------------------+


    |

    +-------------------------------------------------------------------------+
    | Required Input Params                                                   |
    +=========================================================================+
    | | :code:`horizon`                                                       |
    | | *Defined over*: :code:`TMPS x BLN_TYPES`                              |
    |                                                                         |
    | Describes the horizon that each timeoint belongs to for a given         |
    | balancing type. Depending on the balancing type, timepoints can be      |
    | grouped in different horizons.                                          |
    +-------------------------------------------------------------------------+
    | | :code:`boundary`                                                      |
    | | *Defined over*: :code:`BLN_TYPE_HRZS`                                 |
    | | *Within*: :code:`['circular', 'linear']`                              |
    |                                                                         |
    | The boundary for each horizon. If the boundary is 'circular,' then the  |
    | last timepoint of the horizon is treated as the 'previous' timepoint    |
    | for the first timepoint of the horizon (e.g. for ramping constraints    |
    | or tracking storage state of charge).                                   |
    +-------------------------------------------------------------------------+

    |

    +-------------------------------------------------------------------------+
    | Derived Input Params                                                    |
    +=========================================================================+
    | | :code:`first_hrz_tmp`                                                 |
    | | *Defined over*: :code:`BLN_TYPE_HRZS`                                 |
    |                                                                         |
    | Derived parameter describing the first timepoint in each horizon for a  |
    | given balancing type. Note: this relies on :code:`TMPS_BY_BLN_TYPE_HRZ` |
    | being an ordered (indexed) set.                                         |
    +-------------------------------------------------------------------------+
    | | :code:`last_hrz_tmp`                                                  |
    | | *Defined over*: :code:`BLN_TYPE_HRZS`                                 |
    |                                                                         |
    | Derived parameter describing the last timepoint in each horizon for a   |
    | given balancing type. Note: this relies on :code:`TMPS_BY_BLN_TYPE_HRZ` |
    | being an ordered (indexed) set.                                         |
    +-------------------------------------------------------------------------+
    | | :code:`prev_tmp`                                                      |
    | | *Defined over*: :code:`TMPS x BLN_TYPES`                              |
    | | *Within*: :code: `m.TMPS | {None}`                                    |
    |                                                                         |
    | Derived parameter describing the previous timepoint for each timepoint  |
    | in each balancing type; depends on whether horizon is circular or       |
    | linear and relies on having ordered :code:`TMPS`.                       |
    +-------------------------------------------------------------------------+
    | | :code:`next_tmp`                                                      |
    | | *Defined over*: :code:`TMPS x BLN_TYPES`                              |
    | | *Within*: :code: `m.TMPS | {None}`                                    |
    |                                                                         |
    | Derived parameter describing the next timepoint for each timepoint in   |
    | each balancing type; depends on whether horizon is circular or linear   |
    | and relies on having ordered :code:`TMPS`.                              |
    +-------------------------------------------------------------------------+


    """

    # Sets
    ###########################################################################

    m.BLN_TYPE_HRZS_USER_DEFINED = Set(dimen=2)

    def get_valid_period_months_by_tmp(mod):
        prd_months = list(set([(mod.period[tmp], mod.month[tmp]) for tmp in mod.TMPS]))

        return prd_months

    m.VALID_PERIOD_MONTHS = Set(
        within=m.PERIODS * m.MONTHS, initialize=get_valid_period_months_by_tmp
    )

    def builtin_bln_type_hrz_init(mod):
        """
        Built in balancing types:
        * subproblem: all timepoints in the subproblem belong to a single
          horizon of the balancing type 'subproblem.'
        * subproblem_period: all timepoints in a given period in the subproblem
        * subproblem_period_month: all timepoints in a given month in the
        subproblem and period

        These can be linear or circular
        """
        return set(
            [("subproblem_circular", 1)]
            + [("subproblem_period_circular", period) for period in mod.PERIODS]
            + [("subproblem_linear", 1)]
            + [("subproblem_period_linear", period) for period in mod.PERIODS]
            + [("subproblem_linked", 1)]
            + [("subproblem_period_linked", period) for period in mod.PERIODS]
            + [
                ("subproblem_period_month_linear", period * 100 + month)
                for (period, month) in mod.VALID_PERIOD_MONTHS
            ]
            + [
                ("subproblem_period_month_circular", period * 100 + month)
                for (period, month) in mod.VALID_PERIOD_MONTHS
            ]
        )

    m.BLN_TYPE_HRZS_BUILTIN = Set(dimen=2, initialize=builtin_bln_type_hrz_init)

    m.BLN_TYPE_HRZS = Set(
        dimen=2,
        initialize=lambda mod: mod.BLN_TYPE_HRZS_USER_DEFINED.union(
            mod.BLN_TYPE_HRZS_BUILTIN
        ),
    )

    # Timepoints by balancing type and horizon
    m.TMPS_BY_BLN_TYPE_HRZ_USER_DEFINED = Set(
        m.BLN_TYPE_HRZS_USER_DEFINED, within=PositiveIntegers
    )

    # TODO: add linked
    def tmps_by_bln_type_hrz_builtin_init(mod, b, h):
        """ """
        if b in ["subproblem_circular", "subproblem_linear", "subproblem_linked"]:
            return [tmp for tmp in mod.TMPS]
        elif b in [
            "subproblem_period_circular",
            "subproblem_period_linear",
            "subproblem_period_linked",
        ]:
            return [tmp for tmp in mod.TMPS_IN_PRD[h]]
        elif b in [
            "subproblem_period_month_circular",
            "subproblem_period_month_linear",
        ]:
            return [
                tmp for tmp in mod.TMPS if (mod.month[tmp] + 100 * mod.period[tmp]) == h
            ]
        else:
            raise ValueError(
                f"Unrecognized built-in balancing type '{b}' " f"with horizon '{h}'."
            )

    m.TMPS_BY_BLN_TYPE_HRZ_BUILTIN = Set(
        m.BLN_TYPE_HRZS_BUILTIN,
        within=PositiveIntegers,
        initialize=tmps_by_bln_type_hrz_builtin_init,
    )

    def tmps_by_bln_type_hrz_join_init(mod):
        joined_indexed_sets = {}
        for bt, hrz in mod.BLN_TYPE_HRZS_USER_DEFINED:
            joined_indexed_sets[bt, hrz] = list(
                mod.TMPS_BY_BLN_TYPE_HRZ_USER_DEFINED[bt, hrz]
            )

        for bt, hrz in mod.BLN_TYPE_HRZS_BUILTIN:
            joined_indexed_sets[bt, hrz] = list(
                mod.TMPS_BY_BLN_TYPE_HRZ_BUILTIN[bt, hrz]
            )

        return joined_indexed_sets

    m.TMPS_BY_BLN_TYPE_HRZ = Set(
        m.BLN_TYPE_HRZS,
        within=PositiveIntegers,
        initialize=tmps_by_bln_type_hrz_join_init,
    )

    # Derived Sets
    ###########################################################################

    m.BLN_TYPES = Set(initialize=balancing_types_init)

    m.HRZS_BY_BLN_TYPE = Set(
        m.BLN_TYPES, within=PositiveIntegers, initialize=horizons_by_balancing_type_init
    )

    m.TMPS_BLN_TYPES = Set(
        dimen=2,
        within=m.TMPS * m.BLN_TYPES,
        initialize=lambda mod: sorted(
            list(
                set(
                    [
                        (tmp, bt)
                        for (bt, h) in mod.BLN_TYPE_HRZS
                        for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, h]
                    ]
                ),
            )
        ),
    )

    # Required Params
    ###########################################################################

    m.horizon = Param(
        m.TMPS,
        m.BLN_TYPES,
        within=PositiveIntegers | {None},
        initialize=horizon_init,
    )

    m.boundary_user_defined = Param(
        m.BLN_TYPE_HRZS_USER_DEFINED, within=["circular", "linear", "linked"]
    )

    def boundary_builtin_init(mod, b, h):
        return b.split("_")[-1]

    m.boundary_builtin = Param(
        m.BLN_TYPE_HRZS_BUILTIN,
        within=["circular", "linear", "linked"],
        initialize=boundary_builtin_init,
    )

    def boundary_join_init(mod, b, h):
        if (b, h) in mod.BLN_TYPE_HRZS_USER_DEFINED:
            return mod.boundary_user_defined[b, h]
        elif (b, h) in mod.BLN_TYPE_HRZS_BUILTIN:
            return mod.boundary_builtin[b, h]
        else:
            raise ValueError(
                f"Balancing type - horizon pair {b} {h} not found in either "
                f"user-defined or builtin sets."
            )

    m.boundary = Param(
        m.BLN_TYPE_HRZS,
        within=["circular", "linear", "linked"],
        initialize=boundary_join_init,
    )

    # Derived Params
    ###########################################################################

    def first_hrz_tmp_init(mod, b, h):
        return list(mod.TMPS_BY_BLN_TYPE_HRZ[b, h])[0]

    m.first_hrz_tmp = Param(
        m.BLN_TYPE_HRZS,
        within=PositiveIntegers,
        initialize=first_hrz_tmp_init,
    )

    def last_hrz_tmp_init(mod, b, h):
        return list(mod.TMPS_BY_BLN_TYPE_HRZ[b, h])[-1]

    m.last_hrz_tmp = Param(
        m.BLN_TYPE_HRZS,
        within=PositiveIntegers,
        initialize=last_hrz_tmp_init,
    )

    def hrz_period_init(mod, bt, hrz):
        if (
            mod.period[mod.first_hrz_tmp[bt, hrz]]
            == mod.period[mod.first_hrz_tmp[bt, hrz]]
        ):
            return mod.period[mod.first_hrz_tmp[bt, hrz]]
        else:
            warnings.warn(f"""Horizon found that spans periods. Is this intended? Check 
                timepoints for balancing type {bt}, horizon {hrz}. Some 
                functionality sets the horizon period to the period of the 
                first timepoint of the horizon.""")

    m.hrz_period = Param(m.BLN_TYPE_HRZS, within=m.PERIODS, initialize=hrz_period_init)

    m.prev_tmp = Param(
        m.TMPS_BLN_TYPES, within=m.TMPS | {"."}, initialize=prev_tmp_init
    )

    m.next_tmp = Param(
        m.TMPS_BLN_TYPES, within=m.TMPS | {"."}, initialize=next_tmp_init
    )


# Set Rules
###############################################################################


def balancing_types_init(mod):
    """
    **Set Name**: BLN_TYPES

    Derives the unique set of balancing types from the 2-dimensional
    BLN_TYPE_HRZS set.
    """
    balancing_types = list()
    for b, h in mod.BLN_TYPE_HRZS:
        if b in balancing_types:
            pass
        else:
            balancing_types.append(b)

    return balancing_types


def horizons_by_balancing_type_init(mod, bt):
    """
    **Set Name**: HRZS_BY_BLN_TYPE
    **Defined Over**: BLN_TYPES

    Re-arranges the 2-dimensional BLN_TYPE_HRZS set into a 1-dimensional set of
    horizons by balancing type.
    """
    horizons_of_balancing_type = []
    for b, h in mod.BLN_TYPE_HRZS:
        if b == bt:
            horizons_of_balancing_type.append(h)

    return horizons_of_balancing_type


# Param Rules
###############################################################################


def horizon_init(mod):
    """
    **Param Name**: horizon
    **Defined Over**: TMPS x BLN_TYPES

    Determine the horizon of each timepoint for each balancing type in a
    single pass over the horizons. Timepoints that don't belong to any
    horizon of a balancing type get None.
    """
    tmp_bt_to_hrz = {}
    for bt, hrz in mod.BLN_TYPE_HRZS:
        for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]:
            tmp_bt_to_hrz[tmp, bt] = hrz

    return {
        (tmp, bt): tmp_bt_to_hrz.get((tmp, bt))
        for tmp in mod.TMPS
        for bt in mod.BLN_TYPES
    }


def prev_tmp_init(mod):
    """
    **Param Name**: prev_tmp
    **Defined Over**: TMPS x BLN_TYPES

    Determine the previous timepoint for each timepoint. If the timepoint is
    the first timepoint of a horizon and the horizon boundary is circular,
    then the previous timepoint is the last timepoint of the respective
    horizon (for each horizon type). If the timepoint is the first timepoint
    of a horizon and the horizon boundary is linear, then no previous
    timepoint is defined. In all other cases, the previous timepoints is the
    one with an index of tmp-1.
    """
    prev_tmp = {}
    for bt, hrz in mod.BLN_TYPE_HRZS:
        boundary = mod.boundary[bt, hrz]
        if boundary not in ["circular", "linear", "linked"]:
            raise ValueError(
                "Invalid boundary value '{}' for balancing type "
                "horizon '{} {}'".format(boundary, bt, hrz)
                + "\n"
                + "Horizon boundary must be 'circular,' 'linear,' "
                "or 'linked.'"
            )
        tmps = list(mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz])
        prev_tmp[tmps[0], bt] = tmps[-1] if boundary == "circular" else "."
        for prev_t, tmp in zip(tmps[:-1], tmps[1:]):
            prev_tmp[tmp, bt] = prev_t

    return prev_tmp


def next_tmp_init(mod):
    """
    **Param Name**: next_tmp
    **Defined Over**: TMPS x BLN_TYPES

    Determine the next timepoint for each timepoint. If the timepoint is
    the last timepoint of a horizon and the horizon boundary is circular,
    then the next timepoint is the first timepoint of the respective
    horizon. If the timepoint is the last timepoint of a horizon and the
    horizon boundary is linear, then no next timepoint is defined. In all
    other cases, the next timepoint is the one with an index of tmp+1.
    """
    next_tmp = {}
    for bt, hrz in mod.BLN_TYPE_HRZS:
        boundary = mod.boundary[bt, hrz]
        if boundary not in ["circular", "linear", "linked"]:
            raise ValueError(
                "Invalid boundary value '{}' for balancing "
                "type horizon '{} {}'".format(boundary, bt, hrz)
                + "\n"
                + "Horizon boundary must be 'circular,' 'linear,' "
                "or 'linked.'"
            )
        tmps = list(mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz])
        next_tmp[tmps[-1], bt] = tmps[0] if boundary == "circular" else "."
        for tmp, next_t in zip(tmps[:-1], tmps[1:]):
            next_tmp[tmp, bt] = next_t

    return next_tmp


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
    """ """
    hrz_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "horizons_user_defined.tab",
    )

    # Load user-defined horizons if any (i.e., the file exists)
    if os.path.exists(hrz_filename):
        data_portal.load(
            filename=hrz_filename,
            select=("balancing_type_horizon", "horizon", "boundary"),
            index=m.BLN_TYPE_HRZS_USER_DEFINED,
            param=m.boundary_user_defined,
        )

    hrz_tmp_filename = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        "horizon_user_defined_timepoints.tab",
    )
    if os.path.exists(hrz_tmp_filename):
        with open(hrz_tmp_filename) as f:
            reader = csv.reader(f, delimiter="\t", lineterminator="\n")
            next(reader)
            tmps_on_horizon = dict()
            for row in reader:
                if (row[1], int(row[0])) not in tmps_on_horizon.keys():
                    tmps_on_horizon[row[1], int(row[0])] = [int(row[2])]
                else:
                    tmps_on_horizon[row[1], int(row[0])].append(int(row[2]))

        data_portal.data()["TMPS_BY_BLN_TYPE_HRZ_USER_DEFINED"] = tmps_on_horizon

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
    builtin_hrz_types_list = ", ".join(f"'{h}'" for h in BUILTIN_HORIZON_TYPES)
    c1 = conn.cursor()
    horizons = c1.execute(f"""SELECT horizon, balancing_type_horizon, boundary
        FROM inputs_temporal_horizons
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND (balancing_type_horizon, horizon) in (
            SELECT DISTINCT balancing_type_horizon, horizon
            FROM inputs_temporal_horizon_timepoints
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
        )
        -- Don't get the built-ins
        AND balancing_type_horizon NOT IN ({builtin_hrz_types_list})
        ORDER BY balancing_type_horizon, horizon;
        """)

    c2 = conn.cursor()
    horizon_timepoints = c2.execute(
        f"""SELECT horizon, balancing_type_horizon, timepoint
        FROM inputs_temporal_horizon_timepoints
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
       AND subproblem_id = {subproblem}
       AND stage_id = {stage}
       -- Don't get the built-ins
       AND balancing_type_horizon NOT IN ({builtin_hrz_types_list})
       ORDER BY balancing_type_horizon, timepoint;"""
    )

    return horizons, horizon_timepoints


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
    horizons_user_defined.tab file.
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

    horizons, horizon_timepoints = get_inputs_from_database(
        scenario_id,
        subscenarios,
        db_weather_iteration,
        db_hydro_iteration,
        db_availability_iteration,
        db_subproblem,
        db_stage,
        conn,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="horizons_user_defined.tab",
        data=horizons,
        replace_nulls=False,
    )

    write_tab_file_model_inputs(
        scenario_directory=scenario_directory,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        fname="horizon_user_defined_timepoints.tab",
        data=horizon_timepoints,
        replace_nulls=False,
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

    hrzs, hrz_tmps = get_inputs_from_database(
        scenario_id,
        subscenarios,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        conn,
    )

    c = conn.cursor()

    builtin_hrz_types_list = ", ".join(f"'{h}'" for h in BUILTIN_HORIZON_TYPES)

    periods_horizons = c.execute(f"""
        SELECT balancing_type_horizon, period, horizon
        FROM periods_horizons
        WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
        AND stage_id = {stage}
        AND balancing_type_horizon NOT IN ({builtin_hrz_types_list})
        """)

    df_hrzs = cursor_to_df(hrzs)
    df_hrz_tmps = cursor_to_df(hrz_tmps)
    df_periods_hrzs = cursor_to_df(periods_horizons)

    # Get expected dtypes
    expected_dtypes = get_expected_dtypes(
        conn=conn,
        tables=["inputs_temporal_horizons", "inputs_temporal_horizon_timepoints"],
    )

    # Check dtypes horizons
    dtype_errors, error_columns = validate_dtypes(df_hrzs, expected_dtypes)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_temporal_horizons",
        severity="High",
        errors=dtype_errors,
    )

    # Check dtypes horizon_timepoints
    dtype_errors, error_columns = validate_dtypes(df_hrz_tmps, expected_dtypes)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_temporal_horizon_timepoints",
        severity="High",
        errors=dtype_errors,
    )

    # Check valid numeric columns are non-negative - horizons
    numeric_columns = [c for c in df_hrzs.columns if expected_dtypes[c] == "numeric"]
    valid_numeric_columns = set(numeric_columns) - set(error_columns)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_temporal_horizons",
        severity="Mid",
        errors=validate_values(df_hrzs, valid_numeric_columns, "horizon", min=0),
    )

    # Check valid numeric columns are non-negative - horizon_timepoints
    numeric_columns = [c for c in df_hrzs.columns if expected_dtypes[c] == "numeric"]
    valid_numeric_columns = set(numeric_columns) - set(error_columns)
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_temporal_horizon_timepoints",
        severity="Mid",
        errors=validate_values(
            df_hrz_tmps, valid_numeric_columns, ["horizon", "timepoint"], min=0
        ),
    )

    # Make sure there are no missing horizon inputs
    write_validation_to_database(
        conn=conn,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem_id=subproblem,
        stage_id=stage,
        gridpath_module=__name__,
        db_table="inputs_temporal_horizon_timepoints",
        severity="High",
        errors=validate_missing_inputs(
            df=df_hrz_tmps,
            col="horizon",
            idx_col=["balancing_type_horizon", "timepoint"],
        ),
    )
