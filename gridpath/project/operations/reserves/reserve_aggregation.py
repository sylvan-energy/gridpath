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

"""
Helpers for aggregating a project's reserve-provision variables in a
timepoint (headroom/footroom sums and their derated variants).

The reserve variable, derate-param, and balancing-area-param *names* live in
the dynamic components (as strings). Resolving those names with getattr on
every project-timepoint can be a significant share of model construction time,
so the resolved component objects (and per-project param values, which don't
vary by timepoint) are cached on the model instance on first use.
"""

from gridpath.auxiliary.dynamic_components import (
    headroom_variables,
    footroom_variables,
    reserve_variable_derate_params,
    reserve_to_energy_adjustment_params,
)

_CACHE_ATTR = "_gridpath_reserve_component_cache"


def _get_cache(d, mod, key, builder):
    cache = getattr(mod, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(mod, _CACHE_ATTR, cache)
    if key not in cache:
        cache[key] = builder(d, mod, key)
    return cache[key]


def _direction_attr(direction):
    return headroom_variables if direction == "headroom" else footroom_variables


def _build_vars_by_prj(d, mod, key):
    """{prj: [reserve Var component, ...]}"""
    direction = key[0]
    comp_by_name = {}
    return {
        prj: [comp_by_name.setdefault(c, getattr(mod, c)) for c in names]
        for prj, names in getattr(d, _direction_attr(direction)).items()
    }


def _build_derated_vars_by_prj(d, mod, key):
    """{prj: [(reserve Var component, derate param value for prj), ...]}"""
    direction = key[0]
    derate_param_names = getattr(d, reserve_variable_derate_params)
    comp_by_name = {}
    return {
        prj: [
            (
                comp_by_name.setdefault(c, getattr(mod, c)),
                getattr(mod, derate_param_names[c])[prj],
            )
            for c in names
        ]
        for prj, names in getattr(d, _direction_attr(direction)).items()
    }


def _build_adjusted_vars_by_prj(d, mod, key):
    """{prj: [(reserve Var component, subhourly adjustment param value for
    prj's balancing area), ...]}

    The adjustment parameter name varies by reserve type and its value
    varies by balancing area; the balancing area param name also varies by
    reserve type. Both the adjustment param and the balancing area param
    are indexed by project/balancing area only (not timepoint), so they
    resolve to a plain value per project-reserve pair here.
    """
    direction = key[0]
    adjustment_params = getattr(d, reserve_to_energy_adjustment_params)
    comp_by_name = {}
    return {
        prj: [
            (
                comp_by_name.setdefault(c, getattr(mod, c)),
                # adjustment param, indexed by the project's balancing area
                getattr(mod, adjustment_params[c][0])[
                    getattr(mod, adjustment_params[c][1])[prj]
                ],
            )
            for c in names
        ]
        for prj, names in getattr(d, _direction_attr(direction)).items()
    }


def headroom_provision_rule(d, mod, prj, tmp):
    """Sum of the project's headroom (upward reserve) variables in tmp."""
    return sum(
        v[prj, tmp]
        for v in _get_cache(d, mod, ("headroom", "vars"), _build_vars_by_prj)[prj]
    )


def footroom_provision_rule(d, mod, prj, tmp):
    """Sum of the project's footroom (downward reserve) variables in tmp."""
    return sum(
        v[prj, tmp]
        for v in _get_cache(d, mod, ("footroom", "vars"), _build_vars_by_prj)[prj]
    )


def derated_headroom_provision_rule(d, mod, prj, tmp):
    """Sum of the project's headroom variables in tmp, each derated."""
    return sum(
        v[prj, tmp] / derate
        for (v, derate) in _get_cache(
            d, mod, ("headroom", "derated"), _build_derated_vars_by_prj
        )[prj]
    )


def derated_footroom_provision_rule(d, mod, prj, tmp):
    """Sum of the project's footroom variables in tmp, each derated."""
    return sum(
        v[prj, tmp] / derate
        for (v, derate) in _get_cache(
            d, mod, ("footroom", "derated"), _build_derated_vars_by_prj
        )[prj]
    )


def subhourly_headroom_adjustment_rule(d, mod, prj, tmp):
    """Sum of the project's headroom variables in tmp, each multiplied by
    its reserve type's subhourly energy adjustment for the project's
    balancing area."""
    return sum(
        v[prj, tmp] * adj
        for (v, adj) in _get_cache(
            d, mod, ("headroom", "adjusted"), _build_adjusted_vars_by_prj
        )[prj]
    )


def subhourly_footroom_adjustment_rule(d, mod, prj, tmp):
    """Sum of the project's footroom variables in tmp, each multiplied by
    its reserve type's subhourly energy adjustment for the project's
    balancing area."""
    return sum(
        v[prj, tmp] * adj
        for (v, adj) in _get_cache(
            d, mod, ("footroom", "adjusted"), _build_adjusted_vars_by_prj
        )[prj]
    )
