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

"""
Scenario characteristics in database.
"""

from collections import namedtuple
import copy
import os.path
import pandas as pd
from pathlib import Path
from typing import Dict, Union

from gridpath.auxiliary.auxiliary import (
    check_for_integer_subdirectories,
    check_for_starting_string_subdirectories,
)
from gridpath.common_functions import ensure_empty_string

# TODO: conslidate use 0s and 1s to indicate no subdirectories?


class OptionalFeatures(object):
    def __init__(self, conn, scenario_id):
        """
        :param cursor:
        :param scenario_id:
        """
        of_column_names = [
            n for n in get_scenario_table_columns(conn=conn) if n.startswith("of_")
        ]

        for of in of_column_names:
            setattr(
                self,
                of.upper(),
                db_column_to_self(column=of, conn=conn, scenario_id=scenario_id),
            )

    def get_all_available_features(self):
        all_features = [attr[3:].lower() for attr, value in self.__dict__.items()]

        return all_features

    def get_active_features(self):
        """
        Get list of requested features
        :return:
        """
        active_features = list()

        for attr, value in self.__dict__.items():
            if value:
                active_features.append(attr[3:].lower())

        return active_features


class SubScenarios(object):
    """
    The subscenario IDs will be used to format SQL queries, so we set them to
    "NULL" (not None) if an ID is not specified for the scenario.
    """

    def __init__(self, conn, scenario_id):
        """

        :param cursor:
        :param scenario_id:
        """
        subscenario_column_names = [
            n
            for n in get_scenario_table_columns(conn=conn)
            if n.endswith("_scenario_id")
        ]

        for subscenario in subscenario_column_names:
            setattr(
                self,
                subscenario.upper(),
                db_column_to_self(
                    column=subscenario, conn=conn, scenario_id=scenario_id
                ),
            )

    def get_all_available_subscenarios(self):
        all_subscenarios = [
            attr.lower()
            for attr, value in self.__dict__.items()
            if attr != "SCENARIO_ID"
        ]

        return all_subscenarios


class ScenarioStructure(object):
    def __init__(
        self,
        weather_hydro_avail_subproblem_stage_dict,
        weather_iteration_flag,
        hydro_iteration_flag,
        availability_iteration_flag,
        subproblem_flag,
        stage_flag,
    ):
        # Weather, hydro, and availability iterations are the first three
        # levels, followed by subproblem and stage
        # {weather_iteration:
        #   {hydro_iteration:
        #       {availability_iterations:
        #           {subproblem: [stage]
        #           }
        #        }
        #    }
        # }
        # If no weather iterations, we're expecting a single key with 0 as value
        # If no hydro iterations, we're expecting a single key with 0 as value
        # If no availability itertions, we're expecting a list with 0 as member
        # [0]
        # No weather, no hydro, no availability: {0: {0: [0]}}
        # List of stages by subproblem in dict within each iteration
        # combination in a dictionary format {subproblem: [stages]}
        # This should have a single key, 1, if a single subproblem
        # This should be subproblem: [1] when a single stage in the subproblem
        self.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT = (
            weather_hydro_avail_subproblem_stage_dict
        )

        self.WEATHER_ITERATION_FLAG = weather_iteration_flag
        self.HYDRO_ITERATION_FLAG = hydro_iteration_flag
        self.AVAILABILITY_ITERATION_FLAG = availability_iteration_flag
        self.SUBPROBLEM_FLAG = subproblem_flag
        self.STAGE_FLAG = stage_flag

        # For determining whether we can parallelize
        self.N_SUBPROBLEMS = self.calculate_n_subproblems(
            weather_hydro_avail_subproblem_stage_dict=weather_hydro_avail_subproblem_stage_dict,
        )

    def calculate_n_subproblems(self, weather_hydro_avail_subproblem_stage_dict):
        # Total subproblems to determine parallelization
        n_subproblems = 0
        for w in weather_hydro_avail_subproblem_stage_dict.keys():
            for h in weather_hydro_avail_subproblem_stage_dict[w].keys():
                for a in weather_hydro_avail_subproblem_stage_dict[w][h].keys():
                    for s in weather_hydro_avail_subproblem_stage_dict[w][h][a].keys():
                        n_subproblems += 1

        return n_subproblems


class ScenarioDirectoryStructure(object):
    def __init__(self, scenario_structure):
        self.SCENARIO_DIRECTORY_STRUCTURE = (
            determine_directory_structure_from_scenario_structure(scenario_structure)
        )


