# Copyright 2016-2023 Blue Marble Analytics LLC. All rights reserved.

from gridpath.auxiliary.auxiliary import load_subtype_modules


def load_operational_type_modules(required_operational_modules):
    """
    Load a specified set of operational type modules
    :param required_operational_modules:
    :return: dictionary with the imported subtype modules
        {name of subtype module: Python module object}
    """
    return load_subtype_modules(
        required_subtype_modules=required_operational_modules,
        package="gridpath.project.operations.operational_types",
        required_attributes=[],
    )


def resolve_op_type_rules(imported_operational_modules, rule_name, default_module):
    """
    Map each imported operational type module to its :code:`rule_name`
    function, falling back to the default op-type implementation in
    :code:`default_module` for modules that don't define it.

    Resolving these once at component-declaration time avoids per-index
    hasattr/getattr dispatch in rules that are called once per
    project-timepoint.
    """
    return {
        op_m: getattr(module, rule_name, getattr(default_module, rule_name))
        for op_m, module in imported_operational_modules.items()
    }
