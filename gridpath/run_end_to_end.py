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

"""
This script calls the __main__ functions of get_scenario_inputs.py,
run scenario.py, import_scenario_results.py, and process_results.py to run a
scenario end-to-end, i.e. get the scenario inputs from the database,
solve the scenario problem, import the results the database and perform any
necessary results-processing.

The main() function of this script can also be called with the
*gridpath_process_results* command when GridPath is installed.
"""

from argparse import ArgumentParser
import datetime
import logging
import os
import signal
import sys

# GridPath modules
from db.common_functions import connect_to_database, spin_on_database_lock
from gridpath.common_functions import (
    get_db_parser,
    get_temporal_structure_csv_overwrite_parser,
    get_run_scenario_parser,
    get_required_e2e_arguments_parser,
    get_get_inputs_parser,
    get_version_parser,
    create_logs_directory_if_not_exists,
    Logging,
    determine_scenario_directory,
    get_import_results_parser,
    string_from_time,
)
from gridpath import (
    get_scenario_inputs,
    run_scenario,
    import_scenario_results,
    process_results,
)
from gridpath.run_scenario import _export_rule, _summarize_rule
from gridpath.import_scenario_results import _import_rule
from gridpath.auxiliary.db_interface import get_scenario_id_and_name


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """

    parser = ArgumentParser(
        add_help=True,
        parents=[
            get_db_parser(),
            get_temporal_structure_csv_overwrite_parser(),
            get_required_e2e_arguments_parser(),
            get_run_scenario_parser(),
            get_get_inputs_parser(),
            get_import_results_parser(),
            get_version_parser(),
        ],
    )

    # Arguments to skip an E2E step
    parser.add_argument(
        "--skip_get_inputs",
        default=False,
        action="store_true",
        help="Skip the 'get_scenario_inputs' E2E step.",
    )
    parser.add_argument(
        "--skip_run_scenario",
        default=False,
        action="store_true",
        help="Skip the 'run_scenario' E2E step.",
    )
    parser.add_argument(
        "--skip_import_results",
        default=False,
        action="store_true",
        help="Skip the 'import_scenario_results' E2E step.",
    )
    parser.add_argument(
        "--skip_process_results",
        default=False,
        action="store_true",
        help="Skip the 'process_results' E2E step.",
    )

    # Run only a single E2E step
    parser.add_argument(
        "--single_e2e_step_only",
        choices=["get_inputs", "run_scenario", "import_results", "process_results"],
        help="Run only the specified E2E step. All others " "will be skipped.",
    )

    parsed_arguments = parser.parse_args(args=args)

    return parsed_arguments


# TODO: change all these to use scenario_id, not scenario_name
def update_run_status(db_path, scenario, status_id):
    """
    :param db_path:
    :param scenario:
    :param status_id:
    :return:

    Update the run status in the database for the scenario.
    """

    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    sql = """
        UPDATE scenarios
        SET run_status_id = ?
        WHERE scenario_name = ?;
        """

    spin_on_database_lock(
        conn=conn, cursor=c, sql=sql, data=(status_id, scenario), many=False
    )

    conn.commit()
    conn.close()


def record_process_id_and_start_time(db_path, scenario, process_id, start_time):
    """
    :param db_path:
    :param scenario:
    :param process_id:
    :param start_time:
    :return:

    Record the scenario run's process ID.
    """
    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    sql = """
        UPDATE scenarios
        SET run_process_id = ?,
        run_start_time = ?
        WHERE scenario_name = ?;
        """

    spin_on_database_lock(
        conn=conn,
        cursor=c,
        sql=sql,
        data=(process_id, start_time, scenario),
        many=False,
    )

    conn.commit()
    conn.close()


def record_end_time(db_path, scenario, process_id, end_time):
    """
    :param db_path:
    :param scenario:
    :param process_id:
    :param end_time:
    :return:

    Record the scenario run's process ID.
    """
    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    sql = """
        UPDATE scenarios
        SET run_end_time = ?
        WHERE scenario_name = ?
        AND run_process_id = ?;
        """

    spin_on_database_lock(
        conn=conn, cursor=c, sql=sql, data=(end_time, scenario, process_id), many=False
    )

    conn.commit()
    conn.close()


def check_if_in_queue(db_path, scenario):
    """
    :param db_path:
    :param scenario:
    :return:

    Check if we're running from the queue
    """
    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    queue_order_id = c.execute("""
        SELECT queue_order_id
        FROM scenarios
        WHERE scenario_name = '{}'
        """.format(scenario)).fetchone()[0]

    conn.commit()
    conn.close()

    return queue_order_id


def remove_from_queue_if_in_queue(db_path, scenario, queue_order_id):
    """
    :param db_path:
    :param scenario:
    :param queue_order_id:
    :return:

    If running from the queue, remove from the queue
    """

    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    if queue_order_id is not None:
        print("Removing scenario ID {} from queue".format(scenario))
        sql = """
            UPDATE scenarios SET queue_order_id = NULL WHERE scenario_name = ?
        """
        spin_on_database_lock(
            conn=conn, cursor=c, sql=sql, data=(scenario,), many=False
        )

    conn.commit()
    conn.close()


def step_timings_table_exists(cursor):
    """
    :param cursor:
    :return: boolean

    Check whether the status_e2e_step_timings table exists. Databases
    created before the table was added to the schema don't have it, in
    which case we skip recording step timings in the database.
    """
    return (
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'status_e2e_step_timings';"
        ).fetchone()
        is not None
    )


def clear_step_timings_in_db(db_path, scenario_id):
    """
    :param db_path:
    :param scenario_id:
    :return:

    Clear any step timings from previous runs of this scenario, so that the
    status_e2e_step_timings table only holds timings from the most recent
    run.
    """
    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    if step_timings_table_exists(cursor=c):
        sql = """
            DELETE FROM status_e2e_step_timings
            WHERE scenario_id = ?;
            """
        spin_on_database_lock(
            conn=conn, cursor=c, sql=sql, data=(scenario_id,), many=False
        )

    conn.commit()
    conn.close()


def record_step_timing_in_db(
    db_path, scenario_id, process_id, step, step_start_time, step_end_time
):
    """
    :param db_path:
    :param scenario_id:
    :param process_id:
    :param step: name of the E2E step that just finished
    :param step_start_time: the step start time
    :param step_end_time: the step end time
    :return:

    Record the step's start/end time and duration in the
    status_e2e_step_timings table.
    """
    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    if step_timings_table_exists(cursor=c):
        sql = """
            INSERT OR REPLACE INTO status_e2e_step_timings
            (scenario_id, run_process_id, e2e_step, step_start_time,
            step_end_time, duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?);
            """
        spin_on_database_lock(
            conn=conn,
            cursor=c,
            sql=sql,
            data=(
                scenario_id,
                process_id,
                step,
                str(step_start_time),
                str(step_end_time),
                (step_end_time - step_start_time).total_seconds(),
            ),
            many=False,
        )

    conn.commit()
    conn.close()


def record_step_timing(
    db_path,
    scenario_id,
    process_id,
    step,
    step_start_time,
    timing_summary_file_path,
    quiet,
):
    """
    :param db_path:
    :param scenario_id:
    :param process_id:
    :param step: name of the E2E step that just finished
    :param step_start_time: the step start time
    :param timing_summary_file_path: the timing summary file path (None if
        not logging)
    :param quiet: boolean
    :return:

    Print the step end time and duration (indented under the step's own
    starting print statement), append the step's timing to the timing
    summary file, and record it in the database.
    """
    step_end_time = datetime.datetime.now()
    if not quiet:
        print(
            "...E2E step '{}' finished on {} (duration {})".format(
                step, step_end_time, step_end_time - step_start_time
            )
        )
    append_to_timing_summary_file(
        timing_summary_file_path,
        "... {}: started on {}, finished on {}, duration {}".format(
            step, step_start_time, step_end_time, step_end_time - step_start_time
        ),
    )
    record_step_timing_in_db(
        db_path=db_path,
        scenario_id=scenario_id,
        process_id=process_id,
        step=step,
        step_start_time=step_start_time,
        step_end_time=step_end_time,
    )


def get_timing_summary_file_path(logs_directory, process_id, start_time):
    """
    :param logs_directory: the logs directory to write the summary file to
    :param process_id: the run's process ID
    :param start_time: the run start time
    :return: the timing summary file path

    The timing summary gets its own text file in the logs directory, named
    consistently with the run's log file.
    """
    return os.path.join(
        logs_directory,
        "e2e_timing_summary_{}_pid_{}.txt".format(
            string_from_time(start_time), str(process_id)
        ),
    )


def append_to_timing_summary_file(timing_summary_file_path, line):
    """
    :param timing_summary_file_path: the timing summary file path; None if
        no summary file is being kept (i.e. when not logging)
    :param line: the line to append
    :return:

    Append a line to the timing summary file. The summary is written as we
    go, so that it is available (with the steps completed so far) even if
    the run fails or is interrupted.
    """
    if timing_summary_file_path is not None:
        with open(timing_summary_file_path, "a") as summary_file:
            summary_file.write(line + "\n")


# TODO: add more run status types?
# TODO: handle error messages for parser: the argparser error message will refer
#   to run_end_to_end.py, even if the parsing fails at one of the scripts
#   being called here (e.g. run_scenario.py), while the listed arguments refer
#   to the parser used when the script fails
def main(args=None):
    """

    :param args:
    :return:
    """

    # Get process ID and start_time
    process_id = os.getpid()
    start_time = datetime.datetime.now()

    # Signal-handling directives
    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigint_handler)

    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args)

    # Log the run if requested
    # If directed to do so, log e2e run
    scenario_directory = determine_scenario_directory(
        scenario_location=parsed_args.scenario_location,
        scenario_name=parsed_args.scenario,
    )

    # The timing summary is written to its own file in the logs directory
    # (i.e. only when logging), as the run progresses
    timing_summary_file_path = None

    # TODO: why aren't we printing the log in the individual optimization
    #  directory
    if parsed_args.log:
        logs_directory = create_logs_directory_if_not_exists(
            scenario_directory=scenario_directory,
            weather_iteration="",
            hydro_iteration="",
            availability_iteration="",
            subproblem="",
            stage="",
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
            start_time=start_time,
            e2e=True,
            process_id=process_id,
        )
        sys.stdout = logger
        sys.stderr = logger

        timing_summary_file_path = get_timing_summary_file_path(
            logs_directory=logs_directory,
            process_id=process_id,
            start_time=start_time,
        )
        append_to_timing_summary_file(timing_summary_file_path, "E2E timing summary:")

    # Create connection
    db_path = parsed_args.database
    conn = connect_to_database(db_path=db_path)

    scenario_id, scenario = get_scenario_id_and_name(
        scenario_id_arg=parsed_args.scenario_id,
        scenario_name_arg=parsed_args.scenario,
        c=conn.cursor(),
        script="run_end_to_end",
    )
    conn.close()

    if not parsed_args.quiet:
        print("Running scenario {} end to end".format(scenario))

    # Check if running from queue
    queue_order_id = check_if_in_queue(db_path, scenario)

    # Update run status to 'running'
    update_run_status(db_path, scenario, 1)

    # Record process ID and process start time in database
    if not parsed_args.quiet:
        print("Process ID is {}".format(process_id))
        print("End-to-end run started on {}".format(start_time))
    record_process_id_and_start_time(
        db_path, parsed_args.scenario, process_id, start_time
    )

    # Clear any step timings from previous runs of this scenario
    clear_step_timings_in_db(db_path=db_path, scenario_id=scenario_id)

    # Figure out which steps we are skipping if user has requested a single
    # E2E step; start by assuming we'll skip and reverse skipping if the
    # step is specified
    skip_get_inputs = True
    skip_run_scenario = True
    skip_import_results = True
    skip_process_results = True

    if parsed_args.single_e2e_step_only == "get_inputs":
        skip_get_inputs = False
    elif parsed_args.single_e2e_step_only == "run_scenario":
        skip_run_scenario = False
    elif parsed_args.single_e2e_step_only == "import_results":
        skip_import_results = False
    elif parsed_args.single_e2e_step_only == "process_results":
        skip_process_results = False
    else:
        skip_get_inputs = False
        skip_run_scenario = False
        skip_import_results = False
        skip_process_results = False

    # Go through the steps if user has not requested to skip them
    if not skip_get_inputs and not parsed_args.skip_get_inputs:
        step_start_time = datetime.datetime.now()
        try:
            get_scenario_inputs.main(args=args)
        except Exception as e:
            logging.exception(e)
            end_time = update_db_for_run_end(
                db_path=db_path,
                scenario=scenario,
                queue_order_id=queue_order_id,
                process_id=process_id,
                run_status_id=3,
                start_time=start_time,
                timing_summary_file_path=timing_summary_file_path,
            )
            print(
                "Error encountered when getting inputs from the database for "
                "scenario {}. End time: {}. Total run time: {}.".format(
                    scenario, end_time, end_time - start_time
                )
            )
            sys.exit(1)
        record_step_timing(
            db_path=db_path,
            scenario_id=scenario_id,
            process_id=process_id,
            step="get_inputs",
            step_start_time=step_start_time,
            timing_summary_file_path=timing_summary_file_path,
            quiet=parsed_args.quiet,
        )

    if not skip_run_scenario and not parsed_args.skip_run_scenario:
        step_start_time = datetime.datetime.now()
        try:
            # make sure run_scenario.py gets the required --scenario argument
            run_scenario_args = args + ["--scenario", scenario]
            expected_objective_values = run_scenario.main(
                args=run_scenario_args,
            )
        except Exception as e:
            logging.exception(e)
            end_time = update_db_for_run_end(
                db_path=db_path,
                scenario=scenario,
                queue_order_id=queue_order_id,
                process_id=process_id,
                run_status_id=3,
                start_time=start_time,
                timing_summary_file_path=timing_summary_file_path,
            )
            print(
                "Error encountered when running scenario {}. End time: {}. "
                "Total run time: {}.".format(scenario, end_time, end_time - start_time)
            )
            sys.exit(1)
        record_step_timing(
            db_path=db_path,
            scenario_id=scenario_id,
            process_id=process_id,
            step="run_scenario",
            step_start_time=step_start_time,
            timing_summary_file_path=timing_summary_file_path,
            quiet=parsed_args.quiet,
        )
    else:
        expected_objective_values = None

    if not skip_import_results and not parsed_args.skip_import_results:
        step_start_time = datetime.datetime.now()
        try:
            import_scenario_results.main(args=args)
        except Exception as e:
            logging.exception(e)
            end_time = update_db_for_run_end(
                db_path=db_path,
                scenario=scenario,
                queue_order_id=queue_order_id,
                process_id=process_id,
                run_status_id=3,
                start_time=start_time,
                timing_summary_file_path=timing_summary_file_path,
            )
            print(
                "Error encountered when importing results for "
                "scenario {}. End time: {}. Total run time: {}.".format(
                    scenario, end_time, end_time - start_time
                )
            )
            sys.exit(1)
        record_step_timing(
            db_path=db_path,
            scenario_id=scenario_id,
            process_id=process_id,
            step="import_results",
            step_start_time=step_start_time,
            timing_summary_file_path=timing_summary_file_path,
            quiet=parsed_args.quiet,
        )

    if not skip_process_results and not parsed_args.skip_process_results:
        step_start_time = datetime.datetime.now()
        try:
            process_results.main(args=args)
        except Exception as e:
            logging.exception(e)
            end_time = update_db_for_run_end(
                db_path=db_path,
                scenario=scenario,
                queue_order_id=queue_order_id,
                process_id=process_id,
                run_status_id=3,
                start_time=start_time,
                timing_summary_file_path=timing_summary_file_path,
            )
            print(
                "Error encountered when processing results for "
                "scenario {}. End time: {}. Total run time: {}.".format(
                    scenario, end_time, end_time - start_time
                )
            )
            sys.exit(1)
        record_step_timing(
            db_path=db_path,
            scenario_id=scenario_id,
            process_id=process_id,
            step="process_results",
            step_start_time=step_start_time,
            timing_summary_file_path=timing_summary_file_path,
            quiet=parsed_args.quiet,
        )

    # If we make it here, mark run as complete and update run end time
    end_time = update_db_for_run_end(
        db_path=db_path,
        scenario=scenario,
        queue_order_id=queue_order_id,
        process_id=process_id,
        run_status_id=2,
        start_time=start_time,
        timing_summary_file_path=timing_summary_file_path,
    )
    # TODO: should the process ID be set back to NULL?
    if not parsed_args.quiet:
        print(
            "Done. Run finished on {}. Total run time: {}.".format(
                end_time, end_time - start_time
            )
        )

    # If logging, we need to return sys.stdout to original (i.e. stop writing
    # to log file) and close the log file to release file descriptor
    if parsed_args.log:
        logger.close()
        sys.stdout = stdout_original
        sys.stderr = stderr_original

    # Return expected objective values (for testing)
    if parsed_args.testing:
        return expected_objective_values


def update_db_for_run_end(
    db_path,
    scenario,
    queue_order_id,
    process_id,
    run_status_id,
    start_time,
    timing_summary_file_path,
):
    """
    Make the necessary database updates when a run ends (remove from queue,
    update the run status, and record the end time), and append the total
    run time to the timing summary file (if one is being kept). This is
    called both when the run finishes successfully and when a step fails,
    so the summary file gets the total run time either way.
    """

    end_time = datetime.datetime.now()
    remove_from_queue_if_in_queue(db_path, scenario, queue_order_id)
    update_run_status(db_path, scenario, run_status_id)
    record_end_time(
        db_path=db_path, scenario=scenario, process_id=process_id, end_time=end_time
    )
    append_to_timing_summary_file(
        timing_summary_file_path,
        "... total run time: {}".format(end_time - start_time),
    )

    return end_time


# TODO: need to make sure that the database can be closed properly, pending
#  transactions rolled back, etc.
def exit_gracefully():
    """
    Clean up before exit
    """
    print("Exiting gracefully")
    args = sys.argv[1:]
    parsed_args = parse_arguments(args)

    db_path = parsed_args.database
    conn = connect_to_database(db_path)
    scenario_id, scenario = get_scenario_id_and_name(
        scenario_id_arg=parsed_args.scenario_id,
        scenario_name_arg=parsed_args.scenario,
        c=conn.cursor(),
        script="run_end_to_end",
    )

    # Check if running from queue
    queue_order_id = check_if_in_queue(db_path, scenario)
    remove_from_queue_if_in_queue(db_path, scenario, queue_order_id)
    update_run_status(db_path, scenario, 4)

    conn.commit()
    conn.close()


def sigterm_handler(signal, frame):
    """
    Exit when SIGTERM received
    :param signal:
    :param frame:
    :return:
    """
    print("SIGTERM received by run_end_to_end.py. Terminating process.")
    exit_gracefully()
    sys.exit()


def sigint_handler(signal, frame):
    """
    Exit when SIGINT received
    :param signal:
    :param frame:
    :return:
    """
    print("SIGINT received by run_end_to_end.py. Terminating process.")
    exit_gracefully()
    sys.exit()


if __name__ == "__main__":
    main(args=sys.argv[1:])
