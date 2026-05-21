import { App, Editor, EditorPosition, MarkdownView } from "obsidian";
import { LmatEnvironment } from "/models/cas/LmatEnvironment";
import { iterateMathBlocks, MathBlockSpan } from "/utils/MathBlockIterator";

// Regex matching the contents of an lmat code block.
const LMAT_BLOCK_REGEX = /^```lmat\s*(?:\r\n|\r|\n)([\s\S]*?)```$/;

// Markdown horizontal rule (---, ***, ___) on its own line.
const HORIZONTAL_RULE_REGEX = /^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$/m;

export interface SectionContext {
    environment: LmatEnvironment;
    prior_blocks: MathBlockSpan[];
}

// Section dividers per design_docs.md §"Section Scopes":
// - markdown horizontal rule (`---`)
// - any markdown heading
// - an `lmat` code block (also supplies TOML config for the section)
//
// The new section begins immediately after the divider and runs to the cursor.
// Math blocks within that range become the "prior blocks" that Python replays
// to reconstruct the implicit context.
export class SectionContextBuilder {
    public static build(app: App, view: MarkdownView, cursor?: EditorPosition): SectionContext {
        if (!view.file) {
            throw new Error("No file in markdown view");
        }

        const editor = view.editor;
        const position = cursor ?? editor.getCursor();
        const cursor_offset = editor.posToOffset(position);

        const file_cache = app.metadataCache.getFileCache(view.file);
        const sections = file_cache?.sections ?? [];

        // Walk sections that end before the cursor; find the LATEST one that
        // qualifies as a section divider, and grab its lmat config if any.
        let divider_end_offset = 0;
        let lmat_config_text: string | undefined = undefined;

        for (const section of sections) {
            if (section.position.end.offset >= cursor_offset) break;

            const is_divider = this.isDivider(section, editor);
            if (!is_divider.divider) continue;

            divider_end_offset = section.position.end.offset;
            lmat_config_text = is_divider.lmat_text;
        }

        // Body of the section starts after the divider's end.
        const body_text = editor.getRange(editor.offsetToPos(divider_end_offset), position);

        const all_blocks = iterateMathBlocks(body_text, divider_end_offset);

        // The block at the cursor itself is the one being run right now — exclude it
        // from prior_blocks. We detect it by checking if the cursor falls inside.
        const prior_blocks = all_blocks.filter(b => b.to < cursor_offset);

        const environment = LmatEnvironment.fromCodeBlock(lmat_config_text, []);

        return { environment, prior_blocks };
    }

    private static isDivider(
        section: { type: string; position: { start: { offset: number }; end: { offset: number } } },
        editor: Editor,
    ): { divider: boolean; lmat_text?: string } {
        // Headings always divide.
        if (section.type === "heading") {
            return { divider: true };
        }

        // Obsidian uses "thematicBreak" for `---` rules; older versions may report
        // them as paragraphs. Cover both via a regex fallback.
        const text = editor.getRange(
            editor.offsetToPos(section.position.start.offset),
            editor.offsetToPos(section.position.end.offset),
        );

        if (section.type === "thematicBreak" || HORIZONTAL_RULE_REGEX.test(text)) {
            return { divider: true };
        }

        if (section.type === "code") {
            const match = text.match(LMAT_BLOCK_REGEX);
            if (match) {
                return { divider: true, lmat_text: match[1] };
            }
        }

        return { divider: false };
    }
}
