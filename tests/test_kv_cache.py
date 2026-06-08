"""Tests for KV/prompt-cache save/load with fail-closed compatibility."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mac_llm.cache.kv import CacheCompatibilityError, KvPromptCacheStore
from mac_llm.cache.metadata import CacheMetadata, load_metadata, save_metadata


class FakeCacheBackend:
    """Minimal stand-in for upstream save/load without a real model."""

    def save(
        self,
        payload_path: Path,
        cache: Any,
        extra_metadata: dict[str, str],
    ) -> None:
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_bytes(f"cache:{cache}".encode("utf-8"))

    def load(self, payload_path: Path) -> tuple[Any, dict[str, str]]:
        return payload_path.read_text(encoding="utf-8"), {}


def _metadata(**overrides: object) -> CacheMetadata:
    base = {
        "cache_id": "repo-review",
        "model_id": "local-deep-moe-v1",
        "runtime_id": "local_deep_moe",
        "prompt_hash": "abc123",
        "prefix_tokens": (1, 2, 3),
        "disk_size_bytes": 0,
    }
    base.update(overrides)
    return CacheMetadata(**base)  # type: ignore[arg-type]


def test_metadata_roundtrip_via_json_file(tmp_path: Path) -> None:
    metadata = _metadata(disk_size_bytes=4096)
    metadata_path = tmp_path / "metadata.json"

    save_metadata(metadata_path, metadata)
    loaded = load_metadata(metadata_path)

    assert loaded == metadata
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["cache_id"] == "repo-review"
    assert payload["prefix_tokens"] == [1, 2, 3]
    assert payload["disk_size_bytes"] == 4096


def test_save_persists_metadata_next_to_payload(tmp_path: Path) -> None:
    store = KvPromptCacheStore(tmp_path, backend=FakeCacheBackend())

    saved = store.save(
        cache=_metadata(),
        cache_payload="warm-prefix",
    )

    cache_dir = tmp_path / "repo-review"
    assert (cache_dir / "payload.safetensors").is_file()
    assert (cache_dir / "metadata.json").is_file()
    assert saved.disk_size_bytes == len("cache:warm-prefix".encode("utf-8"))
    assert load_metadata(cache_dir / "metadata.json") == saved


def test_load_returns_saved_cache_when_metadata_matches(tmp_path: Path) -> None:
    store = KvPromptCacheStore(tmp_path, backend=FakeCacheBackend())
    expected = _metadata()

    store.save(cache=expected, cache_payload="warm-prefix")
    loaded_cache, loaded_metadata = store.load(expected=expected)

    assert loaded_cache == "cache:warm-prefix"
    assert loaded_metadata == expected.with_disk_size(len("cache:warm-prefix".encode("utf-8")))


@pytest.mark.parametrize(
    ("field", "mismatched_value"),
    [
        ("model_id", "other-model"),
        ("runtime_id", "local_fast"),
        ("prompt_hash", "deadbeef"),
    ],
)
def test_load_fails_closed_on_metadata_mismatch(
    tmp_path: Path,
    field: str,
    mismatched_value: str,
) -> None:
    store = KvPromptCacheStore(tmp_path, backend=FakeCacheBackend())
    saved = _metadata()
    store.save(cache=saved, cache_payload="warm-prefix")

    mismatched = _metadata(**{field: mismatched_value})
    with pytest.raises(CacheCompatibilityError, match=field):
        store.load(expected=mismatched)


def test_load_fails_closed_when_metadata_file_missing(tmp_path: Path) -> None:
    store = KvPromptCacheStore(tmp_path, backend=FakeCacheBackend())
    cache_dir = tmp_path / "repo-review"
    cache_dir.mkdir(parents=True)
    (cache_dir / "payload.safetensors").write_bytes(b"cache:orphan")

    with pytest.raises(CacheCompatibilityError, match="metadata"):
        store.load(expected=_metadata())


def test_load_fails_closed_when_payload_missing(tmp_path: Path) -> None:
    store = KvPromptCacheStore(tmp_path, backend=FakeCacheBackend())
    cache_dir = tmp_path / "repo-review"
    cache_dir.mkdir(parents=True)
    save_metadata(cache_dir / "metadata.json", _metadata(disk_size_bytes=12))

    with pytest.raises(CacheCompatibilityError, match="payload"):
        store.load(expected=_metadata())
