"""Pure role-target selection (manual only, no automatic router)."""

from __future__ import annotations

from dataclasses import dataclass

from mac_llm.roles.config import DEFAULT_ROLE_TARGETS, KNOWN_ROLES, RoleTargetMapping
from mac_llm.runtime.target import get_target


class UnknownRoleError(ValueError):
    """Raised when a role is not configured."""


@dataclass(frozen=True)
class SelectionResult:
    """Resolved target for a role and difficulty."""

    target_id: str
    deep_escalation: bool
    cache_strategy: str


def _validate_mapping(role: str, mapping: RoleTargetMapping) -> None:
    get_target(mapping.default_target)
    if mapping.deep_target != "disabled":
        get_target(mapping.deep_target)


def select_target(role: str, *, difficulty: str = "medium") -> SelectionResult:
    """Return the configured target id and deep-escalation hint for a role."""
    if role not in KNOWN_ROLES:
        raise UnknownRoleError(f"unknown role: {role}")

    mapping = DEFAULT_ROLE_TARGETS[role]
    _validate_mapping(role, mapping)

    deep_escalation = _deep_escalation_indicated(mapping, difficulty)
    target_id = mapping.default_target
    if deep_escalation and mapping.deep_target != "disabled":
        target_id = mapping.deep_target

    return SelectionResult(
        target_id=target_id,
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
