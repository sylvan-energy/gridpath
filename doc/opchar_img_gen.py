# Copyright 2016-2025 Blue Marble Analytics LLC.
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
This script generates the images (SVG and PNG) of the table of operational
characteristics with the corresponding project operational types for
inclusion into the documentation.

Run this only after editing
../gridpath/project/operations/operational_types/opchar_param_requirements.csv
and commit the regenerated files in graphics/. It is NOT part of the
GridPath install extras or the Read the Docs build (which uses the
already-committed images) because its df2img dependency requires
pandas<3.0, which conflicts with GridPath's own pandas pin. Install df2img
in a separate, throwaway environment (with an older pandas) to run this
script rather than the main GridPath dev environment.
"""

import pandas as pd, numpy as np
import df2img

df = pd.read_csv(
    "../gridpath/project/operations/operational_types/opchar_param_requirements.csv",
    na_filter=False,
)

d2i_tbl_hdr_dict = dict(
    align="right", fill_color="#5176BF", font_color="white", line_color="darkslategray"
)
d2i_tbl_cel_dict = dict(align="right", line_color="darkslategray")

padding = 2  # Some elbow space for the values
col_width_header = list(df.columns.str.len())
col_width_values = [df[coll].map(len).max() for coll in df]
col_width_both = [
    max(one_col_width) + padding
    for one_col_width in zip(col_width_header, col_width_values)
]

fig = df2img.plot_dataframe(
    df,
    tbl_header=d2i_tbl_hdr_dict,
    tbl_cells=d2i_tbl_cel_dict,
    show_fig=False,
    row_fill_color=("#ffffff", "#5176BF"),
    print_index=False,
    fig_size=(3500, 1000),
    col_width=tuple(col_width_both),
)

fig_table = fig.data[0]
rr1, cc1 = np.where(df == "required")
rr2, cc2 = np.where(df == "optional")

# python
# prepare a mutable, normalized column-first list-of-lists for cell fill colors
colors = list(fig_table.cells.fill.color)

# determine actual number of rows in the table (includes header row)
num_rows_in_table = 0
for col in colors:
    if isinstance(col, (tuple, list)):
        num_rows_in_table = max(num_rows_in_table, len(col))
    else:
        num_rows_in_table = max(num_rows_in_table, 1)
if num_rows_in_table == 0:
    num_rows_in_table = len(df) + 1

# normalize each column to be a list of length num_rows_in_table
normalized = []
for col in colors:
    if not isinstance(col, list):
        col_list = list(col) if isinstance(col, (tuple, list)) else [col]
    else:
        col_list = col
    if len(col_list) < num_rows_in_table:
        col_list = col_list + ["#ffffff"] * (num_rows_in_table - len(col_list))
    elif len(col_list) > num_rows_in_table:
        col_list = col_list[:num_rows_in_table]
    normalized.append(list(col_list))
colors = normalized

# compute offset between dataframe row indices and table row indices (header row)
header_offset = num_rows_in_table - len(df)
if header_offset < 0:
    header_offset = 0

# set required cells to red (apply header_offset)
for r, c in zip(rr1, cc1):
    if 0 <= c < len(colors) and 0 <= (r + header_offset) < len(colors[c]):
        colors[c][r + header_offset] = "#BF5176"

# set optional cells to yellow (apply header_offset)
for r, c in zip(rr2, cc2):
    if 0 <= c < len(colors) and 0 <= (r + header_offset) < len(colors[c]):
        colors[c][r + header_offset] = "#51BF9B"

# assign back the modified colors
fig_table.cells.fill.color = colors

df2img.save_dataframe(fig=fig, filename="graphics/optype_opchar_matrix.png")
df2img.save_dataframe(fig=fig, filename="graphics/optype_opchar_matrix.svg")
