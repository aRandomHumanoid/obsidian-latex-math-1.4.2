import { describe, expect, test } from "vitest";
import { buildSmartSolveBlockText, computeCursorOffset } from "/utils/SmartSolveRewrite";

describe("SmartSolveRewrite", () => {
    test("writes display math on a single line and ends outside the block", () => {
        expect(buildSmartSolveBlockText("$$x = 3$$", "x = 4 \\Rightarrow 4")).toBe("$$x = 4 \\Rightarrow 4$$\n");
    });

    test("writes inline math on a single line and ends outside the block", () => {
        expect(buildSmartSolveBlockText("$x = 3$", "x = 4 \\Rightarrow 4")).toBe("$x = 4 \\Rightarrow 4$\n");
    });

    test("cursor offset accounts for earlier edits", () => {
        const prior_updates = [{ from: 0, to: 4, new_text: "abc" }];
        const target_update = { from: 10, to: 15, new_text: "wxyz\n" };

        expect(computeCursorOffset(target_update, prior_updates)).toBe(14);
    });
});