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
Components and input/results handling shared by the hydro operational types
(:code:`gen_hydro` and :code:`gen_hydro_must_take`), which differ in whether
output can be curtailed but build their energy budget and its optional
within-horizon allocation limits the same way.

The generic loaders for the hydro operational characteristics themselves
(average/min/max power fraction) live in
:code:`gridpath.project.operations.operational_types.common_functions`, as
they are also used by the energy-shaping operational types.
"""

import csv
import os.path
import pandas as pd
from pyomo.environ import (
    Set,
    Param,
    Expression,
    Constraint,
    PercentFraction,
    PositiveIntegers,
    value,
)

from gridpath.auxiliary.auxiliary import cursor_to_df
from gridpath.auxiliary.db_interface import directories_to_db_values, import_csv
from gridpath.auxiliary.validations import (
    write_validation_to_database,
    validate_values,
    validate_column_monotonicity,
)
from gridpath.common_functions import duals_wrapper
from gridpath.project.common_functions import get_energy_budget_balancing_type
from gridpath.project.operations.operational_types.common_functions import (
    get_bt_hrz_index_query_params,
    get_prj_temporal_index_opr_inputs_from_db,
    write_tab_file_model_inputs,
)

# The allocation limits' data table stores the SUB-horizon's balancing type
# in the canonical balancing_type_horizon column (the hydro opchars tables
# use the historical name balancing_type_project for the project's own
# horizons)
BT_HRZ_HORIZON_COLUMN_INDEX_QUERY_PARAMS = get_bt_hrz_index_query_params(
    "balancing_type_horizon"
)

# Energy-budget allocation limits
###############################################################################
# Limits on how much of a project's horizon energy budget may be produced in
# each sub-horizon of that horizon (e.g. each half of a month with a monthly
# budget). The sub-horizons are horizons of another balancing type in the
# temporal scenario, nested within the project's balancing-type horizons.

HYDRO_BUDGET_ALLOCATION_TAB_FILE = "hydro_budget_allocation.tab"
HYDRO_BUDGET_ALLOCATION_TABLE = "inputs_project_hydro_budget_allocation"
HYDRO_BUDGET_ALLOCATION_SUBSCENARIO_ID_COLUMN = "hydro_budget_allocation_scenario_id"
HYDRO_BUDGET_ALLOCATION_DATA_COLUMNS = "min_budget_fraction, max_budget_fraction"
HYDRO_BUDGET_ALLOCATION_RESULTS_TABLE = "results_project_hydro_budget_allocation"
# The results CSV columns, in order; both hydro operational types write their
# own CSV and import it into the shared results table above, whose columns
# must match these exactly (plus the scenario/iteration keys import_csv adds)
HYDRO_BUDGET_ALLOCATION_RESULTS_COLUMNS = [
    "project",
    "balancing_type_horizon",
    "horizon",
    "parent_balancing_type_horizon",
    "parent_horizon",
    "min_budget_fraction",
    "max_budget_fraction",
    "energy_mwh",
    "parent_budget_mwh",
    "budget_share",
    "min_constraint_dual",
    "max_constraint_dual",
]


def get_hydro_budget_allocation_results_file_name(op_type):
    """
    The per-operational-type results CSV; both types' rows land in the
    shared results table.
    """
    return f"{op_type}_budget_allocation.csv"


def add_hydro_budget_allocation_components(m, op_type, component_prefix, power_var):
    """
    Add the components limiting how a hydro project's horizon energy
    budget may be allocated among sub-horizons of that horizon.

    The calling operational type must define :code:`{OP_TYPE}` (its project
    set), :code:`{OP_TYPE}_OPR_BT_HRZS`, and the Param
    :code:`{op_type}_average_power_fraction` over the latter, from which the
    horizon energy budget is built exactly as in the op type's own energy
    budget constraint. This function then adds:

    * :code:`{OP_TYPE}_BUDGET_ALLOC_BT_HRZS`: three-dimensional set of
      (project, sub-horizon balancing type, sub-horizon) with allocation
      limits; the sub-horizon's timepoints must all belong to a single
      horizon of the project's energy-budget balancing type (the parent horizon).
    * :code:`{op_type}_budget_alloc_min_fraction` /
      :code:`{op_type}_budget_alloc_max_fraction`: the minimum/maximum
      share of the parent horizon's energy budget that must/may be
      produced in the sub-horizon; no default -- a limit that is not
      specified is not enforced. Note that a specified maximum of 1 (or
      minimum of 0) is NOT redundant, as negative output (pumping) in
      other sub-horizons could otherwise let a sub-horizon exceed the
      budget.
    * :code:`{op_type}_budget_alloc_parent_hrz`: the derived parent
      horizon of each sub-horizon; construction raises if a sub-horizon
      straddles parent horizons, has no parent horizon with a budget, or
      is a horizon of the project's energy-budget balancing type.
    * :code:`{OP_TYPE}_BUDGET_ALLOC_PARENT_BT_HRZS`: the parent horizons
      the limits refer to, and
      :code:`{ComponentPrefix}_Parent_Hrz_Energy_Budget_MWh`, their energy
      budget. Both are indexed over only those parent horizons, so a
      project without allocation limits costs nothing.
    * :code:`{ComponentPrefix}_Budget_Alloc_Energy_MWh`: the project's
      gross energy in the sub-horizon.
    * :code:`{ComponentPrefix}_Budget_Alloc_Min_Constraint` /
      :code:`{ComponentPrefix}_Budget_Alloc_Max_Constraint`: sub-horizon
      energy >= min fraction x parent budget, and <= max fraction x
      parent budget; skipped where the respective fraction is not
      specified.

    The shares refer to the budget as enforced, i.e. including any
    availability derates in the parent horizon.

    :param m: the Pyomo abstract model
    :param op_type: str, e.g. "gen_hydro"
    :param component_prefix: str, e.g. "GenHydro"
    :param power_var: str, name of the op type's gross power variable
    """
    op_type_upper = op_type.upper()
    alloc_set_name = f"{op_type_upper}_BUDGET_ALLOC_BT_HRZS"
    opr_bt_hrzs_name = f"{op_type_upper}_OPR_BT_HRZS"
    min_frac_name = f"{op_type}_budget_alloc_min_fraction"
    max_frac_name = f"{op_type}_budget_alloc_max_fraction"
    parent_hrz_name = f"{op_type}_budget_alloc_parent_hrz"
    energy_name = f"{component_prefix}_Budget_Alloc_Energy_MWh"
    parent_bt_hrzs_name = f"{op_type_upper}_BUDGET_ALLOC_PARENT_BT_HRZS"
    budget_name = f"{component_prefix}_Parent_Hrz_Energy_Budget_MWh"
    budget_bt_name = f"{op_type}_energy_budget_balancing_type"

    def budget_bt(mod, prj):
        """
        The balancing type of the project's budget horizons (the parents).
        """
        return get_energy_budget_balancing_type(mod, prj, getattr(mod, budget_bt_name))

    setattr(
        m,
        alloc_set_name,
        Set(dimen=3, within=getattr(m, op_type_upper) * m.BLN_TYPE_HRZS),
    )
    alloc_set = getattr(m, alloc_set_name)

    # No defaults: a limit that is not specified is not enforced (sparse
    # membership is tested in the constraint rules)
    setattr(m, min_frac_name, Param(alloc_set, within=PercentFraction))
    setattr(m, max_frac_name, Param(alloc_set, within=PercentFraction))

    def parent_hrz_init(mod):
        """
        Derive the parent horizon (of the project's energy-budget balancing type)
        of each sub-horizon in a single pass, checking the nesting.
        """
        parent_hrzs = {}
        for prj, sub_bt, sub_hrz in getattr(mod, alloc_set_name):
            bt = budget_bt(mod, prj)
            if sub_bt == bt:
                raise ValueError(
                    f"Hydro budget allocation limits for project {prj} are "
                    f"specified for horizon {sub_hrz} of balancing type "
                    f"{sub_bt}, which is the project's energy-budget balancing type; "
                    f"allocation limits must refer to sub-horizons of a "
                    f"different balancing type nested within the project's "
                    f"horizons."
                )
            parents = {
                mod.horizon[tmp, bt]
                for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[sub_bt, sub_hrz]
            }
            if len(parents) != 1 or None in parents:
                raise ValueError(
                    f"Hydro budget allocation sub-horizon {sub_hrz} of "
                    f"balancing type {sub_bt} for project {prj} is not nested "
                    f"within a single horizon of the project's energy-budget balancing type "
                    f"{bt} (horizons found: {sorted(parents, key=str)})."
                )
            (parent_hrz,) = parents
            if (prj, bt, parent_hrz) not in getattr(mod, opr_bt_hrzs_name):
                raise ValueError(
                    f"Hydro budget allocation sub-horizon {sub_hrz} of "
                    f"balancing type {sub_bt} for project {prj} lies in "
                    f"horizon {parent_hrz} of balancing type {bt}, for which "
                    f"the project has no energy budget."
                )
            parent_hrzs[prj, sub_bt, sub_hrz] = parent_hrz

        return parent_hrzs

    setattr(
        m,
        parent_hrz_name,
        Param(alloc_set, within=PositiveIntegers, initialize=parent_hrz_init),
    )

    def parent_bt_hrzs_init(mod):
        parent_hrz = getattr(mod, parent_hrz_name)
        return sorted(
            {
                (prj, budget_bt(mod, prj), parent_hrz[idx])
                for idx in getattr(mod, alloc_set_name)
                for prj in [idx[0]]
            }
        )

    setattr(
        m,
        parent_bt_hrzs_name,
        Set(dimen=3, initialize=parent_bt_hrzs_init),
    )

    def parent_hrz_energy_budget_rule(mod, prj, bt, hrz):
        """
        The parent horizon's energy budget, built exactly as the op type's
        energy budget constraint builds its right-hand side: the average
        power fraction times the available capacity, over the horizon's
        timepoints. The allocation shares refer to this quantity, so any
        availability derate in the parent horizon shrinks them along with
        the budget itself.
        """
        avg_power_fraction = getattr(mod, f"{op_type}_average_power_fraction")
        return sum(
            avg_power_fraction[prj, bt, hrz]
            * mod.Capacity_MW[prj, mod.period[tmp]]
            * mod.Availability_Derate[prj, tmp]
            * mod.hrs_in_tmp[tmp]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[bt, hrz]
        )

    setattr(
        m,
        budget_name,
        Expression(getattr(m, parent_bt_hrzs_name), rule=parent_hrz_energy_budget_rule),
    )

    def energy_rule(mod, prj, sub_bt, sub_hrz):
        power = getattr(mod, power_var)
        return sum(
            power[prj, tmp] * mod.hrs_in_tmp[tmp]
            for tmp in mod.TMPS_BY_BLN_TYPE_HRZ[sub_bt, sub_hrz]
        )

    setattr(m, energy_name, Expression(alloc_set, rule=energy_rule))

    def parent_budget(mod, prj, sub_bt, sub_hrz):
        return getattr(mod, budget_name)[
            prj,
            budget_bt(mod, prj),
            getattr(mod, parent_hrz_name)[prj, sub_bt, sub_hrz],
        ]

    def min_rule(mod, prj, sub_bt, sub_hrz):
        min_frac = getattr(mod, min_frac_name)
        if (prj, sub_bt, sub_hrz) not in min_frac:
            return Constraint.Skip
        return getattr(mod, energy_name)[prj, sub_bt, sub_hrz] >= min_frac[
            prj, sub_bt, sub_hrz
        ] * parent_budget(mod, prj, sub_bt, sub_hrz)

    def max_rule(mod, prj, sub_bt, sub_hrz):
        max_frac = getattr(mod, max_frac_name)
        if (prj, sub_bt, sub_hrz) not in max_frac:
            return Constraint.Skip
        return getattr(mod, energy_name)[prj, sub_bt, sub_hrz] <= max_frac[
            prj, sub_bt, sub_hrz
        ] * parent_budget(mod, prj, sub_bt, sub_hrz)

    setattr(
        m,
        f"{component_prefix}_Budget_Alloc_Min_Constraint",
        Constraint(alloc_set, rule=min_rule),
    )
    setattr(
        m,
        f"{component_prefix}_Budget_Alloc_Max_Constraint",
        Constraint(alloc_set, rule=max_rule),
    )


def load_hydro_budget_allocation(
    data_portal,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    op_type,
    projects,
):
    """
    Load the (optional) hydro budget allocation limits for the projects of
    *op_type* from the shared hydro_budget_allocation.tab file, which may
    hold rows for several hydro operational types. Unspecified limits (".")
    are left out so the respective constraint is skipped.
    """
    fname = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "inputs",
        HYDRO_BUDGET_ALLOCATION_TAB_FILE,
    )
    if not os.path.exists(fname):
        return

    df = pd.read_csv(fname, sep="\t", dtype=str, keep_default_na=False)
    df = df[df["project"].isin(projects)]

    prj_bt_hrzs = []
    min_frac = {}
    max_frac = {}
    for prj, bt, hrz, min_val, max_val in zip(
        df["project"],
        df["balancing_type_horizon"],
        df["horizon"],
        df["min_budget_fraction"],
        df["max_budget_fraction"],
    ):
        idx = (prj, bt, int(hrz))
        prj_bt_hrzs.append(idx)
        if min_val != ".":
            min_frac[idx] = float(min_val)
        if max_val != ".":
            max_frac[idx] = float(max_val)

    data_portal.data()[f"{op_type.upper()}_BUDGET_ALLOC_BT_HRZS"] = {None: prj_bt_hrzs}
    data_portal.data()[f"{op_type}_budget_alloc_min_fraction"] = min_frac
    data_portal.data()[f"{op_type}_budget_alloc_max_fraction"] = max_frac


def get_hydro_budget_allocation_inputs_from_db(
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    op_type,
):
    """
    Query the hydro budget allocation limits of the *op_type* projects in
    the portfolio for the sub-horizons in the current subproblem/stage;
    iteration/stage/temporal-map resolution is the same as for all other
    horizon-indexed opchar inputs. Takes DATABASE iteration/subproblem/stage
    values (see directories_to_db_values).

    :return: cursor with columns project, balancing_type_horizon, horizon,
        min_budget_fraction, max_budget_fraction
    """
    return get_prj_temporal_index_opr_inputs_from_db(
        subscenarios=subscenarios,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        conn=conn,
        op_type=op_type,
        table=HYDRO_BUDGET_ALLOCATION_TABLE,
        subscenario_id_column=HYDRO_BUDGET_ALLOCATION_SUBSCENARIO_ID_COLUMN,
        data_column=HYDRO_BUDGET_ALLOCATION_DATA_COLUMNS,
        opr_index_dict=BT_HRZ_HORIZON_COLUMN_INDEX_QUERY_PARAMS,
    )


def write_hydro_budget_allocation_inputs(
    scenario_directory,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    op_type,
):
    """
    Write the *op_type* projects' hydro budget allocation limits to the
    shared hydro_budget_allocation.tab file (appending if another hydro
    operational type has already written its rows; nothing is written if
    no project of this type has limits). NULL limits are written as ".".
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

    data = get_hydro_budget_allocation_inputs_from_db(
        subscenarios=subscenarios,
        weather_iteration=db_weather_iteration,
        hydro_iteration=db_hydro_iteration,
        availability_iteration=db_availability_iteration,
        subproblem=db_subproblem,
        stage=db_stage,
        conn=conn,
        op_type=op_type,
    )

    write_tab_file_model_inputs(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        HYDRO_BUDGET_ALLOCATION_TAB_FILE,
        data,
        replace_nulls=True,
    )


def validate_hydro_budget_allocation(
    scenario_id,
    subscenarios,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    op_type,
):
    """
    Validate the *op_type* projects' hydro budget allocation limits:
    fractions within [0, 1] (Low), min <= max (Mid), every sub-horizon of a
    balancing type other than the project's own and nested within a single
    horizon of the project's energy-budget balancing type (High), and, per parent horizon,
    sum of minimum shares <= 1 and sum of maximum shares >= 1 (Low --
    infeasible unless the project can produce negative output in some
    sub-horizon). The share sums are only checked for parent horizons whose
    timepoints the listed sub-horizons exactly cover, as the budget applies
    to the whole parent horizon; an unspecified minimum counts as 0, while a
    single unspecified maximum leaves the sum unbounded, so such parents are
    skipped for the maximum check. Like the other validate_* functions, this
    receives DATABASE iteration/subproblem/stage values.
    """
    df = cursor_to_df(
        get_hydro_budget_allocation_inputs_from_db(
            subscenarios=subscenarios,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            conn=conn,
            op_type=op_type,
        )
    )
    if df.empty:
        return

    value_cols = ["min_budget_fraction", "max_budget_fraction"]
    idx_cols = ["project", "balancing_type_horizon", "horizon"]

    def write(severity, errors):
        write_validation_to_database(
            conn=conn,
            scenario_id=scenario_id,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem_id=subproblem,
            stage_id=stage,
            gridpath_module=__name__,
            db_table=HYDRO_BUDGET_ALLOCATION_TABLE,
            severity=severity,
            errors=errors,
        )

    write("Low", validate_values(df, value_cols, idx_col=idx_cols, min=0, max=1))
    write("Mid", validate_column_monotonicity(df, value_cols, idx_col=idx_cols))

    # Nesting: each sub-horizon must be of a balancing type other than the
    # project's own, and its timepoints must map to exactly one horizon of
    # the project's energy-budget balancing type. The sub-horizons to check
    # come from the already-queried df, NOT the raw table: df's rows are
    # scoped by subscenario ID and iteration and, with a
    # hydro_budget_allocation_hrz_map_scenario_id assigned, carry the
    # model's own horizons rather than the raw data horizons (which may not
    # exist in this temporal scenario at all)
    sub_horizons = [
        (str(prj), str(bt), int(hrz))
        for prj, bt, hrz in df[idx_cols].drop_duplicates().itertuples(index=False)
    ]
    sub_relation_sql = " UNION ALL ".join(
        ["SELECT ? AS project, ? AS balancing_type_horizon, ? AS horizon"]
        + ["SELECT ?, ?, ?"] * (len(sub_horizons) - 1)
    )
    c = conn.cursor()
    parent_rows = c.execute(
        f"""
        SELECT sub.project, sub.balancing_type_horizon, sub.horizon,
            COALESCE(opchar.energy_budget_balancing_type,
                opchar.balancing_type_project),
            COUNT(DISTINCT parent.horizon) AS n_parents,
            MIN(parent.horizon) AS parent_horizon,
            COUNT(DISTINCT sub_tmps.timepoint) AS n_sub_tmps
        FROM ({sub_relation_sql}) AS sub
        JOIN inputs_project_operational_chars AS opchar
            ON opchar.project = sub.project
            AND opchar.project_operational_chars_scenario_id =
                {subscenarios.PROJECT_OPERATIONAL_CHARS_SCENARIO_ID}
        JOIN inputs_temporal_horizon_timepoints AS sub_tmps
            ON sub_tmps.temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND sub_tmps.subproblem_id = {subproblem}
            AND sub_tmps.stage_id = {stage}
            AND sub_tmps.balancing_type_horizon = sub.balancing_type_horizon
            AND sub_tmps.horizon = sub.horizon
        LEFT JOIN inputs_temporal_horizon_timepoints AS parent
            ON parent.temporal_scenario_id = sub_tmps.temporal_scenario_id
            AND parent.subproblem_id = sub_tmps.subproblem_id
            AND parent.stage_id = sub_tmps.stage_id
            AND parent.timepoint = sub_tmps.timepoint
            AND parent.balancing_type_horizon = COALESCE(opchar.energy_budget_balancing_type,
                opchar.balancing_type_project)
        GROUP BY sub.project, sub.balancing_type_horizon, sub.horizon,
            COALESCE(opchar.energy_budget_balancing_type,
                opchar.balancing_type_project)
        """,
        [value for row in sub_horizons for value in row],
    ).fetchall()
    parent_df = pd.DataFrame(
        parent_rows,
        columns=idx_cols
        + ["energy_budget_balancing_type", "n_parents", "parent_horizon", "n_sub_tmps"],
    )
    df = df.merge(parent_df, on=idx_cols, how="left")
    same_bt = df["balancing_type_horizon"] == df["energy_budget_balancing_type"]
    write(
        "High",
        (
            [
                f"project(s) {sorted(df[same_bt]['project'].unique())}: hydro budget "
                f"allocation limits {df[same_bt][idx_cols].values.tolist()} are "
                f"specified for horizons of the project's energy-budget balancing type; "
                f"they must refer to sub-horizons of a different balancing type."
            ]
            if same_bt.any()
            else []
        ),
    )
    not_nested = df[~same_bt & (df["n_parents"].fillna(0) != 1)]
    write(
        "High",
        (
            [
                f"project(s) {sorted(not_nested['project'].unique())}: hydro budget "
                f"allocation sub-horizons {not_nested[idx_cols].values.tolist()} "
                f"are not nested within a single horizon of the project's "
                f"balancing type."
            ]
            if not not_nested.empty
            else []
        ),
    )

    # Share sums are only meaningful where the sub-horizons cover the whole
    # parent horizon, as the budget applies to all of its timepoints
    parent_tmp_counts = pd.DataFrame(
        c.execute(f"""
            SELECT balancing_type_horizon, horizon,
                COUNT(DISTINCT timepoint) AS n_parent_tmps
            FROM inputs_temporal_horizon_timepoints
            WHERE temporal_scenario_id = {subscenarios.TEMPORAL_SCENARIO_ID}
            AND subproblem_id = {subproblem}
            AND stage_id = {stage}
            GROUP BY balancing_type_horizon, horizon
        """).fetchall(),
        columns=["energy_budget_balancing_type", "parent_horizon", "n_parent_tmps"],
    )
    nested = df[~same_bt & (df["n_parents"] == 1)].merge(
        parent_tmp_counts,
        on=["energy_budget_balancing_type", "parent_horizon"],
        how="left",
    )
    share_sums = nested.groupby(["project", "parent_horizon"]).agg(
        min_sum=("min_budget_fraction", lambda x: x.fillna(0).sum()),
        max_sum=("max_budget_fraction", "sum"),
        n_max_missing=("max_budget_fraction", lambda x: x.isna().sum()),
        n_sub_tmps=("n_sub_tmps", "sum"),
        n_parent_tmps=("n_parent_tmps", "first"),
    )
    covers_parent = share_sums["n_sub_tmps"] == share_sums["n_parent_tmps"]
    over = share_sums[covers_parent & (share_sums["min_sum"] > 1 + 1e-9)]
    under = share_sums[
        covers_parent
        & (share_sums["n_max_missing"] == 0)
        & (share_sums["max_sum"] < 1 - 1e-9)
    ]
    errors = []
    if not over.empty:
        errors.append(
            f"project-horizon(s) {over.index.tolist()}: hydro budget allocation "
            f"minimum shares sum to more than 1."
        )
    if not under.empty:
        errors.append(
            f"project-horizon(s) {under.index.tolist()}: hydro budget allocation "
            f"maximum shares sum to less than 1."
        )
    write("Low", errors)


def export_hydro_budget_allocation_results(
    mod,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    op_type,
    component_prefix,
):
    """
    Write the *op_type* projects' sub-horizon energy, parent-horizon budget,
    realized share, limits, and constraint duals to
    results/{op_type}_budget_allocation.csv (nothing is written if no
    project of this type has allocation limits). A skipped constraint has
    no dual; so does a run with --skip_duals, or a MIP.
    """
    alloc_set = getattr(mod, f"{op_type.upper()}_BUDGET_ALLOC_BT_HRZS")
    if len(alloc_set) == 0:
        return

    min_frac = getattr(mod, f"{op_type}_budget_alloc_min_fraction")
    max_frac = getattr(mod, f"{op_type}_budget_alloc_max_fraction")
    parent_hrz = getattr(mod, f"{op_type}_budget_alloc_parent_hrz")
    energy = getattr(mod, f"{component_prefix}_Budget_Alloc_Energy_MWh")
    budget = getattr(mod, f"{component_prefix}_Parent_Hrz_Energy_Budget_MWh")
    budget_bt_param = getattr(mod, f"{op_type}_energy_budget_balancing_type")
    min_constraint = getattr(mod, f"{component_prefix}_Budget_Alloc_Min_Constraint")
    max_constraint = getattr(mod, f"{component_prefix}_Budget_Alloc_Max_Constraint")

    results_file = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "results",
        get_hydro_budget_allocation_results_file_name(op_type),
    )
    with open(results_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HYDRO_BUDGET_ALLOCATION_RESULTS_COLUMNS)
        for idx in sorted(alloc_set):
            prj, sub_bt, sub_hrz = idx
            bt = get_energy_budget_balancing_type(mod, prj, budget_bt_param)
            energy_mwh = value(energy[idx])
            budget_mwh = value(budget[prj, bt, parent_hrz[idx]])
            writer.writerow(
                [
                    prj,
                    sub_bt,
                    sub_hrz,
                    bt,
                    parent_hrz[idx],
                    min_frac[idx] if idx in min_frac else None,
                    max_frac[idx] if idx in max_frac else None,
                    energy_mwh,
                    budget_mwh,
                    energy_mwh / budget_mwh if budget_mwh else None,
                    (
                        duals_wrapper(mod, min_constraint[idx])
                        if idx in min_constraint
                        else None
                    ),
                    (
                        duals_wrapper(mod, max_constraint[idx])
                        if idx in max_constraint
                        else None
                    ),
                ]
            )


def import_hydro_budget_allocation_results_into_database(
    scenario_id,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    conn,
    cursor,
    results_directory,
    quiet,
    op_type,
):
    """
    Import the *op_type* projects' energy-budget allocation results into the
    shared results_project_hydro_budget_allocation table. Both hydro
    operational types write their own CSV and append to that one table.
    """
    import_csv(
        conn=conn,
        cursor=cursor,
        scenario_id=scenario_id,
        weather_iteration=weather_iteration,
        hydro_iteration=hydro_iteration,
        availability_iteration=availability_iteration,
        subproblem=subproblem,
        stage=stage,
        quiet=quiet,
        results_directory=results_directory,
        which_results=get_hydro_budget_allocation_results_file_name(op_type).replace(
            ".csv", ""
        ),
        results_table=HYDRO_BUDGET_ALLOCATION_RESULTS_TABLE,
    )
