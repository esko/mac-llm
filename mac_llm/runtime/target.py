"""Runtime target definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class UnknownTargetError(ValueError):
    """Raised when a runtime target id is not configured."""


@dataclass(frozen=True)
class RuntimeTarget:
    """Static configuration for a managed local runtime target."""

    target_id: str
    runtime_type: str
    command: tuple[str, ...]
    port: int
    health_url: str
    log_path: Path
    state_path: Path
    stop_timeout: int
    model_config_ref: str


def _data_root() -> Path:
    return Path.home() / ".mac-llm"


def _targets() -> dict[str, RuntimeTarget]:
    data_root = _data_root()
    return {
        "local_fast": RuntimeTarget(
            target_id="local_fast",
            runtime_type="llama.cpp",
            command=(
                "llama-server",
                "--host",
                "127.0.0.1",
                "--port",
                "8080",
                "--model",
                "${MAC_LLM_MODEL_LOCAL_FAST}",
            ),
            port=8080,
            health_url="http://127.0.0.1:8080/health",
            log_path=data_root / "logs" / "local_fast.log",
            state_path=data_root / "state" / "local_fast.json",
            stop_timeout=30,
            model_config_ref="models.local_fast",
        ),
        "local_deep_moe": RuntimeTarget(
            target_id="local_deep_moe",
            runtime_type="mlx_sniper",
            command=(
                "mlx-sniper",
                "serve",
                "${MAC_LLM_MODEL_LOCAL_DEEP_MOE}",
                "--host",
                "127.0.0.1",
                "--port",
                "8081",
            ),
            port=8081,
            health_url="http://127.0.0.1:8081/api/tags",
            log_path=data_root / "logs" / "local_deep_moe.log",
            state_path=data_root / "state" / "local_deep_moe.json",
            stop_timeout=60,
            model_config_ref="models.local_deep_moe",
        ),
    }


def get_target(target_id: str) -> RuntimeTarget:
    """Return a configured runtime target or fail closed."""
    targets = _targets()
    if target_id not in targets:
        raise UnknownTargetError(f"unknown runtime target: {target_id}")
    return targets[target_id]
