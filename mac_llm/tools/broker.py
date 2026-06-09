"""Policy-gated tool broker with fail-closed validation and logging."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mac_llm.artifacts.schemas import make_tool_result_summary
from mac_llm.tools.log import (
    ToolDispatchLogEntry,
    estimate_token_size,
    hash_tool_args,
)
from mac_llm.tools.readonly import ReadOnlyToolError, execute_read_only_tool
from mac_llm.tools.schema import (
    APPROVAL_GATED_TOOLS,
    READ_ONLY_TOOLS,
    ToolCallValidationError,
    tool_uses_path_arg,
    validate_tool_call,
)

DEFAULT_DENIED_SEGMENTS: frozenset[str] = frozenset(
    {
        ".env",
        ".ssh",
        ".gnupg",
        ".netrc",
    }
)


class ToolBrokerError(ValueError):
    """Raised when a tool request is rejected or cannot be executed."""


@dataclass(frozen=True)
class ToolDispatchResult:
    """Result of a brokered tool dispatch."""

    tool: str
    status: str
    output: str
    summarized: bool
    token_size: int


class ToolBroker:
    """Local deterministic policy-gated tool layer."""

    def __init__(
        self,
        *,
        repo_root: Path | str,
        denied_path_segments: frozenset[str] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.denied_path_segments = (
            denied_path_segments if denied_path_segments is not None else DEFAULT_DENIED_SEGMENTS
        )
        self.log_entries: list[ToolDispatchLogEntry] = []

    def dispatch(
        self,
        *,
        role: str,
        requester_target: str,
        payload: dict[str, Any],
        approved: bool = False,
    ) -> ToolDispatchResult:
        """Validate, policy-check, execute, and log one tool call."""
        try:
            call = validate_tool_call(payload)
        except ToolCallValidationError as exc:
            raise ToolBrokerError(str(exc)) from exc

        if call.tool not in READ_ONLY_TOOLS and call.tool not in APPROVAL_GATED_TOOLS:
            raise ToolBrokerError(f"unknown tool: {call.tool}")

        approval_status = self._approval_status(call.tool, approved)
        if approval_status == "denied":
            raise ToolBrokerError(f"approval required for tool: {call.tool}")

        resolved_paths = self._resolve_path_args(call.tool, call.args)

        try:
            output = self._execute(call.tool, call.args, resolved_paths)
            status = "ok"
        except ReadOnlyToolError as exc:
            raise ToolBrokerError(str(exc)) from exc

        summary = make_tool_result_summary(tool=call.tool, status=status, output=output)
        summarized = summary.summary != output.strip()
        token_size = estimate_token_size(output)
        result = ToolDispatchResult(
            tool=call.tool,
            status=status,
            output=output,
            summarized=summarized,
            token_size=token_size,
        )
        self.log_entries.append(
            ToolDispatchLogEntry(
                role=role,
                requester_target=requester_target,
                tool=call.tool,
                args_hash=hash_tool_args(call.args),
                approval_status=approval_status,
                result_summary=summary.summary,
                result_token_size=token_size,
                result_summarized=summarized,
            )
        )
        return result

    def _approval_status(self, tool: str, approved: bool) -> str:
        if tool in READ_ONLY_TOOLS:
            return "pre_approved"
        if tool in APPROVAL_GATED_TOOLS:
            return "approved" if approved else "denied"
        return "denied"

    def _resolve_path_args(self, tool: str, args: dict[str, Any]) -> dict[str, Path]:
        if not tool_uses_path_arg(tool):
            return {}

        resolved: dict[str, Path] = {}
        path_keys = ("file", "path")
        for key in path_keys:
            if key not in args:
                continue
            resolved[key] = self._resolve_repo_path(args[key])
        return resolved

    def _resolve_repo_path(self, relative_path: str) -> Path:
        if not relative_path or not isinstance(relative_path, str):
            raise ToolBrokerError("unsafe path: path must be a non-empty string")

        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ToolBrokerError("unsafe path: absolute paths are not allowed")

        resolved = (self.repo_root / candidate).resolve()
        try:
            resolved.relative_to(self.repo_root)
        except ValueError as exc:
            raise ToolBrokerError("unsafe path: escapes repo root") from exc

        parts = Path(relative_path).parts
        for part in parts:
            if part in self.denied_path_segments:
                raise ToolBrokerError(f"denied path: {relative_path}")

        for part in resolved.parts:
            if part in self.denied_path_segments:
                raise ToolBrokerError(f"denied path: {relative_path}")

        return resolved

    def _execute(
        self,
        tool: str,
        args: dict[str, Any],
        resolved_paths: dict[str, Path],
    ) -> str:
        if tool in READ_ONLY_TOOLS:
            return execute_read_only_tool(
                tool,
                self.repo_root,
                args,
                resolved_paths=resolved_paths,
            )
        raise ToolBrokerError(f"tool not implemented: {tool}")