def determine_directory_structure_from_scenario_structure(scenario_structure):
    """
    Determine whether we will have iteration (weather, hydro iteration),
    We write the subdirectories if we have multiple items at that level
    """

    iteration_directory_strings_dict = {}
    for w in scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT.keys():
        w_string = (
            f"weather_iteration_{w}"
            if scenario_structure.WEATHER_ITERATION_FLAG
            else ""
        )
        iteration_directory_strings_dict[w_string] = {}
        for h in scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[w].keys():
            h_string = (
                f"hydro_iteration_{h}"
                if (scenario_structure.HYDRO_ITERATION_FLAG)
                else ""
            )
            iteration_directory_strings_dict[w_string][h_string] = {}
            for a in scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[w][
                h
            ].keys():
                a_string = (
                    f"availability_iteration_{a}"
                    if (scenario_structure.AVAILABILITY_ITERATION_FLAG)
                    else ""
                )
                iteration_directory_strings_dict[w_string][h_string][a_string] = {}
                #     The subproblem structure is the same within each iteration
                #     If we only have a single subproblem AND it does not have stages, set the
                #     subproblem_string to an empty string (the subproblem directory should not
                #     have been created)
                #     If we have multiple subproblems or a single subproblems with stages,
                #     we're expecting a subproblem directory
                for (
                    subproblem
                ) in scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[w][h][
                    a
                ].keys():
                    subproblem_string = (
                        f"{subproblem}"
                        if (
                            scenario_structure.SUBPROBLEM_FLAG
                            or scenario_structure.STAGE_FLAG
                        )
                        else ""
                    )
                    iteration_directory_strings_dict[w_string][h_string][a_string][
                        subproblem_string
                    ] = []
                    for stage in (
                        scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT
                    )[w][h][a][subproblem]:
                        stage_string = (
                            f"{stage}" if (scenario_structure.STAGE_FLAG) else ""
                        )
                        iteration_directory_strings_dict[w_string][h_string][a_string][
                            subproblem_string
                        ].append(stage_string)

    return iteration_directory_strings_dict


def iterate_draws(scenario_structure):
    """
    :param scenario_structure: ScenarioStructure
    :return: generator of (weather_iteration, hydro_iteration,
        availability_iteration) keys, one per iteration "draw" of the
        scenario (a single (0, 0, 0) key when the scenario has no iteration
        levels)
    """
    for w in scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT.keys():
        for h in scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[w].keys():
            for a in scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[w][
                h
            ].keys():
                yield w, h, a


def validate_csv_structure_against_db(csv_structure, db_structure):
    """
    :param csv_structure: ScenarioStructure from a temporal-structure CSV
    :param db_structure: the scenario's database-derived ScenarioStructure
    :raises ValueError: if the CSV specifies draws or subproblems/stages
        that don't exist in the scenario's structure

    A temporal-structure CSV can only meaningfully NARROW the scenario's
    structure: iteration/subproblem/stage combinations outside it have no
    input data, so without this check they fail late -- at model load
    ("load not specified"-style errors) or as an import that finds nothing.
    """
    db_draws = set(iterate_draws(db_structure))
    # The database structure has the same subproblem/stage set for every
    # draw
    a_db_draw = next(iter(db_draws))
    db_subproblem_stages = {
        int(subproblem): {int(stage) for stage in stages}
        for subproblem, stages in db_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[
            a_db_draw[0]
        ][
            a_db_draw[1]
        ][
            a_db_draw[2]
        ].items()
    }

    unknown = []
    for draw in iterate_draws(csv_structure):
        if draw not in db_draws:
            unknown.append(
                f"draw (weather {draw[0]}, hydro {draw[1]}, availability {draw[2]})"
            )
            continue
        csv_subproblem_stages = csv_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[
            draw[0]
        ][draw[1]][draw[2]]
        for subproblem, stages in csv_subproblem_stages.items():
            if int(subproblem) not in db_subproblem_stages:
                unknown.append(f"subproblem {subproblem}")
                continue
            for stage in stages:
                if int(stage) not in db_subproblem_stages[int(subproblem)]:
                    unknown.append(f"subproblem {subproblem}, stage {stage}")

    if unknown:
        max_examples = 10
        examples = "; ".join(unknown[:max_examples])
        if len(unknown) > max_examples:
            examples += f"; ... and {len(unknown) - max_examples} more"
        raise ValueError(
            f"The temporal structure CSV specifies "
            f"iteration/subproblem/stage combinations that don't exist in "
            f"the scenario's structure: {examples}. The CSV can only narrow "
            f"the scenario's structure -- combinations outside it have no "
            f"input data."
        )


