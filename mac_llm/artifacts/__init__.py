"""Structured artifact schemas for compact task/repo/tool summaries."""

from mac_llm.artifacts.schemas import (
    EditAttemptSummary,
    ExternalConsultationBrief,
    ExternalConsultationOpinion,
    GitDiffSummary,
    RepoStateSummary,
    StackTraceSummary,
    StructuredArtifact,
    TestFailureSummary,
    ToolResultSummary,
    UserTaskSummary,
    make_git_diff_summary,
    make_tool_result_summary,
    make_user_task_summary,
)

__all__ = [
    "EditAttemptSummary",
    "ExternalConsultationBrief",
    "ExternalConsultationOpinion",
    "GitDiffSummary",
    "RepoStateSummary",
    "StackTraceSummary",
    "StructuredArtifact",
    "TestFailureSummary",
    "ToolResultSummary",
    "UserTaskSummary",
    "make_git_diff_summary",
    "make_tool_result_summary",
    "make_user_task_summary",
]
