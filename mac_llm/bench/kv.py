"""KV cold-vs-warm prompt-cache benchmark orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mac_llm.bench.artifacts import BenchmarkArtifactWriter, RunRecord
from mac_llm.cache.metadata import CacheCompatibilityError, CacheMetadata

BUILTIN_PREFIXES: dict[str, str] = {
    "repo-review": (
        "You are reviewing a repository change. Summarize risks, test gaps, "
        "and the smallest safe next step."
    ),
}


class UnknownPrefixError(ValueError):
    """Raised when a benchmark prefix name is not configured."""


@dataclass(frozen=True)
class KvBenchRecord:
    cache_id: str
    model_id: str
    runtime_id: str
    tokenizer_hash: str | None
    prompt_hash: str
    prefix_tokens: int
    save_time_ms: float | None
    load_time_ms: float | None
    cold_ttft_ms: float | None
    warm_ttft_ms: float | None
    disk_size_bytes: int | None
    cache_helped: bool | None
    compatibility: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_id": self.cache_id,
            "model_id": self.model_id,
            "runtime_id": self.runtime_id,
            "tokenizer_hash": self.tokenizer_hash,
            "prompt_hash": self.prompt_hash,
            "prefix_tokens": self.prefix_tokens,
            "save_time_ms": self.save_time_ms,
            "load_time_ms": self.load_time_ms,
            "cold_ttft_ms": self.cold_ttft_ms,
            "warm_ttft_ms": self.warm_ttft_ms,
            "disk_size_bytes": self.disk_size_bytes,
            "cache_helped": self.cache_helped,
            "compatibility": self.compatibility,
        }


@dataclass(frozen=True)
class KvBenchResult:
    status: str
    record: KvBenchRecord | None = None
    message: str | None = None


class PromptCacheStore(Protocol):
    def save(self, payload: Any, metadata: CacheMetadata) -> tuple[int, float]: ...

    def load(
        self, cache_id: str, expected: CacheMetadata
    ) -> tuple[Any, int, float]: ...


class KvInferenceRunner(Protocol):
    def run_cold(self, prefix_text: str) -> tuple[float, Any]: ...

    def run_warm(self, prefix_text: str, cache_payload: Any) -> float: ...


def resolve_prefix(prefix_name: str) -> str:
    try:
        return BUILTIN_PREFIXES[prefix_name]
    except KeyError as exc:
        raise UnknownPrefixError(f"unknown prefix: {prefix_name}") from exc


def estimate_prefix_token_ids(prefix_text: str) -> tuple[int, ...]:
    words = prefix_text.split()
    count = max(len(words), 1)
    return tuple(range(count))


def evaluate_cache_helped(*, cold_ttft_ms: float, warm_ttft_ms: float) -> bool:
    return warm_ttft_ms < cold_ttft_ms


def _bench_record_from_metadata(
    metadata: CacheMetadata,
    *,
    tokenizer_hash: str | None,
    save_time_ms: float | None = None,
    load_time_ms: float | None = None,
    cold_ttft_ms: float | None = None,
    warm_ttft_ms: float | None = None,
    disk_size_bytes: int | None = None,
    cache_helped: bool | None = None,
    compatibility: str,
) -> KvBenchRecord:
    return KvBenchRecord(
        cache_id=metadata.cache_id,
        model_id=metadata.model_id,
        runtime_id=metadata.runtime_id,
        tokenizer_hash=tokenizer_hash,
        prompt_hash=metadata.prompt_hash,
        prefix_tokens=len(metadata.prefix_tokens),
        save_time_ms=save_time_ms,
        load_time_ms=load_time_ms,
        cold_ttft_ms=cold_ttft_ms,
        warm_ttft_ms=warm_ttft_ms,
        disk_size_bytes=disk_size_bytes,
        cache_helped=cache_helped,
        compatibility=compatibility,
    )


def run_kv_benchmark(
    *,
    prefix_name: str,
    metadata: CacheMetadata,
    cache_store: PromptCacheStore,
    runner: KvInferenceRunner,
    writer: BenchmarkArtifactWriter,
    tokenizer_hash: str | None = None,
) -> KvBenchResult:
    prefix_text = resolve_prefix(prefix_name)
    writer.append(
        RunRecord(
            event="bench.kv.start",
            status="ok",
            message=f"prefix={prefix_name}",
            metadata={"runtime_id": metadata.runtime_id, "cache_id": metadata.cache_id},
        )
    )

    cold_ttft_ms, cache_payload = runner.run_cold(prefix_text)
    disk_size_bytes, save_time_ms = cache_store.save(cache_payload, metadata)

    try:
        loaded_payload, loaded_disk_size, load_time_ms = cache_store.load(
            metadata.cache_id,
            metadata,
        )
    except CacheCompatibilityError as exc:
        record = _bench_record_from_metadata(
            metadata,
            tokenizer_hash=tokenizer_hash,
            save_time_ms=save_time_ms,
            cold_ttft_ms=cold_ttft_ms,
            disk_size_bytes=disk_size_bytes,
            compatibility="mismatch",
        )
        writer.append(
            RunRecord(
                event="bench.kv.complete",
                status="failed",
                message=str(exc),
                metadata={"record": record.to_dict()},
            )
        )
        writer.write_summary()
        return KvBenchResult(status="failed", record=record, message=str(exc))

    warm_ttft_ms = runner.run_warm(prefix_text, loaded_payload)
    cache_helped = evaluate_cache_helped(
        cold_ttft_ms=cold_ttft_ms,
        warm_ttft_ms=warm_ttft_ms,
    )
    record = _bench_record_from_metadata(
        metadata,
        tokenizer_hash=tokenizer_hash,
        save_time_ms=save_time_ms,
        load_time_ms=load_time_ms,
        cold_ttft_ms=cold_ttft_ms,
        warm_ttft_ms=warm_ttft_ms,
        disk_size_bytes=loaded_disk_size,
        cache_helped=cache_helped,
        compatibility="ok",
    )
    writer.append(
        RunRecord(
            event="bench.kv.complete",
            status="ok",
            message=f"cache_helped={cache_helped}",
            metadata={"record": record.to_dict()},
        )
    )
    writer.write_summary()
    return KvBenchResult(status="ok", record=record)


def build_metadata(
    *,
    cache_id: str,
    model_id: str,
    runtime_id: str,
    prefix_name: str,
    prompt_hash: str | None = None,
) -> CacheMetadata:
    prefix_text = resolve_prefix(prefix_name)
    return CacheMetadata(
        cache_id=cache_id,
        model_id=model_id,
        runtime_id=runtime_id,
        prompt_hash=prompt_hash or prefix_name,
        prefix_tokens=estimate_prefix_token_ids(prefix_text),
        disk_size_bytes=0,
    )


class TimedKvPromptCacheStore:
    """Adapter that records save/load timings around KvPromptCacheStore."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def save(self, payload: Any, metadata: CacheMetadata) -> tuple[int, float]:
        started = time.perf_counter()
        saved = self._store.save(cache=metadata, cache_payload=payload)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return saved.disk_size_bytes, elapsed_ms

    def load(
        self, cache_id: str, expected: CacheMetadata
    ) -> tuple[Any, int, float]:
        started = time.perf_counter()
        payload, stored = self._store.load(expected=expected)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return payload, stored.disk_size_bytes, elapsed_ms


