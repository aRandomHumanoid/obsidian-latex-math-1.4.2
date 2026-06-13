// The `<!-- lmat:ignore -->` HTML comment marker (design_docs.md §"Design
// Requirements for `lmat:ignore` HTML Comment Marker").
//
// Placed immediately before a math block, it opts that block out of ALL LaTeX
// Math evaluation surfaces while keeping the LaTeX visible and normally rendered
// (an HTML comment is invisible in rendered Markdown). It is plugin-wide, unlike
// the Smart Solve-local `%ref`.
//
// The marker lives in the Markdown around the math block, never inside the LaTeX
// source, so it is recognized here on the TypeScript side and never reaches the
// CAS.

// The payload is case-insensitive; internal whitespace is tolerated so
// `<!--lmat:ignore-->` and `<!--  lmat:ignore  -->` both work.
const IGNORE_MARKER = /<!--\s*lmat:ignore\s*-->/i;

// The marker binds to the *next* math block only when adjacent — at most
// whitespace may sit between the marker and the block opener. Anchored at the
// end so ordinary prose between the marker and the block breaks the association.
const IGNORE_MARKER_BEFORE_BLOCK = /<!--\s*lmat:ignore\s*-->\s*$/i;

// Longest possible marker plus a generous whitespace allowance; bounds how far
// back callers need to look before a block opener.
export const IGNORE_MARKER_LOOKBACK = 256;

// User-facing notice shown when a command is invoked on an ignored block.
export const IGNORE_NOTICE = "This math block is marked `lmat:ignore` and will not be evaluated.";

// True if `text_before` (the Markdown immediately preceding a math block opener)
// ends with the ignore marker, separated from the block by whitespace only.
export function precededByIgnoreMarker(text_before: string): boolean {
    return IGNORE_MARKER_BEFORE_BLOCK.test(text_before);
}

// True if `text` contains the ignore marker anywhere (used for whole-block
// source checks where the marker's exact position isn't needed).
export function containsIgnoreMarker(text: string): boolean {
    return IGNORE_MARKER.test(text);
}
