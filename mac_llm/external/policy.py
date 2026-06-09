"""Fail-closed external-agents policy and request gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from mac_llm.external.config import (
    DEFAULT_EXTERNAL_TARGETS,
    UnknownExternalTargetError,
    get_external_target,
)
from mac_llm.external.schemas import (
    CONSULTATION_MODES,
    EXECUTION_MODES,
    FALLBACK_ACTIONS_BY_TRIGGER,
    FALLBACK_TRIGGERS,
    FallbackChain,
)


class ExternalPolicyError(ValueError):
    """Raised when an external request is blocked or invalid."""


@dataclass(frozen=True)
class ExternalAgentsPolicy:
    """Global policy for external consultation and execution."""

    enabled: bool = False
    require_approval: bool = True
    can_write_files: bool = False
    can_run_tools_directly: bool = False
    can_request_brokered_tools: bool = True
    returns_final_answer: bool = False
    allow_private_repo_context: bool = False
    log_every_call: bool = True
    max_brief_tokens: int = 6000
    max_tool_round_trips: int = 3
    max_files_read: int = 5
    max_total_tool_result_tokens: int = 12000


DEFAULT_EXTERNAL_AGENTS_POLICY = ExternalAgentsPolicy()


def validate_fallback_chain(chain: FallbackChain) -> None:
    """Validate a fallback chain trigger and actions, failing closed on unknowns."""
    if chain.trigger not in FALLBACK_TRIGGERS:
        raise ValueError(f"unknown fallback trigger: {chain.trigger}")

    allowed = FALLBACK_ACTIONS_BY_TRIGGER[chain.trigger]
    for action in chain.actions:
        if action not in allowed:
            raise ValueError(f"unknown fallback action for {chain.trigger}: {action}")


class ExternalAgentsGate:
    """Policy gate that blocks external send/execute without network I/O."""

    def __init__(
        self,
        *,
        policy: ExternalAgentsPolicy | None = None,
        targets: dict[str, object] | None = None,
    ) -> None:
        self.policy = policy if policy is not None else DEFAULT_EXTERNAL_AGENTS_POLICY
        self._targets = targets if targets is not None else DEFAULT_EXTERNAL_TARGETS

    def assert_consultation_allowed(self, *, target_id: str, mode: str) -> None:
        """Raise if consultation would be blocked."""
        if mode not in CONSULTATION_MODES:
            raise ExternalPolicyError(f"unknown consultation mode: {mode}")

        target = self._resolve_target(target_id)
        if target.mode != "consultation":
            raise ExternalPolicyError(
                f"execution target does not accept consultation: {target_id}"
            )

        self._assert_policy_allows(target_id=target_id, interaction="consultation")

    def assert_execution_allowed(self, *, target_id: str, mode: str) -> None:
        """Raise if execution would be blocked."""
        if mode not in EXECUTION_MODES:
            raise ExternalPolicyError(f"unknown execution mode: {mode}")

        target = self._resolve_target(target_id)
        if target.mode != "execution":
            raise ExternalPolicyError(
                f"consultation target does not accept execution: {target_id}"
            )

        self._assert_policy_allows(target_id=target_id, interaction="execution")

    def request_consultation(
        self,
        *,
        target_id: str,
        mode: str,
        role: str,
        question: str,
    ) -> Never:
        """Fail-closed consultation entry point; no network I/O under default policy."""
        self.assert_consultation_allowed(target_id=target_id, mode=mode)
        raise ExternalPolicyError(
            f"external consultation blocked by policy for target {target_id!r} "
            f"(role={role!r})"
        )

    def request_execution(
        self,
        *,
        target_id: str,
        mode: str,
        role: str,
        task: str,
    ) -> Never:
        """Fail-closed execution entry point; no network I/O under default policy."""
        self.assert_execution_allowed(target_id=target_id, mode=mode)
        raise ExternalPolicyError(
            f"external execution blocked by policy for target {target_id!r} "
            f"(role={role!r})"
        )

    def _resolve_target(self, target_id: str):
        if target_id not in self._targets:
            raise UnknownExternalTargetError(f"unknown external target: {target_id}")
        return self._targets[target_id]

    def _assert_policy_allows(self, *, target_id: str, interaction: str) -> None:
        target = self._resolve_target(target_id)

        if not self.policy.enabled:
            raise ExternalPolicyError(
                f"external {interaction} blocked: external_agents.enabled is false"
            )

        if not target.enabled:
            raise ExternalPolicyError(
                f"external {interaction} blocked: target {target_id!r} is disabled"
            )

        if self.policy.require_approval:
            raise ExternalPolicyError(
                f"external {interaction} blocked: approval required"
            )
