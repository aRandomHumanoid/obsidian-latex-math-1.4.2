// Iterate over math blocks within a given text range.
// We use a hand-rolled scanner rather than the CodeMirror syntax tree because
// the syntax tree only covers what's currently visible/parsed; the markdown
// range we walk may extend across the whole document.
//
// Recognizes two flavors of math:
//   - `$$...$$` (display math, may span multiple lines)
//   - `$...$`  (inline math, must stay on one line)
//
// Both are returned in document order via the same `MathBlockSpan` shape so
// downstream code (Smart Solve dispatch, result rewriting) doesn't need to
// branch on flavor — the `from`/`to` offsets cover the literal delimiters in
// either case.

import { precededByIgnoreMarker } from "/utils/IgnoreMarker";

export interface MathBlockSpan {
    contents: string;   // text between the delimiters (trimmed)
    from: number;       // offset of the opening `$` (first of `$$` for display)
    to: number;         // offset just past the closing `$` (or second `$` for display)
    ignored: boolean;   // preceded by a `<!-- lmat:ignore -->` marker
}

export function iterateMathBlocks(text: string, base_offset = 0): MathBlockSpan[] {
    const blocks: MathBlockSpan[] = [];
    let i = 0;

    while (i < text.length) {
        const ch = text[i];

        // Skip past any escape sequence so `\$` is not treated as a delimiter.
        if (ch === '\\') {
            i += 2;
            continue;
        }

        if (ch !== '$') {
            i++;
            continue;
        }

        // Display math: opens with `$$`.
        if (text[i + 1] === '$') {
            const open = i;
            let j = i + 2;
            let closed = false;
            while (j < text.length - 1) {
                if (text[j] === '\\') { j += 2; continue; }
                if (text[j] === '$' && text[j + 1] === '$') {
                    closed = true;
                    break;
                }
                j++;
            }
            if (!closed) {
                // Unterminated `$$` — bail out; trying to recover would risk
                // matching the wrong closer further down the document.
                break;
            }
            blocks.push({
                contents: text.slice(open + 2, j).trim(),
                from: base_offset + open,
                to: base_offset + j + 2,
                ignored: precededByIgnoreMarker(text.slice(0, open)),
            });
            i = j + 2;
            continue;
        }

        // Inline math: opens with a single `$`. The closer must be on the same
        // line, must not be escaped, and must not be the first half of `$$`.
        const open = i;
        let j = i + 1;
        let closed_at = -1;
        while (j < text.length) {
            const cj = text[j];
            if (cj === '\n') break;
            if (cj === '\\') { j += 2; continue; }
            if (cj === '$') {
                if (text[j + 1] === '$') {
                    // It's a `$$` opener, not our closer — abandon the inline match.
                    break;
                }
                closed_at = j;
                break;
            }
            j++;
        }

        if (closed_at < 0) {
            // No valid closer found; just advance past the lone `$`.
            i++;
            continue;
        }

        blocks.push({
            contents: text.slice(open + 1, closed_at).trim(),
            from: base_offset + open,
            to: base_offset + closed_at + 1,
            ignored: precededByIgnoreMarker(text.slice(0, open)),
        });
        i = closed_at + 1;
    }

    return blocks;
}
