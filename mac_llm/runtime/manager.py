"""Runtime manager — lifecycle control and dry-run rendering."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mac_llm.runtime.probes import (
    HealthCheckResult,
    OrphanCheckResult,
    command_available,
    expand_command,
    is_port_occupied,
    orphan_check,
    pid_on_port,
    probe_health,
)
from mac_llm.runtime.state import RuntimeState, clear_state, load_state, save_state
from mac_llm.runtime.target import RuntimeTarget

PortPidFn = Callable[[int], int | None]
StartProcessFn = Callable[[tuple[str, ...], Path], int]
StopProcessFn = Callable[[int, int], bool]


class RuntimeLifecycleError(RuntimeError):
    """Raised when a lifecycle action cannot complete safely."""


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


@dataclass
class RuntimeManager:
    """Manage one configured runtime target lifecycle."""

    target: RuntimeTarget
    port_pid_fn: PortPidFn = pid_on_port
    start_process: StartProcessFn | None = None
    stop_process: StopProcessFn | None = None

    def __post_init__(self) -> None:
        if self.start_process is None:
            self.start_process = _default_start_process
        if self.stop_process is None:
            self.stop_process = _default_stop_process

    def render_start_command(self) -> RenderedStartCommand:
        """Render the start command and metadata for a target without side effects."""
        return render_start_command(self.target)

    def status(self) -> RuntimeState | None:
        """Return persisted runtime state when present."""
        return load_state(self.target.state_path)

    def health_check(self) -> HealthCheckResult:
        """Probe the configured health URL for this target."""
        return probe_health(self.target.health_url)

    def orphan_check(self) -> OrphanCheckResult:
        """Detect leftover processes or stale state for this target."""
        return orphan_check(
            self.target,
            self.status(),
            process_alive=_process_alive,
            port_pid_fn=self.port_pid_fn,
        )

    def start(self, *, environ: dict[str, str] | None = None) -> RuntimeState:
        """Start the configured runtime when available."""
        env = dict(os.environ if environ is None else environ)
        state_path = self.target.state_path

        def record_error(message: str) -> RuntimeState:
            state = RuntimeState(
                target_id=self.target.target_id,
                pid=None,
                port=self.target.port,
                start_time=None,
                stop_timeout=self.target.stop_timeout,
                last_error=message,
                status="stopped",
            )
            save_state(state_path, state)
            return state

        if not command_available(self.target.command):
            record_error("runtime command unavailable")
            raise RuntimeLifecycleError("runtime command unavailable")

        try:
            command = expand_command(self.target.command, env)
        except ValueError as exc:
            record_error(str(exc))
            raise RuntimeLifecycleError(str(exc)) from exc

        if is_port_occupied(self.target.port, port_pid_fn=self.port_pid_fn):
            record_error(f"port {self.target.port} is occupied")
            raise RuntimeLifecycleError(f"port {self.target.port} is occupied")

        existing = self.status()
        if existing is not None and existing.status == "running" and existing.pid is not None:
            if _process_alive(existing.pid):
                record_error(f"runtime already running with pid {existing.pid}")
                raise RuntimeLifecycleError(
                    f"runtime already running with pid {existing.pid}"
                )

        self.target.log_path.parent.mkdir(parents=True, exist_ok=True)
        pid = self.start_process(command, self.target.log_path)
        started = RuntimeState(
            target_id=self.target.target_id,
            pid=pid,
            port=self.target.port,
            start_time=time.time(),
            stop_timeout=self.target.stop_timeout,
            last_error=None,
            status="running",
        )
        save_state(state_path, started)
        return started

    def stop(self) -> RuntimeState:
        """Stop the managed runtime using targeted process termination."""
        state_path = self.target.state_path
        state = self.status()
        if state is None or state.pid is None or state.status != "running":
            stopped = RuntimeState(
                target_id=self.target.target_id,
                pid=None,
                port=self.target.port,
                start_time=None,
                stop_timeout=self.target.stop_timeout,
                last_error="no managed runtime is running",
                status="stopped",
            )
            save_state(state_path, stopped)
            raise RuntimeLifecycleError("no managed runtime is running")

        stopped_ok = self.stop_process(state.pid, state.stop_timeout)
        if not stopped_ok:
            failed = state.with_updates(
                last_error=f"failed to stop pid {state.pid} within {state.stop_timeout}s",
                status="stopped",
                pid=None,
                start_time=None,
            )
            save_state(state_path, failed)
            raise RuntimeLifecycleError(failed.last_error or "failed to stop runtime")

        stopped = RuntimeState(
            target_id=self.target.target_id,
            pid=None,
            port=self.target.port,
            start_time=None,
            stop_timeout=self.target.stop_timeout,
            last_error=None,
            status="stopped",
        )
        clear_state(state_path)
        save_state(state_path, stopped)
        return stopped


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


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _default_start_process(command: tuple[str, ...], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        list(command),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()
    return process.pid


def _default_stop_process(pid: int, timeout: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    return not _process_alive(pid)
