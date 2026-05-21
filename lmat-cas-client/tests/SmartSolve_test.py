from lmat_cas_client.command_handlers.SmartSolveHandler import SmartSolveHandler
from lmat_cas_client.compiling.Compiler import LatexToSympyCompiler


class TestSmartSolveBasic:
    """Step 1 — basic dispatch: solve, evaluate, verify, contradiction, error cases."""

    compiler = LatexToSympyCompiler()

    def _dispatch(self, expression: str, environment: dict | None = None):
        handler = SmartSolveHandler(self.compiler)
        return handler.handle({
            "expression": expression,
            "environment": environment or {},
        })._result

    # --- Fresh single-variable assignment ---------------------------------

    def test_fresh_assignment(self):
        result = self._dispatch(r"x = 3")
        assert result.kind == "display"
        assert result.display_latex == "x = 3"

    def test_solve_linear_single_variable(self):
        result = self._dispatch(r"x + 1 = 5")
        assert result.kind == "display"
        assert result.display_latex == "x = 4"

    # --- Trailing-equals evaluation ---------------------------------------

    def test_trailing_equals_evaluation(self):
        result = self._dispatch(r"1 + 1 =")
        assert result.kind == "display"
        assert result.display_latex == "2"

    def test_trailing_equals_with_definition(self):
        env = {"definitions": [{"name_expr": "x", "value_expr": "4"}]}
        result = self._dispatch(r"x =", environment=env)
        assert result.kind == "display"
        assert result.display_latex == "4"

    # --- Plain expression evaluation --------------------------------------

    def test_plain_expression_evaluation(self):
        result = self._dispatch(r"2 + 3")
        assert result.kind == "display"
        assert result.display_latex == "5"

    def test_expression_with_definition_substitution(self):
        env = {"definitions": [{"name_expr": "x", "value_expr": "10"}]}
        result = self._dispatch(r"x + 5", environment=env)
        assert result.kind == "display"
        assert result.display_latex == "15"

    # --- Multi-variable with one undefined (Step 4c, partial) ------------

    def test_two_variables_one_defined(self):
        env = {"definitions": [{"name_expr": "y", "value_expr": "5"}]}
        result = self._dispatch(r"x + y = 10", environment=env)
        assert result.kind == "display"
        assert result.display_latex == "x = 5"

    # --- Verification & contradiction -------------------------------------

    def test_verified_concrete_equality(self):
        result = self._dispatch(r"2 + 2 = 4")
        assert result.kind == "silent"
        assert result.display_latex is None
        # No toasts on silent verification.
        assert result.toasts == []

    def test_contradiction_when_no_free_vars(self):
        # x and y both defined; equation evaluates to a false statement.
        env = {
            "definitions": [
                {"name_expr": "x", "value_expr": "3"},
                {"name_expr": "y", "value_expr": "5"},
            ]
        }
        result = self._dispatch(r"x + y = 10", environment=env)
        assert result.kind == "silent"
        assert any(t.severity == "error" and "Contradiction" in t.text for t in result.toasts)

    # --- Error cases ------------------------------------------------------

    def test_two_unresolved_vars_stored_as_constraint(self):
        # After Step 6 this is no longer an error: it's stored silently for
        # later resolution.
        result = self._dispatch(r"x + y = 10")
        assert result.kind == "silent"
        assert not any(t.severity == "error" for t in result.toasts)

    def test_undefined_variable_in_expression_errors(self):
        result = self._dispatch(r"x + 5")
        assert result.kind == "silent"
        assert any(
            t.severity == "error" and "Undefined" in t.text for t in result.toasts
        )


