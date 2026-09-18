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

""" """

import csv
import os.path
import pandas as pd


# TODO: use this in capacity and operational type project subset
#  determinations
def determine_project_subset(
    scenario_directory,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
    column,
    type,
    prj_or_tx,
):
    """
    :param scenario_directory:
    :param subproblem:
    :param stage:
    :param column:
    :param type:
    :return:

    """

    project_subset = list()

    dynamic_components = pd.read_csv(
        os.path.join(
            scenario_directory,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
            "inputs",
            "{}s.tab".format(prj_or_tx),
        ),
        sep="\t",
        usecols=[prj_or_tx, column],
    )

    for row in zip(dynamic_components[prj_or_tx], dynamic_components[column]):
        if row[1] == type:
            project_subset.append(row[0])

    return project_subset


def get_energy_budget_balancing_type(mod, prj, energy_budget_balancing_type_param):
    """
    The balancing type of the horizons over which the project's energy
    budgets (and per-horizon budget-related limits) apply: the project's
    optional ``energy_budget_balancing_type`` characteristic if specified,
    otherwise its ``balancing_type_project``. The latter continues to govern
    chronology (ramps and horizon-boundary handling) in either case, so a
    project can e.g. be budgeted by month while ramping continuously across
    month boundaries.

    :param mod: the Pyomo model
    :param prj: the project
    :param energy_budget_balancing_type_param: the operational type's
        ``{op_type}_energy_budget_balancing_type`` Param (no default, so
        specification is tested via sparse membership)
    :return: the balancing type
    """
    if not energy_budget_balancing_type_param.is_constructed():
        # Pyomo constructs components in declaration order and membership
        # in a not-yet-constructed Param is silently False, i.e. the
        # fallback would be taken for every project with no error: declare
        # the Param before the component whose initializer calls this
        raise RuntimeError(
            f"{energy_budget_balancing_type_param.name} has not been "
            f"constructed yet: declare it before the component whose "
            f"initializer reads it."
        )
    if prj in energy_budget_balancing_type_param:
        return energy_budget_balancing_type_param[prj]
    else:
        return mod.balancing_type_project[prj]


def check_if_first_timepoint(mod, tmp, balancing_type):
    return tmp == mod.first_hrz_tmp[balancing_type, mod.horizon[tmp, balancing_type]]


def check_if_last_timepoint(mod, tmp, balancing_type):
    return tmp == mod.last_hrz_tmp[balancing_type, mod.horizon[tmp, balancing_type]]


def check_boundary_type(mod, tmp, balancing_type, boundary_type):
    return (
        mod.boundary[balancing_type, mod.horizon[tmp, balancing_type]] == boundary_type
    )


def check_if_boundary_type_and_first_timepoint(mod, tmp, balancing_type, boundary_type):
    if check_if_first_timepoint(
        mod=mod, tmp=tmp, balancing_type=balancing_type
    ) and check_boundary_type(
        mod=mod, tmp=tmp, balancing_type=balancing_type, boundary_type=boundary_type
    ):
        return True
    else:
        return False


def check_if_boundary_type_and_last_timepoint(mod, tmp, balancing_type, boundary_type):
    if check_if_last_timepoint(
        mod=mod, tmp=tmp, balancing_type=balancing_type
    ) and check_boundary_type(
        mod=mod, tmp=tmp, balancing_type=balancing_type, boundary_type=boundary_type
    ):
        return True
    else:
        return False


def get_column_row_value(header, column_name, row):
    """
    :param header: list; the CSV file header (list of column names)
    :param column_name: string; the column name we're looking for
    :param row: list; the values in the current row
    :return:

    Check if the header contains the column_name; if not, return None for
    the value for this column_name in this row; if it does, get the right
    value from the value based on the column_name index in the header.
    """
    try:
        column_index = header.index(column_name)
    except ValueError:
        column_index = None

    row_column_value = None if column_index is None else row[column_index]

    return row_column_value


def append_to_input_file(
    inputs_directory, input_file, query_results, index_n_columns, new_column_names
):
    """

    :param inputs_directory:
    :param input_file:
    :param query_results:
    :param new_column_names:
    :return:
    """

    # Make a dictionary by project for easy access
    dict_by_project = dict()
    for row in query_results:
        indx = tuple(row[:index_n_columns])
        indx_char = row[index_n_columns:]
        # Assign values for each project key
        # Replace None values with "." to feed into Pyomo
        dict_by_project[indx] = ["." if x is None else x for x in indx_char]

    # Open the projects file

    with open(os.path.join(inputs_directory, input_file), "r") as f_in:
        # Read in the file
        reader = csv.reader(f_in, delimiter="\t", lineterminator="\n")

        # We'll be changing each row of the reader and adding the updated
        # row to this list
        new_rows = list()

        # First, add the new items to the header and append the updated
        # header to the new_rows list
        header = next(reader)
        for h in new_column_names:
            header.append(h)
        new_rows.append(header)

        # Next, append the new values to the row for each project and add
        # the updated row to the new_rows list
        for row in reader:
            indx = tuple(row[:index_n_columns])
            # If the project is in the dictionary keys, add the values from
            # the dictionary to the project row and append the updated row
            # to the new_rows list
            if indx in list(dict_by_project.keys()):
                for char in dict_by_project[indx]:
                    row.append(char)
                new_rows.append(row)
            # If project is not in the dictionary keys, fill the row with
            # "." to feed empty values into Pyomo and append the updated row
            # to the new_rows list
            else:
                for h in new_column_names:
                    row.append(".")
                new_rows.append(row)

    # Now that we have updated all our rows, overwrite the previous
    # projects.tab file
    with open(os.path.join(inputs_directory, input_file), "w", newline="") as f_out:
        writer = csv.writer(f_out, delimiter="\t", lineterminator="\n")
        writer.writerows(new_rows)
