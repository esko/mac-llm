"""Persisted cache metadata and fail-closed compatibility checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CacheCompatibilityError(ValueError):
    """Raised when stored cache metadata does not match the expected context."""


@dataclass(frozen=True)
class CacheMetadata:
    """Compatibility record persisted next to a cache payload."""

    cache_id: str
    model_id: str
    runtime_id: str
    prompt_hash: str
    prefix_tokens: tuple[int, ...]
    disk_size_bytes: int

    def with_disk_size(self, disk_size_bytes: int) -> CacheMetadata:
        return CacheMetadata(
            cache_id=self.cache_id,
            model_id=self.model_id,
            runtime_id=self.runtime_id,
            prompt_hash=self.prompt_hash,
            prefix_tokens=self.prefix_tokens,
            disk_size_bytes=disk_size_bytes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_id": self.cache_id,
            "model_id": self.model_id,
            "runtime_id": self.runtime_id,
            "prompt_hash": self.prompt_hash,
            "prefix_tokens": list(self.prefix_tokens),
            "disk_size_bytes": self.disk_size_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheMetadata:
        required = {
            "cache_id",
            "model_id",
            "runtime_id",
            "prompt_hash",
            "prefix_tokens",
            "disk_size_bytes",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError(f"missing required field(s): {', '.join(missing)}")

        return cls(
            cache_id=str(data["cache_id"]),
            model_id=str(data["model_id"]),
            runtime_id=str(data["runtime_id"]),
            prompt_hash=str(data["prompt_hash"]),
            prefix_tokens=tuple(int(token) for token in data["prefix_tokens"]),
            disk_size_bytes=int(data["disk_size_bytes"]),
        )


def save_metadata(path: Path, metadata: CacheMetadata) -> None:
    """Write cache metadata next to the cache payload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_metadata(path: Path) -> CacheMetadata:
    """Load cache metadata from disk."""
    return CacheMetadata.from_dict(json.loads(path.read_text(encoding="utf-8")))


def check_compatibility(expected: CacheMetadata, stored: CacheMetadata) -> None:
    """Fail closed when model, runtime, or prompt hash do not match."""
    checks = (
        ("model_id", expected.model_id, stored.model_id),
        ("runtime_id", expected.runtime_id, stored.runtime_id),
        ("prompt_hash", expected.prompt_hash, stored.prompt_hash),
    )
    for field, expected_value, stored_value in checks:
        if expected_value != stored_value:
            raise CacheCompatibilityError(
                f"{field} mismatch: expected {expected_value!r}, got {stored_value!r}"
            )
