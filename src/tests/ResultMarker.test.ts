import { describe, expect, test } from "vitest";
import { DEFAULT_RESULT_MARKER, resolveMarker, splitSource, stripResult } from "/utils/ResultMarker";

const RESULT_MARKER = DEFAULT_RESULT_MARKER;

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

    test("legacy `\\quad \\Rightarrow \\quad` markers still split", () => {
        // Notes written under v1.5.0/1.5.1 used quads on both sides. Refresh
        // must still find them after the v1.5.3 default switched to plain.
        const contents = "x = 5 \\quad \\Rightarrow \\quad 5";
        const result = splitSource(contents);
        expect(result.has_marker).toBe(true);
        expect(result.source).toBe("x = 5");
    });

    test("alternative arrow markers (\\to, \\implies) split too", () => {
        for (const arrow of ["\\to", "\\implies", "\\rightarrow", "\\Longrightarrow"]) {
            const r = splitSource(`a ${arrow} b`);
            expect(r.has_marker, `arrow=${arrow}`).toBe(true);
            expect(r.source, `arrow=${arrow}`).toBe("a");
        }
    });

    test("resolveMarker: empty/undefined falls back to default", () => {
        expect(resolveMarker(undefined)).toBe(DEFAULT_RESULT_MARKER);
        expect(resolveMarker("")).toBe(DEFAULT_RESULT_MARKER);
        expect(resolveMarker("   ")).toBe(DEFAULT_RESULT_MARKER);
    });

    test("resolveMarker: passes through configured value, trimmed", () => {
        expect(resolveMarker("\\to")).toBe("\\to");
        expect(resolveMarker("  \\implies  ")).toBe("\\implies");
    });
});
