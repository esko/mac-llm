"""External-target schemas, disabled-by-default config, and fail-closed policy."""

from mac_llm.external.config import (
    DEFAULT_EXTERNAL_TARGETS,
    UnknownExternalTargetError,
    get_external_target,
    list_external_target_ids,
)
from mac_llm.external.policy import (
    DEFAULT_EXTERNAL_AGENTS_POLICY,
    ExternalAgentsGate,
    ExternalAgentsPolicy,
    ExternalPolicyError,
    validate_fallback_chain,
)
from mac_llm.external.schemas import (
    CONSULTATION_MODES,
    EXECUTION_MODES,
    AgentTarget,
    ConsultationMode,
    EscalationPolicy,
    ExecutionMode,
    ExternalAgentTarget,
    ExternalCostLedgerEntry,
    ExternalToolRequest,
    ExternalToolResult,
    FallbackChain,
    default_fallback_chains,
)

__all__ = [
    "CONSULTATION_MODES",
    "DEFAULT_EXTERNAL_AGENTS_POLICY",
    "DEFAULT_EXTERNAL_TARGETS",
    "EXECUTION_MODES",
    "AgentTarget",
    "ConsultationMode",
    "EscalationPolicy",
    "ExecutionMode",
    "ExternalAgentTarget",
    "ExternalAgentsGate",
    "ExternalAgentsPolicy",
    "ExternalCostLedgerEntry",
    "ExternalPolicyError",
    "ExternalToolRequest",
    "ExternalToolResult",
    "FallbackChain",
    "UnknownExternalTargetError",
    "default_fallback_chains",
    "get_external_target",
    "list_external_target_ids",
    "validate_fallback_chain",
]
