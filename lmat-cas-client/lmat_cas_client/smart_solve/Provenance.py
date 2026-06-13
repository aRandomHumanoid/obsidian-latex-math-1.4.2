"""
Notation provenance for Smart Solve vector definitions
(design_docs.md §"Rendering Provenance Requirements").

A vector can be written three ways: alias basis (`\\ihat`), hat basis
(`\\hat{i}`), or matrix (`bmatrix`/`pmatrix`/`array`). Smart Solve records which
*family* a symbol was defined with so it can round-trip the value back in the
same notation, rather than always collapsing to a matrix.

Family of a block is computed deterministically (design_docs §"Family
Computation") from two sources: the basis/matrix tokens appearing literally in
the block, plus the recorded family of any already-defined vector symbol the
block references. The rule:

  * any `matrix` contributor, or both `alias` and `hat` present  -> `matrix`
  * exactly one basis family                                     -> that family
  * no vector families                                           -> None

Provenance is carried on the definition object itself (`VectorDefinition`), so
it travels with the definition through clone / cache / replay exactly as the
value does — no separate side table to keep in sync.
"""

import re

from lmat_cas_client.compiling.Definitions import SympyDefinition

# Provenance family identifiers.
ALIAS = "alias"
HAT = "hat"
MATRIX = "matrix"

BASIS_FAMILIES = (ALIAS, HAT)

# Lexical detectors for notation present literally in a block's source.
_ALIAS_RE = re.compile(r"\\[ijk]hat\b")
_HAT_RE = re.compile(r"\\hat\s*\{\s*(?:i|j|k|\\imath|\\jmath)\s*\}")
_MATRIX_ENV_RE = re.compile(
    r"\\begin\s*\{\s*(?:[bp]?(?:small)?matrix|array|vmatrix)\s*\}"
)


class VectorDefinition(SympyDefinition):
    """A vector-valued definition that also records its notation provenance.

    Behaves exactly like `SympyDefinition` for the compiler (the stored value is
    a plain matrix); Smart Solve additionally reads `.family` to decide how to
    render the value.
    """

    def __init__(self, sympy_expr, family: str):
        super().__init__(sympy_expr)
        self.family = family


def family_of(definition) -> str | None:
    """The recorded family of a definition, or None if it carries no provenance."""
    return getattr(definition, "family", None)


def compute_family(latex_str: str, referenced_symbols, def_store) -> str | None:
    """Resolve the notation family of a block (design_docs §"Family Computation").

    `referenced_symbols` are the symbols whose stored family should contribute —
    for a definition, the value side's symbols (target excluded); for a plain
    expression, all of its free symbols.
    """
    families: set[str] = set()

    if _ALIAS_RE.search(latex_str):
        families.add(ALIAS)
    if _HAT_RE.search(latex_str):
        families.add(HAT)
    if _MATRIX_ENV_RE.search(latex_str):
        families.add(MATRIX)

    for sym in referenced_symbols:
        defn = def_store.get_definition(getattr(sym, "name", str(sym)))
        fam = family_of(defn)
        if fam:
            families.add(fam)

    basis = families & set(BASIS_FAMILIES)

    if MATRIX in families:
        return MATRIX
    if len(basis) == 1:
        return next(iter(basis))
    if len(basis) >= 2:
        # Mixing alias and hat is ambiguous; fall back to matrix.
        return MATRIX
    return None