class TestSmartSolveOverrideSemantics:
    """Step 2 — override semantics: latest line wins, contradiction only when
    no derivation is possible."""

    compiler = LatexToSympyCompiler()

    def _dispatch(self, expression: str, environment: dict | None = None):
        handler = SmartSolveHandler(self.compiler)
        return handler.handle({
            "expression": expression,
            "environment": environment or {},
        })._result

    def test_single_solution_matches_prior_is_silent(self):
        env = {"definitions": [{"name_expr": "x", "value_expr": "3"}]}
        # `x + 1 = 4` solves to x=3, matching prior.
        result = self._dispatch(r"x + 1 = 4", environment=env)
        assert result.kind == "silent"
        assert result.toasts == []

    def test_single_solution_differs_from_prior_emits_info_toast(self):
        env = {"definitions": [{"name_expr": "x", "value_expr": "3"}]}
        # `x + 1 = 5` solves to x=4, overrides prior.
        result = self._dispatch(r"x + 1 = 5", environment=env)
        assert result.kind == "display"
        assert result.display_latex == "x = 4"
        info_toasts = [t for t in result.toasts if t.severity == "info"]
        assert len(info_toasts) == 1
        assert "Overriding" in info_toasts[0].text
        assert "x" in info_toasts[0].text

    def test_fresh_assignment_no_toast(self):
        # No prior value → silent storage, no override toast.
        result = self._dispatch(r"x + 1 = 5")
        assert result.kind == "display"
        assert result.display_latex == "x = 4"
        info_toasts = [t for t in result.toasts if t.severity == "info"]
        assert info_toasts == []

    def test_direct_assignment_override(self):
        # `x = 4` with prior `x = 3` → derivation target is x (1 syntactic var),
        # solves to 4, overrides.
        env = {"definitions": [{"name_expr": "x", "value_expr": "3"}]}
        result = self._dispatch(r"x = 4", environment=env)
        assert result.kind == "display"
        assert result.display_latex == "x = 4"
        info_toasts = [t for t in result.toasts if t.severity == "info"]
        assert len(info_toasts) == 1

    def test_direct_assignment_same_value_silent(self):
        env = {"definitions": [{"name_expr": "x", "value_expr": "3"}]}
        result = self._dispatch(r"x = 3", environment=env)
        assert result.kind == "silent"
        assert result.toasts == []

    def test_contradiction_only_when_no_free_vars(self):
        # All variables defined → contradiction, no derivation possible.
        env = {
            "definitions": [
                {"name_expr": "x", "value_expr": "3"},
                {"name_expr": "y", "value_expr": "5"},
            ]
        }
        result = self._dispatch(r"x + y = 10", environment=env)
        assert result.kind == "silent"
        error_toasts = [t for t in result.toasts if t.severity == "error"]
        assert any("Contradiction" in t.text for t in error_toasts)

    def test_no_contradiction_when_var_available_for_redefinition(self):
        # Only y defined. x is a derivable target → no contradiction, x = 5.
        env = {"definitions": [{"name_expr": "y", "value_expr": "5"}]}
        result = self._dispatch(r"x + y = 10", environment=env)
        assert result.kind == "display"
        assert result.display_latex == "x = 5"
        assert not any("Contradiction" in t.text for t in result.toasts)

    def test_verified_when_lhs_equals_rhs_no_free_vars(self):
        env = {"definitions": [{"name_expr": "x", "value_expr": "3"}]}
        # x + 1 = 4 → after subst: 4 = 4. Verified, silent.
        # But syntactic_vars = {x}, len=1, so case 4b → solve, get x=3, prior=3, silent.
        # Try a case with no syntactic vars: 2 + 2 = 4.
        result = self._dispatch(r"2 + 2 = 4", environment=env)
        assert result.kind == "silent"
        assert result.toasts == []


class TestSmartSolveTiebreaker:
    """Step 3 — multi-solution tiebreaker."""

    compiler = LatexToSympyCompiler()

    def _dispatch(self, expression: str, environment: dict | None = None):
        handler = SmartSolveHandler(self.compiler)
        return handler.handle({
            "expression": expression,
            "environment": environment or {},
        })._result

    def test_quadratic_no_prior_picks_positive(self):
        # x^2 = 4 → {-2, 2}. Equal magnitudes; positive real wins.
        result = self._dispatch(r"x^2 = 4")
        assert result.kind == "display"
        assert result.display_latex == "x = 2"
        warnings = [t for t in result.toasts if t.severity == "warning"]
        assert len(warnings) == 1
        assert "Multiple solutions" in warnings[0].text

    def test_quadratic_prior_matches_negative_silent(self):
        env = {"definitions": [{"name_expr": "x", "value_expr": "-3"}]}
        # x^2 = 9 → {-3, 3}. Prior matches -3 → silent, no override.
        result = self._dispatch(r"x^2 = 9", environment=env)
        assert result.kind == "silent"
        assert result.toasts == []

    def test_quadratic_prior_does_not_match_picks_positive(self):
        env = {"definitions": [{"name_expr": "x", "value_expr": "7"}]}
        # x^2 = 9 → {-3, 3}. Prior 7 doesn't match; pick positive → 3.
        result = self._dispatch(r"x^2 = 9", environment=env)
        assert result.kind == "display"
        assert result.display_latex == "x = 3"
        # Both override-info AND multi-solution-warning toasts expected.
        severities = {t.severity for t in result.toasts}
        assert "info" in severities
        assert "warning" in severities

    def test_largest_magnitude_wins_when_unequal(self):
        # (x-1)(x-10) = 0 → {1, 10}. 10 has larger magnitude → wins.
        result = self._dispatch(r"x^2 - 11x + 10 = 0")
        assert result.kind == "display"
        assert result.display_latex == "x = 10"


