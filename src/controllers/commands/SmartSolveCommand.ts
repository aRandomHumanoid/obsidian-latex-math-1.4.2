import { App, Editor, MarkdownView, Notice } from "obsidian";
import { CasServer } from "/services/CasServer";
import { LatexMathCommand } from "./LatexMathCommand";
import { SectionContextBuilder } from "/models/cas/SectionContextBuilder";
import { formatLatex } from "/utils/LatexFormatter";
import { iterateMathBlocks } from "/utils/MathBlockIterator";
import { RESULT_MARKER, splitSource, stripResult } from "/utils/ResultMarker";
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

// Cap on how many individual toasts to surface per run before we collapse
// the remainder into a single "and N more" notice. Document-wide runs can
// emit a lot of notices and Obsidian stacks them in the corner.
const MAX_TOASTS_PER_RUN = 5;

export class SmartSolveCommand extends LatexMathCommand {
    readonly id = "smart-solve-latex-expression";

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

        const updates: BlockUpdate[] = [];
        const all_toasts: SmartSolveToast[] = [];
        let display_count = 0;
        let error_count = 0;

        for (const block of all_blocks) {
            // Bail if a newer press has taken over.
            if (this.current_run_id !== this_run_id) return;

            const { source } = splitSource(block.contents);
            const source_trimmed = source.trim();

            // Skip blocks that are empty after stripping any prior result.
            if (source_trimmed === "") continue;

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

            // Preserve the user's original delimiter style: `$$...$$` (display,
            // possibly fenced across newlines) vs. `$...$` (inline, single-line).
            const original_raw = editor.getRange(editor.offsetToPos(block.from), editor.offsetToPos(block.to));
            const is_display = original_raw.startsWith("$$");
            const is_multiline = is_display && /\n/.test(original_raw);

            let new_inner: string | null = null;

            if (result.kind === "display" && result.display_latex !== undefined) {
                const formatted = await formatLatex(result.display_latex);
                let body = `${source_trimmed} ${RESULT_MARKER} ${formatted}`;
                // Inline math cannot contain newlines; flatten the result body.
                if (!is_multiline) body = body.replaceAll('\n', ' ');
                new_inner = body;
                display_count++;
            } else if (result.kind === "silent") {
                // Strip any stale result marker so silent dispatches (definitions,
                // verified equalities) don't leave a now-irrelevant `⇒ ...` tail.
                if (block.contents !== source_trimmed) {
                    new_inner = source_trimmed;
                }
            }
            // no_op leaves the block untouched.

            if (new_inner !== null) {
                let new_text: string;
                if (is_display) {
                    new_text = is_multiline ? `$$\n${new_inner}\n$$` : `$$${new_inner}$$`;
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
            new Notice(`...and ${all_toasts.length - MAX_TOASTS_PER_RUN} more notice${all_toasts.length - MAX_TOASTS_PER_RUN === 1 ? '' : 's'}`);
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
