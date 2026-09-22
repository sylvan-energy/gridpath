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
Default storage durations for unrated storage units.

EIA-860 reports no ``energy_storage_capacity_mwh`` for many storage units
that are not yet operating (and for some that are), so a unit's energy
capacity can be missing exactly where a study-year fleet needs it most —
the planned and under-construction units. The specified-capacity steps
sum energy over the units that have a value, which silently understates
an aggregated project's ``specified_stor_capacity_mwh`` whenever SOME of
its units are unrated (and leaves it NULL only when ALL are — the NULL
then fails at GridPath model load, but the understated value runs and
silently shortens every battery in the zone).

The remedy lives here and is applied PER UNIT, in the steps that still
see units: each in-fleet storage unit with a NULL energy rating gets
``duration × capacity_mw`` from the ``default_battery_duration_hours``
(prime mover 'BA') and ``default_pumped_storage_duration_hours`` ('PS')
settings; rated units are never changed, and a zero MWh rating is a
rating, not a gap. Unset settings mean no fill. The fleet audit uses the
same settings to label each storage unit's energy source ('filed' /
'default_duration' / 'missing'), and
:func:`report_default_storage_duration_fill` prints what a run filled —
plus a loud warning for projects whose energy capacity is then mostly
assumption.
"""

import pandas as pd

# The prime movers whose energy_storage_capacity_mwh rides into
# specified_stor_capacity_mwh: batteries, other energy storage,
# flywheels, pumped storage
STORAGE_PRIME_MOVERS = ("BA", "ES", "FW", "PS")

# The prime movers a default-duration setting exists for, and the setting
# that fills each — single-sourced so the argument helper, the fill
# expression, and the audit's source label can't drift
DEFAULT_DURATION_SETTINGS = {
    "BA": "default_battery_duration_hours",
    "PS": "default_pumped_storage_duration_hours",
}

# A project mostly made of unrated units has a mostly-assumed duration —
# warn above this filled share of its storage capacity
FILLED_SHARE_WARNING_THRESHOLD = 0.5


def add_default_storage_duration_arguments(parser):
    """
    Add the default-storage-duration arguments —
    ``--default_battery_duration_hours`` and
    ``--default_pumped_storage_duration_hours`` — to a step's argument
    parser. Single-sourced here (like add_fleet_selection_arguments) so
    the settings and their --help texts can't drift across the steps that
    take them (the two specified-capacity steps and the fleet audit);
    they must be set consistently across those steps for the audit's
    ``energy_mwh_source`` labels to describe the generated capacity CSV.
    """
    parser.add_argument(
        "-ba_dur",
        "--default_battery_duration_hours",
        default=None,
        help="Assume this duration (hours) for every in-fleet battery "
        "(prime mover 'BA') with no EIA-reported energy capacity: the "
        "unit contributes duration × capacity_mw to its project's "
        "specified_stor_capacity_mwh. Units WITH a reported energy "
        "capacity — including a reported zero — are never changed. Unset "
        "(the default) means no fill: unrated units contribute no energy "
        "capacity, so an aggregated project with some unrated units is "
        "understated and a fully-unrated one comes out empty.",
    )
    parser.add_argument(
        "-ps_dur",
        "--default_pumped_storage_duration_hours",
        default=None,
        help="Assume this duration (hours) for every in-fleet "
        "pumped-storage unit (prime mover 'PS') with no EIA-reported "
        "energy capacity, as with --default_battery_duration_hours.",
    )


def get_default_durations_from_args(parsed_args):
    """
    The default durations a step's parsed arguments request, as a
    {prime mover: hours} dict with only the set ones. Call before
    connecting: it validates the settings (which arrive as strings from a
    settings CSV) — a non-numeric or non-positive duration raises.
    """
    durations = {}
    for prime_mover, setting in DEFAULT_DURATION_SETTINGS.items():
        value = getattr(parsed_args, setting, None)
        if value is not None:
            try:
                value = float(value)
            except ValueError:
                raise ValueError(f"{setting} must be a number of hours, got {value!r}.")
            if value <= 0:
                raise ValueError(f"{setting} must be positive, got {value}.")
            durations[prime_mover] = value

    return durations


def get_specified_stor_capacity_mwh_expr(generators_table, default_durations):
    """
    The per-unit ``specified_stor_capacity_mwh`` SQL expression: the
    unit's ``energy_storage_capacity_mwh`` for the storage prime movers
    (NULL for everything else), with unrated units filled as
    ``duration × capacity_mw`` for the prime movers *default_durations*
    covers. With no durations set this is exactly the unfilled
    expression. The specified-capacity steps SUM it per project in their
    aggregated mode, so the fill lands per unit — a partially-rated
    project gets its rated units' sum plus the default for the rest.
    """
    storage_pm_sql = ", ".join(f"'{pm}'" for pm in STORAGE_PRIME_MOVERS)
    fill_branches = "".join(
        f"""
            WHEN energy_storage_capacity_mwh IS NULL
                AND {generators_table}.prime_mover_code = '{prime_mover}'
                THEN {duration} * capacity_mw"""
        for prime_mover, duration in default_durations.items()
    )

    return f"""CASE
            WHEN {generators_table}.prime_mover_code
                NOT IN ({storage_pm_sql}) THEN NULL{fill_branches}
            ELSE energy_storage_capacity_mwh
        END"""


def get_energy_mwh_source_expr(generators_table, default_durations):
    """
    The fleet audit's ``energy_mwh_source`` SQL expression, labeling
    where each storage unit's energy capacity comes from under the given
    default-duration settings: 'filed' (EIA-reported, zero included),
    'default_duration' (unrated, a default fills it), or 'missing'
    (unrated with no default set — the project value stays understated
    or NULL). NULL for non-storage prime movers.
    """
    storage_pm_sql = ", ".join(f"'{pm}'" for pm in STORAGE_PRIME_MOVERS)
    filled_branch = ""
    if default_durations:
        filled_pm_sql = ", ".join(f"'{pm}'" for pm in default_durations)
        filled_branch = f"""
            WHEN {generators_table}.prime_mover_code IN ({filled_pm_sql})
                THEN 'default_duration'"""

    return f"""CASE
            WHEN {generators_table}.prime_mover_code
                NOT IN ({storage_pm_sql}) THEN NULL
            WHEN energy_storage_capacity_mwh IS NOT NULL
                THEN 'filed'{filled_branch}
            ELSE 'missing'
        END"""


def report_default_storage_duration_fill(
    conn, project_name_str, fleet_relation_sql, default_durations, generators_table
):
    """
    Print what the default-duration fill did — unrated units and MW
    filled, MWh added — and warn about projects where the filled share of
    the storage capacity exceeds :data:`FILLED_SHARE_WARNING_THRESHOLD`,
    since such a project's duration is then mostly an assumption. Prints
    regardless of any quiet setting, by design: the fill substitutes an
    assumption for filed data, so it must be visible in every run. A
    no-op when no default duration is set.
    """
    if not default_durations:
        return

    duration_case = (
        "CASE "
        + " ".join(
            f"WHEN {generators_table}.prime_mover_code = '{prime_mover}' "
            f"THEN {duration}"
            for prime_mover, duration in default_durations.items()
        )
        + " END"
    )
    filled_pm_sql = ", ".join(f"'{pm}'" for pm in default_durations)
    unrated = "energy_storage_capacity_mwh IS NULL"
    sql = f"""
        SELECT {project_name_str} AS project,
            SUM(capacity_mw) AS storage_mw,
            SUM(CASE WHEN {unrated} THEN 1 ELSE 0 END) AS unrated_units,
            SUM(CASE WHEN {unrated} THEN capacity_mw ELSE 0 END)
                AS unrated_mw,
            SUM(CASE WHEN {unrated} THEN {duration_case} * capacity_mw
                ELSE 0 END) AS filled_mwh
        {fleet_relation_sql}
        AND {generators_table}.prime_mover_code IN ({filled_pm_sql})
        GROUP BY project
        ;
    """
    fill_df = pd.read_sql(sql, conn)

    filled = fill_df[fill_df["unrated_units"] > 0]
    print(
        f"Default storage durations filled {int(filled['unrated_units'].sum())} "
        f"unrated units ({round(filled['unrated_mw'].sum())} MW) in "
        f"{len(filled)} projects: {round(filled['filled_mwh'].sum())} MWh "
        f"added."
    )

    mostly_assumed = filled[
        filled["unrated_mw"] > FILLED_SHARE_WARNING_THRESHOLD * filled["storage_mw"]
    ]
    if not mostly_assumed.empty:
        project_shares = ", ".join(
            f"{row.project} ({row.unrated_mw / row.storage_mw:.0%})"
            for row in mostly_assumed.itertuples()
        )
        print(
            f"WARNING: more than "
            f"{FILLED_SHARE_WARNING_THRESHOLD:.0%} of the storage capacity "
            f"of the following project(s) has no filed energy rating, so "
            f"their energy capacity is mostly the default-duration "
            f"assumption: {project_shares}"
        )
