"""Dry-run external consultation brief rendering and brokered-tool enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from mac_llm.artifacts.schemas import ExternalConsultationBrief
from mac_llm.external.config import get_external_target
from mac_llm.external.ledger import ExternalCostLedger
from mac_llm.external.policy import ExternalAgentsGate, ExternalPolicyError
from mac_llm.external.redaction import validate_context_refs
from mac_llm.external.schemas import ExternalCostLedgerEntry
from mac_llm.tools.schema import KNOWN_TOOLS


class ExternalBrokeredToolError(ExternalPolicyError):
    """Raised when an external agent requests a disallowed tool."""


@dataclass(frozen=True)
class RenderedExternalConsultationBrief:
    """Pure dry-run render result for an external consultation brief."""

    brief: ExternalConsultationBrief
    brokered_tools: tuple[str, ...]
    policy_mode: str = "dry_run"

    def format_output(self) -> str:
        lines = [
            f"policy_mode: {self.policy_mode}",
            f"role: {self.brief.role}",
            f"target: {self.brief.target}",
            f"mode: {self.brief.mode}",
            f"question: {self.brief.question}",
            f"brokered_tools: {', '.join(self.brokered_tools)}",
        ]
        if self.brief.context_refs:
            lines.append(f"context_refs: {', '.join(self.brief.context_refs)}")
        return "\n".join(lines) + "\n"


def assert_external_brokered_tool_allowed(*, target_id: str, tool: str) -> None:
    """Fail closed unless the tool is brokered for the target and on the M10 allowlist."""
    if tool not in KNOWN_TOOLS:
        raise ExternalBrokeredToolError(f"not brokered: raw or unknown tool {tool!r}")

    target = get_external_target(target_id)
    if tool not in target.brokered_tools:
        raise ExternalBrokeredToolError(
            f"tool {tool!r} not allowed for target {target_id!r}"
        )


def render_dry_run_consultation_brief(
    *,
    role: str,
    target_id: str,
    mode: str,
    question: str,
    context_refs: list[str] | None = None,
    gate: ExternalAgentsGate | None = None,
) -> RenderedExternalConsultationBrief:
    """Construct a consultation brief for inspection with no network I/O."""
    active_gate = gate if gate is not None else ExternalAgentsGate()
    active_gate.validate_consultation_shape(target_id=target_id, mode=mode)

    target = get_external_target(target_id)
    safe_refs = list(validate_context_refs(context_refs))
    brief = ExternalConsultationBrief(
        role=role,
        target=target_id,
        mode=mode,
        question=question,
        context_refs=safe_refs or None,
    )
    return RenderedExternalConsultationBrief(
        brief=brief,
        brokered_tools=target.brokered_tools,
        policy_mode="dry_run",
    )


@dataclass
class ExternalConsultationDryRun:
    """Render-only external consultation path with ledger recording."""

    gate: ExternalAgentsGate | None = None
    ledger: ExternalCostLedger | None = None

    def __post_init__(self) -> None:
        if self.gate is None:
            self.gate = ExternalAgentsGate()
        if self.ledger is None:
            self.ledger = ExternalCostLedger()

    def render(
        self,
        *,
        role: str,
        target_id: str,
        mode: str,
        question: str,
        reason: str,
        context_refs: list[str] | None = None,
        timestamp: str = "1970-01-01T00:00:00Z",
        fallback_chain_step: int = 0,
    ) -> RenderedExternalConsultationBrief:
        rendered = render_dry_run_consultation_brief(
            role=role,
            target_id=target_id,
            mode=mode,
            question=question,
            context_refs=context_refs,
            gate=self.gate,
        )
        self.ledger.record_dry_run(
            timestamp=timestamp,
            role=role,
            external_target=target_id,
            mode=mode,
            reason=reason,
            fallback_chain_step=fallback_chain_step,
            brokered_tools_used=rendered.brokered_tools,
        )
        return rendered

    def send(self, rendered: RenderedExternalConsultationBrief) -> Never:
        """Fail-closed send path; no network I/O under default policy."""
        brief = rendered.brief
        return self.gate.request_consultation(
            target_id=brief.target,
            mode=brief.mode,
            role=brief.role,
            question=brief.question,
        )

    def last_ledger_entry(self) -> ExternalCostLedgerEntry | None:
        if not self.ledger.entries:
            return None
        return self.ledger.entries[-1]
