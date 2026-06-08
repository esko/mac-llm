"""Runtime state persistence for managed local processes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class StateError(ValueError):
    """Raised when runtime state cannot be read or written."""


@dataclass(frozen=True)
class RuntimeState:
    """Persisted lifecycle metadata for one runtime target."""

    target_id: str
    pid: int | None
    port: int
    start_time: float | None
    stop_timeout: int
    last_error: str | None
    status: str

    def with_updates(self, **changes: Any) -> RuntimeState:
        data = asdict(self)
        data.update(changes)
        return RuntimeState(**data)


def load_state(path: Path) -> RuntimeState | None:
    """Load runtime state from disk, or None when no state file exists."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"failed to read runtime state: {path}") from exc

    required = {
        "target_id",
        "pid",
        "port",
        "start_time",
        "stop_timeout",
        "last_error",
        "status",
    }
    if not required.issubset(raw):
        raise StateError(f"invalid runtime state: {path}")

    return RuntimeState(
        target_id=str(raw["target_id"]),
        pid=raw["pid"],
        port=int(raw["port"]),
        start_time=raw["start_time"],
        stop_timeout=int(raw["stop_timeout"]),
        last_error=raw["last_error"],
        status=str(raw["status"]),
    )


def save_state(path: Path, state: RuntimeState) -> None:
    """Persist runtime state atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise StateError(f"failed to write runtime state: {path}") from exc


def clear_state(path: Path) -> None:
    """Remove persisted runtime state when present."""
    if path.exists():
        path.unlink()
