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
This script runs a GridPath scenario. It assumes that scenario inputs have
already been written.

The main() function of this script can also be called with the
*gridpath_run* command when GridPath is installed.
"""

import argparse
from csv import reader, writer
import datetime
import dill
import gc
import json
from multiprocessing import get_context, Manager
import os.path
import xml.etree.ElementTree as ET

from pyomo.environ import (
    AbstractModel,
    Suffix,
    DataPortal,
    SolverFactory,
    SolverStatus,
    TerminationCondition,
)

# from pyomo.util.infeasible import log_infeasible_constraints
from pyomo.common.timing import report_timing
from pyomo.common.tempfiles import TempfileManager
from pyomo.core import ComponentUID, SymbolMap
from pyomo.opt import ReaderFactory, ResultsFormat, ProblemFormat
import sys
import warnings

from gridpath.auxiliary.import_export_rules import import_export_rules
from gridpath.auxiliary.scenario_chars import (
    get_scenario_structure_from_disk,
    ScenarioDirectoryStructure,
)
from gridpath.common_functions import (
    determine_scenario_directory,
    get_scenario_name_parser,
    get_required_e2e_arguments_parser,
    get_run_scenario_parser,
    get_version_parser,
    create_logs_directory_if_not_exists,
    Logging,
    ensure_empty_string,
)
from gridpath.auxiliary.dynamic_components import DynamicComponents
from gridpath.auxiliary.module_list import determine_modules, load_modules


def create_problem(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    multi_stage,
    parsed_arguments,
):
    """
    :param scenario_directory: the main scenario directory
    :param subproblem: the horizon subproblem name
    :param stage: the stage subproblem name
    :param parsed_arguments: the user-defined script arguments
    :return: modules_to_use (list of module names used in scenario),
        loaded_modules (Python objects), dynamic_inputs (the populated
        dynamic components class), instance (the problem instance), results
        (the optimization results)

    This method creates the problem instance.

    To create the problem, we use a Pyomo AbstractModel() class. We will add
    Pyomo optimization components to this class, will load data into the
    components, and will then compile the problem.

    We first need to determine which GridPath modules we need to use. See
    *determine_modules* method (imported from
    *gridpath.auxiilary.module_list*) and import those modules (via the
    *load_modules* method imported from *gridpath.auxiliary.module_list*).

    We then determine the dynamic model components based on the selected
    modules and input data. See *populate_dynamic_components* method.

    The next step is to create the abstract model (see *create_abstract_model*
    method) and load the input data into its components (see
    *load_scenario_data*).

    Finally, we compile the problem (see *create_problem_instance* method).
    If any variables need to be fixed, this is done as the last step here
    (see the *fix_variables* method).
    """
    # Create pyomo abstract model class
    model = AbstractModel()
    dynamic_components = DynamicComponents()

    # Determine/load modules and dynamic components
    modules_to_use, loaded_modules = set_up_gridpath_modules(
        scenario_directory=scenario_directory, multi_stage=multi_stage
    )

    # Create the abstract model; some components are initialized here
    if not parsed_arguments.quiet:
        print("Building model...")
    create_abstract_model(
        model,
        dynamic_components,
        loaded_modules,
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    )

    if parsed_arguments.report_timing:
        report_timing()

    # Create a dual suffix component unless the user asked to skip duals;
    # duals are imported for every constraint in the model, which adds
    # significant memory and solution-load time
    if not parsed_arguments.skip_duals:
        model.dual = Suffix(direction=Suffix.IMPORT)

    # Load the scenario data
    if not parsed_arguments.quiet:
        print("Loading data...")
    scenario_data = load_scenario_data(
        model,
        dynamic_components,
        loaded_modules,
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    )

    if not parsed_arguments.quiet:
        print("Creating problem instance...")
    instance = create_problem_instance(model, scenario_data)

    # Fix variables if modules request so
    instance = fix_variables(
        instance,
        dynamic_components,
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        loaded_modules,
    )

    return dynamic_components, instance


def solve_problem(parsed_arguments, instance):
    # Solve
    if not parsed_arguments.quiet:
        print("Solving...")
    results = solve(instance, parsed_arguments)

    return instance, results


def run_optimization_for_subproblem_stage(
    scenario_directory,
    weather_iteration_directory,
    hydro_iteration_directory,
    availability_iteration_directory,
    subproblem_directory,
    stage_directory,
    multi_stage,
    parsed_arguments,
):
    """
    :param scenario_directory: the main scenario directory
    :param subproblem_directory: if there are horizon subproblems, the horizon
    :param stage_directory: if there are stage subproblems, the stage
    :param parsed_arguments: the parsed script arguments
    :return: return the objective function value (Total_Cost); only used in
        testing

    Log each run in the (sub)problem directory if requested by the user.

    Create and solve the (sub)problem (See *create_problem* and
    *solve_problem* methods respectively).

    Save results. See *save_results()* method.

    Return the objective function (Total_Cost) value; only used in testing mode

    """
    # Determine whether to skip this optimization before creating logger to
    # avoid the logging overhead and opening too many files for large
    # simulations
    skip_solve = False
    if parsed_arguments.incomplete_only:
        termination_condition_file = os.path.join(
            scenario_directory,
            weather_iteration_directory,
            hydro_iteration_directory,
            availability_iteration_directory,
            subproblem_directory,
            stage_directory,
            "results",
            "termination_condition.txt",
        )
        if os.path.isfile(termination_condition_file):
            with open(termination_condition_file, "r") as f:
                termination_condition = f.read()
            if not parsed_arguments.quiet:
                print(
                    f"Subproblem stage {subproblem_directory} "
                    f"{stage_directory} "
                    f"previously solved with termination condition "
                    f"**{termination_condition}**. Skipping solve."
                )
            skip_solve = True
            if not parsed_arguments.quiet:
                print(
                    f"Skipping {weather_iteration_directory}/{hydro_iteration_directory}/"
                    f"{availability_iteration_directory}/{subproblem_directory}/{stage_directory} "
                    f"(already solved)"
                )
            # Force garbage collection to release file descriptor immediately
            gc.collect()
            return None  # Exit early without creating logger

    # If directed to do so, log optimization run (only if actually solving)
    if parsed_arguments.log:
        logs_directory = create_logs_directory_if_not_exists(
            scenario_directory,
            weather_iteration_directory,
            hydro_iteration_directory,
            availability_iteration_directory,
            subproblem_directory,
            stage_directory,
        )

        # Save sys.stdout, so we can return to it later
        stdout_original = sys.stdout
        stderr_original = sys.stderr

        # The print statement will call the write() method of any object
        # you assign to sys.stdout (in this case the Logging object). The
        # write method of Logging writes both to sys.stdout and a log file
        # (see auxiliary/auxiliary.py)
        logger = Logging(
            logs_dir=logs_directory,
            start_time=datetime.datetime.now(),
            e2e=False,
            process_id=None,
        )
        sys.stdout = logger
        sys.stderr = logger

    if not skip_solve:
        # If directed, set temporary file directory to be the logs directory
        # In conjunction with --keepfiles, this will write the solver solution
        # files into the log directory (rather than a hidden temp folder).
        # Use the --symbolic argument as well for best debugging results
        if parsed_arguments.write_solver_files_to_logs_dir:
            logs_directory = create_logs_directory_if_not_exists(
                scenario_directory,
                weather_iteration_directory,
                hydro_iteration_directory,
                availability_iteration_directory,
                subproblem_directory,
                stage_directory,
            )
            TempfileManager.tempdir = logs_directory

        if not parsed_arguments.quiet:
            print(
                "\nRunning optimization for scenario {}".format(
                    scenario_directory.split("/")[-1]
                )
            )
            current_suproblem = os.path.join(
                weather_iteration_directory,
                hydro_iteration_directory,
                availability_iteration_directory,
                subproblem_directory,
                stage_directory,
            )
            if current_suproblem.endswith("/"):
                current_suproblem = current_suproblem[:-1]

            print(f"--- subproblem: {current_suproblem}")

        # We're expecting subproblem and stage to be strings downstream from here
        subproblem_directory = str(subproblem_directory)
        stage_directory = str(stage_directory)

        # Used only if we are writing problem files or loading solutions
        prob_sol_files_directory = os.path.join(
            scenario_directory, subproblem_directory, stage_directory, "prob_sol_files"
        )

        # Create problem instance and either save the problem file or solve the instance
        # TODO: incompatible options
        # If we are loading a solution, skip the compilation step; we'll use the saved
        # instance and dynamic components
        if parsed_arguments.load_cplex_solution:
            solved_instance, results, dynamic_components = load_cplex_xml_solution(
                prob_sol_files_directory=prob_sol_files_directory,
                solution_filename="cplex_solution.sol",
            )
        elif parsed_arguments.load_gurobi_solution:
            solved_instance, results, dynamic_components = load_gurobi_json_solution(
                prob_sol_files_directory=prob_sol_files_directory,
                solution_filename="gurobi_solution.json",
            )
        if parsed_arguments.load_highs_solution:
            solved_instance, results, dynamic_components = load_highs_xml_solution(
                prob_sol_files_directory=prob_sol_files_directory,
                solution_filename="highs_solution.sol",
            )
        else:
            dynamic_components, instance = create_problem(
                scenario_directory=scenario_directory,
                weather_iteration=weather_iteration_directory,
                hydro_iteration=hydro_iteration_directory,
                availability_iteration=availability_iteration_directory,
                subproblem=subproblem_directory,
                stage=stage_directory,
                multi_stage=multi_stage,
                parsed_arguments=parsed_arguments,
            )

            if parsed_arguments.create_lp_problem_file_only:
                prob_sol_files_directory = os.path.join(
                    scenario_directory,
                    subproblem_directory,
                    stage_directory,
                    "prob_sol_files",
                )
                if not os.path.exists(prob_sol_files_directory):
                    os.makedirs(prob_sol_files_directory)
                with open(
                    os.path.join(prob_sol_files_directory, "instance.pickle"), "wb"
                ) as f_out:
                    dill.dump(instance, f_out)
                with open(
                    os.path.join(prob_sol_files_directory, "dynamic_components.pickle"),
                    "wb",
                ) as f_out:
                    dill.dump(dynamic_components, f_out)

                smap_id = write_problem_file(
                    instance=instance, prob_sol_files_directory=prob_sol_files_directory
                )
                symbol_map = instance.solutions.symbol_map[smap_id]

                symbol_cuid_pairs = tuple(
                    (symbol, ComponentUID(var_weakref, cuid_buffer={}))
                    for symbol, var_weakref in symbol_map.bySymbol.items()
                )

                with open(
                    os.path.join(prob_sol_files_directory, "symbol_map.pickle"), "wb"
                ) as f_out:
                    dill.dump(symbol_cuid_pairs, f_out)

                print("Problem file written to {}".format(prob_sol_files_directory))
                sys.exit()
            else:
                solved_instance, results = solve_problem(
                    parsed_arguments=parsed_arguments,
                    instance=instance,
                )

        # Save the scenario results to disk
        save_results(
            scenario_directory,
            weather_iteration_directory,
            hydro_iteration_directory,
            availability_iteration_directory,
            subproblem_directory,
            stage_directory,
            multi_stage,
            solved_instance,
            results,
            dynamic_components,
            parsed_arguments,
        )

        # If logging, we need to return sys.stdout to original (i.e. stop writing
        # to log file) and close the log file to release file descriptor
        if parsed_arguments.log:
            logger.close()
            sys.stdout = stdout_original
            sys.stderr = stderr_original
            # Explicitly delete logger reference and force garbage collection
            del logger
            gc.collect()

        # Return the objective function value (in the testing suite, the value
        # gets checked against the expected value, but this is the only place
        # this is actually used)
        if results.solver.termination_condition != "infeasible":
            if parsed_arguments.testing:
                return solved_instance.NPV()
        else:
            warnings.warn("WARNING: the problem was infeasible!")


def run_optimization_for_subproblem(
    scenario_directory,
    weather_iteration_directory,
    hydro_iteration_directory,
    availability_iteration_directory,
    subproblem_directory,
    stage_directories,
    multi_stage,
    parsed_arguments,
    objective_values,
):
    """
    Check if there are stages in the subproblem; if not solve subproblem;
    if, yes, solve each stage sequentially
    """
    subproblem = 1 if subproblem_directory == "" else int(subproblem_directory)

    for stage_directory in stage_directories:
        stage = 1 if stage_directory == "" else int(stage_directory)
        objective_values[
            (
                weather_iteration_directory,
                hydro_iteration_directory,
                availability_iteration_directory,
                subproblem,
            )
        ][stage] = run_optimization_for_subproblem_stage(
            scenario_directory,
            weather_iteration_directory,
            hydro_iteration_directory,
            availability_iteration_directory,
            subproblem_directory,
            stage_directory,
            multi_stage,
            parsed_arguments,
        )
        # Force garbage collection after each stage to release file descriptors
        gc.collect()


def is_subproblem_stage_complete(
    scenario_directory,
    weather_iteration_directory,
    hydro_iteration_directory,
    availability_iteration_directory,
    subproblem_directory,
    stage_directory,
):
    """
    Check if a subproblem stage has been previously solved successfully.

    :param scenario_directory: the main scenario directory
    :param weather_iteration_directory: weather iteration directory
    :param hydro_iteration_directory: hydro iteration directory
    :param availability_iteration_directory: availability iteration directory
    :param subproblem_directory: subproblem directory
    :param stage_directory: stage directory
    :return: True if the subproblem stage is complete, False otherwise
    """
    termination_condition_file = os.path.join(
        scenario_directory,
        weather_iteration_directory,
        hydro_iteration_directory,
        availability_iteration_directory,
        subproblem_directory,
        stage_directory,
        "results",
        "termination_condition.txt",
    )
    return os.path.isfile(termination_condition_file)


def run_optimization_for_subproblem_pool(pool_datum):
    """
    Helper function to easily pass to pool.map if solving subproblems in
    parallel
    """
    [
        scenario_directory,
        weather_iteration_directory,
        hydro_iteration_directory,
        availability_iteration_directory,
        subproblem_directory,
        stage_directories,
        multi_stage,
        parsed_arguments,
        objective_values,
    ] = pool_datum

    run_optimization_for_subproblem(
        scenario_directory=scenario_directory,
        weather_iteration_directory=weather_iteration_directory,
        hydro_iteration_directory=hydro_iteration_directory,
        availability_iteration_directory=availability_iteration_directory,
        subproblem_directory=subproblem_directory,
        stage_directories=stage_directories,
        multi_stage=multi_stage,
        parsed_arguments=parsed_arguments,
        objective_values=objective_values,
    )


def solve_sequentially(
    scenario_directory_structure,
    scenario_directory,
    scenario_structure,
    parsed_arguments,
):
    # Create dictionary with which we'll keep track of subproblem/stage
    # objective function values
    objective_values = {}

    # TODO: refactor this
    for weather_iteration_str in scenario_directory_structure.keys():
        for hydro_iteration_str in scenario_directory_structure[
            weather_iteration_str
        ].keys():
            for availability_iteration_str in scenario_directory_structure[
                weather_iteration_str
            ][hydro_iteration_str]:
                # We may have passed "empty_string" to avoid actual empty
                # strings as dictionary keys; convert to actual empty
                # strings here to pass to the directory creation methods
                weather_iteration_str = ensure_empty_string(weather_iteration_str)
                hydro_iteration_str = ensure_empty_string(hydro_iteration_str)
                availability_iteration_str = ensure_empty_string(
                    availability_iteration_str
                )

                for subproblem_str in scenario_directory_structure[
                    weather_iteration_str
                ][hydro_iteration_str][availability_iteration_str].keys():
                    subproblem = 1 if subproblem_str == "" else int(subproblem_str)

                    # Write pass through input file headers
                    # TODO: this is not the best place for this; we should
                    #  probably set up the gridpath modules only once and do
                    #  this first
                    #  It needs to be created BEFORE stage 1 is run; it could
                    #  alternatively be created by the first stage that
                    #  exports pass through inputs, but this will require
                    #  changes to the formulation (for commitment)
                    if scenario_structure.STAGE_FLAG:
                        create_pass_through_inputs(
                            scenario_directory,
                            scenario_structure,
                            subproblem_str,
                            weather_iteration_str,
                            hydro_iteration_str,
                            availability_iteration_str,
                        )

                    objective_values[
                        (
                            weather_iteration_str,
                            hydro_iteration_str,
                            availability_iteration_str,
                            subproblem,
                        )
                    ] = {}
                    run_optimization_for_subproblem(
                        scenario_directory=scenario_directory,
                        weather_iteration_directory=weather_iteration_str,
                        hydro_iteration_directory=hydro_iteration_str,
                        availability_iteration_directory=availability_iteration_str,
                        subproblem_directory=subproblem_str,
                        stage_directories=scenario_directory_structure[
                            weather_iteration_str
                        ][hydro_iteration_str][availability_iteration_str][
                            subproblem_str
                        ],
                        multi_stage=scenario_structure.STAGE_FLAG,
                        parsed_arguments=parsed_arguments,
                        objective_values=objective_values,
                    )
                    # Force garbage collection after each subproblem to release file descriptors
                    gc.collect()
                # Force garbage collection after each availability iteration
                gc.collect()

    return objective_values


def run_scenario(
    scenario_directory,
    scenario_structure,
    parsed_arguments,
):
    """
    Check the scenario structure, iterate over all subproblems if they
    exist, and run the subproblem optimization.

    The objective function is returned, but it's only really used if we
    are in 'testing' mode.

    :param scenario_directory: scenario directory path
    :param scenario_structure: the subproblem structure object
    :param parsed_arguments:
    :return: the objective function value (NPV); only used in
     'testing' mode.
    """

    scenario_directory_structure = ScenarioDirectoryStructure(
        scenario_structure
    ).SCENARIO_DIRECTORY_STRUCTURE

    # TODO: consolidate parallelization checks
    try:
        n_parallel_subproblems = int(parsed_arguments.n_parallel_solve)
    except ValueError:
        warnings.warn(
            "The argument '--n_parallel_subproblems' must be "
            "an integer. Solving subproblems sequentially."
        )
        n_parallel_subproblems = 1

    # If only a single subproblem, run main problem
    if scenario_structure.N_SUBPROBLEMS == 1:
        if n_parallel_subproblems > 1:
            warnings.warn(
                "GridPath WARNING: only a single subproblem in "
                "scenario. No parallelization possible."
            )
        n_parallel_subproblems = 1

    # If parallelization is not requested, solve sequentially
    if n_parallel_subproblems == 1:
        objective_values = solve_sequentially(
            scenario_directory_structure=scenario_directory_structure,
            scenario_directory=scenario_directory,
            scenario_structure=scenario_structure,
            parsed_arguments=parsed_arguments,
        )

        return objective_values

    # If parallelization is requested, proceed with some checks
    elif n_parallel_subproblems > 1:
        # Check if the subproblems are linked, in which case
        # we can't parallelize and throw a warning, then solve
        # sequentially
        if os.path.exists(
            os.path.join(scenario_directory, "linked_subproblems_map.csv")
        ):
            warnings.warn(
                "GridPath WARNING: subproblems are linked and "
                "cannot be solved in parallel. Solving "
                "sequentially."
            )
            objective_values = solve_sequentially(
                scenario_directory_structure=scenario_directory_structure,
                subproblem_stage_directory_strings=subproblem_stage_directory_strings,
                scenario_directory=scenario_directory,
                scenario_structure=scenario_structure,
                parsed_arguments=parsed_arguments,
            )

            return objective_values

        # If subproblems are independent, we create pool of subproblems
        # and solve them in parallel
        else:
            # Create dictionary with which we'll keep track
            # of subproblem objective function values
            manager = Manager()
            objective_values = manager.dict()

            for weather_iteration_str in scenario_directory_structure.keys():
                for hydro_iteration_str in scenario_directory_structure[
                    weather_iteration_str
                ].keys():
                    for availability_iteration_str in scenario_directory_structure[
                        weather_iteration_str
                    ][hydro_iteration_str]:
                        # We may have passed "empty_string" to avoid actual empty
                        # strings as dictionary keys; convert to actual empty
                        # strings here to pass to the directory creation methods
                        weather_iteration_str = ensure_empty_string(
                            weather_iteration_str
                        )
                        hydro_iteration_str = ensure_empty_string(hydro_iteration_str)
                        availability_iteration_str = ensure_empty_string(
                            availability_iteration_str
                        )
                        for subproblem_str in scenario_directory_structure[
                            weather_iteration_str
                        ][hydro_iteration_str][availability_iteration_str].keys():
                            if scenario_structure.STAGE_FLAG:
                                create_pass_through_inputs(
                                    scenario_directory,
                                    scenario_structure,
                                    subproblem_str,
                                    weather_iteration_str,
                                    hydro_iteration_str,
                                    availability_iteration_str,
                                )

                            # TODO: create management of iteration objective functions
                            subproblem = (
                                1 if subproblem_str == "" else int(subproblem_str)
                            )
                            objective_values[
                                (
                                    weather_iteration_str,
                                    hydro_iteration_str,
                                    availability_iteration_str,
                                    subproblem,
                                )
                            ] = manager.dict()

            pool_data = []
            for weather_iteration_str in scenario_directory_structure.keys():
                for hydro_iteration_str in scenario_directory_structure[
                    weather_iteration_str
                ].keys():
                    for availability_iteration_str in scenario_directory_structure[
                        weather_iteration_str
                    ][hydro_iteration_str]:
                        # We may have passed "empty_string" to avoid actual empty
                        # strings as dictionary keys; convert to actual empty
                        # strings here to pass to the directory creation methods
                        weather_iteration_str = ensure_empty_string(
                            weather_iteration_str
                        )
                        hydro_iteration_str = ensure_empty_string(hydro_iteration_str)
                        availability_iteration_str = ensure_empty_string(
                            availability_iteration_str
                        )
                        for subproblem_str in scenario_directory_structure[
                            weather_iteration_str
                        ][hydro_iteration_str][availability_iteration_str].keys():
                            stage_directories = scenario_directory_structure[
                                weather_iteration_str
                            ][hydro_iteration_str][availability_iteration_str][
                                subproblem_str
                            ]

                            # If --incomplete_only flag is set, filter out complete subproblems
                            if parsed_arguments.incomplete_only:
                                # Filter stage directories to only include incomplete stages
                                incomplete_stage_directories = [
                                    stage_dir
                                    for stage_dir in stage_directories
                                    if not is_subproblem_stage_complete(
                                        scenario_directory,
                                        weather_iteration_str,
                                        hydro_iteration_str,
                                        availability_iteration_str,
                                        subproblem_str,
                                        stage_dir,
                                    )
                                ]
                                # Only add to pool if there are incomplete stages
                                if incomplete_stage_directories:
                                    pool_data.append(
                                        [
                                            scenario_directory,
                                            weather_iteration_str,
                                            hydro_iteration_str,
                                            availability_iteration_str,
                                            subproblem_str,
                                            incomplete_stage_directories,
                                            scenario_structure.STAGE_FLAG,
                                            parsed_arguments,
                                            objective_values,
                                        ]
                                    )
                            else:
                                # Add all stages if not filtering
                                pool_data.append(
                                    [
                                        scenario_directory,
                                        weather_iteration_str,
                                        hydro_iteration_str,
                                        availability_iteration_str,
                                        subproblem_str,
                                        stage_directories,
                                        scenario_structure.STAGE_FLAG,
                                        parsed_arguments,
                                        objective_values,
                                    ]
                                )

            pool_data = tuple(pool_data)

            # Adjust pool size based on actual number of tasks
            # (may be less than total subproblems if using --incomplete_only)
            n_tasks = len(pool_data)
            if n_tasks == 0:
                if not parsed_arguments.quiet:
                    print("All subproblems already complete. Nothing to solve.")
                return objective_values

            # Don't create more processes than tasks
            if n_parallel_subproblems > n_tasks:
                n_parallel_subproblems = n_tasks

            # Pool must use spawn to work properly on Linux
            pool = get_context("spawn").Pool(n_parallel_subproblems)

            pool.map(run_optimization_for_subproblem_pool, pool_data)
            pool.close()

            return objective_values


def create_pass_through_inputs(
    scenario_directory,
    scenario_structure,
    subproblem_str,
    weather_iteration_str,
    hydro_iteration_str,
    availability_iteration_str,
):
    modules_to_use, loaded_modules = set_up_gridpath_modules(
        scenario_directory=scenario_directory,
        multi_stage=scenario_structure.STAGE_FLAG,
    )
    pass_through_directory = os.path.join(
        scenario_directory,
        weather_iteration_str,
        hydro_iteration_str,
        availability_iteration_str,
        subproblem_str,
        "pass_through_inputs",
    )
    if not os.path.exists(pass_through_directory):
        os.makedirs(pass_through_directory)
    for m in loaded_modules:
        # Writing the headers will delete prior data in the file
        if hasattr(m, "write_pass_through_file_headers"):
            m.write_pass_through_file_headers(
                pass_through_directory=pass_through_directory
            )


def save_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    multi_stage,
    instance,
    results,
    dynamic_components,
    parsed_arguments,
):
    """
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param instance: model instance (solution loaded after solving by default)
    :param dynamic_components:
    :param parsed_arguments:
    :return:

    Create a results directory for the (sub)problem.
    Export results.
    Export pass through imports.
    Save objective function value.
    Save constraint duals.
    """
    if not parsed_arguments.quiet:
        print("Saving results...")

    # TODO: how best to handle non-empty results directories?
    results_directory = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "results",
    )
    if not os.path.exists(results_directory):
        os.makedirs(results_directory)

    # Check if a solution was found and only export results if so; save the
    # solver status, which will be used to determine the behavior of other
    # scripts
    with open(
        os.path.join(results_directory, "solver_status.txt"), "w", newline=""
    ) as f:
        f.write(str(results.solver.status))
    with open(
        os.path.join(results_directory, "termination_condition.txt"), "w", newline=""
    ) as f:
        f.write(str(results.solver.termination_condition))

    if results.solver.status == SolverStatus.ok:
        if not parsed_arguments.quiet:
            print(
                "...solver termination condition: {}.".format(
                    results.solver.termination_condition
                )
            )
        if results.solver.termination_condition != TerminationCondition.optimal:
            warnings.warn("   ...solution is not optimal!")
        # Continue with results export
        # Parse arguments to see if we're following a special rule for whether to
        # export results
        if parsed_arguments.results_export_rule is None:
            export_rule = _export_rule(instance=instance, quiet=parsed_arguments.quiet)
        else:
            export_rule = import_export_rules[parsed_arguments.results_export_rule][
                "export"
            ](instance=instance, quiet=parsed_arguments.quiet)

        if not parsed_arguments.quiet:
            print("...exporting detailed CSV results")
        export_results(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            multi_stage=multi_stage,
            instance=instance,
            dynamic_components=dynamic_components,
            export_rule=export_rule,
            verbose=parsed_arguments.verbose,
        )

        if parsed_arguments.results_export_summary_rule is None:
            export_summary_rule = _export_summary_results_rule(
                instance=instance, quiet=parsed_arguments.quiet
            )
        else:
            export_summary_rule = import_export_rules[
                parsed_arguments.results_export_summary_rule
            ]["export_summary"](instance=instance, quiet=parsed_arguments.quiet)

        if export_summary_rule:
            if not parsed_arguments.quiet:
                print("...exporting summary CSV results")
            export_summary_results(
                scenario_directory=scenario_directory,
                weather_iteration=weather_iteration,
                hydro_iteration=hydro_iteration,
                availability_iteration=availability_iteration,
                subproblem=subproblem,
                stage=stage,
                multi_stage=multi_stage,
                instance=instance,
                dynamic_components=dynamic_components,
                verbose=parsed_arguments.verbose,
            )

        export_pass_through_inputs(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            multi_stage=multi_stage,
            instance=instance,
            verbose=parsed_arguments.verbose,
        )

        save_objective_function_value(
            scenario_directory=scenario_directory,
            weather_iteration=weather_iteration,
            hydro_iteration=hydro_iteration,
            availability_iteration=availability_iteration,
            subproblem=subproblem,
            stage=stage,
            instance=instance,
        )

        if not parsed_arguments.skip_duals:
            save_duals(
                scenario_directory=scenario_directory,
                weather_iteration=weather_iteration,
                hydro_iteration=hydro_iteration,
                availability_iteration=availability_iteration,
                subproblem=subproblem,
                stage=stage,
                multi_stage=multi_stage,
                instance=instance,
                dynamic_components=dynamic_components,
                verbose=parsed_arguments.verbose,
            )

        # Force garbage collection to release file descriptors immediately
        # This prevents "too many open files" errors when processing many iterations
        gc.collect()
    # If solver status is not ok, don't export results and print some
    # messages for the user
    else:
        if results.solver.termination_condition == TerminationCondition.infeasible:
            if not parsed_arguments.quiet:
                print(
                    "Problem was infeasible. Results not exported for "
                    "subproblem {}, stage {}.".format(subproblem, stage)
                )
            # If subproblems are linked, exit since we don't have linked inputs
            # for the next subproblem; otherwise, move on to the next
            # subproblem
            if os.path.exists(
                os.path.join(scenario_directory, "linked_subproblems_map.csv")
            ):
                raise Exception(
                    "Subproblem {}, stage {} was infeasible. "
                    "Exiting linked subproblem run.".format(subproblem, stage)
                )


def create_abstract_model(
    model,
    dynamic_components,
    loaded_modules,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    :param model: the Pyomo AbstractModel object
    :param dynamic_components: the populated dynamic model components class
    :param loaded_modules: list of the required modules as Python objects
    :param scenario_directory:
    :param subproblem:
    :param stage:

    To create the abstract model, we iterate over all required modules and
    call their *add_model_components* method to add components to the Pyomo
    AbstractModel. Some modules' *add_model_components* method also require the
    dynamic component class as an argument for any dynamic components to be
    added to the model.
    """
    for m in loaded_modules:
        if hasattr(m, "add_model_components"):
            m.add_model_components(
                model,
                dynamic_components,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            )


