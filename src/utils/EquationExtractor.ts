import { syntaxTree } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { Editor } from "obsidian";
import { IGNORE_MARKER_LOOKBACK, precededByIgnoreMarker } from "/utils/IgnoreMarker";

export class EquationExtractor {

    // Extract the contents of the equation block, which the given position offset is currently inside.
    // Returns null if the position is not inside an equation.
    public static extractEquation(position: number, editor: Editor): { from: number; to: number, block_from: number, block_to: number, contents: string, is_multiline: boolean, ignored: boolean } | null {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const state = (editor as any).cm.state as EditorState;

        // we cannot extract an equation if we are not currently within one.
        if (!this.isWithinEquation(position, state)) {
            return null;
        }

        // simply travel left and right until we are no longer inside an equation.

        let from = position;
        let to = position;

        while (this.isWithinEquation(from, state)) {
            from--;
        }

        from++;

        while (this.isWithinEquation(to, state)) {
            to++;
        }

        to--;

        let block_from = from - 1;
        let block_to = to + 1;

        if (editor.getRange(editor.offsetToPos(from), editor.offsetToPos(from + 1)) === "$") {
            from++;

            block_from = from - 2;
            block_to = to + 2;
        }

        // move from and to as right and left most as possible, until from and to no longer starts on whitespace
        while (to > block_from && /^\s$/.test(editor.getRange(editor.offsetToPos(to - 1), editor.offsetToPos(to)))) {
            to--;
        }

        while (from < to && /^\s$/.test(editor.getRange(editor.offsetToPos(from), editor.offsetToPos(from + 1)))) {
            from++;
        }

        // check if contents are surrounded by {}, as this is commonly used as a trick to prevent flickering in single line math blocks.
        // TODO: this should be handled in the parser.
        if (/{} .* {}/s.test(editor.getRange(editor.offsetToPos(from), editor.offsetToPos(to)))) {
            from += 3;
            to -= 3;
        }

        // A `<!-- lmat:ignore -->` marker immediately before the block opts the
        // whole block out of evaluation, regardless of any selection within it.
        const lookback_start = Math.max(0, block_from - IGNORE_MARKER_LOOKBACK);
        const text_before = editor.getRange(editor.offsetToPos(lookback_start), editor.offsetToPos(block_from));

        return {
            from: from,
            to: to,
            block_from: block_from,
            block_to: block_to,
            contents: editor.getRange(editor.offsetToPos(from), editor.offsetToPos(to)),
            is_multiline: /^\$\$.*\$\$$/s.test(editor.getRange(editor.offsetToPos(block_from), editor.offsetToPos(block_to))),
            ignored: precededByIgnoreMarker(text_before),
        };
    }

    // Check if the given cursor offset is inside an equation.
    // Taken from obsidian latex suite plugin:
    // https://github.com/artisticat1/obsidian-latex-suite/blob/main/src/utils/context.ts#L157
    public static isWithinEquation(position: number, state: EditorState): boolean {
        const tree = syntaxTree(state);

        let syntaxNode = tree.resolveInner(position, -1);
        if (syntaxNode.name.includes("math-end")) return false;

        if (!syntaxNode.parent) {
            syntaxNode = tree.resolveInner(position, 1);
            if (syntaxNode.name.includes("math-begin")) return false;
        }

        // Account/allow for being on an empty line in a equation
        if (!syntaxNode.parent) {
            const left = tree.resolveInner(position - 1, -1);
            const right = tree.resolveInner(position + 1, 1);

            return (left.name.includes("math") && right.name.includes("math") && !(left.name.includes("math-end")));
        }

        return (syntaxNode.name.includes("math"));
    }
}