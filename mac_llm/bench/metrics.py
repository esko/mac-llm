"""System metric probes for benchmark runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class MetricSource(Protocol):
    """Injectable source for system metrics."""

    def read_memory_pressure(self) -> dict[str, Any] | None: ...

    def read_swap_used_bytes(self) -> int | None: ...

    def read_orphan_processes(self) -> list[str] | None: ...


@dataclass(frozen=True)
class ProbeResult:
    status: str
    reason: str | None = None
    level: str | None = None
    score: float | None = None
    baseline_bytes: int | None = None
    current_bytes: int | None = None
    delta_bytes: int | None = None
    orphaned: bool | None = None
    count: int | None = None
    processes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.level is not None:
            payload["level"] = self.level
        if self.score is not None:
            payload["score"] = self.score
        if self.baseline_bytes is not None:
            payload["baseline_bytes"] = self.baseline_bytes
        if self.current_bytes is not None:
            payload["current_bytes"] = self.current_bytes
        if self.delta_bytes is not None:
            payload["delta_bytes"] = self.delta_bytes
        if self.orphaned is not None:
            payload["orphaned"] = self.orphaned
        if self.count is not None:
            payload["count"] = self.count
        if self.processes is not None:
            payload["processes"] = self.processes
        return payload


def _unavailable(reason: str) -> ProbeResult:
    return ProbeResult(status="unavailable", reason=reason)


def probe_memory_pressure(source: MetricSource) -> ProbeResult:
    try:
        reading = source.read_memory_pressure()
    except Exception:
        return _unavailable("memory pressure source unavailable")

    if reading is None:
        return _unavailable("memory pressure source unavailable")

    level = reading.get("level")
    score = reading.get("score")
    if not isinstance(level, str):
        return _unavailable("memory pressure source unavailable")

    normalized_score = float(score) if isinstance(score, (int, float)) else None
    return ProbeResult(status="ok", level=level, score=normalized_score)


def probe_swap_delta(
    source: MetricSource,
    *,
    baseline_bytes: int | None,
) -> ProbeResult:
    if baseline_bytes is None:
        return _unavailable("swap baseline unavailable")

    try:
        current_bytes = source.read_swap_used_bytes()
    except Exception:
        return _unavailable("swap usage source unavailable")

    if current_bytes is None:
        return _unavailable("swap usage source unavailable")

    return ProbeResult(
        status="ok",
        baseline_bytes=baseline_bytes,
        current_bytes=current_bytes,
        delta_bytes=current_bytes - baseline_bytes,
    )


def probe_orphan_status(source: MetricSource) -> ProbeResult:
    try:
        processes = source.read_orphan_processes()
    except Exception:
        return _unavailable("orphan status source unavailable")

    if processes is None:
        return _unavailable("orphan status source unavailable")

    return ProbeResult(
        status="ok",
        orphaned=len(processes) > 0,
        count=len(processes),
        processes=list(processes),
    )


class SystemMetricProbes:
    """Collect memory pressure, swap delta, and orphan status probes."""

    def __init__(
        self,
        source: MetricSource,
        *,
        swap_baseline_bytes: int | None = None,
    ) -> None:
        self._source = source
        self._swap_baseline_bytes = swap_baseline_bytes

    def collect(self) -> dict[str, dict[str, Any]]:
        return {
            "memory_pressure": probe_memory_pressure(self._source).to_dict(),
            "swap_delta": probe_swap_delta(
                self._source,
                baseline_bytes=self._swap_baseline_bytes,
            ).to_dict(),
            "orphan_status": probe_orphan_status(self._source).to_dict(),
        }
