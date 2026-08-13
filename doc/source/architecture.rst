

*********************
GridPath Architecture
*********************

This section describes GridPath's modular architecture, i.e. how the modules
are linked and work together (as opposed to their formulation or the
functionality they add).

================
GridPath Modules
================

gridpath.auxiliary.module_list
******************************

.. automodule:: gridpath.auxiliary.module_list
    :members: all_modules_list, optional_modules_list,
        cross_feature_modules_list, determine_modules, load_modules

gridpath.auxiliary.dynamic_components
*************************************
.. automodule:: gridpath.auxiliary.dynamic_components
    :members: DynamicComponents


================
Running GridPath
================

Running a Scenario
******************

gridpath.run_scenario
=====================
.. automodule:: gridpath.run_scenario
    :members: main, parse_arguments, run_scenario, run_optimization_for_subproblem,
        create_problem, solve_problem, create_abstract_model,
        load_scenario_data, create_problem_instance, fix_variables, solve


Database Access
***************

gridpath.get_scenario_inputs
============================
.. automodule:: gridpath.get_scenario_inputs

gridpath.import_scenario_results
================================
.. automodule:: gridpath.import_scenario_results

gridpath.process_results
========================
.. automodule:: gridpath.process_results


Running End-to-End
******************

gridpath.run_end_to_end
=======================
.. automodule:: gridpath.run_end_to_end

gridpath.run_end_to_end_per_draw
================================
.. automodule:: gridpath.run_end_to_end_per_draw

gridpath.scenario_directory_cleanup
===================================
.. automodule:: gridpath.scenario_directory_cleanup


Input Validation
****************

gridpath.validate_inputs
========================
.. automodule:: gridpath.validate_inputs



