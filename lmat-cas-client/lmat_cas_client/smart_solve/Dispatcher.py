import re
from dataclasses import dataclass, field
from typing import Optional

from sympy import (
    Dummy,
    Expr,
    FiniteSet,
    S,
    Symbol,
    Tuple,
    linsolve,
    nonlinsolve,
    simplify,
    solveset,
    sympify,
)
from sympy.core.function import AppliedUndef
from sympy.core.relational import Equality, Relational
from sympy.logic.boolalg import BooleanAtom, BooleanTrue
from sympy.physics.units.unitsystem import UnitSystem
from sympy.solvers.solveset import NonlinearError

import lmat_cas_client.math_lib.units.UnitUtils as UnitUtils
from lmat_cas_client.compiling.Compiler import LatexToSympyCompiler
from lmat_cas_client.compiling.Definitions import MultiValueDefinition
from lmat_cas_client.compiling.DefinitionStore import DefinitionStore
from lmat_cas_client.compiling.transforming.SystemOfExpr import SystemOfExpr
from lmat_cas_client.LmatEnvironment import LmatEnvironment
from lmat_cas_client.LmatLatexPrinter import lmat_latex
from lmat_cas_client.smart_solve import Tiebreaker
from lmat_cas_client.smart_solve.Renderer import DEFAULT_SIG_FIGS, render

# --- Result envelope -------------------------------------------------------


@dataclass
class Toast:
    severity: str  # "info" | "warning" | "error"
    text: str


@dataclass
class DispatchResult:
    # "display"  -> render display_latex inline (with the result marker on the TS side)
    # "silent"   -> no inline change; toasts only
    # "no_op"    -> intentionally skipped (e.g. %ref)
    kind: str
    display_latex: Optional[str] = None
    toasts: list[Toast] = field(default_factory=list)
    is_multiline: Optional[bool] = None
    end_line: Optional[int] = None


def _display(latex: str, toasts: list[Toast] | None = None) -> DispatchResult:
    return DispatchResult(
        kind="display", display_latex=latex, toasts=list(toasts or [])
    )


def _silent(toasts: list[Toast] | None = None) -> DispatchResult:
    return DispatchResult(kind="silent", toasts=list(toasts or []))


def _no_op() -> DispatchResult:
    return DispatchResult(kind="no_op")


def _error(text: str) -> DispatchResult:
    return _silent([Toast("error", text)])


# --- Helpers ---------------------------------------------------------------


def _parse_domain(env: LmatEnvironment):
    if env.solve_domain is not None and env.solve_domain.strip() != "":
        return sympify(env.solve_domain)
    return S.Complexes


def _auto_convert(expr: Expr, env: LmatEnvironment) -> Expr:
    if env.unit_system is not None:
        return UnitUtils.auto_convert(expr, UnitSystem.get_unit_system(env.unit_system))
    return UnitUtils.auto_convert(expr)


def _evaluate_expression(expr: Expr, env: LmatEnvironment) -> Expr:
    return _auto_convert(simplify(expr.doit()), env)


def _resolve_definition_value(
    sym: Symbol,
    def_store: DefinitionStore,
    *,
    for_calculation: bool,
    sig_figs: int,
) -> tuple[object | None, list[Toast]]:
    defn = def_store.get_definition(sym.name)
    if defn is None:
        return None, []

    if isinstance(defn, MultiValueDefinition):
        if not for_calculation:
            return defn.defined_value(def_store), []

        selection = Tiebreaker.select(list(defn.values), None)
        toasts: list[Toast] = []
        if selection.was_choice_made:
            all_sols = ", ".join(render(s, sig_figs) for s in defn.values)
            toasts.append(
                Toast(
                    "warning",
                    f"Multiple stored values for {sym}: {{{all_sols}}}. Using {render(selection.chosen, sig_figs)} for this calculation.",
                )
            )
        return selection.chosen, toasts

    try:
        return defn.defined_value(def_store), []
    except Exception:
        return None, []


def _substitute_defined(
    expr: Expr,
    targets: set[Symbol],
    def_store: DefinitionStore,
) -> tuple[Expr, list[Toast]]:
    """Substitute definitions for every free symbol in `expr` that is NOT in `targets`."""
    toasts: list[Toast] = []
    for sym in list(expr.free_symbols):
        if sym in targets:
            continue
        value, value_toasts = _resolve_definition_value(
            sym,
            def_store,
            for_calculation=True,
            sig_figs=DEFAULT_SIG_FIGS,
        )
        if value is None:
            continue
        toasts.extend(value_toasts)
        expr = expr.subs(sym, value)
    return expr, toasts


