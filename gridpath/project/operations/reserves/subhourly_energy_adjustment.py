# Copyright 2016-2023 Blue Marble Analytics LLC.
# Copyright 2026 Sylvan Energy Analytics LLC
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

from gridpath.project.operations.reserves.reserve_aggregation import (
    subhourly_footroom_adjustment_rule,
    subhourly_headroom_adjustment_rule,
)

# TODO: shoud probably re-name to sub-timepoint from subhourly


def footroom_subhourly_energy_adjustment_rule(d, mod, g, tmp):
    """
    Subhourly curtailment (difference from scheduled energy) from providing
    downward reserves

    Each footroom variable is multiplied by its reserve type's subhourly
    energy adjustment param, whose value varies by the project's balancing
    area (the component names vary by reserve type and are recorded in the
    dynamic components; see reserve_aggregation for how they're resolved).
    :param d:
    :param mod:
    :param g:
    :param tmp:
    :return:
    """
    return subhourly_footroom_adjustment_rule(d, mod, g, tmp)


def headroom_subhourly_energy_adjustment_rule(d, mod, g, tmp):
    """
    Subhourly additional energy delivered from providing upward reserves

    Each headroom variable is multiplied by its reserve type's subhourly
    energy adjustment param, whose value varies by the project's balancing
    area (the component names vary by reserve type and are recorded in the
    dynamic components; see reserve_aggregation for how they're resolved).
    :param d:
    :param mod:
    :param g:
    :param tmp:
    :return:
    """
    return subhourly_headroom_adjustment_rule(d, mod, g, tmp)
