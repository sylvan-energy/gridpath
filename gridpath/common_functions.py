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

import os.path
import sys
import warnings

from argparse import ArgumentParser

import pandas as pd


def determine_scenario_directory(scenario_location, scenario_name):
    """
    :param scenario_location: string, the base directory
    :param scenario_name: string, the scenario name
    :return: the scenario directory (string)

    Determine the scenario directory given a base directory and the scenario
    name. If no base directory is specified, use a directory named
    'scenarios' in the root directory (one level down from the current
    working directory).
    """
    if scenario_location is None:
        main_directory = os.path.join(os.getcwd(), "..", "scenarios")
    else:
        main_directory = scenario_location

    scenario_directory = os.path.join(main_directory, str(scenario_name))

    return scenario_directory


def create_directory_if_not_exists(directory):
    """
    :param directory: string; the directory path

    Check if a directory exists and create it if not.
    """
    if not os.path.exists(directory):
        os.makedirs(directory)


def get_required_e2e_arguments_parser():
    """
    :return: the common parser for all e2e arguments

    Create ArgumentParser object which has the common set of arguments all
    end-to-end scripts. This includes the information for accessing local
    scenario data and whether to print run output.

    We can then simply add 'parents=[get_required_e2e_arguments_parser()]'
    when we create a parser for a script to inherit these common arguments.

    Note that 'add_help' is set to 'False' to avoid multiple `-h/--help` options
    (one for parent and one for each child), which will throw an error.
    """

    parser = ArgumentParser(add_help=False)
    parser.add_argument(
        "--scenario_location",
        default="../scenarios",
        help="The path to the directory in which to create "
        "the scenario directory. Defaults to "
        "'../scenarios' if not specified.",
    )
    parser.add_argument(
        "--quiet", default=False, action="store_true", help="Don't print run output."
    )

    parser.add_argument(
        "--verbose",
        default=False,
        action="store_true",
        help="Print extra output, e.g. current module info.",
    )

    return parser


def get_scenario_name_parser():
    """
    Create ArgumentParser object which has the common set of arguments for
    getting the scenario name

    We can then simply add 'parents=[get_scenario_names_parser()]' when we
    create a parser for a script to inherit these common arguments.

    Note that 'add_help' is set to 'False' to avoid multiple `-h/--help` options
    (one for parent and one for each child), which will throw an error.
    :return:
    """

    parser = ArgumentParser(add_help=False)
    required = parser.add_argument_group("required arguments")
    required.add_argument(
        "--scenario",
        required=True,
        type=str,
        help="Name of the scenario problem to solve.",
    )

    return parser


def get_db_parser():
    """
    Create ArgumentParser object which has the common set of arguments for
    accessing scenario data from the database.

    We can then simply add 'parents=[get_db_parser()]' when we create a
    parser for a script to inherit these common arguments.

    Note that 'add_help' is set to 'False' to avoid multiple `-h/--help` options
    (one for parent and one for each child), which will throw an error.
    :return:
    """

    parser = ArgumentParser(add_help=False)
    parser.add_argument(
        "--database",
        default="../db/io.db",
        help="The database file path relative to the current "
        "working directory. Defaults to ../db/io.db ",
    )
    parser.add_argument(
        "--scenario_id",
        type=int,
        help="The scenario_id from the database. Not needed "
        "if scenario is specified.",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        help="The scenario_name from the database. Not "
        "needed if scenario_id is specified.",
    )

    return parser


def get_temporal_structure_csv_overwrite_parser():
    """ """
    parser = ArgumentParser(add_help=False)
    parser.add_argument(
        "--temporal_structure_csv_overwrite",
        default=False,
        action="store_true",
        help="Overwrite the temporal structure from the database with the "
        "provided CSV file.",
    )
    parser.add_argument(
        "--temporal_structure_csv_path",
        help="Path to the CSV where the temporal structure is defined.",
    )

    return parser


def get_get_inputs_parser():
    """ """

    parser = ArgumentParser(add_help=False)
    parser.add_argument(
        "--n_parallel_get_inputs",
        default=1,
        help="Get inputs for n subproblems in parallel.",
    )

    return parser


