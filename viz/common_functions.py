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

import os.path
from argparse import ArgumentParser

from bokeh import events
from bokeh.plotting import figure, output_file, show
from bokeh.layouts import column
from bokeh.models import (
    Button,
    CustomJS,
    ColumnDataSource,
    Legend,
    FactorRange,
    NumeralTickFormatter,
    InlineStyleSheet,
)
from bokeh.models.tools import HoverTool
from bokeh.palettes import cividis
import numpy as np
import pandas as pd

from gridpath.common_functions import create_directory_if_not_exists
from version import __version__


def show_hide_legend(plot):
    """
    Show/hide the legend on double tap.

    :param plot:
    """
    plot.js_on_event(
        events.DoubleTap,
        CustomJS(
            args=dict(legend=plot.legend[0]), code="legend.visible = !legend.visible"
        ),
    )


def show_plot(plot, plot_name, plot_write_directory, source, scenario=None):
    """
    Show plot in HTML browser file if requested.

    When comparing scenario, the plot will be saved in the "scenario_comparison"
    subfolfder of the plot_write_directory.

    When looking at a particular scenario, the plot will be saved in the
    "scenario/results/figures" subfolder of the plot_write_directory.

    :param plot:
    :param plot_name:
    :param plot_write_directory:
    :param scenario: str, optional (not required if comparing scenarios)
    :return:
    """

    if scenario is None:
        plot_write_subdir = os.path.join(
            plot_write_directory, "scenario_comparison", "figures"
        )
    else:
        plot_write_subdir = os.path.join(
            plot_write_directory, scenario, "results", "figures"
        )

    create_directory_if_not_exists(plot_write_subdir)
    file_path = os.path.join(plot_write_subdir, plot_name + ".html")

    output_file(file_path)

    layout = add_download_button(plot, source)
    show(layout)


def get_parent_parser():
    """
    Create "parent" ArgumentParser object which has the common set of arguments
    that each plot requires. We can then simply add 'parents=[parent_parser]'
    when we create a parser for a plot to inherit these common arguments.

    Note that 'add_help' is set to 'False' to avoid multiple `-h/--help` options
    (one for parent and one for each child), which will throw an error.
    :return:
    """

    parser = ArgumentParser(add_help=False)
    parser.add_argument(
        "--database",
        help="The database file path relative to the current "
        "working directory. Defaults to ../db/io.db",
    )
    parser.add_argument(
        "--plot_write_directory",
        default="../scenarios",
        help="The path to the base directory in which to save "
        "the plot html file. Note: the file will be saved "
        "in a subfolder of this base directory, generally "
        "'scenario_name/results/figures'",
    )
    parser.add_argument(
        "--scenario_name_in_title",
        default=False,
        action="store_true",
        help="Include the scenario name in the plot title.",
    )
    parser.add_argument("--ylimit", help="Set y-axis limit.", type=float)
    parser.add_argument(
        "--show",
        default=False,
        action="store_true",
        help="Show figure and save html file",
    )
    parser.add_argument(
        "--return_json",
        default=False,
        action="store_true",
        help="Return plot as a json file.",
    )
    parser.add_argument(
        "--version", action="version", version=f"GridPath {__version__}"
    )

    return parser


def get_tech_colors(c):
    """
    Get the colors by technology as specified in the viz_technologies db
    table.

    :param c:
    :return:
    """
    colors = c.execute("""
        SELECT technology, color
        FROM viz_technologies
        WHERE color is not NULL
        """).fetchall()

    return dict(colors)


def get_tech_plotting_order(c):
    """
    Get the plotting order of each technology as specified in the
    viz_technologies db table.

    :param c:
    :return:
    """

    order = c.execute("""
        SELECT technology, plotting_order
        FROM viz_technologies
        WHERE plotting_order is not NULL
        """).fetchall()

    return dict(order)


def get_unit(c, metric):
    """
    Get the unit of measurement for a given metric

    :param c:
    :param metric: str, the metric for which we want the unit of measurement
    :return:
    """

    unit = c.execute("SELECT unit FROM mod_units WHERE metric=?", (metric,))

    if unit.rowcount == 0:
        raise ValueError("""
            Error! The metric '{}' does not exists in the mod_units table.
            Please specify an existing metric. 
            """.format(metric))
    else:
        return unit.fetchone()[0]


