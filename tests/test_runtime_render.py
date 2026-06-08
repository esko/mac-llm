"""Tests for runtime target rendering (no real model or process)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from mac_llm.runtime.manager import render_start_command
from mac_llm.runtime.target import UnknownTargetError, get_target


def test_render_start_command_local_fast() -> None:
    target = get_target("local_fast")
    rendered = render_start_command(target)

    assert rendered.target_id == "local_fast"
    assert rendered.runtime_type
    assert rendered.command
    assert rendered.port > 0
    assert rendered.health_url.startswith("http")
    assert rendered.log_path
    assert rendered.state_path
    assert rendered.stop_timeout > 0
    assert rendered.model_config_ref


def test_get_target_unknown_fails_closed() -> None:
    with pytest.raises(UnknownTargetError, match="unknown runtime target"):
        get_target("does_not_exist")


def test_cli_runtime_render_local_fast() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mac_llm.cli", "runtime", "render", "local_fast"],
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout

    assert "target_id: local_fast" in output
    assert "runtime_type:" in output
    assert "command:" in output
    assert "port:" in output
    assert "health_url:" in output
    assert "log_path:" in output
    assert "state_path:" in output
    assert "model_config_ref:" in output
    assert "stop_timeout:" in output


def test_cli_runtime_render_unknown_target_fails_closed() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mac_llm.cli", "runtime", "render", "missing_target"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "unknown runtime target" in result.stderr.lower()
