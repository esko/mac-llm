"""Fast→fast swap benchmark orchestration."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from mac_llm.bench.artifacts import BenchmarkArtifactWriter, RunRecord
from mac_llm.bench.metrics import MetricSource, SystemMetricProbes
from mac_llm.runtime.manager import RuntimeLifecycleError, RuntimeManager
from mac_llm.runtime.target import UnknownTargetError, get_target

DEFAULT_PROMPT = "Count from 1 to 50, one number per line."
HEALTH_POLL_INTERVAL_SECONDS = 0.25
HEALTH_TIMEOUT_SECONDS = 120.0
SUPPORTED_TARGET_ID = "local_fast"


class PromptRunner(Protocol):
    """Run a fixed benchmark prompt against a runtime base URL."""

    def run(self, *, base_url: str, prompt: str) -> PromptMetrics: ...


@dataclass(frozen=True)
class PromptMetrics:
    ttft_seconds: float | None = None
    decode_tok_per_s: float | None = None
    prompt_tok_per_s: float | None = None


@dataclass(frozen=True)
class SwapRunResult:
    ok: bool
    run_dir: Path
    message: str
    system_metrics: dict[str, dict[str, Any]] | None = None


@dataclass
class _UnavailableMetricSource:
    def read_memory_pressure(self) -> dict[str, Any] | None:
        return None

    def read_swap_used_bytes(self) -> int | None:
        return None

    def read_orphan_processes(self) -> list[str] | None:
        return None


def _health_base_url(health_url: str) -> str:
    marker = "/health"
    if health_url.endswith(marker):
        return health_url[: -len(marker)]
    return health_url.rstrip("/")


def _wait_for_health(
    manager: RuntimeManager,
    *,
    timeout_seconds: float = HEALTH_TIMEOUT_SECONDS,
    poll_seconds: float = HEALTH_POLL_INTERVAL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> float:
    deadline = monotonic() + timeout_seconds
    started = monotonic()
    while monotonic() < deadline:
        if manager.health_check().ok:
            return monotonic() - started
        sleep(poll_seconds)
    raise RuntimeLifecycleError("runtime health check timed out")


def default_prompt_runner(*, base_url: str, prompt: str) -> PromptMetrics:
    """Run the fixed prompt against an OpenAI-compatible chat endpoint."""
    payload = json.dumps(
        {
            "model": "local",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300,
            "temperature": 0.1,
        }
    ).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return PromptMetrics()

    timings = body.get("timings") if isinstance(body, dict) else None
    if not isinstance(timings, dict):
        return PromptMetrics()

    decode_tok_per_s = timings.get("predicted_per_second")
    prompt_tok_per_s = timings.get("prompt_per_second")
    prompt_ms = timings.get("prompt_ms")

    ttft_seconds: float | None = None
    if isinstance(prompt_ms, (int, float)):
        ttft_seconds = float(prompt_ms) / 1000.0

    return PromptMetrics(
        ttft_seconds=ttft_seconds,
        decode_tok_per_s=float(decode_tok_per_s)
        if isinstance(decode_tok_per_s, (int, float))
        else None,
        prompt_tok_per_s=float(prompt_tok_per_s)
        if isinstance(prompt_tok_per_s, (int, float))
        else None,
    )


def _prompt_metrics_dict(metrics: PromptMetrics) -> dict[str, Any]:
    return {
        "ttft_seconds": metrics.ttft_seconds,
        "decode_tok_per_s": metrics.decode_tok_per_s,
        "prompt_tok_per_s": metrics.prompt_tok_per_s,
    }


def _default_manager_for(target_id: str) -> RuntimeManager:
    return RuntimeManager(target=get_target(target_id))


def _ensure_inactive(manager: RuntimeManager) -> None:
    orphan = manager.orphan_check()
    if orphan.has_orphan:
        raise RuntimeLifecycleError(orphan.message)

    state = manager.status()
    if state is None or state.status != "running" or state.pid is None:
        return

    try:
        manager.stop()
    except RuntimeLifecycleError as exc:
        raise RuntimeLifecycleError(
            f"failed to stop existing managed runtime: {exc}"
        ) from exc


def _run_cycle(
    manager: RuntimeManager,
    *,
    cycle: int,
    prompt_runner: PromptRunner,
    prompt: str,
    writer: BenchmarkArtifactWriter,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    writer.append(
        RunRecord(
            event="bench.swap.cycle.start",
            status="ok",
            message=f"starting cycle {cycle}",
            metadata={"cycle": cycle},
        )
    )

    load_started = monotonic()
    manager.start()
    cold_load_seconds = monotonic() - load_started

    health_seconds = _wait_for_health(manager)

    base_url = _health_base_url(manager.target.health_url)
    prompt_metrics = prompt_runner.run(base_url=base_url, prompt=prompt)

    stop_started = monotonic()
    manager.stop()
    stop_seconds = monotonic() - stop_started

    metadata = {
        "cycle": cycle,
        "cold_load_seconds": cold_load_seconds,
        "health_seconds": health_seconds,
        "stop_seconds": stop_seconds,
        "prompt": _prompt_metrics_dict(prompt_metrics),
    }
    writer.append(
        RunRecord(
            event="bench.swap.cycle.complete",
            status="ok",
            metadata=metadata,
        )
    )
    return metadata


def _attempt_cleanup(manager: RuntimeManager) -> None:
    state = manager.status()
    if state is None or state.status != "running" or state.pid is None:
        return
    try:
        manager.stop()
    except RuntimeLifecycleError:
        return


def run_swap_benchmark(
    *,
    from_target_id: str,
    to_target_id: str,
    root: Path | None = None,
    manager_for: Callable[[str], RuntimeManager] | None = None,
    prompt_runner: PromptRunner | None = None,
    metric_source: MetricSource | None = None,
    writer: BenchmarkArtifactWriter | None = None,
    timestamp: str | None = None,
    prompt: str = DEFAULT_PROMPT,
    swap_baseline_bytes: int | None = None,
) -> SwapRunResult:
    """Run the fast→fast swap benchmark and write artifacts."""
    artifact_root = Path.cwd() if root is None else root
    resolve_manager = manager_for or _default_manager_for
    run_prompt = prompt_runner or default_prompt_runner
    source = metric_source or _UnavailableMetricSource()
    artifact_writer = writer or BenchmarkArtifactWriter(
        artifact_root,
        timestamp=timestamp,
    )

    if from_target_id != to_target_id:
        message = "from and to targets must match for fast→fast benchmark"
        artifact_writer.append(
            RunRecord(event="bench.swap.failed", status="error", message=message)
        )
        artifact_writer.write_summary()
        return SwapRunResult(
            ok=False,
            run_dir=artifact_writer.run_dir,
            message=message,
        )

    if from_target_id != SUPPORTED_TARGET_ID:
        message = f"only {SUPPORTED_TARGET_ID} → {SUPPORTED_TARGET_ID} is supported"
        artifact_writer.append(
            RunRecord(event="bench.swap.failed", status="error", message=message)
        )
        artifact_writer.write_summary()
        return SwapRunResult(
            ok=False,
            run_dir=artifact_writer.run_dir,
            message=message,
        )

    try:
        manager = resolve_manager(from_target_id)
    except UnknownTargetError as exc:
        message = str(exc)
        artifact_writer.append(
            RunRecord(event="bench.swap.failed", status="error", message=message)
        )
        artifact_writer.write_summary()
        return SwapRunResult(
            ok=False,
            run_dir=artifact_writer.run_dir,
            message=message,
        )

    artifact_writer.append(
        RunRecord(
            event="bench.swap.start",
            status="ok",
            message=f"{from_target_id} → {to_target_id}",
            metadata={"from": from_target_id, "to": to_target_id},
        )
    )

    if swap_baseline_bytes is None:
        swap_baseline_bytes = source.read_swap_used_bytes()

    probes = SystemMetricProbes(source, swap_baseline_bytes=swap_baseline_bytes)
    failure_message: str | None = None

    try:
        _ensure_inactive(manager)
        artifact_writer.append(
            RunRecord(
                event="bench.swap.ensure_inactive",
                status="ok",
                message="no managed runtime active",
            )
        )

        for cycle in (1, 2):
            _run_cycle(
                manager,
                cycle=cycle,
                prompt_runner=run_prompt,
                prompt=prompt,
                writer=artifact_writer,
            )

        system_metrics = probes.collect()
        artifact_writer.append(
            RunRecord(
                event="bench.swap.system_metrics",
                status="ok",
                metadata={"metrics": system_metrics},
            )
        )

        final_orphan = manager.orphan_check()
        if final_orphan.has_orphan:
            raise RuntimeLifecycleError(final_orphan.message)

        artifact_writer.append(
            RunRecord(
                event="bench.swap.complete",
                status="ok",
                message="benchmark completed",
            )
        )
        artifact_writer.write_summary()
        return SwapRunResult(
            ok=True,
            run_dir=artifact_writer.run_dir,
            message="benchmark completed",
            system_metrics=system_metrics,
        )
    except (RuntimeLifecycleError, UnknownTargetError) as exc:
        failure_message = str(exc)
    except Exception as exc:  # pragma: no cover - safety net for cleanup path
        failure_message = str(exc)

    _attempt_cleanup(manager)
    system_metrics = probes.collect()
    artifact_writer.append(
        RunRecord(
            event="bench.swap.system_metrics",
            status="error" if failure_message else "ok",
            metadata={"metrics": system_metrics},
        )
    )
    artifact_writer.append(
        RunRecord(
            event="bench.swap.failed",
            status="error",
            message=failure_message or "benchmark failed",
        )
    )
    artifact_writer.write_summary()
    return SwapRunResult(
        ok=False,
        run_dir=artifact_writer.run_dir,
        message=failure_message or "benchmark failed",
        system_metrics=system_metrics,
    )
