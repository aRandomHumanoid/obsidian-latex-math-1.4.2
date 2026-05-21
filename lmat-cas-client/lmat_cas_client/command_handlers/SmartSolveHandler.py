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


class SmartSolveCommandResult(CommandResult):
    def __init__(self, dispatch_result: DispatchResult):
        super().__init__()
        self._result = dispatch_result

    @override
    def getResponsePayload(self) -> tuple[str, dict]:
        metadata: dict = {}
        if self._result.is_multiline is not None:
            metadata["is_multiline"] = self._result.is_multiline
        if self._result.end_line is not None:
            metadata["end_line"] = self._result.end_line

        value = {
            "kind": self._result.kind,
            "toasts": [
                {"severity": t.severity, "text": t.text} for t in self._result.toasts
            ],
            "metadata": metadata,
        }

        if self._result.display_latex is not None:
            value["display_latex"] = self._result.display_latex

        return CommandResult.result(value)


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