def get_capacity_data(
    conn, subproblem, stage, capacity_col, scenario_id=None, load_zone=None, period=None
):
    """
    Get capacity results by scenario/period/technology. Users can
    optionally provide a subset of scenarios/load_zones/periods.
    Note: if load zone is not provided, will aggregate across load zones.

    :param conn:
    :param subproblem:
    :param stage:
    :param capacity_col: str, capacity column in results_project_period
    :param scenario_id: int or list of int, optional (default: return all
        scenarios)
    :param load_zone: str or list of str, optional (default: aggregate across
        load_zones)
    :param period: int or list of int, optional (default: return all periods)
    :return: DataFrame with columns scenario_id, period, technology, capacity_mw
    """

    params = [subproblem, stage]
    sql = """SELECT scenario_name AS scenario, period, technology, 
        sum({}) AS capacity_mw
        FROM results_project_period
        INNER JOIN 
        (SELECT scenario_name, scenario_id FROM scenarios) as scen_table
        USING (scenario_id)
        WHERE subproblem_id = ?
        AND stage_id = ?""".format(capacity_col)
    if period is not None:
        period = period if isinstance(period, list) else [period]
        sql += " AND period in ({})".format(",".join("?" * len(period)))
        params += period
    if scenario_id is not None:
        scenario_id = scenario_id if isinstance(scenario_id, list) else [scenario_id]
        sql += " AND scenario_id in ({})".format(",".join("?" * len(scenario_id)))
        params += scenario_id
    if load_zone is not None:
        load_zone = load_zone if isinstance(load_zone, list) else [load_zone]
        sql += " AND load_zone in ({})".format(",".join("?" * len(load_zone)))
        params += load_zone
    sql += " GROUP BY scenario, period, technology;"

    df = pd.read_sql(sql, con=conn, params=params)

    return df


def order_cols_by_nunique(df, cols):
    """
    Reorder columns in cols according to number of unique values in the df.
    This can be used to have a cleaner grouped (multi-level) x-axis where
    the level with the least unique values is at the bottom.
    Note: alternatively you could remove cols that have only 1 unique value
    :param df: pandas DataFrame
    :param cols: list of columns to reorder
    :return:
    """
    unique_count = df[cols].nunique().sort_values()
    re_ordered_cols = list(unique_count.index.values)
    return re_ordered_cols


def process_stacked_plot_data(df, y_col, x_col, category_col, column_mapper={}):
    """
    Processes a SQL-style long dataframe into a Bokeh ColumnDataSource (CDS)
    for stacked bar plotting:
        - Reorder index columns (x_cols) according to unique entries
        - Convert index column values to string
        - Pivot category_col to wide format
        - Rename columns and indices using an optional column_mapper
        - Create the CDS from the dataframe
    Returns the processed CDS as well as the reordered index column labels.

    Note: x_col(s) and category_col should uniquely identify a dataframe row!

    Example:
    data = {'period': [2018, 2018],
            'scenario' : ['scen1', 'scen2'],
            'tech': ['t1', 't2'],
            'mw': [5, 8],
            }
    df = pd.DataFrame(data)
    source, reordered_cols = process_stacked_plot_data(
        df=df,
        y_col="mw",
        x_col=["scenario", "period"],
        category_label="tech"
    )
    --> source = {'period_scenario': [('2018', 'scen1'), ('2018', 'scen2')],
                  't1': [5],
                  't2': [8]}
    --> x_col_reordered = ["period", scenario"]

    :param df: a database style long DataFrame which should include the columns
    'y_col', 'x_col' (can be list of cols) and 'category_col'. The
    'x_col' and 'category_col' should uniquely identify the value of the 'y_col'
    the 'y_col' (e.g. capacity should be uniquely defined by the
    period and the technology).
    :param y_col:
    :param x_col: str or list of str, the index column(s) to use
    :param category_col: str, name of column to pivot
    :param column_mapper:
    :return:
    """

    # Prepare x_col (index)
    x_col = x_col if isinstance(x_col, list) else [x_col]
    df[x_col] = df[x_col].astype(str)  # required for categorical bar chart
    x_col_reordered = order_cols_by_nunique(df, x_col)  # cleaner grouped axis
    # Pivot such that values in category column become column headers
    # Note on df.pivot vs. pd.pivot_table:
    #   df.pivot doesn't work with list of indexes in v1.0.5. Fixed in 1.1.0
    #   pd.pivot_table doesn't work with non-numeric values so need .fillna(0)
    #      to make sure None values are replaced with zero (e.g. hurdle rates)
    #   pd.pivot_table doesn't work with empty table without aggfunc="first"
    df = (
        pd.pivot_table(
            data=df.infer_objects().fillna(0),
            index=x_col_reordered,  # can be multi-level index!
            columns=category_col,
            values=y_col,
            aggfunc="first",  # take first value if there are duplicates
        )
        .fillna(0)
        .sort_index()
    )  # sorting for grouped x-axis format
    # Rename columns (optional)
    df.rename(columns=column_mapper, index=column_mapper, inplace=True)
    # Set up Bokeh ColumnDataSource
    source = ColumnDataSource(data=df)

    return source, x_col_reordered


