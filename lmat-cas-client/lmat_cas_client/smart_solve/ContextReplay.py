"""
Replay a list of prior math blocks through the Smart Solve dispatcher to
reconstruct the implicit context (definitions, constraints) for the current
block.

Design_docs.md §"The Context": context is rebuilt from scratch on every hotkey
press by walking the document from the most recent section divider to the
cursor. ContextReplay is the Python side of that walk: TypeScript hands over the
list of prior block LaTeX strings, we run each through a minimal version of the
dispatch and accumulate the resulting definitions.
"""

from collections import OrderedDict
from dataclasses import dataclass

from sympy import Dummy, FiniteSet, S, Symbol, simplify, solveset, sympify
from sympy.core.function import AppliedUndef
from sympy.core.relational import Equality, Relational

from lmat_cas_client.compiling.Compiler import LatexToSympyCompiler
from lmat_cas_client.compiling.Definitions import MultiValueDefinition, SympyDefinition
from lmat_cas_client.compiling.DefinitionStore import DefinitionStore
from lmat_cas_client.LmatEnvironment import LmatEnvironment
from lmat_cas_client.smart_solve import Tiebreaker
from lmat_cas_client.smart_solve.ConstraintStore import (
    ConstraintStore,
    apply_determined,
)
from lmat_cas_client.smart_solve.MatrixSupport import (
    assignment_value,
    has_matrix,
    is_matrix,
    matrix_assignment_sides,
    to_plain_matrix,
)
from lmat_cas_client.smart_solve.Provenance import VectorDefinition, compute_family


@dataclass
class ReplayedContext:
    def_store: DefinitionStore
    constraints: ConstraintStore

    def clone(self) -> "ReplayedContext":
        return ReplayedContext(
            def_store=self.def_store.clone(),
            constraints=self.constraints.clone(),
        )


# Bounded LRU cache for replayed contexts (design_docs.md §"Caching").
# Keyed on the tuple of prior-block LaTeX strings + an environment signature.
# Re-pressing the hotkey on the same block hits this directly.
_REPLAY_CACHE_MAX = 32
_replay_cache: "OrderedDict[tuple, ReplayedContext]" = OrderedDict()


def _env_signature(env: LmatEnvironment) -> tuple:
    return (
        tuple(sorted((k, tuple(v)) for k, v in env.symbols.items())),
        tuple((d.name_expr, d.value_expr) for d in env.definitions),
        env.unit_system,
        env.solve_domain,
        env.render_sig_figs,
    )


# Markdown comment marker for "this block is documentation only".
# Matches design_docs.md §"Reference Equations".
def is_ref_block(latex: str) -> bool:
    import re

    return re.search(r"%\s*\\?text\{?\s*ref\b|%\s*ref\b", latex) is not None


def replay_blocks(
    blocks: list[str],
    base_environment: LmatEnvironment,
    compiler: LatexToSympyCompiler,
) -> ReplayedContext:
    """
    Replay each prior block, accumulating definitions AND constraints in a
    fresh context.

    Errors during replay are silently ignored — the user's prior state is what
    it is, and the only error we surface is the one for the current block.
    """
    cache_key = (tuple(blocks), _env_signature(base_environment))
    cached = _replay_cache.get(cache_key)
    if cached is not None:
        _replay_cache.move_to_end(cache_key)
        return cached.clone()

    # Start with assumptions only, then overlay env definitions.
    asm_env = LmatEnvironment(
        symbols=base_environment.symbols,
        definitions=[],
        unit_system=base_environment.unit_system,
        solve_domain=base_environment.solve_domain,
    )
    store = LmatEnvironment.create_definition_store(asm_env)
    if base_environment.definitions:
        store = LmatEnvironment.create_definition_store(base_environment)

    constraints = ConstraintStore()

    for latex in blocks:
        if not latex.strip():
            continue
        if is_ref_block(latex):
            continue
        try:
            _replay_one(latex, store, constraints, base_environment, compiler)
        except Exception:
            continue
        # After each block, re-attempt the constraint system. A newly-stored
        # definition may make previously-stuck constraints solvable.
        try:
            determined = constraints.solve_and_materialize(store, None)
        except Exception:
            determined = {}
        if determined:
            apply_determined(store, determined)

    result = ReplayedContext(def_store=store, constraints=constraints)

    _replay_cache[cache_key] = result.clone()
    if len(_replay_cache) > _REPLAY_CACHE_MAX:
        _replay_cache.popitem(last=False)

    return result


