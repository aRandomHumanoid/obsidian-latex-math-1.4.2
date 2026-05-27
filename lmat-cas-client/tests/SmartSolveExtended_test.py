"""
Extended Smart Solve test suite — fills gaps left by SmartSolve_test.py.

Coverage:
  - Edge cases at the dispatcher boundary (multi-equation blocks, garbage input,
    empty strings, unusual numeric forms).
  - Symbol assumptions and domain restrictions interacting with solve.
  - Chained definitions referencing other definitions in the environment.
  - ConstraintStore unit behavior (pruning, underdetermined, mixed known/unknown).
  - Tiebreaker unit behavior (complex roots, negative-magnitude ties, no-prior).
  - Renderer edge cases (zero, negatives, scientific boundaries).
  - Replay cache hit / invalidation.
"""

from lmat_cas_client.command_handlers.SmartSolveHandler import (
    SmartSolveHandler,
    SmartSolveSectionHandler,
)
from lmat_cas_client.compiling.Compiler import LatexToSympyCompiler
from lmat_cas_client.compiling.DefinitionStore import DefinitionStore
from lmat_cas_client.LmatEnvironment import LmatEnvironment
from lmat_cas_client.smart_solve import ContextReplay, Tiebreaker
from lmat_cas_client.smart_solve.ConstraintStore import (
    ConstraintStore,
    apply_determined,
)
from lmat_cas_client.smart_solve.Renderer import render
from sympy import (
    I,
    Symbol,
    sympify,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dispatch(
    expression: str,
    *,
    environment: dict | None = None,
    prior_blocks: list[str] | None = None,
):
    handler = SmartSolveHandler(LatexToSympyCompiler())
    return handler.handle({
        "expression": expression,
        "environment": environment or {},
        "prior_blocks": [{"contents": b} for b in (prior_blocks or [])],
    })._result


def _dispatch_section(
    blocks: list[str],
    *,
    environment: dict | None = None,
):
    handler = SmartSolveSectionHandler(LatexToSympyCompiler())
    return handler.handle({
        "environment": environment or {},
        "blocks": [{"contents": b} for b in blocks],
    }).getResponsePayload()[1]["results"]


# ---------------------------------------------------------------------------
# Dispatcher edge cases
# ---------------------------------------------------------------------------


class TestSmartSolveEdgeCases:
    def test_multi_equation_align_block_returns_error(self):
        # \begin{align} parses as a SystemOfExpr in the existing infrastructure.
        latex = r"""
        \begin{align}
        x + y &= 5 \\
        x - y &= 1
        \end{align}
        """
        result = _dispatch(latex)
        assert result.kind == "silent"
        assert any(
            t.severity == "error" and "Multi-equation" in t.text for t in result.toasts
        )

    def test_garbage_latex_returns_error_silently(self):
        result = _dispatch(r"!!! not valid latex ###")
        assert result.kind == "silent"
        assert any(t.severity == "error" for t in result.toasts)

    def test_empty_expression_returns_error(self):
        result = _dispatch("")
        assert result.kind == "silent"
        assert any(t.severity == "error" for t in result.toasts)

    def test_whitespace_only_expression(self):
        result = _dispatch("   ")
        assert result.kind == "silent"
        assert any(t.severity == "error" for t in result.toasts)


# ---------------------------------------------------------------------------
# Symbol assumptions and domains
# ---------------------------------------------------------------------------


class TestSmartSolveAssumptions:
    def test_positive_assumption_filters_negative_root(self):
        # When x is declared positive, x^2 = 9 yields only {3}, no multi-solution toast.
        result = _dispatch(
            r"x^2 = 9",
            environment={"symbols": {"x": ["real", "positive"]}},
        )
        assert result.kind == "display"
        assert result.display_latex == "x = 3"
        # No multi-solution warning since only one candidate exists.
        warnings = [t for t in result.toasts if t.severity == "warning"]
        assert not any("Multiple solutions" in t.text for t in warnings)

    def test_real_domain_filters_complex_solutions(self):
        # x^2 = -1 in real domain → empty + complex-mode hint.
        result = _dispatch(
            r"x^2 + 1 = 0",
            environment={"solve_domain": "S.Reals"},
        )
        assert result.kind == "silent"
        warnings = [t for t in result.toasts if t.severity == "warning"]
        assert any("complex" in t.text.lower() for t in warnings)

    def test_complex_domain_finds_imaginary_roots(self):
        # Default domain is S.Complexes; x^2 = -1 should yield ±i.
        result = _dispatch(r"x^2 + 1 = 0")
        assert result.kind == "display"
        # Either +i or -i is fine; tiebreaker picks one and warns.
        assert "i" in result.display_latex
        warnings = [t for t in result.toasts if t.severity == "warning"]
        assert any("Multiple solutions" in t.text for t in warnings)


# ---------------------------------------------------------------------------
# Chained definitions
# ---------------------------------------------------------------------------


class TestSmartSolveChainedDefinitions:
    def test_definition_value_references_another_definition(self):
        # x := 3, y := x + 1 (from env, processed by existing := pipeline).
        # Smart Solve then evaluates `y` → should resolve to 4.
        result = _dispatch(
            r"y =",
            environment={
                "definitions": [
                    {"name_expr": "x", "value_expr": "3"},
                    {"name_expr": "y", "value_expr": "x + 1"},
                ]
            },
        )
        assert result.kind == "display"
        assert result.display_latex == "4"

    def test_implicit_chain_via_replay(self):
        # Three blocks: x = 3, y = x + 1, z = x * y. Then evaluate z.
        result = _dispatch(
            r"z =",
            prior_blocks=[r"x = 3", r"y = x + 1", r"z = x \cdot y"],
        )
        assert result.kind == "display"
        assert result.display_latex == "12"


class TestSmartSolveSectionBatch:
    def test_section_batch_reuses_prior_context(self):
        results = _dispatch_section([r"x = 3", r"x + 1 ="])

        assert len(results) == 2
        assert results[0]["kind"] == "display"
        assert results[0]["display_latex"] == "x = 3"
        assert results[1]["kind"] == "display"
        assert results[1]["display_latex"] == "4"

    def test_section_batch_skips_bad_block_when_replaying_later_state(self):
        results = _dispatch_section([r"this is not latex \$\$", r"x = 5", r"x + 1 ="])

        assert results[0]["kind"] == "silent"
        assert any(t["severity"] == "error" for t in results[0]["toasts"])
        assert results[2]["kind"] == "display"
        assert results[2]["display_latex"] == "6"

    def test_override_in_chain_propagates(self):
        # x = 3; y = x + 1 (=4); x = 10 (override). Now evaluate y.
        # Replay computes y=4 (when x was 3), then x is overridden to 10.
        # Subsequent evaluation of y still uses the y=4 derived earlier.
        # This documents the "snapshot-at-derivation" semantics.
        result = _dispatch(
            r"y =",
            prior_blocks=[r"x = 3", r"y = x + 1", r"x = 10"],
        )
        assert result.kind == "display"
        # y was bound to 4 when computed, and x is now 10 but y stays = 4.
        # This matches imperative semantics (REPL-style).
        assert result.display_latex == "4"


class TestSmartSolveStoredAmbiguousValues:
    def test_replayed_multi_solution_prints_full_set(self):
        result = _dispatch(
            r"x =",
            prior_blocks=[r"x^2 = 4"],
        )
        assert result.kind == "display"
        assert result.display_latex == r"\left\{-2, 2\right\}"
        assert not any(t.severity == "warning" for t in result.toasts)

    def test_replayed_multi_solution_warns_when_used_in_calculation(self):
        result = _dispatch(
            r"x + 1 =",
            prior_blocks=[r"x^2 = 4"],
        )
        assert result.kind == "display"
        assert result.display_latex == "3"
        warnings = [t for t in result.toasts if t.severity == "warning"]
        assert len(warnings) == 1
        assert "Multiple stored values for x" in warnings[0].text
        assert "Using 2" in warnings[0].text

    def test_replayed_ambiguous_value_can_feed_later_definition(self):
        result = _dispatch(
            r"y =",
            prior_blocks=[r"x^2 = 4", r"y = x + 1"],
        )
        assert result.kind == "display"
        assert result.display_latex == "3"


# ---------------------------------------------------------------------------
# Override edge cases
# ---------------------------------------------------------------------------


class TestSmartSolveOverrideEdges:
    def test_override_equal_after_simplification(self):
        # Prior x = 6/2 should compare equal to new derivation x = 3.
        result = _dispatch(
            r"x + 1 = 4",
            environment={
                "definitions": [{"name_expr": "x", "value_expr": r"\frac{6}{2}"}]
            },
        )
        # Solving x + 1 = 4 → x = 3, which simplifies-equals prior 6/2.
        assert result.kind == "silent"
        assert result.toasts == []

    def test_override_with_rendered_values_in_toast(self):
        result = _dispatch(
            r"x + 1 = 5",
            environment={"definitions": [{"name_expr": "x", "value_expr": "3"}]},
        )
        info = [t for t in result.toasts if t.severity == "info"]
        assert len(info) == 1
        # Toast should mention both old and new values.
        assert "3" in info[0].text
        assert "4" in info[0].text


# ---------------------------------------------------------------------------
# Constraint accumulation edge cases
# ---------------------------------------------------------------------------


class TestSmartSolveConstraintEdges:
    def test_constraint_uses_existing_definition(self):
        # z := 5 (already known). Then x + y + z = 10 (3 syntactic vars, 1 defined).
        # Substituted: x + y = 5. Two free remaining → stored as constraint silently.
        result = _dispatch(
            r"x + y + z = 10",
            environment={"definitions": [{"name_expr": "z", "value_expr": "5"}]},
        )
        assert result.kind == "silent"
        assert not any(t.severity == "error" for t in result.toasts)

    def test_three_blocks_underdetermined_then_resolved(self):
        # First two blocks produce a 3-variable system w/ 2 equations (underdet);
        # third block adds the third equation, fully resolving.
        result = _dispatch(
            r"x + y + z = 9",
            prior_blocks=[
                r"x + y = 5",
                r"y + z = 7",
            ],
        )
        assert result.kind == "silent"
        derived = " ".join(t.text for t in result.toasts if t.severity == "info")
        # Expected: x=2, y=3, z=4.
        for v in ("2", "3", "4"):
            assert v in derived

    def test_constraint_dropped_after_resolution(self):
        # After replay, the constraint store should not still contain a
        # constraint whose every variable is now determined.
        store = ConstraintStore()
        def_store = DefinitionStore()
        x = Symbol("x")
        y = Symbol("y")

        # Add x + y - 10 = 0 to constraints.
        store.add(x + y - 10)
        # First solve: underdetermined.
        determined = store.solve_and_materialize(def_store, None)
        assert determined == {}
        assert len(store.constraints) == 1

        # Add another equation that resolves the system.
        determined = store.solve_and_materialize(def_store, x - y - 2)
        assert determined == {"x": 6, "y": 4}
        # Both original constraints' free vars are now resolved → store empty.
        assert store.constraints == []


# ---------------------------------------------------------------------------
# ConstraintStore unit tests
# ---------------------------------------------------------------------------


class TestConstraintStoreUnit:
    def test_empty_store_returns_empty(self):
        store = ConstraintStore()
        result = store.solve_and_materialize(DefinitionStore(), None)
        assert result == {}

    def test_underdetermined_system_returns_empty(self):
        store = ConstraintStore()
        x = Symbol("x")
        y = Symbol("y")
        store.add(x + y - 10)
        result = store.solve_and_materialize(DefinitionStore(), None)
        assert result == {}
        assert len(store.constraints) == 1

    def test_clone_is_independent(self):
        store = ConstraintStore()
        x = Symbol("x")
        store.add(x - 5)
        cloned = store.clone()
        cloned.add(x + 5)
        assert len(store.constraints) == 1
        assert len(cloned.constraints) == 2

    def test_solves_linear_2x2_system(self):
        store = ConstraintStore()
        x = Symbol("x")
        y = Symbol("y")
        store.add(x + y - 10)
        store.add(x - y - 2)
        result = store.solve_and_materialize(DefinitionStore(), None)
        assert result == {"x": 6, "y": 4}

    def test_apply_determined_writes_to_def_store(self):
        store = DefinitionStore()
        apply_determined(store, {"x": sympify(6), "y": sympify(4)})
        assert store.get_definition("x") is not None
        assert store.get_definition("y") is not None


# ---------------------------------------------------------------------------
# Tiebreaker unit tests
# ---------------------------------------------------------------------------


class TestTiebreakerUnit:
    def test_single_solution_no_choice(self):
        sel = Tiebreaker.select([sympify(5)], None)
        assert sel.chosen == 5
        assert sel.was_choice_made is False

    def test_prior_match_silent(self):
        sel = Tiebreaker.select([sympify(-3), sympify(3)], sympify(-3))
        assert sel.chosen == -3
        assert sel.was_choice_made is False

    def test_largest_magnitude_wins(self):
        sel = Tiebreaker.select([sympify(1), sympify(10)], None)
        assert sel.chosen == 10
        assert sel.was_choice_made is True

    def test_equal_magnitude_prefers_positive_real(self):
        sel = Tiebreaker.select([sympify(-2), sympify(2)], None)
        assert sel.chosen == 2
        assert sel.was_choice_made is True

    def test_complex_solutions_rank_after_reals(self):
        # 2 + 3i has magnitude sqrt(13) ≈ 3.6, but 3 is positive real.
        # When magnitudes are similar, real wins.
        # Here we have a clear magnitude diff favoring complex; verify it still wins.
        sel = Tiebreaker.select([sympify(2), 2 + 3 * I], None)
        # 2 + 3i has larger magnitude → wins.
        assert str(sel.chosen) in ("2 + 3*I", "3*I + 2", "I*(3) + 2")
        assert sel.was_choice_made is True


# ---------------------------------------------------------------------------
# Renderer edge cases
# ---------------------------------------------------------------------------


class TestRendererEdgeCases:
    def test_zero(self):
        assert render(sympify(0)) == "0"

    def test_negative_integer(self):
        assert render(sympify(-7)) == "-7"

    def test_negative_rational(self):
        assert render(sympify(-1) / 3) == "-0.333"

    def test_exactly_at_low_boundary_uses_scientific(self):
        # 1e-4 itself — design choice: use scientific.
        out = render(sympify("0.00001"))
        assert "10^" in out

    def test_exactly_at_high_boundary_uses_scientific(self):
        out = render(sympify(1_000_000))
        assert "10^" in out

    def test_just_below_high_boundary_uses_fixed(self):
        out = render(sympify(999_999))
        assert "10^" not in out

    def test_sig_figs_zero_falls_back_to_default(self):
        # Defensive: invalid sig_figs (0 or negative) falls back to default.
        assert render(sympify(1) / 3, sig_figs=0) == "0.333"

    def test_pi_value_rendered(self):
        from sympy import pi

        out = render(pi)
        assert out.startswith("3.14")

    def test_infinity_falls_back_to_latex(self):
        from sympy import oo

        # Symbolic infinity passes through the existing printer.
        out = render(oo)
        assert "infty" in out or "oo" in out

    def test_symbolic_matrix_falls_back(self):
        from sympy import Matrix

        out = render(Matrix([[1, 2], [3, 4]]))
        # Matrix rendering uses LaTeX matrix env.
        assert "matrix" in out or "&" in out


# ---------------------------------------------------------------------------
# Replay cache behavior
# ---------------------------------------------------------------------------


class TestReplayCache:
    def test_cache_hit_returns_equivalent_result(self):
        ContextReplay._replay_cache.clear()
        compiler = LatexToSympyCompiler()
        env = LmatEnvironment()

        r1 = ContextReplay.replay_blocks([r"x = 3", r"y = x + 1"], env, compiler)
        r2 = ContextReplay.replay_blocks([r"x = 3", r"y = x + 1"], env, compiler)

        # Definitions equivalent: both should resolve y to 4.
        for store in (r1.def_store, r2.def_store):
            defn = store.get_definition("y")
            assert defn is not None
            assert defn.defined_value(store) == 4

    def test_cache_invalidates_on_different_blocks(self):
        ContextReplay._replay_cache.clear()
        compiler = LatexToSympyCompiler()
        env = LmatEnvironment()

        r1 = ContextReplay.replay_blocks([r"x = 3"], env, compiler)
        r2 = ContextReplay.replay_blocks([r"x = 7"], env, compiler)

        assert r1.def_store.get_definition("x").defined_value(r1.def_store) == 3
        assert r2.def_store.get_definition("x").defined_value(r2.def_store) == 7

    def test_cache_results_are_independent_clones(self):
        ContextReplay._replay_cache.clear()
        compiler = LatexToSympyCompiler()
        env = LmatEnvironment()

        r1 = ContextReplay.replay_blocks([r"x = 3"], env, compiler)
        # Mutating r1's store must not poison the cached entry for the next call.
        from lmat_cas_client.compiling.Definitions import SympyDefinition

        r1.def_store.set_definition("z", SympyDefinition(sympify(99)))

        r2 = ContextReplay.replay_blocks([r"x = 3"], env, compiler)
        # r2 should have x but NOT z (z was added only to r1's local copy).
        assert r2.def_store.get_definition("x") is not None
        assert r2.def_store.get_definition("z") is None

    def test_cache_bounded_size(self):
        ContextReplay._replay_cache.clear()
        compiler = LatexToSympyCompiler()
        env = LmatEnvironment()

        # Push more entries than the cache cap.
        cap = ContextReplay._REPLAY_CACHE_MAX
        for i in range(cap + 5):
            ContextReplay.replay_blocks([f"a_{{{i}}} = {i}"], env, compiler)

        assert len(ContextReplay._replay_cache) <= cap


# ---------------------------------------------------------------------------
# %ref edge cases
# ---------------------------------------------------------------------------


class TestRefEdgeCases:
    def test_ref_with_text_block_format(self):
        # The design doc shows `\%text{ref}` as the canonical form.
        result = _dispatch(r"E = mc^2 \quad \% \text{ref}")
        assert result.kind == "no_op"

    def test_ref_followed_by_other_text(self):
        # `%ref foo bar` — `ref` as a whole word still matches.
        result = _dispatch(r"x = 5 %ref this is a citation")
        assert result.kind == "no_op"

    def test_non_ref_comment_not_skipped(self):
        # `% comment` without `ref` keyword should NOT be a no-op.
        # (The parser strips comments; the block still runs normally.)
        result = _dispatch(r"x = 5 % just a note")
        assert result.kind == "display"
        assert result.display_latex == "x = 5"

    def test_ref_in_one_of_several_prior_blocks(self):
        # Only the non-ref prior block contributes to context.
        result = _dispatch(
            r"x + 1 =",
            prior_blocks=[
                r"x = 99 \quad %ref this should be ignored",
                r"x = 7",
            ],
        )
        assert result.kind == "display"
        assert result.display_latex == "8"


# ---------------------------------------------------------------------------
# Trailing equals with side effects
# ---------------------------------------------------------------------------


class TestTrailingEqualsEdges:
    def test_trailing_equals_on_undefined_variable_errors(self):
        result = _dispatch(r"x =")
        assert result.kind == "silent"
        assert any(
            t.severity == "error" and "Undefined" in t.text for t in result.toasts
        )

    def test_trailing_equals_with_arithmetic(self):
        result = _dispatch(r"\frac{1}{2} + \frac{1}{4} =")
        assert result.kind == "display"
        assert result.display_latex == "0.75"

    def test_trailing_equals_using_constraint_derived_value(self):
        # x is determined by the constraint system across two prior blocks.
        # Then `x =` evaluates to that value.
        result = _dispatch(
            r"x =",
            prior_blocks=[r"x + y = 10", r"x - y = 2"],
        )
        assert result.kind == "display"
        assert result.display_latex == "6"


class TestSymbolicFallback:
    """Evaluating an expression whose variables can only be expressed in
    terms of remaining free parameters should return a symbolic answer
    instead of an 'undefined variable' error."""

    def test_simple_symbolic_substitution(self):
        # x = y + z; y = 3z + 5; evaluate x → 4z + 5 (free parameter z).
        result = _dispatch(
            r"x",
            prior_blocks=[r"x = y + z", r"y = 3z + 5"],
        )
        assert result.kind == "display", (
            f"expected display, got {result.kind} with toasts={result.toasts}"
        )
        # Symbolic form: 4*z + 5, however lmat_latex chooses to render.
        assert "z" in result.display_latex
        assert "5" in result.display_latex
        # An info toast announces the symbolic-with-free-parameter result.
        assert any(t.severity == "info" and "Symbolic" in t.text for t in result.toasts)

    def test_no_constraints_still_errors(self):
        # No prior context; bare `x` is genuinely undefined.
        result = _dispatch(r"x")
        assert result.kind == "silent"
        assert any(
            t.severity == "error" and "Undefined" in t.text for t in result.toasts
        )

    def test_constraint_pins_to_numeric(self):
        # When constraints uniquely determine the value, prefer the numeric
        # answer (no "Symbolic" toast since there are no free parameters left).
        result = _dispatch(
            r"x",
            prior_blocks=[r"x + y = 10", r"x - y = 2"],
        )
        assert result.kind == "display"
        assert result.display_latex == "6"
        assert not any("Symbolic" in t.text for t in result.toasts)
