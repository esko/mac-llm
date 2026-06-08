"""Role-target configuration and manual ask orchestration."""

from mac_llm.roles.ask import AskError, AskResult, run_ask
from mac_llm.roles.select import SelectionResult, UnknownRoleError, select_target

__all__ = [
    "AskError",
    "AskResult",
    "SelectionResult",
    "UnknownRoleError",
    "run_ask",
    "select_target",
]
