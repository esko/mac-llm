"""OpenAI-compatible smoke requests against managed runtime targets."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from mac_llm.bench.artifacts import BenchmarkArtifactWriter, RunRecord
from mac_llm.bench.metrics import SystemMetricProbes
from mac_llm.bench.records import SmokeBenchmarkRecord
from mac_llm.runtime.manager import RuntimeManager
from mac_llm.runtime.probes import OrphanCheckResult, probe_health
from mac_llm.runtime.target import RuntimeTarget

OrphanCheckFn = Callable[[], OrphanCheckResult]

_SMOKE_PROMPT = "ping"
_SMOKE_MAX_TOKENS = 16


@dataclass(frozen=True)
class SmokeRequestResult:
    """Outcome of a smoke request, including the written artifact directory."""

    record: SmokeBenchmarkRecord
    artifact_dir: Path


def completion_url(target: RuntimeTarget, *, base_url: str | None = None) -> str:
    """Build the OpenAI-compatible chat completions URL for a target."""
    origin = base_url or _origin_from_health_url(target.health_url)
    parsed = urlparse(origin)
    return urlunparse((parsed.scheme, parsed.netloc, "/v1/chat/completions", "", "", ""))


def run_smoke(
    target: RuntimeTarget,
    *,
    artifact_root: Path,
    base_url: str | None = None,
    metric_probes: SystemMetricProbes | None = None,
    orphan_check_fn: OrphanCheckFn | None = None,
    timestamp: str | None = None,
) -> SmokeRequestResult:
    """Run a minimal OpenAI-compatible smoke request and always write an artifact."""
    writer = BenchmarkArtifactWriter(artifact_root, timestamp=timestamp)
    writer.append(
        RunRecord(
            event="smoke.start",
            status="ok",
            message=f"smoke request for {target.target_id}",
            metadata={"target_id": target.target_id, "runtime_type": target.runtime_type},
        )
    )

    metrics = _collect_metrics(target, metric_probes, orphan_check_fn)
    health_url = _health_url(target, base_url)
    health = probe_health(health_url)
    if not health.ok:
        record = _failed_record(
            target,
            message=f"health check failed: {health.message}",
            memory=metrics["memory"],
            orphan_status=metrics["orphan_status"],
        )
        _write_failure(writer, record)
        return SmokeRequestResult(record=record, artifact_dir=writer.run_dir)

    completion_result = _post_completion(target, base_url=base_url)
    if not completion_result.ok:
        record = _failed_record(
            target,
            message=completion_result.message,
            memory=metrics["memory"],
            orphan_status=metrics["orphan_status"],
        )
        _write_failure(writer, record)
        return SmokeRequestResult(record=record, artifact_dir=writer.run_dir)

    record = SmokeBenchmarkRecord(
        target_id=target.target_id,
        runtime_type=target.runtime_type,
        status="ok",
        load_time_s=completion_result.load_time_s,
        ttft_s=completion_result.ttft_s,
        tokens_per_second=completion_result.tokens_per_second,
        memory=metrics["memory"],
        orphan_status=metrics["orphan_status"],
        message=completion_result.message,
    )
    writer.append(
        RunRecord(
            event="smoke.complete",
            status="ok",
            message="smoke request succeeded",
            metadata={"benchmark": record.to_dict()},
        )
    )
    writer.write_summary()
    return SmokeRequestResult(record=record, artifact_dir=writer.run_dir)


def _collect_metrics(
    target: RuntimeTarget,
    metric_probes: SystemMetricProbes | None,
    orphan_check_fn: OrphanCheckFn | None,
) -> dict[str, dict[str, Any]]:
    if metric_probes is None:
        metric_probes = SystemMetricProbes(_UnavailableMetricSource())
    collected = metric_probes.collect()

    if orphan_check_fn is None:
        orphan = RuntimeManager(target=target).orphan_check()
    else:
        orphan = orphan_check_fn()
    orphan_status = {
        "status": "ok",
        "orphaned": orphan.has_orphan,
        "count": 1 if orphan.has_orphan else 0,
        "processes": [],
    }

    return {
        "memory": collected["memory_pressure"],
        "orphan_status": orphan_status,
    }


def _failed_record(
    target: RuntimeTarget,
    *,
    message: str,
    memory: dict[str, Any],
    orphan_status: dict[str, Any],
) -> SmokeBenchmarkRecord:
    return SmokeBenchmarkRecord(
        target_id=target.target_id,
        runtime_type=target.runtime_type,
        status="failed",
        load_time_s=None,
        ttft_s=None,
        tokens_per_second=None,
        memory=memory,
        orphan_status=orphan_status,
        message=message,
    )


def _write_failure(writer: BenchmarkArtifactWriter, record: SmokeBenchmarkRecord) -> None:
    writer.append(
        RunRecord(
            event="smoke.failed",
            status="failed",
            message=record.message,
            metadata={"benchmark": record.to_dict()},
        )
    )
    writer.write_summary()


@dataclass(frozen=True)
class _CompletionResult:
    ok: bool
    message: str
    load_time_s: float | None = None
    ttft_s: float | None = None
    tokens_per_second: float | None = None


def _post_completion(
    target: RuntimeTarget,
    *,
    base_url: str | None = None,
) -> _CompletionResult:
    url = completion_url(target, base_url=base_url)
    payload = {
        "model": target.target_id,
        "messages": [{"role": "user", "content": _SMOKE_PROMPT}],
        "max_tokens": _SMOKE_MAX_TOKENS,
        "temperature": 0.0,
        "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return _CompletionResult(
            ok=False,
            message=f"completion http error: {exc.code} {detail}".strip(),
        )
    except urllib.error.URLError as exc:
        return _CompletionResult(ok=False, message=f"completion unavailable: {exc.reason}")
    except TimeoutError:
        return _CompletionResult(ok=False, message="completion unavailable: timeout")

    elapsed = time.time() - started
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _CompletionResult(ok=False, message="completion returned invalid json")

    return _parse_completion_response(data, elapsed)


def _parse_completion_response(data: dict[str, Any], elapsed: float) -> _CompletionResult:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return _CompletionResult(ok=False, message="completion returned no choices")

    message = choices[0].get("message", {})
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        return _CompletionResult(ok=False, message="completion returned empty content")

    timings = data.get("timings", {})
    usage = data.get("usage", {})
    load_time = _coerce_float(data.get("load_time"))
    if load_time is None and isinstance(timings, dict):
        load_time = _coerce_float(timings.get("load_time"))

    ttft_s = None
    if isinstance(timings, dict):
        prompt_ms = _coerce_float(timings.get("prompt_ms"))
        if prompt_ms is not None:
            ttft_s = prompt_ms / 1000.0

    tokens_per_second = None
    if isinstance(timings, dict):
        tokens_per_second = _coerce_float(timings.get("predicted_per_second"))

    completion_tokens = None
    if isinstance(usage, dict):
        completion_tokens = _coerce_int(usage.get("completion_tokens"))

    if tokens_per_second is None and completion_tokens and elapsed > 0:
        tokens_per_second = completion_tokens / elapsed

    return _CompletionResult(
        ok=True,
        message="completion ok",
        load_time_s=load_time,
        ttft_s=ttft_s,
        tokens_per_second=tokens_per_second,
    )


def _coerce_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _origin_from_health_url(health_url: str) -> str:
    parsed = urlparse(health_url)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _health_url(target: RuntimeTarget, base_url: str | None) -> str:
    if base_url is None:
        return target.health_url
    parsed = urlparse(target.health_url)
    origin = urlparse(base_url)
    return urlunparse((origin.scheme, origin.netloc, parsed.path, "", "", ""))


class _UnavailableMetricSource:
    def read_memory_pressure(self) -> dict[str, Any] | None:
        return None

    def read_swap_used_bytes(self) -> int | None:
        return None

    def read_orphan_processes(self) -> list[str] | None:
        return None
