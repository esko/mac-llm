"""Role-target configuration and pure selection."""

from mac_llm.roles.config import (
    DEFAULT_ROLE_TARGETS,
    KNOWN_ROLES,
    RoleTargetMapping,
    validate_role_targets,
)
from mac_llm.roles.select import SelectionResult, UnknownRoleError, select_target

__all__ = [
    "DEFAULT_ROLE_TARGETS",
    "KNOWN_ROLES",
    "RoleTargetMapping",
    "SelectionResult",
    "UnknownRoleError",
    "select_target",
    "validate_role_targets",
]
