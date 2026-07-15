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
Numerical scaling for improved solver conditioning.

Large models can span a wide numerical range: power/energy quantities in MW/MWh
(``10**0``-``10**5``) sit in the same matrix as dollar penalties in ``$/MWh``
that reach ``10**6`` or more after net-present-value weighting. Solvers warn
about (and can stall on) such coefficient ranges.

This module assigns a Pyomo ``scaling_factor`` Suffix so that the built model
can be solved in scaled units -- e.g. GW/GWh instead of MW/MWh (a power/energy
scale factor of ``1000``) and millions of dollars instead of dollars (a dollar
scale factor of ``1000000``). The actual reformulation and the inverse mapping
of the solution (variable values, duals, and reduced costs) back to native
units are done by Pyomo's ``core.scale_model`` transformation; this module only
decides the per-component factors.

Why this is safe: ``core.scale_model`` is an *exact* affine reformulation for
any positive factor assignment (a component with no factor defaults to ``1.0``,
i.e. identity). A units misclassification here therefore only affects
conditioning -- it can never change the optimal solution. In particular, the
mixed-unit cost coefficients (``$/MWh``, ``$/MW-yr``, ``$/MMBtu``, ...) live as
*constants inside rows*, not as variables, and the transformation rescales every
constant coefficient in every row automatically; they are handled structurally
and never need to be enumerated here.

The classification of a component's units is therefore a conditioning heuristic
driven by GridPath's naming conventions:

    * variables carrying an ``MW`` / ``MWh`` / ``MWs`` token (or a trailing
      ``Power``) are power/energy;
    * variables carrying a ``Cost`` token are dollars;
    * integer/binary variables are never scaled (scaling their bounds would
      break integrality);
    * a constraint's factor is inferred from the variables in its body;
    * the objective (net present value, in dollars) is scaled by the dollar
      factor.

