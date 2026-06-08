"""Tests for system metric probes (memory pressure, swap delta, orphan status)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from mac_llm.bench.metrics import (
    SystemMetricProbes,
    probe_memory_pressure,
    probe_orphan_status,
    probe_swap_delta,
)


@dataclass
class FakeMetricSource:
    memory_pressure: dict[str, object] | None = None
    swap_used_bytes: int | None = None
    orphan_processes: list[str] | None = None
    memory_pressure_error: Exception | None = None
    swap_error: Exception | None = None
    orphan_error: Exception | None = None

    def read_memory_pressure(self) -> dict[str, object] | None:
        if self.memory_pressure_error is not None:
            raise self.memory_pressure_error
        return self.memory_pressure

    def read_swap_used_bytes(self) -> int | None:
        if self.swap_error is not None:
            raise self.swap_error
        return self.swap_used_bytes

    def read_orphan_processes(self) -> list[str] | None:
        if self.orphan_error is not None:
            raise self.orphan_error
        return self.orphan_processes


def test_memory_pressure_returns_structured_value_when_available() -> None:
    source = FakeMetricSource(memory_pressure={"level": "warning", "score": 42.5})
    result = probe_memory_pressure(source)

    assert result.to_dict() == {
        "status": "ok",
        "level": "warning",
        "score": 42.5,
    }


def test_memory_pressure_returns_unavailable_when_source_missing() -> None:
    source = FakeMetricSource(memory_pressure=None)
    result = probe_memory_pressure(source)

    assert result.to_dict() == {
        "status": "unavailable",
        "reason": "memory pressure source unavailable",
    }


def test_memory_pressure_returns_unavailable_when_source_raises() -> None:
    source = FakeMetricSource(
        memory_pressure_error=RuntimeError("vm_stat failed"),
    )
    result = probe_memory_pressure(source)

    payload = result.to_dict()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "memory pressure source unavailable"


def test_swap_delta_returns_structured_value_when_available() -> None:
    source = FakeMetricSource(swap_used_bytes=1_500_000_000)
    result = probe_swap_delta(source, baseline_bytes=1_000_000_000)

    assert result.to_dict() == {
        "status": "ok",
        "baseline_bytes": 1_000_000_000,
        "current_bytes": 1_500_000_000,
        "delta_bytes": 500_000_000,
    }


def test_swap_delta_returns_unavailable_without_baseline() -> None:
    source = FakeMetricSource(swap_used_bytes=1_500_000_000)
    result = probe_swap_delta(source, baseline_bytes=None)

    assert result.to_dict() == {
        "status": "unavailable",
        "reason": "swap baseline unavailable",
    }


def test_swap_delta_returns_unavailable_when_current_missing() -> None:
    source = FakeMetricSource(swap_used_bytes=None)
    result = probe_swap_delta(source, baseline_bytes=1_000_000_000)

    assert result.to_dict() == {
        "status": "unavailable",
        "reason": "swap usage source unavailable",
    }


def test_orphan_status_reports_no_orphans_when_list_empty() -> None:
    source = FakeMetricSource(orphan_processes=[])
    result = probe_orphan_status(source)

    assert result.to_dict() == {
        "status": "ok",
        "orphaned": False,
        "count": 0,
        "processes": [],
    }


def test_orphan_status_reports_orphans_when_present() -> None:
    source = FakeMetricSource(orphan_processes=["llama-server", "mlx_engine"])
    result = probe_orphan_status(source)

    assert result.to_dict() == {
        "status": "ok",
        "orphaned": True,
        "count": 2,
        "processes": ["llama-server", "mlx_engine"],
    }


def test_orphan_status_returns_unavailable_when_source_missing() -> None:
    source = FakeMetricSource(orphan_processes=None)
    result = probe_orphan_status(source)

    assert result.to_dict() == {
        "status": "unavailable",
        "reason": "orphan status source unavailable",
    }


def test_probe_outputs_are_json_serializable() -> None:
    source = FakeMetricSource(
        memory_pressure={"level": "normal", "score": 10},
        swap_used_bytes=2_000,
        orphan_processes=["orphan-proc"],
    )
    payloads = [
        probe_memory_pressure(source).to_dict(),
        probe_swap_delta(source, baseline_bytes=1_000).to_dict(),
        probe_orphan_status(source).to_dict(),
    ]

    for payload in payloads:
        json.dumps(payload)


def test_system_metric_probes_collect_all_metrics() -> None:
    source = FakeMetricSource(
        memory_pressure={"level": "normal", "score": 5},
        swap_used_bytes=4_000,
        orphan_processes=[],
    )
    probes = SystemMetricProbes(source, swap_baseline_bytes=3_000)
    collected = probes.collect()

    assert collected == {
        "memory_pressure": {
            "status": "ok",
            "level": "normal",
            "score": 5,
        },
        "swap_delta": {
            "status": "ok",
            "baseline_bytes": 3_000,
            "current_bytes": 4_000,
            "delta_bytes": 1_000,
        },
        "orphan_status": {
            "status": "ok",
            "orphaned": False,
            "count": 0,
            "processes": [],
        },
    }
    json.dumps(collected)
