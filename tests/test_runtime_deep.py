"""Tests for local_deep_moe mlx-sniper target rendering and lifecycle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mac_llm.runtime.manager import RuntimeLifecycleError, RuntimeManager, render_start_command
from mac_llm.runtime.probes import expand_command, orphan_check
from mac_llm.runtime.state import load_state
from mac_llm.runtime.target import get_target


def test_local_deep_moe_is_registered_with_mlx_sniper_fields() -> None:
    target = get_target("local_deep_moe")

    assert target.target_id == "local_deep_moe"
    assert target.runtime_type == "mlx_sniper"
    assert target.command[0] == "mlx-sniper"
    assert "serve" in target.command
    assert "${MAC_LLM_MODEL_LOCAL_DEEP_MOE}" in target.command
    assert target.port == 8081
    assert target.health_url == "http://127.0.0.1:8081/api/tags"
    assert target.log_path.name == "local_deep_moe.log"
    assert target.state_path.name == "local_deep_moe.json"
    assert target.stop_timeout > 0
    assert target.model_config_ref == "models.local_deep_moe"


def test_render_start_command_local_deep_moe() -> None:
    target = get_target("local_deep_moe")
    rendered = render_start_command(target)

    assert rendered.target_id == "local_deep_moe"
    assert rendered.runtime_type == "mlx_sniper"
    assert rendered.command[0] == "mlx-sniper"
    assert rendered.port == 8081
    assert rendered.health_url.startswith("http")
    assert rendered.model_config_ref == "models.local_deep_moe"
    assert all(
        candidate not in " ".join(rendered.command)
        for candidate in ("Qwen3.5-35B-A3B", "Qwen3-30B-A3B")
    )


def test_cli_runtime_render_local_deep_moe() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mac_llm.cli", "runtime", "render", "local_deep_moe"],
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout

    assert "target_id: local_deep_moe" in output
    assert "runtime_type: mlx_sniper" in output
    assert "command: mlx-sniper serve" in output
    assert "port: 8081" in output
    assert "health_url: http://127.0.0.1:8081/api/tags" in output
    assert "model_config_ref: models.local_deep_moe" in output


def test_expand_command_requires_local_deep_moe_model_env() -> None:
    target = get_target("local_deep_moe")

    with pytest.raises(ValueError, match="missing required environment variable"):
        expand_command(target.command, {})

    expanded = expand_command(
        target.command,
        {"MAC_LLM_MODEL_LOCAL_DEEP_MOE": "/tmp/qwen3.5-35b-sniper"},
    )
    assert expanded == (
        "mlx-sniper",
        "serve",
        "/tmp/qwen3.5-35b-sniper",
        "--host",
        "127.0.0.1",
        "--port",
        "8081",
    )


def test_local_deep_moe_start_fails_when_command_unavailable(tmp_path: Path) -> None:
    target = get_target("local_deep_moe")
    target = target.__class__(
        **{
            **target.__dict__,
            "log_path": tmp_path / "logs" / "local_deep_moe.log",
            "state_path": tmp_path / "state" / "local_deep_moe.json",
            "command": ("definitely-missing-mlx-sniper-binary", "serve", "/tmp/model"),
        }
    )
    manager = RuntimeManager(target=target)

    with pytest.raises(RuntimeLifecycleError, match="runtime command unavailable"):
        manager.start()

    state = load_state(target.state_path)
    assert state is not None
    assert state.last_error == "runtime command unavailable"


def test_local_deep_moe_start_and_stop_with_fakes(tmp_path: Path) -> None:
    target = get_target("local_deep_moe")
    target = target.__class__(
        **{
            **target.__dict__,
            "log_path": tmp_path / "logs" / "local_deep_moe.log",
            "state_path": tmp_path / "state" / "local_deep_moe.json",
            "command": ("echo", "deep-moe"),
        }
    )
    started_pid = 303
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
    assert running.status == "running"

    stopped_state = manager.stop()
    assert stopped == [started_pid]
    assert stopped_state.status == "stopped"


def test_local_deep_moe_orphan_check_detects_untracked_port(tmp_path: Path) -> None:
    target = get_target("local_deep_moe")
    target = target.__class__(
        **{
            **target.__dict__,
            "log_path": tmp_path / "logs" / "local_deep_moe.log",
            "state_path": tmp_path / "state" / "local_deep_moe.json",
        }
    )

    result = orphan_check(
        target,
        None,
        process_alive=lambda _pid: False,
        port_pid_fn=lambda _port: 909,
    )

    assert result.has_orphan is True
    assert "orphan detected" in result.message
