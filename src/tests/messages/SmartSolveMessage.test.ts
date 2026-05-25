import { expect, test } from "vitest";
import { response_verifier, server } from "../setup";
import {
    SmartSolveArgsPayload,
    SmartSolveMessage,
    SmartSolveResponse,
} from "../../models/cas/messages/SmartSolveMessage";
import { LmatEnvironment } from "../../models/cas/LmatEnvironment";

async function dispatch(
    expression: string,
    options: {
        environment?: LmatEnvironment;
        prior_blocks?: { contents: string }[];
    } = {},
): Promise<SmartSolveResponse> {
    const env = options.environment ?? new LmatEnvironment();
    const payload = new SmartSolveArgsPayload(expression, env, options.prior_blocks ?? []);
    const response = await server.send(new SmartSolveMessage(payload)).response;
    return response_verifier.verifyResponse<SmartSolveResponse>(response);
}

test("Smart Solve: fresh single-variable assignment displays x = value", async () => {
    const r = await dispatch("x = 3");
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("x = 3");
});

test("Smart Solve: solves linear equation and displays result", async () => {
    const r = await dispatch("x + 1 = 5");
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("x = 4");
});

test("Smart Solve: trailing equals evaluates left side", async () => {
    const r = await dispatch("1 + 1 =");
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("2");
});

test("Smart Solve: verified equality is silent", async () => {
    const r = await dispatch("2 + 2 = 4");
    expect(r.kind).toBe("silent");
    expect(r.display_latex).toBeUndefined();
    expect(r.toasts).toEqual([]);
});

test("Smart Solve: contradiction emits error toast", async () => {
    const env = new LmatEnvironment(
        {},
        [
            { name_expr: "x", value_expr: "3" },
            { name_expr: "y", value_expr: "5" },
        ],
    );
    const r = await dispatch("x + y = 10", { environment: env });
    expect(r.kind).toBe("silent");
    expect(r.toasts.some(t => t.severity === "error" && /Contradiction/.test(t.text))).toBe(true);
});

test("Smart Solve: %ref blocks return no_op", async () => {
    const r = await dispatch("E = mc^2 \\quad %\\text{ref}");
    expect(r.kind).toBe("no_op");
    expect(r.toasts).toEqual([]);
});

test("Smart Solve: prior blocks contribute to context (notebook semantics)", async () => {
    const r = await dispatch("x + 1 =", {
        prior_blocks: [{ contents: "x = 3" }],
    });
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("4");
});

test("Smart Solve: constraint system resolves across two prior blocks", async () => {
    const r = await dispatch("x - y = 2", {
        prior_blocks: [{ contents: "x + y = 10" }],
    });
    expect(r.kind).toBe("silent");
    const info = r.toasts.filter(t => t.severity === "info");
    const all_text = info.map(t => t.text).join(" ");
    expect(all_text).toMatch(/x/);
    expect(all_text).toMatch(/y/);
    expect(all_text).toMatch(/6/);
    expect(all_text).toMatch(/4/);
});

test("Smart Solve: multi-solution emits warning with both roots", async () => {
    const r = await dispatch("x^2 = 4");
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("x = 2");
    const warnings = r.toasts.filter(t => t.severity === "warning");
    expect(warnings.length).toBeGreaterThan(0);
    expect(warnings[0].text).toMatch(/Multiple solutions/);
});

test("Smart Solve: replayed multi-solution prints the stored set", async () => {
    const r = await dispatch("x =", {
        prior_blocks: [{ contents: "x^2 = 4" }],
    });
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("\\left\\{-2, 2\\right\\}");
    expect(r.toasts.some(t => t.severity === "warning")).toBe(false);
});

test("Smart Solve: replayed multi-solution warns when used in a calculation", async () => {
    const r = await dispatch("x + 1 =", {
        prior_blocks: [{ contents: "x^2 = 4" }],
    });
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("3");
    const warnings = r.toasts.filter(t => t.severity === "warning");
    expect(warnings).toHaveLength(1);
    expect(warnings[0].text).toMatch(/Multiple stored values for x/);
    expect(warnings[0].text).toMatch(/Using 2/);
});

test("Smart Solve: override emits info toast on value change", async () => {
    const env = new LmatEnvironment({}, [{ name_expr: "x", value_expr: "3" }]);
    const r = await dispatch("x + 1 = 5", { environment: env });
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("x = 4");
    const info = r.toasts.filter(t => t.severity === "info");
    expect(info.length).toBe(1);
    expect(info[0].text).toMatch(/Overriding/);
});

test("Smart Solve: sig_figs override in environment", async () => {
    const env = new LmatEnvironment({}, [], undefined, undefined, 5);
    const r = await dispatch("1 / 3", { environment: env });
    expect(r.kind).toBe("display");
    expect(r.display_latex).toBe("0.33333");
});

test("Smart Solve: real domain hints at complex when no real solution", async () => {
    const env = new LmatEnvironment({}, [], undefined, "S.Reals");
    const r = await dispatch("x^2 + 1 = 0", { environment: env });
    expect(r.kind).toBe("silent");
    const warnings = r.toasts.filter(t => t.severity === "warning");
    expect(warnings.some(t => /complex/i.test(t.text))).toBe(true);
});

test("Smart Solve: undefined variable errors", async () => {
    const r = await dispatch("x + 5");
    expect(r.kind).toBe("silent");
    expect(r.toasts.some(t => t.severity === "error" && /Undefined/.test(t.text))).toBe(true);
});

test("Smart Solve: garbage LaTeX returns error gracefully (no crash)", async () => {
    const r = await dispatch("!!! not valid ###");
    expect(r.kind).toBe("silent");
    expect(r.toasts.some(t => t.severity === "error")).toBe(true);
});
