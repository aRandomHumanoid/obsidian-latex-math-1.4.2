"""
Smart Solve vector / matrix support.

These tests exercise the *real* evaluation pipeline (compile -> evaluate ->
render), so the values flowing through are the compiler's `LatexMatrix`
instances rather than plain sympy matrices. That distinction matters: the
render-recursion bug and the scalar-`subs` breakage both only reproduced with
`LatexMatrix`, not with a plain `Matrix`, so the previously-existing matrix test
(which rendered a plain `Matrix`) did not catch them.

Covered:
  - render no longer recurses on an evaluated matrix result
  - literal vector arithmetic (sum, cross product, inner product) displays
  - defining a vector with `=` and `:=`, then using it (scale, sum, cross, dot,
    norm) with correct type-dispatched operators
  - overriding a vector value
  - verifying vector equality (silent) and contradictions (error toast)
  - matrix equations that can't be solved produce a clear error, not a crash
  - delimiter style is preserved on a direct assignment
  - scalar dispatch is unaffected when a vector lives in the same section
"""

from lmat_cas_client.command_handlers.SmartSolveHandler import (
    SmartSolveHandler,
    SmartSolveSectionHandler,
)
from lmat_cas_client.compiling.Compiler import LatexToSympyCompiler
from lmat_cas_client.LmatEnvironment import LmatEnvironment
from lmat_cas_client.smart_solve.Dispatcher import _evaluate_expression
from lmat_cas_client.smart_solve.Renderer import render


def _dispatch(expression, *, environment=None, prior_blocks=None):
    handler = SmartSolveHandler(LatexToSympyCompiler())
    return handler.handle({
        "expression": expression,
        "environment": environment or {},
        "prior_blocks": [{"contents": b} for b in (prior_blocks or [])],
    })._result


def _dispatch_section(blocks, *, environment=None):
    handler = SmartSolveSectionHandler(LatexToSympyCompiler())
    return handler.handle({
        "environment": environment or {},
        "blocks": [{"contents": b} for b in blocks],
    }).getResponsePayload()[1]["results"]


def _errors(result_dict):
    return [t["text"] for t in result_dict["toasts"] if t["severity"] == "error"]


# ---------------------------------------------------------------------------
# Render regression: evaluated matrix results are LatexMatrix, not plain Matrix
# ---------------------------------------------------------------------------


class TestRenderMatrixPipeline:
    compiler = LatexToSympyCompiler()

    def _evaluated(self, latex):
        env = LmatEnvironment.model_validate({})
        store = LmatEnvironment.create_definition_store(env)
        return _evaluate_expression(self.compiler.compile(latex, store), env)

    def test_render_evaluated_vector_does_not_recurse(self):
        # Regression: `expr in (oo, ...)` used to recurse infinitely on the
        # LatexMatrix subclass. Must return matrix LaTeX instead of raising.
        result = self._evaluated(
            r"\begin{bmatrix}1\\2\\3\end{bmatrix} + \begin{bmatrix}4\\5\\6\end{bmatrix}"
        )
        out = render(result)
        assert "matrix" in out
        assert "5" in out and "7" in out and "9" in out

    def test_render_evaluated_2x2_matrix(self):
        out = render(self._evaluated(r"\begin{bmatrix}1 & 2\\3 & 4\end{bmatrix}"))
        assert "matrix" in out or "&" in out


# ---------------------------------------------------------------------------
# Literal vector arithmetic
# ---------------------------------------------------------------------------


class TestLiteralVectorArithmetic:
    def test_vector_sum_displays(self):
        result = _dispatch(
            r"\begin{bmatrix}1\\2\\3\end{bmatrix} + \begin{bmatrix}4\\5\\6\end{bmatrix}"
        )
        assert result.kind == "display"
        for n in ("5", "7", "9"):
            assert n in result.display_latex

    def test_cross_product_displays(self):
        result = _dispatch(
            r"\begin{bmatrix}3\\-3\\1\end{bmatrix} \times \begin{bmatrix}4\\9\\2\end{bmatrix}"
        )
        assert result.kind == "display"
        for n in ("-15", "-2", "39"):
            assert n in result.display_latex

    def test_inner_product_is_scalar(self):
        result = _dispatch(
            r"\langle \begin{bmatrix}1\\2\end{bmatrix} | \begin{bmatrix}2\\4\end{bmatrix} \rangle"
        )
        assert result.kind == "display"
        assert result.display_latex == "10"


# ---------------------------------------------------------------------------
# Defining a vector and using it (type-dispatched operators must re-resolve)
# ---------------------------------------------------------------------------


