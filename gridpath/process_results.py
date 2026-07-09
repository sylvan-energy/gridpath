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
This script iterates over all modules required for a GridPath scenario and
calls their *process_results()* method, which makes updates to database
tables.

The main() function of this script can also be called with the
*gridpath_process_results* command when GridPath is installed.
"""

from argparse import ArgumentParser
import sys

from db.common_functions import connect_to_database, update_db_last_modified
from gridpath.common_functions import (
    determine_scenario_directory,
    get_db_parser,
    get_required_e2e_arguments_parser,
    get_version_parser,
)
from gridpath.auxiliary.db_interface import get_scenario_id_and_name
from gridpath.auxiliary.module_list import determine_modules, load_modules
from gridpath.auxiliary.scenario_chars import SubScenarios


def process_results(loaded_modules, db, cursor, scenario_id, subscenarios, quiet):
    """

    :param loaded_modules:
    :param db:
    :param cursor:
    :param subscenarios:
    :param quiet:
    :return:
    """
    for m in loaded_modules:
        if hasattr(m, "process_results"):
            m.process_results(db, cursor, scenario_id, subscenarios, quiet)


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
            get_required_e2e_arguments_parser(),
            get_version_parser(),
        ],
    )
    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    """

    :return:
    """
    if args is None:
        args = sys.argv[1:]

    parsed_arguments = parse_arguments(args=args)

    db_path = parsed_arguments.database
    scenario_id_arg = parsed_arguments.scenario_id
    scenario_name_arg = parsed_arguments.scenario
    scenario_location = parsed_arguments.scenario_location

    conn = connect_to_database(db_path=db_path)
    c = conn.cursor()

    if not parsed_arguments.quiet:
        print("Processing results... (connected to database {})".format(db_path))

    scenario_id, scenario_name = get_scenario_id_and_name(
        scenario_id_arg=scenario_id_arg,
        scenario_name_arg=scenario_name_arg,
        c=c,
        script="process_results",
    )

    # Determine scenario directory
    scenario_directory = determine_scenario_directory(
        scenario_location=scenario_location, scenario_name=scenario_name
    )

    # Go through modules
    modules_to_use = determine_modules(scenario_directory=scenario_directory)
    loaded_modules = load_modules(modules_to_use)

    # Subscenarios
    subscenarios = SubScenarios(conn=conn, scenario_id=scenario_id)

    process_results(
        loaded_modules=loaded_modules,
        db=conn,
        cursor=c,
        scenario_id=scenario_id,
        subscenarios=subscenarios,
        quiet=parsed_arguments.quiet,
    )

    update_db_last_modified(conn=conn, modification_type="results_process")

    # Close the database connection
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
