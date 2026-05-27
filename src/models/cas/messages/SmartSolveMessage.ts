import { GenericPayload, StartCommandMessage } from "../../../services/CasServer";
import { LmatEnvironment } from "../LmatEnvironment";

export interface PriorBlock {
    contents: string;
}

export interface SmartSolveSectionBlock {
    contents: string;
}

export class SmartSolveArgsPayload implements GenericPayload {
    public constructor(
        public expression: string,
        public environment: LmatEnvironment,
        public prior_blocks: PriorBlock[] = [],
    ) { }
    [x: string]: unknown;
}

export class SmartSolveMessage extends StartCommandMessage {
    constructor(args: SmartSolveArgsPayload) {
        super({ command_type: 'smart-solve', start_args: args });
    }
}

export class SmartSolveSectionArgsPayload implements GenericPayload {
    public constructor(
        public environment: LmatEnvironment,
        public blocks: SmartSolveSectionBlock[],
    ) { }
    [x: string]: unknown;
}

export class SmartSolveSectionMessage extends StartCommandMessage {
    constructor(args: SmartSolveSectionArgsPayload) {
        super({ command_type: 'smart-solve-section', start_args: args });
    }
}

export type ToastSeverity = "info" | "warning" | "error";

export interface SmartSolveToast {
    severity: ToastSeverity;
    text: string;
}

// Result kinds returned by the smart-solve Python handler.
// - "display": render display_latex inline (with the result marker).
// - "silent":  no inline change; toasts only (used for stored definitions, verified equalities,
//              and stored constraints in later steps).
// - "no_op":   block was a %ref or otherwise intentionally skipped.
export type SmartSolveKind = "display" | "silent" | "no_op";

export interface SmartSolveResponse {
    kind: SmartSolveKind;
    display_latex?: string;
    toasts: SmartSolveToast[];
    metadata: {
        is_multiline?: boolean;
        end_line?: number;
    };
}

export interface SmartSolveSectionResponse {
    results: SmartSolveResponse[];
}