def get_diverging_layout_flags(csv_structure, db_structure):
    """
    :param csv_structure: ScenarioStructure from a temporal-structure CSV
    :param db_structure: the scenario's database-derived ScenarioStructure
    :return: list of human-readable descriptions of directory-layout flags
        on which the two structures diverge (empty if none)

    The CSV's directory-layout flags are derived from its values (see
    get_scenario_structure_from_csv), so a CSV narrowing a scenario to only
    subproblem/stage 1 implies a DIFFERENT directory layout than the
    scenario's own structure uses. That layout is self-consistent for a
    stand-alone run, but files generated with it will not line up with a
    directory tree (or archive tarballs) generated from the scenario's full
    structure. The iteration-level flags cannot diverge once the CSV has
    been validated against the database structure, so only the
    subproblem/stage flags are compared.
    """
    diverging = []
    if csv_structure.SUBPROBLEM_FLAG != db_structure.SUBPROBLEM_FLAG:
        diverging.append(
            f"subproblem directories ({'used' if csv_structure.SUBPROBLEM_FLAG else 'not used'} "
            f"per the CSV vs "
            f"{'used' if db_structure.SUBPROBLEM_FLAG else 'not used'} "
            f"per the scenario's structure)"
        )
    if csv_structure.STAGE_FLAG != db_structure.STAGE_FLAG:
        diverging.append(
            f"stage directories ({'used' if csv_structure.STAGE_FLAG else 'not used'} "
            f"per the CSV vs "
            f"{'used' if db_structure.STAGE_FLAG else 'not used'} "
            f"per the scenario's structure)"
        )

    return diverging


def resolve_requested_draw(
    scenario_structure, weather_iteration, hydro_iteration, availability_iteration
):
    """
    :param scenario_structure: ScenarioStructure
    :param weather_iteration: int; 0 means the scenario doesn't use the
        level (the same convention as inputs_temporal_iterations and the
        structure dictionaries)
    :param hydro_iteration: int
    :param availability_iteration: int
    :return: the validated (weather_iteration, hydro_iteration,
        availability_iteration) draw key

    Validate a user-requested iteration draw against the scenario's
    structure: every iteration level the scenario uses needs a (nonzero)
    iteration value, levels the scenario doesn't use must be given as 0,
    and the resulting draw must exist.
    """
    requested = {
        "weather": weather_iteration,
        "hydro": hydro_iteration,
        "availability": availability_iteration,
    }
    flags = {
        "weather": scenario_structure.WEATHER_ITERATION_FLAG,
        "hydro": scenario_structure.HYDRO_ITERATION_FLAG,
        "availability": scenario_structure.AVAILABILITY_ITERATION_FLAG,
    }

    for level, value in requested.items():
        if flags[level] and value == 0:
            raise ValueError(
                f"The scenario has {level} iterations, so a single draw "
                f"requires the draw's {level} iteration value (0 means the "
                f"level is not used)."
            )
        if not flags[level] and value != 0:
            raise ValueError(
                f"The scenario has no {level} iterations; pass 0 for the "
                f"{level} iteration value."
            )

    draw = (
        requested["weather"],
        requested["hydro"],
        requested["availability"],
    )
    if draw not in set(iterate_draws(scenario_structure)):
        raise ValueError(
            f"The scenario has no draw with weather iteration {draw[0]}, "
            f"hydro iteration {draw[1]}, availability iteration {draw[2]} "
            f"(0 = level not used)."
        )

    return draw


def build_single_draw_structure(
    scenario_structure, weather_iteration, hydro_iteration, availability_iteration
):
    """
    :param scenario_structure: ScenarioStructure
    :return: a new ScenarioStructure containing only the requested draw,
        with the same iteration/subproblem/stage flags

    The stage functions (write_model_inputs, run_scenario,
    import_scenario_results_into_database, cleanup_scenario_directory) all
    take their work specification from a ScenarioStructure, so a
    single-draw slice makes them operate on one draw at a time.
    """
    subproblem_stage_dict = (
        scenario_structure.WEATHER_HYDRO_AVAIL_SUBPROBLEM_STAGE_DICT[weather_iteration][
            hydro_iteration
        ][availability_iteration]
    )

    return ScenarioStructure(
        weather_hydro_avail_subproblem_stage_dict={
            weather_iteration: {
                hydro_iteration: {availability_iteration: subproblem_stage_dict}
            }
        },
        weather_iteration_flag=scenario_structure.WEATHER_ITERATION_FLAG,
        hydro_iteration_flag=scenario_structure.HYDRO_ITERATION_FLAG,
        availability_iteration_flag=scenario_structure.AVAILABILITY_ITERATION_FLAG,
        subproblem_flag=scenario_structure.SUBPROBLEM_FLAG,
        stage_flag=scenario_structure.STAGE_FLAG,
    )