class TestSmartSolveContextReplay:
    """Step 4 — section scoping & context replay (Python side).

    The TS side decides what's "in the section"; here we verify that when
    prior_blocks are handed to the Python handler, the implicit context is
    rebuilt and used for the current block.
    """

    compiler = LatexToSympyCompiler()

    def _dispatch(self, expression: str, prior_blocks: list[str] | None = None,
                  environment: dict | None = None):
        handler = SmartSolveHandler(self.compiler)
        return handler.handle({
            "expression": expression,
            "environment": environment or {},
            "prior_blocks": [{"contents": b} for b in (prior_blocks or [])],
        })._result

    def test_implicit_equals_defines_for_next_block(self):
        # Block 1: x = 3   (implicit definition)
        # Block 2: x + 1 = (trailing) → evaluates to 4.
        result = self._dispatch(r"x + 1 =", prior_blocks=[r"x = 3"])
        assert result.kind == "display"
        assert result.display_latex == "4"

    def test_chain_of_implicit_definitions(self):
        # x = 3; y = x + 1; z = x + y → should derive z = 7.
        result = self._dispatch(r"z = x + y", prior_blocks=[
            r"x = 3",
            r"y = x + 1",
        ])
        assert result.kind == "display"
        assert result.display_latex == "z = 7"

    def test_override_in_prior_blocks(self):
        # x = 3; x + 1 = 5 → overrides x to 4; eval x → 4
        result = self._dispatch(r"x =", prior_blocks=[
            r"x = 3",
            r"x + 1 = 5",
        ])
        assert result.kind == "display"
        assert result.display_latex == "4"

    def test_bad_prior_block_does_not_break_replay(self):
        # Garbage prior block is silently skipped; subsequent ones still apply.
        result = self._dispatch(r"x + 1 =", prior_blocks=[
            r"this is not latex \$\$",
            r"x = 5",
        ])
        assert result.kind == "display"
        assert result.display_latex == "6"


class TestSmartSolveRef:
    """Step 5 — %ref blocks are no-ops."""

    compiler = LatexToSympyCompiler()

    def _dispatch(self, expression: str, prior_blocks: list[str] | None = None):
        handler = SmartSolveHandler(self.compiler)
        return handler.handle({
            "expression": expression,
            "environment": {},
            "prior_blocks": [{"contents": b} for b in (prior_blocks or [])],
        })._result

    def test_ref_block_returns_no_op(self):
        result = self._dispatch(r"E = mc^2 \quad %\text{ref}")
        assert result.kind == "no_op"
        assert result.toasts == []

    def test_short_ref_marker_returns_no_op(self):
        result = self._dispatch(r"E = mc^2 % ref")
        assert result.kind == "no_op"

    def test_constraints_become_derivations_when_enough_info(self):
        # Block 1: x + y = 10 (constraint, ≥2 unknowns)
        # Block 2: y = 4 (defines y)
        # Current: x = (trailing equals, evaluates x)
        # After replay: x + y = 10 + y = 4 → x = 6
        handler = SmartSolveHandler(self.compiler)
        result = handler.handle({
            "expression": r"x =",
            "environment": {},
            "prior_blocks": [
                {"contents": r"x + y = 10"},
                {"contents": r"y = 4"},
            ],
        })._result
        assert result.kind == "display"
        assert result.display_latex == "6"

    def test_ref_in_prior_block_is_skipped_during_replay(self):
        # Prior %ref block defines `x = 99` but should be ignored.
        # The actual definition `x = 3` is what applies.
        result = self._dispatch(
            r"x + 1 =",
            prior_blocks=[
                r"x = 99 \quad %ref",
                r"x = 3",
            ],
        )
        assert result.kind == "display"
        assert result.display_latex == "4"


