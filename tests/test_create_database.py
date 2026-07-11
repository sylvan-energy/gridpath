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

import os
import sqlite3
import tempfile
import unittest

from db import create_database
from db.common_functions import update_db_last_modified
from version import __version__

# Change directory to 'db,' as it's what create_database.py expects
os.chdir(os.path.join(os.path.dirname(__file__), "..", "db"))


class TestCreateDatabase(unittest.TestCase):
    """
    Check if the database is created with no errors.
    """

    create_database.main(["--in_memory"])

    def test_db_metadata(self):
        """
        Check that the created database records the GridPath version and the
        creation datetime, that the last-modified datetimes start out NULL,
        and that update_db_last_modified sets only the requested one.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test_metadata.db")
            create_database.main(["--database", db_path])

            conn = sqlite3.connect(db_path)
            metadata = conn.execute("""SELECT gridpath_version, created_datetime,
                inputs_last_modified_datetime, scenarios_last_modified_datetime,
                results_last_imported_datetime, results_last_processed_datetime
                FROM db_metadata;""").fetchall()

            self.assertEqual(len(metadata), 1)
            (
                gridpath_version,
                created,
                inputs_modified,
                scenarios_modified,
                results_imported,
                results_processed,
            ) = metadata[0]
            self.assertEqual(gridpath_version, __version__)
            self.assertIsNotNone(created)
            self.assertIsNone(inputs_modified)
            self.assertIsNone(scenarios_modified)
            self.assertIsNone(results_imported)
            self.assertIsNone(results_processed)

            update_db_last_modified(conn=conn, modification_type="inputs")
            inputs_modified, scenarios_modified = conn.execute(
                """SELECT inputs_last_modified_datetime,
                scenarios_last_modified_datetime FROM db_metadata;"""
            ).fetchone()
            self.assertIsNotNone(inputs_modified)
            self.assertIsNone(scenarios_modified)

            conn.close()

    def test_raw_data_db_metadata(self):
        """
        Check that the raw-data database records the GridPath version.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test_raw_metadata.db")
            create_database.main(
                [
                    "--database",
                    db_path,
                    "--db_schema",
                    "../data_toolkit/raw_data_db_schema.sql",
                    "--omit_data",
                ]
            )

            conn = sqlite3.connect(db_path)
            metadata = conn.execute(
                "SELECT gridpath_version FROM db_metadata;"
            ).fetchall()
            self.assertEqual(metadata, [(__version__,)])

            conn.close()