def get_run_scenario_parser():
    """
    Create ArgumentParser object which has the common set of arguments for
    solving a scenario (see run_scenario.py and run_end_to_end.py).

    We can then simply add 'parents=[get_solve_parser()]' when we create a
    parser for a script to inherit these common arguments.

    Note that 'add_help' is set to 'False' to avoid multiple `-h/--help` options
    (one for parent and one for each child), which will throw an error.
    :return:
    """

    parser = ArgumentParser(add_help=False)

    # Output options
    parser.add_argument(
        "--log",
        default=False,
        action="store_true",
        help="Log output to a file in the scenario's 'logs' "
        "directory as well as the terminal.",
    )
    # Problem files and solutions
    parser.add_argument(
        "--create_lp_problem_file_only",
        default=False,
        action="store_true",
        help="Create and save the problem file, but don't solve yet.",
    )
    parser.add_argument(
        "--load_cplex_solution",
        default=False,
        action="store_true",
        help="Skip solve and load results from a CPLEX solution file instead.",
    )
    parser.add_argument(
        "--load_gurobi_solution",
        default=False,
        action="store_true",
        help="Skip solve and load results from a Gurobi solution file instead.",
    )
    parser.add_argument(
        "--load_highs_solution",
        default=False,
        action="store_true",
        help="Skip solve and load results from a HiGHS solution file instead.",
    )
    # Solver options
    parser.add_argument(
        "--solver",
        help="Name of the solver to use. "
        "GridPath will use Cbc if solver is "
        "not specified here and a "
        "'solver_options.csv' file does not "
        "exist in the scenario directory.",
    )
    parser.add_argument(
        "--solver_executable",
        help="The path to the solver executable to use. This "
        "is optional; if you don't specify it, "
        "Pyomo will look for the solver executable in "
        "your PATH. The solver specified with the "
        "--solver option must be the same as the solver "
        "for which you are providing an executable.",
    )
    parser.add_argument(
        "--mute_solver_output",
        default=False,
        action="store_true",
        help="Don't print solver output.",
    )
    parser.add_argument(
        "--write_solver_files_to_logs_dir",
        default=False,
        action="store_true",
        help="Write the temporary " "solver files to the logs " "directory.",
    )
    parser.add_argument(
        "--keepfiles",
        default=False,
        action="store_true",
        help="Save temporary solver files.",
    )
    parser.add_argument(
        "--symbolic",
        default=False,
        action="store_true",
        help="Use symbolic labels in solver files.",
    )
    parser.add_argument(
        "--report_timing",
        default=False,
        action="store_true",
    )
    # Flag for test runs (various changes in behavior)
    parser.add_argument(
        "--testing",
        default=False,
        action="store_true",
        help="Flag for test suite runs.",
    )

    # Parallel solve
    parser.add_argument(
        "--n_parallel_solve",
        default=1,
        help="Solve n subproblems in parallel.",
    )

    # Solve only incomplete subproblems
    parser.add_argument(
        "--incomplete_only",
        default=False,
        action="store_true",
        help="Solve only incomplete subproblems, i.e. do no re-solve if "
        "results are found. The subproblem is assumed complete if the"
        "termination_condition.txt file is found.",
    )

    # Results export rule name
    parser.add_argument(
        "--results_export_rule",
        help="The name of the rule to use to decide whether to export results.",
    )

    parser.add_argument(
        "--results_export_summary_rule",
        help="The name of the rule to use to decide whether to export "
        "summary results.",
    )

    parser.add_argument(
        "--skip_quick_summary",
        default=False,
        action="store_true",
        help="Skip quick summary text file",
    )

    # Numerical scaling (for solver conditioning)
    parser.add_argument(
        "--power_scale_factor",
        default=1.0,
        type=float,
        help="Divide power/energy quantities (MW, MWh) by this factor when "
        "solving, then map the solution back to native units. E.g. 1000 solves "
        "in GW/GWh. Default 1.0 (no scaling). See gridpath/auxiliary/scaling.py.",
    )
    parser.add_argument(
        "--dollar_scale_factor",
        default=1.0,
        type=float,
        help="Divide dollar quantities by this factor when solving, then map "
        "the solution back to native units. E.g. 1000000 solves in millions of "
        "dollars. Default 1.0 (no scaling). See gridpath/auxiliary/scaling.py.",
    )
    parser.add_argument(
        "--scale_mode",
        default="out_of_place",
        choices=["out_of_place", "in_place"],
        help="How to apply numerical scaling (only relevant if a scale factor "
        "is set). 'out_of_place' (default) solves a scaled clone and maps the "
        "solution back, keeping the original model pristine. 'in_place' scales "
        "the model itself and inverts the solution afterward, avoiding the clone "
        "(~half the peak memory and faster setup) at the cost of mutating the "
        "model; use it for very large problems where the clone is expensive.",
    )

    return parser


