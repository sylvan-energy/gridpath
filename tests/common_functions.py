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

import csv
import os
import shutil
import tempfile

from pyomo.environ import AbstractModel, DataPortal
from gridpath.auxiliary.dynamic_components import DynamicComponents


def add_model_components(
    prereq_modules,
    module_to_test,
    model,
    d,
    test_data_dir,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    Create abstract model, add components from prerequisite modules, add
    components from the module being tested
    :param prereq_modules:
    :param module_to_test:
    :param model:
    :param dynamic_inputs:
    :return:
    """
    for m in prereq_modules:
        if hasattr(m, "add_model_components"):
            m.add_model_components(
                model,
                d,
                test_data_dir,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            )
    if hasattr(module_to_test, "add_model_components"):
        module_to_test.add_model_components(
            model,
            d,
            test_data_dir,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
        )

    return model


def create_abstract_model(
    prereq_modules,
    module_to_test,
    test_data_dir,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    Determine dynamic components and build abstract model
    :param prereq_modules:
    :param module_to_test:
    :param test_data_dir:
    :param stage:
    :param stage:
    :return:
    """
    d = DynamicComponents()
    m = AbstractModel()
    add_model_components(
        prereq_modules,
        module_to_test,
        m,
        d,
        test_data_dir,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    )

    return m, d


def add_components_and_load_data(
    prereq_modules,
    module_to_test,
    test_data_dir,
    weather_iteration,
    hydro_iteration,
    availability_iteration,
    subproblem,
    stage,
):
    """
    Test that data are loaded with no errors
    :return:
    """

    m, d = create_abstract_model(
        prereq_modules,
        module_to_test,
        test_data_dir,
        weather_iteration,
        hydro_iteration,
        availability_iteration,
        subproblem,
        stage,
    )
    data = DataPortal()
    for mod in prereq_modules:
        if hasattr(mod, "load_model_data"):
            mod.load_model_data(
                m,
                d,
                data,
                test_data_dir,
                weather_iteration,
                hydro_iteration,
                availability_iteration,
                subproblem,
                stage,
            )
    if hasattr(module_to_test, "load_model_data"):
        module_to_test.load_model_data(
            m,
            d,
            data,
            test_data_dir,
            weather_iteration,
            hydro_iteration,
            availability_iteration,
            subproblem,
            stage,
        )

    return m, data


def _stage_test_data(test_case, test_data_dir):
    """
    Copy *test_data_dir* to a temporary directory (removed when *test_case*
    finishes) and return the copy.
    """
    staged = tempfile.mkdtemp()
    test_case.addCleanup(shutil.rmtree, staged, ignore_errors=True)
    staged_dir = os.path.join(staged, "test_data")
    shutil.copytree(test_data_dir, staged_dir)

    return staged_dir


def _edit_tab_file(path, edit_row):
    """
    Rewrite the tab file at *path*, calling *edit_row(header, row)* on every
    data row (both lists of strings) so it can change cells in place. The
    file's line terminator is preserved.
    """
    with open(path, newline="") as f:
        raw = f.read()
    terminator = "\r\n" if "\r\n" in raw else "\n"
    rows = list(csv.reader(raw.splitlines(), delimiter="\t"))
    header = rows[0]
    for row in rows[1:]:
        edit_row(header, row)
    with open(path, "w", newline="") as f:
        csv.writer(f, delimiter="\t", lineterminator=terminator).writerows(rows)


def stage_test_data_with_appended_rows(test_case, test_data_dir, tab_file, rows):
    """
    Copy *test_data_dir* to a temporary directory (removed when *test_case*
    finishes) and append *rows* (lists of cell values) to its
    inputs/*tab_file*. Returns the staged directory.
    """
    staged_dir = _stage_test_data(test_case, test_data_dir)
    path = os.path.join(staged_dir, "inputs", tab_file)
    with open(path, newline="") as f:
        raw = f.read()
    terminator = "\r\n" if "\r\n" in raw else "\n"
    with open(path, "a", newline="") as f:
        if raw and not raw.endswith(("\n", "\r")):
            f.write(terminator)
        csv.writer(f, delimiter="\t", lineterminator=terminator).writerows(rows)

    return staged_dir


def stage_test_data_with_blanked_cells(
    test_case, test_data_dir, tab_file, where, blank
):
    """
    Copy *test_data_dir* to a temporary directory (removed when *test_case*
    finishes) and, in its inputs/*tab_file*, set the *blank* columns to "."
    (Pyomo's "no value", so the param falls back to its default) in every row
    whose values match the column -> value pairs in *where*. Returns the
    staged directory.

    Lets a test exercise "input left unspecified" behavior (e.g. a limit at
    its infinite default) without a second fixture tree.
    """
    staged_dir = _stage_test_data(test_case, test_data_dir)

    def edit_row(header, row):
        if all(row[header.index(col)] == str(val) for col, val in where.items()):
            for col in blank:
                row[header.index(col)] = "."

    _edit_tab_file(os.path.join(staged_dir, "inputs", tab_file), edit_row)

    return staged_dir


def stage_test_data_with_timepoint_weights(
    test_case, test_data_dir, weight_by_timepoint
):
    """
    Copy *test_data_dir* to a temporary directory (removed when *test_case*
    finishes) and set the timepoint_weight of the timepoints in
    *weight_by_timepoint* (timepoint -> weight) in its inputs/timepoints.tab.
    Returns the staged directory.

    The fixture's weights are all 1, so this is how a test gets a horizon
    whose timepoints carry different weights.
    """
    staged_dir = _stage_test_data(test_case, test_data_dir)

    def edit_row(header, row):
        tmp = int(row[header.index("timepoint")])
        if tmp in weight_by_timepoint:
            row[header.index("timepoint_weight")] = str(weight_by_timepoint[tmp])

    _edit_tab_file(os.path.join(staged_dir, "inputs", "timepoints.tab"), edit_row)

    return staged_dir
