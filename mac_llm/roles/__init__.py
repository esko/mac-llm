"""Role-target configuration, selection, and manual ask orchestration."""

from mac_llm.roles.ask import AskError, AskResult, run_ask
from mac_llm.roles.config import (
    DEFAULT_ROLE_TARGETS,
    KNOWN_ROLES,
    RoleTargetMapping,
    validate_role_targets,
)
from mac_llm.roles.select import SelectionResult, UnknownRoleError, select_target

__all__ = [
    "AskError",
    "AskResult",
    "DEFAULT_ROLE_TARGETS",
    "KNOWN_ROLES",
    "RoleTargetMapping",
    "SelectionResult",
    "UnknownRoleError",
    "run_ask",
    "select_target",
    "validate_role_targets",
]