# A single (weather iteration, hydro iteration, availability iteration,
# subproblem, stage) of the scenario directory structure: the directory-name
# strings ("" for levels not in use) and the corresponding integer values (0
# for levels not in use)
DirectoryStructureCell = namedtuple(
    "DirectoryStructureCell",
    [
        "weather_iteration_str",
        "hydro_iteration_str",
        "availability_iteration_str",
        "subproblem_str",
        "stage_str",
        "weather_iteration",
        "hydro_iteration",
        "availability_iteration",
        "subproblem",
        "stage",
    ],
)


def iterate_directory_structure(scenario_directory_structure):
    """
    :param scenario_directory_structure: the dictionary created by
        ScenarioDirectoryStructure
    :return: generator of DirectoryStructureCell

    Iterate over every (weather iteration, hydro iteration, availability
    iteration, subproblem, stage) of the scenario directory structure.
    """
    for weather_iteration_str in scenario_directory_structure.keys():
        for hydro_iteration_str in scenario_directory_structure[
            weather_iteration_str
        ].keys():
            for availability_iteration_str in scenario_directory_structure[
                weather_iteration_str
            ][hydro_iteration_str].keys():
                for subproblem_str in scenario_directory_structure[
                    weather_iteration_str
                ][hydro_iteration_str][availability_iteration_str].keys():
                    for stage_str in scenario_directory_structure[
                        weather_iteration_str
                    ][hydro_iteration_str][availability_iteration_str][subproblem_str]:
                        # We may have passed "empty_string" to avoid actual
                        # empty strings as dictionary keys; convert to actual
                        # empty strings here for directory-path purposes
                        w_str = ensure_empty_string(weather_iteration_str)
                        h_str = ensure_empty_string(hydro_iteration_str)
                        a_str = ensure_empty_string(availability_iteration_str)

                        yield DirectoryStructureCell(
                            weather_iteration_str=w_str,
                            hydro_iteration_str=h_str,
                            availability_iteration_str=a_str,
                            subproblem_str=subproblem_str,
                            stage_str=stage_str,
                            weather_iteration=(
                                0
                                if w_str == ""
                                else int(w_str.replace("weather_iteration_", ""))
                            ),
                            hydro_iteration=(
                                0
                                if h_str == ""
                                else int(h_str.replace("hydro_iteration_", ""))
                            ),
                            availability_iteration=(
                                0
                                if a_str == ""
                                else int(a_str.replace("availability_iteration_", ""))
                            ),
                            subproblem=(
                                0 if subproblem_str == "" else int(subproblem_str)
                            ),
                            stage=0 if stage_str == "" else int(stage_str),
                        )


