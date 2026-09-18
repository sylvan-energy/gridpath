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
import functools
import http.server
import io
import os
import socketserver
import tempfile
import threading
import unittest
import zipfile

import pandas as pd

from open_data_toolkit.raw_data.common_functions import log_data_metadata
from open_data_toolkit.raw_data.pudl import download_data_from_pudl

PUDL_VERSION_TEST = "vtest"

# The tables main() downloads by default
MAIN_TABLE_NAMES = [
    "core_eia860__scd_generators",
    "core_eia860__scd_plants",
    "core_eia__entity_generators",
    "core_eia860__scd_generators_solar",
    "core_eia860__scd_generators_energy_storage",
    "core_eia860m__changelog_generators",
    "core_eia__codes_balancing_authorities",
    "core_eiaaeo__yearly_projected_fuel_cost_in_electric_sector_by_type",
    "core_eia930__hourly_interchange",
    "core_eia930__hourly_net_generation_by_energy_source",
    "core_eia930__hourly_operations",
    "out_eia923__monthly_generation_fuel_combined",
    "out_ferc714__hourly_planning_area_demand",
    "out_ferc714__summarized_demand",
]


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler logs every request to stderr; keep the test
    output clean."""

    def log_message(self, format, *args):
        pass


class TestDownloadDataFromPudl(unittest.TestCase):
    """
    Test the download functions against a local HTTP server standing in for
    the PUDL S3 endpoint (no network needed).
    """

    @classmethod
    def setUpClass(cls):
        # Lay out a fake versioned PUDL endpoint in a temp directory
        cls.tmp_dir = tempfile.TemporaryDirectory()
        serve_root = os.path.join(cls.tmp_dir.name, "serve_root")
        version_dir = os.path.join(serve_root, PUDL_VERSION_TEST)
        os.makedirs(version_dir)

        cls.parquet_content = b"not-really-parquet"
        with open(os.path.join(version_dir, "test_table.parquet"), "wb") as f:
            f.write(cls.parquet_content)
        for table_name in MAIN_TABLE_NAMES:
            with open(os.path.join(version_dir, f"{table_name}.parquet"), "wb") as f:
                f.write(cls.parquet_content)

        cls.sqlite_content = b"SQLite format 3\x00" + b"x" * 1024
        with zipfile.ZipFile(
            os.path.join(version_dir, "pudl.sqlite.zip"), "w", zipfile.ZIP_DEFLATED
        ) as z:
            z.writestr("pudl.sqlite", cls.sqlite_content)

        # A fake Zenodo concept-record response for the latest-version lookup
        with open(os.path.join(serve_root, "zenodo_record.json"), "w") as f:
            f.write('{"metadata": {"version": "v-zenodo-latest"}}')

        handler = functools.partial(QuietHTTPRequestHandler, directory=serve_root)
        cls.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

        server_url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.orig_base_url = download_data_from_pudl.PUDL_S3_BASE_URL
        download_data_from_pudl.PUDL_S3_BASE_URL = server_url
        cls.orig_zenodo_url = download_data_from_pudl.PUDL_ZENODO_CONCEPT_RECORD_URL
        download_data_from_pudl.PUDL_ZENODO_CONCEPT_RECORD_URL = (
            f"{server_url}/zenodo_record.json"
        )

    def read_metadata(self, download_directory):
        return pd.read_csv(
            os.path.join(download_directory, "data_metadata.csv"), dtype=str
        )

    def test_determine_pudl_version_defaults_to_latest(self):
        self.assertEqual(
            download_data_from_pudl.determine_pudl_version(
                pudl_version=None, quiet=True
            ),
            "v-zenodo-latest",
        )

    def test_determine_pudl_version_explicit_passthrough(self):
        self.assertEqual(
            download_data_from_pudl.determine_pudl_version(
                pudl_version="v2020.1.0", quiet=True
            ),
            "v2020.1.0",
        )

    def test_determine_pudl_version_unresolvable_raises(self):
        orig = download_data_from_pudl.PUDL_ZENODO_CONCEPT_RECORD_URL
        download_data_from_pudl.PUDL_ZENODO_CONCEPT_RECORD_URL = (
            f"{download_data_from_pudl.PUDL_S3_BASE_URL}/no_such_record.json"
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "--pudl_version"):
                download_data_from_pudl.determine_pudl_version(
                    pudl_version=None, quiet=True
                )
        finally:
            download_data_from_pudl.PUDL_ZENODO_CONCEPT_RECORD_URL = orig

    def test_get_parquet_file(self):
        download_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        download_data_from_pudl.get_parquet_file_from_pudl_s3(
            pudl_version=PUDL_VERSION_TEST,
            filename="test_table",
            download_directory=download_directory,
            quiet=True,
        )

        filepath = os.path.join(download_directory, "test_table.parquet")
        with open(filepath, "rb") as f:
            self.assertEqual(f.read(), self.parquet_content)
        # No leftover .part file
        self.assertFalse(os.path.exists(f"{filepath}.part"))

        metadata = self.read_metadata(download_directory)
        self.assertEqual(
            metadata["output_file"].unique().tolist(), ["test_table.parquet"]
        )
        settings = dict(zip(metadata["setting"], metadata["value"]))
        self.assertEqual(settings["pudl_version"], PUDL_VERSION_TEST)
        self.assertTrue(settings["source_url"].endswith("test_table.parquet"))
        self.assertIn("gridpath_version", settings)

    def test_get_pudl_sqlite(self):
        download_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        download_data_from_pudl.get_pudl_sqlite_from_pudl_s3(
            pudl_version=PUDL_VERSION_TEST,
            download_directory=download_directory,
            quiet=True,
        )

        with open(os.path.join(download_directory, "pudl.sqlite"), "rb") as f:
            self.assertEqual(f.read(), self.sqlite_content)
        # The downloaded zip is cleaned up after extraction
        self.assertEqual(
            sorted(os.listdir(download_directory)),
            ["data_metadata.csv", "pudl.sqlite"],
        )

        metadata = self.read_metadata(download_directory)
        self.assertEqual(metadata["output_file"].unique().tolist(), ["pudl.sqlite"])

    def test_main_downloads_all_and_records_metadata(self):
        download_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        download_data_from_pudl.main(
            [
                "--pudl_version",
                PUDL_VERSION_TEST,
                "--pudl_download_directory",
                download_directory,
                "--quiet",
            ]
        )

        for table_name in MAIN_TABLE_NAMES:
            self.assertTrue(
                os.path.exists(
                    os.path.join(download_directory, f"{table_name}.parquet")
                )
            )

        metadata = self.read_metadata(download_directory)
        # The run arguments as given
        run_args = metadata[metadata["output_file"] == "run_arguments"]
        run_args_settings = dict(zip(run_args["setting"], run_args["value"]))
        self.assertEqual(run_args_settings["pudl_version"], PUDL_VERSION_TEST)
        # Per-file entries for every downloaded table
        self.assertEqual(
            sorted(
                metadata[metadata["output_file"] != "run_arguments"][
                    "output_file"
                ].unique()
            ),
            sorted(f"{t}.parquet" for t in MAIN_TABLE_NAMES),
        )
        # A single-release download: no mixed-version warning
        self.assertNotIn("run_warnings", metadata["output_file"].tolist())

    def test_main_warns_on_mixed_versions(self):
        download_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        # Simulate a file downloaded earlier under a different release and
        # not re-downloaded by this run
        log_data_metadata(
            directory=download_directory,
            script="download_data_from_pudl",
            output_file="extra_table.parquet",
            settings={"pudl_version": "v-old"},
        )

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            download_data_from_pudl.main(
                [
                    "--pudl_version",
                    PUDL_VERSION_TEST,
                    "--pudl_download_directory",
                    download_directory,
                    "--quiet",
                ]
            )

        self.assertIn("more than one PUDL data release", captured.getvalue())
        metadata = self.read_metadata(download_directory)
        warnings_rows = metadata[metadata["output_file"] == "run_warnings"]
        warning_settings = dict(zip(warnings_rows["setting"], warnings_rows["value"]))
        self.assertIn(
            "extra_table.parquet: v-old", warning_settings["mixed_pudl_versions"]
        )
        self.assertIn(
            f"core_eia860__scd_generators.parquet: {PUDL_VERSION_TEST}",
            warning_settings["mixed_pudl_versions"],
        )

    def test_metadata_appends_across_downloads(self):
        download_directory = tempfile.mkdtemp(dir=self.tmp_dir.name)
        download_data_from_pudl.get_parquet_file_from_pudl_s3(
            pudl_version=PUDL_VERSION_TEST,
            filename="test_table",
            download_directory=download_directory,
            quiet=True,
        )
        download_data_from_pudl.get_pudl_sqlite_from_pudl_s3(
            pudl_version=PUDL_VERSION_TEST,
            download_directory=download_directory,
            quiet=True,
        )

        metadata = self.read_metadata(download_directory)
        self.assertEqual(
            metadata["output_file"].unique().tolist(),
            ["test_table.parquet", "pudl.sqlite"],
        )

    @classmethod
    def tearDownClass(cls):
        download_data_from_pudl.PUDL_S3_BASE_URL = cls.orig_base_url
        download_data_from_pudl.PUDL_ZENODO_CONCEPT_RECORD_URL = cls.orig_zenodo_url
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
