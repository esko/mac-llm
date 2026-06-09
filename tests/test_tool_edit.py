"""Tests for approval-gated write/edit/test tools."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from mac_llm.tools.broker import ToolBroker, ToolBrokerError


def _hash_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


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
    (root / "src" / "hello.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n",
        encoding="utf-8",
    )
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
def broker(repo: Path) -> ToolBroker:
    return ToolBroker(repo_root=repo)


def test_replace_block_hash_checked_applies_when_hash_matches(
    broker: ToolBroker, repo: Path
) -> None:
    old_text = "line2\n"
    new_text = "replaced\n"
    result = broker.dispatch(
        role="coding",
        requester_target="local_fast",
        approved=True,
        payload={
            "tool": "replace_block_hash_checked",
            "args": {
                "file": "src/hello.py",
                "old_hash": _hash_text(old_text),
                "old_text": old_text,
                "new_text": new_text,
            },
        },
    )
    assert result.status == "ok"
    content = (repo / "src" / "hello.py").read_text(encoding="utf-8")
    assert "replaced" in content
    assert "line2" not in content


def test_replace_block_hash_checked_fails_closed_on_hash_mismatch(
    broker: ToolBroker, repo: Path
) -> None:
    original = (repo / "src" / "hello.py").read_text(encoding="utf-8")
    with pytest.raises(ToolBrokerError, match="hash mismatch"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            approved=True,
            payload={
                "tool": "replace_block_hash_checked",
                "args": {
                    "file": "src/hello.py",
                    "old_hash": "sha256:" + "0" * 64,
                    "old_text": "line2\n",
                    "new_text": "replaced\n",
                },
            },
        )
    assert (repo / "src" / "hello.py").read_text(encoding="utf-8") == original


def test_propose_patch_blocked_without_approval(broker: ToolBroker) -> None:
    patch = (
        "--- a/src/hello.py\n"
        "+++ b/src/hello.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+patched\n"
        " line3\n"
    )
    with pytest.raises(ToolBrokerError, match="approval required"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            payload={
                "tool": "propose_patch",
                "args": {"file": "src/hello.py", "patch": patch},
            },
        )


def test_propose_patch_applies_when_approved(broker: ToolBroker, repo: Path) -> None:
    patch = (
        "--- a/src/hello.py\n"
        "+++ b/src/hello.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+patched\n"
        " line3\n"
    )
    result = broker.dispatch(
        role="coding",
        requester_target="local_fast",
        approved=True,
        payload={
            "tool": "propose_patch",
            "args": {"file": "src/hello.py", "patch": patch},
        },
    )
    assert result.status == "ok"
    content = (repo / "src" / "hello.py").read_text(encoding="utf-8")
    assert "patched" in content
    assert "line2" not in content


def test_run_test_command_blocked_without_approval(broker: ToolBroker) -> None:
    with pytest.raises(ToolBrokerError, match="approval required"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            payload={
                "tool": "run_test_command",
                "args": {"command": "pytest tests/test_ok.py -q"},
            },
        )


def test_run_test_command_runs_constrained_pytest_when_approved(
    broker: ToolBroker,
) -> None:
    result = broker.dispatch(
        role="coding",
        requester_target="local_fast",
        approved=True,
        payload={
            "tool": "run_test_command",
            "args": {"command": "pytest tests/test_ok.py -q"},
        },
    )
    assert result.status == "ok"
    assert "passed" in result.output.lower() or "1" in result.output


def test_run_test_command_rejects_shell_metacharacters(broker: ToolBroker) -> None:
    with pytest.raises(ToolBrokerError, match="disallowed"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            approved=True,
            payload={
                "tool": "run_test_command",
                "args": {"command": "pytest; rm -rf /"},
            },
        )


def test_run_test_command_rejects_non_pytest_commands(broker: ToolBroker) -> None:
    with pytest.raises(ToolBrokerError, match="disallowed"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            approved=True,
            payload={
                "tool": "run_test_command",
                "args": {"command": "bash -c 'echo hi'"},
            },
        )
