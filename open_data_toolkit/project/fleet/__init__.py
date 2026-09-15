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
The EIA860(M) fleet pipeline: how raw generator rows become the set of
GridPath projects a study models. Every ``eia860*_to_project_*`` step
composes the same four stages, in this order, and this package holds one
module per stage:

0. **BA assignment** (:mod:`open_data_toolkit.project.fleet.ba_assignment`) —
   resolve each generator's balancing authority: manual overrides, then
   the EIA-930A operational inventory, then the EIA-860 plant-reported
   value. Produces the generator relation everything else selects FROM.
1. **Geographic scope** (:mod:`open_data_toolkit.geographic_scope`, which lives
   one level up because the system and transmission pipelines consume it
   too) — which BAs are in the study footprint, and what load zone each
   maps to at the chosen load-zone level.
2. **Fleet filters** (:mod:`open_data_toolkit.project.fleet.fleet_filters`) —
   which units qualify: operational-status tiers, operating/retirement
   dates against the study year, behind-the-meter sectors. Its
   :func:`get_fleet_relation_sql` is the canonical FROM/JOIN/WHERE block
   the steps put a SELECT list on top of.
3. **Aggregation** (:mod:`open_data_toolkit.project.fleet.aggregation`) — how
   the qualifying units are named, and thereby whether they are modeled
   individually or grouped into aggregate projects.

Two more modules support the steps rather than adding a stage:
:mod:`open_data_toolkit.project.fleet.step_common` holds the scaffolding every
step's ``main`` runs (resolve settings, connect, run the scope checks and
data-gap warnings), and :mod:`open_data_toolkit.project.fleet.fleet_audit` is
the ``gridpath_fleet_audit`` step, which reports what these stages decided
about every unit — the intermediate checkpoint between the raw data and
the generated input CSVs.

Note that :mod:`open_data_toolkit.project.project_data_filters_common`, one
level up, re-exports this package's public names under their historical
import path; it is the documented import surface for callers outside this
repository and is kept deliberately.
"""