def run_kv_benchmark_cli(
    *,
    target_id: str,
    prefix_name: str,
    root: Path,
    writer: BenchmarkArtifactWriter,
) -> KvBenchResult:
    """Run the KV benchmark from CLI, failing clearly when integration is unavailable."""
    from mac_llm.runtime.target import UnknownTargetError, get_target

    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        writer.append(
            RunRecord(
                event="bench.kv.complete",
                status="failed",
                message=str(exc),
            )
        )
        writer.write_summary()
        return KvBenchResult(status="failed", message=str(exc))

    cache_id = f"bench-{prefix_name}"
    metadata = build_metadata(
        cache_id=cache_id,
        model_id=target.model_config_ref,
        runtime_id=target.target_id,
        prefix_name=prefix_name,
    )

    try:
        from mac_llm.cache.kv import KvPromptCacheStore
        from mac_llm.cache.runtime import KvRuntimeRunner
    except ImportError as exc:
        message = (
            f"KV cache runtime integration unavailable for target {target_id}: {exc}"
        )
        writer.append(
            RunRecord(
                event="bench.kv.complete",
                status="failed",
                message=message,
                metadata={"runtime_id": target.target_id, "cache_id": cache_id},
            )
        )
        writer.write_summary()
        return KvBenchResult(status="failed", message=message)

    cache_root = root / "cache"
    return run_kv_benchmark(
        prefix_name=prefix_name,
        metadata=metadata,
        cache_store=TimedKvPromptCacheStore(KvPromptCacheStore(cache_root)),
        runner=KvRuntimeRunner(target=target),
        writer=writer,
    )
