"""Structured benchmark record types for smoke and swap runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SmokeBenchmarkRecord:
    """Runtime-typed smoke benchmark fields for one target."""

    target_id: str
    runtime_type: str
    status: str
    load_time_s: float | None
    ttft_s: float | None
    tokens_per_second: float | None
    memory: dict[str, Any]
    orphan_status: dict[str, Any]
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target_id": self.target_id,
            "runtime_type": self.runtime_type,
            "status": self.status,
            "load_time_s": self.load_time_s,
            "ttft_s": self.ttft_s,
            "tokens_per_second": self.tokens_per_second,
            "memory": self.memory,
            "orphan_status": self.orphan_status,
        }
        if self.message is not None:
            payload["message"] = self.message
        return payload
