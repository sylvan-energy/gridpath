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
The generic *gridpath* command. GridPath's functionality lives in dedicated
commands (see below), so this command currently only reports information
about the GridPath package itself, e.g.:

>>> gridpath --version
"""

from argparse import ArgumentParser, RawDescriptionHelpFormatter
import sys

from gridpath.common_functions import get_version_parser

DESCRIPTION = """\
GridPath is a versatile power-system planning platform capable of a range of
planning approaches including production-cost, capacity-expansion, asset-
valuation, and reliability modeling.
"""

EPILOG = """\
GridPath's functionality is provided by dedicated commands, including:

  gridpath_create_database   create an empty GridPath database
  gridpath_load_csvs         load input CSVs into the database
  gridpath_load_scenarios    load scenario definitions into the database
  gridpath_validate          validate scenario inputs
  gridpath_get_inputs        write scenario input files from the database
  gridpath_run               run a scenario
  gridpath_run_e2e           run the end-to-end workflow
  gridpath_import_results    import scenario results into the database
  gridpath_process_results   post-process scenario results

Run any command with --help for usage info. For the full documentation,
see https://gridpath.readthedocs.io.
"""


def parse_arguments(args):
    """
    :param args: the command-line arguments
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(
        prog="gridpath",
        add_help=True,
        parents=[get_version_parser()],
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=RawDescriptionHelpFormatter,
    )

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    # Print the help message if called with no arguments
    if not args:
        args = ["--help"]

    parse_arguments(args=args)


if __name__ == "__main__":
    main()
