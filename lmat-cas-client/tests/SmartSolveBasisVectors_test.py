"""
Basis-vector notation (design_docs.md §"Design Requirements for Basis-Vector
Notation").

Covers parser input forms, the required vector-math surface, Smart Solve
provenance round-tripping, the spec's acceptance examples, and the
basis-style output rules.
"""

from lmat_cas_client.command_handlers.SmartSolveHandler import (
    SmartSolveHandler,
    SmartSolveSectionHandler,
)
from lmat_cas_client.compiling.Compiler import LatexToSympyCompiler
from lmat_cas_client.LmatEnvironment import LmatEnvironment
from lmat_cas_client.smart_solve import ContextReplay
from lmat_cas_client.smart_solve.Provenance import ALIAS, HAT, MATRIX, compute_family
from lmat_cas_client.smart_solve.Renderer import render
from sympy import ImmutableDenseMatrix as Vec
from sympy import Rational, Symbol, symbols

_COMPILER = LatexToSympyCompiler()


def _compile(latex, environment=None):
    env = LmatEnvironment.model_validate(environment or {})
    return _COMPILER.compile(latex, LmatEnvironment.create_definition_store(env))


def _dispatch(expression, *, environment=None, prior_blocks=None):
    handler = SmartSolveHandler(LatexToSympyCompiler())
    return handler.handle({
        "expression": expression,
        "environment": environment or {},
        "prior_blocks": [{"contents": b} for b in (prior_blocks or [])],
    })._result


def _section(blocks, *, environment=None):
    handler = SmartSolveSectionHandler(LatexToSympyCompiler())
    return handler.handle({
        "environment": environment or {},
        "blocks": [{"contents": b} for b in blocks],
    }).getResponsePayload()[1]["results"]


def _last_display(blocks, **kw):
    return _section(blocks, **kw)[-1].get("display_latex")


# ---------------------------------------------------------------------------
# Parser input forms
# ---------------------------------------------------------------------------


class TestBasisInputForms:
    def test_alias_forms(self):
        assert _compile(r"\ihat") == Vec([1, 0, 0])
        assert _compile(r"\jhat") == Vec([0, 1, 0])
        assert _compile(r"\khat") == Vec([0, 0, 1])

    def test_literal_hat_forms(self):
        assert _compile(r"\hat{i}") == Vec([1, 0, 0])
        assert _compile(r"\hat{j}") == Vec([0, 1, 0])
        assert _compile(r"\hat{k}") == Vec([0, 0, 1])

    def test_dotless_hat_forms(self):
        # \imath / \jmath denote the same basis vectors as i / j.
        assert _compile(r"\hat{\imath}") == Vec([1, 0, 0])
        assert _compile(r"\hat{\jmath}") == Vec([0, 1, 0])

    def test_hat_tolerates_whitespace(self):
        assert _compile(r"\hat {i}") == Vec([1, 0, 0])
        assert _compile(r"\hat{ k }") == Vec([0, 0, 1])

    def test_linear_combination(self):
        assert _compile(r"2\ihat + 3\jhat - \khat") == Vec([2, 3, -1])


class TestBasisCompatibility:
    def test_hat_of_other_symbol_stays_a_symbol(self):
        # \hat{x} must remain an ordinary formatted symbol, not a basis vector.
        result = _compile(r"\hat{x}")
        assert isinstance(result, Symbol)
        assert not getattr(result, "is_Matrix", False)

    def test_bare_i_is_imaginary_unit(self):
        from sympy import I

        assert _compile(r"i") == I

    def test_vec_v_stays_a_symbol(self):
        assert isinstance(_compile(r"\vec{v}"), Symbol)


# ---------------------------------------------------------------------------
# Required vector-math surface (design_docs §"Required Math Surface")
# ---------------------------------------------------------------------------


class TestBasisMathSurface:
    def test_addition(self):
        assert _last_display([r"\ihat + \jhat ="]) == r"\ihat + \jhat"

    def test_subtraction(self):
        assert _last_display([r"a = 5\ihat", r"b = 2\ihat", r"a - b ="]) == r"3\ihat"

    def test_scalar_multiplication(self):
        assert _last_display([r"v = \ihat + \jhat", r"3 v ="]) == r"3\ihat + 3\jhat"

    def test_cross_product(self):
        assert _last_display([r"a = \ihat", r"b = \jhat", r"a \times b ="]) == r"\khat"

    def test_dot_product_is_scalar(self):
        assert _last_display([r"\langle \ihat + \jhat | \ihat \rangle ="]) == "1"

    def test_norm_is_scalar(self):
        assert _last_display([r"\Vert 3\ihat + 4\jhat \Vert ="]) == "5"

    def test_unit_vector_preserves_family(self):
        assert _last_display([r"\vu(3\ihat + 4\jhat) ="]) == r"0.6\ihat + 0.8\jhat"


# ---------------------------------------------------------------------------
# Acceptance examples (design_docs §"Acceptance Examples")
# ---------------------------------------------------------------------------


