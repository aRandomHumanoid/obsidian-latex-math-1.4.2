<!-- omit in toc -->
# LaTeX Math Environments

**LaTeX Math** environments are used to configure CAS options for a section of a note.

The persistence of **LaTeX Math** environments is location-based.

A new environment declaration resets all previous configurations to their default values, including variables defined through `$ .. := .. $`.

For the [Smart Solve](COMMANDS.md#smart-solve-latex-expression) command, an `lmat` code block additionally acts as a **section divider** (alongside markdown headings and horizontal rules): the implicit context of definitions, derived values, and stored constraints resets after it, and the block's configuration governs the new section.

Environments are declared directly in the note using an `lmat` code block.

Below is a preview of the default **LaTeX Math** environment used, when no other environment has been declared.

<pre>
```lmat
<a href="##symbols">[symbols]</a>

[units]
<a href="##unit-system">system</a> = "SI"

[solve]
<a href="##default-solve-domain">domain</a> = "Complexes"

[render]
<a href="##significant-figures">sig_figs</a> = 3
```
</pre>

<!-- omit in toc -->
## Table of Contents

- [Symbol Assumptions](#symbol-assumptions)
- [Unit System](#unit-system)
- [Default Solve Domain](#default-solve-domain)
- [Significant Figures](#significant-figures)

## Symbol Assumptions

Assumptions are specified for a single symbol by assigning a list of [sympy assumptions](https://docs.sympy.org/latest/guides/assumptions.html#id28) to the symbol name, under the `symbols` table.

```toml
[symbols]
x = [ "real", "positive" ]
y = [ "integer", ... ]
...
```

A preview of the symbol assumptions is also generated while the `lmat` code block is not being edited.

## Unit System

The default unit system to use when auto-converting between units can be specified in the `system` field under the `units` table.

```toml
[units]
system = "..."
```

The value must be a string equal to one of the names in the **Unit System Name** column:

| Unit System Name | Base Units                                             |
| ---------------- | ------------------------------------------------------ |
| SI               | meter, kilogram, second, ampere, mole, candela, kelvin |
| MKSA             | meter, kilogram, second, ampere                        |
| MKS              | meter, kilogram, second                                |
| Natural system   | hbar, electronvolt, speed of light                     |

## Default Solve Domain

The default solution domain for single equations can be set in the `domain` field under the `solve` table.

```toml
[solve]
domain = "..."
```

This must be a string equal to the name of a [sympy fancy set](https://docs.sympy.org/latest/modules/sets.html#module-sympy.sets.fancysets) (e.g. "Reals" for the real numbers or "Naturals" for all natural numbers).

This domain is used both by the [Solve](COMMANDS.md#solve-latex-expression) command (for single equations) and by [Smart Solve](COMMANDS.md#smart-solve-latex-expression) when deriving variable values. If unset, the domain is `"Complexes"`.

There is no global plugin setting for the default solve domain; configure it per section through `lmat`.

If Smart Solve is running in the real domain and only complex solutions exist, it warns you to change this field to `"Complexes"` for that section.

## Significant Figures

The number of significant figures [Smart Solve](COMMANDS.md#smart-solve-latex-expression) uses when displaying numeric results can be set in the `sig_figs` field under the `render` table.

```toml
[render]
sig_figs = 4
```

The default is `3`. Invalid non-positive values fall back to `3`. Magnitudes below `1e-4` or at/above `1e6` are displayed in scientific notation. This only affects *display* — values are always stored exactly (symbolically) for use in later calculations.

There is no global plugin setting for Smart Solve numeric precision; configure it per section through `lmat`.
