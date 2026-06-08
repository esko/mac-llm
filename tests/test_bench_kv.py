"""Tests for KV cold-vs-warm benchmark orchestration (no real model)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mac_llm.bench.artifacts import BenchmarkArtifactWriter
from mac_llm.bench.kv import (
    BUILTIN_PREFIXES,
    KvBenchRecord,
    UnknownPrefixError,
    evaluate_cache_helped,
    resolve_prefix,
    run_kv_benchmark,
    run_kv_benchmark_cli,
)
from mac_llm.cache.metadata import CacheCompatibilityError, CacheMetadata


@dataclass
class FakeCacheStore:
    save_time_ms: float = 12.5
    load_time_ms: float = 8.0
    disk_size_bytes: int = 4096
    incompatible: bool = False
    saved_payload: Any = b"cache-bytes"

    def save(self, payload: Any, metadata: CacheMetadata) -> tuple[int, float]:
        self.saved_payload = payload
        return self.disk_size_bytes, self.save_time_ms

    def load(
        self, cache_id: str, expected: CacheMetadata
    ) -> tuple[Any, int, float]:
        if self.incompatible:
            raise CacheCompatibilityError("prompt_hash mismatch")
        return self.saved_payload, self.disk_size_bytes, self.load_time_ms


@dataclass
class FakeRunner:
    cold_ttft_ms: float = 250.0
    warm_ttft_ms: float = 40.0
    cache_payload: bytes = b"cache-bytes"

    def run_cold(self, prefix_text: str) -> tuple[float, bytes]:
        return self.cold_ttft_ms, self.cache_payload

    def run_warm(self, prefix_text: str, cache_payload: bytes) -> float:
        return self.warm_ttft_ms


def _metadata() -> CacheMetadata:
    return CacheMetadata(
        cache_id="bench-repo-review",
        model_id="test-model",
        runtime_id="local_deep_moe",
        prompt_hash="prompt-def",
        prefix_tokens=tuple(range(128)),
        disk_size_bytes=0,
    )


def test_resolve_prefix_returns_builtin_text() -> None:
    assert resolve_prefix("repo-review") == BUILTIN_PREFIXES["repo-review"]


def test_resolve_prefix_unknown_fails_closed() -> None:
    with pytest.raises(UnknownPrefixError, match="unknown prefix"):
        resolve_prefix("missing-prefix")


def test_evaluate_cache_helped_when_warm_ttft_is_lower() -> None:
    assert evaluate_cache_helped(cold_ttft_ms=200.0, warm_ttft_ms=50.0) is True


def test_evaluate_cache_helped_when_warm_ttft_is_not_lower() -> None:
    assert evaluate_cache_helped(cold_ttft_ms=100.0, warm_ttft_ms=150.0) is False


def test_kv_record_includes_required_fields(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")
    result = run_kv_benchmark(
        prefix_name="repo-review",
        metadata=_metadata(),
        cache_store=FakeCacheStore(),
        runner=FakeRunner(),
        writer=writer,
        tokenizer_hash="tok-abc",
    )

    assert result.status == "ok"
    assert result.record is not None
    record = result.record
    assert isinstance(record, KvBenchRecord)
    assert record.cache_id == "bench-repo-review"
    assert record.model_id == "test-model"
    assert record.runtime_id == "local_deep_moe"
    assert record.tokenizer_hash == "tok-abc"
    assert record.prompt_hash == "prompt-def"
    assert record.prefix_tokens == 128
    assert record.save_time_ms == 12.5
    assert record.load_time_ms == 8.0
    assert record.cold_ttft_ms == 250.0
    assert record.warm_ttft_ms == 40.0
    assert record.disk_size_bytes == 4096
    assert record.cache_helped is True
    assert record.compatibility == "ok"


def test_incompatible_cache_fails_closed_without_warm_success(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")
    result = run_kv_benchmark(
        prefix_name="repo-review",
        metadata=_metadata(),
        cache_store=FakeCacheStore(incompatible=True),
        runner=FakeRunner(),
        writer=writer,
    )

    assert result.status == "failed"
    assert result.record is not None
    assert result.record.compatibility == "mismatch"
    assert result.record.warm_ttft_ms is None
    assert result.record.cache_helped is None
    assert "mismatch" in (result.message or "").lower()


def test_writes_run_jsonl_and_summary_on_success(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")
    run_kv_benchmark(
        prefix_name="repo-review",
        metadata=_metadata(),
        cache_store=FakeCacheStore(),
        runner=FakeRunner(),
        writer=writer,
    )

    jsonl_path = writer.run_dir / "run.jsonl"
    summary_path = writer.run_dir / "summary.md"
    assert jsonl_path.is_file()
    assert summary_path.is_file()

    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    event_names = [event["event"] for event in events]
    assert "bench.kv.start" in event_names
    assert "bench.kv.complete" in event_names

    summary = summary_path.read_text(encoding="utf-8")
    assert "bench.kv.complete" in summary
    assert "cache_helped" in summary


def test_writes_failure_artifact_on_incompatible_cache(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")
    run_kv_benchmark(
        prefix_name="repo-review",
        metadata=_metadata(),
        cache_store=FakeCacheStore(incompatible=True),
        runner=FakeRunner(),
        writer=writer,
    )

    jsonl_path = writer.run_dir / "run.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    failed = [event for event in events if event.get("status") == "failed"]
    assert failed
    assert writer.run_dir.joinpath("summary.md").is_file()


def test_cli_path_fails_clear_without_runtime_integration(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")
    result = run_kv_benchmark_cli(
        target_id="local_deep_moe",
        prefix_name="repo-review",
        root=tmp_path,
        writer=writer,
    )

    assert result.status == "failed"
    assert result.message is not None
    assert "unavailable" in result.message.lower()
    assert (writer.run_dir / "run.jsonl").is_file()
    assert (writer.run_dir / "summary.md").is_file()
