// Iterate over $$...$$ math blocks within a given text range.
// We use a regex pass rather than the CodeMirror syntax tree because the syntax
// tree only covers what's currently visible/parsed; the markdown range we walk
// may extend across the whole document.

export interface MathBlockSpan {
    contents: string;   // text between the $$ delimiters (trimmed)
    from: number;       // offset in the original text of the opening $$
    to: number;         // offset of the closing $$ (inclusive of the second $)
}

// Match opening and closing `$$` that aren't escaped with a backslash.
// Note: we don't try to match inline `$...$` math — the notebook convention is
// block math for equations the user wants to "run".
const BLOCK_MATH_REGEX = /(?<!\\)\$\$([\s\S]*?)(?<!\\)\$\$/g;

export function iterateMathBlocks(text: string, base_offset = 0): MathBlockSpan[] {
    const blocks: MathBlockSpan[] = [];

    for (const match of text.matchAll(BLOCK_MATH_REGEX)) {
        if (match.index === undefined) continue;
        blocks.push({
            contents: match[1].trim(),
            from: base_offset + match.index,
            to: base_offset + match.index + match[0].length,
        });
    }

    return blocks;
}
