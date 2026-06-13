
<!-- omit in toc -->
# LaTeX Math Commands

This documentation section provides detailed descriptions for all Obsidian commands provided by the **LaTeX Math** plugin. For a quick overview, see the [README command list](../README.md#command-list).

<!-- omit in toc -->
## Table Of Contents

- [General Information](#general-information)
- [Commands](#commands)
  - [Smart Solve LaTeX Expression](#smart-solve-latex-expression)
  - [Evaluate LaTeX Expression](#evaluate-latex-expression)
  - [Evalf LaTeX Expression](#evalf-latex-expression)
  - [Factor LaTeX Expression](#factor-latex-expression)
  - [Expand LaTeX Expression](#expand-latex-expression)
  - [Partial Fraction Decompose LaTeX Expression](#partial-fraction-decompose-latex-expression)
  - [Convert Units In LaTeX Expression](#convert-units-in-latex-expression)
  - [Solve LaTeX Expression](#solve-latex-expression)
  - [Create Truth Table from LaTeX Expression](#create-truth-table-from-latex-expression)
  - [Convert LaTeX Expression To Sympy](#convert-latex-expression-to-sympy)

## General Information

All commands require LaTeX input, but they do not all source that input the same way.

- **Evaluate / Evalf / Expand / Factor / Partial fraction decompose / Convert units / Convert to Sympy:** if a selection is present, use the selection; otherwise use the current math block.[^math-block]
- **Solve / Create truth table:** require the cursor to be inside a math block and ignore any selection.
- **Smart Solve:** ignores any selection and operates on *all* Smart Solve-visible math blocks in the current section (see below).

[^math-block]: For cursor-based commands, a math block means editor-recognized LaTeX math delimited by `$...$` or `$$...$$`.

If a command is processed for longer than a set time (currently 1 s), **LaTeX Math** displays a clickable 'evaluating' entry in the Obsidian status bar.

Clicking this gives the option to interrupt all currently processing commands.

This is useful if you accidentally try to evaluate an intensive expression that may not finish within a reasonable time.

## Commands

### Smart Solve LaTeX Expression

> Obsidian command name: `Smart Solve LaTeX expression`

The fork's primary command. Re-evaluates **every math block in the current section** (display `$$...$$` and single-line inline `$...$`) in document order, maintaining a notebook-style implicit context of variable definitions and stored constraints. Depending on each block's structure it will:

- **Define:** `x = 3` stores `x ↦ 3`. A later equation in one unknown overrides the stored value ("most recent derivation wins"), with an `Overriding x: was 3, now 4.` notice when the value changes.
- **Solve:** an equation with one remaining unknown (after substituting known values) is solved in the configured [solve domain](LMAT_ENV.md#default-solve-domain). Multiple solutions are resolved by a deterministic tiebreaker (prior value match, then largest magnitude, then positive real > negative real > complex), with a warning notice listing the alternatives. Solutions are filtered by [symbol assumptions](LMAT_ENV.md#symbol-assumptions).
- **Accumulate:** an equation with 2+ remaining unknowns is stored as a constraint. Whenever the accumulated system uniquely determines variables, they are promoted to definitions (`Derived: y = 7` notices).
- **Evaluate:** a plain expression (or a block ending in `=`) is evaluated with all definitions substituted, and the result is written inline after a marker (default `\Rightarrow`, configurable via the Smart Solve result marker setting; a blank setting falls back to `\Rightarrow`). If unknowns remain but are constrained, a symbolic result is shown instead.
- **Verify:** an equation whose symbols are all defined is checked: silent if true, `Contradiction` error notice if false.

Additional behavior:

- **Sections:** the context resets at every markdown heading, horizontal rule (`---`/`***`/`___`), and `lmat` code block. See [LMAT_ENV.md](LMAT_ENV.md).
- **Refresh semantics:** only the block under the cursor can get a *new* inline result; other blocks only have *existing* results refreshed (or stripped if stale). Pressing the hotkey outside any math block refreshes the section without adding anything.
- **Idempotent rewrites:** re-running replaces the text after the result marker rather than appending. Any of the common arrows (`\Rightarrow`, `\to`, `\implies`, ...) are detected as markers, and a trailing `\text{...}` suffix is preserved.
- **`%ref` blocks:** a block containing a `%ref` / `% \text{ref}` comment is ignored entirely (documentation only).
- **Numeric display:** numeric results use significant figures (default 3, configurable via [`[render] sig_figs`](LMAT_ENV.md#significant-figures)), with scientific notation for very large/small magnitudes. Values are stored exactly (symbolically) regardless of display.
- **Notices:** at most 5 notices are shown per press plus a rollup and a summary line (`Re-evaluated 3/5 blocks — 1 error`).

If the current solve domain is real and only complex solutions exist, Smart Solve shows a warning telling you to switch the section's [`[solve] domain`](LMAT_ENV.md#default-solve-domain) to `"Complexes"`.

Current limitations: multi-equation blocks (`cases` / `align`) are rejected — use [Solve](#solve-latex-expression) for those — and function definitions like `f(x) = x^2` are skipped; define functions with `:=` instead.

### Evaluate LaTeX Expression

> Obsidian command name: `Evaluate LaTeX expression`

The `Evaluate LaTeX expression` command simplifies (via [`sympy.simplify`](https://docs.sympy.org/latest/tutorials/intro-tutorial/simplification.html#simplify)) the *right-most* expression in the given LaTeX input, and inserts the result to the right of the input, separated by `=`.

For example, if `2x < y = 3^2` is the input, **LaTeX Math** evaluates `3^2` (the *right-most* expression) to `9`, and inserts `= 9` at the end of the input.

If the input is a system of relations, the *right-most* expression of the *bottom-most* line is evaluated and inserted on that line.

### Evalf LaTeX Expression

> Obsidian command name: `Evalf LaTeX expression`

Same as [Evaluate LaTeX Expression](#evaluate-latex-expression), except [`sympy.evalf`](https://docs.sympy.org/latest/modules/core.html#module-sympy.core.evalf) is also applied to the parsed input after simplification.

### Factor LaTeX Expression

> Obsidian command name: `Factor LaTeX expression`

Same as [Evaluate LaTeX Expression](#evaluate-latex-expression), except [`sympy.factor`](https://docs.sympy.org/latest/tutorials/intro-tutorial/simplification.html#factor) is also applied to the parsed input after simplification.

### Expand LaTeX Expression

> Obsidian command name: `Expand LaTeX expression`

Same as [Evaluate LaTeX Expression](#evaluate-latex-expression), except [`sympy.expand`](https://docs.sympy.org/latest/tutorials/intro-tutorial/simplification.html#expand) is also applied to the parsed input after simplification.

### Partial Fraction Decompose LaTeX Expression

> Obsidian command name: `Partial Fraction Decompose LaTeX expression`

Same as [Evaluate LaTeX Expression](#evaluate-latex-expression), except [`sympy.apart`](https://docs.sympy.org/latest/tutorials/intro-tutorial/simplification.html#apart) is also applied to the parsed input after simplification.

### Convert Units In LaTeX Expression

> Obsidian command name: `Convert units in LaTeX expression`

This command prompts for a list of units[^unit-list] separated by whitespace which existing units should be converted to.

[^unit-list]: see [SYNTAX.md](SYNTAX.md#supported-units) for a list of units.

Upon confirmation of the unit list, this command parses and evaluates the LaTeX input like the [Evaluate LaTeX Expression](#evaluate-latex-expression) command, and performs the unit conversion on the simplified result.

> [!NOTE]
> **Example**
>
> Supplied list of units through the unit modal is `km h`, this is interpreted as the units `km` and `h`
>
> LaTeX input is `50 \frac{{m}}{{s}}`.
>
> Output is `180 \frac{{km}}{{h}}`.

### Solve LaTeX Expression

> Obsidian command name: `Solve LaTeX expression`

This command attempts to parse a single or a series of equations.

The output is always placed in a `$$ ... $$` math block, below the LaTeX input.

If there are too many unknowns to solve for, **LaTeX Math** prompts the user to select which symbols should be solved for.

One can also specify the *solution domain* for single equations.

Series of equations can be notated by chaining multiple relations together (`x < y < z`) or by inserting multiple relations in a `cases` or `align` environment (`\begin{cases} x = 2 y \\ y = 5 \end{cases}`).

#### Restricting the solution

The method for restricting the set of solutions for a given input varies on the input type.

If the input is a single relation, then one must restrict the solution set either through the solve modals `Solution domain` input,
or in the `lmat` environments [solve domain field](LMAT_ENV.md#default-solve-domain).

If the input is a series of relations, one must restrict the solution set by applying [assumptions on the unknown variables](LMAT_ENV.md#symbol-assumptions) in the relations.

### Create Truth Table from LaTeX Expression

> Obsidian command name: `Create truth table from LaTeX expression (Markdown)` / `Create truth table from LaTeX expression (LaTeX)`

This command requires the input is a [proposition](SYNTAX.md#logical-proposition).

[`sympy.logic.boolalg.truth_table`](https://docs.sympy.org/latest/modules/logic.html#sympy.logic.boolalg.truth_table) is used to generate a truth table of the proposition input, which is then inserted either as a LaTeX array, or a markdown table depending on the chosen command.

The input permutations are shown in the left most columns, and the proposition value is shown in the right most column.

### Convert LaTeX Expression To Sympy

> Obsidian command name: `Convert LaTeX expression to Sympy`

This command parses the LaTeX input, and places the parsed sympy code into a `python` code block below the selected input or current math block.

Definitions and assumptions are currently **NOT** included, and need to be added in manually.
