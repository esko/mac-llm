"""Tests for Tool Broker schema validation, policy gating, and read-only tools."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mac_llm.tools.broker import ToolBroker, ToolBrokerError
from mac_llm.tools.log import TOOL_LOG_FIELDS, ToolDispatchLogEntry
from mac_llm.tools.schema import (
    APPROVAL_GATED_TOOLS,
    READ_ONLY_TOOLS,
    ToolCallValidationError,
    validate_tool_call,
)


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
    (root / "README.md").write_text("# demo\nfindme token\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
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


def test_registry_classifies_read_only_and_approval_gated_tools() -> None:
    assert "read_file_range" in READ_ONLY_TOOLS
    assert "search_text" in READ_ONLY_TOOLS
    assert "git_status" in READ_ONLY_TOOLS
    assert "git_diff" in READ_ONLY_TOOLS
    assert "list_files" in READ_ONLY_TOOLS
    assert "replace_block_hash_checked" in APPROVAL_GATED_TOOLS
    assert "propose_patch" in APPROVAL_GATED_TOOLS
    assert "run_test_command" in APPROVAL_GATED_TOOLS
    assert "shell" not in READ_ONLY_TOOLS
    assert "shell" not in APPROVAL_GATED_TOOLS


def test_validate_tool_call_accepts_read_only_tool() -> None:
    call = validate_tool_call(
        {
            "tool": "read_file_range",
            "args": {"file": "src/hello.py", "start_line": 1, "end_line": 2},
        }
    )
    assert call.tool == "read_file_range"
    assert call.args["file"] == "src/hello.py"


@pytest.mark.parametrize(
    "payload",
    [
        {"args": {"file": "x"}},
        {"tool": "read_file_range"},
        {"tool": "read_file_range", "args": "bad"},
        {"tool": "read_file_range", "args": {"file": "x"}},
        {"tool": "read_file_range", "args": {"file": "x", "start_line": 0, "end_line": 1}},
    ],
)
def test_validate_tool_call_rejects_malformed_args(payload: dict) -> None:
    with pytest.raises(ToolCallValidationError):
        validate_tool_call(payload)


def test_broker_rejects_unknown_tool(broker: ToolBroker) -> None:
    with pytest.raises(ToolBrokerError, match="unknown tool"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            payload={"tool": "shell", "args": {"command": "ls"}},
        )


def test_broker_rejects_unsafe_path_escape(broker: ToolBroker) -> None:
    with pytest.raises(ToolBrokerError, match="unsafe path"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            payload={
                "tool": "read_file_range",
                "args": {"file": "../../etc/passwd", "start_line": 1, "end_line": 1},
            },
        )


def test_broker_rejects_denied_path(broker: ToolBroker) -> None:
    with pytest.raises(ToolBrokerError, match="denied path"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            payload={
                "tool": "read_file_range",
                "args": {"file": ".env", "start_line": 1, "end_line": 1},
            },
        )


def test_broker_blocks_approval_gated_tool_without_approval(broker: ToolBroker) -> None:
    with pytest.raises(ToolBrokerError, match="approval required"):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            payload={
                "tool": "propose_patch",
                "args": {"file": "src/hello.py", "patch": "diff"},
            },
        )


def test_read_file_range_returns_requested_lines(broker: ToolBroker) -> None:
    result = broker.dispatch(
        role="coding",
        requester_target="local_fast",
        payload={
            "tool": "read_file_range",
            "args": {"file": "src/hello.py", "start_line": 2, "end_line": 3},
        },
    )
    assert result.status == "ok"
    assert "line2" in result.output
    assert "line3" in result.output


def test_search_text_finds_pattern_in_repo(broker: ToolBroker) -> None:
    result = broker.dispatch(
        role="review",
        requester_target="local_fast",
        payload={"tool": "search_text", "args": {"pattern": "findme", "path": "."}},
    )
    assert result.status == "ok"
    assert "README.md" in result.output


def test_git_status_reports_clean_tree_after_commit(broker: ToolBroker) -> None:
    result = broker.dispatch(
        role="coding",
        requester_target="local_fast",
        payload={"tool": "git_status", "args": {}},
    )
    assert result.status == "ok"
    assert "On branch" in result.output or "main" in result.output.lower()


def test_git_diff_returns_empty_when_clean(broker: ToolBroker) -> None:
    result = broker.dispatch(
        role="coding",
        requester_target="local_fast",
        payload={"tool": "git_diff", "args": {}},
    )
    assert result.status == "ok"


def test_list_files_lists_directory_entries(broker: ToolBroker) -> None:
    result = broker.dispatch(
        role="coding",
        requester_target="local_fast",
        payload={"tool": "list_files", "args": {"path": "src"}},
    )
    assert result.status == "ok"
    assert "hello.py" in result.output


def test_dispatch_log_entry_has_required_fields(broker: ToolBroker) -> None:
    broker.dispatch(
        role="tool_operator",
        requester_target="local_fast",
        payload={
            "tool": "read_file_range",
            "args": {"file": "src/hello.py", "start_line": 1, "end_line": 1},
        },
    )
    assert len(broker.log_entries) == 1
    entry = broker.log_entries[0]
    assert isinstance(entry, ToolDispatchLogEntry)
    payload = entry.to_dict()
    for field in TOOL_LOG_FIELDS:
        assert field in payload
    assert entry.role == "tool_operator"
    assert entry.requester_target == "local_fast"
    assert entry.tool == "read_file_range"
    assert entry.approval_status == "pre_approved"
    assert entry.args_hash.startswith("sha256:")
    assert entry.result_summary
    assert entry.result_token_size >= 0
    assert isinstance(entry.result_summarized, bool)


def test_log_entry_serializes_to_json(broker: ToolBroker) -> None:
    broker.dispatch(
        role="coding",
        requester_target="local_fast",
        payload={"tool": "git_status", "args": {}},
    )
    serialized = json.dumps(broker.log_entries[0].to_dict(), sort_keys=True)
    restored = json.loads(serialized)
    assert restored["tool"] == "git_status"


def test_broker_has_no_shell_tool(broker: ToolBroker) -> None:
    with pytest.raises(ToolBrokerError):
        broker.dispatch(
            role="coding",
            requester_target="local_fast",
            payload={"tool": "run_shell", "args": {"command": "echo hi"}},
        )


def test_search_text_does_not_leak_denied_files(broker: ToolBroker) -> None:
    result = broker.dispatch(
        role="review",
        requester_target="local_fast",
        payload={"tool": "search_text", "args": {"pattern": "SECRET"}},
    )
    assert result.status == "ok"
    assert ".env" not in result.output
    assert "SECRET" not in result.output


def test_list_files_recursive_excludes_denied_files(broker: ToolBroker) -> None:
    result = broker.dispatch(
        role="coding",
        requester_target="local_fast",
        payload={"tool": "list_files", "args": {"path": ".", "recursive": True}},
    )
    assert result.status == "ok"
    assert ".env" not in result.output
