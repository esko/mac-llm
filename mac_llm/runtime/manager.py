"""Runtime manager — dry-run rendering only in this milestone."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mac_llm.runtime.target import RuntimeTarget


@dataclass(frozen=True)
class RenderedStartCommand:
    """Pure render result for a runtime target start command."""

    target_id: str
    runtime_type: str
    command: tuple[str, ...]
    port: int
    health_url: str
    log_path: Path
    state_path: Path
    stop_timeout: int
    model_config_ref: str

    def format_output(self) -> str:
        command = " ".join(self.command)
        lines = [
            f"target_id: {self.target_id}",
            f"runtime_type: {self.runtime_type}",
            f"command: {command}",
            f"port: {self.port}",
            f"health_url: {self.health_url}",
            f"log_path: {self.log_path}",
            f"state_path: {self.state_path}",
            f"stop_timeout: {self.stop_timeout}",
            f"model_config_ref: {self.model_config_ref}",
        ]
        return "\n".join(lines) + "\n"


def render_start_command(target: RuntimeTarget) -> RenderedStartCommand:
    """Render the start command and metadata for a target without side effects."""
    return RenderedStartCommand(
        target_id=target.target_id,
        runtime_type=target.runtime_type,
        command=target.command,
        port=target.port,
        health_url=target.health_url,
        log_path=target.log_path,
        state_path=target.state_path,
        stop_timeout=target.stop_timeout,
        model_config_ref=target.model_config_ref,
    )