def _resolve_sig_figs(environment: LmatEnvironment) -> int:
    """Step 9: per-document `[render] sig_figs` override (default falls back to 3)."""
    return getattr(environment, "render_sig_figs", None) or DEFAULT_SIG_FIGS


def _assignment_latex(target: Symbol, value: Expr, sig_figs: int) -> str:
    return f"{lmat_latex(target)} = {render(value, sig_figs)}"


# Match a LaTeX comment that contains `ref` as a whole word.
# Covers `%ref`, `% ref`, and `% \text{ref}`.
_REF_REGEX = re.compile(r"%\s*\\?text\{?\s*ref\b|%\s*ref\b", re.IGNORECASE)


def _is_ref_block(latex_str: str) -> bool:
    return bool(_REF_REGEX.search(latex_str))


def _resolve_prior(target: Symbol, def_store: DefinitionStore) -> Optional[Expr]:
    """Return the current value of `target` in the store, or None if undefined.
    Symbol-only assumption definitions are NOT a value — they return the symbol itself.
    """
    defn = def_store.get_definition(target.name)
    if defn is None:
        return None
    if isinstance(defn, MultiValueDefinition):
        return Tiebreaker.select(list(defn.values), None).chosen
    try:
        value = defn.defined_value(def_store)
    except Exception:
        return None
    # An AssumptionDefinition just stores the symbol; that means "x is real" not "x = ...".
    if value == target:
        return None
    return value


def _filter_by_assumptions(target: Symbol, candidates: list[Expr]) -> list[Expr]:
    """
    sympy's solveset uses the domain parameter but does not honor a symbol's
    declared assumptions (positive, integer, etc.) as a post-filter. Apply them
    here so e.g. `x` declared positive only takes the positive root of x^2 = 9.
    """
    filtered = []
    for sol in candidates:
        if not _satisfies_assumptions(target, sol):
            continue
        filtered.append(sol)
    return filtered


def _satisfies_assumptions(target: Symbol, sol: Expr) -> bool:
    checks = [
        ("is_positive", True),
        ("is_negative", True),
        ("is_nonnegative", True),
        ("is_nonpositive", True),
        ("is_real", True),
        ("is_integer", True),
        ("is_rational", True),
    ]
    for attr, _ in checks:
        target_value = getattr(target, attr, None)
        if target_value is True:
            sol_value = getattr(sol, attr, None)
            if sol_value is False:
                return False
    return True


def _values_equal(a: Expr, b: Expr) -> bool:
    try:
        diff = simplify(a - b)
    except Exception:
        return False
    return diff == 0


def _try_resolve_via_constraints(
    expr: Expr,
    constraints,  # ConstraintStore
    def_store: DefinitionStore,
) -> tuple[Optional[Expr], list[Toast]]:
    """
    Attempt to express `expr` using the accumulated constraint system.

    When the user evaluates a symbol that has no concrete definition but
    appears in a constraint (e.g. `x = y + z` with `y = 3z + 5` and the user
    asks for `x`), we solve the system over all constraint variables and
    substitute the matching solutions back into the expression. The result
    may still contain free parameters (here, `z`) — that's the symbolic
    answer the user wants instead of an "undefined variable" error.

    Returns the substituted/simplified expression, or `None` if no useful
    progress was made (no constraints, solver failure, etc.).
    """
    if not getattr(constraints, "constraints", None):
        return None, []

    toasts: list[Toast] = []

    # Materialize any definitions already in the store before solving — this
    # mirrors ConstraintStore.solve_and_materialize's behavior so we don't
    # re-derive what's already known.
    substituted_constraints: list[Expr] = []
    for c in constraints.constraints:
        sc = c
        for sym in list(sc.free_symbols):
            value, value_toasts = _resolve_definition_value(
                sym,
                def_store,
                for_calculation=True,
                sig_figs=DEFAULT_SIG_FIGS,
            )
            if value is None:
                continue
            toasts.extend(value_toasts)
            try:
                sc = sc.subs(sym, value)
            except Exception:
                continue
        substituted_constraints.append(sc)

    all_constraint_syms: set[Symbol] = set()
    for c in substituted_constraints:
        all_constraint_syms |= c.free_symbols
    if not all_constraint_syms:
        return None, toasts

    ordered = sorted(all_constraint_syms, key=lambda s: s.name)

    try:
        sols = linsolve(substituted_constraints, ordered)
    except NonlinearError:
        try:
            sols = nonlinsolve(substituted_constraints, ordered)
        except Exception:
            return None, toasts
    except Exception:
        return None, toasts

    if not isinstance(sols, FiniteSet) or len(sols) == 0:
        return None, toasts

    first = next(iter(sols))
    if isinstance(first, (tuple, Tuple)):
        first = tuple(first)
    else:
        first = (first,)

    sub_dict: dict[Symbol, Expr] = {}
    for sym, value in zip(ordered, first):
        # linsolve returns the symbol itself when underdetermined — that's a
        # parametric leave-it-free, not a substitution.
        if value == sym:
            continue
        sub_dict[sym] = value

    if not sub_dict:
        return None, toasts

    try:
        new_expr = expr.subs(sub_dict)
    except Exception:
        return None, toasts

    try:
        new_expr = simplify(new_expr)
    except Exception:
        pass
    return new_expr, toasts


