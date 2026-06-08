"""Validated role-target configuration from PROJECT.md Milestone 7."""

from __future__ import annotations

from dataclasses import dataclass

KNOWN_ROLES = frozenset(
    {
        "coding",
        "planning",
        "review",
        "debugging",
        "summarization",
        "tool_operator",
    }
)

ASK_CLI_ROLES = frozenset({"coding", "planning", "review"})


@dataclass(frozen=True)
class RoleTargetMapping:
    """Configured default/deep targets for one agent role."""

    default_target: str
    deep_target: str
    deep_threshold: str


DEFAULT_ROLE_TARGETS: dict[str, RoleTargetMapping] = {
    "coding": RoleTargetMapping(
        default_target="local_fast",
        deep_target="local_deep_moe",
        deep_threshold="high",
    ),
    "planning": RoleTargetMapping(
        default_target="local_fast",
        deep_target="local_deep_moe",
        deep_threshold="medium",
    ),
    "review": RoleTargetMapping(
        default_target="local_fast",
        deep_target="local_deep_moe",
        deep_threshold="medium",
    ),
    "debugging": RoleTargetMapping(
        default_target="local_fast",
        deep_target="local_deep_moe",
        deep_threshold="high_after_evidence",
    ),
    "summarization": RoleTargetMapping(
        default_target="local_fast",
        deep_target="disabled",
        deep_threshold="disabled",
    ),
    "tool_operator": RoleTargetMapping(
        default_target="local_fast",
        deep_target="disabled",
        deep_threshold="disabled",
    ),
}
