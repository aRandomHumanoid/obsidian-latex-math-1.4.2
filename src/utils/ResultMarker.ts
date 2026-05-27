// Marker inserted between the user's source LaTeX and a Smart Solve result.
// Re-pressing the hotkey detects the marker and replaces everything after it,
// so the operation is idempotent.
//
// The *insertion* marker is configurable via plugin settings (so users can pick
// `\to`, `\implies`, etc.). *Detection* is intentionally liberal: we recognize
// any of the common LaTeX arrows below, with or without surrounding `\quad`
// padding — this keeps old notes (`\quad \Rightarrow \quad`) and the v1.5.1
// default (no padding) detectable regardless of the current setting.

export const DEFAULT_RESULT_MARKER = "\\Rightarrow";

// Standard LaTeX arrows that we treat as "result markers" when detecting an
// existing inline result. Anchored to a leading backslash; optional `\quad`s
// on either side are absorbed so old `\quad \Rightarrow \quad` markers split
// correctly.
const MARKER_REGEX = /(?:\\quad\s*)?\\(?:Rightarrow|rightarrow|to|implies|Longrightarrow|longrightarrow|Leftrightarrow|iff)(?:\s*\\quad)?/;

export interface SplitResult {
    source: string;
    has_marker: boolean;
    marker_offset?: number;
    trailing_text?: string;
}

// Split math-block contents on the first detected result marker.
// Returns the source half plus whether a marker was found and at what offset within the input.
export function splitSource(contents: string): SplitResult {
    const match = MARKER_REGEX.exec(contents);

    if (!match) {
        return { source: contents, has_marker: false };
    }

    const before = contents.slice(0, match.index);
    const marker_end = match.index + match[0].length;

    return {
        source: before.replace(/\s+$/, ''),
        has_marker: true,
        marker_offset: match.index,
        trailing_text: extractTrailingText(contents, marker_end),
    };
}

// Strip any trailing result (marker + result text) from raw LaTeX source.
// Useful when sending the user's input to the backend without prior decorations.
export function stripResult(contents: string): string {
    return splitSource(contents).source;
}

// Normalize a user-configured marker. Falls back to the default if empty.
export function resolveMarker(configured: string | undefined): string {
    const trimmed = (configured ?? "").trim();
    return trimmed === "" ? DEFAULT_RESULT_MARKER : trimmed;
}

function extractTrailingText(contents: string, marker_end: number): string | undefined {
    let candidate = contents.indexOf("\\text", marker_end);

    while (candidate >= 0) {
        let suffix_start = candidate;

        while (suffix_start > marker_end && /\s/.test(contents[suffix_start - 1])) {
            suffix_start -= 1;
        }

        if (consumeTrailingText(contents, suffix_start) === contents.length) {
            return contents.slice(suffix_start);
        }

        candidate = contents.indexOf("\\text", candidate + 5);
    }

    return undefined;
}

function consumeTrailingText(contents: string, start: number): number {
    let cursor = start;

    while (cursor < contents.length) {
        while (cursor < contents.length && /\s/.test(contents[cursor])) {
            cursor += 1;
        }

        if (cursor === contents.length) {
            return cursor;
        }

        if (!contents.startsWith("\\text", cursor)) {
            return -1;
        }

        cursor += 5;

        while (cursor < contents.length && /[A-Za-z]/.test(contents[cursor])) {
            cursor += 1;
        }

        while (cursor < contents.length && /\s/.test(contents[cursor])) {
            cursor += 1;
        }

        if (contents[cursor] !== "{") {
            return -1;
        }

        cursor = consumeBalancedGroup(contents, cursor);
        if (cursor < 0) {
            return -1;
        }
    }

    return cursor;
}

function consumeBalancedGroup(contents: string, open_index: number): number {
    let depth = 0;

    for (let cursor = open_index; cursor < contents.length; cursor++) {
        const ch = contents[cursor];

        if (ch === "\\") {
            cursor += 1;
            continue;
        }

        if (ch === "{") {
            depth += 1;
            continue;
        }

        if (ch !== "}") {
            continue;
        }

        depth -= 1;

        if (depth === 0) {
            return cursor + 1;
        }
    }

    return -1;
}
