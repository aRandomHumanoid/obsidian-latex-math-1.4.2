from lark import Transformer, v_args
from sympy import *
from sympy import ImmutableDenseMatrix

# Cartesian unit basis vectors of R^3, keyed by terminal type. Plain immutable
# matrices (not LatexMatrix) so they flow through the scalar `subs`/`Mul`
# machinery without the LatexMatrix subclass's breakage.
_BASIS_VECTORS = {
    "BASIS_VECTOR_I": ImmutableDenseMatrix([1, 0, 0]),
    "BASIS_VECTOR_J": ImmutableDenseMatrix([0, 1, 0]),
    "BASIS_VECTOR_K": ImmutableDenseMatrix([0, 0, 1]),
}


# This transformer is responsible for providing the values of various un-redefinable (cannot ':=' them) mathematical constants.
@v_args(inline=True)
class ConstantsTransformer(Transformer):
    def CONST_INFINITY(self, _) -> Expr:
        return oo

    def basis_vector(self, token) -> Expr:
        return _BASIS_VECTORS[token.type]
