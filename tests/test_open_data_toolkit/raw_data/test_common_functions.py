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

import contextlib
import io
import os
import tempfile
import unittest

import pandas as pd

from open_data_toolkit.raw_data.common_functions import (
    DATA_PROVENANCE_FILENAME,
    copy_data_metadata,
    log_data_metadata,
    warn_on_mixed_pudl_versions,
)


class TestDataMetadata(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.source_dir = tempfile.mkdtemp(dir=self.tmp_dir.name)
        self.target_dir = tempfile.mkdtemp(dir=self.tmp_dir.name)

    def read_metadata(self, directory):
        return pd.read_csv(os.path.join(directory, DATA_PROVENANCE_FILENAME), dtype=str)

    def test_copy_preserves_source_rows_and_deduplicates(self):
        log_data_metadata(
            directory=self.source_dir,
            script="download_data_from_pudl",
            output_file="some_table.parquet",
            settings={"pudl_version": "v-test"},
        )
        # Pre-existing native rows in the target must be kept
        log_data_metadata(
            directory=self.target_dir,
            script="pudl_to_gridpath_raw_data",
            output_file="run_arguments",
            settings={"quiet": True},
        )

        copy_data_metadata(from_directory=self.source_dir, to_directory=self.target_dir)
        # A second copy must not duplicate the source rows
        copy_data_metadata(from_directory=self.source_dir, to_directory=self.target_dir)

        source = self.read_metadata(self.source_dir)
        target = self.read_metadata(self.target_dir)
        copied = target[target["script"] == "download_data_from_pudl"]
        # Copied rows are identical to the source rows (same timestamps)
        pd.testing.assert_frame_equal(
            copied.reset_index(drop=True), source.reset_index(drop=True)
        )
        # Native target rows still there
        self.assertIn("pudl_to_gridpath_raw_data", target["script"].tolist())

    def test_copy_creates_target_file_if_missing(self):
        log_data_metadata(
            directory=self.source_dir,
            script="download_data_from_pudl",
            output_file="some_table.parquet",
            settings={"pudl_version": "v-test"},
        )

        copy_data_metadata(from_directory=self.source_dir, to_directory=self.target_dir)

        source = self.read_metadata(self.source_dir)
        target = self.read_metadata(self.target_dir)
        pd.testing.assert_frame_equal(source, target)

    def test_copy_with_missing_source_is_a_noop(self):
        copy_data_metadata(from_directory=self.source_dir, to_directory=self.target_dir)

        self.assertFalse(
            os.path.exists(os.path.join(self.target_dir, DATA_PROVENANCE_FILENAME))
        )

    def test_warn_on_mixed_pudl_versions(self):
        log_data_metadata(
            directory=self.source_dir,
            script="download_data_from_pudl",
            output_file="a.parquet",
            settings={"pudl_version": "v-old"},
        )
        log_data_metadata(
            directory=self.source_dir,
            script="download_data_from_pudl",
            output_file="b.parquet",
            settings={"pudl_version": "v-new"},
        )

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            warn_on_mixed_pudl_versions(
                pudl_download_directory=self.source_dir,
                log_directory=self.target_dir,
                script="test_script",
            )

        self.assertIn("more than one PUDL data release", captured.getvalue())
        metadata = self.read_metadata(self.target_dir)
        warnings_rows = metadata[metadata["output_file"] == "run_warnings"]
        self.assertEqual(warnings_rows["script"].unique().tolist(), ["test_script"])
        warning_settings = dict(zip(warnings_rows["setting"], warnings_rows["value"]))
        self.assertIn("a.parquet: v-old", warning_settings["mixed_pudl_versions"])
        self.assertIn("b.parquet: v-new", warning_settings["mixed_pudl_versions"])

    def test_no_warning_on_single_pudl_version(self):
        # A file re-downloaded at the SAME version (extra metadata rows) is
        # not a mix and must not warn; run_arguments entries (which also
        # carry a pudl_version setting) don't count as files either
        for _ in range(2):
            log_data_metadata(
                directory=self.source_dir,
                script="download_data_from_pudl",
                output_file="a.parquet",
                settings={"pudl_version": "v-same"},
            )
        log_data_metadata(
            directory=self.source_dir,
            script="download_data_from_pudl",
            output_file="b.parquet",
            settings={"pudl_version": "v-same"},
        )
        log_data_metadata(
            directory=self.source_dir,
            script="download_data_from_pudl",
            output_file="run_arguments",
            settings={"pudl_version": ""},
        )

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            warn_on_mixed_pudl_versions(
                pudl_download_directory=self.source_dir,
                log_directory=self.target_dir,
                script="test_script",
            )

        self.assertEqual(captured.getvalue(), "")
        self.assertFalse(
            os.path.exists(os.path.join(self.target_dir, DATA_PROVENANCE_FILENAME))
        )

    def tearDown(self):
        self.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