def create_context(
    base_environment: LmatEnvironment,
    compiler: LatexToSympyCompiler,
) -> ReplayedContext:
    return replay_blocks([], base_environment, compiler)


def advance_context(
    context: ReplayedContext,
    latex: str,
    base_environment: LmatEnvironment,
    compiler: LatexToSympyCompiler,
) -> None:
    if not latex.strip() or is_ref_block(latex):
        return

    try:
        _replay_one(
            latex, context.def_store, context.constraints, base_environment, compiler
        )
    except Exception:
        return

    try:
        determined = context.constraints.solve_and_materialize(context.def_store, None)
    except Exception:
        determined = {}

    if determined:
        apply_determined(context.def_store, determined)


def _replay_one(
    latex: str,
    store: DefinitionStore,
    constraints: ConstraintStore,
    environment: LmatEnvironment,
    compiler: LatexToSympyCompiler,
) -> None:
    """Apply a single prior block's effects to `store` and `constraints` in place."""

    asm_store = LmatEnvironment.create_definition_store(
        LmatEnvironment(
            symbols=environment.symbols,
            definitions=[],
            unit_system=environment.unit_system,
            solve_domain=environment.solve_domain,
        )
    )

    try:
        expr = compiler.compile(latex, asm_store)
    except Exception:
        # Mirror Dispatcher: a block adding a vector symbol to a literal vector
        # (`u + \ihat`) can't parse with scalar symbols; retry with matrix-valued
        # definitions substituted.
        expr = compiler.compile(latex, _matrix_def_store(store, asm_store))

    if isinstance(expr, Relational):
        _replay_relation(expr, store, constraints, environment, latex)


def _matrix_def_store(
    store: DefinitionStore, asm_store: DefinitionStore
) -> DefinitionStore:
    """`asm_store` augmented with every matrix-valued definition (mirrors
    Dispatcher._matrix_def_store)."""
    matrix_defs = {}
    for name in store.get_definition_names():
        defn = store.get_definition(name)
        try:
            value = defn.defined_value(store)
        except Exception:
            continue
        if is_matrix(value):
            matrix_defs[name] = defn
    return asm_store.override(matrix_defs)


def _replay_relation(
    expr: Relational,
    store: DefinitionStore,
    constraints: ConstraintStore,
    environment: LmatEnvironment,
    latex: str,
) -> None:
    if isinstance(expr, Equality) and isinstance(expr.rhs, Dummy):
        return

    if isinstance(expr.lhs, AppliedUndef):
        return

    # Matrix/vector assignment (`\vec v = <vector>`): store it as a definition.
    # Mirrors Dispatcher._assign_matrix so the persisted context matches what
    # the dispatcher displayed. The vector may carry its own free parameters.
    target, value_side = matrix_assignment_sides(expr)
    if target is not None:
        if _store_matrix_assignment(target, value_side, store, latex):
            return

    syntactic = set(expr.free_symbols)
    if len(syntactic) == 0:
        return

    if len(syntactic) == 1:
        target = next(iter(syntactic))
        _solve_and_store(expr, target, store, environment, latex)
        return

    # 2+ syntactic vars: substitute defined ones, see what remains.
    defined = {s for s in syntactic if store.get_definition(s.name) is not None}

    # A single isolated target whose value side becomes a matrix after
    # substitution is a vector assignment (`\vec w = 2\vec v`). Mirrors
    # Dispatcher._dispatch_relation.
    undefined = syntactic - defined
    if len(undefined) == 1:
        only_target = next(iter(undefined))
        value_side = assignment_value(expr, only_target)
        if value_side is not None and _store_matrix_assignment(
            only_target, value_side, store, latex
        ):
            return

    substituted = expr
    for sym in defined:
        defn = store.get_definition(sym.name)
        if defn is None:
            continue
        try:
            if isinstance(defn, MultiValueDefinition):
                value = Tiebreaker.select(list(defn.values), None).chosen
            else:
                value = defn.defined_value(store)
            # Normalize matrices: the LatexMatrix subclass breaks scalar `subs`.
            substituted = substituted.subs(sym, to_plain_matrix(value))
        except Exception:
            return

    if not isinstance(substituted, Relational):
        return

    remaining = substituted.free_symbols
    if len(remaining) == 1:
        target = next(iter(remaining))
        _solve_and_store(substituted, target, store, environment, latex)
        return

    # ≥2 remaining unresolved vars → add as a constraint and try to materialize
    # uniquely determined variables (design_docs.md §"Permissive Partial-
    # System Solving").
    new_constraint = substituted.lhs - substituted.rhs
    determined = constraints.solve_and_materialize(store, new_constraint)
    if determined:
        apply_determined(store, determined)


