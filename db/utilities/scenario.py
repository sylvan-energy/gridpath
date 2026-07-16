# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

"""
You can use the *gridpath_load_scenarios* command to create, update, or delete
a scenario. You can create a single or multiple scenarios from a CSV.
This command assumes that the user has already created the database file
using the *gridpath_create_database* command and loaded input data for the
scenario using the *gridpath_load_csvs* command.

The *gridpath_load_scenarios* command takes several arguments. For usage info,
run:

>>> gridpath_load_scenarios --help

The user must specify the GridPath database path using the *--database* flag
and the path to the directory where the scenario CSV is located using the
*--csv_path* flag.

>>> gridpath_load_scenarios --database PATH/DO/DB --csv_path PATH/TO/SCENARIO/CSV

If you are using the csvs_test_examples directory included with GridPath, /PATH/TO/SCENARIO/CSV
can be set to ../csvs_test_examples/scenarios.csv.

To load a single scenario by name, use the *--scenario* flag. To delete a scenario from
the database, specify the scenario name with the *--scenario* flag and use the
*--delete* flag.
"""

from argparse import ArgumentParser
from gridpath.common_functions import get_version_parser
import os.path
import pandas as pd
import sys
import warnings

from db.common_functions import (
    connect_to_database,
    spin_on_database_lock,
    update_db_last_modified,
)
from db.utilities.common_functions import confirm


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
        "working directory. Defaults to ../io.db ",
    )
    parser.add_argument(
        "--csv_path",
        default="../csvs_test_examples/scenarios.csv",
        help="Path to the scenarios CSV. Defaults to "
        "../csvs_test_examples/scenarios.csv",
    )
    parser.add_argument(
        "--scenario",
        help="The scenario to load (or delete). If not "
        "specified, the script will load data for all "
        "scenarios in the CSV.",
    )
    parser.add_argument(
        "--delete",
        default=False,
        action="store_true",
        help="Delete the specified scenario. No data "
        "will be imported. WARNING: this will delete "
        "all prior results and data associated with "
        "this scenario.",
    )
    parser.add_argument(
        "--quiet", default=False, action="store_true", help="Don't print output."
    )

    parsed_arguments = parser.parse_known_args(args=args)[0]

    return parsed_arguments


def create_scenario(io, c, column_values_dict):
    """
    Flexible way to insert a scenario that does not require specifying
    values for all columns. Columns can be skipped entirely or None can be
    specified as their value (in which case this function will insert a NULL
    value for that column). The scenario_id column is auto increment, so
    should not be inserted directly. If the scenario_id is specified,
    it will be skipped (not inserted) and a warning will be raised.

    :param io: the database connection object
    :param c: database cursor object
    :param column_values_dict: dictionary containing the scenarios table
        column names to populate as keys and the scenarios table column
        values as the dictionary values
    :return: None
    """
    column_names_sql_string = str()
    column_values_sql_string = str()
    column_values_data = tuple()

    # TODO: add a check that the column names are correct and values are
    #  integers
    for column_name in column_values_dict.keys():
        if column_name == "scenario_id":
            warnings.warn(
                "The scenario_id is an AUTOINCREMENT column and should not be "
                "inserted directly. \n"
                "Your scenario will be assigned a scenario_id automatically.\n"
                "Remove the 'scenario_id' key from the dictionary to avoid "
                "seeing this warning again."
            )
        else:
            if list(column_values_dict.keys()).index(column_name) == 0:
                column_names_sql_string += "{}, ".format(column_name)
                column_values_sql_string += "?,"
                column_values_data = (column_values_dict[column_name],)
            elif (
                list(column_values_dict.keys()).index(column_name)
                == len(list(column_values_dict.keys())) - 1
            ):
                column_names_sql_string += "{}".format(column_name)
                column_values_sql_string += "?"
                column_values_data = column_values_data + (
                    column_values_dict[column_name],
                )
            else:
                column_names_sql_string += "{}, ".format(column_name)
                column_values_sql_string += "?,"
                column_values_data = column_values_data + (
                    column_values_dict[column_name],
                )

    sql = """
        INSERT INTO scenarios ({}) VALUES ({});
        """.format(column_names_sql_string, column_values_sql_string)

    spin_on_database_lock(
        conn=io, cursor=c, sql=sql, data=column_values_data, many=False
    )


