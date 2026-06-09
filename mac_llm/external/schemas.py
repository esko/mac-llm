"""JSON-serializable external-target schemas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


def _require_fields(data: dict[str, Any], required: set[str]) -> None:
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")


class ConsultationMode(str, Enum):
    """Modes for asking another target for advice without delegating execution."""

    PREFLIGHT_CONSULT = "preflight_consult"
    CRITIQUE_CONSULT = "critique_consult"
    FAILURE_CONSULT = "failure_consult"


class ExecutionMode(str, Enum):
    """Modes for delegating work to an external target."""

    DELEGATE_EXECUTION = "delegate_execution"


CONSULTATION_MODES: frozenset[str] = frozenset(mode.value for mode in ConsultationMode)
EXECUTION_MODES: frozenset[str] = frozenset(mode.value for mode in ExecutionMode)

FALLBACK_TRIGGERS: frozenset[str] = frozenset(
    {
        "context_overflow",
        "generation_truncated",
        "provider_quota_or_token_exhausted",
        "low_confidence_or_repeated_failure",
    }
)

FALLBACK_ACTIONS_BY_TRIGGER: dict[str, frozenset[str]] = {
    "context_overflow": frozenset(
        {
            "compress_context",
            "split_task",
            "local_larger_context_or_deep",
            "external_large_context_consult",
            "ask_user",
        }
    ),
    "generation_truncated": frozenset(
        {
            "continue_same_target",
            "request_shorter_output",
            "split_output",
            "ask_user",
        }
    ),
    "provider_quota_or_token_exhausted": frozenset(
        {
            "next_external_agent",
            "local_deep_moe",
            "local_fast_reduced_scope",
            "ask_user",
        }
    ),
    "low_confidence_or_repeated_failure": frozenset(
        {
            "consult_role_advisor",
            "local_deep_moe",
            "external_execution_if_policy_allows",
            "ask_user",
        }
    ),
}


@dataclass(frozen=True)
class AgentTarget:
    """A local model/runtime or external provider target."""

    target_id: str
    kind: str
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "kind": self.kind,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentTarget:
        _require_fields(data, {"target_id", "kind", "enabled"})
        return cls(
            target_id=data["target_id"],
            kind=data["kind"],
            enabled=bool(data["enabled"]),
        )


@dataclass(frozen=True)
class ExternalAgentTarget:
    """Role-specific external provider target configuration."""

    target_id: str
    mode: str
    enabled: bool
    good_for: tuple[str, ...]
    brokered_tools: tuple[str, ...]
    kind: str = "external"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "kind": self.kind,
            "mode": self.mode,
            "enabled": self.enabled,
            "good_for": list(self.good_for),
            "brokered_tools": list(self.brokered_tools),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalAgentTarget:
        _require_fields(
            data,
            {"target_id", "mode", "enabled", "good_for", "brokered_tools"},
        )
        return cls(
            target_id=data["target_id"],
            mode=data["mode"],
            enabled=bool(data["enabled"]),
            good_for=tuple(data["good_for"]),
            brokered_tools=tuple(data["brokered_tools"]),
            kind=data.get("kind", "external"),
        )


@dataclass(frozen=True)
class FallbackChain:
    """Ordered fallback actions for a specific failure trigger."""

    trigger: str
    actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "actions": list(self.actions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FallbackChain:
        _require_fields(data, {"trigger", "actions"})
        return cls(trigger=data["trigger"], actions=tuple(data["actions"]))


@dataclass(frozen=True)
class EscalationPolicy:
    """Role-specific policy for consultation and external execution."""

    role: str
    advisors: tuple[str, ...]
    consultation_threshold: str
    external_execution: str
    fallback_execution: tuple[str, ...] | None = None
    external_execution_threshold: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "advisors": list(self.advisors),
            "consultation_threshold": self.consultation_threshold,
            "external_execution": self.external_execution,
        }
        if self.fallback_execution is not None:
            payload["fallback_execution"] = list(self.fallback_execution)
        if self.external_execution_threshold is not None:
            payload["external_execution_threshold"] = self.external_execution_threshold
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EscalationPolicy:
        _require_fields(
            data,
            {"role", "advisors", "consultation_threshold", "external_execution"},
        )
        return cls(
            role=data["role"],
            advisors=tuple(data["advisors"]),
            consultation_threshold=data["consultation_threshold"],
            external_execution=data["external_execution"],
            fallback_execution=(
                tuple(data["fallback_execution"])
                if "fallback_execution" in data
                else None
            ),
            external_execution_threshold=data.get("external_execution_threshold"),
        )


@dataclass(frozen=True)
class ExternalCostLedgerEntry:
    """Logged cost and outcome for one external-agent interaction."""

    timestamp: str
    role: str
    external_target: str
    mode: str
    reason: str
    fallback_chain_step: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    tool_round_trips: int
    brokered_tools_used: tuple[str, ...]
    helpfulness: str
    result: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "role": self.role,
            "external_target": self.external_target,
            "mode": self.mode,
            "reason": self.reason,
            "fallback_chain_step": self.fallback_chain_step,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "tool_round_trips": self.tool_round_trips,
            "brokered_tools_used": list(self.brokered_tools_used),
            "helpfulness": self.helpfulness,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalCostLedgerEntry:
        _require_fields(
            data,
            {
                "timestamp",
                "role",
                "external_target",
                "mode",
                "reason",
                "fallback_chain_step",
                "input_tokens",
                "output_tokens",
                "estimated_cost_usd",
                "tool_round_trips",
                "brokered_tools_used",
                "helpfulness",
                "result",
            },
        )
        return cls(
            timestamp=data["timestamp"],
            role=data["role"],
            external_target=data["external_target"],
            mode=data["mode"],
            reason=data["reason"],
            fallback_chain_step=int(data["fallback_chain_step"]),
            input_tokens=int(data["input_tokens"]),
            output_tokens=int(data["output_tokens"]),
            estimated_cost_usd=float(data["estimated_cost_usd"]),
            tool_round_trips=int(data["tool_round_trips"]),
            brokered_tools_used=tuple(data["brokered_tools_used"]),
            helpfulness=data["helpfulness"],
            result=data["result"],
        )


@dataclass(frozen=True)
class ExternalToolRequest:
    """Brokered tool request issued on behalf of an external agent."""

    target: str
    tool: str
    args: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "tool": self.tool,
            "args": self.args,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalToolRequest:
        _require_fields(data, {"target", "tool", "args"})
        return cls(target=data["target"], tool=data["tool"], args=dict(data["args"]))


@dataclass(frozen=True)
class ExternalToolResult:
    """Brokered tool result returned to an external agent."""

    target: str
    tool: str
    status: str
    output: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "tool": self.tool,
            "status": self.status,
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalToolResult:
        _require_fields(data, {"target", "tool", "status", "output"})
        return cls(
            target=data["target"],
            tool=data["tool"],
            status=data["status"],
            output=data["output"],
        )


def default_fallback_chains() -> dict[str, FallbackChain]:
    """Return the default fallback chains from PROJECT.md Milestone 11."""
    return {
        trigger: FallbackChain(trigger=trigger, actions=actions)
        for trigger, actions in (
            (
                "context_overflow",
                (
                    "compress_context",
                    "split_task",
                    "local_larger_context_or_deep",
                    "external_large_context_consult",
                    "ask_user",
                ),
            ),
            (
                "generation_truncated",
                (
                    "continue_same_target",
                    "request_shorter_output",
                    "split_output",
                    "ask_user",
                ),
            ),
            (
                "provider_quota_or_token_exhausted",
                (
                    "next_external_agent",
                    "local_deep_moe",
                    "local_fast_reduced_scope",
                    "ask_user",
                ),
            ),
            (
                "low_confidence_or_repeated_failure",
                (
                    "consult_role_advisor",
                    "local_deep_moe",
                    "external_execution_if_policy_allows",
                    "ask_user",
                ),
            ),
        )
    }
