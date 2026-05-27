from typing import override

from pydantic import BaseModel

from lmat_cas_client.compiling.Compiler import LatexToSympyCompiler
from lmat_cas_client.LmatEnvironment import LmatEnvironment
from lmat_cas_client.smart_solve.Dispatcher import (
    DispatchResult,
    SmartSolveDispatcher,
)

from .CommandHandler import CommandHandler, CommandResult


class PriorBlock(BaseModel):
    contents: str


class SmartSolveMessage(BaseModel):
    expression: str
    environment: LmatEnvironment
    prior_blocks: list[PriorBlock] = []


class SmartSolveSectionBlock(BaseModel):
    contents: str


class SmartSolveSectionMessage(BaseModel):
    environment: LmatEnvironment
    blocks: list[SmartSolveSectionBlock] = []


def _serialize_dispatch_result(dispatch_result: DispatchResult) -> dict:
    metadata: dict = {}
    if dispatch_result.is_multiline is not None:
        metadata["is_multiline"] = dispatch_result.is_multiline
    if dispatch_result.end_line is not None:
        metadata["end_line"] = dispatch_result.end_line

    value = {
        "kind": dispatch_result.kind,
        "toasts": [
            {"severity": t.severity, "text": t.text} for t in dispatch_result.toasts
        ],
        "metadata": metadata,
    }

    if dispatch_result.display_latex is not None:
        value["display_latex"] = dispatch_result.display_latex

    return value


class SmartSolveCommandResult(CommandResult):
    def __init__(self, dispatch_result: DispatchResult):
        super().__init__()
        self._result = dispatch_result

    @override
    def getResponsePayload(self) -> tuple[str, dict]:
        return CommandResult.result(_serialize_dispatch_result(self._result))


class SmartSolveSectionCommandResult(CommandResult):
    def __init__(self, dispatch_results: list[DispatchResult]):
        super().__init__()
        self._results = dispatch_results

    @override
    def getResponsePayload(self) -> tuple[str, dict]:
        return CommandResult.result({
            "results": [_serialize_dispatch_result(result) for result in self._results],
        })


class SmartSolveHandler(CommandHandler):
    """
    Handler for the new "smart-solve" command (design_docs.md). Step 1 scope:
    dispatch a single math block to one of: define, evaluate, solve, verify,
    or error. Section walking + constraint accumulation come in later steps.
    """

    def __init__(self, compiler: LatexToSympyCompiler):
        super().__init__()
        self._dispatcher = SmartSolveDispatcher(compiler)

    @override
    def handle(self, message) -> SmartSolveCommandResult:
        message = SmartSolveMessage.model_validate(message)
        prior_latex = [b.contents for b in message.prior_blocks]
        result = self._dispatcher.dispatch(
            message.expression,
            message.environment,
            prior_blocks=prior_latex,
        )
        return SmartSolveCommandResult(result)


class SmartSolveSectionHandler(CommandHandler):
    def __init__(self, compiler: LatexToSympyCompiler):
        super().__init__()
        self._dispatcher = SmartSolveDispatcher(compiler)

    @override
    def handle(self, message) -> SmartSolveSectionCommandResult:
        message = SmartSolveSectionMessage.model_validate(message)
        results = self._dispatcher.dispatch_section(
            [block.contents for block in message.blocks],
            message.environment,
        )
        return SmartSolveSectionCommandResult(results)
