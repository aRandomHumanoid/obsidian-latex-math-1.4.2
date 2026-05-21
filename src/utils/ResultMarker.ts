// Marker inserted between the user's source LaTeX and a Smart Solve result.
// Re-pressing the hotkey detects this marker and replaces everything after it,
// so the operation is idempotent.
export const RESULT_MARKER = "\\quad \\Rightarrow \\quad";

const MARKER_REGEX = /\\quad\s*\\Rightarrow\s*\\quad/;

export interface SplitResult {
    source: string;
    has_marker: boolean;
    marker_offset?: number;
}

// Split math-block contents on the result marker.
// Returns the source half plus whether a marker was found and at what offset within the input.
export function splitSource(contents: string): SplitResult {
    const match = MARKER_REGEX.exec(contents);

    if (!match) {
        return { source: contents, has_marker: false };
    }

    const before = contents.slice(0, match.index);
    return {
        source: before.replace(/\s+$/, ''),
        has_marker: true,
        marker_offset: match.index,
    };
}

// Strip any trailing result (marker + result) from raw LaTeX source.
// Useful when sending the user's input to the backend without prior decorations.
export function stripResult(contents: string): string {
    return splitSource(contents).source;
}
