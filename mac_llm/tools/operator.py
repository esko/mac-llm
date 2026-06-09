"""Tool Operator skeleton: parse model JSON, validate, and dispatch via broker."""

from __future__ import annotations

import json
from typing import Any

from mac_llm.tools.broker import ToolBroker, ToolBrokerError, ToolDispatchResult
from mac_llm.tools.schema import ToolCallValidationError, validate_tool_call


class ToolOperatorError(ValueError):
    """Raised when model output cannot be parsed or validated."""


class ToolOperator:
    """Deterministic skeleton that validates JSON tool calls and dispatches them."""

    def __init__(self, *, broker: ToolBroker) -> None:
        self.broker = broker

    def handle_model_output(
        self,
        raw_output: str,
        *,
        role: str,
        requester_target: str,
        approved: bool = False,
    ) -> ToolDispatchResult:
        """Parse, validate, and dispatch one model-emitted tool call."""
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ToolOperatorError("invalid JSON tool call output") from exc

        if not isinstance(payload, dict):
            raise ToolOperatorError("invalid JSON tool call output")

        try:
            validate_tool_call(payload)
        except ToolCallValidationError as exc:
            raise ToolOperatorError(str(exc)) from exc

        try:
            return self.broker.dispatch(
                role=role,
                requester_target=requester_target,
                payload=payload,
                approved=approved,
            )
        except ToolBrokerError:
            raise