def create_stacked_bar_plot(
    source,
    x_col,
    x_label=None,
    y_label=None,
    category_label="Category",
    category_colors={},
    category_order={},
    title=None,
    ylimit=None,
    sizing_mode="fixed",
):
    """
    Create a stacked bar chart from a Bokeh ColumnDataSource (CDS). The CDS
    should have have a "x_col" column where each element is either a string
    for a simple stacked bar charts or a tuple of strings for a grouped stacked
    bar chart. Note that strings are required for the categorical axis.
    All other columns are assumed to be categories that will be stacked in
    the bar chart.

    :param source: Bokeh ColumnDataSource
    :param x_col: str
    :param x_label: str, optional (defaults to x_col)
    :param y_label: str, optional (defaults to no label)
    :param category_label: str, optional
    :param category_colors: dict, optional, maps categories to colors.
        Categories without a specified color will use a default palette
    :param category_order: dict, optional, maps categories to their
        plotting order in the stacked bar chart (lower = bottom)
    :param title: string, optional, plot title
    :param ylimit: float/int, optional, upper limit of y-axis
    :param sizing_mode: Bokeh layout/figure sizing mode, default 'fixed'
    :return:
    """

    # Determine column types for plotting, legend and colors
    # Order of stacked_cols will define order of stacked areas in chart
    cols = list(source.data.keys())
    cols.remove(x_col)
    for col in cols:
        if col not in category_order:
            category_order[col] = max(category_order.values(), default=0) + 1
    stacked_cols = sorted(cols, key=lambda x: category_order[x])

    # Set up color scheme. Use cividis palette for unspecified colors
    unspecified_columns = [c for c in stacked_cols if c not in category_colors.keys()]
    unspecified_category_colors = dict(
        zip(unspecified_columns, cividis(len(unspecified_columns)))
    )
    colors = []
    for column in stacked_cols:
        if column in category_colors:
            colors.append(category_colors[column])
        else:
            colors.append(unspecified_category_colors[column])

    # Determine whether we are dealing with a grouped x_axis (tuple values)
    grouped_x = False
    try:
        if isinstance(source.data[x_col][0], tuple):
            grouped_x = True
    except IndexError:
        # If there is no data, grouped_x remains False
        pass

    # Find max label length in x axis labels
    if grouped_x:
        tuples = list(zip(*source.data[x_col]))  # convert to tuple of lists
        max_length = len(max(tuples[-1], key=len))  # look at inner-most level
    else:
        max_length = len(max(list(source.data[x_col]), key=len, default=""))

    # Set up the figure
    plot = figure(
        min_width=800,
        min_height=500,
        tools=["pan", "reset", "zoom_in", "zoom_out", "save", "help"],
        title=title,
        x_range=FactorRange(*source.data[x_col]) if grouped_x else source.data[x_col],
        sizing_mode=sizing_mode,
    )

    # Add stacked area chart to plot
    area_renderers = plot.vbar_stack(
        stackers=stacked_cols,
        x=x_col,
        source=source,
        color=colors,
        width=0.8,
        alpha=0.7,  # transparency
    )

    # Add Legend
    legend_items = [
        (y, [area_renderers[i]])
        for i, y in enumerate(stacked_cols)
        if np.mean(source.data[y]) > 0
    ]
    legend = Legend(items=legend_items)
    plot.add_layout(legend, "right")
    plot.legend.title = category_label
    plot.legend[0].items.reverse()  # Reverse legend to match stacked order
    plot.legend.click_policy = "hide"  # Add interactivity to the legend
    show_hide_legend(plot=plot)  # Hide legend on double click

    # Format Axes (labels, number formatting, range, etc.)
    x_label = x_col if x_label is None else x_label
    plot.xaxis.axis_label = x_label
    if max_length > 10:  # Print innermost labels at angle if label is long
        plot.xaxis.major_label_orientation = 1
    plot.xgrid.grid_line_color = None
    if y_label is not None:
        plot.yaxis.axis_label = y_label
    plot.yaxis.formatter = NumeralTickFormatter(format="0,0")
    if ylimit is not None:
        plot.y_range.end = ylimit  # will be ignored if ylimit is None

    # Add HoverTools for stacked bars/areas
    for r in area_renderers:
        category = r.name
        tooltips = [
            ("%s" % x_label, "@{%s}" % x_col),
            ("%s" % category_label, category),
        ]
        if y_label is not None:
            if "$" in y_label or "USD" in y_label:
                tooltips.append(("%s" % y_label, "@%s{$0,0}" % category))
            else:
                tooltips.append(("%s" % y_label, "@%s{0,0}" % category))
        hover = HoverTool(tooltips=tooltips, renderers=[r], visible=False)
        plot.add_tools(hover)

    return plot


def add_download_button(plot, source):
    stylesheet = InlineStyleSheet(
        css=".bk-btn { background-color: lightblue; color: white; }"
    )
    button = Button(
        label="Download Data", button_type="success", stylesheets=[stylesheet]
    )
    button.js_on_click(
        CustomJS(
            args=dict(source=source),
            code="""
        const data = source.data;
        const cols = Object.keys(data);
        const nrows = data[cols[0]].length;
        let csv = cols.join(",") + "\\n";
        for (let i = 0; i < nrows; i++) {
            let row = [];
            for (let j = 0; j < cols.length; j++) {
                row.push(data[cols[j]][i]);
            }
            csv += row.join(",") + "\\n";
        }
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "plot_data.csv";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    """,
        )
    )
    return column(plot, button)
