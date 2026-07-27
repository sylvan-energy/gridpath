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
Run the GridPath test suite in two phases:

Phase 1 (parallel): everything that is safe to run concurrently, via
pytest-xdist. Each worker gets its own copy of the unittest_examples
database (see the PYTEST_XDIST_WORKER handling in tests/test_examples.py);
the database is built once as a template beforehand and the workers copy
it (see set_up_test_database in tests/test_examples.py).

Phase 2 (serial): tests that share writable state on disk and must not
overlap with each other or with phase 1:
  - tests/test_data_toolkit and tests/test_run_data_toolkit.py regenerate
    committed fixture CSVs under db/csvs_test_examples/, some of which
    both file sets write;
  - tests/test_viz.py solves several example scenarios in one setUpClass;
    it is self-contained (template-database copy plus a temporary copy of
    the scenario directories) but stays out of phase 1 because worksteal
    scheduling would re-run that expensive setUpClass on every worker
    that picks up one of its tests.

Usage:
    python scripts/run_tests_parallel.py [--coverage]

Requires the "parallel_tests" extra (pip install -e .[parallel_tests]);
--coverage additionally requires the "coverage" extra and appends phase 2's
coverage data to phase 1's, leaving a combined .coverage file at the repo
root (pytest-cov measures the xdist worker processes, which a plain
"coverage run -m pytest" would miss).
"""

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tests with shared on-disk state, excluded from phase 1 and run serially
# in phase 2 (see module docstring for what each one shares)
SHARED_STATE_TEST_PATHS = [
    "tests/test_data_toolkit",
    "tests/test_run_data_toolkit.py",
    "tests/test_viz.py",
]


# Where to pre-build the examples testing database that the test classes
# then copy instead of each rebuilding it from the CSVs; the path is passed
# to the test processes via this environment variable (see
# set_up_test_database in tests/test_examples.py)
DB_TEMPLATE_ENV_VAR = "GRIDPATH_TEST_EXAMPLES_DB_TEMPLATE"
DB_TEMPLATE_PATH = os.path.join(REPO_ROOT, "db", "unittest_examples_template.db")


def run_phase(name, cmd, env=None):
    print(f"=== {name} ===", flush=True)
    returncode = subprocess.run(cmd, cwd=REPO_ROOT, env=env).returncode
    if returncode != 0:
        sys.exit(returncode)


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

    phase_1_cmd = [sys.executable, "-m", "pytest", "tests", "-n", "auto"]
    phase_1_cmd += ["--dist", "worksteal", "-q"]
    # The --ignore paths must be absolute: some test modules os.chdir at
    # import time, which happens mid-collection, and pytest resolves
    # relative --ignore paths against the current working directory when
    # it visits each directory — so relative ignores stop matching after
    # the chdir
    for path in SHARED_STATE_TEST_PATHS:
        phase_1_cmd.append("--ignore=" + os.path.join(REPO_ROOT, *path.split("/")))

    phase_2_cmd = [sys.executable, "-m", "pytest", "-q"]
    phase_2_cmd += SHARED_STATE_TEST_PATHS

    if parsed_args.coverage:
        # --cov-report= suppresses the terminal report; the .coverage data
        # file is what downstream tools (coveralls) consume
        phase_1_cmd += ["--cov", "--cov-report="]
        phase_2_cmd += ["--cov", "--cov-append", "--cov-report="]

    # Build the examples testing database once; the test classes copy it
    # instead of each xdist worker rebuilding it from the CSVs
    run_phase(
        "Building the testing-database template",
        [
            sys.executable,
            "-c",
            "from tests.test_examples import create_test_database; "
            f"create_test_database(r'{DB_TEMPLATE_PATH}')",
        ],
    )
    env = os.environ.copy()
    env[DB_TEMPLATE_ENV_VAR] = DB_TEMPLATE_PATH

    try:
        run_phase("Phase 1: parallel (pytest-xdist)", phase_1_cmd, env=env)
        run_phase("Phase 2: serial (shared on-disk state)", phase_2_cmd, env=env)
    finally:
        if os.path.exists(DB_TEMPLATE_PATH):
            os.remove(DB_TEMPLATE_PATH)
    print("=== All tests passed ===")


if __name__ == "__main__":
    main()
