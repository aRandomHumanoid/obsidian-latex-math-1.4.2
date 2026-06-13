# LaTeX Math Docs

## [Commands](COMMANDS.md)

**LaTeX Math** provides its main functionality through a series of Obsidian commands.

This section of the documentation goes through each command in detail — including this fork's [Smart Solve](COMMANDS.md#smart-solve-latex-expression) command, which dispatches each math block in the current section to define, solve, verify, or evaluate based on its structure.

For the full Smart Solve design (dispatch algorithm, tiebreaker rules, constraint accumulation), see [design_docs.md](../design_docs.md) in the repository root.

## [LaTeX Syntax (how to write LaTeX the plugin understands)](SYNTAX.md)

The parser is designed to parse most naturally written LaTeX.

Still, LaTeX is very flexible, and the same visual output can be produced in many different ways.

This section outlines how the parser expects the input to be written.

### [Constants](SYNTAX.md#mathematical-constants)

List of mathematical constants supported by this plugin.

### [Functions](SYNTAX.md#mathematical-functions)

List of mathematical functions supported by this plugin.

### [Units](SYNTAX.md#supported-units)

List of units supported by this plugin.

### [Physical Constants](SYNTAX.md#supported-physical-constants)

List of built-in physical constants.

## [LaTeX Math (`lmat`) Environments](LMAT_ENV.md)

The **LaTeX Math** environment configures section-scoped symbol assumptions, unit systems, solve domains, and Smart Solve numeric rendering.

It also resets location-based definitions, and for Smart Solve it acts as a section divider that resets implicit definitions and constraints for the section that follows.

This section provides an overview of the purpose of **LaTeX Math** environments and how to use the `lmat` code block.

## [Contributing](CONTRIBUTING.md)

This section covers setting up a development environment, as well as a quick overview of how to contribute to this plugin.
