import { App, Editor, MarkdownView, Notice } from "obsidian";
import { CasServer } from "/services/CasServer";
import { LatexMathCommand } from "./LatexMathCommand";
import { SectionContextBuilder } from "/models/cas/SectionContextBuilder";
import { formatLatex } from "/utils/LatexFormatter";
import { resolveMarker, splitSource } from "/utils/ResultMarker";
import { buildSmartSolveBlockText, computeCursorOffset, BlockUpdate } from "/utils/SmartSolveRewrite";
import { SuccessResponseVerifier } from "/services/ResponseVerifier";
import {
    SmartSolveResponse,
    SmartSolveSectionArgsPayload,
    SmartSolveSectionMessage,
    SmartSolveSectionResponse,
    SmartSolveToast,
} from "/models/cas/messages/SmartSolveMessage";

// Cap on individual toasts per run before we collapse the remainder into a
// single rollup notice. Document-wide runs can emit a lot, and Obsidian
// stacks every notice in the corner.
const MAX_TOASTS_PER_RUN = 5;

export class SmartSolveCommand extends LatexMathCommand {
    readonly id = "smart-solve-latex-expression";

    constructor(
        response_verifier: SuccessResponseVerifier,
        // Resolved lazily on each press so settings changes take effect without
        // re-registering the command. Returns the user's configured marker
        // LaTeX; if blank/undefined it falls back to the default \Rightarrow.
        private readonly getMarker: () => string,
    ) {
        super(response_verifier);
    }

    // Monotonic counter incremented on each press. The async loop checks this
    // between iterations so a re-press abandons the in-flight run instead of
    // racing two sets of edits into the same document.
    private current_run_id = 0;

    public async functionCallback(cas_server: CasServer, app: App, editor: Editor, view: MarkdownView): Promise<void> {
        this.current_run_id += 1;
        const this_run_id = this.current_run_id;

        const doc_text = editor.getValue();
        const section_context = SectionContextBuilder.build(app, view);
        const all_blocks = section_context.section_blocks;

        if (all_blocks.length === 0) {
            new Notice("No math blocks in current section");
            return;
        }

        // Out-of-block press = refresh-only: don't add `⇒` markers to blocks
        // that don't already have one. But we still dispatch every block to
        // CAS, because override warnings, contradiction errors, and other
        // toasts only fire from the dispatcher — short-circuiting before the
        // round-trip would silently swallow them.
        const cursor_offset = editor.posToOffset(editor.getCursor());
        const marker = resolveMarker(this.getMarker());

        const updates: BlockUpdate[] = [];
        let cursor_update: BlockUpdate | undefined;
        const all_toasts: SmartSolveToast[] = [];
        let display_count = 0;
        let error_count = 0;
        const formatted_cache = new Map<string, string>();

        const runnable_blocks = all_blocks
            .map((block) => {
                const split = splitSource(block.contents);
                return {
                    block,
                    split,
                    source_trimmed: split.source.trim(),
                    is_cursor_block: cursor_offset >= block.from && cursor_offset <= block.to,
                };
            })
            .filter((entry) => entry.source_trimmed !== "");

        if (runnable_blocks.length === 0) {
            new Notice("No non-empty math blocks in current section");
            return;
        }

        let results: SmartSolveResponse[];
        try {
            const response = await cas_server.send(new SmartSolveSectionMessage(
                new SmartSolveSectionArgsPayload(
                    section_context.environment,
                    runnable_blocks.map(({ source_trimmed }) => ({ contents: source_trimmed })),
                ),
            )).response;
            const section_response = this.response_verifier.verifyResponse<SmartSolveSectionResponse>(response);
            results = section_response.results;
        } catch (e) {
            new Notice(`Smart Solve error: ${e instanceof Error ? e.message : String(e)}`, 8000);
            return;
        }

        if (results.length !== runnable_blocks.length) {
            throw new Error(`Smart Solve section result count mismatch: expected ${runnable_blocks.length}, got ${results.length}`);
        }

        for (let index = 0; index < runnable_blocks.length; index++) {
            if (this.current_run_id !== this_run_id) return;

            const { block, split, source_trimmed, is_cursor_block } = runnable_blocks[index];
            const result = results[index];

            all_toasts.push(...(result.toasts ?? []));
            if (result.toasts?.some((toast) => toast.severity === "error")) {
                error_count++;
            }

            // Whether we're allowed to commit a *new* marker to this block.
            // Refresh-only blocks (outside cursor + no existing marker) get the
            // toasts but don't have their text rewritten.
            const may_write_marker = is_cursor_block || split.has_marker;

            // Preserve the user's delimiter flavor: `$$...$$` (possibly fenced)
            // vs. `$...$` (inline, single-line).
            const original_raw = editor.getRange(editor.offsetToPos(block.from), editor.offsetToPos(block.to));

            let new_inner: string | null = null;

            if (result.kind === "display" && result.display_latex !== undefined && may_write_marker) {
                let formatted = formatted_cache.get(result.display_latex);
                if (formatted === undefined) {
                    formatted = await formatLatex(result.display_latex);
                    formatted_cache.set(result.display_latex, formatted);
                }

                new_inner = `${source_trimmed} ${marker} ${formatted.replaceAll("\n", " ")}${split.trailing_text ?? ""}`;
                display_count++;
            } else if (result.kind === "silent" && split.has_marker) {
                // Stale result on a now-silent block (e.g., a verified equality
                // or a definition that previously rendered a value): strip it.
                new_inner = source_trimmed;
            }
            // no_op leaves the block untouched.

            if (new_inner !== null) {
                const next_char_is_newline = doc_text.slice(block.to, block.to + 1) === "\n";
                const update: BlockUpdate = {
                    from: block.from,
                    to: block.to + (next_char_is_newline ? 1 : 0),
                    new_text: buildSmartSolveBlockText(original_raw, new_inner),
                };
                const original_slice = doc_text.slice(update.from, update.to);

                if (is_cursor_block) {
                    cursor_update = update;
                }

                if (update.new_text !== original_slice) {
                    updates.push(update);
                }
            }
        }

        if (this.current_run_id !== this_run_id) return;

        // Apply edits back-to-front so each earlier replacement doesn't shift
        // the offsets of replacements we haven't applied yet.
        for (let i = updates.length - 1; i >= 0; i--) {
            const u = updates[i];
            editor.replaceRange(u.new_text, editor.offsetToPos(u.from), editor.offsetToPos(u.to));
        }

        if (cursor_update !== undefined) {
            const cursor_offset = computeCursorOffset(cursor_update, updates);
            editor.setCursor(editor.offsetToPos(cursor_offset));
        }

        for (const toast of all_toasts.slice(0, MAX_TOASTS_PER_RUN)) {
            this.showToast(toast);
        }
        if (all_toasts.length > MAX_TOASTS_PER_RUN) {
            const extra = all_toasts.length - MAX_TOASTS_PER_RUN;
            new Notice(`...and ${extra} more notice${extra === 1 ? '' : 's'}`);
        }

        const summary_parts = [`Re-evaluated ${display_count}/${all_blocks.length} block${all_blocks.length === 1 ? '' : 's'}`];
        if (error_count > 0) summary_parts.push(`${error_count} error${error_count === 1 ? '' : 's'}`);
        new Notice(summary_parts.join(' — '));
    }

    private showToast(toast: SmartSolveToast): void {
        const timeout = toast.severity === "error" ? 8000 : undefined;
        new Notice(toast.text, timeout);
    }
}
