"""Tests for RuntimeManager lifecycle without a real model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mac_llm.runtime.manager import RuntimeLifecycleError, RuntimeManager, render_start_command
from mac_llm.runtime.probes import (
    HealthCheckResult,
    command_available,
    expand_command,
    is_port_occupied,
    orphan_check,
    probe_health,
)
from mac_llm.runtime.state import RuntimeState, load_state, save_state
from mac_llm.runtime.target import RuntimeTarget


def _target(tmp_path: Path) -> RuntimeTarget:
    return RuntimeTarget(
        target_id="test_fast",
        runtime_type="test",
        command=("echo", "hello"),
        port=18080,
        health_url="http://127.0.0.1:18080/health",
        log_path=tmp_path / "logs" / "test_fast.log",
        state_path=tmp_path / "state" / "test_fast.json",
        stop_timeout=5,
        model_config_ref="models.test_fast",
    )


def test_state_roundtrip(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = RuntimeState(
        target_id="test_fast",
        pid=4242,
        port=18080,
        start_time=1710000000.0,
        stop_timeout=30,
        last_error=None,
        status="running",
    )

    save_state(state_path, state)
    loaded = load_state(state_path)

    assert loaded == state


def test_is_port_occupied_with_fake_probe() -> None:
    assert is_port_occupied(18080, port_pid_fn=lambda _port: 99) is True
    assert is_port_occupied(18080, port_pid_fn=lambda _port: None) is False


def test_expand_command_requires_environment_variables() -> None:
    with pytest.raises(ValueError, match="missing required environment variable"):
        expand_command(("llama-server", "--model", "${MAC_LLM_MODEL_LOCAL_FAST}"), {})

    expanded = expand_command(
        ("llama-server", "--model", "${MAC_LLM_MODEL_LOCAL_FAST}"),
        {"MAC_LLM_MODEL_LOCAL_FAST": "/tmp/model.gguf"},
    )
    assert expanded == ("llama-server", "--model", "/tmp/model.gguf")


def test_orphan_check_detects_untracked_port_process(tmp_path: Path) -> None:
    target = _target(tmp_path)

    result = orphan_check(
        target,
        None,
        process_alive=lambda _pid: False,
        port_pid_fn=lambda _port: 77,
    )

    assert result.has_orphan is True
    assert result.port_occupied is True
    assert result.occupying_pid == 77
    assert "orphan detected" in result.message


def test_orphan_check_detects_stale_state_pid(tmp_path: Path) -> None:
    target = _target(tmp_path)
    state = RuntimeState(
        target_id=target.target_id,
        pid=55,
        port=target.port,
        start_time=1.0,
        stop_timeout=5,
        last_error=None,
        status="stopped",
    )

    result = orphan_check(
        target,
        state,
        process_alive=lambda pid: pid == 55,
        port_pid_fn=lambda _port: None,
    )

    assert result.has_orphan is True
    assert result.stale_state_pid == 55


def test_start_fails_when_command_unavailable(tmp_path: Path) -> None:
    target = _target(tmp_path)
    target = RuntimeTarget(
        **{**target.__dict__, "command": ("definitely-missing-binary-xyz",)}
    )
    manager = RuntimeManager(target=target)

    with pytest.raises(RuntimeLifecycleError, match="runtime command unavailable"):
        manager.start()

    state = load_state(target.state_path)
    assert state is not None
    assert state.last_error == "runtime command unavailable"


def test_start_fails_when_port_occupied(tmp_path: Path) -> None:
    target = _target(tmp_path)
    manager = RuntimeManager(
        target=target,
        port_pid_fn=lambda _port: 88,
    )

    with pytest.raises(RuntimeLifecycleError, match="port 18080 is occupied"):
        manager.start()

    state = load_state(target.state_path)
    assert state is not None
    assert state.last_error == "port 18080 is occupied"


def test_start_and_stop_manage_process_with_state(tmp_path: Path) -> None:
    target = _target(tmp_path)
    started_pid = 101
    stopped: list[int] = []

    def fake_start(command: tuple[str, ...], log_path: Path) -> int:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(" ".join(command) + "\n", encoding="utf-8")
        return started_pid

    def fake_stop(pid: int, timeout: int) -> bool:
        stopped.append(pid)
        return True

    manager = RuntimeManager(
        target=target,
        port_pid_fn=lambda _port: None,
        start_process=fake_start,
        stop_process=fake_stop,
    )

    running = manager.start()
    assert running.pid == started_pid
    assert running.port == target.port
    assert running.start_time is not None
    assert running.stop_timeout == target.stop_timeout
    assert running.status == "running"

    stopped_state = manager.stop()
    assert stopped == [started_pid]
    assert stopped_state.status == "stopped"
    assert stopped_state.pid is None
    assert stopped_state.last_error is None


def test_stop_fails_when_not_running(tmp_path: Path) -> None:
    target = _target(tmp_path)
    manager = RuntimeManager(target=target, port_pid_fn=lambda _port: None)

    with pytest.raises(RuntimeLifecycleError, match="no managed runtime is running"):
        manager.stop()

    state = load_state(target.state_path)
    assert state is not None
    assert state.last_error == "no managed runtime is running"


def test_health_check_uses_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _target(tmp_path)
    manager = RuntimeManager(target=target)

    monkeypatch.setattr(
        "mac_llm.runtime.manager.probe_health",
        lambda _url: HealthCheckResult(ok=True, message="healthy"),
    )

    assert manager.health_check().ok is True


def test_probe_health_reports_unreachable() -> None:
    result = probe_health("http://127.0.0.1:1/health", timeout=0.2)
    assert result.ok is False
    assert "unreachable" in result.message or "timeout" in result.message


def test_command_available_for_echo() -> None:
    assert command_available(("echo", "hello")) is True
    assert command_available(("definitely-missing-binary-xyz",)) is False


def test_render_start_command_local_fast() -> None:
    from mac_llm.runtime.target import get_target

    target = get_target("local_fast")
    rendered = render_start_command(target)

    assert rendered.target_id == "local_fast"
    assert rendered.runtime_type
    assert rendered.command
    assert rendered.port > 0
    assert rendered.health_url.startswith("http")
    assert rendered.state_path


def test_cli_runtime_start_stop_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from mac_llm.cli import _cmd_runtime_start, _cmd_runtime_status, _cmd_runtime_stop

    state_path = tmp_path / "state" / "local_fast.json"
    log_path = tmp_path / "logs" / "local_fast.log"

    def fake_get_target(target_id: str) -> RuntimeTarget:
        return RuntimeTarget(
            target_id=target_id,
            runtime_type="test",
            command=("echo", "hello"),
            port=18081,
            health_url="http://127.0.0.1:18081/health",
            log_path=log_path,
            state_path=state_path,
            stop_timeout=5,
            model_config_ref="models.test_fast",
        )

    started_pid = 202
    stopped: list[int] = []

    monkeypatch.setattr("mac_llm.cli.get_target", fake_get_target)
    monkeypatch.setattr(
        "mac_llm.runtime.manager._default_start_process",
        lambda command, log_path: started_pid,
    )
    monkeypatch.setattr(
        "mac_llm.runtime.manager._default_stop_process",
        lambda pid, timeout: stopped.append(pid) or True,
    )
    monkeypatch.setattr(
        "mac_llm.runtime.manager.is_port_occupied",
        lambda _port, port_pid_fn=None: False,
    )

    assert _cmd_runtime_start("local_fast") == 0
    assert f"started pid {started_pid}" in capsys.readouterr().out

    assert _cmd_runtime_status("local_fast") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pid"] == started_pid
    assert payload["status"] == "running"

    assert _cmd_runtime_stop("local_fast") == 0
    assert "stopped runtime" in capsys.readouterr().out
    assert stopped == [started_pid]
