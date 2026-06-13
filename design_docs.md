# LaTeX Math Fork — Design Specification

A fork of the [obsidian-latex-math](https://github.com/zarstensen/obsidian-latex-math) plugin that consolidates evaluation and solving into a single "smart" hotkey with notebook-style implicit variable management and section-scoped namespaces.

> [!NOTE]
> **Document status (v1.5.8):** this began as a pre-implementation spec and has been revised to describe the system *as built*. Where the implementation deliberately deviates from or extends the original spec, the section says so explicitly. Pointers into the code accompany each major section: the TypeScript side lives under `src/` (entry: `src/controllers/commands/SmartSolveCommand.ts`), the Python side under `lmat-cas-client/lmat_cas_client/smart_solve/` (entry: `Dispatcher.py`).

## Goals

- **One primary hotkey** that dispatches to the right operation (evaluate, solve, store) based on the structure of the math block.
- **Notebook-style semantics:** writing `x = 3` defines `x`, and subsequent blocks can use that definition without ceremony.
- **Implicit constraint accumulation:** equations with multiple unknowns are stored and used to solve future blocks when possible.
- **Section-scoped namespaces:** variables persist within a section but reset at explicit dividers, allowing variable name reuse across sections of a document.
- **Preserve existing functionality:** advanced transformations (Expand, Factor, Partial Fraction Decompose), explicit `:=` assignment, and `lmat` configuration blocks remain available.

## Core Concepts

### The Context

At every point in a document, there is an implicit **context** consisting of:

- **Definitions:** symbols and functions with assigned values (`x ↦ 3`, `f(x) ↦ x^2 + 1`).
- **Constraints:** equations that haven't been solved but are stored for potential future use (`x + y = 5`).
- **Domain:** the solution domain, settable per section via the `lmat` block (default: complex — see [Domain Setting](#domain-setting)).
- **Render settings:** significant figures for numeric output (`[render] sig_figs`).

The context is **reconstructed on every hotkey press** by walking the document from the most recent section divider down. There is no persistent in-memory model between hotkey presses (apart from a bounded replay cache — see [Caching](#caching)).

As built, context reconstruction happens on the Python side: TypeScript collects the section's math-block sources (`src/models/cas/SectionContextBuilder.ts`) and sends them in document order; `smart_solve/ContextReplay.py` replays each block through a reduced version of the dispatch, accumulating definitions and constraints.

### Section Scopes

The document is divided into **sections**. Each section has its own independent context. Variables, definitions, and constraints in one section do not affect any other section.

A section ends and a new one begins at any of (see `SectionContextBuilder.isDivider`):

- A markdown horizontal rule: `---`, `***`, or `___`
- A markdown heading (any level): `# Heading`, `## Subheading`, etc.
- An `lmat` configuration code block (which also supplies the TOML config for the new section)

**Global constants** can be defined in a dedicated section at the top of the document (before any section divider) — they are *not* automatically inherited by other sections. To share values across sections, the user must explicitly redefine them.

(Future extension: a `# Constants` or similar named section whose contents are inherited by all other sections. Not in v1.)

### Reference Equations

A math block tagged with a `%ref` LaTeX comment is treated as pure documentation. The plugin ignores it entirely: no evaluation, no storage, no participation in the constraint system.

As built, detection is liberal (case-insensitive regex in `Dispatcher.py`): `%ref`, `% ref`, and `% \text{ref}` all work — the `\text{...}` form matters because Obsidian renders bare `%`-comments invisibly.

Example:
```latex
$$ E = mc^2 \quad \% \text{ref} $$
```

## The Smart Solve Hotkey

The primary command is **`Smart Solve LaTeX expression`** (recommended hotkey `Alt+B`; like all Obsidian commands it ships unbound). When pressed, it:

1. Builds the current section's context (`SectionContextBuilder`): all math blocks — display `$$...$$` and single-line inline `$...$` — between the nearest enclosing section dividers, plus the governing `lmat` config.
2. Sends the *entire section* as one `smart-solve-section` message (batch dispatch, added in 1.5.8 — one CAS round-trip per press, not one per block).
3. Python replays the blocks in order, returning a per-block result: `display` (render a result inline), `silent` (toasts only), or `no_op` (e.g. `%ref`).
4. TypeScript rewrites blocks as needed (see [Result Insertion](#result-insertion)), shows toasts, and prints a one-line summary notice (`Re-evaluated 3/5 blocks — 1 error`).

A re-press while a run is in flight abandons the older run (monotonic run-id check in `SmartSolveCommand`), so two runs never race edits into the same document.

### Dispatch Algorithm

The dispatch always tries to **derive new values** from each equation, ignoring prior definitions of the variable(s) being solved for. This implements "the most recent value wins" semantics: a later block can freely override earlier definitions, as long as it produces an unambiguous derivation.

Contradictions are only flagged when every symbol in the equation is already defined and substitution yields a false statement — i.e., when there's no variable left to be redefined.

As-built algorithm (per block; `Dispatcher.dispatch_with_context`):

```
INPUT: current math block B, accumulated context C (replayed from the section's prior blocks)

Step 0: If B contains a %ref comment, return NO_OP.

Step 0.5 (as built): If B parses to a multi-equation system (`cases`/`align`),
  error: "Multi-equation blocks are not yet supported by Smart Solve."
  (Use the explicit Solve command for systems written in one block.)

Step 1: ":=" definitions are handled by the pre-existing upstream pipeline
  (TypeScript extracts them into the environment's definition list), not by
  the dispatcher itself. They participate in C like any other definition.

Step 2: If B's LHS is a function application "f(args) = ...":
  - NOT IMPLEMENTED. The block is silently skipped (hook left in
    `_dispatch_relation`). Function definitions require ":=".

Step 2.5 (as built): If B is "expr =" (trailing equals), it parses as
  Eq(expr, Dummy) and is treated as "evaluate expr" (Step 5).

Step 3: syntactic_vars = all free symbols appearing in B.

Step 4: If B is a relation:

  4a: If len(syntactic_vars) == 0:
      - Both sides are concrete. Verification check (simplify(lhs - rhs) == 0).
      - If equal: silent. (Any stale inline result on the block is stripped.)
      - Else: error toast "Contradiction: {LHS} ≠ {RHS}."

  4b: If len(syntactic_vars) == 1:
      - One variable in the equation. Treat as the derivation target.
      - Solve B for that variable in C.domain (sympy solveset).
      - Candidate solutions are post-filtered by the symbol's declared
        assumptions (positive, integer, ...) — solveset does not do this
        itself. If filtering empties the set: error.
      - 0 solutions: error "No solution exists for {target} in {domain}."
        (If domain is Reals and complex solutions exist, a hint toast is added.)
      - 1 solution: store as definition (overriding if already defined) and
        display "x = value" inline.
        - If prior value existed and differed: info toast "Overriding x: was 3, now 4."
        - If prior value existed and matched: silent (no display, no toast).
      - 2+ solutions:
        - If prior value matches one solution: keep prior value, silent.
        - Else: pick by tiebreaker, store, display, and warn via toast listing
          all solutions.
        - (Replay-side nuance, 1.5.7: ALL candidate values are retained in a
          MultiValueDefinition until the variable is actually *used* in a
          calculation, at which point the tiebreaker picks one and a warning
          toast says which.)
      - Non-finite solution sets (e.g. periodic trig solutions): the first
        element is taken if the set is iterable; otherwise a toast shows the
        solution set itself.

  4c: If len(syntactic_vars) >= 2:
      - Substitute known definitions from C for all symbols that ARE defined.
      - Let remaining_vars = free symbols after substitution.

      - If len(remaining_vars) == 0:
          - All symbols were defined; substitution yielded a concrete statement.
          - If true: silent verification.
          - Else: error "Contradiction: {LHS} ≠ {RHS} after substitution."

      - If len(remaining_vars) == 1:
          - One variable left after substitution. Same handling as 4b.

      - If len(remaining_vars) >= 2:
          - Add (lhs - rhs) to the accumulated constraint system and attempt
            to solve it (linsolve, falling back to nonlinsolve) for all
            remaining variables (`ConstraintStore.solve_and_materialize`).
          - Variables whose solved value is concrete (no free parameters) are
            promoted to definitions; an info toast "Derived: y = 7" fires per
            variable. Fully-determined constraints are pruned from the store.
          - Underdetermined variables stay free; the block stays silent and
            its equation remains stored as a constraint.

Step 5: If B is an expression (no relation, or trailing "="):
  - Substitute all known definitions from C into B and evaluate
    (simplify + automatic unit conversion).
  - If fully concrete: display the result inline.
  - If free symbols remain: try to express them via the accumulated
    constraints (symbolic fallback, 1.5.3). If that makes progress, display
    the (possibly still symbolic) result; if free parameters remain, an info
    toast lists them ("Symbolic result (free parameters: z).").
  - Otherwise: error "Undefined variable(s): x, y."
```

### The Key Difference from a "Strict" CAS

Under this dispatch, the document is **not a system of simultaneous equations**. It is a sequence of derivations where later lines override earlier ones. The plugin is closer in spirit to a Python REPL than to Mathematica's symbolic equation-handling.

Example:
```
$$ x = 3 $$         → x := 3
$$ x + 1 = 5 $$     → solve for x → x = 4; override (was 3, now 4)
$$ x = $$            → evaluate → 4
```

A strict CAS would reject the second line as inconsistent with the first. This plugin instead treats each equation as a fresh statement about the current value of its variable(s).

The contradiction safety net only fires when no derivation is possible — i.e., the equation has no free variables to assign. This catches cases like:

```
$$ x = 3 $$
$$ y = 5 $$
$$ x + y = 10 $$   → after sub: 8 = 10. No free vars. Contradiction toast.
```

Here, the user has likely made a mistake (the third equation can't be reconciled and there's no symbol to redefine). The plugin flags it but does nothing else.

### Multi-Solution Tiebreaker

When an equation has multiple valid solutions, the plugin picks one and stores it (`smart_solve/Tiebreaker.py`).

Selection rule, in order:

1. **Match prior value if possible.** If the variable was previously defined and one of the new solutions equals the prior value, keep the prior value. No override, no toast — the equation is consistent with what we already had.

2. **Largest magnitude.** Otherwise, sort solutions by `abs(solution)`, descending.

3. **Tiebreaker for equal magnitudes:** positive real (zero counts as positive) > negative real > complex.

4. **Final tiebreaker:** string form of the expression (deterministic; mirrors Sympy's natural ordering for simple cases).

When a choice was made among multiple solutions (rules 2–4), a warning toast lists all solutions and which was chosen.

Examples:

- `x^2 = 4` with no prior `x` → solutions `{-2, 2}` → equal magnitudes → positive real → stored as `x = 2`. Warning toast.
- `x^2 = 9` with `x := -3` defined → solutions `{-3, 3}` → `-3` matches prior → keep `x = -3`. Silent.
- `x^2 = 9` with `x := 7` defined → solutions `{-3, 3}` → no match → largest magnitude tied → positive real → store `x = 3`. Override toast + multi-solution warning.

**Value retention (1.5.7).** During context replay, a multi-solution equation stores *all* its candidate values (`MultiValueDefinition`) rather than committing immediately. When the variable is merely displayed, the stored set is tiebroken as above; when it is *used in a calculation*, the tiebreaker picks one and a warning toast announces the choice (`Multiple stored values for x: {-2, 2}. Using 2 for this calculation.`). This keeps `x^2 = 4` followed by `x = -2` consistent: the second equation matches a retained candidate instead of contradicting a prematurely-chosen one.

### Override Behavior Details

- **Single-solution derivation matches prior value:** silent no-op.
- **Single-solution derivation differs from prior value:** info toast "Overriding x: was 3, now 4." and the new value is displayed inline.
- **Multi-solution derivation, one matches prior value:** silent, keep prior.
- **Multi-solution derivation, none matches prior value:** override toast + multi-solution warning toast.
- **Fresh assignment (variable had no prior value):** stored, and the derived value is displayed inline on the block (`x = 4` after the marker).

### Permissive Partial-System Solving

When a block introduces a new constraint and the accumulated system has more equations than before, the plugin attempts to derive as many variable values as possible (`smart_solve/ConstraintStore.py`):

```
system = C.constraints ∪ {current_block, with known definitions substituted}
solution = linsolve(system, all_free_vars)   # nonlinsolve on NonlinearError

for var in all_free_vars:
    if solution[var] is a concrete value (no free parameters):
        promote to definition in C            # info toast "Derived: var = value"
        prune fully-determined constraints
    else:
        leave var free; the equation stays stored as a constraint
```

If the system uniquely determines some but not all variables, materialize the determined ones and leave the rest. Don't fail because the system is underdetermined overall.

During replay, the system is re-attempted after *every* block — a newly stored definition may unstick previously stored constraints.

## Secondary Hotkeys

These commands remain as in the original plugin and are useful for explicit transformations the user requests:

| Command                                     | Recommended hotkey | Behavior |
|---------------------------------------------|--------------------|----------|
| Smart Solve LaTeX expression                | `Alt+B`    | The dispatch above. |
| Evaluate LaTeX expression                   | (unbound)  | Upstream evaluate (rightmost expression, simplify). |
| Evalf LaTeX expression                      | `Alt+F`    | Evaluate with `evalf`, output decimals. |
| Expand LaTeX expression                     | `Alt+E`    | Evaluate and expand result. |
| Factor LaTeX expression                     | (unbound)  | Evaluate and factor result. |
| Partial fraction decompose LaTeX expression | (unbound)  | Evaluate and PFD. |
| Solve LaTeX expression                      | `Alt+L`    | Original Solve, useful when user wants to pick which variable to solve for, or to solve `cases`/`align` systems. |
| Convert units in LaTeX expression           | `Alt+U`    | Unchanged. |
| Create truth table (Markdown / LaTeX)       | (unbound)  | Unchanged (two commands). |
| Convert LaTeX expression to Sympy           | (unbound)  | Unchanged. |

Smart Solve is the default; users reach for the others when they want a specific transformation.

## Rendering

### Storage vs. Display

- **Internal storage:** always symbolic (Sympy expression). `1/3` is stored as `Rational(1, 3)`, not `0.333`.
- **Display:** numeric scalars are rendered as decimals with configurable significant figures; non-numeric results (symbolic expressions, matrices, sets) are printed symbolically via the existing LaTeX printer.

This avoids precision loss: storing `x = 1/3` symbolically allows `3*x = 1` exactly. Storing `x = 0.333` would give `3*x = 0.999`.

### Decimal Rendering

Implemented in `smart_solve/Renderer.py`:

- Default: **3 significant figures**, configurable per document via the `lmat` block (`[render] sig_figs`). There is currently no global plugin setting for this.
- Invalid non-positive `sig_figs` values fall back to the default 3.
- Uses significant figures rather than decimal places. Magnitudes below `1e-4` or at/above `1e6` switch to scientific notation (`2.5 \times 10^{7}`), so very large and very small numbers stay compact.
- Trailing zeros are stripped (`1.50` → `1.5`).
- Exact rational/irrational scalars (`1/3`, `\sqrt{2}`) render as decimals; anything with free symbols falls through to the symbolic printer.

### Result Insertion

When Smart Solve produces a display result, it is inserted inline in the math block, after a **result marker**:

```latex
$$ x + 3 = 7 \Rightarrow x = 4 $$
```

- The insertion marker defaults to `\Rightarrow` and is configurable in plugin settings (1.5.3).
- A blank marker setting falls back to `\Rightarrow` (`resolveMarker`).
- **Detection is deliberately liberal** (`src/utils/ResultMarker.ts`): any of `\Rightarrow`, `\rightarrow`, `\to`, `\implies`, `\Longrightarrow`, `\longrightarrow`, `\Leftrightarrow`, `\iff` — with or without surrounding `\quad` padding — is recognized as an existing marker, regardless of the current setting. This keeps old notes (including the original `\quad \Rightarrow \quad` format) refreshable.
- On re-press: the existing marker is detected, everything after it is stripped, and the new result is inserted. Idempotent: pressing the hotkey twice produces the same final state.
- **Text suffixes are preserved** (1.5.8): a trailing run of `\text{...}` groups after the result (e.g. `\text{m/s}` or an inline comment) survives refreshes.
- The block's delimiter flavor (`$$...$$` vs inline `$...$`) is preserved when rewriting.
- Edits are applied back-to-front so earlier replacements don't shift later offsets; the cursor is restored to the end of the rewritten cursor-block.

### Refresh-Only Semantics (1.5.2)

Only the block under the cursor may receive a *new* marker. Every other block in the section is refresh-only:

- If it already has a marker, its result is recomputed and replaced.
- If it now produces no display result (e.g. it became a verified equality), the stale marker and result are stripped.
- If it never had a marker, it is left untouched — but it is still dispatched, because override warnings and contradiction errors only fire from the dispatcher.

A press with the cursor *outside* any math block refreshes the whole section without adding markers anywhere.

### Storage Without Display

Storage happens automatically as part of reconstructing context on every hotkey press. Blocks whose equations are stored as constraints (2+ free variables, system not yet uniquely determined) do not get inline annotations. They sit in the document as the user wrote them; any values the system *does* uniquely determine are announced via "Derived: …" toasts instead.

## Domain Setting

- **Default domain: complex** (`S.Complexes`), matching the upstream plugin's behavior. The original spec called for a global plugin setting with a `real` default; as built there is **no global plugin setting** — the domain is set per section via the `lmat` block (`[solve] domain = "Reals"`), and the unqualified default is complex.
- The `domain` value is any sympy set expression by name (`"Reals"`, `"Complexes"`, `"Naturals"`, …), shared with the explicit Solve command.

When a solve fails in the real domain but complex solutions exist, the error is accompanied by a hint toast:

- "No real solution exists. Complex solutions exist; set `[solve] domain = \"Complexes\"` in this document's `lmat` block."

## `lmat` Configuration Blocks

`lmat` code blocks retain their existing functionality (symbol assumptions, unit system, solve domain) and additionally:

- Act as **section dividers**, resetting the context after them.
- Can set per-section overrides for:
  - Domain (`[solve] domain = "Reals" | "Complexes" | ...`).
  - Significant figures (`[render] sig_figs = 3`).

Recognized TOML keys as built (`src/models/cas/LmatEnvironment.ts`): `[symbols]`, `[units] system`, `[solve] domain`, `[render] sig_figs`.

Example:
```lmat
[symbols]
x = ["real", "positive"]

[solve]
domain = "Complexes"

[render]
sig_figs = 4
```

## Error and Warning Handling

All non-result feedback is delivered via **Obsidian's `Notice` toasts**. The document text is never modified to display errors.

To keep document-wide refreshes usable, at most **5 toasts** are shown per press; any excess is collapsed into a single "...and N more notices" rollup. Every press also ends with a summary notice (`Re-evaluated 3/5 blocks — 1 error`). Error toasts stay up 8 s; others use the Obsidian default.

### Error categories (as-built messages)

| Category | Severity | Message |
|----------|----------|-----------------|
| Parse failure | Error | "Could not parse expression: `<details>`" |
| Multi-equation block | Error | "Multi-equation blocks are not yet supported by Smart Solve." |
| No solution exists | Error | "No solution exists for `x` in `<domain>`." (+ complex-solutions hint when applicable) |
| Solutions excluded by assumptions | Error | "No solution exists for `x` consistent with declared assumptions." |
| Contradiction (overconstrained) | Error | "Contradiction: `8` ≠ `10` [after substitution]." |
| Undefined variable | Error | "Undefined variable(s): `x`, `y`." |
| Evaluation/solve failure | Error | "Evaluation failed: `<details>`" / "Solve failed: `<details>`" |
| Multiple solutions | Warning | "Multiple solutions: `{-2, 2}`. Chose `2`." |
| Multiple stored values used | Warning | "Multiple stored values for `x`: `{-2, 2}`. Using `2` for this calculation." |
| Non-finite solution set | Warning | "Solution set: `<set>`" |
| Variable override | Info | "Overriding `x`: was `3`, now `4`." |
| Derived from constraints | Info | "Derived: `y` = `7`" |
| Symbolic result | Info | "Symbolic result (free parameters: `z`)." |

Note: Contradictions only fire when **no derivation is possible** (all variables already defined and the equation is false). When an equation contains a derivable variable, the plugin always overrides the old value rather than flagging a contradiction.

### Limits and interruption

- There is **no automatic solve timeout** (the spec's 3 s hard timeout was not implemented). Long-running evaluations surface in the Obsidian status bar after ~1 s as a clickable "evaluating" entry, from which all in-flight CAS commands can be interrupted manually (upstream mechanism).
- A re-press cancels the *editing* phase of the previous Smart Solve run (run-id check), though the CAS computation itself runs to completion or manual interruption.
- The spec's "20+ stored constraints" performance warning was not implemented.

## Performance Architecture

### Persistent Python Process

- Started eagerly on plugin load (bundled executable, or source + venv in developer mode).
- Communicates with the TypeScript side over a **local WebSocket connection** (the plugin passes a localhost port to `lmat-cas-client.py`), carrying JSON messages. *(The original spec said stdin/stdout; the upstream transport is a local socket.)*
- The LaTeX parser is [lark](https://github.com/lark-parser/lark)-based (upstream's grammar in `compiling/parsing/latex_math_grammar.lark`), not ANTLR; there is no warm-up parse at startup.

### Caching

- **Replay cache** (`ContextReplay.py`): a bounded LRU (32 entries) keyed on the tuple of prior-block LaTeX strings plus an environment signature. Re-pressing the hotkey with an unchanged section prefix hits the cache instead of re-replaying.
- **Per-run format cache** (`SmartSolveCommand.ts`): identical display results within one press are LaTeX-formatted only once.
- The spec's per-block parsed-expression cache (keyed on source hash) was not implemented; batch dispatch (one round-trip per press) reduced the need.

### Expected Latency Budget

Original targets, retained as guidance (not enforced by any timeout):

| Operation | Target |
|-----------|--------|
| Substitute + evaluate (cached) | < 50ms |
| Single-variable linear solve | 50–100ms |
| Quadratic solve | 70–150ms |
| 2–3 variable linear system | 80–200ms |
| Trig/transcendental solve | 150–500ms |
| Cold-start first hotkey | up to 1s (one time) |

## Implementation Status

The original implementation-order plan, with as-built status:

1. ✅ **Smart Solve dispatch (basic version).** Definitions via `=`, evaluation of expressions and trailing-`=` blocks, single-variable solving, `:=` definitions as context.
2. ✅ **Override semantics.** "Latest line wins"; info toast only on value change; contradiction check only when no free variables remain.
3. ✅ **Multi-solution handling.** Tiebreaker (largest magnitude, positive-real preference), warning toast listing all solutions. Extended in 1.5.7 with multi-value retention (all candidates kept until used).
4. ✅ **Section scoping.** `---`/`***`/`___`, headings, and `lmat` blocks divide sections.
5. ✅ **`%ref` skip.** Liberal comment matching (`%ref`, `% ref`, `% \text{ref}`).
6. ✅ **Constraint accumulation + system solving (permissive).** linsolve→nonlinsolve, partial materialization, constraint pruning, "Derived" toasts, symbolic fallback for expression evaluation (1.5.3).
7. ✅ **Rendering.** Significant figures + scientific notation; replace-not-append markers; configurable marker (1.5.3); text-suffix preservation (1.5.8); stale-result stripping.
8. 🟡 **Performance.** Replay LRU cache and batch section dispatch (1.5.8) implemented; no solve timeout; "computing" indicator is the upstream status-bar entry.
9. 🟡 **Per-document overrides via `lmat`.** `[solve] domain` and `[render] sig_figs` implemented; no global plugin settings for domain/precision.

Not implemented (deliberate gaps):

- Function definitions via plain `=` (`f(x) = x^2`) — blocks are skipped; `:=` is required.
- Multi-equation (`cases`/`align`) blocks under Smart Solve — rejected with an error; the explicit Solve command handles them.
- Global plugin settings for default domain and significant figures.
- Constraint-store size warning; automatic solve timeout.

## Design Requirements for Basis-Vector Notation

> [!NOTE]
> **Status:** implemented. Parser support lives in the shared grammar/transformer
> (`\ihat`/`\jhat`/`\khat` and `\hat{i|j|k|\imath|\jmath}` evaluate to `\mathbb{R}^3`
> basis vectors); Smart Solve provenance and basis-style rendering live in
> `smart_solve/Provenance.py`, `smart_solve/Renderer.py`, `smart_solve/Dispatcher.py`,
> and `smart_solve/ContextReplay.py`.

The goal of this extension is to let users define 3D Cartesian vectors by basis components directly in LaTeX, then use those values in subsequent Smart Solve blocks with standard vector operations, while preserving the notation family the user originally chose.

### Supported Input Forms

- The parser must accept **both** literal-hat and alias spellings for the Cartesian unit basis vectors.
- Required literal forms:
  - `\hat{i}`
  - `\hat{j}`
  - `\hat{k}`
  - `\hat{\imath}`
  - `\hat{\jmath}`
- Required alias forms:
  - `\ihat`
  - `\jhat`
  - `\khat`
- All supported spellings denote the same three built-in constants: the unit basis vectors of `\mathbb{R}^{3}`.
- These basis vectors are constants, not user-defined solve targets. They are not redefined via `:=`, `lmat`, or plain `=`.
- **Disambiguation.** Only `i`, `j`, `k`, `\imath`, `\jmath` *inside* `\hat{...}` denote basis vectors. `\hat{x}` (or any other `\hat{...}`) stays an ordinary formatted symbol, and a bare `i` stays the imaginary unit. There is no `\hat{\kmath}` form, because LaTeX has no dotless-k; `\hat{k}` is the only literal `k` spelling.
- Basis-vector support is **value-driven**, not name-driven. A symbol becomes vector-valued because of the expression assigned to it, not because its name is formatted in any special way. For example, `v = 2\ihat + \jhat` and `\vec v = 2\ihat + \jhat` both define vector-valued symbols under the repo's existing symbol-identity rules.

### Semantic Model

- Internally, basis vectors must participate in the existing matrix/vector pipeline rather than introducing a second vector algebra system.
- A basis vector evaluates to a 3-component vector value compatible with the current matrix-based operations already used by Evaluate and Smart Solve.
- Any expression whose evaluated value depends on one or more basis vectors is vector-valued.
- Any symbol defined from such an expression becomes a stored vector definition for downstream Smart Solve replay.
- Vector-ness is a property of the **evaluated value**, not a property inferred from a symbol's spelling.
- The first version of this extension targets **3D Cartesian basis notation only**. It does not introduce arbitrary symbolic bases, coordinate-system transforms, higher-dimensional basis families, or tensor notation.

### Required Math Surface

Once basis vectors are recognized, they must work with the same vector operations that already work for matrix-valued vectors in the current CAS surface.

- Required in-scope operations:
  - vector addition and subtraction
  - scalar multiplication
  - cross product
  - inner product / dot-product surface already supported by the plugin
  - norm / magnitude
  - unit-vector normalization
- Existing matrix-style vectors and matrix-style vector operations must continue to work unchanged.
- This extension must be additive: users may continue to write vectors as `bmatrix` / `pmatrix` / `array` values, and those forms remain valid.
- Whether `\cdot` itself should be reinterpreted as a vector dot-product shorthand is **not** required for the first version. The extension only needs to support the vector-operation surfaces the repo already exposes.

### Smart Solve Scope

Smart Solve is the primary feature target for this extension.

- A direct definition such as `v = 2\ihat - 3\jhat + 4\khat` must store `v` as a vector-valued definition and display the result inline.
- A later evaluation such as `v =` must substitute the stored vector value and display it using `v`'s recorded notation provenance (see below).
- Expressions such as `v + \ihat =`, `u \times v =`, `\lVert v \rVert =`, and equivalent already-supported vector surfaces must evaluate using stored vector values.
- Verification of fully concrete vector equalities must be supported in the same way scalar verification is supported now: silent if true, contradiction notice if false.
- Vector definitions must participate in context replay exactly like scalar definitions: re-pressing Smart Solve rebuilds the same vector state from document text, with no hidden mutable session state.
- Section scoping rules remain unchanged: vector definitions are still local to the current Smart Solve section.

### Out-of-Scope Solving Behavior

This extension does **not** require Smart Solve to become a general vector-equation solver.

- Still out of scope for the first version:
  - `2v = b`
  - `M v = b`
  - systems whose unknowns are vectors or matrices
  - constraint accumulation over vector unknowns
- Direct isolated assignment remains the supported vector-definition path for Smart Solve.
- When the current block is a matrix/vector equation that is not a direct isolated assignment, Smart Solve should keep failing explicitly rather than attempting partial, heuristic, or guessed behavior.

### Rendering Provenance Requirements

The user's formatting choice is a first-class part of the feature.

- Smart Solve must **not** render every 3D vector in basis notation unconditionally.
- Each stored vector definition carries notation provenance describing how that symbol was originally defined.
- At minimum, the renderer distinguishes these provenance families:
  - **hat family**: `\hat{i}` / `\hat{\imath}` / `\hat{j}` / `\hat{\jmath}` / `\hat{k}`
  - **alias family**: `\ihat`, `\jhat`, `\khat`
  - **matrix family**: `bmatrix`, `pmatrix`, `array`, and other existing matrix-style vector inputs
- When Smart Solve later displays the value of a stored symbol, it must use that symbol's recorded family rather than inspecting only the numeric value.
- Required round-trip behavior:
  - a vector first defined with aliases renders back in alias notation
  - a vector first defined with literal hats renders back in hat notation
  - a vector first defined as a matrix renders back as a matrix
- Whitespace and brace trivia do not need to round-trip exactly, but the **visible notation family** must round-trip.
- Provenance is section-local Smart Solve state and must survive replay, cache hits, and cloning exactly as definitions do, so re-pressing the hotkey reconstructs the same display style deterministically.

### Provenance Propagation Rules

The renderer needs deterministic behavior for derived values.

- A symbol defined directly from a basis-style expression inherits the notation family of its **defining block**.
- A symbol defined directly from a matrix-style expression inherits matrix provenance from its defining block.
- If a definition block mixes incompatible style families, the resulting stored symbol must fall back to matrix provenance rather than guessing.
- If an evaluated expression has no single stable provenance family, Smart Solve must prefer matrix output over basis output.
- Alias-family and hat-family basis notation count as distinct provenance families for round-tripping purposes. Using `\ihat` does **not** authorize the renderer to silently switch to `\hat{i}`, and vice versa.
- If exact lexical preservation inside the hat family (`\hat{i}` vs `\hat{\imath}`, `\hat{j}` vs `\hat{\jmath}`) is infeasible, the implementation may canonicalize **within** the hat family, but alias-vs-hat family preservation is mandatory.

#### Family Computation (operational rule)

The above rules are made concrete by a single deterministic computation, shared by the live dispatcher and by context replay so both agree on every press:

1. Collect the set of **contributing families** for the block:
   - `alias` — the block contains a `\ihat` / `\jhat` / `\khat` token.
   - `hat` — the block contains a `\hat{i|j|k|\imath|\jmath}` token.
   - `matrix` — the block contains a matrix environment (`bmatrix` / `pmatrix` / `array` / …).
   - plus the **recorded family of every already-defined vector symbol the block references** (looked up from the section's definitions).
2. Resolve the set to one family:
   - if it contains `matrix`, **or** contains both `alias` and `hat` → `matrix`;
   - if it contains exactly one basis family (`alias` xor `hat`) → that family;
   - if it contains no vector families → the value is not basis-rendered (matrix fallback if it is nonetheless a vector).
3. For a **definition** (`target = …`), the target symbol's own *prior* family is **not** a contributor — the defining block's notation wins, so redefining a matrix-provenance symbol with a basis expression switches it to the basis family.

Scalar results (dot product, norm, determinant, …) carry no basis family and always use the scalar renderer.

#### Implementation choices permitted by the rules above

- **Hat canonicalization:** within the hat family the renderer emits `\hat{i}`, `\hat{j}`, `\hat{k}`. So `\hat{\imath}` / `\hat{\jmath}` round-trip to `\hat{i}` / `\hat{j}` (family preserved, exact spelling canonicalized — explicitly allowed above).
- **Matrix family:** rendered as the renderer's default matrix form; the specific input delimiter (`bmatrix` vs `pmatrix` vs `array`) is not preserved, only the matrix *family*.

### Basis-Style Output Rules

When Smart Solve chooses basis-style output, the emitted form must be deterministic.

- Basis-style rendering applies only to 3-component vectors.
- Non-3D vectors always fall back to matrix rendering.
- Terms are emitted in `i`, `j`, `k` order.
- Zero components are omitted.
- The zero vector renders as `0` rather than an expanded `0\ihat + 0\jhat + 0\khat` form.
- Coefficients reuse the existing scalar renderer (fractions, signs, scientific notation, etc.).
- Coefficient `1` is omitted where natural (`\ihat`, not `1\ihat`); coefficient `-1` renders as `-\ihat`.

### Command-Surface Requirements

- Smart Solve is the only surface that is required to preserve basis-vs-matrix provenance in this first version.
- Other commands may continue to emit matrix-form outputs unless explicitly extended later.
- Parser support for basis vectors is shared infrastructure, so Evaluate / Solve / Convert to Sympy may consume the syntax, but provenance-preserving output is not a requirement outside Smart Solve initial scope.

### Compatibility Requirements

- Existing `\hat{x}`, `\vec v`, `\vectorarrow`, `\vectorbold`, matrix environments, and other formatted-symbol paths must continue to parse as they do now.
- Adding `\ihat`, `\jhat`, and `\khat` support must not break generic formatted-symbol parsing or existing physics-package commands.
- Existing notes that use matrix notation for vectors must keep producing matrix outputs.
- Existing Smart Solve matrix/vector assignment behavior remains valid; this extension only adds an alternate input and display family.

### Acceptance Examples

The following examples define the required observable behavior.

- **Alias round-trip**
  - input block: `u = 2\ihat + 3\jhat - \khat`
  - later block: `u =`
  - required Smart Solve display: `2\ihat + 3\jhat - \khat`
- **Literal-hat round-trip**
  - input block: `v = \hat{i} - 2\hat{k}`
  - later block: `v =`
  - required Smart Solve display: `\hat{i} - 2\hat{k}`
- **Matrix round-trip**
  - input block: `w = \begin{bmatrix}1 \\ 2 \\ 3\end{bmatrix}`
  - later block: `w =`
  - required Smart Solve display: matrix notation, not basis notation
- **Mixed-style fallback**
  - input block: `x = u + \begin{bmatrix}1 \\ 0 \\ 0\end{bmatrix}`
  - later block: `x =`
  - required Smart Solve display: matrix notation, because the defining block mixed provenance families
- **Vector math support**
  - input block: `a = \ihat`
  - input block: `b = \jhat`
  - later block: `a \times b =`
  - required Smart Solve display: a basis-style vector equal to `\khat` if the block's provenance is unambiguous; otherwise matrix fallback is acceptable only where provenance is mixed or absent

## Design Requirements for `lmat:ignore` HTML Comment Marker

> [!NOTE]
> **Status:** implemented. Because the marker lives in the Markdown *around* the
> math block (not in the LaTeX source the CAS sees), detection is entirely
> TypeScript-side: `src/utils/IgnoreMarker.ts` recognizes the marker, the math-block
> scanners (`MathBlockIterator`, `EquationExtractor`) tag each block with an
> `ignored` flag, explicit commands abort on an ignored block, and Smart Solve
> *excludes ignored blocks from the section it sends to Python* — so they are
> omitted from replay without any CAS-side change. This is a cleaner realization
> of the "detect before parsing / never reaches the CAS" requirement than a
> Python-side check would be: an ignored block is simply never sent.

The goal of `<!-- lmat:ignore -->` is to let users keep LaTeX visible and normally rendered in the note while opting that math block out of **all** LaTeX Math evaluation surfaces.

Unlike `%ref`, which is a Smart Solve-local documentation marker, `<!-- lmat:ignore -->` is a plugin-wide **do not evaluate** marker.

### Primary Use Case

- A user has math in the note that should render as math but should never be treated as command input by LaTeX Math.
- The marker itself must not render in the note.
- The user must be able to finish the math segment and keep writing normal Markdown text on the same source line.
- The opt-out should apply consistently across Smart Solve and every explicit command.

### Syntax and Placement

- The recognized marker is the HTML comment `<!-- lmat:ignore -->`.
- Detection should be case-insensitive for the `lmat:ignore` payload.
- Surrounding whitespace inside the comment may be normalized, so forms such as `<!--lmat:ignore-->` and `<!--  lmat:ignore  -->` may be accepted if implementation simplicity requires it.
- Only the exact plugin-specific payload `lmat:ignore` is special. Unrelated HTML comments are not markers.
- The marker lives **outside** the math source, not inside the LaTeX expression.

Recommended placements:

- **Inline math / single-line math:** place the marker immediately before the math block.
  - example: `<!-- lmat:ignore --> $x + y$ and then normal text continues here.`
- **Display math:** place the marker immediately before the display block.
  - example:
    ```markdown
    <!-- lmat:ignore -->
    $$
    x + y
    $$
    ```

Placement rules:

- The marker applies to the **next** math block in source order.
- The marker should only bind when it is adjacent to the next math block, allowing at most whitespace between the comment and the math opener.
- Ordinary prose between the marker and the next math block breaks the association.
- The marker is invisible in rendered Markdown because it is an HTML comment.
- This HTML-comment design replaces the earlier `%ignore` idea because TeX comments consume the rest of the source line and make same-line trailing text awkward or impossible.

### Semantic Meaning

- A math block preceded by `<!-- lmat:ignore -->` is considered **non-evaluable plugin content**.
- Such a block must:
  - render normally as math in the note,
  - participate in no command evaluation,
  - produce no CAS request,
  - produce no definitions,
  - accumulate no Smart Solve constraints,
  - contribute no derived values,
  - produce no inserted evaluation result.

The meaning is block-level, not substring-level.

- If the current math block is bound to `<!-- lmat:ignore -->`, then selecting only part of that block does **not** bypass the ignore rule.
- For selection-capable commands, the block remains ignored even when the selected text itself does not include the marker.

### Command-Surface Requirements

`<!-- lmat:ignore -->` applies to **all** LaTeX Math commands.

- Evaluate / Evalf / Expand / Factor / Partial fraction decompose
- Solve
- Convert units
- Create truth table (Markdown / LaTeX)
- Convert LaTeX to Sympy
- Smart Solve

Behavior for explicit single-block commands:

- If the target block is marked by `<!-- lmat:ignore -->`, the command aborts without contacting the CAS.
- The command shows a user-facing notice explaining that the block is marked `lmat:ignore` and will not be evaluated.
- The command does not modify the note.

Behavior for Smart Solve:

- `lmat:ignore` blocks are omitted from section replay.
- `lmat:ignore` blocks do not contribute definitions or constraints to later blocks in the section.
- `lmat:ignore` blocks do not receive new inline results.
- If the cursor is inside an ignored block and Smart Solve is invoked, the command does not evaluate that block.
- Smart Solve may show a single informational notice when the cursor block itself is ignored, but ignored blocks elsewhere in the section should be skipped silently to avoid noise.

### Interaction with Existing Results

Ignored blocks may already contain stale LaTeX Math output from before the marker was added.

- When Smart Solve refreshes a section, an ignored block with an existing Smart Solve result marker should have that plugin-owned result stripped.
- The source expression and `<!-- lmat:ignore -->` marker remain.
- Explicit commands never rewrite ignored blocks.

This keeps `lmat:ignore` authoritative: once a block is marked ignored, the plugin stops owning any output inside it.

### Interaction with `%ref`

`%ref` and `lmat:ignore` serve different purposes:

- `%ref` means: Smart Solve documentation-only block, ignored by Smart Solve replay.
- `lmat:ignore` means: plugin-wide non-evaluable block, ignored by every command.

Precedence rule:

- If a block is both `%ref`-marked and preceded by `<!-- lmat:ignore -->`, `lmat:ignore` wins.

Rationale:

- `lmat:ignore` is the stronger, broader opt-out and should produce one consistent block policy across the entire plugin.

### Detection Order

Detection should happen on the raw math-block source before normal command parsing.

- For Smart Solve, `lmat:ignore` detection happens before result-marker stripping, expression parsing, replay classification, or `%ref` handling.
- For explicit commands, `lmat:ignore` detection happens before extracting evaluable input for the CAS.
- A `lmat:ignore` block is therefore rejected/skipped even if the mathematical expression itself would otherwise parse successfully.

### Summary and Counting Semantics

Smart Solve summaries should not treat ignored blocks as runnable work.

- Ignored blocks are excluded from the set of blocks considered for evaluation.
- The summary count should reflect only non-ignored runnable blocks.
- Skipped ignored blocks should not inflate error counts.

### Acceptance Examples

- **Inline opt-out**
  - source: `<!-- lmat:ignore --> $x + y$ and then normal text continues here.`
  - expected behavior: renders as math; no LaTeX Math command evaluates it.
- **Display opt-out with leading HTML comment**
  - source:
    ```markdown
    <!-- lmat:ignore -->
    $$
    x^2 + y^2 = z^2
    $$
    ```
  - expected behavior: the equation renders normally; the plugin skips it.
- **Block-level enforcement for selection commands**
  - source: `<!-- lmat:ignore --> $x + y$`
  - action: select only `x + y` and run Evaluate
  - expected behavior: command still refuses to evaluate, because the containing math block is ignored.
- **Smart Solve replay exclusion**
  - block 1: `<!-- lmat:ignore --> $x = 3$`
  - block 2: `x + 1 =`
  - expected behavior: block 1 contributes no definition; block 2 behaves as if `x` were undefined.
- **`lmat:ignore` precedence over `%ref`**
  - source: `<!-- lmat:ignore --> $E = mc^2 %ref$`
  - expected behavior: all commands treat the block as ignored, not merely Smart Solve-reference-only.

## Open Questions for Later Versions

These are deliberately deferred:

- **Inheritance from a "globals" section.** Currently global constants must be redefined per section. Could add a special section name (e.g., `# Constants`) whose contents are inherited.
- **Cross-section references.** Currently impossible. Could add an `\import{x from "Section 1"}` syntax.
- **Symbolic display mode.** Numeric scalars always render as decimals; a per-block or per-document toggle for exact symbolic display could be added. (Symbolic *results* — expressions with free parameters — already display symbolically.)
- **Calctex-style synchronous evaluation.** Currently hotkey-triggered only. Could add live evaluation as user types, gated by a setting.
- **Auto-conversion of `=` to `:=` in input.** Largely obsolete: Smart Solve gives `=` definition semantics directly. `:=` remains for explicit definitions and functions.
- **Function definitions via `=`.** The dispatcher has the hook; needs definition-store plumbing.
- **Smart Solve for multi-equation blocks.** Could route `cases`/`align` systems into the constraint store wholesale.

## Compatibility with Upstream

This fork preserves all existing LaTeX Math functionality. Specifically:

- All upstream commands continue to work (Evaluate, Evalf, Expand, Factor, Partial fraction decompose, Solve, Convert units, Truth tables, Convert to Sympy).
- `:=` continues to be the explicit definition operator, and remains the only way to define functions.
- `lmat` blocks retain their existing semantics (`[symbols]`, `[units] system`, `[solve] domain`), extended with `[render] sig_figs` and the section-divider role.
- Existing user documents continue to work without modification.

The new behavior is additive: Smart Solve is a new command (`smart-solve-latex-expression`) plus two new CAS message types (`smart-solve`, `smart-solve-section`). Users who don't bind or use it see no behavioral change. The fork ships under its own plugin id (`latex-math-smart-solve`), so it can be installed side-by-side with the original.
