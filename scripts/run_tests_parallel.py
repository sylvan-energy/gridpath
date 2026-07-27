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
Run the GridPath test suite in three concurrent lanes, after building the
examples testing database once as a template (which the test classes then
copy instead of each rebuilding it; see set_up_test_database in
tests/test_examples.py):

- Lane 1 (pytest-xdist): everything that is safe to run concurrently.
  Each worker gets its own copy of the unittest_examples database (see
  the PYTEST_XDIST_WORKER handling in tests/test_examples.py).
- Lane 2 (serial): tests/test_data_toolkit and
  tests/test_run_data_toolkit.py, which regenerate committed fixture CSVs
  under db/csvs_test_examples/, some of which both file sets write — so
  they must not overlap each other. Nothing else reads those CSVs while
  tests run (the testing database is built from them beforehand).
- Lane 3 (serial): tests/test_viz.py, which solves several example
  scenarios in one setUpClass. It is self-contained (template-database
  copy plus a temporary copy of the scenario directories) but gets its
  own serial lane because worksteal scheduling in lane 1 would re-run
  that expensive setUpClass on every worker that picks up one of its
  tests.

The three lanes touch disjoint sets of files, so they run concurrently —
except under --coverage, where they run sequentially because they would
otherwise race on the .coverage data file.

Usage:
    python scripts/run_tests_parallel.py [--coverage]

Requires the "parallel_tests" extra (pip install -e .[parallel_tests]);
--coverage additionally requires the "coverage" extra and leaves a
combined .coverage file at the repo root (pytest-cov measures the xdist
worker processes, which a plain "coverage run -m pytest" would miss).
"""

import argparse
import os
import sqlite3
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tests that regenerate committed fixture CSVs under db/csvs_test_examples/
# (lane 2) and the self-contained but expensive-setup viz tests (lane 3);
# both excluded from the pytest-xdist lane (see module docstring)
TOOLKIT_TEST_PATHS = [
    "tests/test_data_toolkit",
    "tests/test_run_data_toolkit.py",
]
VIZ_TEST_PATH = "tests/test_viz.py"


# Where to pre-build the examples testing database that the test classes
# then copy instead of each rebuilding it from the CSVs; the path is passed
# to the test processes via this environment variable (see
# set_up_test_database in tests/test_examples.py)
DB_TEMPLATE_ENV_VAR = "GRIDPATH_TEST_EXAMPLES_DB_TEMPLATE"
DB_TEMPLATE_PATH = os.path.join(REPO_ROOT, "db", "unittest_examples_template.db")


def remove_template_files(sidecars_only=False):
    paths = [f"{DB_TEMPLATE_PATH}-shm", f"{DB_TEMPLATE_PATH}-wal"]
    if not sidecars_only:
        paths.append(DB_TEMPLATE_PATH)
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


def run_sequentially(lanes, env):
    for name, cmd in lanes:
        print(f"=== {name} ===", flush=True)
        returncode = subprocess.run(cmd, cwd=REPO_ROOT, env=env).returncode
        if returncode != 0:
            sys.exit(returncode)


def run_concurrently(lanes, env):
    processes = [
        (
            name,
            subprocess.Popen(
                cmd,
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ),
        )
        for name, cmd in lanes
    ]
    print(
        "Running concurrently: " + ", ".join(name for name, _ in processes),
        flush=True,
    )
    failed = False
    for name, process in processes:
        output = process.communicate()[0]
        print(f"=== {name} ===\n{output}", flush=True)
        if process.returncode != 0:
            failed = True
    if failed:
        sys.exit(1)


def main(args=None):
    if args is None:
        args = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="measure test coverage via pytest-cov (combined .coverage "
        "file at the repo root)",
    )
    parsed_args = parser.parse_args(args)

    xdist_cmd = [sys.executable, "-m", "pytest", "tests", "-n", "auto"]
    xdist_cmd += ["--dist", "worksteal", "-q"]
    # The --ignore paths must be absolute: some test modules os.chdir at
    # import time, which happens mid-collection, and pytest resolves
    # relative --ignore paths against the current working directory when
    # it visits each directory — so relative ignores stop matching after
    # the chdir
    for path in TOOLKIT_TEST_PATHS + [VIZ_TEST_PATH]:
        xdist_cmd.append("--ignore=" + os.path.join(REPO_ROOT, *path.split("/")))

    # The serial lanes disable the pytest cache plugin so that they don't
    # race the xdist lane on writing .pytest_cache
    toolkit_cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    toolkit_cmd += TOOLKIT_TEST_PATHS
    viz_cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    viz_cmd += [VIZ_TEST_PATH]

    if parsed_args.coverage:
        # --cov-report= suppresses the terminal report; the .coverage data
        # file is what downstream tools (coveralls) consume
        xdist_cmd += ["--cov", "--cov-report="]
        toolkit_cmd += ["--cov", "--cov-append", "--cov-report="]
        viz_cmd += ["--cov", "--cov-append", "--cov-report="]

    lanes = [
        ("Lane 1: pytest-xdist", xdist_cmd),
        ("Lane 2: data toolkit (serial)", toolkit_cmd),
        ("Lane 3: viz (serial)", viz_cmd),
    ]

    # Build the examples testing database once; the test classes copy it
    # instead of each xdist worker rebuilding it from the CSVs
    run_sequentially(
        [
            (
                "Building the testing-database template",
                [
                    sys.executable,
                    "-c",
                    "from tests.test_examples import create_test_database; "
                    f"create_test_database(r'{DB_TEMPLATE_PATH}')",
                ],
            )
        ],
        env=None,
    )
    # Copying only the .db file would silently lose any pages still sitting
    # in a write-ahead log, so checkpoint the WAL into the main file and
    # remove the sidecar files before anything copies the template
    conn = sqlite3.connect(DB_TEMPLATE_PATH)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    remove_template_files(sidecars_only=True)

    env = os.environ.copy()
    env[DB_TEMPLATE_ENV_VAR] = DB_TEMPLATE_PATH

    try:
        if parsed_args.coverage:
            # Sequential: concurrent lanes would race on the .coverage
            # data file
            run_sequentially(lanes, env=env)
        else:
            run_concurrently(lanes, env=env)
    finally:
        remove_template_files()
    print("=== All tests passed ===")


if __name__ == "__main__":
    main()
