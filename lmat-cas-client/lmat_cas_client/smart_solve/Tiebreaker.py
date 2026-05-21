from dataclasses import dataclass
from typing import Optional

from sympy import Abs, Expr, im, re, simplify


@dataclass
class TiebreakerSelection:
    chosen: Expr
    was_choice_made: bool  # True only when ≥2 candidates AND no prior match


def select(solutions: list[Expr], prior: Optional[Expr]) -> TiebreakerSelection:
    """
    Apply the multi-solution tiebreaker from design_docs §"Multi-Solution Tiebreaker":

    1. If prior value matches one solution → return it silently (no choice made).
    2. Otherwise sort by `abs(solution)` descending.
    3. Equal-magnitude tiebreaker: positive real > negative real > complex.
    4. Final tiebreaker: Sympy's natural ordering of the candidates (str() comparison).

    Returns the chosen value and a flag indicating whether a choice was made
    among multiple candidates (i.e. a multi-solution warning should be raised).
    """
    if len(solutions) == 0:
        raise ValueError("Tiebreaker.select called with no solutions")

    if len(solutions) == 1:
        return TiebreakerSelection(chosen=solutions[0], was_choice_made=False)

    # Rule 1: prior match.
    if prior is not None:
        for sol in solutions:
            try:
                if simplify(sol - prior) == 0:
                    return TiebreakerSelection(chosen=sol, was_choice_made=False)
            except Exception:
                continue

    # Rules 2–4: sort.
    sorted_sols = sorted(solutions, key=_rank_key)
    chosen = sorted_sols[0]
    return TiebreakerSelection(chosen=chosen, was_choice_made=True)


def _rank_key(sol: Expr):
    """Rank key for sorting (ascending) such that the smallest tuple is the most preferred.

    Priorities (smaller wins):
    - (a) Negative of magnitude (so large magnitudes sort first).
    - (b) Type rank: 0 = positive real, 1 = negative real, 2 = complex.
    - (c) String form (deterministic final tiebreaker, mirrors sympy natural ordering for simple cases).
    """
    try:
        magnitude = float(simplify(Abs(sol)))
    except (TypeError, ValueError):
        magnitude = 0.0

    type_rank = _type_rank(sol)
    return (-magnitude, type_rank, str(sol))


def _type_rank(sol: Expr) -> int:
    try:
        imag = simplify(im(sol))
    except Exception:
        imag = None

    if imag is not None and imag == 0:
        try:
            real = simplify(re(sol))
        except Exception:
            real = None
        if real is not None and real >= 0:
            return 0  # positive real (or zero)
        return 1  # negative real
    return 2  # complex
