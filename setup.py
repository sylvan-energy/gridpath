from setuptools import find_packages, setup

# Get version
version = {}
with open("./version.py") as fp:
    exec(fp.read(), version)

# Set up extras
extras_doc = [
    "Sphinx==7.2.6",
    "sphinx-argparse==0.4.0",
    "df2img",
]

extras_black = ["black"]

extras_coverage = [
    "coverage",  # test coverage
    "coveralls",  # automated coverage results
]

extras_gurobi = ["gurobipy"]  # Gurobi Python interface

extras_all = extras_doc + extras_black + extras_coverage + extras_gurobi

setup(
    name="GridPath",
    version=version["__version__"],
    description="A versatile simulation and optimization platform for "
    "power-system planning and operations.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://www.gridpath.io",
    project_urls={
        "Discussions": "https://github.com/sylvan-energy/gridpath/discussions",
        "Documentation": "https://gridpath.readthedocs.io/en/latest/",
        "Issues": "https://github.com/sylvan-energy/gridpath/issues",
        "Source Code": "https://github.com/sylvan-energy/gridpath",
    },
    maintainer="Sylvan Energy Analytics LLC",
    maintainer_email="info@sylvan.energy",
    license="Apache v2",
    platforms=["MacOS", "Windows", "Linux"],
    keywords=["energy", "electricity", "power", "renewables", "planning", "operations"],
    packages=find_packages(),
    py_modules=["version"],  # so the DB metadata can record the version
    install_requires=[
        "Pyomo==6.9.4",  # Optimization modeling language
        "pandas==2.3.3",  # Data-processing
        "bokeh==3.8.0",  # Visualization library
        "pscript==0.8.0",  # Python to JavaScript compiler (for viz)
        "networkx==3.4.2; python_version < '3.11'",  # network package for DC OPF
        "networkx==3.5.0; python_version >= '3.11'",  # network package for DC OPF
        "PyUtilib==6.0.0",  # used for solver temp file management
        "highspy==1.15.1",  # HiGHS Python interface (default solver)
        "dill==0.3.8",  # pickling
        "duckdb==1.4.2",  # data-handling
        "sphinx-rtd-theme",  # documentation theme
    ],
    extras_require={
        "doc": extras_doc,
        "all": extras_all,
        "coverage": extras_coverage,
        "gurobi": extras_gurobi,
    },
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "gridpath = gridpath.cli:main",
            "gridpath_run = gridpath.run_scenario:main",
            "gridpath_run_parallel = gridpath.run_scenario_parallel:main",
            "gridpath_run_e2e = gridpath.run_end_to_end:main",
            "gridpath_get_inputs = gridpath.get_scenario_inputs:main",
            "gridpath_import_results = " "gridpath.import_scenario_results:main",
            "gridpath_process_results = gridpath.process_results:main",
            "gridpath_validate = gridpath.validate_inputs:main",
            "gridpath_run_server = ui.server.run_server:main",
            "gridpath_run_queue_manager = ui.server.run_queue_manager:main",
            "gridpath_create_database = db.create_database:main",
            "gridpath_load_csvs = db.utilities.port_csvs_to_db:main",
            "gridpath_load_scenarios = db.utilities.scenario:main",
            "gridpath_get_pudl_data = "
            "data_toolkit.raw_data.pudl.download_data_from_pudl:main",
            "gridpath_pudl_to_gridpath_raw = "
            "data_toolkit.raw_data.pudl.pudl_to_gridpath_raw_data:main",
            "gridpath_get_pcm_demo_inputs = "
            "data_toolkit.raw_data.get_pcm_demo_user_defined_inputs:main",
            "gridpath_get_ra_toolkit_data_raw = "
            "data_toolkit.raw_data.ra_toolkit.get_ra_toolkit_data:main",
            "gridpath_run_data_toolkit = data_toolkit.run_data_toolkit:main",
            "gridpath_load_raw_data = data_toolkit.load_raw_data:main",
            "gridpath_manual_adjustments = data_toolkit.manual_adjustments:main",
            "gridpath_eiaaeo_to_fuel_chars_input_csvs = "
            "data_toolkit.fuels.eiaaeo_to_fuel_chars_input_csvs:main",
            "gridpath_eiaaeo_fuel_price_input_csvs = "
            "data_toolkit.fuels.eiaaeo_fuel_price_input_csvs:main",
            "gridpath_eia860_to_project_availability_input_csvs = "
            "data_toolkit.project.availability.eia860_to_project_availability_input_csvs:main",
            "gridpath_create_sync_gen_weather_derate_input_csvs = "
            "data_toolkit.project.availability.weather_derates.create_sync_gen_weather_derate_input_csvs:main",
            "gridpath_create_monte_carlo_gen_weather_derate_input_csvs = "
            "data_toolkit.project.availability.weather_derates.create_monte_carlo_gen_weather_derate_input_csvs:main",
            "gridpath_create_availability_iteration_input_csvs = "
            "data_toolkit.project.availability.outages.create_availability_iteration_input_csvs:main",
            "gridpath_eia860_to_project_specified_capacity_input_csvs = "
            "data_toolkit.project.capacity_specified.eia860_to_project_specified_capacity_input_csvs:main",
            "gridpath_eia860_to_project_fixed_cost_input_csvs = "
            "data_toolkit.project.fixed_cost.eia860_to_project_fixed_cost_input_csvs:main",
            "gridpath_eia860_to_project_load_zone_input_csvs = "
            "data_toolkit.project.load_zones.eia860_to_project_load_zone_input_csvs:main",
            "gridpath_eia860_to_project_opchar_input_csvs = "
            "data_toolkit.project.opchar.eia860_to_project_opchar_input_csvs:main",
            "gridpath_eia860_to_project_fuel_input_csvs = "
            "data_toolkit.project.opchar.fuels.eia860_to_project_fuel_input_csvs:main",
            "gridpath_eia860_to_project_heat_rate_input_csvs = "
            "data_toolkit.project.opchar.heat_rates.eia860_to_project_heat_rate_input_csvs:main",
            "gridpath_create_hydro_iteration_input_csvs = "
            "data_toolkit.project.opchar.hydro.create_hydro_iteration_input_csvs:main",
            "gridpath_create_sync_var_gen_input_csvs = "
            "data_toolkit.project.opchar.var_profiles.create_sync_var_gen_input_csvs:main",
            "gridpath_create_monte_carlo_var_gen_input_csvs = "
            "data_toolkit.project.opchar.var_profiles.create_monte_carlo_var_gen_input_csvs:main",
            "gridpath_eia860_to_project_portfolio_input_csvs = "
            "data_toolkit.project.portfolios.eia860_to_project_portfolio_input_csvs:main",
            "gridpath_eia930_load_zone_input_csvs = "
            "data_toolkit.system.eia930_load_zone_input_csvs:main",
            "gridpath_create_sync_load_input_csvs = "
            "data_toolkit.system.create_sync_load_input_csvs:main",
            "gridpath_create_monte_carlo_load_input_csvs = "
            "data_toolkit.system.create_monte_carlo_load_input_csvs:main",
            "gridpath_create_temporal_iteration_csv = "
            "data_toolkit.temporal.create_temporal_iteration_csv:main",
            "gridpath_create_temporal_scenarios = "
            "data_toolkit.temporal.create_temporal_scenarios:main",
            "gridpath_create_monte_carlo_weather_draws = "
            "data_toolkit.temporal.create_monte_carlo_weather_draws:main",
            "gridpath_create_monte_carlo_weather_draw_profiles = "
            "data_toolkit.temporal.create_monte_carlo_weather_draw_profiles:main",
            "gridpath_eia930_to_transmission_load_zone_input_csvs = "
            "data_toolkit.transmission.load_zones.eia930_to_transmission_load_zone_input_csvs:main",
            "gridpath_eia930_to_transmission_availability_input_csvs = "
            "data_toolkit.transmission.availability.eia930_to_transmission_availability_input_csvs:main",
            "gridpath_eia930_to_transmission_specified_capacity_input_csvs = "
            "data_toolkit.transmission.capacity_specified.eia930_to_transmission_specified_capacity_input_csvs:main",
            "gridpath_eia930_to_transmission_opchar_input_csvs = "
            "data_toolkit.transmission.opchar.eia930_to_transmission_opchar_input_csvs:main",
            "gridpath_eia930_to_transmission_portfolio_input_csvs = "
            "data_toolkit.transmission.portfolios.eia930_to_transmission_portfolio_input_csvs:main",
            "gridpath_viz_capacity_factor_plot = viz.capacity_factor_plot:main",
            "gridpath_viz_capacity_new_plot = viz.capacity_new_plot:main",
            "gridpath_viz_capacity_retired_plot = viz.capacity_retired_plot:main",
            "gridpath_viz_capacity_total_loadzone_comparison_plot = viz.capacity_total_loadzone_comparison_plot:main",
            "gridpath_viz_capacity_total_plot = viz.capacity_total_plot:main",
            "gridpath_viz_capacity_total_scenario_comparison_plot = viz.capacity_total_scenario_comparison_plot:main",
            "gridpath_viz_carbon_plot = viz.carbon_plot:main",
            "gridpath_viz_cost_plot = viz.cost_plot:main",
            "gridpath_viz_curtailment_hydro_heatmap_plot = viz.curtailment_hydro_heatmap_plot:main",
            "gridpath_viz_curtailment_variable_heatmap_plot = viz.curtailment_variable_heatmap_plot:main",
            "gridpath_viz_dispatch_plot = viz.dispatch_plot:main",
            "gridpath_viz_energy_plot = viz.energy_plot:main",
            "gridpath_viz_energy_target_plot = viz.energy_target_plot:main",
            "gridpath_viz_project_operations_plot = viz.project_operations_plot:main",
        ]
    },
)
