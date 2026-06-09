"""Disabled-by-default external target configuration."""

from __future__ import annotations

from mac_llm.external.schemas import ExternalAgentTarget


class UnknownExternalTargetError(ValueError):
    """Raised when an external target id is not configured."""


DEFAULT_EXTERNAL_TARGETS: dict[str, ExternalAgentTarget] = {
    "external_architect": ExternalAgentTarget(
        target_id="external_architect",
        mode="consultation",
        enabled=False,
        good_for=("planning", "architecture_critique", "roadmap_review"),
        brokered_tools=("read_file_range", "search_text", "git_diff"),
    ),
    "external_reviewer": ExternalAgentTarget(
        target_id="external_reviewer",
        mode="consultation",
        enabled=False,
        good_for=("review", "safety_review", "api_change_review"),
        brokered_tools=("git_diff", "read_file_range", "search_text"),
    ),
    "external_code_advisor": ExternalAgentTarget(
        target_id="external_code_advisor",
        mode="consultation",
        enabled=False,
        good_for=("debugging", "failed_patch_diagnosis", "implementation_advice"),
        brokered_tools=("read_file_range", "search_text", "git_diff", "propose_patch"),
    ),
    "external_coding_agent": ExternalAgentTarget(
        target_id="external_coding_agent",
        mode="execution",
        enabled=False,
        good_for=("hard_coding_execution",),
        brokered_tools=("read_file_range", "search_text", "git_diff", "propose_patch"),
    ),
    "external_frontier_generalist": ExternalAgentTarget(
        target_id="external_frontier_generalist",
        mode="consultation",
        enabled=False,
        good_for=("general_high_capability_second_opinion",),
        brokered_tools=("read_file_range", "search_text", "git_diff"),
    ),
}


_EXTERNAL_TARGET_ORDER: tuple[str, ...] = (
    "external_architect",
    "external_reviewer",
    "external_code_advisor",
    "external_coding_agent",
    "external_frontier_generalist",
)


def list_external_target_ids() -> tuple[str, ...]:
    """Return configured external target ids in stable order."""
    return _EXTERNAL_TARGET_ORDER


def get_external_target(target_id: str) -> ExternalAgentTarget:
    """Return a configured external target or fail closed."""
    if target_id not in DEFAULT_EXTERNAL_TARGETS:
        raise UnknownExternalTargetError(f"unknown external target: {target_id}")
    return DEFAULT_EXTERNAL_TARGETS[target_id]
