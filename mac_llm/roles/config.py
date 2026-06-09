"""Validated role-target configuration from PROJECT.md Milestone 7."""

from __future__ import annotations

from dataclasses import dataclass

from mac_llm.runtime.target import UnknownTargetError, get_target

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

# Logical target ids allowed in role config before resolution to runtime targets.
ROLE_TARGET_ALIASES: dict[str, str] = {
    "local_small_or_local_fast": "local_fast",
}


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
        default_target="local_small_or_local_fast",
        deep_target="disabled",
        deep_threshold="disabled",
    ),
}


def resolve_role_target(target_id: str) -> str:
    """Resolve a configured role target id to a runtime registry target."""
    if target_id == "disabled":
        return target_id
    resolved = ROLE_TARGET_ALIASES.get(target_id, target_id)
    get_target(resolved)
    return resolved


def validate_role_targets(
    mappings: dict[str, RoleTargetMapping] | None = None,
) -> None:
    """Validate role mappings against the known role set and target registry."""
    role_targets = mappings if mappings is not None else DEFAULT_ROLE_TARGETS

    unknown_roles = set(role_targets) - KNOWN_ROLES
    if unknown_roles:
        raise ValueError(f"unknown role(s): {', '.join(sorted(unknown_roles))}")

    missing_roles = KNOWN_ROLES - set(role_targets)
    if missing_roles:
        raise ValueError(f"missing role(s): {', '.join(sorted(missing_roles))}")

    for role, mapping in role_targets.items():
        try:
            resolve_role_target(mapping.default_target)
            if mapping.deep_target != "disabled":
                resolve_role_target(mapping.deep_target)
        except UnknownTargetError as exc:
            raise UnknownTargetError(
                f"unknown runtime target for role {role!r}: {exc}"
            ) from exc