def get_scenario_structure_from_db(conn, scenario_id):
    """

    :param conn:
    :param scenario_id:
    """
    cursor = conn.cursor()

    # Iterations
    iterations_query = f"""SELECT weather_iteration, 
        hydro_iteration, availability_iteration
               FROM inputs_temporal_iterations
               INNER JOIN scenarios
               USING (temporal_scenario_id)
               WHERE scenario_id = {scenario_id};"""

    iter_df = pd.read_sql(iterations_query, conn)

    if iter_df.empty:
        weather_hydro_avail_subproblem_stage_dict = {0: {0: {0: None}}}
        weather_iteration_flag = False
        hydro_iteration_flag = False
        availability_iteration_flag = False
    else:
        weather_hydro_avail_subproblem_stage_dict = {}
        for row in iter_df.itertuples():
            ix, weather_iteration, hydro_iteration, availability_iteration = row
            if (
                weather_iteration
                not in weather_hydro_avail_subproblem_stage_dict.keys()
            ):
                weather_hydro_avail_subproblem_stage_dict[weather_iteration] = {}
            if (
                hydro_iteration
                not in weather_hydro_avail_subproblem_stage_dict[
                    weather_iteration
                ].keys()
            ):
                weather_hydro_avail_subproblem_stage_dict[weather_iteration][
                    hydro_iteration
                ] = {}
            weather_hydro_avail_subproblem_stage_dict[weather_iteration][
                hydro_iteration
            ][availability_iteration] = None

        weather_iterations = get_distinct_iterations_from_db(
            conn, scenario_id, "weather_iteration"
        )
        weather_iteration_flag = (
            False
            if (len(weather_iterations) == 1 and weather_iterations[0] == 0)
            else True
        )

        hydro_iterations = get_distinct_iterations_from_db(
            conn, scenario_id, "hydro_iteration"
        )
        hydro_iteration_flag = (
            False if (len(hydro_iterations) == 1 and hydro_iterations[0] == 0) else True
        )

        availability_iterations = get_distinct_iterations_from_db(
            conn, scenario_id, "availability_iteration"
        )
        availability_iteration_flag = (
            False
            if (len(availability_iterations) == 1 and availability_iterations[0] == 0)
            else True
        )

    # TODO: make sure there is data integrity between subproblems_stages
    #   and inputs_temporal_horizons and inputs_temporal
    # TODO: probably don't need a separate table for subproblems, but can get
    #  the subproblems from the subproblems_stages table
    all_subproblems = [
        subproblem[0] for subproblem in cursor.execute("""SELECT subproblem_id
               FROM inputs_temporal_subproblems
               INNER JOIN scenarios
               USING (temporal_scenario_id)
               WHERE scenario_id = {};""".format(scenario_id)).fetchall()
    ]
    subproblem_flag = False if len(all_subproblems) == 1 else True

    # Store subproblems and stages in dict {subproblem: [stages]}
    stages_by_subproblem = {}
    for subproblem in all_subproblems:
        stages = cursor.execute(f"""SELECT stage_id
               FROM inputs_temporal_subproblems_stages
               INNER JOIN scenarios
               USING (temporal_scenario_id)
               WHERE scenario_id = {scenario_id}
               AND subproblem_id = {subproblem}
               ;""").fetchall()
        stages = [stage[0] for stage in stages]  # convert to simple list
        stages_by_subproblem[subproblem] = stages

    # Assuming the same for all subproblems
    stage_flag = (
        False
        if len(stages_by_subproblem[next(iter(stages_by_subproblem))]) == 1
        else True
    )

    # Assumes same subproblems/stages for each iteration combo
    for w_it in weather_hydro_avail_subproblem_stage_dict.keys():
        for h_it in weather_hydro_avail_subproblem_stage_dict[w_it].keys():
            for ave_it in weather_hydro_avail_subproblem_stage_dict[w_it][h_it].keys():
                weather_hydro_avail_subproblem_stage_dict[w_it][h_it][
                    ave_it
                ] = stages_by_subproblem

    return ScenarioStructure(
        weather_hydro_avail_subproblem_stage_dict=weather_hydro_avail_subproblem_stage_dict,
        weather_iteration_flag=weather_iteration_flag,
        hydro_iteration_flag=hydro_iteration_flag,
        availability_iteration_flag=availability_iteration_flag,
        subproblem_flag=subproblem_flag,
        stage_flag=stage_flag,
    )


def get_scenario_structure_from_csv(csv_path):
    """
    :param csv_path: path to a CSV with columns weather_iteration,
        hydro_iteration, availability_iteration, subproblem, stage -- one
        row per subproblem/stage to include (0 for iteration levels the
        scenario doesn't use; subproblem/stage 1 when not used)
    :return: ScenarioStructure

    Build the scenario structure from a CSV instead of the database -- used
    with --temporal_structure_csv_overwrite to run/import an arbitrary
    subset of a scenario's iteration/subproblem/stage cells (e.g.
    gridpath_iterate's conditions-only re-runs). This function itself takes
    the rows as given (it has no database connection); the consuming entry
    points validate them against the scenario's database-derived structure
    with validate_csv_structure_against_db. The directory-layout
    flags are DERIVED from the values: an iteration level is "in use" if
    any of its values is nonzero, subproblems/stages if any value isn't 1.
    Note the implication: a CSV that narrows a multi-subproblem scenario
    down to subproblem 1 only yields a no-subproblem-directory layout,
    which will not line up with the scenario's existing directories --
    include a different subproblem, or use get_scenario_inputs'
    --single_draw option (which preserves the scenario's flags) when the
    goal is one iteration draw.
    """

    df = pd.read_csv(csv_path)

    if df.empty:
        weather_hydro_avail_subproblem_stage_dict = {0: {0: {0: {1: [1]}}}}
        weather_iteration_flag = False
        hydro_iteration_flag = False
        availability_iteration_flag = False
        subproblem_flag = False
        stage_flag = False
    else:
        weather_hydro_avail_subproblem_stage_dict = {}
        for row in df.itertuples():
            (
                ix,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            ) = row
            if (
                weather_iteration
                not in weather_hydro_avail_subproblem_stage_dict.keys()
            ):
                weather_hydro_avail_subproblem_stage_dict[weather_iteration] = {}
            if (
                hydro_iteration
                not in weather_hydro_avail_subproblem_stage_dict[
                    weather_iteration
                ].keys()
            ):
                weather_hydro_avail_subproblem_stage_dict[weather_iteration][
                    hydro_iteration
                ] = {}
            if (
                availability_iteration
                not in weather_hydro_avail_subproblem_stage_dict[weather_iteration][
                    hydro_iteration
                ].keys()
            ):
                weather_hydro_avail_subproblem_stage_dict[weather_iteration][
                    hydro_iteration
                ][availability_iteration] = {}
            if (
                subproblem
                not in weather_hydro_avail_subproblem_stage_dict[weather_iteration][
                    hydro_iteration
                ][availability_iteration].keys()
            ):
                weather_hydro_avail_subproblem_stage_dict[weather_iteration][
                    hydro_iteration
                ][availability_iteration][subproblem] = [stage]
            else:
                weather_hydro_avail_subproblem_stage_dict[weather_iteration][
                    hydro_iteration
                ][availability_iteration][subproblem].append(stage)

        weather_iteration_flag = (
            True if any(w != 0 for w in list(df["weather_iteration"])) else False
        )

        hydro_iteration_flag = (
            True if any(w != 0 for w in list(df["hydro_iteration"])) else False
        )
        availability_iteration_flag = (
            True if any(w != 0 for w in list(df["availability_iteration"])) else False
        )
        subproblem_flag = True if any(w != 1 for w in list(df["subproblem"])) else False
        stage_flag = True if any(w != 1 for w in list(df["stage"])) else False

    return ScenarioStructure(
        weather_hydro_avail_subproblem_stage_dict=weather_hydro_avail_subproblem_stage_dict,
        weather_iteration_flag=weather_iteration_flag,
        hydro_iteration_flag=hydro_iteration_flag,
        availability_iteration_flag=availability_iteration_flag,
        subproblem_flag=subproblem_flag,
        stage_flag=stage_flag,
    )


