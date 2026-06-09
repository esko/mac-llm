"""Tests for Tool Operator skeleton (parse, validate, dispatch)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mac_llm.tools.broker import ToolBroker, ToolBrokerError
from mac_llm.tools.operator import ToolOperator, ToolOperatorError


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "hello.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    _init_git_repo(root)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


@pytest.fixture
def operator(repo: Path) -> ToolOperator:
    return ToolOperator(broker=ToolBroker(repo_root=repo))


def test_operator_dispatches_valid_read_only_tool_call(operator: ToolOperator) -> None:
    payload = {
        "tool": "read_file_range",
        "args": {"file": "src/hello.py", "start_line": 1, "end_line": 2},
    }
    result = operator.handle_model_output(
        json.dumps(payload),
        role="tool_operator",
        requester_target="local_fast",
    )
    assert result.status == "ok"
    assert "alpha" in result.output


def test_operator_fails_closed_on_invalid_json(operator: ToolOperator) -> None:
    with pytest.raises(ToolOperatorError, match="invalid JSON"):
        operator.handle_model_output("not json", role="tool_operator", requester_target="local_fast")


def test_operator_fails_closed_on_unknown_tool(operator: ToolOperator) -> None:
    payload = {"tool": "shell", "args": {"command": "ls"}}
    with pytest.raises(ToolOperatorError, match="unknown tool"):
        operator.handle_model_output(
            json.dumps(payload),
            role="tool_operator",
            requester_target="local_fast",
        )


def test_operator_fails_closed_on_malformed_schema(operator: ToolOperator) -> None:
    payload = {"tool": "read_file_range", "args": {"file": "src/hello.py"}}
    with pytest.raises(ToolOperatorError):
        operator.handle_model_output(
            json.dumps(payload),
            role="tool_operator",
            requester_target="local_fast",
        )


def test_operator_dispatches_approval_gated_tool_when_approved(
    operator: ToolOperator, repo: Path
) -> None:
    import hashlib

    old_text = "beta\n"
    digest = hashlib.sha256(old_text.encode("utf-8")).hexdigest()
    payload = {
        "tool": "replace_block_hash_checked",
        "args": {
            "file": "src/hello.py",
            "old_hash": f"sha256:{digest}",
            "old_text": old_text,
            "new_text": "delta\n",
        },
    }
    result = operator.handle_model_output(
        json.dumps(payload),
        role="tool_operator",
        requester_target="local_fast",
        approved=True,
    )
    assert result.status == "ok"
    assert "delta" in (repo / "src" / "hello.py").read_text(encoding="utf-8")


def test_operator_blocks_approval_gated_tool_without_approval(
    operator: ToolOperator,
) -> None:
    payload = {
        "tool": "propose_patch",
        "args": {"file": "src/hello.py", "patch": "---\n+++ \n"},
    }
    with pytest.raises(ToolBrokerError, match="approval required"):
        operator.handle_model_output(
            json.dumps(payload),
            role="tool_operator",
            requester_target="local_fast",
        )