def update_scenario_multiple_columns(io, c, scenario_name, column_values_dict):
    """

    :param io:
    :param c:
    :param scenario_name:
    :param column_values_dict:
    :return:
    """
    for column_name in column_values_dict:
        update_scenario_single_column(
            io=io,
            c=c,
            scenario_name=scenario_name,
            column_name=column_name,
            column_value=column_values_dict[column_name],
        )


def update_scenario_single_column(io, c, scenario_name, column_name, column_value):
    """

    :param io:
    :param c:
    :param scenario_name:
    :param column_name:
    :param column_value:
    :return:
    """
    # Update the column value for the scenario
    update_sql = """
        UPDATE scenarios
        SET {} = ?
        WHERE scenario_name = ?;
        """.format(column_name)

    spin_on_database_lock(
        conn=io,
        cursor=c,
        sql=update_sql,
        data=(column_value, scenario_name),
        many=False,
    )


def delete_scenario(conn, scenario_id):
    """
    :param conn: the database connection object
    :param scenario_id: the scenario_id to delete

    Delete a scenario fully, i.e. delete from all results tables, status
    tables, and the scenarios table.
    """
    # Delete results and statuses
    delete_scenario_results_and_status(conn=conn, scenario_id=scenario_id)

    # Delete from scenarios table
    c = conn.cursor()
    sc_id_sql = "DELETE FROM scenarios WHERE scenario_id = ?"
    spin_on_database_lock(
        conn=conn, cursor=c, sql=sc_id_sql, data=(scenario_id,), many=False
    )


def delete_scenario_results_and_status(conn, scenario_id):
    """
    :param conn:
    :param scenario_id:
    :return:

    Delete scenario results and statuses from relevant tables.
    """
    c = conn.cursor()
    all_tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    ).fetchall()

    results_tables = [tbl[0] for tbl in all_tables if tbl[0].startswith("results")]
    status_tables = [tbl[0] for tbl in all_tables if tbl[0].startswith("status")]

    # Delete from all results and status tables
    for tbl in results_tables + status_tables:
        sql = """
            DELETE FROM {} WHERE scenario_id = ?;
            """.format(tbl)
        spin_on_database_lock(
            conn=conn, cursor=c, sql=sql, data=(scenario_id,), many=False
        )

    # Update statuses in scenarios table to defaults
    status_sql = """
        UPDATE scenarios
        SET validation_status_id=0,
        queue_order_id=NULL,
        run_status_id=0, 
        run_process_id=NULL
        WHERE scenario_id = ?
    """
    spin_on_database_lock(
        conn=conn, cursor=c, sql=status_sql, data=(scenario_id,), many=False
    )


def delete_scenario_results(conn, scenario_id):
    """
    :param conn:
    :param scenario_id:
    :return:

    Delete prior results for this scenario from all results tables.
    """
    c = conn.cursor()
    all_tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    ).fetchall()

    results_tables = [tbl[0] for tbl in all_tables if tbl[0].startswith("results")]

    # Delete from all results tables
    for tbl in results_tables:
        sql = """
            DELETE FROM {} WHERE scenario_id = ?;
            """.format(tbl)
        spin_on_database_lock(
            conn=conn, cursor=c, sql=sql, data=(scenario_id,), many=False
        )


def check_if_scenario_name_exists(conn, scenario_name):
    """
    :param conn: the database connection
    :param scenario_name: str; the scenario name
    :return: scenario_id; str or None
    """
    c = conn.cursor()

    sql = "SELECT scenario_id FROM scenarios WHERE scenario_name = ?"
    query = c.execute(sql, (scenario_name,)).fetchone()

    if query is None:
        scenario_id = None
    else:
        scenario_id = query[0]

    c.close()

    return scenario_id


