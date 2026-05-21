import { App, Editor, EditorPosition, MarkdownView, Notice } from "obsidian";
import { CasServer, InterruptHandlerMessage } from "/services/CasServer";
import { LatexMathCommand } from "./LatexMathCommand";
import { EquationExtractor } from "/utils/EquationExtractor";
import { SectionContextBuilder } from "/models/cas/SectionContextBuilder";
import { formatLatex } from "/utils/LatexFormatter";
import { RESULT_MARKER, splitSource, stripResult } from "/utils/ResultMarker";
import {
    PriorBlock,
    SmartSolveArgsPayload,
    SmartSolveMessage,
    SmartSolveResponse,
    SmartSolveToast,
} from "/models/cas/messages/SmartSolveMessage";

type Expression = {
    from: number;
    to: number;
    contents: string;
    is_multiline: boolean;
};

export class SmartSolveCommand extends LatexMathCommand {
    readonly id = "smart-solve-latex-expression";

    // Track the most recent in-flight uid so a subsequent press can cancel it
    // (design_docs.md §"Timeouts and Cancellation").
    private in_flight_uid: string | null = null;

    public async functionCallback(cas_server: CasServer, app: App, editor: Editor, view: MarkdownView): Promise<void> {
        const expression = this.getExpression(editor);

        if (expression === null) {
            new Notice("You are not inside a math block");
            return;
        }

        // Strip any existing inline result so the backend sees only the user's source.
        const { source } = splitSource(expression.contents);

        const context = SectionContextBuilder.build(app, view);

        const prior_blocks: PriorBlock[] = context.prior_blocks.map(b => ({
            contents: stripResult(b.contents),
        }));

        const payload = new SmartSolveArgsPayload(source, context.environment, prior_blocks);

        // If a previous Smart Solve press is still pending, interrupt it before
        // launching the new one so the user doesn't get stale results.
        if (this.in_flight_uid !== null) {
            try {
                cas_server.send(new InterruptHandlerMessage({ target_uids: [this.in_flight_uid] }));
            } catch (e) {
                // Best-effort cancellation; ignore failures (the original might have
                // already completed between the press and this call).
                void e;
            }
        }

        const sent = cas_server.send(new SmartSolveMessage(payload));
        this.in_flight_uid = sent.uid;

        let response;
        try {
            response = await sent.response;
        } finally {
            // Only clear if no newer press has overwritten this in-flight slot.
            if (this.in_flight_uid === sent.uid) {
                this.in_flight_uid = null;
            }
        }
        const result = this.response_verifier.verifyResponse<SmartSolveResponse>(response);

        for (const toast of result.toasts ?? []) {
            this.showToast(toast);
        }

        if (result.kind === "display" && result.display_latex !== undefined) {
            await this.insertOrReplaceResult(editor, expression, source, result);
        }
    }

    private getExpression(editor: Editor): Expression | null {
        const expression = EquationExtractor.extractEquation(editor.posToOffset(editor.getCursor()), editor);

        if (expression === null) return null;

        if (editor.getSelection().length > 0) {
            return {
                from: editor.posToOffset(editor.getCursor('from')),
                to: editor.posToOffset(editor.getCursor('to')),
                contents: editor.getSelection(),
                is_multiline: expression.is_multiline,
            };
        }

        return {
            from: expression.from,
            to: expression.to,
            contents: expression.contents,
            is_multiline: expression.is_multiline,
        };
    }

    private async insertOrReplaceResult(
        editor: Editor,
        expression: Expression,
        source: string,
        result: SmartSolveResponse,
    ): Promise<void> {
        const formatted = await formatLatex(result.display_latex as string);
        let block_text = `${source.trimEnd()} ${RESULT_MARKER} ${formatted}`;

        if (!expression.is_multiline) {
            block_text = block_text.replaceAll('\n', ' ');
        }

        const from_pos: EditorPosition = editor.offsetToPos(expression.from);
        const to_pos: EditorPosition = editor.offsetToPos(expression.to);

        editor.replaceRange(block_text, from_pos, to_pos);

        const new_end_offset = expression.from + block_text.length;
        editor.setCursor(editor.offsetToPos(new_end_offset));
    }

    private showToast(toast: SmartSolveToast): void {
        // Errors are surfaced longer; info/warning use Obsidian's default 4s.
        const timeout = toast.severity === "error" ? 8000 : undefined;
        new Notice(toast.text, timeout);
    }
}
