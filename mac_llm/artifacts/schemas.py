"""Compact JSON-serializable structured artifact schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


def _require_fields(data: dict[str, Any], required: set[str]) -> None:
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")


def _require_artifact_type(data: dict[str, Any], expected: str) -> None:
    actual = data.get("artifact_type")
    if actual != expected:
        raise ValueError(
            f"artifact_type must be {expected!r}, got {actual!r}"
        )


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3] + "..."


@runtime_checkable
class StructuredArtifact(Protocol):
    """JSON-serializable compact artifact."""

    artifact_type: str

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructuredArtifact: ...


@dataclass(frozen=True)
class UserTaskSummary:
    """Compact summary of the user's task or request."""

    intent: str
    goal: str
    artifact_type: str = "user_task_summary"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "intent": self.intent,
            "goal": self.goal,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserTaskSummary:
        _require_artifact_type(data, "user_task_summary")
        _require_fields(data, {"intent", "goal"})
        return cls(intent=data["intent"], goal=data["goal"])


@dataclass(frozen=True)
class RepoStateSummary:
    """Compact summary of repository working-tree state."""

    root_path: str
    branch: str
    dirty: bool
    staged_files: int
    unstaged_files: int
    untracked_files: int | None = None
    artifact_type: str = "repo_state_summary"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_type": self.artifact_type,
            "root_path": self.root_path,
            "branch": self.branch,
            "dirty": self.dirty,
            "staged_files": self.staged_files,
            "unstaged_files": self.unstaged_files,
        }
        if self.untracked_files is not None:
            payload["untracked_files"] = self.untracked_files
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoStateSummary:
        _require_artifact_type(data, "repo_state_summary")
        _require_fields(
            data,
            {"root_path", "branch", "dirty", "staged_files", "unstaged_files"},
        )
        return cls(
            root_path=data["root_path"],
            branch=data["branch"],
            dirty=data["dirty"],
            staged_files=data["staged_files"],
            unstaged_files=data["unstaged_files"],
            untracked_files=data.get("untracked_files"),
        )


@dataclass(frozen=True)
class GitDiffSummary:
    """Compact summary of a git diff."""

    files_changed: int
    insertions: int
    deletions: int
    paths: list[str]
    summary: str
    artifact_type: str = "git_diff_summary"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "paths": self.paths,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitDiffSummary:
        _require_artifact_type(data, "git_diff_summary")
        _require_fields(
            data,
            {"files_changed", "insertions", "deletions", "paths", "summary"},
        )
        return cls(
            files_changed=data["files_changed"],
            insertions=data["insertions"],
            deletions=data["deletions"],
            paths=list(data["paths"]),
            summary=data["summary"],
        )


@dataclass(frozen=True)
class StackTraceSummary:
    """Compact summary of an error stack trace."""

    error_type: str
    message: str
    top_frame: str
    frames: int
    snippet: str | None = None
    artifact_type: str = "stack_trace_summary"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_type": self.artifact_type,
            "error_type": self.error_type,
            "message": self.message,
            "top_frame": self.top_frame,
            "frames": self.frames,
        }
        if self.snippet is not None:
            payload["snippet"] = self.snippet
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StackTraceSummary:
        _require_artifact_type(data, "stack_trace_summary")
        _require_fields(
            data,
            {"error_type", "message", "top_frame", "frames"},
        )
        return cls(
            error_type=data["error_type"],
            message=data["message"],
            top_frame=data["top_frame"],
            frames=data["frames"],
            snippet=data.get("snippet"),
        )


@dataclass(frozen=True)
class TestFailureSummary:
    """Compact summary of a failing test."""

    test_name: str
    file_path: str
    message: str
    assertion: str | None = None
    artifact_type: str = "test_failure_summary"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_type": self.artifact_type,
            "test_name": self.test_name,
            "file_path": self.file_path,
            "message": self.message,
        }
        if self.assertion is not None:
            payload["assertion"] = self.assertion
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestFailureSummary:
        _require_artifact_type(data, "test_failure_summary")
        _require_fields(data, {"test_name", "file_path", "message"})
        return cls(
            test_name=data["test_name"],
            file_path=data["file_path"],
            message=data["message"],
            assertion=data.get("assertion"),
        )


TestFailureSummary.__test__ = False  # noqa: SLF001 — not a pytest test class


