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

import gdown
import os.path

from db.utilities.common_functions import confirm


def download_file_from_gdrive(gdrive_file_id, filename, download_directory):
    """ """
    proceed = True
    filepath = os.path.join(download_directory, filename)
    if os.path.exists(filepath):
        proceed = confirm(
            f"WARNING: The file {filepath} already exists. Downloading "
            f"the data again will overwrite the previous file. Are you sure?"
        )

    if proceed:
        print(f"Downloading {filename}...")
        gdrive_file_id = f"https://drive.google.com/uc?id={gdrive_file_id}"
        gdown.download(gdrive_file_id, filepath, quiet=False)
