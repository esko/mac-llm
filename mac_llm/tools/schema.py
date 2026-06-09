"""Strict JSON tool-call schema and registry classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ToolCallValidationError(ValueError):
    """Raised when a tool call payload fails schema validation."""


READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "read_file_range",
        "search_text",
        "git_status",
        "git_diff",
        "list_files",
    }
)

APPROVAL_GATED_TOOLS: frozenset[str] = frozenset(
    {
        "replace_block_hash_checked",
        "propose_patch",
        "run_test_command",
    }
)

KNOWN_TOOLS: frozenset[str] = READ_ONLY_TOOLS | APPROVAL_GATED_TOOLS

_PATH_ARG_TOOLS: frozenset[str] = frozenset(
    {
        "read_file_range",
        "search_text",
        "list_files",
        "replace_block_hash_checked",
        "propose_patch",
    }
)

_OPTIONAL_TOOL_ARGS: dict[str, dict[str, type]] = {
    "search_text": {"path": str},
    "list_files": {"recursive": bool},
}

_TOOL_ARG_SPECS: dict[str, dict[str, type]] = {
    "read_file_range": {"file": str, "start_line": int, "end_line": int},
    "search_text": {"pattern": str},
    "list_files": {"path": str},
    "git_status": {},
    "git_diff": {},
    "replace_block_hash_checked": {
        "file": str,
        "old_hash": str,
        "old_text": str,
        "new_text": str,
    },
    "propose_patch": {"file": str, "patch": str},
    "run_test_command": {"command": str},
}


@dataclass(frozen=True)
class ToolCall:
    """Validated tool call with typed arguments."""

    tool: str
    args: dict[str, Any]


def _require_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ToolCallValidationError(f"{key} must be an object")
    return value


def _validate_arg_types(tool: str, args: dict[str, Any]) -> None:
    required = _TOOL_ARG_SPECS[tool]
    optional = _OPTIONAL_TOOL_ARGS.get(tool, {})
    allowed = set(required) | set(optional)

    for name, expected_type in required.items():
        if name not in args:
            raise ToolCallValidationError(f"missing required arg: {name}")
        if not isinstance(args[name], expected_type):
            raise ToolCallValidationError(
                f"arg {name!r} must be {expected_type.__name__}"
            )

    for name, expected_type in optional.items():
        if name not in args:
            continue
        if not isinstance(args[name], expected_type):
            raise ToolCallValidationError(
                f"arg {name!r} must be {expected_type.__name__}"
            )

    extra = set(args) - allowed
    if extra:
        unknown = ", ".join(sorted(extra))
        raise ToolCallValidationError(f"unknown arg(s): {unknown}")


def _validate_read_file_range(args: dict[str, Any]) -> None:
    if args["start_line"] < 1:
        raise ToolCallValidationError("start_line must be >= 1")
    if args["end_line"] < args["start_line"]:
        raise ToolCallValidationError("end_line must be >= start_line")


def validate_tool_call(data: dict[str, Any]) -> ToolCall:
    """Validate a JSON tool-call payload; fail closed on unknown or malformed input."""
    if not isinstance(data, dict):
        raise ToolCallValidationError("tool call must be an object")

    tool = data.get("tool")
    if not isinstance(tool, str) or not tool:
        raise ToolCallValidationError("tool must be a non-empty string")
    if tool not in KNOWN_TOOLS:
        raise ToolCallValidationError(f"unknown tool: {tool}")

    args = _require_mapping(data, "args")
    _validate_arg_types(tool, args)

    if tool == "read_file_range":
        _validate_read_file_range(args)

    return ToolCall(tool=tool, args=dict(args))


def tool_uses_path_arg(tool: str) -> bool:
    """Return whether the tool accepts a repo-relative path argument."""
    return tool in _PATH_ARG_TOOLS
