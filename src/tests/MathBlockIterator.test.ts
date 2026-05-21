import { describe, expect, test } from "vitest";
import { iterateMathBlocks } from "/utils/MathBlockIterator";

describe("MathBlockIterator", () => {
    test("finds a single $$...$$ block", () => {
        const text = "before\n$$x = 3$$\nafter";
        const blocks = iterateMathBlocks(text);
        expect(blocks).toHaveLength(1);
        expect(blocks[0].contents).toBe("x = 3");
    });

    test("finds multiple blocks in order", () => {
        const text = "$$a = 1$$\n\nsome prose\n\n$$b = 2$$\n$$c = 3$$";
        const blocks = iterateMathBlocks(text);
        expect(blocks).toHaveLength(3);
        expect(blocks.map(b => b.contents)).toEqual(["a = 1", "b = 2", "c = 3"]);
    });

    test("trims interior whitespace", () => {
        const text = "$$\n  x = 3\n$$";
        const blocks = iterateMathBlocks(text);
        expect(blocks[0].contents).toBe("x = 3");
    });

    test("ignores inline $...$ blocks", () => {
        const text = "this $x$ is inline and $$y = 5$$ is block";
        const blocks = iterateMathBlocks(text);
        expect(blocks).toHaveLength(1);
        expect(blocks[0].contents).toBe("y = 5");
    });

    test("applies base_offset to the from/to positions", () => {
        const text = "$$x = 3$$";
        const blocks = iterateMathBlocks(text, 100);
        expect(blocks[0].from).toBe(100);
        expect(blocks[0].to).toBe(100 + text.length);
    });

    test("returns empty array when no blocks present", () => {
        const blocks = iterateMathBlocks("just some prose, no math here");
        expect(blocks).toHaveLength(0);
    });

    test("ignores escaped $$ (preceded by backslash)", () => {
        const text = "the text \\$\\$not math\\$\\$ here";
        const blocks = iterateMathBlocks(text);
        expect(blocks).toHaveLength(0);
    });

    test("handles multiline content inside a block", () => {
        const text = "$$\n\\begin{align}\nx &= 3 \\\\\ny &= 4\n\\end{align}\n$$";
        const blocks = iterateMathBlocks(text);
        expect(blocks).toHaveLength(1);
        expect(blocks[0].contents).toContain("\\begin{align}");
        expect(blocks[0].contents).toContain("y &= 4");
    });

    test("two consecutive blocks separated by single newline", () => {
        const text = "$$a = 1$$\n$$b = 2$$";
        const blocks = iterateMathBlocks(text);
        expect(blocks).toHaveLength(2);
        expect(blocks[0].contents).toBe("a = 1");
        expect(blocks[1].contents).toBe("b = 2");
    });

    test("from/to positions span the entire $$...$$ literal", () => {
        const text = "prefix $$x = 3$$ suffix";
        const blocks = iterateMathBlocks(text);
        expect(blocks).toHaveLength(1);
        const slice = text.slice(blocks[0].from, blocks[0].to);
        expect(slice).toBe("$$x = 3$$");
    });
});
