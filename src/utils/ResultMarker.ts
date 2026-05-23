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
}

// Split math-block contents on the first detected result marker.
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
