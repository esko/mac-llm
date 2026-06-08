"""Benchmark artifact writer — model-independent run.jsonl + summary.md."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _default_timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True)
class RunRecord:
    """Structured in-memory event for a benchmark run."""

    event: str
    status: str
    message: str | None = None
    metadata: dict[str, Any] | None = None

    def to_event(self, *, run_id: str) -> dict[str, Any]:
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "event": self.event,
            "status": self.status,
        }
        if self.message is not None:
            event["message"] = self.message
        if self.metadata:
            event["metadata"] = self.metadata
        return event


class BenchmarkArtifactWriter:
    """Writes benchmark runs under benchmarks/runs/<timestamp>/."""

    def __init__(
        self,
        root: Path,
        *,
        timestamp: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self._root = root
        self._timestamp = timestamp or _default_timestamp()
        self._run_id = run_id or self._timestamp
        self._run_dir = root / "benchmarks" / "runs" / self._timestamp
        self._jsonl_path = self._run_dir / "run.jsonl"
        self._summary_path = self._run_dir / "summary.md"
        self._records: list[dict[str, Any]] = []

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    def ensure_run_dir(self) -> Path:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        return self._run_dir

    def append(self, record: RunRecord) -> None:
        self.ensure_run_dir()
        event = record.to_event(run_id=self._run_id)
        self._records.append(event)
        with self._jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def write_summary(self) -> Path:
        self.ensure_run_dir()
        rel_dir = self._run_dir.relative_to(self._root)
        lines = [
            f"# Benchmark run {self._run_id}",
            "",
            f"- Run directory: `{rel_dir}`",
            f"- Events: {len(self._records)}",
            "",
            "## Events",
            "",
        ]
        for event in self._records:
            name = event.get("event", "unknown")
            status = event.get("status", "unknown")
            line = f"- **{name}** ({status})"
            message = event.get("message")
            if message:
                line += f": {message}"
            lines.append(line)

        self._summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self._summary_path
