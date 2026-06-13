import { expect, test } from "vitest";
import { SectionContextBuilder } from "/models/cas/SectionContextBuilder";

type MockPosition = { line: number; ch: number };

function createEditor(text: string) {
    return {
        getValue: () => text,
        getRange: (from: MockPosition, to: MockPosition) => text.slice(from.ch, to.ch),
        offsetToPos: (offset: number): MockPosition => ({ line: 0, ch: offset }),
        posToOffset: (position: MockPosition) => position.ch,
        getCursor: (): MockPosition => ({ line: 0, ch: 0 }),
    };
}

test("SectionContextBuilder scopes blocks to the cursor section", () => {
    const text = [
        "# Before",
        "$$a = 1$$",
        "",
        "```lmat",
        "[solve]",
        'domain = "S.Reals"',
        "```",
        "$$x = 3$$",
        "$$x + 1 =$$",
        "---",
        "$$y = 2$$",
    ].join("\n");

    const editor = createEditor(text);
    const code_block = "```lmat\n[solve]\ndomain = \"S.Reals\"\n```";
    const code_start = text.indexOf(code_block);
    const code_end = code_start + code_block.length;
    const break_start = text.indexOf("---");
    const cursor = editor.offsetToPos(text.indexOf("x + 1"));

    const sections = [
        {
            type: "heading",
            position: {
                start: { offset: 0 },
                end: { offset: text.indexOf("\n") },
            },
        },
        {
            type: "code",
            position: {
                start: { offset: code_start },
                end: { offset: code_end },
            },
        },
        {
            type: "thematicBreak",
            position: {
                start: { offset: break_start },
                end: { offset: break_start + 3 },
            },
        },
    ];

    const app = {
        metadataCache: {
            getFileCache: () => ({ sections }),
        },
    };
    const view = {
        file: {},
        editor,
    };

    const result = SectionContextBuilder.build(app as never, view as never, cursor as never);

    expect(result.section_start_offset).toBe(code_end);
    expect(result.section_end_offset).toBe(break_start);
    expect(result.section_blocks.map(block => block.contents)).toEqual(["x = 3", "x + 1 ="]);
    expect(result.prior_blocks.map(block => block.contents)).toEqual(["x = 3"]);
    expect(result.environment.solve_domain).toBe("S.Reals");
});

test("SectionContextBuilder flags lmat:ignore blocks in the section", () => {
    const text = [
        "$a = 1$",
        "<!-- lmat:ignore --> $b = 2$",
    ].join("\n");

    const editor = createEditor(text);
    const app = { metadataCache: { getFileCache: () => ({ sections: [] }) } };
    const view = { file: {}, editor };
    const cursor = editor.offsetToPos(text.length);

    const result = SectionContextBuilder.build(app as never, view as never, cursor as never);

    expect(result.section_blocks.map(b => b.contents)).toEqual(["a = 1", "b = 2"]);
    expect(result.section_blocks.map(b => b.ignored)).toEqual([false, true]);
});