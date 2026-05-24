export interface BlockUpdate {
    from: number;
    to: number;
    new_text: string;
}

export function buildSmartSolveBlockText(original_raw: string, contents: string): string {
    const delimiter = original_raw.startsWith("$$") ? "$$" : "$";
    return `${delimiter}${contents}${delimiter}\n`;
}

export function computeCursorOffset(target_update: BlockUpdate, prior_updates: BlockUpdate[]): number {
    const shift = prior_updates
        .filter(update => update.from < target_update.from)
        .reduce((accumulator, update) => accumulator + (update.new_text.length - (update.to - update.from)), 0);

    return target_update.from + target_update.new_text.length + shift;
}