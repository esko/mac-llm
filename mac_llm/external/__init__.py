"""External-target schemas, disabled-by-default config, and fail-closed policy."""

from mac_llm.external.brief import (
    ExternalBrokeredToolError,
    ExternalConsultationDryRun,
    RenderedExternalConsultationBrief,
    assert_external_brokered_tool_allowed,
    render_dry_run_consultation_brief,
)
from mac_llm.external.config import (
    DEFAULT_EXTERNAL_TARGETS,
    UnknownExternalTargetError,
    get_external_target,
    list_external_target_ids,
)
from mac_llm.external.ledger import ExternalCostLedger
from mac_llm.external.policy import (
    DEFAULT_EXTERNAL_AGENTS_POLICY,
    ExternalAgentsGate,
    ExternalAgentsPolicy,
    ExternalPolicyError,
    validate_fallback_chain,
)
from mac_llm.external.redaction import RedactionError, validate_context_refs
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
    "ExternalBrokeredToolError",
    "ExternalConsultationDryRun",
    "ExternalCostLedger",
    "ExternalCostLedgerEntry",
    "ExternalPolicyError",
    "ExternalToolRequest",
    "ExternalToolResult",
    "FallbackChain",
    "RedactionError",
    "RenderedExternalConsultationBrief",
    "UnknownExternalTargetError",
    "assert_external_brokered_tool_allowed",
    "default_fallback_chains",
    "get_external_target",
    "list_external_target_ids",
    "render_dry_run_consultation_brief",
    "validate_context_refs",
    "validate_fallback_chain",
]