def get_distinct_iterations_from_db(conn, scenario_id, iteration_type):
    c = conn.cursor()
    iterations = [i[0] for i in c.execute(f"""SELECT DISTINCT 
    {iteration_type}
                   FROM inputs_temporal_iterations
                   INNER JOIN scenarios
                   USING (temporal_scenario_id)
                   WHERE scenario_id = {scenario_id};""").fetchall()]
    return iterations


def get_scenario_structure_from_disk(scenario_directory):

    # Iterate through items in the scenario_directory and create a nested
    # dictionary of the directory structure
    # Limit to five levels (weather, hydro, availability, subproblem, stage)
    # We'll then parse this dictionary to understand which levels exist
    level_start = 1
    max_level = 5
    dir_structure_from_disk = dir_to_nested_dict(
        Path(scenario_directory), level_start, max_level
    )

    # First, reverse engineer the directory structure that was sent to the
    # scenario
    # We need empty strings for layers that do not exist
    # We'll start with what we got from disk
    dir_structure_start = copy.deepcopy(dir_structure_from_disk)

    # Check if we have a weather iteration level; if we don't, add the level
    # with a single key weather_iteration_0
    if not check_dict_key_for_string_recursive(
        dir_structure_from_disk, "weather_iteration_"
    ):
        weather_iteration_flag = False
        dir_structure_w_weather = {
            "weather_iteration_0": copy.deepcopy(dir_structure_start)
        }
    else:
        weather_iteration_flag = True
        dir_structure_w_weather = copy.deepcopy(dir_structure_start)

    # Check if we have a hydro iteration level; if we don't, add the level
    # with a single hydro_iteration_0 under each weather iteration key
    if not check_dict_key_for_string_recursive(
        dir_structure_from_disk, "hydro_iteration_"
    ):
        hydro_iteration_flag = False
        dir_structure_w_weather_hydro = {}
        for w in dir_structure_w_weather.keys():
            dir_structure_w_weather_hydro[w] = {}
            dir_structure_w_weather_hydro[w]["hydro_iteration_0"] = copy.deepcopy(
                dir_structure_w_weather
            )[w]
    else:
        hydro_iteration_flag = True
        dir_structure_w_weather_hydro = copy.deepcopy(dir_structure_w_weather)

    # Check if we have an availability iteration level; if we don't, add the level
    # with a single availability_iteration_0 under each weather/hydro iteration
    # key
    if not check_dict_key_for_string_recursive(
        dir_structure_from_disk, "availability_iteration_"
    ):
        availability_iteration_flag = False
        dir_structure_w_weather_hydro_av = {}
        for w in dir_structure_w_weather_hydro.keys():
            dir_structure_w_weather_hydro_av[w] = {}
            for h in dir_structure_w_weather_hydro[w].keys():
                dir_structure_w_weather_hydro_av[w][h] = {}
                dir_structure_w_weather_hydro_av[w][h]["availability_iteration_0"] = (
                    copy.deepcopy(dir_structure_w_weather_hydro[w][h])
                )
    else:
        availability_iteration_flag = True
        dir_structure_w_weather_hydro_av = copy.deepcopy(dir_structure_w_weather_hydro)

    # Iteration layers
    iteration_layers_n = sum(
        [weather_iteration_flag, hydro_iteration_flag, availability_iteration_flag]
    )
    dir_structure_depth = get_dictionary_depth(dir_structure_from_disk) - 1
    non_iteration_layers_n = dir_structure_depth - iteration_layers_n

    # Finally, figure out the subproblem/stage structure from the non-iteration
    # layers
    # 0 - no subproblems exist, add the levels as {1:[1]}
    # 1 - subproblems exist or single subproblem with stages if there
    # is a passthrough directory
    # 2 - subproblems and stages exist
    if non_iteration_layers_n == 0:
        subproblem_flag = False
        stage_flag = False
        for w in dir_structure_w_weather_hydro_av.keys():
            for h in dir_structure_w_weather_hydro_av[w].keys():
                for a in dir_structure_w_weather_hydro_av[w][h].keys():
                    dir_structure_w_weather_hydro_av[w][h][a] = {1: [1]}
    elif non_iteration_layers_n == 1:
        # If stages, add the subproblem
        txt_file_for_stage_flag = os.path.join(
            scenario_directory, "multi_stage_flag.txt"
        )
        if os.path.exists(txt_file_for_stage_flag):
            with open(txt_file_for_stage_flag) as f:
                with open(txt_file_for_stage_flag) as f:
                    check_true = f.read()
                    if check_true != "True":
                        raise ValueError(
                            "ERROR: Scenario directory structure appears to have "
                            "stages but the multi_stage_flag.txt file is not set "
                            "to True, indicating an upstream error in handling "
                            "the scenario structure."
                        )

            subproblem_flag = False
            stage_flag = True
            for w in dir_structure_w_weather_hydro_av.keys():
                for h in dir_structure_w_weather_hydro_av[w].keys():
                    for a in dir_structure_w_weather_hydro_av[w][h].keys():
                        dir_structure_w_weather_hydro_av[w][h][a] = {
                            1: list(dir_structure_w_weather_hydro_av[w][h][a].keys())
                        }
        # If no stages, add them
        else:
            subproblem_flag = True
            stage_flag = False
            for w in dir_structure_w_weather_hydro_av.keys():
                for h in dir_structure_w_weather_hydro_av[w].keys():
                    for a in dir_structure_w_weather_hydro_av[w][h].keys():
                        for subproblem in dir_structure_w_weather_hydro_av[w][h][
                            a
                        ].keys():
                            dir_structure_w_weather_hydro_av[w][h][a][subproblem] = [1]
    elif non_iteration_layers_n == 2:
        txt_file_for_stage_flag = os.path.join(
            scenario_directory, "multi_stage_flag.txt"
        )
        if os.path.exists(txt_file_for_stage_flag):
            with open(txt_file_for_stage_flag) as f:
                check_true = f.read()
                if check_true != "True":
                    raise ValueError(
                        "ERROR: Scenario directory structure appears to have "
                        "stages but the multi_stage_flag.txt file is not set "
                        "to True, indicating an upstream error in handling "
                        "the scenario structure."
                    )
        else:
            raise ValueError(
                "ERROR: Scenario directory structure appears to have "
                "stages but the multi_stage_flag.txt does not exist, "
                "indicating an upstream error in handling the scenario "
                "structure."
            )
        subproblem_flag = True
        stage_flag = True
        for w in dir_structure_w_weather_hydro_av.keys():
            for h in dir_structure_w_weather_hydro_av[w].keys():
                for a in dir_structure_w_weather_hydro_av[w][h].keys():
                    for subproblem in dir_structure_w_weather_hydro_av[w][h][a].keys():
                        dir_structure_w_weather_hydro_av[w][h][a][subproblem] = list(
                            dir_structure_w_weather_hydro_av[w][h][a][subproblem].keys()
                        )
    else:
        raise ValueError(
            "ERROR: Scenario directory structure is not supported. "
            "The number of non-iteration layers must be 0, 1, or 2."
        )

    # Remove the starting strings for the iteration levels and make the final
    # dictionary
    weather_hydro_avail_subproblem_stage_dict_final = {}
    for w in dir_structure_w_weather_hydro_av.keys():
        w_int = int(w.replace(f"weather_iteration_", ""))
        weather_hydro_avail_subproblem_stage_dict_final[w_int] = {}
        for h in dir_structure_w_weather_hydro_av[w].keys():
            h_int = int(h.replace(f"hydro_iteration_", ""))
            weather_hydro_avail_subproblem_stage_dict_final[w_int][h_int] = {}
            for a in dir_structure_w_weather_hydro_av[w][h].keys():
                a_int = int(a.replace(f"availability_iteration_", ""))
                weather_hydro_avail_subproblem_stage_dict_final[w_int][h_int][
                    a_int
                ] = {}
                for subproblem, stages in dir_structure_w_weather_hydro_av[w][h][
                    a
                ].items():
                    weather_hydro_avail_subproblem_stage_dict_final[w_int][h_int][
                        a_int
                    ][subproblem] = stages

    return ScenarioStructure(
        weather_hydro_avail_subproblem_stage_dict=weather_hydro_avail_subproblem_stage_dict_final,
        weather_iteration_flag=weather_iteration_flag,
        hydro_iteration_flag=hydro_iteration_flag,
        availability_iteration_flag=availability_iteration_flag,
        subproblem_flag=subproblem_flag,
        stage_flag=stage_flag,
    )


