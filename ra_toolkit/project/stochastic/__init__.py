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

"""
Machinery shared by the project steps that generate weather- and
hydro-dependent inputs — variable generation profiles, generator weather
derates, hydro budgets — in either of the two flavors GridPath supports:

* **synchronous** (:mod:`ra_toolkit.project.stochastic.sync_gen_common`)
  — one profile per historical weather year, used directly;
* **Monte Carlo**
  (:mod:`ra_toolkit.project.stochastic.monte_carlo_gen_common`) — draws
  assembled from weather bins by the temporal weather-draw steps.

:mod:`ra_toolkit.project.stochastic.iterations` writes the per-project
``iterations`` CSV that tells GridPath which draws a project's data varies
over.

This is a separate pipeline from the EIA860(M)-based project steps in
:mod:`data_toolkit.project`: the two share no code, and a step draws on
one or the other, never both. Steps here take their project list from the
profiles' own raw data rather than from the EIA860 filters.
"""