@dataclass(frozen=True)
class ToolResultSummary:
    """Compact summary of a tool execution result."""

    tool: str
    status: str
    summary: str
    token_estimate: int | None = None
    artifact_type: str = "tool_result_summary"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_type": self.artifact_type,
            "tool": self.tool,
            "status": self.status,
            "summary": self.summary,
        }
        if self.token_estimate is not None:
            payload["token_estimate"] = self.token_estimate
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolResultSummary:
        _require_artifact_type(data, "tool_result_summary")
        _require_fields(data, {"tool", "status", "summary"})
        return cls(
            tool=data["tool"],
            status=data["status"],
            summary=data["summary"],
            token_estimate=data.get("token_estimate"),
        )


@dataclass(frozen=True)
class EditAttemptSummary:
    """Compact summary of a file edit attempt."""

    file: str
    status: str
    tool: str
    artifact_type: str = "edit_attempt_summary"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "file": self.file,
            "status": self.status,
            "tool": self.tool,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditAttemptSummary:
        _require_artifact_type(data, "edit_attempt_summary")
        _require_fields(data, {"file", "status", "tool"})
        return cls(file=data["file"], status=data["status"], tool=data["tool"])


@dataclass(frozen=True)
class ExternalConsultationBrief:
    """Compact brief for an external consultation request."""

    role: str
    target: str
    mode: str
    question: str
    context_refs: list[str] | None = None
    artifact_type: str = "external_consultation_brief"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_type": self.artifact_type,
            "role": self.role,
            "target": self.target,
            "mode": self.mode,
            "question": self.question,
        }
        if self.context_refs is not None:
            payload["context_refs"] = self.context_refs
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalConsultationBrief:
        _require_artifact_type(data, "external_consultation_brief")
        _require_fields(data, {"role", "target", "mode", "question"})
        return cls(
            role=data["role"],
            target=data["target"],
            mode=data["mode"],
            question=data["question"],
            context_refs=data.get("context_refs"),
        )


@dataclass(frozen=True)
class ExternalConsultationOpinion:
    """Compact opinion returned from an external consultation."""

    target: str
    mode: str
    opinion: str
    confidence: str | None = None
    artifact_type: str = "external_consultation_opinion"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_type": self.artifact_type,
            "target": self.target,
            "mode": self.mode,
            "opinion": self.opinion,
        }
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalConsultationOpinion:
        _require_artifact_type(data, "external_consultation_opinion")
        _require_fields(data, {"target", "mode", "opinion"})
        return cls(
            target=data["target"],
            mode=data["mode"],
            opinion=data["opinion"],
            confidence=data.get("confidence"),
        )


ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        cls.__dataclass_fields__["artifact_type"].default  # type: ignore[attr-defined]
        for cls in (
            UserTaskSummary,
            RepoStateSummary,
            GitDiffSummary,
            StackTraceSummary,
            TestFailureSummary,
            ToolResultSummary,
            EditAttemptSummary,
            ExternalConsultationBrief,
            ExternalConsultationOpinion,
        )
    }
)

_MAX_USER_GOAL_CHARS = 500
_MAX_GIT_DIFF_PATHS = 10
_MAX_TOOL_SUMMARY_CHARS = 200


def make_user_task_summary(*, user_text: str, intent: str = "general") -> UserTaskSummary:
    """Build a compact user-task summary from raw user text."""
    goal = user_text.strip()
    if not goal:
        raise ValueError("user_text must not be empty")
    return UserTaskSummary(intent=intent, goal=_truncate(goal, _MAX_USER_GOAL_CHARS))


def make_git_diff_summary(
    *,
    files_changed: int,
    insertions: int,
    deletions: int,
    paths: list[str],
    summary: str | None = None,
) -> GitDiffSummary:
    """Build a compact git-diff summary from diff stats."""
    compact_paths = paths[:_MAX_GIT_DIFF_PATHS]
    if summary is None:
        summary = (
            f"{files_changed} file(s) changed, "
            f"+{insertions}/-{deletions}"
        )
    return GitDiffSummary(
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
        paths=compact_paths,
        summary=summary,
    )


def make_tool_result_summary(
    *,
    tool: str,
    status: str,
    output: str,
    token_estimate: int | None = None,
) -> ToolResultSummary:
    """Build a compact tool-result summary from raw tool output."""
    return ToolResultSummary(
        tool=tool,
        status=status,
        summary=_truncate(output.strip(), _MAX_TOOL_SUMMARY_CHARS),
        token_estimate=token_estimate,
    )
