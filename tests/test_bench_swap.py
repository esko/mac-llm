"""Tests for bench swap orchestration without a real model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mac_llm.bench.artifacts import BenchmarkArtifactWriter
from mac_llm.bench.metrics import MetricSource
from mac_llm.bench.swap import (
    DEFAULT_PROMPT,
    PromptMetrics,
    PromptRunner,
    SwapRunResult,
    run_swap_benchmark,
)
from mac_llm.runtime.manager import RuntimeLifecycleError, RuntimeManager
from mac_llm.runtime.probes import OrphanCheckResult
from mac_llm.runtime.state import RuntimeState, save_state
from mac_llm.runtime.target import RuntimeTarget


def _target(tmp_path: Path, *, target_id: str = "local_fast") -> RuntimeTarget:
    return RuntimeTarget(
        target_id=target_id,
        runtime_type="test",
        command=("echo", "hello"),
        port=18080,
        health_url="http://127.0.0.1:18080/health",
        log_path=tmp_path / "logs" / f"{target_id}.log",
        state_path=tmp_path / "state" / f"{target_id}.json",
        stop_timeout=5,
        model_config_ref="models.test_fast",
    )


@dataclass
class FakeMetricSource:
    memory_pressure: dict[str, object] | None = None
    swap_used_bytes: int | None = None
    orphan_processes: list[str] | None = None

    def read_memory_pressure(self) -> dict[str, object] | None:
        return self.memory_pressure

    def read_swap_used_bytes(self) -> int | None:
        return self.swap_used_bytes

    def read_orphan_processes(self) -> list[str] | None:
        return self.orphan_processes


@dataclass
class RecordingPromptRunner:
    calls: list[tuple[str, str]] = field(default_factory=list)
    metrics: PromptMetrics = field(
        default_factory=lambda: PromptMetrics(
            ttft_seconds=0.25,
            decode_tok_per_s=42.0,
            prompt_tok_per_s=100.0,
        )
    )

    def run(self, *, base_url: str, prompt: str) -> PromptMetrics:
        self.calls.append((base_url, prompt))
        return self.metrics


@dataclass
class FakeRuntimeHarness:
    target: RuntimeTarget
    started_pid: int = 501
    running: bool = False
    start_calls: int = 0
    stop_calls: int = 0
    orphan_results: list[OrphanCheckResult] = field(default_factory=list)
    start_should_fail: bool = False
    health_ok: bool = True

    def manager(self) -> RuntimeManager:
        harness = self

        def fake_start(command: tuple[str, ...], log_path: Path) -> int:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            return harness.started_pid

        def fake_stop(pid: int, timeout: int) -> bool:
            harness.running = False
            return True

        manager = RuntimeManager(
            target=self.target,
            port_pid_fn=lambda _port: None,
            start_process=fake_start,
            stop_process=fake_stop,
        )

        original_start = manager.start
        original_stop = manager.stop
        original_health = manager.health_check
        original_orphan = manager.orphan_check

        def wrapped_start(*args, **kwargs):
            harness.start_calls += 1
            if harness.start_should_fail:
                raise RuntimeLifecycleError("runtime command unavailable")
            state = original_start(*args, **kwargs)
            harness.running = True
            return state

        def wrapped_stop(*args, **kwargs):
            harness.stop_calls += 1
            return original_stop(*args, **kwargs)

        def wrapped_health():
            from mac_llm.runtime.probes import HealthCheckResult

            if harness.health_ok:
                return HealthCheckResult(ok=True, message="healthy")
            return HealthCheckResult(ok=False, message="unhealthy")

        def wrapped_orphan():
            if harness.orphan_results:
                return harness.orphan_results.pop(0)
            return OrphanCheckResult(
                has_orphan=False,
                port_occupied=False,
                occupying_pid=None,
                stale_state_pid=None,
                message="no orphan detected",
            )

        manager.start = wrapped_start  # type: ignore[method-assign]
        manager.stop = wrapped_stop  # type: ignore[method-assign]
        manager.health_check = wrapped_health  # type: ignore[method-assign]
        manager.orphan_check = wrapped_orphan  # type: ignore[method-assign]
        return manager


def test_successful_swap_runs_two_cycles_and_writes_artifacts(tmp_path: Path) -> None:
    target = _target(tmp_path)
    harness = FakeRuntimeHarness(target=target)
    prompt_runner = RecordingPromptRunner()
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")

    result = run_swap_benchmark(
        from_target_id="local_fast",
        to_target_id="local_fast",
        root=tmp_path,
        manager_for=lambda _target_id: harness.manager(),
        prompt_runner=prompt_runner,
        metric_source=FakeMetricSource(
            memory_pressure={"level": "normal", "score": 1.0},
            swap_used_bytes=2_000,
            orphan_processes=[],
        ),
        writer=writer,
        swap_baseline_bytes=1_000,
    )

    assert result.ok is True
    assert harness.start_calls == 2
    assert harness.stop_calls == 2
    assert len(prompt_runner.calls) == 2
    assert prompt_runner.calls[0][1] == DEFAULT_PROMPT

    jsonl_path = writer.run_dir / "run.jsonl"
    summary_path = writer.run_dir / "summary.md"
    assert jsonl_path.is_file()
    assert summary_path.is_file()

    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    event_names = [event["event"] for event in events]
    assert "bench.swap.start" in event_names
    assert event_names.count("bench.swap.cycle.complete") == 2
    assert "bench.swap.complete" in event_names

    cycle_events = [
        event for event in events if event["event"] == "bench.swap.cycle.complete"
    ]
    assert cycle_events[0]["metadata"]["cold_load_seconds"] >= 0
    assert cycle_events[0]["metadata"]["prompt"]["ttft_seconds"] == 0.25
    assert cycle_events[0]["metadata"]["prompt"]["decode_tok_per_s"] == 42.0


def test_failure_writes_artifact_when_runtime_unavailable(tmp_path: Path) -> None:
    target = _target(tmp_path)
    harness = FakeRuntimeHarness(target=target, start_should_fail=True)
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120001Z")

    result = run_swap_benchmark(
        from_target_id="local_fast",
        to_target_id="local_fast",
        root=tmp_path,
        manager_for=lambda _target_id: harness.manager(),
        prompt_runner=RecordingPromptRunner(),
        metric_source=FakeMetricSource(),
        writer=writer,
    )

    assert result.ok is False
    assert "runtime command unavailable" in result.message

    events = [
        json.loads(line)
        for line in (writer.run_dir / "run.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "bench.swap.failed" for event in events)
    assert (writer.run_dir / "summary.md").is_file()


def test_failure_when_orphan_detected_before_start(tmp_path: Path) -> None:
    target = _target(tmp_path)
    harness = FakeRuntimeHarness(
        target=target,
        orphan_results=[
            OrphanCheckResult(
                has_orphan=True,
                port_occupied=True,
                occupying_pid=999,
                stale_state_pid=None,
                message="orphan detected: port 18080 held by pid 999",
            )
        ],
    )
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120002Z")

    result = run_swap_benchmark(
        from_target_id="local_fast",
        to_target_id="local_fast",
        root=tmp_path,
        manager_for=lambda _target_id: harness.manager(),
        prompt_runner=RecordingPromptRunner(),
        metric_source=FakeMetricSource(),
        writer=writer,
    )

    assert result.ok is False
    assert "orphan detected" in result.message
    assert harness.start_calls == 0


def test_stops_existing_runtime_before_benchmark(tmp_path: Path) -> None:
    target = _target(tmp_path)
    save_state(
        target.state_path,
        RuntimeState(
            target_id=target.target_id,
            pid=777,
            port=target.port,
            start_time=1.0,
            stop_timeout=5,
            last_error=None,
            status="running",
        ),
    )
    harness = FakeRuntimeHarness(target=target, started_pid=888)
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120003Z")

    result = run_swap_benchmark(
        from_target_id="local_fast",
        to_target_id="local_fast",
        root=tmp_path,
        manager_for=lambda _target_id: harness.manager(),
        prompt_runner=RecordingPromptRunner(),
        metric_source=FakeMetricSource(orphan_processes=[]),
        writer=writer,
    )

    assert result.ok is True
    assert harness.stop_calls >= 1


def test_no_orphan_remains_after_success(tmp_path: Path) -> None:
    target = _target(tmp_path)
    harness = FakeRuntimeHarness(target=target)
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120004Z")

    result = run_swap_benchmark(
        from_target_id="local_fast",
        to_target_id="local_fast",
        root=tmp_path,
        manager_for=lambda _target_id: harness.manager(),
        prompt_runner=RecordingPromptRunner(),
        metric_source=FakeMetricSource(orphan_processes=[]),
        writer=writer,
    )

    assert result.ok is True
    assert result.system_metrics is not None
    assert result.system_metrics["orphan_status"]["orphaned"] is False
