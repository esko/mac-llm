"""Pure probes for port, health, orphan, and command availability."""

from __future__ import annotations

import shutil
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from mac_llm.runtime.state import RuntimeState
from mac_llm.runtime.target import RuntimeTarget

ProcessAliveFn = Callable[[int], bool]
PortPidFn = Callable[[int], int | None]


@dataclass(frozen=True)
class HealthCheckResult:
    """Outcome of probing a runtime health URL."""

    ok: bool
    message: str


@dataclass(frozen=True)
class OrphanCheckResult:
    """Outcome of checking for leftover runtime processes."""

    has_orphan: bool
    port_occupied: bool
    occupying_pid: int | None
    stale_state_pid: int | None
    message: str


def is_port_occupied(port: int, *, port_pid_fn: PortPidFn | None = None) -> bool:
    """Return True when the local TCP port is already in use."""
    if port_pid_fn is not None:
        return port_pid_fn(port) is not None

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def pid_on_port(port: int) -> int | None:
    """Best-effort lookup of the PID listening on a local TCP port."""
    try:
        import subprocess

        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, FileNotFoundError):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        return int(result.stdout.strip().splitlines()[0])
    except ValueError:
        return None


def probe_health(url: str, *, timeout: float = 2.0) -> HealthCheckResult:
    """Probe a runtime health URL over HTTP."""
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if 200 <= response.status < 300:
                return HealthCheckResult(ok=True, message="healthy")
            return HealthCheckResult(
                ok=False,
                message=f"unexpected status: {response.status}",
            )
    except urllib.error.HTTPError as exc:
        return HealthCheckResult(ok=False, message=f"http error: {exc.code}")
    except urllib.error.URLError as exc:
        return HealthCheckResult(ok=False, message=f"unreachable: {exc.reason}")
    except TimeoutError:
        return HealthCheckResult(ok=False, message="timeout")


def command_available(command: tuple[str, ...]) -> bool:
    """Return True when the runtime executable appears available locally."""
    if not command:
        return False
    executable = command[0]
    if "/" in executable:
        from pathlib import Path

        return Path(executable).exists()
    return shutil.which(executable) is not None


def expand_command(command: tuple[str, ...], environ: dict[str, str]) -> tuple[str, ...]:
    """Expand ${VAR} placeholders from the provided environment."""
    expanded: list[str] = []
    for part in command:
        if part.startswith("${") and part.endswith("}"):
            key = part[2:-1]
            if key not in environ or not environ[key]:
                raise ValueError(f"missing required environment variable: {key}")
            expanded.append(environ[key])
        else:
            expanded.append(part)
    return tuple(expanded)


def orphan_check(
    target: RuntimeTarget,
    state: RuntimeState | None,
    *,
    process_alive: ProcessAliveFn,
    port_pid_fn: PortPidFn,
) -> OrphanCheckResult:
    """Detect leftover processes or stale state for a runtime target."""
    occupying_pid = port_pid_fn(target.port)
    port_occupied = occupying_pid is not None

    stale_state_pid: int | None = None
    if state is not None and state.pid is not None:
        if state.status != "running" and process_alive(state.pid):
            stale_state_pid = state.pid

    untracked_port_process = (
        port_occupied
        and (
            state is None
            or state.pid is None
            or occupying_pid != state.pid
        )
    )

    has_orphan = untracked_port_process or stale_state_pid is not None

    if untracked_port_process and stale_state_pid is not None:
        message = (
            f"orphan detected: port {target.port} held by pid {occupying_pid} "
            f"and stale state pid {stale_state_pid}"
        )
    elif untracked_port_process:
        message = f"orphan detected: port {target.port} held by pid {occupying_pid}"
    elif stale_state_pid is not None:
        message = f"orphan detected: stale state pid {stale_state_pid} still running"
    else:
        message = "no orphan detected"

    return OrphanCheckResult(
        has_orphan=has_orphan,
        port_occupied=port_occupied,
        occupying_pid=occupying_pid,
        stale_state_pid=stale_state_pid,
        message=message,
    )