class TestBasisAcceptanceExamples:
    def test_alias_round_trip(self):
        out = _last_display([r"u = 2\ihat + 3\jhat - \khat", r"u ="])
        assert out == r"2\ihat + 3\jhat - \khat"

    def test_literal_hat_round_trip(self):
        out = _last_display([r"v = \hat{i} - 2\hat{k}", r"v ="])
        assert out == r"\hat{i} - 2\hat{k}"

    def test_matrix_round_trip(self):
        out = _last_display([r"w = \begin{bmatrix}1 \\ 2 \\ 3\end{bmatrix}", r"w ="])
        assert "matrix" in out and "ihat" not in out and "hat{" not in out

    def test_mixed_style_fallback(self):
        out = _last_display([
            r"u = \ihat",
            r"x = u + \begin{bmatrix}1 \\ 0 \\ 0\end{bmatrix}",
            r"x =",
        ])
        # Mixing a basis symbol with a matrix literal falls back to matrix.
        assert "matrix" in out and "ihat" not in out

    def test_vector_math_support(self):
        out = _last_display([r"a = \ihat", r"b = \jhat", r"a \times b ="])
        assert out == r"\khat"


# ---------------------------------------------------------------------------
# Provenance behavior
# ---------------------------------------------------------------------------


class TestBasisProvenance:
    def test_dotless_canonicalizes_within_hat_family(self):
        # \hat{\imath} round-trips to the canonical \hat{i} (family preserved).
        out = _last_display([r"v = \hat{\imath} + \hat{\jmath}", r"v ="])
        assert out == r"\hat{i} + \hat{j}"

    def test_override_keeps_new_family(self):
        out = _last_display([r"v = \ihat", r"v = 2\jhat", r"v ="])
        assert out == r"2\jhat"

    def test_redefining_matrix_as_basis_switches_family(self):
        # The defining block's notation wins; prior matrix family does not stick.
        out = _last_display([
            r"v = \begin{bmatrix}1\\0\\0\end{bmatrix}",
            r"v = \jhat",
            r"v =",
        ])
        assert out == r"\jhat"

    def test_derived_vector_inherits_family_consistently(self):
        # `w = 2v` inherits v's family, and the defining block and a later
        # recall must agree (regression: replay computed family from the
        # already-substituted value and disagreed with the live display).
        results = _section([r"v = \ihat + \jhat", r"w = 2 v", r"w ="])
        assert results[1]["display_latex"] == r"w = 2\ihat + 2\jhat"
        assert results[2]["display_latex"] == r"2\ihat + 2\jhat"

    def test_provenance_survives_replay_cache(self):
        ContextReplay._replay_cache.clear()
        prior = [r"u = 2\ihat + 3\jhat - \khat"]
        first = _dispatch(r"u =", prior_blocks=prior)
        second = _dispatch(r"u =", prior_blocks=prior)  # cache hit
        assert first.display_latex == r"2\ihat + 3\jhat - \khat"
        assert second.display_latex == first.display_latex

    def test_alias_and_hat_mix_falls_back_to_matrix(self):
        # Two basis families in one expression are ambiguous -> matrix.
        a, b = symbols("a b")
        store = LmatEnvironment.create_definition_store(
            LmatEnvironment.model_validate({})
        )
        assert compute_family(r"\ihat + \hat{j}", set(), store) == MATRIX
        assert compute_family(r"\ihat + \jhat", set(), store) == ALIAS
        assert compute_family(r"\hat{i} + \hat{j}", set(), store) == HAT
        assert (
            compute_family(r"\begin{bmatrix}1\\2\\3\end{bmatrix}", set(), store)
            == MATRIX
        )
        assert compute_family(r"x + y", {a, b}, store) is None


# ---------------------------------------------------------------------------
# Basis-style output rules (design_docs §"Basis-Style Output Rules")
# ---------------------------------------------------------------------------


class TestBasisRenderRules:
    def test_zero_vector_renders_as_zero(self):
        assert render(Vec([0, 0, 0]), 3, ALIAS) == "0"

    def test_zero_components_omitted(self):
        assert render(Vec([0, 5, 0]), 3, ALIAS) == r"5\jhat"

    def test_coefficient_one_omitted(self):
        assert render(Vec([1, 0, 0]), 3, ALIAS) == r"\ihat"

    def test_coefficient_negative_one(self):
        assert render(Vec([-1, 0, 0]), 3, ALIAS) == r"-\ihat"

    def test_ijk_order_and_signs(self):
        assert render(Vec([2, -3, 1]), 3, ALIAS) == r"2\ihat - 3\jhat + \khat"

    def test_fractional_coefficient_uses_scalar_renderer(self):
        assert render(Vec([Rational(1, 3), 0, 0]), 3, ALIAS) == r"0.333\ihat"

    def test_non_three_component_vector_falls_back_to_matrix(self):
        out = render(Vec([1, 2]), 3, ALIAS)
        assert "matrix" in out and "ihat" not in out

    def test_no_family_renders_as_matrix(self):
        out = render(Vec([1, 2, 3]), 3, None)
        assert "matrix" in out
