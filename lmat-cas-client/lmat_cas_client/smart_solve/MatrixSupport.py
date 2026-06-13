"""
Helpers for handling matrix / vector quantities inside Smart Solve.

Smart Solve's dispatch logic is scalar-oriented: it leans on `solveset` to turn
`x = ...` into a stored value and on `expr.subs(symbol, value)` to substitute
definitions back into expressions. Neither plays nicely with matrices:

  * `solveset(Eq(v, <matrix>), v)` raises (matrices are unhashable / not a
    scalar solve target), so a `\\vec v = <vector>` block can't go through the
    normal solve path — it must be treated as a direct *assignment*.

  * The compiler's `LatexMatrix` subclass (see
    `compiling/transforming/LatexMatrix.py`) is generated per-instance with a
    custom `__new__`. The resulting class is unhashable and is missing sympy's
    assumption attributes (`is_Rational`, ...), so feeding it into a scalar
    `Mul`/`subs` blows up with `AttributeError`/`TypeError`. A *plain* sympy
    matrix substitutes and evaluates cleanly, so we normalize to one before any
    value flows through sympy's scalar machinery.

These helpers are shared by the dispatcher and the context-replay walk so both
sides agree on what counts as a matrix assignment and how matrix values are
normalized.
"""

from typing import Optional

from sympy import ImmutableDenseMatrix, Symbol
from sympy.core.relational import Equality, Relational
from sympy.matrices.matrixbase import MatrixBase


def is_matrix(value) -> bool:
    """True for any sympy matrix (vectors included — a vector is an n×1 matrix)."""
    return isinstance(value, MatrixBase)


def has_matrix(expr) -> bool:
    """True if `expr` is, or contains, a matrix subexpression."""
    if is_matrix(expr):
        return True
    try:
        return bool(expr.has(MatrixBase))
    except Exception:
        return False


def to_plain_matrix(value):
    """Normalize a matrix to a plain immutable sympy matrix.

    The custom `LatexMatrix` subclass breaks `subs`/`Mul`/`solveset` (see module
    docstring). `ImmutableDenseMatrix` substitutes cleanly and is hashable. The
    visible delimiter style (`bmatrix`/`pmatrix`/...) is only carried by
    `LatexMatrix`, so callers that want to *display* the original should render
    it before normalizing. Non-matrix values pass through unchanged.
    """
    if isinstance(value, MatrixBase):
        return ImmutableDenseMatrix(value)
    return value


def assignment_value(equation: Relational, target) -> Optional[object]:
    """If `equation` directly isolates `target` (`target = <expr>` or
    `<expr> = target`) with `target` absent from the other side, return that
    other side. Otherwise return None.

    This lets a `\\vec v = <vector>` block be handled as a definition instead of
    being routed through `solveset`, which cannot solve matrix-valued equations.
    """
    if not isinstance(equation, Equality):
        return None
    lhs, rhs = equation.lhs, equation.rhs
    # `target` is always a scalar Symbol, so a matrix side can never equal it.
    # Guard the `== target` checks: `matrix == symbol` triggers elementwise
    # `__eq__`, which recurses infinitely on the LatexMatrix subclass.
    if not is_matrix(lhs) and lhs == target and target not in rhs.free_symbols:
        return rhs
    if not is_matrix(rhs) and rhs == target and target not in lhs.free_symbols:
        return lhs
    return None


def matrix_assignment_sides(equation: Relational):
    """If `equation` assigns a matrix to a lone symbol — `s = <…matrix…>` or
    `<…matrix…> = s` — return `(s, value_side)`. Otherwise return
    `(None, None)`.

    Unlike `assignment_value`, the value side may carry its *own* free
    parameters (e.g. `\\vec v = \\begin{bmatrix} a \\\\ b \\end{bmatrix}`).
    Those parameters would otherwise make the block look like a multi-variable
    system; recognizing the assignment up front lets a vector be defined the
    same way a scalar is.
    """
    if not isinstance(equation, Equality):
        return None, None
    lhs, rhs = equation.lhs, equation.rhs
    if isinstance(lhs, Symbol) and has_matrix(rhs) and lhs not in rhs.free_symbols:
        return lhs, rhs
    if isinstance(rhs, Symbol) and has_matrix(lhs) and rhs not in lhs.free_symbols:
        return rhs, lhs
    return None, None


def matrices_equal(a, b) -> bool:
    """Shape-aware zero-difference test for two matrices."""
    if not (is_matrix(a) and is_matrix(b)):
        return False
    if a.shape != b.shape:
        return False
    try:
        return bool((a - b).is_zero_matrix)
    except Exception:
        return False
