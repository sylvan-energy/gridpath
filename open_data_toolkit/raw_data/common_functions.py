# Copyright 2016-2024 Blue Marble Analytics LLC.
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

import csv
from datetime import datetime
import os.path

import pandas as pd

from version import __version__

DATA_PROVENANCE_FILENAME = "data_metadata.csv"


def get_pudl_version_rows_by_file(pudl_download_directory):
    """
    The latest recorded PUDL release version per downloaded file in the
    directory's data_metadata.csv (an empty Series if there is no metadata
    file). Run-level entries ("run_arguments", which also carry a
    pudl_version setting) are excluded — only rows describing actual
    downloaded files count.
    """
    metadata_filepath = os.path.join(pudl_download_directory, DATA_PROVENANCE_FILENAME)
    if not os.path.exists(metadata_filepath):
        return pd.Series(dtype=str)

    metadata = pd.read_csv(metadata_filepath, dtype=str)
    version_rows = metadata[
        (metadata["setting"] == "pudl_version")
        & (metadata["output_file"] != "run_arguments")
    ]

    # Rows are appended chronologically, so the last row per file is the
    # version currently on disk
    return version_rows.groupby("output_file")["value"].last()


def warn_on_mixed_pudl_versions(pudl_download_directory, log_directory, script):
    """
    If the files in the download directory were downloaded from more than
    one PUDL data release (e.g., only some were re-downloaded after a new
    release came out), warn the user and record the mix under
    ``output_file=run_warnings`` in *log_directory*'s metadata trail: a
    single release is the only combination of the source tables that PUDL
    actually publishes together. The warning is informational — a mixed
    snapshot may be intentional.
    """
    latest_version_by_file = get_pudl_version_rows_by_file(
        pudl_download_directory=pudl_download_directory
    )

    if latest_version_by_file.nunique() > 1:
        mix_str = "; ".join(f"{f}: {v}" for f, v in latest_version_by_file.items())
        print(
            f"WARNING: the files in {pudl_download_directory} were "
            f"downloaded from more than one PUDL data release "
            f"({mix_str}). PUDL only publishes these tables together "
            f"within a single release; proceed only if mixing releases "
            f"is intentional."
        )
        log_data_metadata(
            directory=log_directory,
            script=script,
            output_file="run_warnings",
            settings={"mixed_pudl_versions": mix_str},
        )


def log_data_metadata(directory, script, output_file, settings):
    """
    Append rows to the *data_metadata.csv* file in *directory* recording
    which settings produced *output_file* — one row per setting with a
    shared timestamp, plus the GridPath version. The file is a running
    log: reruns append new rows rather than overwriting, so it preserves
    the full history of how the data in the directory was obtained.
    """
    filepath = os.path.join(directory, DATA_PROVENANCE_FILENAME)
    file_exists = os.path.exists(filepath)
    timestamp = datetime.now().isoformat(timespec="seconds")

    with open(filepath, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "script", "output_file", "setting", "value"])
        for setting, value in {
            "gridpath_version": __version__,
            **settings,
        }.items():
            writer.writerow([timestamp, script, output_file, setting, value])


def copy_data_metadata(from_directory, to_directory):
    """
    Copy the *data_metadata.csv* rows from *from_directory* into the
    *data_metadata.csv* in *to_directory*, so that the metadata of source
    data (e.g., how the PUDL files were downloaded) travels along with data
    derived from it. Rows keep their original timestamp and script, and
    rows already present in the target are skipped, so reruns don't
    duplicate the history. A missing source file is a no-op (e.g., data
    obtained before metadata tracking was added).
    """
    source_filepath = os.path.join(from_directory, DATA_PROVENANCE_FILENAME)
    if not os.path.exists(source_filepath):
        return

    with open(source_filepath, newline="") as f:
        source_rows = list(csv.reader(f))[1:]  # skip the header

    target_filepath = os.path.join(to_directory, DATA_PROVENANCE_FILENAME)
    target_exists = os.path.exists(target_filepath)
    existing_rows = set()
    if target_exists:
        with open(target_filepath, newline="") as f:
            existing_rows = {tuple(row) for row in csv.reader(f)}

    with open(target_filepath, "a", newline="") as f:
        writer = csv.writer(f)
        if not target_exists:
            writer.writerow(["timestamp", "script", "output_file", "setting", "value"])
        for row in source_rows:
            if tuple(row) not in existing_rows:
                writer.writerow(row)