def _store_vector(
    target: Symbol, value, store: DefinitionStore, latex: str, referenced
) -> None:
    """Store `target` as a vector definition, recording its notation provenance
    (design_docs.md §"Rendering Provenance Requirements").

    `referenced` is the value side's symbols *before* substitution — provenance
    derives from them (and the block's literal notation), so it must match what
    Dispatcher._assign_matrix computes for the same block.
    """
    family = compute_family(latex, referenced, store)
    store.set_definition(target.name, VectorDefinition(to_plain_matrix(value), family))


def _store_matrix_assignment(
    target: Symbol,
    value_side,
    store: DefinitionStore,
    latex: str,
) -> bool:
    """Substitute any defined symbols into `value_side`; if it is a matrix,
    store `target := <matrix>` (with provenance) and return True. Otherwise
    return False."""
    # Capture referenced symbols before substitution erases them.
    referenced = value_side.free_symbols - {target}
    value = value_side
    for sym in list(value.free_symbols):
        if sym == target:
            continue
        defn = store.get_definition(sym.name)
        if defn is None:
            continue
        try:
            if isinstance(defn, MultiValueDefinition):
                sub = Tiebreaker.select(list(defn.values), None).chosen
            else:
                sub = defn.defined_value(store)
            value = value.subs(sym, to_plain_matrix(sub))
        except Exception:
            continue
    try:
        value = value.doit()
    except Exception:
        pass
    if not is_matrix(value):
        return False
    _store_vector(target, value, store, latex, referenced)
    return True


def _solve_and_store(
    equation: Relational,
    target: Symbol,
    store: DefinitionStore,
    environment: LmatEnvironment,
    latex: str,
) -> None:
    domain = S.Complexes
    if environment.solve_domain and environment.solve_domain.strip():
        try:
            domain = sympify(environment.solve_domain)
        except Exception:
            pass

    # Matrix/vector assignment (`\vec v = <vector>`): store it as a definition.
    # `solveset` can't solve matrix-valued equations, so this must be handled
    # before the solve path. Mirrors Dispatcher._solve_single.
    assigned = assignment_value(equation, target)
    if assigned is not None:
        referenced = assigned.free_symbols - {target}
        value = assigned
        try:
            value = simplify(value.doit())
        except Exception:
            pass
        if is_matrix(value):
            _store_vector(target, value, store, latex, referenced)
            return

    # Other matrix equations aren't solvable here; skip (don't crash solveset).
    if has_matrix(equation.lhs) or has_matrix(equation.rhs):
        return

    try:
        solutions = solveset(equation, target, domain=domain)
    except Exception:
        return

    if not isinstance(solutions, FiniteSet) or len(solutions) == 0:
        return

    candidates = [simplify(solution) for solution in solutions.args]
    if len(candidates) == 1:
        store.set_definition(target.name, SympyDefinition(candidates[0]))
        return

    store.set_definition(target.name, MultiValueDefinition(candidates))