def load_scenario_data(
    model,
    dynamic_components,
    loaded_modules,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    :param model: the Pyomo abstract model object with components added
    :param dynamic_components: the dynamic components class
    :param loaded_modules: list of the imported GridPath modules as Python
        objects
    :param scenario_directory: the main scenario directory
    :param subproblem: the horizon subproblem
    :param stage: the stage subproblem
    :return: the DataPortal object populated with the input data

    Iterate over all required GridPath modules and call their
    *load_model_data* method in order to load input data into the relevant
    model components. Return the resulting DataPortal object with the data
    loaded in.
    """
    # Load data
    data_portal = DataPortal()
    for m in loaded_modules:
        if hasattr(m, "load_model_data"):
            m.load_model_data(
                model,
                dynamic_components,
                data_portal,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            )
    return data_portal


def create_problem_instance(model, loaded_data):
    """
    :param model: the AbstractModel Pyomo object with components added
    :param loaded_data: the DataPortal object with the data loaded in and
        linked to the relevant model components
    :return: the compiled problem instance

    Compile the problem based on the abstract model formulation and the data
    loaded into the model components.
    """
    # Create problem instance
    instance = model.create_instance(loaded_data)
    return instance


def fix_variables(
    instance,
    dynamic_components,
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    loaded_modules,
):
    """
    :param instance: the compiled problem instance
    :param dynamic_components: the dynamic component class
    :param scenario_directory: str
    :param subproblem: str
    :param stage: str
    :param loaded_modules: list of imported GridPath modules as Python objects
    :return: the problem instance with the relevant variables fixed

    Iterate over the required GridPath modules and fix variables by calling
    the modules' *fix_variables*, if applicable. Return the modified
    problem instance with the relevant variables fixed.
    """
    for m in loaded_modules:
        if hasattr(m, "fix_variables"):
            m.fix_variables(
                instance,
                dynamic_components,
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            )

    return instance


def view_loaded_data(loaded_modules, instance):
    """
    :param loaded_modules:
    :param instance:
    :return:

    View data (for debugging)
    """
    for m in loaded_modules:
        if hasattr(m, "view_loaded_data"):
            m.view_loaded_data(instance)


def solve(instance, parsed_arguments):
    """
    :param instance: the compiled problem instance
    :param parsed_arguments: the user-defined arguments (parsed)
    :return: the problem results

    Send the compiled problem instance to the solver and solve.
    """
    # Start with solver name specified on command line
    solver_name = parsed_arguments.solver

    # Get any user-requested solver options
    scenario_directory = determine_scenario_directory(
        scenario_location=parsed_arguments.scenario_location,
        scenario_name=parsed_arguments.scenario,
    )
    solver_options = dict()
    solver_options_file = os.path.join(scenario_directory, "solver_options.csv")

    # First, figure out which solver or shell solver (solver_name) we are using and do
    # some checks
    # The solver_name is simply the chosen "optimizer," e.g. Cbc, Gurobi, CPLEX,
    # or a shell solver such as GAMS and AMPL
    # This is separate from a "solver" option, which is the solver to use if using a
    # shell solver such as GAMS
    if os.path.exists(solver_options_file):
        with open(solver_options_file) as f:
            _reader = reader(f, delimiter=",")
            for row in _reader:
                solver_options[row[0]] = row[1]

        # Check the solver name specified is the same as that given from the
        # command line (if any)
        if parsed_arguments.solver is not None:
            if not parsed_arguments.solver == solver_options["solver_name"]:
                raise UserWarning(
                    "ERROR! Solver specified on command line ({}) and solver name "
                    "in solver_options.csv ({}) do not match.".format(
                        parsed_arguments.solver, solver_options["solver_name"]
                    )
                )

        # If we make it here, set the solver name from the
        # solver_options.csv file
        solver_name = solver_options["solver_name"]
        # remove "solver_name" from the solver_options object, as it is not actually
        # an "option" and we can iterate over options later without worrying about
        # skipping this
        del solver_options["solver_name"]

    else:
        if parsed_arguments.solver is None:
            solver_name = "cbc"

    # Get solver
    # If a solver executable is specified, pass it to Pyomo
    if parsed_arguments.solver_executable is not None:
        optimizer = SolverFactory(
            solver_name, executable=parsed_arguments.solver_executable
        )
    # Otherwise, only pass the solver name; Pyomo will look for the
    # executable in the PATH
    else:
        optimizer = SolverFactory(solver_name)

    # Solve
    # Apply the solver options (if any)
    # Note: Pyomo moves the results to the instance object by default.
    # If you want the results to stay into a results object, set the
    # load_solutions argument to False:
    # >>> results = solver.solve(instance, load_solutions=False)
    # With "shell solvers" (e.g. GAMS, AMPL), we can specify which solver (e.g.
    # CPLEX, Gurobi) to use
    # No access to AMPL, so not supported at this pont
    if solver_name == "gams":
        # Specify which "solver" to use if using GAMS as a "shell solver" --
        # e.g. we could be using CPLEX through GAMS
        # The following way to pass options to the solver is GAMS-specific, may also
        # work for AMPL but not supported at this point
        # Based on: https://stackoverflow.com/questions/57965894/how-to-specify-gams-solver-specific-options-through-pyomo/64698920#64698920
        if "solver" in solver_options.keys():
            add_options = [
                "GAMS_MODEL.optfile = 1;",
                "$onecho > {solver}.opt".format(solver=solver_options["solver"]),
            ]
            for opt in solver_options.keys():
                if not opt == "solver":
                    opt_string = "{option} {value}".format(
                        option=opt, value=solver_options[opt]
                    )
                    add_options.append(opt_string)

            add_options.append("$offecho")

            results = optimizer.solve(
                instance,
                solver=solver_options["solver"],
                add_options=add_options,
                tee=not parsed_arguments.mute_solver_output,
                keepfiles=parsed_arguments.keepfiles,
                symbolic_solver_labels=parsed_arguments.symbolic,
            )
        else:
            warnings.warn(
                "A solver must be specified in the solver settings if you "
                "want to pass settings through GAMS."
            )
    else:
        for opt in solver_options.keys():
            optimizer.options[opt] = solver_options[opt]

        results = optimizer.solve(
            instance,
            tee=not parsed_arguments.mute_solver_output,
            keepfiles=parsed_arguments.keepfiles,
            symbolic_solver_labels=parsed_arguments.symbolic,
        )

    # Can optionally log infeasibilities but this has resulted in false
    # positives due to rounding errors larger than the default tolerance
    # of 1E-6.
    # log_infeasible_constraints(instance)

    return results


def export_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    multi_stage,
    instance,
    dynamic_components,
    export_rule,
    verbose,
):
    """
    :param scenario_directory:
    :param hydro_iteration:
    :param subproblem:
    :param stage:
    :param instance:
    :param dynamic_components:
    :param export_rule:
    :param verbose:
    :return:

    Export results for each loaded module (if applicable)
    """
    if export_rule:
        # Determine/load modules and dynamic components
        modules_to_use, loaded_modules = set_up_gridpath_modules(
            scenario_directory=scenario_directory, multi_stage=multi_stage
        )

        n = 0
        for m in loaded_modules:
            if hasattr(m, "export_results"):
                if verbose:
                    print(f"... {modules_to_use[n]}")
                m.export_results(
                    scenario_directory,
                    weather_iteration,
                    hydro_iteration,
                    availability_iteration,
                    subproblem,
                    stage,
                    instance,
                    dynamic_components,
                )

            n += 1


def export_summary_results(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    multi_stage,
    instance,
    dynamic_components,
    verbose,
):
    """
    :param scenario_directory:
    :param hydro_iteration:
    :param subproblem:
    :param stage:
    :param instance:
    :param dynamic_components:
    :param export_rule:
    :param verbose:
    :return:

    Export results for each loaded module (if applicable)
    """
    # Determine/load modules and dynamic components
    modules_to_use, loaded_modules = set_up_gridpath_modules(
        scenario_directory=scenario_directory, multi_stage=multi_stage
    )

    n = 0
    for m in loaded_modules:
        if hasattr(m, "export_summary_results"):
            if verbose:
                print(f"... {modules_to_use[n]}")
            m.export_summary_results(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                instance,
                dynamic_components,
            )

        n += 1


def export_pass_through_inputs(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    multi_stage,
    instance,
    verbose,
):
    """
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param instance:
    :param verbose:
    :return:

    Export pass through inputs for each loaded module (if applicable)
    """
    # Determine/load modules and dynamic components
    modules_to_use, loaded_modules = set_up_gridpath_modules(
        scenario_directory=scenario_directory, multi_stage=multi_stage
    )

    n = 0
    for m in loaded_modules:
        if hasattr(m, "export_pass_through_inputs"):
            if verbose:
                print(f"... {modules_to_use[n]}")
            m.export_pass_through_inputs(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                instance,
            )
        n += 1


def save_objective_function_value(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    instance,
):
    """
    Save the objective function value.
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param instance:
    :return:
    """
    objective_function_value = instance.NPV()

    # Round objective function value of test examples
    if os.path.dirname(scenario_directory)[-8:] == "examples":
        objective_function_value = round(objective_function_value, 2)

    with open(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "results",
            "objective_function_value.txt",
        ),
        "w",
        newline="",
    ) as objective_file:
        objective_file.write(str(objective_function_value))


def save_duals(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    multi_stage,
    instance,
    dynamic_components,
    verbose,
):
    """
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param instance:
    :param dynamic_components:
    :param verbose:
    :return:

    Save the duals of various constraints.
    """
    # Determine/load modules and dynamic components
    modules_to_use, loaded_modules = set_up_gridpath_modules(
        scenario_directory=scenario_directory, multi_stage=multi_stage
    )

    instance.constraint_indices = {}

    n = 0
    for m in loaded_modules:
        if verbose:
            print(f"... {modules_to_use[n]}")
        if hasattr(m, "save_duals"):
            m.save_duals(
                scenario_directory,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
                instance,
                dynamic_components,
            )
        n += 1


def set_up_gridpath_modules(scenario_directory, multi_stage):
    """
    :return: list of the names of the modules the scenario uses, list of the
        loaded modules, and the populated dynamic components for the scenario

    Set up the modules and dynamic components for a scenario run problem
    instance.
    """
    # Determine and load modules
    modules_to_use = determine_modules(
        scenario_directory=scenario_directory, multi_stage=multi_stage
    )
    loaded_modules = load_modules(modules_to_use)
    # Determine the dynamic components based on the needed modules and input
    # data
    # populate_dynamic_inputs(dynamic_components, loaded_modules,
    #                         scenario_directory, subproblem, stage)

    return modules_to_use, loaded_modules


# Parse run options
def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
        Python object)

    Parse the known arguments.
    """
    parser = argparse.ArgumentParser(
        add_help=True,
        parents=[
            get_scenario_name_parser(),
            get_required_e2e_arguments_parser(),
            get_run_scenario_parser(),
            get_version_parser(),
        ],
    )

    # Flip order of argument groups so "required arguments" show first
    # https://stackoverflow.com/questions/39047075/reorder-python-argparse-argument-groups
    # Note: hacky fix; preferred answer of creating an explicit optional group
    # doesn't work because we combine parsers here with the parents keyword
    parser._action_groups.reverse()

    # Parse arguments
    # TODO: should we throw warning for unknown arguments (here and in the
    #  other scripts)? run_start_to_end does pass unknown arguments (e.g.
    #  the database file path), so we'd have to suppress warnings then
    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    """
    This is the 'main' method that runs a scenario. It takes in and parses the
    script arguments, determines the scenario structure (i.e. whether it is a
    single optimization or has subproblems), and runs the scenario.
    This method also returns the objective function value(s).
    """

    if args is None:
        args = sys.argv[1:]
    # Parse arguments
    parsed_args = parse_arguments(args)

    scenario_directory = determine_scenario_directory(
        scenario_location=parsed_args.scenario_location,
        scenario_name=parsed_args.scenario,
    )

    # Check if the scenario actually exists
    if not os.path.exists(scenario_directory):
        raise IOError(
            "Scenario '{}/{}' does not exist. Please verify"
            " scenario name and scenario location".format(
                parsed_args.scenario_location, parsed_args.scenario
            )
        )

    scenario_structure = get_scenario_structure_from_disk(
        scenario_directory=scenario_directory
    )

    if not parsed_args.quiet:
        print(
            "Running scenario {}, started on {}...".format(
                parsed_args.scenario, datetime.datetime.now()
            )
        )

    # Run the scenario (can be multiple optimization subproblems)
    expected_objective_values = run_scenario(
        scenario_directory=scenario_directory,
        scenario_structure=scenario_structure,
        parsed_arguments=parsed_args,
    )

    # Return the objective function values (used in testing)
    return expected_objective_values


def _export_rule(instance, quiet):
    """
    :return: boolean

    Rule for whether to export results for the current proble. Write your
    custom rule here to use this functionality. Must return True or False.
    """
    export_results = True

    return export_results


def _export_summary_results_rule(instance, quiet):
    """
    :return: boolean

    Rule for whether to export summary results for the current problem. Write
    your custom rule here to use this functionality. Must return True or False.
    """
    export_summary_results_results = True

    return export_summary_results_results


def _summarize_rule(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    quiet,
):
    """
    :return: boolean

    Rule for whether to summarize results for a subproblem/stage. Write your
    custom rule here to use this functionality. Must return True or False.
    """
    summarize_results = True

    return summarize_results


#####


def write_problem_file(instance, prob_sol_files_directory, problem_format="lp"):
    """

    :param instance:
    :param prob_sol_files_directory:
    :param problem_format:
    :return:

    """
    formats = dict()
    # Only supporting LP problem format for now
    formats["lp"] = ProblemFormat.cpxlp

    # formats["py"] = ProblemFormat.pyomo
    # formats["nl"] = ProblemFormat.nl
    # formats["bar"] = ProblemFormat.bar
    # formats["mps"] = ProblemFormat.mps
    # formats["mod"] = ProblemFormat.mod
    # formats["osil"] = ProblemFormat.osil
    # formats["gms"] = ProblemFormat.gams
    # formats["gams"] = ProblemFormat.gams

    print("Writing {} problem file...".format(problem_format.upper()))
    filename, smap_id = instance.write(
        os.path.join(
            prob_sol_files_directory, "problem_file.{}".format(problem_format)
        ),
        format=formats[problem_format],
        io_options=[],
    )

    return smap_id


def load_cplex_xml_solution(
    prob_sol_files_directory, solution_filename="cplex_solution.sol"
):
    """
    :param prob_sol_files_directory:
    :param solution_filename:
    :return:
    """
    print(
        "Loading results from solution file {}...".format(
            os.path.join(prob_sol_files_directory, solution_filename)
        )
    )
    instance, dynamic_components, symbol_map = load_problem_info(
        prob_sol_files_directory=prob_sol_files_directory
    )

    # Read XML (.sol) solution file
    root = ET.parse(os.path.join(prob_sol_files_directory, solution_filename)).getroot()

    # Variables
    for type_tag in root.findall("variables/variable"):
        var_id, var_index, value = (
            type_tag.get("name"),
            type_tag.get("index"),
            type_tag.get("value"),
        )
        # "x2" with value None added for CPLEXSolution version 1.2
        if not var_id in ["ONE_VAR_CONSTANT", "x2"]:
            symbol_map.bySymbol[var_id].value = float(value)

    # Constraints (only if the instance was created with a dual suffix,
    # i.e. not with --skip_duals)
    if hasattr(instance, "dual"):
        for type_tag in root.findall("linearConstraints/constraint"):
            constraint_id_w_extra_symbols, const_index, dual = (
                type_tag.get("name"),
                type_tag.get("index"),
                type_tag.get("dual"),
            )
            if not constraint_id_w_extra_symbols == "c_e_ONE_VAR_CONSTANT":
                # constraint_id = constraint_id_w_extra_symbols[4:-1]
                constraint_id = constraint_id_w_extra_symbols
                instance.dual[symbol_map.bySymbol[constraint_id]] = float(dual)

    # Solver status
    header = root.findall("header")[0]  # Need a check that there is only one element

    termination_condition = header.get("solutionStatusString")
    # TODO: what are the types
    solver_status = "ok" if header.get("solutionStatusValue") == "1" else "unknown"
    results = Results(
        solver_status=solver_status, termination_condition=termination_condition
    )

    return instance, results, dynamic_components


def load_gurobi_json_solution(
    prob_sol_files_directory, solution_filename="gurobi_solution.json"
):
    """
    :param prob_sol_files_directory:
    :param solution_filename:
    :return:
    """
    print(
        "Loading results from solution file {}...".format(
            os.path.join(prob_sol_files_directory, solution_filename)
        )
    )

    instance, dynamic_components, symbol_map = load_problem_info(
        prob_sol_files_directory=prob_sol_files_directory
    )

    # #### WORKING VERSION #####
    # This needs to be under an if statement and execute when we are loading
    # solution from disk
    # Read JSON solution file
    with open(os.path.join(prob_sol_files_directory, solution_filename), "r") as f:
        solution = json.load(f)

    # Variables
    for v in solution["Vars"]:
        var_id, value = v["VTag"][0], v["X"]
        if not var_id == "ONE_VAR_CONSTANT":
            symbol_map.bySymbol[var_id]().value = float(value)

    # Constraints (only if the instance was created with a dual suffix,
    # i.e. not with --skip_duals)
    if hasattr(instance, "dual"):
        for c in solution["Constrs"]:
            constraint_id, dual = c["CTag"][0][4:], c["Pi"]
            if not constraint_id == "ONE_VAR_CONSTAN":
                instance.dual[symbol_map.bySymbol[constraint_id]()] = float(dual)

    # Solver status
    # TODO: what are the types
    termination_condition = (
        "optimal" if solution["SolutionInfo"]["Status"] == 2 else "unknown"
    )
    solver_status = "ok" if solution["SolutionInfo"]["Status"] == 2 else "unknown"
    results = Results(
        solver_status=solver_status, termination_condition=termination_condition
    )

    return instance, results, dynamic_components


def load_highs_xml_solution(
    prob_sol_files_directory, solution_filename="highs_solution.sol"
):
    """
    :param prob_sol_files_directory:
    :param solution_filename:
    :return:
    """
    print(
        "Loading results from solution file {}...".format(
            os.path.join(prob_sol_files_directory, solution_filename)
        )
    )
    instance, dynamic_components, symbol_map = load_problem_info(
        prob_sol_files_directory=prob_sol_files_directory
    )

    # Read HiGHS solution file
    with open(os.path.join(prob_sol_files_directory, solution_filename), "r") as f:
        lines = f.readlines()

    # Model status is  th second line
    model_status = lines[1].strip() if len(lines) > 1 else "Unknown"
    termination_condition = model_status.lower()
    solver_status = "ok" if termination_condition == "optimal" else "unknown"

    # Parse the HiGHS solution file
    section = None

    for line in lines:
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            # Check for section headers in comments
            if line == "# Primal solution values":
                section = "primal_start"
            elif "# Columns" in line and section == "primal_start":
                section = "primal_columns"
            elif "# Rows" in line and section == "primal_columns":
                section = "primal_rows"
            elif line == "# Dual solution values":
                section = "dual_start"
            elif "# Columns" in line and section == "dual_start":
                section = "dual_columns"
            elif "# Rows" in line and section in ["dual_start", "dual_columns"]:
                section = "dual_rows"
            elif line == "# Basis":
                # Stop parsing once we reach basis section
                break
            continue

        # Skip non-data lines
        if line in ["Model status", "Feasible", "Valid"]:
            continue
        if line.startswith("Objective "):
            continue

        # Parse primal variable values (x variables only)
        if section == "primal_columns":
            parts = line.split()
            if len(parts) == 2:
                var_id, value = parts[0], parts[1]
                if (
                    var_id.startswith("x")
                    and var_id in symbol_map.bySymbol
                    and var_id not in ["ONE_VAR_CONSTANT", "x2"]
                ):
                    symbol_map.bySymbol[var_id].value = float(value)

        # Parse constraint dual values (c_ constraints only) from dual rows
        # (only if the instance was created with a dual suffix, i.e. not
        # with --skip_duals)
        elif section == "dual_rows":
            parts = line.split()
            if len(parts) == 2 and hasattr(instance, "dual"):
                constraint_id, dual = parts[0], parts[1]
                if (
                    constraint_id.startswith("c_")
                    and constraint_id in symbol_map.bySymbol
                    and constraint_id != "c_e_ONE_VAR_CONSTANT"
                ):
                    instance.dual[symbol_map.bySymbol[constraint_id]] = float(dual)

    results = Results(
        solver_status=solver_status, termination_condition=termination_condition
    )

    return instance, results, dynamic_components


def load_problem_info(prob_sol_files_directory):
    with open(
        os.path.join(prob_sol_files_directory, "instance.pickle"), "rb"
    ) as instance_in:
        instance = dill.load(instance_in)
    with open(
        os.path.join(prob_sol_files_directory, "dynamic_components.pickle"), "rb"
    ) as dc_in:
        dynamic_components = dill.load(dc_in)
    with open(
        os.path.join(prob_sol_files_directory, "symbol_map.pickle"), "rb"
    ) as map_in:
        symbol_cuid_pairs = dill.load(map_in)
        symbol_map = SymbolMap()
        symbol_map.addSymbols(
            (cuid.find_component_on(instance), symbol)
            for symbol, cuid in symbol_cuid_pairs
        )

    return instance, dynamic_components, symbol_map


class Results(object):
    def __init__(self, solver_status, termination_condition):
        self.solver = Object()
        self.solver.status = solver_status
        self.solver.termination_condition = termination_condition


class Object(object):
    pass


if __name__ == "__main__":
    main()
