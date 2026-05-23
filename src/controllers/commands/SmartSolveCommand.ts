import { App, Editor, MarkdownView, Notice } from "obsidian";
import { CasServer } from "/services/CasServer";
import { LatexMathCommand } from "./LatexMathCommand";
import { SectionContextBuilder } from "/models/cas/SectionContextBuilder";
import { formatLatex } from "/utils/LatexFormatter";
import { iterateMathBlocks } from "/utils/MathBlockIterator";
import { resolveMarker, splitSource, stripResult } from "/utils/ResultMarker";
import { SuccessResponseVerifier } from "/services/ResponseVerifier";
import {
    PriorBlock,
    SmartSolveArgsPayload,
    SmartSolveMessage,
    SmartSolveResponse,
    SmartSolveToast,
} from "/models/cas/messages/SmartSolveMessage";

interface BlockUpdate {
    from: number;
    to: number;
    new_text: string;
}

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
        const all_blocks = iterateMathBlocks(doc_text);

        if (all_blocks.length === 0) {
            new Notice("No math blocks in document");
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
        const all_toasts: SmartSolveToast[] = [];
        let display_count = 0;
        let error_count = 0;

        for (const block of all_blocks) {
            if (this.current_run_id !== this_run_id) return;

            const split = splitSource(block.contents);
            const source_trimmed = split.source.trim();
            const is_cursor_block = cursor_offset >= block.from && cursor_offset <= block.to;

            if (source_trimmed === "") continue;

            // Always dispatch — we need the toasts even on blocks we won't write to.
            const context = SectionContextBuilder.build(app, view, editor.offsetToPos(block.from));
            const prior_blocks: PriorBlock[] = context.prior_blocks.map(b => ({
                contents: stripResult(b.contents),
            }));
            const payload = new SmartSolveArgsPayload(source_trimmed, context.environment, prior_blocks);

            let result: SmartSolveResponse;
            try {
                const response = await cas_server.send(new SmartSolveMessage(payload)).response;
                result = this.response_verifier.verifyResponse<SmartSolveResponse>(response);
            } catch (e) {
                error_count++;
                new Notice(`Smart Solve error on block: ${e instanceof Error ? e.message : String(e)}`, 8000);
                continue;
            }

            all_toasts.push(...(result.toasts ?? []));

            // Whether we're allowed to commit a *new* marker to this block.
            // Refresh-only blocks (outside cursor + no existing marker) get the
            // toasts but don't have their text rewritten.
            const may_write_marker = is_cursor_block || split.has_marker;

            // Preserve the user's delimiter flavor: `$$...$$` (possibly fenced)
            // vs. `$...$` (inline, single-line).
            const original_raw = editor.getRange(editor.offsetToPos(block.from), editor.offsetToPos(block.to));
            const is_display = original_raw.startsWith("$$");

            let new_inner: string | null = null;
            let force_multiline = false;

            if (result.kind === "display" && result.display_latex !== undefined && may_write_marker) {
                const formatted = await formatLatex(result.display_latex);

                // Pressing inside a `$$...$$` block promotes single-line to
                // multi-line so the result lands on its own line. Refreshing
                // an existing marker keeps the block's current flavor.
                if (is_cursor_block && is_display) {
                    force_multiline = true;
                }

                const will_be_multiline = is_display && (force_multiline || /\n/.test(original_raw));

                if (will_be_multiline) {
                    new_inner = `${source_trimmed}\n${marker} ${formatted.replaceAll("\n", " ")}`;
                } else {
                    new_inner = `${source_trimmed} ${marker} ${formatted}`.replaceAll('\n', ' ');
                }
                display_count++;
            } else if (result.kind === "silent" && split.has_marker) {
                // Stale result on a now-silent block (e.g., a verified equality
                // or a definition that previously rendered a value): strip it.
                new_inner = source_trimmed;
            }
            // no_op leaves the block untouched.

            if (new_inner !== null) {
                let new_text: string;
                if (is_display) {
                    const will_be_multiline = force_multiline || /\n/.test(original_raw);
                    new_text = will_be_multiline ? `$$\n${new_inner}\n$$` : `$$${new_inner}$$`;
                } else {
                    new_text = `$${new_inner}$`;
                }
                if (new_text !== original_raw) {
                    updates.push({ from: block.from, to: block.to, new_text });
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