class SolverOptions(object):
    def __init__(self, conn, scenario_id):
        """
        :param cursor:
        :param scenario_id:
        """
        cursor = conn.cursor()

        self.SOLVER_OPTIONS_ID = cursor.execute("""
            SELECT solver_options_id 
            FROM scenarios 
            WHERE scenario_id = {}
            """.format(scenario_id)).fetchone()[0]

        if self.SOLVER_OPTIONS_ID is None:
            self.SOLVER_NAME = None
        else:
            distinct_solvers = cursor.execute(
                """SELECT DISTINCT solver_name 
                FROM inputs_options_solver 
                WHERE solver_options_id = {}""".format(self.SOLVER_OPTIONS_ID)
            ).fetchall()
            if len(distinct_solvers) > 1:
                raise ValueError("""
                ERROR: Solver options include more than one solver name! Only a 
                single solver name must be specified for solver_options_id in the 
                inputs_options_solver table. See solver_options_id {}. 
                """.format(self.SOLVER_OPTIONS_ID))
            else:
                self.SOLVER_NAME = distinct_solvers[0][0]

        self.SOLVER_OPTIONS = (
            None
            if self.SOLVER_OPTIONS_ID is None
            else {
                row[0]: row[1]
                for row in cursor.execute("""
                    SELECT solver_option_name, solver_option_value
                    FROM inputs_options_solver
                    WHERE solver_options_id = {};
                    """.format(self.SOLVER_OPTIONS_ID)).fetchall()
                if row[0] is not None and row[0] != ""
            }
        )


