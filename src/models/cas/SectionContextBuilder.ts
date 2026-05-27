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
    section_blocks: MathBlockSpan[];
    section_start_offset: number;
    section_end_offset: number;
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

        const section_range = this.getSectionRange(sections, editor, cursor_offset, editor.getValue().length);

        const section_text = editor.getRange(
            editor.offsetToPos(section_range.start_offset),
            editor.offsetToPos(section_range.end_offset),
        );

        const section_blocks = iterateMathBlocks(section_text, section_range.start_offset);

        const prior_blocks = section_blocks.filter(b => b.to < cursor_offset);

        const environment = LmatEnvironment.fromCodeBlock(section_range.lmat_config_text, []);

        return {
            environment,
            prior_blocks,
            section_blocks,
            section_start_offset: section_range.start_offset,
            section_end_offset: section_range.end_offset,
        };
    }

    private static getSectionRange(
        sections: { type: string; position: { start: { offset: number }; end: { offset: number } } }[],
        editor: Editor,
        cursor_offset: number,
        document_length: number,
    ): { start_offset: number; end_offset: number; lmat_config_text?: string } {
        let start_offset = 0;
        let end_offset = document_length;
        let lmat_config_text: string | undefined = undefined;

        for (const section of sections) {
            const is_divider = this.isDivider(section, editor);
            if (!is_divider.divider) continue;

            if (section.position.end.offset < cursor_offset) {
                start_offset = section.position.end.offset;
                lmat_config_text = is_divider.lmat_text;
                continue;
            }

            if (section.position.start.offset > cursor_offset) {
                end_offset = section.position.start.offset;
                break;
            }
        }

        return { start_offset, end_offset, lmat_config_text };
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
