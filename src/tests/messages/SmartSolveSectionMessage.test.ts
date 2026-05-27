import { expect, test } from "vitest";
import { response_verifier, server } from "../setup";
import {
    SmartSolveSectionArgsPayload,
    SmartSolveSectionMessage,
    SmartSolveSectionResponse,
} from "../../models/cas/messages/SmartSolveMessage";
import { LmatEnvironment } from "../../models/cas/LmatEnvironment";

async function dispatchSection(
    blocks: string[],
    environment: LmatEnvironment = new LmatEnvironment(),
): Promise<SmartSolveSectionResponse> {
    const response = await server.send(new SmartSolveSectionMessage(
        new SmartSolveSectionArgsPayload(
            environment,
            blocks.map((contents) => ({ contents })),
        ),
    )).response;

    return response_verifier.verifyResponse<SmartSolveSectionResponse>(response);
}

test("Smart Solve section: blocks share sequential context", async () => {
    const result = await dispatchSection(["x = 3", "x + 1 ="]);

    expect(result.results).toHaveLength(2);
    expect(result.results[0].kind).toBe("display");
    expect(result.results[0].display_latex).toBe("x = 3");
    expect(result.results[1].kind).toBe("display");
    expect(result.results[1].display_latex).toBe("4");
});