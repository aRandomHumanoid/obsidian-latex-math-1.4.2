"""
Accumulated constraint store for Smart Solve (design_docs.md §"Permissive
Partial-System Solving").

When a block has ≥2 unresolved free variables, it's stored as a constraint
(expression equated to zero: lhs - rhs). On every new block we try to solve
the accumulated system. Any variable whose value comes out concrete (no free
parameters) is promoted to a definition; the rest stay as constraints.
"""

from typing import Optional

from sympy import Expr, FiniteSet, Symbol, Tuple, linsolve, nonlinsolve, simplify
from sympy.solvers.solveset import NonlinearError

from lmat_cas_client.compiling.Definitions import (
    AssumptionDefinition,
    SympyDefinition,
)
from lmat_cas_client.compiling.DefinitionStore import DefinitionStore


class ConstraintStore:
    """Holds equations as (lhs - rhs) expressions equated to 0."""

    def __init__(self) -> None:
        self.constraints: list[Expr] = []

    def add(self, eq_zero: Expr) -> None:
        """Append a constraint of the form expression == 0."""
        self.constraints.append(eq_zero)

    def clone(self) -> "ConstraintStore":
        cs = ConstraintStore()
        cs.constraints = list(self.constraints)
        return cs

    def solve_and_materialize(
        self,
        def_store: DefinitionStore,
        new_constraint: Optional[Expr] = None,
    ) -> dict[str, Expr]:
        """
        Try to solve the accumulated system (existing constraints + optional
        new one) using known definitions for substitution. Return the names
        and values of any variables uniquely determined by the solve.

        Side effects:
          - `new_constraint` is added to self.constraints (whether or not it
            contributes to a unique determination).
          - Constraints whose every free symbol becomes uniquely determined
            are dropped from the store (no longer informative).
          - Resolved values are NOT applied to `def_store` — the caller does
            that, so it can also emit toasts as it goes.
        """
        if new_constraint is not None:
            self.constraints.append(new_constraint)

        if not self.constraints:
            return {}

        substituted = [self._substitute_known(c, def_store) for c in self.constraints]

        # Collect remaining free symbols. Skip any that became constants.
        all_free: set[Symbol] = set()
        for c in substituted:
            all_free |= c.free_symbols

        if len(all_free) == 0:
            return {}

        ordered_syms = sorted(all_free, key=lambda s: s.name)

        solutions = _solve(substituted, ordered_syms)
        if solutions is None:
            return {}

        # Take the first solution tuple (matches our Tiebreaker convention of
        # picking the natural-ordering candidate when multiple exist).
        first = next(iter(solutions), None)
        if first is None:
            return {}

        # linsolve/nonlinsolve wrap their solutions in sympy.Tuple, not a
        # plain Python tuple. Treat both the same way.
        if isinstance(first, (tuple, Tuple)):
            first = tuple(first)
        else:
            first = (first,)

        determined: dict[str, Expr] = {}
        for sym, value in zip(ordered_syms, first):
            if value == sym:
                continue  # underdetermined: linsolve returns the symbol itself
            if not value.free_symbols:
                try:
                    determined[sym.name] = simplify(value)
                except Exception:
                    determined[sym.name] = value

        # Prune constraints whose every free symbol is now determined.
        if determined:
            kept: list[Expr] = []
            for original, sub in zip(self.constraints, substituted):
                sub_free = sub.free_symbols
                if sub_free and all(s.name in determined for s in sub_free):
                    continue
                kept.append(original)
            self.constraints = kept

        return determined

    @staticmethod
    def _substitute_known(expr: Expr, def_store: DefinitionStore) -> Expr:
        for sym in list(expr.free_symbols):
            defn = def_store.get_definition(sym.name)
            if defn is None or isinstance(defn, AssumptionDefinition):
                continue
            try:
                expr = expr.subs(sym, defn.defined_value(def_store))
            except Exception:
                continue
        return expr


def _solve(equations: list[Expr], symbols: list[Symbol]) -> Optional[FiniteSet]:
    """Try linsolve first, fall back to nonlinsolve. Return None on failure."""
    try:
        result = linsolve(equations, symbols)
    except NonlinearError:
        try:
            result = nonlinsolve(equations, symbols)
        except Exception:
            return None
    except Exception:
        return None

    if not isinstance(result, FiniteSet) or len(result) == 0:
        return None
    return result


def apply_determined(
    def_store: DefinitionStore,
    determined: dict[str, Expr],
) -> None:
    """Apply uniquely-determined variables to the definition store as values."""
    for name, value in determined.items():
        def_store.set_definition(name, SympyDefinition(value))
