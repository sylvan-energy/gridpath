# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

"""
The *gridpath_load_csvs* command ports the input data provided through CSV
files to the GridPath SQLite database. It assumes that the user has
already created the database file and loaded the GridPath schema using the
*gridpath_create_database* command.

The gridpath_load_csvs command takes several arguments. For usage info, run:

>>> gridpath_load_csvs --help

The user must specify the GridPath database path using the *--database* flag
and the path to the directory where the CSVs are located using the
*--csv_location* flag.

>>> gridpath_load_csvs --database PATH/DO/DB --csv_location PATH/TO/CSVS


Running the command above will look for the *csv_structure.csv* file in
the *PATH/TO/CSVS* directory and use the information in this file to
determine which CSV files to import. The template *csv_structure.csv* file
is located in the *db/cvs_test_examples* directory. This file has the list
of all the subscenarios and associated tables in the GridPath database. CSV
data is imported if the user specifies a path in the *path* column of the file.
This path should be relative to the *PATH/TO/CSVS* directory. Other columns
of this file should not be modified by the user with the exception of the
*cols_to_exclude_str* column. In this column, the user can specify a string,
which, if it is the beginning of the header of a column in the CSV input file,
will tell the port script to ignore the data in that column instead of
attempting to import it.

The script will look for CSV files in the path specified by the user for each
subscenario.

If no name has been specified for a subscenario/table in the  *filename* column
of the *csv_structure.csv* file, the script is expecting that the CSV
filename will conform to a certain structure, indicating the ID and name of
the subscenario the file contains data for, with the ID and name separated
by an underscore. For example, to load data for different project portfolio
subscenarios, the user must first specify the path where the project
portfoio CSVs are located in the *path* column of the
*project_portfolio_scenario_id* row of the *csv_structure.csv* file. In
this directory, the user must include a file for each portfolio they want to
be able to model, e.g. *1_base.csv* for project_portfolio_scenario_id 1 and
*2_extra_project.csv* for project_portfolio_scenario_id 2. CSVs for
subscenarios flagged with 1 in the *sub_input_flag* column of the
*csv_structure.csv* file require that the filename consist of the project
name, subscenario ID, and subscenario name, separated by dashes, e.g. two
profiles for a project named 'Solar' can be specified in the files named
*Solar-1-base.csv* and *Solar-2-high.csv* respectively. Note that project
filenames should not include dashes. Use the same format for transmission
lines and reservoirs. To tell GridPath what the column name is for these
types of inputs, include it in the sub_input_column field (e.g., project,
transmission_line, or reservoir).

The user can specify that a subscenario ID is based on another "default"
subscenario ID. This is done by ending the CSV filename for the subscenario
ID with a dash followed by the default subscenario ID. For example,
*3_base_with_change-1.csv* indicates that the subscenario ID 3 should use
values from the default subscenario ID 1 except for the values specified in the
3_base_with_change-1.csv.
.. warning:: This functionality is new and hasn't been extensively used and
tested yet, so please proceed with caution.

A few subscenarios consist of multiple tables data for which is located
inside CSVs in the same directory. For these subscenarios, the directory
name should begin with the subscenario ID followed by an underscore and then
the scenario name. The names of the files expected inside the directory are
specified in the *csv_structure.csv* file in the *filename* column. For
example, a *temporal_scenario_id* directory must contain files named
*period_params.csv*, *horizon_params.csv*, *structure.csv*, and
*horizon_timepoints.csv*.

The *scenarios.csv* under the scenario folder contains the subscenario ID
specifications for each scenario to be loaded. The user-defined name of the
scenario should be entered as the name of the scenario column.

"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import numpy as np
import os
import pandas as pd
import sqlite3
import sys

# Data-import modules
from db.common_functions import connect_to_database, update_db_last_modified
from db.utilities.common_functions import (
    load_all_subscenario_ids_from_dir_to_subscenario_table,
    load_single_subscenario_id_from_dir_to_subscenario_table,
    generic_delete_subscenario,
    determine_tables_to_delete_from,
    confirm_and_temp_update_affected_tables,
    repopulate_tables,
    verify_sub_input_flag_project_alignment,
)


def parse_arguments(args):
    """
    :param args: the script arguments specified by the user
    :return: the parsed known argument values (<class 'argparse.Namespace'>
    Python object)

    Parse the known arguments.
    """
    parser = ArgumentParser(add_help=True, parents=[get_version_parser()])

    # Database name and location options
    parser.add_argument(
        "--database",
        default="../io.db",
        help="The database file path relative to the current "
        "working directory. Defaults to ./io.db ",
    )
    parser.add_argument(
        "--csv_location",
        default="../csvs_test_examples",
        help="Path to the csvs folder including folder name "
        "relative to the current working directory.",
    )
    parser.add_argument(
        "--subscenario",
        default=None,
        help="The subscenario to load. The script will look "
        "for the directory where data for the "
        "subscenario are located based on the "
        "csv_structure file and will load all subscenario "
        "IDs located there.",
    )
    parser.add_argument(
        "--subscenario_id",
        default=None,
        help="The subscenario ID to load. The "
        "'--subscenario' argument must also be "
        "specified. The script will look for the "
        "directory where data for the subscenario are "
        "located based on the csv_structure file and will "
        "load the data for this subscenario ID.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="The project for which to load data. The "
        "'--subscenario' and '--subscenario_id' "
        "arguments must also be specified, and this "
        "must be a project-level subscenario. The script "
        "will look for the directory where data for the "
        "subscenario are located based on the "
        "csv_structure file and will load the data for "
        "this project and subscenario ID.",
    )
    parser.add_argument(
        "--delete",
        default=False,
        action="store_true",
        help="Delete prior data. Defaults to False.",
    )
    parser.add_argument(
        "--turn_off_fk",
        default=False,
        action="store_true",
        help="Turn off foreign key enforcement. Can be helpful when trying to "
        "delete and reload data, but please proceed with caution.",
    )
    parser.add_argument(
        "--quiet",
        default=False,
        action="store_true",
        help="Don't print output. Defaults to False.",
    )

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def load_all_from_csv_structure(conn, csv_path, csv_structure, quiet):
    """
    :param conn: the database connection
    :param csv_path: str, the directory where the CSV files are located
    :param csv_structure: Pandas dataframe of the CSV structure file
    :param quiet: boolean for whether to print output
    :return:

    Read and load all data specified in the CSV structure file.
    """
    # LOAD ALL SUBSCENARIOS WITH NON-CUSTOM INPUTS #
    for index, row in csv_structure.iterrows():
        # Load data if a directory is specified for this table
        if isinstance(row["path"], str):
            subscenario = row["subscenario"]
            (
                table,
                inputs_dir,
                sub_input_flag,
                sub_input_column,
                cols_to_exclude_str,
                custom_method,
                subscenario_type,
                filename,
            ) = parse_row(row=row, csv_path=csv_path)
            if not quiet:
                print(
                    "Importing data for subscenario {}, table {} from {}"
                    "...".format(subscenario, table, inputs_dir)
                )
            load_all_subscenario_ids_from_dir_to_subscenario_table(
                conn,
                subscenario,
                table,
                subscenario_type,
                sub_input_flag,
                sub_input_column,
                cols_to_exclude_str,
                custom_method,
                inputs_dir,
                filename,
                quiet,
            )

        conn.commit()


def load_all_subscenario_ids_from_directory(
    conn, csv_path, csv_structure, subscenario, quiet
):
    """
    :param conn: the database connection
    :param csv_path: str, the directory where the CSV files are located
    :param csv_structure: Pandas dataframe of the CSV structure file
    :param subscenario: str; the subscenario for which to load data (e.g.
        temporal_scenario_id or project_portfolio_scenario_id)
    :param quiet: boolean for whether to print output
    :return:

    Read and load all data for a particular subscenario (e.g. for the
    subscenario temporal_scenario_id).
    """
    for index, row in csv_structure.iterrows():
        # Load data if a directory is specified for this table
        if isinstance(row["path"], str) and row["subscenario"] == subscenario:
            (
                table,
                inputs_dir,
                sub_input_flag,
                sub_input_column,
                cols_to_exclude_str,
                custom_method,
                subscenario_type,
                filename,
            ) = parse_row(row=row, csv_path=csv_path)
            load_all_subscenario_ids_from_dir_to_subscenario_table(
                conn=conn,
                subscenario=subscenario,
                table=table,
                subscenario_type=subscenario_type,
                sub_input_flag=sub_input_flag,
                sub_input_column=sub_input_column,
                cols_to_exclude_str=cols_to_exclude_str,
                custom_method=custom_method,
                inputs_dir=inputs_dir,
                filename=filename,
                quiet=quiet,
            )


def load_single_subscenario_id_from_directory(
    conn,
    csv_path,
    csv_structure,
    subscenario,
    subscenario_id_to_load,
    project,
    delete_flag,
    quiet,
):
    """
    :param conn: the database connection
    :param csv_path: str, the directory where the CSV files are located
    :param csv_structure: Pandas dataframe of the CSV structure file
    :param subscenario: str; the subscenario for which to load data (e.g.
        temporal_scenario_id or project_portfolio_scenario_id)
    :param subscenario_id_to_load: int; the subscenario ID for which to load
        data
    :param project: str; the project for which to load data
    :param delete_flag: boolean for whether to delete prior data
    :param quiet: boolean for whether to print output
    :return:

    Read and load all data for a particular subscenario ID (e.g. for
    temporal_scenario_id=5) or project-subscenario ID (e.g. for project
    'Solar' and variable_generator_scenario_id=1).

    If the delete_flag is turned on, we will first delete prior data for the
    (project-)subscenario_id specified.
    """

    # Delete prior data if instructed to
    if delete_flag:
        # Determine the relevant tables we'll need to delete prior data from
        # If we're dealing with project-level data, we'll also get the
        # base_table and base_subscenario (e.g. the opchar table for
        # variable generator profiles); otherwise, these will be None
        (
            subscenario_table,
            input_tables,
            sub_input_flag,
            sub_input_column,
            base_table,
            base_subscenario,
        ) = determine_tables_to_delete_from(
            csv_structure=csv_structure, subscenario=subscenario
        )

        # Verify project-sub_input_flag aligmnet
        verify_sub_input_flag_project_alignment(
            project=project, sub_input_flag=sub_input_flag, subscenario=subscenario
        )

        # If this subscenario ID (or the base subscenario ID if
        # project-level data) is used in the scenarios table, we'll confirm
        # with the user that they want to update the inputs
        # We'll also need to temporarily NULLify this ID in the scenarios
        # table to avoid FOREIGN KEY errors when deleting the data
        (
            scenario_reupdate_tuples,
            base_subscenario_ids_str,
            base_subscenario_ids_data,
        ) = confirm_and_temp_update_affected_tables(
            conn=conn,
            sub_input_flag=sub_input_flag,
            sub_input_column=sub_input_column,
            subscenario=subscenario,
            subscenario_id=subscenario_id_to_load,
            project=project,
            base_table=base_table,
            base_subscenario=base_subscenario,
        )

        # Delete prior data
        generic_delete_subscenario(
            conn=conn,
            subscenario=subscenario,
            subscenario_id=subscenario_id_to_load,
            project=project,
            subscenario_table=subscenario_table,
            input_tables=input_tables,
            sub_input_flag=sub_input_flag,
            sub_input_column=sub_input_column,
        )

    # Import the data
    for index, row in csv_structure.iterrows():
        # Load data if a directory is specified for this table
        if isinstance(row["path"], str) and row["subscenario"] == subscenario:
            # Parse the row
            (
                table,
                inputs_dir,
                sub_input_flag,
                sub_input_column,
                cols_to_exclude_str,
                custom_method,
                subscenario_type,
                filename,
            ) = parse_row(row=row, csv_path=csv_path)

            # Verify project-sub_input_flag alignment
            verify_sub_input_flag_project_alignment(
                project=project, sub_input_flag=sub_input_flag, subscenario=subscenario
            )

            # Load the data for this (project-)subscenario_id
            load_single_subscenario_id_from_dir_to_subscenario_table(
                conn=conn,
                subscenario=subscenario,
                table=table,
                subscenario_type=subscenario_type,
                sub_input_flag=sub_input_flag,
                sub_input_column=sub_input_column,
                cols_to_exclude_str=cols_to_exclude_str,
                custom_method=custom_method,
                inputs_dir=inputs_dir,
                filename=filename,
                quiet=quiet,
                subscenario_id_to_load=subscenario_id_to_load,
                project=project,
            )

    # If data were deleted, repopulate the affected scenarios with the data
    # we NULLified above
    if delete_flag:
        repopulate_tables(
            conn=conn,
            sub_input_flag=sub_input_flag,
            sub_input_column=sub_input_column,
            subscenario=subscenario,
            subscenario_id=subscenario_id_to_load,
            project=project,
            base_table=base_table,
            base_subscenario=base_subscenario,
            scenario_reupdate_tuples=scenario_reupdate_tuples,
            base_subscenario_ids_str=base_subscenario_ids_str,
            base_subscenario_ids_data=base_subscenario_ids_data,
        )


def main(args=None):
    """
    The 'main' method parses the database name along with path as
    script arguments and loads the data in the database.
    """
    # Parse the arguments
    if args is None:
        args = sys.argv[1:]
    parsed_args = parse_arguments(args=args)

    # Get the database path
    db_path = parsed_args.database
    if not os.path.isfile(db_path):
        raise OSError(
            "The database file {} was not found. Did you mean to "
            "specify a different database?".format(os.path.abspath(db_path))
        )

    # Get the CSV directory
    csv_path = parsed_args.csv_location
    if not os.path.isdir(csv_path):
        raise OSError(
            "The csv folder {} was not found. Did you mean to "
            "specify a different csv folder?".format(os.path.abspath(csv_path))
        )

    #### CSV DATA ####
    csv_structure = pd.read_csv(os.path.join(csv_path, "csv_structure.csv"))

    # Register numpy types with sqlite, so that they are properly inserted
    # from pandas dataframes
    # https://stackoverflow.com/questions/38753737/inserting-numpy-integer-types-into-sqlite-with-python3
    sqlite3.register_adapter(np.int64, lambda val: int(val))
    sqlite3.register_adapter(np.float64, lambda val: float(val))

    # connect to database
    conn = connect_to_database(db_path=db_path)

    # Turn off foreign keys if requested
    if parsed_args.turn_off_fk:
        conn.execute("PRAGMA foreign_keys=OFF;")

    # Load all data in directory
    if (
        parsed_args.subscenario is None
        and parsed_args.subscenario_id is None
        and parsed_args.project is None
    ):
        load_all_from_csv_structure(
            conn=conn,
            csv_path=csv_path,
            csv_structure=csv_structure,
            quiet=parsed_args.quiet,
        )
    elif parsed_args.subscenario is not None and parsed_args.subscenario_id is None:
        # Load all IDs for a subscenario-table
        load_all_subscenario_ids_from_directory(
            conn, csv_path, csv_structure, parsed_args.subscenario, parsed_args.quiet
        )
    else:
        # Load single subscenario ID (or project-subscenario ID)
        load_single_subscenario_id_from_directory(
            conn=conn,
            csv_path=csv_path,
            csv_structure=csv_structure,
            subscenario=parsed_args.subscenario,
            subscenario_id_to_load=parsed_args.subscenario_id,
            project=parsed_args.project,
            delete_flag=parsed_args.delete,
            quiet=parsed_args.quiet,
        )

    update_db_last_modified(conn=conn, modification_type="inputs")

    # Commit and close connection
    conn.commit()
    conn.close()


def parse_row(row, csv_path):
    """
    :param row:
    :param csv_path:
    :return:

    Parse a row of the CSV structure file.
    """
    table = row["table"]
    inputs_dir = os.path.join(csv_path, row["path"])
    sub_input_flag = True if int(row["sub_input_flag"]) else False
    sub_input_column = row["sub_input_column"]
    cols_to_exclude_str = str(row["cols_to_exclude_str"])
    custom_method = str(row["custom_method"])
    subscenario_type = row["subscenario_type"]
    filename = row["filename"]

    return (
        table,
        inputs_dir,
        sub_input_flag,
        sub_input_column,
        cols_to_exclude_str,
        custom_method,
        subscenario_type,
        filename,
    )


if __name__ == "__main__":
    main()