Anything not recognized is left at ``1.0`` (unscaled) -- correct, if not
maximally conditioned. Separate "commodity" chains (fuel in MMBtu, emissions in
tons, water volumes) fall into this bucket; extending the heuristic to those is
a localized change here if a model needs it.
"""

from pyomo.environ import Suffix, Var, Constraint, Objective
from pyomo.core.expr import identify_variables, replace_expressions


# Name tokens (split on "_") that mark a variable as power/energy or dollars.
POWER_ENERGY_TOKENS = frozenset({"MW", "MWh", "MWs"})
DOLLAR_TOKEN = "Cost"


def classify_variable_units(name):
    """Classify a variable by its name using GridPath naming conventions.

    Args:
        name: The variable component's name (e.g. ``"GenSimple_Provide_Power_MW"``).

    Returns:
        One of ``"power"``, ``"dollar"``, or ``None`` (unrecognized -- leave
        unscaled). Dollars take precedence over power, though no GridPath
        variable name currently carries both tokens.
    """
    tokens = name.split("_")
    if DOLLAR_TOKEN in tokens:
        return "dollar"
    if any(t in POWER_ENERGY_TOKENS for t in tokens):
        return "power"
    # A trailing "Power" token catches unsuffixed power variables such as
    # "Net_Market_Purchased_Power" without matching generic-unit names like
    # "Fuel_Prod_Consume_Power_PowerUnit" (whose last token is "PowerUnit").
    if tokens[-1] == "Power":
        return "power"
    return None


def _variable_factor(var, s_power, s_dollar):
    """Return the scaling factor for a variable container.

    Integer/binary variables are never scaled (factor ``1.0``): the scaling
    transformation only rescales bounds and values, not the domain, so scaling
    an integer variable by a non-integer factor would silently break
    integrality.

    Args:
        var: A Pyomo ``Var`` container.
        s_power: The power/energy scaling factor (``1 / power_scale_factor``).
        s_dollar: The dollar scaling factor (``1 / dollar_scale_factor``).

    Returns:
        The float scaling factor to assign to the variable (``1.0`` if it should
        not be scaled).
    """
    representative = next(iter(var.values()), None)
    if representative is None:
        return 1.0
    if representative.is_integer():
        return 1.0

    units = classify_variable_units(var.name)
    if units == "power":
        return s_power
    if units == "dollar":
        return s_dollar
    return 1.0


def _constraint_factor(constraint, container_factor, s_dollar):
    """Infer a constraint's scaling factor from the variables in its body.

    A GridPath ``Constraint`` container is built from a single rule over an
    index set, so every data object shares the same variable-unit structure; we
    therefore inspect only one representative active data object rather than the
    whole (potentially huge) index set.

    The rule, applied to the set of non-unity variable factors appearing in the
    body:

        * none -> ``1.0`` (nothing to condition);
        * the dollar factor appears -> use the dollar factor. This is a
          cost-definition row (e.g. ``Hurdle_Cost >= flow * rate``); scaling by
          the dollar factor makes the defining dollar variable's coefficient
          exactly ``1``;
        * exactly one factor -> use it. This is a homogeneous row (e.g. a power
          balance ``sum(MW) == load``); coefficients stay ``O(1)`` and the
          constant right-hand side is rescaled into the new unit;
        * more than one non-dollar factor -> use the smallest (largest scale),
          a safe fallback for the rare genuinely mixed row.

    Args:
        constraint: A Pyomo ``Constraint`` container.
        container_factor: Map from ``id`` of a ``Var`` container to its assigned
            factor.
        s_dollar: The dollar scaling factor.

    Returns:
        The float scaling factor to assign to the constraint.
    """
    representative = next((cd for cd in constraint.values() if cd.active), None)
    if representative is None:
        return 1.0

    factors = set()
    for var_data in identify_variables(representative.body, include_fixed=False):
        factor = container_factor.get(id(var_data.parent_component()), 1.0)
        factors.add(factor)
    factors.discard(1.0)

    if not factors:
        return 1.0
    if s_dollar in factors:
        return s_dollar
    return min(factors)


def assign_scaling_factors(instance, power_scale_factor, dollar_scale_factor):
    """Attach a ``scaling_factor`` Suffix to a built model instance.

    The suffix is consumed by Pyomo's ``core.scale_model`` transformation. Power
    and energy quantities are divided by ``power_scale_factor`` (e.g. ``1000``
    for MW->GW, MWh->GWh) and dollar quantities by ``dollar_scale_factor`` (e.g.
    ``1000000`` for $->$M). Factors are assigned at the component-container level
    (one suffix entry per container, not per data object), which the
    transformation's suffix lookup resolves to every contained data object --
    essential to keep the suffix small on large models.

    Args:
        instance: A concrete Pyomo model instance (already built and, if
            applicable, with fixed variables set).
        power_scale_factor: Factor to divide power/energy quantities by. Must be
            positive.
        dollar_scale_factor: Factor to divide dollar quantities by. Must be
            positive.

    Returns:
        The instance, with an ``instance.scaling_factor`` Suffix attached.

    Raises:
        ValueError: If either scale factor is not positive.
    """
    if power_scale_factor <= 0 or dollar_scale_factor <= 0:
        raise ValueError(
            "Scale factors must be positive; got power_scale_factor="
            f"{power_scale_factor}, dollar_scale_factor={dollar_scale_factor}."
        )

    s_power = 1.0 / power_scale_factor
    s_dollar = 1.0 / dollar_scale_factor

    instance.scaling_factor = Suffix(direction=Suffix.EXPORT)

    # Variables: classify each container and record its factor for the
    # constraint inference pass.
    container_factor = {}
    for var in instance.component_objects(Var, descend_into=True):
        factor = _variable_factor(var, s_power, s_dollar)
        container_factor[id(var)] = factor
        if factor != 1.0:
            instance.scaling_factor[var] = factor

    # Constraints: infer each container's factor from the variables in its body.
    for constraint in instance.component_objects(
        Constraint, descend_into=True, active=True
    ):
        factor = _constraint_factor(constraint, container_factor, s_dollar)
        if factor != 1.0:
            instance.scaling_factor[constraint] = factor

    # Objective(s): net present value is in dollars.
    for objective in instance.component_objects(
        Objective, descend_into=True, active=True
    ):
        instance.scaling_factor[objective] = s_dollar

    return instance


def propagate_scaled_solution(scaled_instance, instance):
    """Map a solved scaled model's solution back onto the original instance.

    This mirrors Pyomo's ``ScaleModel.propagate_solution`` (variable values are
    divided by their scaling factor; duals are multiplied by the constraint
    factor and divided by the objective factor) but tolerates constraints for
    which the solver did not return a dual. Pyomo's own implementation assumes
    every constraint has a dual and raises ``KeyError`` otherwise; solvers
    routinely leave some duals unpopulated (e.g. non-binding market limits under
    CBC), and GridPath's export path already handles a missing dual as ``None``,
    so skipping them here keeps the scaled and unscaled paths equivalent.

    The ``scaled_instance`` must have been produced by the ``core.scale_model``
    transformation (it carries the ``component_scaling_factor_map`` and
    ``scaled_component_to_original_name_map`` used for back-mapping).

    Args:
        scaled_instance: The scaled model, after it has been solved.
        instance: The original (native-unit) model to receive the solution.

    Returns:
        The original ``instance`` with variable values and duals populated in
        native units.
    """
    factor_map = scaled_instance.component_scaling_factor_map
    name_map = scaled_instance.scaled_component_to_original_name_map

    has_dual = hasattr(scaled_instance, "dual") and hasattr(instance, "dual")

    # Objective scaling factor (duals/reduced costs are relative to it). There
    # is exactly one active objective in GridPath (the NPV).
    objective_factor = 1.0
    for scaled_obj in scaled_instance.component_data_objects(
        Objective, active=True, descend_into=True
    ):
        objective_factor = factor_map[scaled_obj]
        break

    # Variable values: original = scaled / factor.
    for scaled_var in scaled_instance.component_objects(Var, descend_into=True):
        original_var = instance.find_component(name_map[scaled_var])
        for k in scaled_var:
            scaled_value = scaled_var[k].value
            if scaled_value is None:
                original_var[k].set_value(None, skip_validation=True)
            else:
                original_var[k].set_value(
                    scaled_value / factor_map[scaled_var[k]],
                    skip_validation=True,
                )

    # Duals: original = scaled * constraint_factor / objective_factor. Skip any
    # constraint the solver left without a dual.
    if has_dual:
        for scaled_con in scaled_instance.component_objects(
            Constraint, descend_into=True
        ):
            original_con = instance.find_component(name_map[scaled_con])
            for k in scaled_con:
                if scaled_con[k] not in scaled_instance.dual:
                    continue
                instance.dual[original_con[k]] = (
                    scaled_instance.dual[scaled_con[k]]
                    * factor_map[scaled_con[k]]
                    / objective_factor
                )

    return instance


def invert_scaled_solution_in_place(instance):
    """Un-scale a solved model that was scaled in place, restoring native units.

    Counterpart to ``propagate_scaled_solution`` for the in-place path: instead
    of cloning the model (``create_using``) and mapping the solution back onto a
    pristine original, the model itself was scaled with ``apply_to(rename=False)``
    and solved. This reverses the scaling on the solved model so that everything
    downstream reads native units:

        * Objective expression: ``apply_to`` rewrote it as
          ``s_obj * (expression in scaled variables)``. We substitute each scaled
          variable ``v -> v * s_v`` (recovering the native-variable expression,
          still multiplied by ``s_obj``) and then divide the whole objective by
          ``s_obj``. This matters because ``save_objective_function_value`` reads
          ``instance.NPV()`` directly; without this it would be off by ``s_obj``.
        * Variable values: ``v <- v / s_v`` (native units).
        * Duals: ``dual <- dual * s_c / s_obj`` (same formula as
          ``propagate_scaled_solution``).

    Named cost/revenue ``Expression`` components are NOT rewritten by scaling
    (only ``Constraint``/``Objective``/``Var`` are), so once variable values are
    native they already evaluate to native dollars and need no adjustment.

    The instance must have been scaled with ``TransformationFactory(
    'core.scale_model').apply_to(instance, rename=False)`` (which stores the
    ``component_scaling_factor_map`` this reads) and then solved.

    Args:
        instance: The in-place-scaled, solved model to restore to native units.

    Returns:
        The instance, with objective, variable values, and duals in native units.
    """
    factor_map = instance.component_scaling_factor_map

    objective_factor = 1.0
    active_objectives = list(
        instance.component_data_objects(Objective, active=True, descend_into=True)
    )
    for obj in active_objectives:
        objective_factor = factor_map[obj]
        break

    # Reverse the objective substitution: undo v -> v / s_v (i.e. put back
    # v -> v * s_v), then remove the objective row factor s_obj.
    for obj in active_objectives:
        substitution = {id(v): v * factor_map[v] for v in identify_variables(obj.expr)}
        obj.expr = replace_expressions(obj.expr, substitution) / objective_factor

    # Un-scale variable values.
    for var in instance.component_data_objects(Var, descend_into=True):
        if var.value is not None:
            var.set_value(var.value / factor_map[var], skip_validation=True)

    # Rescale duals (skip any constraint the solver left without a dual).
    if hasattr(instance, "dual"):
        for constraint in instance.component_data_objects(
            Constraint, active=True, descend_into=True
        ):
            if constraint in instance.dual:
                instance.dual[constraint] = (
                    instance.dual[constraint]
                    * factor_map[constraint]
                    / objective_factor
                )

    return instance