def db_column_to_self(column, conn, scenario_id):
    of = True if column.startswith("of") else False
    c = conn.cursor()
    query = c.execute(
        """SELECT {}
           FROM scenarios
           WHERE scenario_id = ?;""".format(column),
        (scenario_id,),
    ).fetchone()[0]

    self = "NULL" if query is None and not of else query

    return self


def get_scenario_table_columns(conn):
    c = conn.cursor()

    scenario_query = c.execute("""
        SELECT * FROM scenarios;
        """)
    column_names = [description[0] for description in scenario_query.description]

    return column_names


def dir_to_nested_dict(
    path: Union[str, Path], current_level, max_level: int = 5
) -> Dict[str, dict]:
    """
    Recursively convert a directory structure to a nested dictionary.
    Only add directories that are integers or start with one of
    weather_iteration_, hydro_iteration_, or availability_iteration_.

    Args:
    path: Path to the directory to convert

    Returns:
    Nested dictionary where keys are directory names and values are
    either empty dicts (for leaf directories) or nested dicts (for
    directories containing subdirectories).
    """
    if current_level > max_level:
        return

    path = Path(path)

    if not path.is_dir():
        raise ValueError(f"{path} is not a directory")

    result = {}

    # Iterate through items in the directory
    for item in sorted(path.iterdir()):
        # Only process directories, skip files
        # Only add directories that are integers or start with one of
        # weather_iteration_, hydro_iteration_, or availability_iteration_
        if item.is_dir() and (
            str(item.name).isdigit()
            or str(item.name).startswith("weather_iteration_")
            or str(item.name).startswith("hydro_iteration_")
            or str(item.name).startswith("availability_iteration_")
        ):
            # Recursively process subdirectories
            subdirs = dir_to_nested_dict(item, current_level + 1, max_level)
            # If subdirectory has no subdirs, use empty dict
            result[item.name] = subdirs if subdirs else {}

    return result


def check_dict_key_for_string_recursive(d, starting_string):
    if not d:
        return False
    else:
        for key, value in d.items():
            if key.startswith(starting_string):
                return True
            if isinstance(value, dict):
                if check_dict_key_for_string_recursive(value, starting_string):
                    return True
    return False


def get_dictionary_depth(d):
    if isinstance(d, dict):
        return 1 + (max(map(get_dictionary_depth, d.values()), default=0))
    return 0