# --- Top-level dispatch ----------------------------------------------------


class SmartSolveDispatcher:
    """
    Implements the Step 0–5 algorithm from design_docs.md.
    Step 1 (basic) scope: := definitions, single-variable solve (with substitution of
    other defined symbols), expression evaluation, trailing-`=` evaluation, verification
    of fully-grounded equalities. Multi-variable constraints return an error toast
    pending Step 6.
    """

    def __init__(self, compiler: LatexToSympyCompiler):
        self._compiler = compiler

    def dispatch(
        self,
        latex_str: str,
        environment: LmatEnvironment,
        prior_blocks: Optional[list[str]] = None,
    ) -> DispatchResult:
        # %ref check (design_docs.md §"Reference Equations"): documentation-only blocks.
        if _is_ref_block(latex_str):
            return _no_op()

        # The compiler eagerly substitutes value definitions during parsing.
        # For Smart Solve we need to see the unsubstituted form so that override
        # semantics (design_docs §"Override Behavior Details") can target a
        # previously-defined symbol. We do that by parsing with an
        # assumptions-only store, then carrying a separately-built full store
        # for substitution decisions made by the dispatcher itself.
        asm_store = LmatEnvironment.create_definition_store(
            LmatEnvironment(
                symbols=environment.symbols,
                definitions=[],
                unit_system=environment.unit_system,
                solve_domain=environment.solve_domain,
            )
        )

        # Full store + constraints include:
        # 1. assumptions from environment.symbols,
        # 2. explicit `:=` definitions from environment.definitions, and
        # 3. derived definitions / constraints from replaying prior blocks.
        from lmat_cas_client.smart_solve.ContextReplay import replay_blocks

        replayed = replay_blocks(prior_blocks or [], environment, self._compiler)
        full_store = replayed.def_store
        constraints = replayed.constraints

        try:
            expr = self._compiler.compile(latex_str, asm_store)
        except Exception as e:
            return _error(f"Could not parse expression: {e}")

        if isinstance(expr, SystemOfExpr):
            return _error("Multi-equation blocks are not yet supported by Smart Solve.")

        if isinstance(expr, Relational):
            return self._dispatch_relation(expr, full_store, constraints, environment)

        return self._dispatch_expression(expr, full_store, constraints, environment)

    # --- Relation cases ---------------------------------------------------

    def _dispatch_relation(
        self,
        expr: Relational,
        def_store: DefinitionStore,
        constraints,  # ConstraintStore — passed as positional to avoid circular import
        environment: LmatEnvironment,
    ) -> DispatchResult:
        # Function-application definition: lhs is f(args).
        # Currently the existing := handling covers this via the TS-side regex;
        # leaving the explicit case here as a hook for Step 2+.
        if isinstance(expr.lhs, AppliedUndef):
            return _silent()

        rhs = expr.rhs

        # Trailing-`=` blocks parse as Eq(lhs, Dummy()). Treat as evaluation of lhs.
        if isinstance(expr, Equality) and isinstance(rhs, Dummy):
            return self._dispatch_expression(
                expr.lhs, def_store, constraints, environment
            )

        syntactic_vars: set[Symbol] = set(expr.free_symbols)

        if len(syntactic_vars) == 0:
            return self._verify_concrete(expr.lhs, expr.rhs)

        if len(syntactic_vars) == 1:
            target = next(iter(syntactic_vars))
            return self._solve_single(expr, target, def_store, environment)

        # 2+ syntactic vars. Substitute defined ones; the remainder are targets.
        defined_syms = {
            s for s in syntactic_vars if def_store.get_definition(s.name) is not None
        }
        targets = syntactic_vars - defined_syms

        substituted, toasts = _substitute_defined(expr, targets, def_store)

        # Substitution may collapse the relation into a Boolean (e.g. Eq(8, 10) → False).
        if isinstance(substituted, BooleanAtom):
            result = self._verify_boolean(substituted, expr)
            result.toasts = toasts + result.toasts
            return result

        remaining = substituted.free_symbols

        if len(remaining) == 0:
            result = self._verify_concrete(substituted.lhs, substituted.rhs)
            result.toasts = toasts + result.toasts
            return result

        if len(remaining) == 1:
            target = next(iter(remaining))
            result = self._solve_single(substituted, target, def_store, environment)
            result.toasts = toasts + result.toasts
            return result

        # ≥2 unresolved targets → constraint accumulation (design_docs.md
        # §"Permissive Partial-System Solving"). Add this equation to the
        # accumulated system and try to solve as much of it as possible.
        from lmat_cas_client.smart_solve.ConstraintStore import apply_determined

        new_constraint = substituted.lhs - substituted.rhs
        determined = constraints.solve_and_materialize(def_store, new_constraint)

        if not determined:
            # System is still underdetermined. Block is stored as a constraint;
            # no inline display (design_docs.md §"Storage Without Display").
            return _silent()

        apply_determined(def_store, determined)
        toasts = [
            Toast(
                "info",
                f"Derived: {name} = {lmat_latex(value)}",
            )
            for name, value in sorted(determined.items())
        ]

        # If the current block contributed a variable that's NOT in `determined`,
        # it stays as a constraint. We still emit toasts for what was derived.
        # The block itself doesn't get an inline display.
        return _silent(toasts)

    def _verify_boolean(self, b: BooleanAtom, original: Relational) -> DispatchResult:
        """Verification when substitution produced True/False directly."""
        if isinstance(b, BooleanTrue):
            return _silent()
        return _silent([
            Toast(
                "error",
                f"Contradiction: {lmat_latex(original.lhs)} ≠ {lmat_latex(original.rhs)} after substitution.",
            )
        ])

    def _verify_concrete(self, lhs: Expr, rhs: Expr) -> DispatchResult:
        try:
            difference = simplify(lhs - rhs)
        except Exception:
            difference = lhs - rhs

        if difference == 0:
            # Silent verification — design doc says "silent or subtle indicator".
            return _silent()

        return _silent([
            Toast(
                "error",
                f"Contradiction: {lmat_latex(lhs)} ≠ {lmat_latex(rhs)}.",
            )
        ])

    def _solve_single(
        self,
        equation: Relational,
        target: Symbol,
        def_store: DefinitionStore,
        environment: LmatEnvironment,
    ) -> DispatchResult:
        domain = _parse_domain(environment)
        sig_figs = _resolve_sig_figs(environment)

        # Capture the prior value (if any) so we can decide between silent override,
        # info toast, and no-op per design_docs §"Override Behavior Details".
        prior_value = _resolve_prior(target, def_store)

        try:
            solutions = solveset(equation, target, domain=domain)
        except Exception as e:
            return _error(f"Solve failed: {e}")

        # Empty solution set — check this first so the cross-domain hint fires
        # before falling into non-FiniteSet handling.
        if solutions == S.EmptySet or (
            isinstance(solutions, FiniteSet) and len(solutions) == 0
        ):
            extra: list[Toast] = []
            if domain == S.Reals:
                try:
                    complex_sols = solveset(equation, target, domain=S.Complexes)
                    has_complex = (
                        isinstance(complex_sols, FiniteSet) and len(complex_sols) > 0
                    ) or (
                        not isinstance(complex_sols, FiniteSet)
                        and complex_sols != S.EmptySet
                    )
                    if has_complex:
                        extra.append(
                            Toast(
                                "warning",
                                "No real solution exists. Complex solutions exist; "
                                "enable complex mode in plugin settings or this "
                                "document's `lmat` block.",
                            )
                        )
                except Exception:
                    pass
            base = _error(f"No solution exists for {target} in {lmat_latex(domain)}.")
            base.toasts.extend(extra)
            return base

        if not isinstance(solutions, FiniteSet):
            try:
                first = next(iter(solutions))
            except (StopIteration, TypeError):
                return _silent([
                    Toast("warning", f"Solution set: {lmat_latex(solutions)}"),
                ])
            value = _auto_convert(simplify(first), environment)
            return self._finish_single_solve(
                target, value, prior_value, toasts=[], sig_figs=sig_figs
            )

        if len(solutions) == 0:
            # Cross-domain hint (design_docs §"Domain Setting").
            extra: list[Toast] = []
            if domain == S.Reals:
                try:
                    complex_sols = solveset(equation, target, domain=S.Complexes)
                    if isinstance(complex_sols, FiniteSet) and len(complex_sols) > 0:
                        extra.append(
                            Toast(
                                "warning",
                                "No real solution exists. Complex solutions exist; "
                                "enable complex mode in plugin settings or this "
                                "document's `lmat` block.",
                            )
                        )
                except Exception:
                    pass
            base = _error(f"No solution exists for {target} in {lmat_latex(domain)}.")
            base.toasts.extend(extra)
            return base

        candidates = [_auto_convert(simplify(s), environment) for s in solutions.args]

        # Apply the target symbol's declared assumptions as a post-filter.
        # sympy's solveset doesn't do this automatically, so a `positive` symbol
        # would otherwise get both ±3 for x^2 = 9.
        candidates = _filter_by_assumptions(target, candidates)

        if len(candidates) == 0:
            return _error(
                f"No solution exists for {target} consistent with declared assumptions."
            )

        selection = Tiebreaker.select(candidates, prior_value)
        toasts: list[Toast] = []

        if selection.was_choice_made:
            all_sols = ", ".join(render(s, sig_figs) for s in candidates)
            toasts.append(
                Toast(
                    "warning",
                    f"Multiple solutions: {{{all_sols}}}. Chose {render(selection.chosen, sig_figs)}.",
                )
            )

        return self._finish_single_solve(
            target, selection.chosen, prior_value, toasts=toasts, sig_figs=sig_figs
        )

    def _finish_single_solve(
        self,
        target: Symbol,
        value: Expr,
        prior_value: Optional[Expr],
        toasts: list[Toast],
        sig_figs: int = DEFAULT_SIG_FIGS,
    ) -> DispatchResult:
        """Apply override semantics from design_docs §"Override Behavior Details"."""
        if prior_value is not None:
            if _values_equal(value, prior_value):
                # Silent no-op: derivation matches the prior value exactly.
                return _silent(toasts)
            toasts = toasts + [
                Toast(
                    "info",
                    f"Overriding {target}: was {render(prior_value, sig_figs)}, "
                    f"now {render(value, sig_figs)}.",
                )
            ]

        return _display(_assignment_latex(target, value, sig_figs), toasts)

    # --- Expression case --------------------------------------------------

    def _dispatch_expression(
        self,
        expr: Expr,
        def_store: DefinitionStore,
        constraints,  # ConstraintStore — positional to keep the import in handle()
        environment: LmatEnvironment,
    ) -> DispatchResult:
        # Substitute all definitions, then evaluate.
        if isinstance(expr, Symbol):
            value, toasts = _resolve_definition_value(
                expr,
                def_store,
                for_calculation=False,
                sig_figs=_resolve_sig_figs(environment),
            )
            if value is not None:
                try:
                    result = _evaluate_expression(value, environment)
                except Exception as e:
                    return _error(f"Evaluation failed: {e}")
                return _display(render(result, _resolve_sig_figs(environment)), toasts)

        substituted, toasts = _substitute_defined(expr, set(), def_store)

        try:
            result = _evaluate_expression(substituted, environment)
        except Exception as e:
            failure = _error(f"Evaluation failed: {e}")
            failure.toasts = toasts + failure.toasts
            return failure

        sig_figs = _resolve_sig_figs(environment)
        unresolved = {s for s in result.free_symbols if not isinstance(s, Dummy)}

        if not unresolved:
            return _display(render(result, sig_figs), toasts)

        # Symbolic fallback: if the accumulated constraints over-determine some
        # of the unresolved symbols, substitute them in. The expression may
        # still have free parameters — that's fine, we surface them so the user
        # knows it's a symbolic answer rather than a numeric one.
        resolved, constraint_toasts = _try_resolve_via_constraints(
            result, constraints, def_store
        )
        if resolved is not None and resolved != result:
            still_unresolved = {
                s for s in resolved.free_symbols if not isinstance(s, Dummy)
            }
            all_toasts = toasts + constraint_toasts
            if still_unresolved:
                free_list = ", ".join(sorted(str(s) for s in still_unresolved))
                all_toasts.append(
                    Toast(
                        "info",
                        f"Symbolic result (free parameters: {free_list}).",
                    )
                )
            return _display(render(resolved, sig_figs), all_toasts)

        var_list = ", ".join(sorted(str(s) for s in unresolved))
        failure = _error(f"Undefined variable(s): {var_list}.")
        failure.toasts = toasts + constraint_toasts + failure.toasts
        return failure
