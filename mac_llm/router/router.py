"""Deterministic heuristic router with dry-run logging and policy gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mac_llm.external.config import DEFAULT_EXTERNAL_TARGETS, get_external_target
from mac_llm.external.ledger import ExternalCostLedger
from mac_llm.external.policy import (
    ExternalAgentsGate,
    ExternalPolicyError,
)
from mac_llm.external.schemas import EXECUTION_MODES
from mac_llm.roles.config import KNOWN_ROLES
from mac_llm.roles.select import UnknownRoleError, select_target
from mac_llm.router.decision import (
    ConsultationSpec,
    RouteDecision,
    RouteDecisionValidationError,
    ToolStrategy,
    validate_route_decision,
)
from mac_llm.runtime.target import list_target_ids


class RoutePolicyError(ValueError):
    """Raised when policy blocks a route decision."""


@dataclass(frozen=True)
class DeepTargetPolicy:
    """Policy gate for selecting the local deep runtime target."""

    deep_target_allowed: bool = False


@dataclass(frozen=True)
class RouteDecisionLogEntry:
    """Structured log entry for one route decision."""

    role: str
    task_difficulty: str
    execution_target: str
    requires_swap: bool
    cache_strategy: str
    confidence: float
    dry_run: bool
    consultation_target: str | None
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "task_difficulty": self.task_difficulty,
            "execution_target": self.execution_target,
            "requires_swap": self.requires_swap,
            "cache_strategy": self.cache_strategy,
            "confidence": self.confidence,
            "dry_run": self.dry_run,
            "consultation_target": self.consultation_target,
            "rationale": self.rationale,
        }


@dataclass
class RouteDecisionLog:
    """Append-only in-memory log of route decisions."""

    entries: list[RouteDecisionLogEntry] = field(default_factory=list)

    def record(self, decision: RouteDecision, *, dry_run: bool) -> RouteDecisionLogEntry:
        entry = RouteDecisionLogEntry(
            role=decision.role,
            task_difficulty=decision.task_difficulty,
            execution_target=decision.execution_target,
            requires_swap=decision.requires_swap,
            cache_strategy=decision.cache_strategy,
            confidence=decision.confidence,
            dry_run=dry_run,
            consultation_target=decision.consultation.target,
            rationale=decision.rationale,
        )
        self.entries.append(entry)
        return entry


_ROLE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "coding": ("UserTaskSummary", "StackTraceSummary"),
    "planning": ("UserTaskSummary", "RepoStateSummary"),
    "review": ("UserTaskSummary", "GitDiffSummary"),
    "debugging": ("UserTaskSummary", "StackTraceSummary", "TestFailureSummary"),
    "summarization": ("UserTaskSummary",),
    "tool_operator": ("UserTaskSummary", "ToolResultSummary"),
}

_ROLE_CONSULTATION: dict[str, tuple[str, str]] = {
    "planning": ("external_architect", "preflight_consult"),
    "review": ("external_reviewer", "critique_consult"),
    "debugging": ("external_code_advisor", "failure_consult"),
}


def _default_fallback_chain(execution_target: str) -> tuple[str, ...]:
    chain: list[str] = ["local_fast"]
    if execution_target != "local_fast" and "local_fast" not in chain:
        chain.append("local_fast")
    if execution_target == "local_deep_moe":
        chain.append("local_deep_moe")
    elif execution_target not in chain:
        chain.append(execution_target)
    chain.extend(
        target_id
        for target_id in ("external_reviewer", "external_architect")
        if target_id not in chain
    )
    chain.append("ask_user")
    return tuple(chain)


def _consultation_for_role(role: str, *, difficulty: str) -> ConsultationSpec:
    if difficulty not in {"medium", "high", "very_high"}:
        return ConsultationSpec(target=None, mode=None, required=False)
    if role not in _ROLE_CONSULTATION:
        return ConsultationSpec(target=None, mode=None, required=False)
    target, mode = _ROLE_CONSULTATION[role]
    return ConsultationSpec(target=target, mode=mode, required=False)


class HeuristicRouter:
    """Deterministic role/difficulty router with dry-run and policy gates."""

    def __init__(
        self,
        *,
        deep_policy: DeepTargetPolicy | None = None,
        external_gate: ExternalAgentsGate | None = None,
        ledger: ExternalCostLedger | None = None,
        log: RouteDecisionLog | None = None,
    ) -> None:
        self.deep_policy = (
            deep_policy if deep_policy is not None else DeepTargetPolicy()
        )
        self.external_gate = (
            external_gate if external_gate is not None else ExternalAgentsGate()
        )
        self.ledger = ledger if ledger is not None else ExternalCostLedger()
        self.log = log if log is not None else RouteDecisionLog()

    def decide(
        self,
        role: str,
        *,
        difficulty: str = "medium",
        active_target_id: str | None = None,
    ) -> RouteDecision:
        """Map role and difficulty to a validated route decision without model I/O."""
        if role not in KNOWN_ROLES:
            raise RouteDecisionValidationError(f"unknown role: {role}")

        try:
            selection = select_target(role, difficulty=difficulty)
        except UnknownRoleError as exc:
            raise RouteDecisionValidationError(str(exc)) from exc

        execution_target = selection.target_id
        consultation = _consultation_for_role(role, difficulty=difficulty)
        requires_swap = (
            active_target_id is not None and active_target_id != execution_target
        )

        decision = RouteDecision(
            role=role,
            task_difficulty=difficulty,
            execution_target=execution_target,
            requires_swap=requires_swap,
            cache_strategy=selection.cache_strategy,
            structured_artifacts=_ROLE_ARTIFACTS.get(role, ("UserTaskSummary",)),
            consultation=consultation,
            fallback_chain=_default_fallback_chain(execution_target),
            token_strategy="compress_then_split_then_escalate",
            tool_strategy=ToolStrategy(
                tool_operator_allowed=role == "tool_operator",
                brokered_tools_allowed=consultation.target is not None,
            ),
            confidence=0.65,
            rationale=(
                "Heuristic route from role-target mapping; not model-driven. "
                "Policy layer has final authority."
            ),
        )
        return validate_route_decision(decision.to_dict())

    def dry_run(
        self,
        role: str,
        *,
        difficulty: str = "medium",
        active_target_id: str | None = None,
        timestamp: str = "1970-01-01T00:00:00Z",
    ) -> RouteDecision:
        """Produce and log a route decision without executing swaps or external calls."""
        decision = self.decide(
            role,
            difficulty=difficulty,
            active_target_id=active_target_id,
        )
        self.log.record(decision, dry_run=True)
        if decision.consultation.target is not None:
            self._record_consultation_ledger(decision, timestamp=timestamp)
        return decision

    def assert_policy_allows(self, decision: RouteDecision) -> None:
        """Apply policy as the final gate over a route decision."""
        if decision.execution_target == "local_deep_moe":
            if not self.deep_policy.deep_target_allowed:
                raise RoutePolicyError("deep target requires policy approval")

        consultation = decision.consultation
        if consultation.target is None:
            return

        try:
            if consultation.mode in EXECUTION_MODES:
                self.external_gate.assert_execution_allowed(
                    target_id=consultation.target,
                    mode=consultation.mode,
                )
            else:
                self.external_gate.assert_consultation_allowed(
                    target_id=consultation.target,
                    mode=consultation.mode or "",
                )
        except ExternalPolicyError as exc:
            raise RoutePolicyError(
                f"external consultation blocked: {exc}"
            ) from exc

    def parse_and_validate(self, text: str) -> RouteDecision:
        """Parse strict JSON and validate a route decision."""
        from mac_llm.router.decision import parse_route_decision

        return parse_route_decision(text)

    def _record_consultation_ledger(
        self,
        decision: RouteDecision,
        *,
        timestamp: str,
    ) -> None:
        consultation = decision.consultation
        if consultation.target is None or consultation.mode is None:
            return
        target = get_external_target(consultation.target)
        self.ledger.record_dry_run(
            timestamp=timestamp,
            role=decision.role,
            external_target=consultation.target,
            mode=consultation.mode,
            reason=decision.rationale,
            brokered_tools_used=target.brokered_tools,
        )