def determine_scenarios_to_load(conn, scenarios_df, scenario_name=None):
    """
    :param conn: the database connection
    :param scenarios_df: pandas dataframe; the scenarios CSV as dataframe
    :param scenario_name: str; the scenario name

    """
    c = conn.cursor()

    # If no scenario is specified, we'll return all scenarios from the
    # dataframe as list
    if scenario_name is None:
        scenarios_to_load = scenarios_df.columns.to_list()[1:]
    # Otherwise, return only the scenario name specified in a list
    else:
        scenarios_to_load = [scenario_name]

    c.close()

    return scenarios_to_load


def load_scenario_from_df(conn, scenarios_df, scenario_name):
    """
    :param conn: the database connection
    :param scenarios_df: pandas dataframe; the scenarios CSV as dataframe
    :param scenario_name: str; the scenario name

    Load scenario info from CSV. If scenario is not specified, load all;
    otherwise, load only the specified scenario.
    """
    c = conn.cursor()

    # Convert the dataframe to dictionary
    scenario_info = scenarios_df.set_index("optional_feature_or_subscenarios")[
        scenario_name
    ].to_dict()

    # Add the scenario name
    scenario_info["scenario_name"] = scenario_name

    # Create the scenario (add to scenarios table)
    create_scenario(io=conn, c=c, column_values_dict=scenario_info)

    c.close()


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    parsed_args = parse_arguments(args=args)
    # Get the database path
    db_path = parsed_args.database
    scenarios_csv = parsed_args.csv_path
    scenario = parsed_args.scenario
    delete_flag = parsed_args.delete
    quiet = parsed_args.quiet

    # Check if database exists
    if not os.path.isfile(db_path):
        raise OSError(
            "The database file {} was not found. Did you mean to "
            "specify a different database?".format(os.path.abspath(db_path))
        )

    # Connect to database
    conn = connect_to_database(db_path=db_path)

    # Check if the user has requested that a scenario be deleted
    if delete_flag:
        if scenario is None:
            raise ValueError(
                "You must specify which scenario you'd like to "
                "delete with the '--delete' flag."
            )
        else:
            proceed = confirm(
                prompt="""WARNING: Would you like to delete all data associated 
                with scenario '{}'? If you select 'yes' all prior results 
                associated with scenario '{}' will be deleted.""".format(
                    scenario, scenario
                )
            )
            if proceed:
                sid = check_if_scenario_name_exists(conn=conn, scenario_name=scenario)
                if sid is None:
                    raise ValueError(
                        "Scenario {} not found in the " "database.".format(scenario)
                    )
                else:
                    delete_scenario(conn=conn, scenario_id=sid)
    # If '--delete' not specified, try to load data
    else:
        # Read in the CSV as dataframe
        csv_to_df = pd.read_csv(scenarios_csv)

        # Determine which scenario the user wants to load
        scenarios = determine_scenarios_to_load(
            conn=conn, scenarios_df=csv_to_df, scenario_name=scenario
        )

        # Iterate over the scenarios and check if this scenario name already exists
        if not quiet:
            print("Loading scenarios...")
        for scenario in scenarios:
            if not quiet:
                print("...{}".format(scenario))
            sid = check_if_scenario_name_exists(conn=conn, scenario_name=scenario)
            # If the scenario name does not exist, load the data
            if sid is None:
                load_scenario_from_df(
                    conn=conn, scenarios_df=csv_to_df, scenario_name=scenario
                )
            # If the scenario name exists, ask the user if they want to delete
            # prior data associated with this scenario and re-load the scenario
            # info
            else:
                proceed = confirm(
                    prompt="""There is already a scenario named '{}' in the 
                    database. Would you like to delete all data associated 
                    with this scenario and re-load the scenario definition info? 
                    WARNING: if you select 'yes' all prior results 
                    associated with scenario '{}' will be deleted.""".format(
                        scenario, scenario
                    )
                )
                if proceed:
                    delete_scenario(conn=conn, scenario_id=sid)
                    load_scenario_from_df(
                        conn=conn, scenarios_df=csv_to_df, scenario_name=scenario
                    )

    update_db_last_modified(conn=conn, modification_type="scenarios")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
