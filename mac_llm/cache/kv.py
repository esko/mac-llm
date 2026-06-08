"""First-party KV/prompt-cache save/load interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from mac_llm.cache.metadata import (
    CacheCompatibilityError,
    CacheMetadata,
    check_compatibility,
    load_metadata,
    save_metadata,
)


@runtime_checkable
class CacheBackend(Protocol):
    """Upstream cache save/load behavior injected for testability."""

    def save(
        self,
        payload_path: Path,
        cache: Any,
        extra_metadata: dict[str, str],
    ) -> None: ...

    def load(self, payload_path: Path) -> tuple[Any, dict[str, str]]: ...


class MlxPromptCacheBackend:
    """Wrap upstream mlx_lm prompt-cache save/load without modifying it."""

    def save(
        self,
        payload_path: Path,
        cache: Any,
        extra_metadata: dict[str, str],
    ) -> None:
        from mlx_lm.models.cache import save_prompt_cache

        payload_path.parent.mkdir(parents=True, exist_ok=True)
        save_prompt_cache(str(payload_path), cache, metadata=extra_metadata)

    def load(self, payload_path: Path) -> tuple[Any, dict[str, str]]:
        from mlx_lm.models.cache import load_prompt_cache

        cache, metadata = load_prompt_cache(str(payload_path), return_metadata=True)
        return cache, metadata


class KvPromptCacheStore:
    """Persist and restore prompt caches with fail-closed compatibility checks."""

    _payload_name = "payload.safetensors"
    _metadata_name = "metadata.json"

    def __init__(self, root: Path, backend: CacheBackend | None = None) -> None:
        self._root = root
        self._backend = backend or MlxPromptCacheBackend()

    def save(self, *, cache: CacheMetadata, cache_payload: Any) -> CacheMetadata:
        """Save cache payload and metadata under cache.cache_id."""
        cache_dir = self._cache_dir(cache.cache_id)
        payload_path = cache_dir / self._payload_name
        metadata_path = cache_dir / self._metadata_name

        extra_metadata = {
            "cache_id": cache.cache_id,
            "model_id": cache.model_id,
            "runtime_id": cache.runtime_id,
            "prompt_hash": cache.prompt_hash,
        }
        self._backend.save(payload_path, cache_payload, extra_metadata)

        saved = cache.with_disk_size(payload_path.stat().st_size)
        save_metadata(metadata_path, saved)
        return saved

    def load(
        self,
        *,
        expected: CacheMetadata,
    ) -> tuple[Any, CacheMetadata]:
        """Load cache payload after fail-closed metadata compatibility checks."""
        cache_dir = self._cache_dir(expected.cache_id)
        payload_path = cache_dir / self._payload_name
        metadata_path = cache_dir / self._metadata_name

        if not metadata_path.is_file():
            raise CacheCompatibilityError(
                f"metadata file missing for cache {expected.cache_id!r}"
            )
        if not payload_path.is_file():
            raise CacheCompatibilityError(
                f"payload file missing for cache {expected.cache_id!r}"
            )

        stored = load_metadata(metadata_path)
        check_compatibility(expected, stored)

        cache_payload, _upstream_metadata = self._backend.load(payload_path)
        return cache_payload, stored

    def _cache_dir(self, cache_id: str) -> Path:
        return self._root / cache_id