class TestDefinedVectorUsage:
    def test_define_with_equals_then_scale(self):
        results = _dispatch_section([
            r"\vec{v} = \begin{bmatrix}1\\2\\3\end{bmatrix}",
            r"2 \vec{v}",
        ])
        assert results[0]["kind"] == "display"
        assert "\\vec{v} =" in results[0]["display_latex"]
        assert results[1]["kind"] == "display"
        for n in ("2", "4", "6"):
            assert n in results[1]["display_latex"]

    def test_define_then_norm(self):
        results = _dispatch_section([
            r"\vec{v} = \begin{bmatrix}3\\4\end{bmatrix}",
            r"\Vert \vec{v} \Vert",
        ])
        assert results[1]["kind"] == "display"
        assert results[1]["display_latex"] == "5"

    def test_define_two_then_cross(self):
        results = _dispatch_section([
            r"\vec{a} = \begin{bmatrix}3\\-3\\1\end{bmatrix}",
            r"\vec{b} = \begin{bmatrix}4\\9\\2\end{bmatrix}",
            r"\vec{a} \times \vec{b}",
        ])
        assert results[2]["kind"] == "display"
        for n in ("-15", "-2", "39"):
            assert n in results[2]["display_latex"]

    def test_define_then_dot(self):
        results = _dispatch_section([
            r"\vec{v} = \begin{bmatrix}1\\2\\3\end{bmatrix}",
            r"\langle \vec{v} | \vec{v} \rangle",
        ])
        assert results[1]["kind"] == "display"
        assert results[1]["display_latex"] == "14"

    def test_define_two_then_sum(self):
        results = _dispatch_section([
            r"\vec{a} = \begin{bmatrix}3\\-3\\1\end{bmatrix}",
            r"\vec{b} = \begin{bmatrix}4\\9\\2\end{bmatrix}",
            r"\vec{a} + \vec{b}",
        ])
        assert results[2]["kind"] == "display"
        for n in ("7", "6", "3"):
            assert n in results[2]["display_latex"]

    def test_vector_defined_via_environment_definition(self):
        # The `:=` path: the definition arrives as an environment definition.
        env = {
            "definitions": [
                {
                    "name_expr": r"\vec{v}",
                    "value_expr": r"\begin{bmatrix}1\\2\\3\end{bmatrix}",
                }
            ]
        }
        result = _dispatch(r"\langle \vec{v} | \vec{v} \rangle", environment=env)
        assert result.kind == "display"
        assert result.display_latex == "14"

    def test_symbolic_vector_then_define_parameters(self):
        # A vector literal may carry free parameters; defining them later makes
        # downstream operators concrete. (The parameters must not make the
        # definition look like a multi-variable system.)
        results = _dispatch_section([
            r"\vec{v} = \begin{bmatrix}a\\b\end{bmatrix}",
            r"a = 3",
            r"b = 4",
            r"\Vert \vec{v} \Vert",
        ])
        assert results[0]["kind"] == "display"  # defined, not rejected
        assert results[3]["display_latex"] == "5"

    def test_vector_defined_as_multiple_of_another_vector(self):
        results = _dispatch_section([
            r"\vec{v} = \begin{bmatrix}1\\2\\3\end{bmatrix}",
            r"\vec{w} = 2 \vec{v}",
            r"\vec{w}",
        ])
        assert results[1]["kind"] == "display"
        for n in ("2", "4", "6"):
            assert n in results[1]["display_latex"]
        for n in ("2", "4", "6"):
            assert n in results[2]["display_latex"]

    def test_reversed_assignment_matrix_equals_symbol(self):
        results = _dispatch_section([
            r"\begin{bmatrix}1\\2\end{bmatrix} = \vec{v}",
            r"2 \vec{v}",
        ])
        assert results[0]["kind"] == "display"
        for n in ("2", "4"):
            assert n in results[1]["display_latex"]


# ---------------------------------------------------------------------------
# Override, verify, errors
# ---------------------------------------------------------------------------


class TestVectorOverrideAndVerify:
    def test_override_vector_emits_info(self):
        results = _dispatch_section([
            r"\vec{v} = \begin{bmatrix}1\\2\end{bmatrix}",
            r"\vec{v} = \begin{bmatrix}9\\9\end{bmatrix}",
            r"2 \vec{v}",
        ])
        infos = [t["text"] for t in results[1]["toasts"] if t["severity"] == "info"]
        assert any("Overriding" in t for t in infos)
        # The later use reflects the override (9 -> 18).
        assert "18" in results[2]["display_latex"]

    def test_verify_vector_equality_is_silent(self):
        result = _dispatch(
            r"\begin{bmatrix}1\\2\end{bmatrix} = \begin{bmatrix}1\\2\end{bmatrix}"
        )
        assert result.kind == "silent"
        assert not _errors({
            "toasts": [{"severity": t.severity, "text": t.text} for t in result.toasts]
        })

    def test_verify_vector_contradiction_errors(self):
        result = _dispatch(
            r"\begin{bmatrix}1\\2\end{bmatrix} = \begin{bmatrix}1\\3\end{bmatrix}"
        )
        assert result.kind == "silent"
        assert any("Contradiction" in t.text for t in result.toasts)

    def test_unsolvable_matrix_equation_errors_cleanly(self):
        # `2\vec v = b` isn't a direct assignment and isn't a scalar solve.
        # Must produce an error toast, not crash.
        result = _dispatch(r"2 \vec{v} = \begin{bmatrix}1\\2\end{bmatrix}")
        assert result.kind == "silent"
        assert any(
            "matrix" in t.text.lower() for t in result.toasts if t.severity == "error"
        )


# ---------------------------------------------------------------------------
# Delimiter preservation + scalar coexistence
# ---------------------------------------------------------------------------


class TestVectorMisc:
    def test_assignment_preserves_pmatrix_delimiter(self):
        result = _dispatch(r"\vec{v} = \begin{pmatrix}1\\2\end{pmatrix}")
        assert result.kind == "display"
        assert "pmatrix" in result.display_latex

    def test_scalar_dispatch_unaffected_by_vector_in_section(self):
        results = _dispatch_section([
            r"\vec{v} = \begin{bmatrix}1\\2\end{bmatrix}",
            r"y = 5",
            r"2 y",
            r"\Vert \vec{v} \Vert",
        ])
        assert results[2]["display_latex"] == "10"
        assert results[3]["display_latex"] == "2.24"  # sqrt(5), 3 sig figs
