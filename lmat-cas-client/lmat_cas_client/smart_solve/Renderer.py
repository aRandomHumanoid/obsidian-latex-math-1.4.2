"""
Smart Solve render layer (design_docs.md §"Rendering").

Numeric results are formatted with a configurable number of significant figures.
Very large or very small magnitudes switch to scientific notation so the
display stays compact. Non-numeric / symbolic results fall back to the existing
LmatLatexPrinter.
"""

import math
from typing import Optional

from sympy import Expr, N, nan, oo, zoo

from lmat_cas_client.LmatLatexPrinter import lmat_latex

DEFAULT_SIG_FIGS = 3

# Magnitudes outside this range render in scientific notation.
SCI_LOW = 1e-4
SCI_HIGH = 1e6


def render(expr: Expr, sig_figs: int = DEFAULT_SIG_FIGS) -> str:
    """Render `expr` for inline Smart Solve display.

    Numeric scalars: round to `sig_figs` significant figures, optionally in
    scientific notation. Everything else (symbolic results, matrices, sets,
    relations) goes through the existing LaTeX printer unchanged.
    """
    if sig_figs <= 0:
        sig_figs = DEFAULT_SIG_FIGS

    if expr in (oo, -oo, zoo, nan):
        return lmat_latex(expr)

    if not _is_numeric_scalar(expr):
        return lmat_latex(expr)

    try:
        numeric = float(N(expr))
    except (TypeError, ValueError):
        return lmat_latex(expr)

    return _format_number(numeric, sig_figs)


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
    mantissa = value / (10 ** exponent)
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
