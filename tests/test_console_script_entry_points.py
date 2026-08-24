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
Console-script entry points must not return a value.

The console-script shims generated at install time wrap the entry point as
``sys.exit(entry_point())``, and ``sys.exit()`` of a non-integer, non-None
value prints that value to stderr and exits with status 1. An entry point
that returns data therefore reports failure on every successful run (this
was the case for ``gridpath_run``, which returned the objective function
values). Functions that return data for programmatic callers get a thin
``cli()`` wrapper that discards the return value, and the entry point
points at that wrapper.
"""

import ast
import os.path
import sys
import unittest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- GridPath requires Python >= 3.11
    tomllib = None

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(REPO_DIR, "pyproject.toml")

# Entry points whose target module is not part of the GridPath distribution
# (the UI code was removed in #1290; its entry points are declared but have
# never shipped in the wheel).
MODULES_NOT_IN_REPO = ["ui.server.run_server", "ui.server.run_queue_manager"]

# The viz plot scripts return the plot as JSON when called with
# --return_json, which is consumed by in-process callers (the UI). Called as
# console scripts with that flag they do hit the sys.exit() behavior
# described above; changing where that JSON goes is a user-visible decision
# for the flag's consumers, so it is deliberately left alone here and these
# entry points are exempt from the check.
CONDITIONAL_RETURN_EXEMPTIONS = ["viz."]


def get_entry_points():
    """
    :return: dict of console script name to "module:function" target
    """
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]["scripts"]


def get_own_returns(func_def):
    """
    :param func_def: an ast.FunctionDef
    :return: list of ast.Return nodes in the function's OWN body (returns
        inside functions nested in it belong to those functions)
    """
    returns = []
    stack = list(func_def.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return):
            returns.append(node)
        stack.extend(ast.iter_child_nodes(node))

    return returns


class TestConsoleScriptEntryPoints(unittest.TestCase):
    """ """

    def test_entry_points_do_not_return_values(self):
        """
        No console-script entry point returns a value, so every successful
        run exits with status 0.
        """
        offenders = []
        for script_name, target in sorted(get_entry_points().items()):
            module_name, func_name = target.split(":")
            if module_name in MODULES_NOT_IN_REPO:
                continue
            if any(module_name.startswith(e) for e in CONDITIONAL_RETURN_EXEMPTIONS):
                continue

            module_path = os.path.join(REPO_DIR, *module_name.split(".")) + ".py"
            self.assertTrue(
                os.path.exists(module_path),
                msg=f"Entry point {script_name} points at missing {module_path}.",
            )
            with open(module_path) as f:
                tree = ast.parse(f.read())

            func_def = next(
                (
                    n
                    for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == func_name
                ),
                None,
            )
            self.assertIsNotNone(
                func_def,
                msg=f"Entry point {script_name} points at missing {target}.",
            )

            for node in get_own_returns(func_def):
                returns_value = node.value is not None and not (
                    isinstance(node.value, ast.Constant) and node.value.value is None
                )
                if returns_value:
                    offenders.append(f"{script_name} ({target}, line {node.lineno})")

        self.assertEqual(
            offenders,
            [],
            msg="These console-script entry points return a value, so the "
            "generated shim's sys.exit() will print it to stderr and exit "
            "1 on success. Point the entry point at a cli() wrapper that "
            "discards the return value: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
