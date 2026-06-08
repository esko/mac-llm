"""Pure role-target selection (manual only, no automatic router)."""

from __future__ import annotations

from dataclasses import dataclass

from mac_llm.roles.config import (
    DEFAULT_ROLE_TARGETS,
    KNOWN_ROLES,
    RoleTargetMapping,
    resolve_role_target,
    validate_role_targets,
)
from mac_llm.runtime.target import UnknownTargetError


class UnknownRoleError(ValueError):
    """Raised when a role is not configured."""


@dataclass(frozen=True)
class SelectionResult:
    """Resolved target for a role and difficulty."""

    target_id: str
    deep_escalation: bool
    cache_strategy: str


def _validate_mapping(mapping: RoleTargetMapping) -> None:
    resolve_role_target(mapping.default_target)
    if mapping.deep_target != "disabled":
        resolve_role_target(mapping.deep_target)


def select_target(role: str, *, difficulty: str = "medium") -> SelectionResult:
    """Return the configured target id and deep-escalation hint for a role."""
    if role not in KNOWN_ROLES:
        raise UnknownRoleError(f"unknown role: {role}")

    mapping = DEFAULT_ROLE_TARGETS[role]
    try:
        _validate_mapping(mapping)
    except UnknownTargetError:
        raise

    deep_escalation = _deep_escalation_indicated(mapping, difficulty)
    configured_target = mapping.default_target
    if deep_escalation and mapping.deep_target != "disabled":
        configured_target = mapping.deep_target

    return SelectionResult(
        target_id=resolve_role_target(configured_target),
        deep_escalation=deep_escalation,
        cache_strategy="role_prefix",
    )


def _deep_escalation_indicated(mapping: RoleTargetMapping, difficulty: str) -> bool:
    if mapping.deep_target == "disabled":
        return False

    threshold = mapping.deep_threshold
    if threshold == "high":
        return difficulty in {"high", "very_high"}
    if threshold == "medium":
        return difficulty in {"medium", "high", "very_high"}
    if threshold == "high_after_evidence":
        return difficulty in {"high", "very_high"}
    return False


validate_role_targets()