class TestSmartSolveRenderer:
    """Step 7 — significant-figures rendering."""

    from lmat_cas_client.smart_solve.Renderer import DEFAULT_SIG_FIGS, render

    def test_integer_unchanged(self):
        from sympy import Integer
        from lmat_cas_client.smart_solve.Renderer import render
        assert render(Integer(5)) == "5"

    def test_rational_one_third_rounded(self):
        from sympy import Rational
        from lmat_cas_client.smart_solve.Renderer import render
        assert render(Rational(1, 3)) == "0.333"

    def test_irrational_sqrt_2_rounded(self):
        from sympy import sqrt
        from lmat_cas_client.smart_solve.Renderer import render
        assert render(sqrt(2)) == "1.41"

    def test_small_value_uses_scientific(self):
        from sympy import Rational
        from lmat_cas_client.smart_solve.Renderer import render
        # 1e-7 → scientific notation
        out = render(Rational(1, 10_000_000))
        assert "10^" in out

    def test_large_value_uses_scientific(self):
        from sympy import Integer
        from lmat_cas_client.smart_solve.Renderer import render
        out = render(Integer(123_456_789))
        assert "10^" in out

    def test_sig_figs_override(self):
        from sympy import Rational
        from lmat_cas_client.smart_solve.Renderer import render
        assert render(Rational(1, 3), sig_figs=5) == "0.33333"

    def test_symbolic_falls_back_to_latex_printer(self):
        from sympy import Symbol
        from lmat_cas_client.smart_solve.Renderer import render
        # Symbolic results pass through the existing LaTeX printer (whatever it returns).
        x = Symbol("x")
        out = render(x + 1)
        assert "x" in out


class TestSmartSolveLmatOverrides:
    """Step 9 — per-document overrides via lmat block (sig_figs, domain)."""

    compiler = LatexToSympyCompiler()

    def _dispatch(self, expression: str, environment: dict | None = None):
        handler = SmartSolveHandler(self.compiler)
        return handler.handle({
            "expression": expression,
            "environment": environment or {},
        })._result

    def test_sig_figs_override_in_environment(self):
        result = self._dispatch(
            r"1 / 3",
            environment={"render_sig_figs": 5},
        )
        assert result.kind == "display"
        assert result.display_latex == "0.33333"

    def test_default_sig_figs_is_three(self):
        result = self._dispatch(r"1 / 3")
        assert result.kind == "display"
        assert result.display_latex == "0.333"

    def test_no_real_solution_hints_complex_when_real_domain(self):
        # x^2 = -1 has no real solution; with default complex domain it does.
        # With real domain explicitly, we should hint at complex mode.
        result = self._dispatch(
            r"x^2 = -1",
            environment={"solve_domain": "S.Reals"},
        )
        # Either error + warning about complex mode, or success with a real-domain hint.
        assert result.kind == "silent"
        warnings = [t for t in result.toasts if t.severity == "warning"]
        assert any("complex" in t.text.lower() for t in warnings)


class TestSmartSolveConstraintAccumulation:
    """Step 6 — multi-variable constraints accumulate until the system is solvable."""

    compiler = LatexToSympyCompiler()

    def _dispatch(self, expression: str, prior_blocks: list[str] | None = None):
        handler = SmartSolveHandler(self.compiler)
        return handler.handle({
            "expression": expression,
            "environment": {},
            "prior_blocks": [{"contents": b} for b in (prior_blocks or [])],
        })._result

    def test_first_two_var_block_is_silent_constraint(self):
        # Single ≥2-var block with no prior info → stored silently, no error.
        result = self._dispatch(r"x + y = 10")
        assert result.kind == "silent"
        # No error toast — this is just stored, not flagged.
        assert not any(t.severity == "error" for t in result.toasts)

    def test_pair_of_two_var_blocks_resolves_system(self):
        # x + y = 10; x - y = 2 → solve → x=6, y=4. Current block triggers
        # the resolution; we emit info toasts for derivations.
        result = self._dispatch(r"x - y = 2", prior_blocks=[r"x + y = 10"])
        assert result.kind == "silent"
        info_toasts = [t for t in result.toasts if t.severity == "info"]
        derived = {t.text for t in info_toasts}
        assert any("x" in d and "6" in d for d in derived)
        assert any("y" in d and "4" in d for d in derived)

    def test_uses_constraint_solved_value_in_next_block(self):
        # After solving x=6, y=4 (from first two blocks), the third block
        # can use x and y as definitions.
        result = self._dispatch(
            r"x + y =",
            prior_blocks=[r"x + y = 10", r"x - y = 2"],
        )
        assert result.kind == "display"
        assert result.display_latex == "10"

    def test_three_equations_three_unknowns(self):
        # Classic 3x3 linear system.
        result = self._dispatch(
            r"x + y + z = 9",
            prior_blocks=[
                r"x + y = 5",
                r"y + z = 7",
            ],
        )
        # After all three: x + y = 5, y + z = 7, x + y + z = 9 → z=4, y=3, x=2.
        assert result.kind == "silent"
        derived_text = " ".join(t.text for t in result.toasts if t.severity == "info")
        assert "2" in derived_text and "3" in derived_text and "4" in derived_text
