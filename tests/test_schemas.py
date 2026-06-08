"""Tests for structured artifact schemas and writer integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mac_llm.artifacts.schemas import (
    ARTIFACT_TYPES,
    EditAttemptSummary,
    ExternalConsultationBrief,
    ExternalConsultationOpinion,
    GitDiffSummary,
    RepoStateSummary,
    StackTraceSummary,
    TestFailureSummary,
    ToolResultSummary,
    UserTaskSummary,
    make_git_diff_summary,
    make_tool_result_summary,
    make_user_task_summary,
)
from mac_llm.bench.artifacts import BenchmarkArtifactWriter


def _round_trip(artifact: object) -> dict:
    data = artifact.to_dict()  # type: ignore[attr-defined]
    serialized = json.dumps(data, sort_keys=True)
    restored = type(artifact).from_dict(json.loads(serialized))  # type: ignore[attr-defined]
    return restored.to_dict()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "artifact",
    [
        UserTaskSummary(intent="fix", goal="repair failing test"),
        RepoStateSummary(
            root_path="/repo",
            branch="main",
            dirty=True,
            staged_files=1,
            unstaged_files=2,
        ),
        GitDiffSummary(
            files_changed=2,
            insertions=10,
            deletions=3,
            paths=["a.py", "b.py"],
            summary="two files changed",
        ),
        StackTraceSummary(
            error_type="ValueError",
            message="bad value",
            top_frame="test_foo",
            frames=5,
        ),
        TestFailureSummary(
            test_name="test_foo",
            file_path="tests/test_foo.py",
            message="assert 1 == 2",
        ),
        ToolResultSummary(tool="git_status", status="ok", summary="clean tree"),
        EditAttemptSummary(file="src/a.py", status="applied", tool="replace_block"),
        ExternalConsultationBrief(
            role="review",
            target="external_reviewer",
            mode="critique_consult",
            question="Is this API change safe?",
        ),
        ExternalConsultationOpinion(
            target="external_reviewer",
            mode="critique_consult",
            opinion="Looks safe with minor notes",
        ),
    ],
)
def test_serialization_round_trip(artifact: object) -> None:
    assert _round_trip(artifact) == artifact.to_dict()  # type: ignore[attr-defined]


@pytest.mark.parametrize("artifact_type", sorted(ARTIFACT_TYPES))
def test_all_artifact_types_registered(artifact_type: str) -> None:
    assert artifact_type.endswith("_summary") or artifact_type.endswith("_brief") or artifact_type.endswith("_opinion")


@pytest.mark.parametrize(
    ("cls", "payload"),
    [
        (UserTaskSummary, {"artifact_type": "user_task_summary", "intent": "fix"}),
        (GitDiffSummary, {"artifact_type": "git_diff_summary", "files_changed": 1}),
        (ToolResultSummary, {"artifact_type": "tool_result_summary", "tool": "git_diff"}),
    ],
)
def test_from_dict_rejects_missing_required_fields(cls: type, payload: dict) -> None:
    with pytest.raises(ValueError, match="missing required field"):
        cls.from_dict(payload)


@pytest.mark.parametrize(
    ("cls", "wrong_type"),
    [
        (UserTaskSummary, "git_diff_summary"),
        (GitDiffSummary, "user_task_summary"),
        (ToolResultSummary, "repo_state_summary"),
    ],
)
def test_from_dict_rejects_wrong_artifact_type(cls: type, wrong_type: str) -> None:
    base = {"artifact_type": wrong_type}
    with pytest.raises(ValueError, match="artifact_type"):
        cls.from_dict(base)


def test_make_user_task_summary_truncates_long_text() -> None:
    artifact = make_user_task_summary(user_text="x" * 600, intent="implement")
    assert len(artifact.goal) <= 500
    assert artifact.intent == "implement"


def test_make_user_task_summary_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="user_text"):
        make_user_task_summary(user_text="   ")


def test_make_git_diff_summary_caps_paths() -> None:
    paths = [f"file_{i}.py" for i in range(20)]
    artifact = make_git_diff_summary(
        files_changed=20,
        insertions=100,
        deletions=50,
        paths=paths,
    )
    assert len(artifact.paths) <= 10


def test_make_tool_result_summary_truncates_output() -> None:
    artifact = make_tool_result_summary(
        tool="read_file_range",
        status="ok",
        output="line\n" * 200,
    )
    assert len(artifact.summary) <= 200


def test_writer_logs_structured_artifact(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(
        tmp_path,
        timestamp="20260109T120000Z",
        run_id="run-artifacts-1",
    )
    artifact = make_user_task_summary(user_text="add schema tests", intent="implement")
    writer.append_structured_artifact(artifact)

    jsonl_path = writer.run_dir / "run.jsonl"
    event = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    assert event["event"] == "artifact.user_task_summary"
    assert event["status"] == "ok"
    assert event["metadata"]["artifact"] == artifact.to_dict()


def test_writer_summary_includes_structured_artifacts(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")
    writer.append_structured_artifact(
        make_tool_result_summary(tool="git_status", status="ok", output="clean")
    )
    summary = writer.write_summary().read_text(encoding="utf-8")
    assert "artifact.tool_result_summary" in summary
    assert "git_status" in summary
