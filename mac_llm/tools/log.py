"""Structured logging for tool broker dispatches."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


TOOL_LOG_FIELDS: tuple[str, ...] = (
    "role",
    "requester_target",
    "tool",
    "args_hash",
    "approval_status",
    "result_summary",
    "result_token_size",
    "result_summarized",
)


def hash_tool_args(args: dict[str, Any]) -> str:
    """Return a stable sha256 hash for tool arguments."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def estimate_token_size(text: str) -> int:
    """Estimate token count from returned tool output."""
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


@dataclass(frozen=True)
class ToolDispatchLogEntry:
    """Structured log entry for one tool dispatch."""

    role: str
    requester_target: str
    tool: str
    args_hash: str
    approval_status: str
    result_summary: str
    result_token_size: int
    result_summarized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "requester_target": self.requester_target,
            "tool": self.tool,
            "args_hash": self.args_hash,
            "approval_status": self.approval_status,
            "result_summary": self.result_summary,
            "result_token_size": self.result_token_size,
            "result_summarized": self.result_summarized,
        }
