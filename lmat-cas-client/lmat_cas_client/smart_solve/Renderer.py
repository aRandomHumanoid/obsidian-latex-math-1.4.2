"""
Smart Solve render layer (design_docs.md §"Rendering").

Numeric results are formatted with a configurable number of significant figures.
Very large or very small magnitudes switch to scientific notation so the
display stays compact. Non-numeric / symbolic results fall back to the existing
LmatLatexPrinter.
"""

import math

from sympy import Add, Expr, N, S, nan, oo, zoo

from lmat_cas_client.LmatLatexPrinter import lmat_latex
from lmat_cas_client.smart_solve.Provenance import ALIAS, BASIS_FAMILIES, HAT

DEFAULT_SIG_FIGS = 3

# Magnitudes outside this range render in scientific notation.
SCI_LOW = 1e-4
SCI_HIGH = 1e6

# Basis-vector symbol per provenance family, in i, j, k order.
_BASIS_SYMBOLS = {
    ALIAS: (r"\ihat", r"\jhat", r"\khat"),
    HAT: (r"\hat{i}", r"\hat{j}", r"\hat{k}"),
}


def render(
    expr: Expr, sig_figs: int = DEFAULT_SIG_FIGS, family: str | None = None
) -> str:
    """Render `expr` for inline Smart Solve display.

    Numeric scalars: round to `sig_figs` significant figures, optionally in
    scientific notation. A 3-component vector whose `family` is a basis family
    renders in `i`/`j`/`k` notation. Everything else (symbolic results, other
    matrices, sets, relations) goes through the existing LaTeX printer.
    """
    if sig_figs <= 0:
        sig_figs = DEFAULT_SIG_FIGS

    # Basis-style output for 3-component vectors with recorded basis provenance.
    if family in BASIS_FAMILIES and getattr(expr, "is_Matrix", False):
        basis = _render_basis(expr, family, sig_figs)
        if basis is not None:
            return basis

    # Non-scalar results (matrices/vectors, sets, relations, symbolic exprs) go
    # straight to the LaTeX printer. This MUST come before the oo/nan membership
    # test below: `matrix in (oo, ...)` triggers elementwise `__eq__`, which
    # recurses infinitely on the compiler's `LatexMatrix` subclass.
    if not _is_numeric_scalar(expr):
        return lmat_latex(expr)

    if expr in (oo, -oo, zoo, nan):
        return lmat_latex(expr)

    try:
        numeric = float(N(expr))
    except (TypeError, ValueError):
        return lmat_latex(expr)

    return _format_number(numeric, sig_figs)


def _vector_components(mat):
    """Return the 3 entries of a 3-component vector (3x1 or 1x3), else None."""
    shape = getattr(mat, "shape", None)
    if shape not in ((3, 1), (1, 3)):
        return None
    return list(mat)


def _render_basis(mat, family: str, sig_figs: int) -> str | None:
    """Render a 3-component vector in basis notation, or None if not applicable
    (design_docs.md §"Basis-Style Output Rules")."""
    components = _vector_components(mat)
    if components is None:
        return None

    symbols = _BASIS_SYMBOLS[family]

    # Zero vector renders as a plain 0, never an expanded 0i + 0j + 0k.
    if all(getattr(c, "is_zero", False) for c in components):
        return "0"

    parts: list[tuple[bool, str]] = []
    for coeff, symbol in zip(components, symbols):
        if getattr(coeff, "is_zero", False):
            continue  # omit zero components
        negative = coeff.could_extract_minus_sign()
        magnitude = -coeff if negative else coeff
        if magnitude == S.One:
            body = symbol  # coefficient 1 is implied
        else:
            coeff_str = render(magnitude, sig_figs)
            if isinstance(magnitude, Add):
                coeff_str = rf"\left({coeff_str}\right)"
            body = f"{coeff_str}{symbol}"
        parts.append((negative, body))

    if not parts:
        # Components were symbolic and none provably nonzero — fall back.
        return None

    out = ("-" if parts[0][0] else "") + parts[0][1]
    for negative, body in parts[1:]:
        out += (" - " if negative else " + ") + body
    return out


def _is_numeric_scalar(expr: Expr) -> bool:
    """True if `expr` is a real numeric scalar (no symbols, not a set, not a matrix)."""
    try:
        if expr.free_symbols:
            return False
    except AttributeError:
        return False
    if not getattr(expr, "is_number", False):
        return False
    if getattr(expr, "is_real", None) is False:
        return False
    return True


def _format_number(value: float, sig_figs: int) -> str:
    if value == 0:
        return "0"

    abs_v = abs(value)
    use_sci = abs_v < SCI_LOW or abs_v >= SCI_HIGH

    if use_sci:
        return _format_scientific(value, sig_figs)
    return _format_fixed(value, sig_figs)


def _format_scientific(value: float, sig_figs: int) -> str:
    exponent = int(math.floor(math.log10(abs(value))))
    mantissa = value / (10**exponent)
    mantissa_str = _format_fixed(mantissa, sig_figs)
    return f"{mantissa_str} \\times 10^{{{exponent}}}"


def _format_fixed(value: float, sig_figs: int) -> str:
    if value == 0:
        return "0"
    exponent = int(math.floor(math.log10(abs(value))))
    decimals = max(0, sig_figs - 1 - exponent)
    formatted = f"{value:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
        if formatted in ("", "-"):
            formatted = "0"
    return formatted
