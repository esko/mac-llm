"""Tests for mac-llm CLI entry point."""

from __future__ import annotations

import subprocess
import sys


def test_cli_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mac_llm.cli", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "mac-llm" in result.stdout
    assert "0.1.0" in result.stdout


def test_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mac_llm.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "mac-llm" in result.stdout.lower() or "mac_llm" in result.stdout.lower()
