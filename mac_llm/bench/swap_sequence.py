"""Ordered swap-sequence benchmark orchestration (start → prompt → stop per target)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from mac_llm.bench.artifacts import BenchmarkArtifactWriter, RunRecord
from mac_llm.bench.metrics import MetricSource, SystemMetricProbes
from mac_llm.bench.swap import (
    DEFAULT_PROMPT,
    PromptRunner,
    _attempt_cleanup,
    _ensure_inactive,
    _wait_for_health,
    default_prompt_runner,
)
from mac_llm.runtime.manager import RuntimeLifecycleError, RuntimeManager
from mac_llm.runtime.target import RuntimeTarget, UnknownTargetError, get_target

ALLOWED_TARGET_IDS = frozenset({"local_fast", "local_deep_moe"})
DEEP_TARGET_ID = "local_deep_moe"
CACHE_STATUS_NOT_USED = {
    "status": "not_used",
    "reason": "prompt cache not used in swap-sequence benchmark",
}


@dataclass(frozen=True)
class SwapSequenceRunResult:
    ok: bool
    run_dir: Path
    message: str
    step_records: list[dict[str, Any]] | None = None


@dataclass
class _UnavailableMetricSource:
    def read_memory_pressure(self) -> dict[str, Any] | None:
        return None

    def read_swap_used_bytes(self) -> int | None:
        return None

    def read_orphan_processes(self) -> list[str] | None:
        return None


def _base_url_from_target(target: RuntimeTarget) -> str:
    parsed = urlparse(target.health_url)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _default_manager_for(target_id: str) -> RuntimeManager:
    return RuntimeManager(target=get_target(target_id))


def _validate_target_ids(target_ids: list[str]) -> str | None:
    if not target_ids:
        return "at least one target id is required"

    unknown = [target_id for target_id in target_ids if target_id not in ALLOWED_TARGET_IDS]
    if unknown:
        return f"unsupported target id(s): {', '.join(unknown)}"

    deep_count = sum(1 for target_id in target_ids if target_id == DEEP_TARGET_ID)
    if deep_count > 1:
        return "only one deep target is allowed in a swap sequence"

    return None


def _step_metrics(
    probes: SystemMetricProbes,
    *,
    orphan_check: dict[str, Any],
) -> dict[str, Any]:
    collected = probes.collect()
    return {
        "memory_pressure": collected["memory_pressure"],
        "swap_delta": collected["swap_delta"],
        "orphan_check": orphan_check,
        "cache_status": CACHE_STATUS_NOT_USED,
    }


def _orphan_check_dict(manager: RuntimeManager) -> dict[str, Any]:
    result = manager.orphan_check()
    return {
        "status": "ok" if not result.has_orphan else "error",
        "orphaned": result.has_orphan,
        "message": result.message,
    }


def _run_sequence_step(
    manager: RuntimeManager,
    *,
    step: int,
    prompt_runner: PromptRunner,
    prompt: str,
    probes: SystemMetricProbes,
    writer: BenchmarkArtifactWriter,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    target = manager.target
    writer.append(
        RunRecord(
            event="bench.swap_sequence.step.start",
            status="ok",
            message=f"starting step {step} for {target.target_id}",
            metadata={"step": step, "target_id": target.target_id},
        )
    )

    _ensure_inactive(manager)

    load_started = monotonic()
    manager.start()
    load_time_s = monotonic() - load_started

    health_time_s = _wait_for_health(manager)

    base_url = _base_url_from_target(target)
    prompt_metrics = prompt_runner.run(base_url=base_url, prompt=prompt)

    stop_started = monotonic()
    manager.stop()
    stop_time_s = monotonic() - stop_started

    orphan_check = _orphan_check_dict(manager)
    if orphan_check["orphaned"]:
        raise RuntimeLifecycleError(str(orphan_check["message"]))

    step_metrics = _step_metrics(probes, orphan_check=orphan_check)
    metadata = {
        "step": step,
        "target_id": target.target_id,
        "runtime_type": target.runtime_type,
        "command": list(target.command),
        "load_time_s": load_time_s,
        "health_time_s": health_time_s,
        "ttft_s": prompt_metrics.ttft_seconds,
        "tokens_per_second": prompt_metrics.decode_tok_per_s,
        "stop_time_s": stop_time_s,
        **step_metrics,
    }
    writer.append(
        RunRecord(
            event="bench.swap_sequence.step.complete",
            status="ok",
            metadata=metadata,
        )
    )
    return metadata


def run_swap_sequence_benchmark(
    *,
    target_ids: list[str],
    root: Path | None = None,
    manager_for: Callable[[str], RuntimeManager] | None = None,
    prompt_runner: PromptRunner | None = None,
    metric_source: MetricSource | None = None,
    writer: BenchmarkArtifactWriter | None = None,
    timestamp: str | None = None,
    prompt: str = DEFAULT_PROMPT,
    swap_baseline_bytes: int | None = None,
) -> SwapSequenceRunResult:
    """Run an ordered swap sequence benchmark and write artifacts."""
    artifact_root = Path.cwd() if root is None else root
    resolve_manager = manager_for or _default_manager_for
    run_prompt = prompt_runner or default_prompt_runner
    source = metric_source or _UnavailableMetricSource()
    artifact_writer = writer or BenchmarkArtifactWriter(
        artifact_root,
        timestamp=timestamp,
    )

    validation_error = _validate_target_ids(target_ids)
    if validation_error is not None:
        artifact_writer.append(
            RunRecord(
                event="bench.swap_sequence.failed",
                status="error",
                message=validation_error,
            )
        )
        artifact_writer.write_summary()
        return SwapSequenceRunResult(
            ok=False,
            run_dir=artifact_writer.run_dir,
            message=validation_error,
        )

    artifact_writer.append(
        RunRecord(
            event="bench.swap_sequence.start",
            status="ok",
            message=" → ".join(target_ids),
            metadata={"targets": list(target_ids)},
        )
    )

    if swap_baseline_bytes is None:
        swap_baseline_bytes = source.read_swap_used_bytes()

    probes = SystemMetricProbes(source, swap_baseline_bytes=swap_baseline_bytes)
    step_records: list[dict[str, Any]] = []
    active_manager: RuntimeManager | None = None
    failure_message: str | None = None

    try:
        for step, target_id in enumerate(target_ids, start=1):
            try:
                manager = resolve_manager(target_id)
            except UnknownTargetError as exc:
                raise RuntimeLifecycleError(str(exc)) from exc

            active_manager = manager
            step_records.append(
                _run_sequence_step(
                    manager,
                    step=step,
                    prompt_runner=run_prompt,
                    prompt=prompt,
                    probes=probes,
                    writer=artifact_writer,
                )
            )

        artifact_writer.append(
            RunRecord(
                event="bench.swap_sequence.complete",
                status="ok",
                message="benchmark completed",
                metadata={"steps": len(step_records)},
            )
        )
        artifact_writer.write_summary()
        return SwapSequenceRunResult(
            ok=True,
            run_dir=artifact_writer.run_dir,
            message="benchmark completed",
            step_records=step_records,
        )
    except (RuntimeLifecycleError, UnknownTargetError) as exc:
        failure_message = str(exc)
    except Exception as exc:  # pragma: no cover - safety net for cleanup path
        failure_message = str(exc)

    if active_manager is not None:
        _attempt_cleanup(active_manager)

    artifact_writer.append(
        RunRecord(
            event="bench.swap_sequence.failed",
            status="error",
            message=failure_message or "benchmark failed",
            metadata={"completed_steps": len(step_records)},
        )
    )
    artifact_writer.write_summary()
    return SwapSequenceRunResult(
        ok=False,
        run_dir=artifact_writer.run_dir,
        message=failure_message or "benchmark failed",
        step_records=step_records or None,
    )