def get_import_results_parser():
    parser = ArgumentParser(add_help=False)
    parser.add_argument(
        "--results_import_rule",
        help="The name of the rule to use to decide whether to import results.",
    )
    parser.add_argument(
        "--ignore_incomplete",
        default=False,
        action="store_true",
        help="Ignore problems with no results. Can be used to import results "
        "for subproblems before all other subproblems have been solved. "
        "Proceed with caution.",
    )

    return parser


def ensure_empty_string(string):
    empty_string_ensured = "" if string == "empty_string" else string

    return empty_string_ensured


def create_logs_directory_if_not_exists(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    Create a logs directory if it doesn't exist already
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :return:
    """
    logs_directory = os.path.join(
        scenario_directory,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
        "logs",
    )
    if not os.path.exists(logs_directory):
        os.makedirs(logs_directory)
    return logs_directory


class Logging(object):
    """
    Log output to both standard output and a log file. This will be
    accomplished by assigning this class to sys.stdout.
    """

    def __init__(self, logs_dir, start_time, e2e, process_id):
        """
        Assign sys.stdout and a log file as output destinations

        :param logs_dir:
        """
        self.terminal = sys.stdout

        # If logging only run_scenario, print to a file starting with opt_
        # and the datetime
        # If logging run_e2e, print to a file starting with e2e_, with the
        # datetime, and the process ID
        if not e2e:
            self.log_file_path = os.path.join(
                logs_dir, "opt_{}.log".format(string_from_time(start_time))
            )
        else:
            self.log_file_path = os.path.join(
                logs_dir,
                "e2e_{}_pid_{}.log".format(
                    string_from_time(start_time), str(process_id)
                ),
            )

        self.log_file = open(self.log_file_path, "a", buffering=1)

    def __getattr__(self, attr):
        """
        Default to sys.stdout when calling attributes for this class

        :param attr:
        :return:
        """
        return getattr(self.terminal, attr)

    def write(self, message):
        """
        Output to both terminal and a log file. The print statement will
        call the write() method of any object you assign to sys.stdout
        (in this case the Logging object)

        :param message:
        :return:
        """
        self.terminal.write(message)
        self.log_file.write(message)

        # Find a print statement
        # import collections
        # import inspect

        # if message.strip():
        #     Record = collections.namedtuple(
        #         'Record',
        #         'frame filename line_number function_name lines index')
        #
        #     record = Record(*inspect.getouterframes(inspect.currentframe())[1])
        #     self.terminal.write(
        #         '{f} {n}: '.format(f=record.filename, n=record.line_number))
        # self.terminal.write(message)

    def flush(self):
        """
        Flush both the terminal and the log file

        :return:
        """
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        """
        Close the log file to release the file descriptor.
        Critical for preventing "too many open files" errors.
        """
        if hasattr(self, "log_file") and self.log_file and not self.log_file.closed:
            self.log_file.close()

    def __del__(self):
        """
        Ensure log file is closed when object is garbage collected
        """
        self.close()

    def __enter__(self):
        """
        Support context manager protocol
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Close log file when exiting context manager
        """
        self.close()
        return False


def string_from_time(datetime_string):
    """
    :param datetime_string: datetime string
    :return: formatted time string
    """
    return datetime_string.strftime("%Y-%m-%d_%H-%M-%S")


def create_results_df(index_columns, results_columns, data):
    df = pd.DataFrame(
        columns=index_columns + results_columns,
        data=data,
    ).set_index(index_columns)

    return df


def duals_wrapper(m, component, verbose=False):
    try:
        return m.dual[component]
    except KeyError:
        if verbose:
            warnings.warn(f"""
                KeyError caught when saving duals for {component}. Duals were 
                not exported. This is expected if solving a MIP with CPLEX (and 
                possibly other solvers), not otherwise.
                """)
        return None


def none_dual_type_error_wrapper(component, coefficient):
    try:
        return component / coefficient
    except TypeError:
        return None
