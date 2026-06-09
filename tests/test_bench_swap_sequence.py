"""Tests for bench swap-sequence orchestration without a real model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mac_llm.bench.artifacts import BenchmarkArtifactWriter
from mac_llm.bench.metrics import MetricSource
from mac_llm.bench.swap import DEFAULT_PROMPT, PromptMetrics, PromptRunner
from mac_llm.bench.swap_sequence import run_swap_sequence_benchmark
from mac_llm.runtime.manager import RuntimeLifecycleError, RuntimeManager
from mac_llm.runtime.probes import OrphanCheckResult
from mac_llm.runtime.target import RuntimeTarget


def _target(
    tmp_path: Path,
    *,
    target_id: str = "local_fast",
    port: int = 18080,
) -> RuntimeTarget:
    runtime_type = "llama.cpp" if target_id == "local_fast" else "mlx_sniper"
    command = ("echo", f"hello-{target_id}")
    health_path = "/health" if target_id == "local_fast" else "/api/tags"
    return RuntimeTarget(
        target_id=target_id,
        runtime_type=runtime_type,
        command=command,
        port=port,
        health_url=f"http://127.0.0.1:{port}{health_path}",
        log_path=tmp_path / "logs" / f"{target_id}.log",
        state_path=tmp_path / "state" / f"{target_id}.json",
        stop_timeout=5,
        model_config_ref=f"models.{target_id}",
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


def _harnesses_for_sequence(
    tmp_path: Path,
    target_ids: list[str],
) -> dict[str, FakeRuntimeHarness]:
    harnesses: dict[str, FakeRuntimeHarness] = {}
    for index, target_id in enumerate(target_ids):
        port = 18080 + index
        target = _target(tmp_path, target_id=target_id, port=port)
        harnesses[target_id] = FakeRuntimeHarness(target=target, started_pid=500 + index)
    return harnesses


def test_successful_sequence_runs_all_steps_with_complete_records(tmp_path: Path) -> None:
    target_ids = ["local_fast", "local_deep_moe", "local_fast"]
    harnesses = _harnesses_for_sequence(tmp_path, target_ids)
    prompt_runner = RecordingPromptRunner()
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260609T120000Z")

    result = run_swap_sequence_benchmark(
        target_ids=target_ids,
        root=tmp_path,
        manager_for=lambda target_id: harnesses[target_id].manager(),
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
    assert sum(h.start_calls for h in harnesses.values()) == 3
    assert sum(h.stop_calls for h in harnesses.values()) == 3
    assert len(prompt_runner.calls) == 3
    assert all(call[1] == DEFAULT_PROMPT for call in prompt_runner.calls)

    jsonl_path = writer.run_dir / "run.jsonl"
    summary_path = writer.run_dir / "summary.md"
    assert jsonl_path.is_file()
    assert summary_path.is_file()

    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    event_names = [event["event"] for event in events]
    assert "bench.swap_sequence.start" in event_names
    assert event_names.count("bench.swap_sequence.step.complete") == 3
    assert "bench.swap_sequence.complete" in event_names

    step_events = [
        event
        for event in events
        if event["event"] == "bench.swap_sequence.step.complete"
    ]
    assert [event["metadata"]["target_id"] for event in step_events] == target_ids

    first_step = step_events[0]["metadata"]
    assert first_step["runtime_type"] == "llama.cpp"
    assert first_step["command"] == ["echo", "hello-local_fast"]
    assert first_step["load_time_s"] >= 0
    assert first_step["health_time_s"] >= 0
    assert first_step["ttft_s"] == 0.25
    assert first_step["tokens_per_second"] == 42.0
    assert first_step["stop_time_s"] >= 0
    assert first_step["memory_pressure"]["status"] == "ok"
    assert first_step["swap_delta"]["status"] == "ok"
    assert first_step["orphan_check"]["orphaned"] is False
    assert first_step["cache_status"]["status"] == "not_used"

    deep_step = step_events[1]["metadata"]
    assert deep_step["runtime_type"] == "mlx_sniper"
    assert deep_step["command"] == ["echo", "hello-local_deep_moe"]


def test_mid_sequence_failure_writes_artifact_and_cleans_up(tmp_path: Path) -> None:
    target_ids = ["local_fast", "local_deep_moe", "local_fast"]
    harnesses = _harnesses_for_sequence(tmp_path, target_ids)
    harnesses["local_deep_moe"].start_should_fail = True
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260609T120001Z")

    result = run_swap_sequence_benchmark(
        target_ids=target_ids,
        root=tmp_path,
        manager_for=lambda target_id: harnesses[target_id].manager(),
        prompt_runner=RecordingPromptRunner(),
        metric_source=FakeMetricSource(orphan_processes=[]),
        writer=writer,
    )

    assert result.ok is False
    assert "runtime command unavailable" in result.message
    assert harnesses["local_fast"].start_calls == 1
    assert harnesses["local_deep_moe"].start_calls == 1
    assert harnesses["local_fast"].stop_calls == 1

    events = [
        json.loads(line)
        for line in (writer.run_dir / "run.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "bench.swap_sequence.failed" for event in events)
    assert (writer.run_dir / "summary.md").is_file()
    completed_steps = [
        event
        for event in events
        if event["event"] == "bench.swap_sequence.step.complete"
    ]
    assert len(completed_steps) == 1


def test_no_orphan_remains_after_success_or_failure(tmp_path: Path) -> None:
    target_ids = ["local_fast", "local_deep_moe"]
    harnesses = _harnesses_for_sequence(tmp_path, target_ids)
    harnesses["local_deep_moe"].orphan_results = [
        OrphanCheckResult(
            has_orphan=True,
            port_occupied=True,
            occupying_pid=999,
            stale_state_pid=None,
            message="orphan detected: port held by pid 999",
        )
    ]
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260609T120002Z")

    result = run_swap_sequence_benchmark(
        target_ids=target_ids,
        root=tmp_path,
        manager_for=lambda target_id: harnesses[target_id].manager(),
        prompt_runner=RecordingPromptRunner(),
        metric_source=FakeMetricSource(orphan_processes=[]),
        writer=writer,
    )

    assert result.ok is False
    assert "orphan detected" in result.message
    assert harnesses["local_fast"].stop_calls == 1
