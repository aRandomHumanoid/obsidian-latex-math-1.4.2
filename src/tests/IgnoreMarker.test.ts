import { describe, expect, test } from "vitest";
import { containsIgnoreMarker, precededByIgnoreMarker } from "/utils/IgnoreMarker";

describe("IgnoreMarker", () => {
    describe("precededByIgnoreMarker", () => {
        test("matches the canonical marker immediately before a block", () => {
            expect(precededByIgnoreMarker("<!-- lmat:ignore -->")).toBe(true);
            expect(precededByIgnoreMarker("some prose\n<!-- lmat:ignore --> ")).toBe(true);
        });

        test("allows only whitespace between marker and block", () => {
            expect(precededByIgnoreMarker("<!-- lmat:ignore -->   \n  ")).toBe(true);
        });

        test("tolerates internal whitespace variations", () => {
            expect(precededByIgnoreMarker("<!--lmat:ignore-->")).toBe(true);
            expect(precededByIgnoreMarker("<!--   lmat:ignore   -->")).toBe(true);
        });

        test("is case-insensitive on the payload", () => {
            expect(precededByIgnoreMarker("<!-- LMAT:IGNORE -->")).toBe(true);
            expect(precededByIgnoreMarker("<!-- Lmat:Ignore -->")).toBe(true);
        });

        test("ordinary prose between marker and block breaks the association", () => {
            expect(precededByIgnoreMarker("<!-- lmat:ignore --> some text ")).toBe(false);
            expect(precededByIgnoreMarker("text after marker")).toBe(false);
        });

        test("unrelated HTML comments are not markers", () => {
            expect(precededByIgnoreMarker("<!-- todo: fix this -->")).toBe(false);
            expect(precededByIgnoreMarker("<!-- ignore -->")).toBe(false);
            expect(precededByIgnoreMarker("")).toBe(false);
        });

        test("a marker bound to an earlier block does not bleed into a later one", () => {
            // The previous block's content (ending in `$`) sits between the
            // marker and this position, so it must not match.
            expect(precededByIgnoreMarker("<!-- lmat:ignore --> $a$")).toBe(false);
        });
    });

    describe("containsIgnoreMarker", () => {
        test("finds the marker anywhere in the text", () => {
            expect(containsIgnoreMarker("prefix <!-- lmat:ignore --> suffix")).toBe(true);
            expect(containsIgnoreMarker("nothing here")).toBe(false);
        });
    });
});
