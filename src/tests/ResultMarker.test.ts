import { describe, expect, test } from "vitest";
import { RESULT_MARKER, splitSource, stripResult } from "/utils/ResultMarker";

describe("ResultMarker", () => {
    test("no marker present: returns full input as source", () => {
        const result = splitSource("x + 3 = 7");
        expect(result.has_marker).toBe(false);
        expect(result.source).toBe("x + 3 = 7");
        expect(result.marker_offset).toBeUndefined();
    });

    test("marker present: returns source half with trailing whitespace trimmed", () => {
        const contents = `x + 3 = 7 ${RESULT_MARKER} x = 4`;
        const result = splitSource(contents);
        expect(result.has_marker).toBe(true);
        expect(result.source).toBe("x + 3 = 7");
        expect(result.marker_offset).toBeGreaterThan(0);
    });

    test("marker present with extra whitespace inside marker: still detected", () => {
        const contents = "x = 5 \\quad   \\Rightarrow   \\quad 5";
        const result = splitSource(contents);
        expect(result.has_marker).toBe(true);
        expect(result.source).toBe("x = 5");
    });

    test("stripResult is idempotent across repeated marker insertions", () => {
        const original = "x + 3 = 7";
        const once = `${original} ${RESULT_MARKER} x = 4`;
        const twice = `${stripResult(once)} ${RESULT_MARKER} x = 4`;

        // Stripping twice yields the original source both times.
        expect(stripResult(once)).toBe(original);
        expect(stripResult(twice)).toBe(original);
    });

    test("first marker wins when multiple are present (malformed input)", () => {
        // A defensive case — if a user paste-bombs two markers, we strip from
        // the first one onward. The source half is everything before it.
        const contents = `x = 1 ${RESULT_MARKER} bad ${RESULT_MARKER} also bad`;
        const result = splitSource(contents);
        expect(result.has_marker).toBe(true);
        expect(result.source).toBe("x = 1");
    });

    test("empty input returns empty source", () => {
        const result = splitSource("");
        expect(result.has_marker).toBe(false);
        expect(result.source).toBe("");
    });

    test("marker present but no result text after it", () => {
        const contents = `x = 5 ${RESULT_MARKER}`;
        const result = splitSource(contents);
        expect(result.has_marker).toBe(true);
        expect(result.source).toBe("x = 5");
    });

    test("multi-line source preserved on the source side", () => {
        const contents = `\\begin{align}\nx + y &= 10\n\\end{align} ${RESULT_MARKER} x = 5`;
        const result = splitSource(contents);
        expect(result.has_marker).toBe(true);
        expect(result.source).toContain("\\begin{align}");
        expect(result.source).toContain("\\end{align}");
    });
});
