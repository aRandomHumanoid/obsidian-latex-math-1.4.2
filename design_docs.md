# LaTeX Math Fork — Design Specification

A fork of the [obsidian-latex-math](https://github.com/zarstensen/obsidian-latex-math) plugin that consolidates evaluation and solving into a single "smart" hotkey with notebook-style implicit variable management and section-scoped namespaces.

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
- **Domain:** the solution domain (real or complex), settable via global default and per-document override.
- **Render settings:** decimal places for numeric output, etc.

The context is **reconstructed on every hotkey press** by walking the document from the most recent section divider down to the cursor. There is no persistent in-memory model between hotkey presses.

### Section Scopes

The document is divided into **sections**. Each section has its own independent context. Variables, definitions, and constraints in one section do not affect any other section.

A section ends and a new one begins at any of:

- A markdown horizontal rule: `---`
- A markdown heading (any level): `# Heading`, `## Subheading`, etc.
- An `lmat` configuration code block

**Global constants** can be defined in a dedicated section at the top of the document (before any section divider) — they are *not* automatically inherited by other sections. To share values across sections, the user must explicitly redefine them.

(Future extension: a `# Constants` or similar named section whose contents are inherited by all other sections. Not in v1.)

### Reference Equations

A math block tagged with `%ref` (a LaTeX comment) is treated as pure documentation. The plugin ignores it entirely: no evaluation, no storage, no participation in the constraint system.

Example:
```latex
$$ E = mc^2 \quad \% \text{ref} $$
```

## The Smart Solve Hotkey

The primary hotkey (default `Alt+B`, configurable) is called **Smart Solve**. When pressed inside a math block, it performs the following dispatch:

### Dispatch Algorithm

The dispatch always tries to **derive new values** from each equation, ignoring prior definitions of the variable(s) being solved for. This implements "the most recent value wins" semantics: a later block can freely override earlier definitions, as long as it produces an unambiguous derivation.

Contradictions are only flagged when every symbol in the equation is already defined and substitution yields a false statement — i.e., when there's no variable left to be redefined.

```
INPUT: current math block B, accumulated context C (built by walking the section)

Step 0: If B contains "%ref", return NO_OP.

Step 1: If B uses ":=":
  - If LHS is a symbol or function application, store as definition.
  - Else, error: "Invalid := target".

Step 2: If B contains "=" and LHS matches function-application pattern "name(args)":
  - Store as a function definition.

Step 3: Identify the target variable(s) for derivation.
  syntactic_vars = all symbols appearing in B
  target_vars    = syntactic_vars (treated as free, even if previously defined)
  
  For symbols in syntactic_vars that are NOT being targeted (see Step 4 cases),
  substitute their definitions from C.

Step 4: If B contains "=":

  4a: If len(syntactic_vars) == 0:
      - Both sides are concrete. Verification check.
      - If LHS == RHS: return VERIFIED (silent or subtle indicator).
      - Else: error toast "Contradiction: {LHS} ≠ {RHS}".

  4b: If len(syntactic_vars) == 1:
      - One variable in the equation. Treat as the derivation target.
      - Solve B for that variable in C.domain.
      - 0 solutions: error "No solution exists in {domain}".
        (If complex solutions exist but domain is real, mention this.)
      - 1 solution: store as definition (overriding if already defined).
        - If prior value existed and differed: info toast "Overriding x: was 3, now 4".
        - If prior value existed and matched: silent (no-op override).
      - 2+ solutions:
        - If prior value existed and matches one solution: keep prior value, silent.
        - Else: pick by tiebreaker, store, warn via toast listing all solutions.

  4c: If len(syntactic_vars) >= 2:
      - Substitute known definitions from C for all symbols that ARE defined.
      - Let remaining_vars = symbols in B after substitution.
      
      - If len(remaining_vars) == 0:
          - All symbols were defined; substitution yielded a concrete statement.
          - If LHS == RHS: VERIFIED.
          - Else: error "Contradiction: {substituted LHS} ≠ {substituted RHS}".
            (Document the contradiction; the user has overconstrained the system.)
      
      - If len(remaining_vars) == 1:
          - One variable left after substitution. Solve for it.
          - Same handling as case 4b for the single remaining variable.
      
      - If len(remaining_vars) >= 2:
          - Attempt to solve the accumulated system (C.constraints + [B substituted])
            for all remaining variables.
          - For each variable uniquely determined by the system: materialize it as
            a definition (permissive partial solving).
          - For variables that remain underdetermined: leave them free; the
            substituted equation becomes a new constraint in C.

Step 5: If B contains no "=":
  - Substitute all known definitions from C into B, yielding B'.
  - Evaluate B' as an expression.
  - If well-defined: print result inline.
  - Else: error toast.
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

When an equation has multiple valid solutions, the plugin picks one and stores it.

Selection rule, in order:

1. **Match prior value if possible.** If the variable was previously defined and one of the new solutions equals the prior value, keep the prior value. No override, no toast — the equation is consistent with what we already had.

2. **Largest magnitude.** Otherwise, sort solutions by `abs(solution)`, descending.

3. **Tiebreaker for equal magnitudes:** positive real > negative real > complex.

4. **Final tiebreaker:** arbitrary (first in Sympy's natural ordering).

When a choice was made among multiple solutions (rules 2–4), emit a warning toast listing all solutions and which was chosen.

Examples:

- `x^2 = 4` with no prior `x` → solutions `{-2, 2}` → equal magnitudes → positive real → stored as `x = 2`. Warning toast.
- `x^2 = 9` with `x := -3` defined → solutions `{-3, 3}` → `-3` matches prior → keep `x = -3`. Silent.
- `x^2 = 9` with `x := 7` defined → solutions `{-3, 3}` → no match → largest magnitude tied → positive real → store `x = 3`. Override toast + multi-solution warning.

### Override Behavior Details

- **Single-solution derivation matches prior value:** silent no-op.
- **Single-solution derivation differs from prior value:** info toast "Overriding x: was 3, now 4".
- **Multi-solution derivation, one matches prior value:** silent, keep prior.
- **Multi-solution derivation, none matches prior value:** override toast + multi-solution warning toast.
- **Fresh assignment (variable had no prior value):** silent storage.

### Permissive Partial-System Solving

When a block introduces a new constraint and the accumulated system has more equations than before, the plugin attempts to derive as many variable values as possible:

```
system = C.constraints ∪ {current_block}
solution = solve(system, all_free_vars)

for var in all_free_vars:
    if solution[var] is a concrete value (no free parameters):
        store as definition in C
        remove related constraints from C.constraints
    else:
        leave as constraint
```

If the system uniquely determines some but not all variables, materialize the determined ones and leave the rest. Don't fail because the system is underdetermined overall.

## Secondary Hotkeys

These commands remain as in the original plugin and are useful for explicit transformations the user requests:

| Command                                     | Hotkey     | Behavior |
|---------------------------------------------|------------|----------|
| Smart Solve                                 | `Alt+B`    | The new dispatch above. |
| Force decimal evaluation                    | `Alt+F`    | Evaluate with `evalf`, output decimals. |
| Expand                                      | `Alt+E`    | Evaluate and expand result. |
| Factor                                      | (unbound)  | Evaluate and factor result. |
| Partial fraction decompose                  | (unbound)  | Evaluate and PFD. |
| Solve (explicit, with variable choice)      | `Alt+L`    | Original Solve, useful when user wants to pick which variable to solve for. |
| Convert units                               | `Alt+U`    | Unchanged. |
| Truth table                                 | (unbound)  | Unchanged. |
| Convert to Sympy                            | (unbound)  | Unchanged. |

Smart Solve is the default; users reach for the others when they want a specific transformation.

## Rendering

### Storage vs. Display

- **Internal storage:** always symbolic (Sympy expression). `1/3` is stored as `Rational(1, 3)`, not `0.333`.
- **Display:** rendered as a decimal with configurable significant figures.

This avoids precision loss: storing `x = 1/3` symbolically allows `3*x = 1` exactly. Storing `x = 0.333` would give `3*x = 0.999`.

### Decimal Rendering

- Default: **3 significant figures**, configurable via:
  - Global plugin setting.
  - Per-document override via `lmat` block.
- Uses significant figures rather than decimal places, so:
  - Very large numbers render in scientific notation when appropriate.
  - Very small numbers also render in scientific notation rather than `0.000`.
- Exact rational outputs (`1/3`, `\sqrt{2}`): rendered as decimals by default, matching the consistent display style. (Users wanting symbolic display can use a separate hotkey or setting in a future version.)

### Result Insertion

When Smart Solve produces a result to display, the plugin inserts it inline in the math block. The format consistently terminates with a recognizable marker so subsequent hotkey presses can **replace** the existing result rather than appending a duplicate.

Example format:
```latex
$$ x + 3 = 7 \quad \Rightarrow \quad x = 4 $$
```

On re-press: detect the `\quad \Rightarrow \quad` marker, strip everything after it, and re-insert the new result. Idempotent: pressing the hotkey twice produces the same final state.

### Storage Without Display

Per the design, storage happens automatically as part of reconstructing context on every hotkey press. The hotkey press displays results only when:

1. The block has a solution that can be displayed (single-variable solve, evaluation of a fully-substituted expression).
2. The user actively pressed the hotkey on this block.

Blocks with stored constraints (2+ free variables, system not yet uniquely determined) do not get inline annotations. They sit in the document as the user wrote them.

## Domain Setting

- **Global plugin setting:** default domain (`real` or `complex`). Default: `real`.
- **Per-document override:** via `lmat` block with `[solve] domain = "complex"` or similar TOML key. Persists for the rest of the section (until next section divider).

When a solve fails in the real domain but would succeed in complex:

- Error toast: "No real solution exists. Complex solutions exist; enable complex mode in plugin settings or this document's `lmat` block."

## `lmat` Configuration Blocks

`lmat` code blocks retain their existing functionality (symbol assumptions, solve domain) and additionally:

- Act as **section dividers**, resetting the context after them.
- Can set per-document overrides for:
  - Domain (`[solve] domain = "real" | "complex"`).
  - Decimal precision (`[render] sig_figs = 3`).
  - Other rendering preferences.

Example:
```lmat
[symbols]
x = ["real", "positive"]

[solve]
domain = "complex"

[render]
sig_figs = 4
```

## Error and Warning Handling

All non-result feedback is delivered via **Obsidian's `Notice` toasts**. The document text is never modified to display errors.

### Error categories

| Category | Severity | Example message |
|----------|----------|-----------------|
| No solution exists | Error | "No solution exists for `x` in real domain." |
| Contradiction (overconstrained) | Error | "Contradiction: `8 = 10`. All variables in this equation are already defined." |
| Undefined variable | Error | "`x` is not defined and cannot be derived from stored constraints." |
| Sympy failure | Error | "Could not parse or evaluate: `<details>`." |
| Multiple solutions | Warning | "Multiple solutions: `x ∈ {-2, 2}`. Stored `x = 2`." |
| Variable override | Info | "Overriding `x`: was `3`, now `4`." |
| Large constraint store | Info | "Section has 20+ stored constraints; performance may degrade. Consider adding a section divider." |

Note: Contradictions only fire when **no derivation is possible** (all variables already defined and the equation is false). When an equation contains a derivable variable, the plugin always overrides the old value rather than flagging a contradiction.

### Warning thresholds

- Constraint store size > 20: emit performance warning toast on next hotkey press.
- Solve timeout (configurable, default 3 seconds): abort and emit error.

## Performance Architecture

### Persistent Python Process

- Started eagerly on plugin load.
- A warm-up parse runs at startup (`parse_latex("1+1")`) to JIT-prime ANTLR.
- Communicates via stdin/stdout JSON, same as upstream LaTeX Math.

### Caching

- **Parsed expression cache:** keyed on LaTeX source hash. Reused across hotkey presses if a block's source is unchanged.
- **Context cache:** the accumulated context for a section is rebuilt incrementally — if blocks 1–7 are unchanged and the user presses the hotkey on block 8, blocks 1–7 are read from cache.

### Timeouts and Cancellation

- Each query to the Python backend has a configurable timeout (default 3s).
- If the user triggers a new query while one is in flight, the older query is canceled.
- A "computing…" indicator appears for queries taking >300ms.

## Expected Latency Budget

| Operation | Target |
|-----------|--------|
| Substitute + evaluate (cached) | < 50ms |
| Single-variable linear solve | 50–100ms |
| Quadratic solve | 70–150ms |
| 2–3 variable linear system | 80–200ms |
| Trig/transcendental solve | 150–500ms |
| Cold-start first hotkey | up to 1s (one time) |
| Hard timeout | 3s |

## Implementation Order

Build in this order to minimize integration pain and enable testing at each stage:

1. **Smart Solve dispatch (basic version).** Single hotkey that handles:
   - Definition via `=` (single-symbol equations, fresh assignments).
   - Evaluation of expressions and trailing-`=` blocks.
   - Solving single-variable equations (where the variable may or may not have a prior value).
   - No constraint accumulation yet — fail with clear error on 2+ remaining-free vars after substitution.
   - Use existing `:=` definitions as context.

2. **Override semantics.** Implement the "latest line wins" derivation:
   - Single-solution overrides emit info toast only when the value changes.
   - Multi-solution prefer-prior-value rule.
   - Contradiction check only fires when no free variables remain.

3. **Multi-solution handling.** Tiebreaker logic (largest magnitude, positive real preference), warning toast listing all solutions.

4. **Section scoping.** Implement `---`, headers, and `lmat` blocks as section dividers. Verify context resets correctly.

5. **`%ref` skip.** Add the documentation-only block tag.

6. **Constraint accumulation + system solving (Option C, permissive).** This is the largest single feature. Add stored constraints to context, attempt system solving on every block, materialize uniquely determined variables.

7. **Rendering: significant figures, replace-not-append result insertion.**

8. **Performance: caching, timeouts, "computing…" indicator.**

9. **Per-document overrides via `lmat`: domain, decimal precision.**

Each step is independently testable. Steps 1–3 cover the core "smart hotkey" experience; steps 4–5 add the multi-section structure; step 6 enables multi-equation systems; steps 7–9 add polish and power.

## Open Questions for Later Versions

These are deliberately deferred:

- **Inheritance from a "globals" section.** Currently global constants must be redefined per section. Could add a special section name (e.g., `# Constants`) whose contents are inherited.
- **Cross-section references.** Currently impossible. Could add an `\import{x from "Section 1"}` syntax.
- **Symbolic display mode.** Currently everything renders as decimal. Could add a toggle for symbolic display per block or per document.
- **Calctex-style synchronous evaluation.** Currently hotkey-triggered only. Could add live evaluation as user types, gated by a setting.
- **Auto-conversion of `=` to `:=` in input.** Currently the user must type `:=` for explicit definitions, or use a LaTeX Suite snippet. Could be built into the plugin itself.

## Compatibility with Upstream

This fork preserves all existing LaTeX Math functionality. Specifically:

- All current commands continue to work (Evaluate, Solve, Expand, Factor, etc.).
- `:=` continues to be the explicit definition operator (Smart Solve uses it via Step 1 of dispatch).
- `lmat` blocks retain their existing semantics, extended with new keys for rendering and section dividing.
- Existing user documents continue to work without modification.

The new behavior is additive: Smart Solve is a new command with a new hotkey. Users who don't bind or use `Alt+B` see no behavioral change.

This makes the fork potentially mergeable upstream, or at minimum runnable side-by-side with the original for users who want both.
