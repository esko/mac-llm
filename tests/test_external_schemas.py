"""Tests for external-target schemas, disabled config, and fail-closed policy."""

from __future__ import annotations

import json
import socket
from unittest.mock import patch

import pytest

from mac_llm.artifacts.schemas import ExternalConsultationBrief, ExternalConsultationOpinion
from mac_llm.external.config import (
    DEFAULT_EXTERNAL_TARGETS,
    UnknownExternalTargetError,
    get_external_target,
    list_external_target_ids,
)
from mac_llm.external.policy import (
    DEFAULT_EXTERNAL_AGENTS_POLICY,
    ExternalAgentsGate,
    ExternalPolicyError,
    validate_fallback_chain,
)
from mac_llm.external.schemas import (
    CONSULTATION_MODES,
    EXECUTION_MODES,
    AgentTarget,
    EscalationPolicy,
    ExecutionMode,
    ExternalAgentTarget,
    ExternalCostLedgerEntry,
    ExternalToolRequest,
    ExternalToolResult,
    FallbackChain,
    ConsultationMode,
    default_fallback_chains,
)


def _round_trip(artifact: object) -> dict:
    data = artifact.to_dict()  # type: ignore[attr-defined]
    serialized = json.dumps(data, sort_keys=True)
    restored = type(artifact).from_dict(json.loads(serialized))  # type: ignore[attr-defined]
    return restored.to_dict()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "artifact",
    [
        AgentTarget(target_id="local_fast", kind="local", enabled=True),
        ExternalAgentTarget(
            target_id="external_reviewer",
            mode="consultation",
            enabled=False,
            good_for=("review", "safety_review"),
            brokered_tools=("git_diff", "read_file_range"),
        ),
        FallbackChain(
            trigger="context_overflow",
            actions=("compress_context", "split_task", "ask_user"),
        ),
        EscalationPolicy(
            role="review",
            advisors=("external_reviewer", "external_architect"),
            consultation_threshold="medium",
            external_execution="disabled",
        ),
        ExternalCostLedgerEntry(
            timestamp="2026-06-09T12:00:00Z",
            role="review",
            external_target="external_reviewer",
            mode="critique_consult",
            reason="large diff",
            fallback_chain_step=2,
            input_tokens=4200,
            output_tokens=900,
            estimated_cost_usd=0.0,
            tool_round_trips=1,
            brokered_tools_used=("git_diff", "read_file_range"),
            helpfulness="unknown",
            result="completed",
        ),
        ExternalToolRequest(
            target="external_reviewer",
            tool="git_diff",
            args={"paths": ["src/a.py"]},
        ),
        ExternalToolResult(
            target="external_reviewer",
            tool="git_diff",
            status="ok",
            output="diff summary",
        ),
        ExternalConsultationBrief(
            role="review",
            target="external_reviewer",
            mode="critique_consult",
            question="Is this API change safe?",
        ),
        ExternalConsultationOpinion(
            target="external_reviewer",
            mode="critique_consult",
            opinion="Looks safe with minor notes",
        ),
    ],
)
def test_serialization_round_trip(artifact: object) -> None:
    assert _round_trip(artifact) == artifact.to_dict()  # type: ignore[attr-defined]


def test_consultation_and_execution_modes_are_distinct() -> None:
    assert CONSULTATION_MODES.isdisjoint(EXECUTION_MODES)
    assert ConsultationMode.PREFLIGHT_CONSULT.value in CONSULTATION_MODES
    assert ConsultationMode.CRITIQUE_CONSULT.value in CONSULTATION_MODES
    assert ConsultationMode.FAILURE_CONSULT.value in CONSULTATION_MODES
    assert ExecutionMode.DELEGATE_EXECUTION.value in EXECUTION_MODES


def test_initial_external_targets_are_disabled() -> None:
    expected = (
        "external_architect",
        "external_reviewer",
        "external_code_advisor",
        "external_coding_agent",
        "external_frontier_generalist",
    )
    assert list_external_target_ids() == expected
    for target_id in expected:
        target = get_external_target(target_id)
        assert target.enabled is False
        assert target.kind == "external"


def test_default_external_agents_policy_matches_project_md() -> None:
    policy = DEFAULT_EXTERNAL_AGENTS_POLICY
    assert policy.enabled is False
    assert policy.require_approval is True
    assert policy.can_write_files is False
    assert policy.can_run_tools_directly is False
    assert policy.can_request_brokered_tools is True
    assert policy.returns_final_answer is False
    assert policy.allow_private_repo_context is False
    assert policy.log_every_call is True
    assert policy.max_brief_tokens == 6000
    assert policy.max_tool_round_trips == 3
    assert policy.max_files_read == 5
    assert policy.max_total_tool_result_tokens == 12000


def test_unknown_external_target_fails_closed() -> None:
    with pytest.raises(UnknownExternalTargetError, match="unknown external target"):
        get_external_target("external_typo")


@pytest.fixture
def gate() -> ExternalAgentsGate:
    return ExternalAgentsGate()


def test_default_policy_blocks_consultation_without_network(gate: ExternalAgentsGate) -> None:
    with patch.object(socket, "create_connection", side_effect=AssertionError("network reached")):
        with pytest.raises(ExternalPolicyError, match="blocked"):
            gate.request_consultation(
                target_id="external_reviewer",
                mode="critique_consult",
                role="review",
                question="safe?",
            )


def test_default_policy_blocks_execution_without_network(gate: ExternalAgentsGate) -> None:
    with patch.object(socket, "create_connection", side_effect=AssertionError("network reached")):
        with pytest.raises(ExternalPolicyError, match="blocked"):
            gate.request_execution(
                target_id="external_coding_agent",
                mode="delegate_execution",
                role="coding",
                task="implement feature",
            )


def test_unknown_consultation_mode_fails_closed(gate: ExternalAgentsGate) -> None:
    with pytest.raises(ExternalPolicyError, match="unknown consultation mode"):
        gate.assert_consultation_allowed(
            target_id="external_reviewer",
            mode="mystery_consult",
        )


def test_unknown_execution_mode_fails_closed(gate: ExternalAgentsGate) -> None:
    with pytest.raises(ExternalPolicyError, match="unknown execution mode"):
        gate.assert_execution_allowed(
            target_id="external_coding_agent",
            mode="mystery_execution",
        )


def test_consultation_target_rejects_execution_mode(gate: ExternalAgentsGate) -> None:
    with pytest.raises(ExternalPolicyError, match="consultation target"):
        gate.assert_execution_allowed(
            target_id="external_reviewer",
            mode="delegate_execution",
        )


def test_execution_target_rejects_consultation_mode(gate: ExternalAgentsGate) -> None:
    with pytest.raises(ExternalPolicyError, match="execution target"):
        gate.assert_consultation_allowed(
            target_id="external_coding_agent",
            mode="critique_consult",
        )


@pytest.mark.parametrize(
    "trigger",
    [
        "context_overflow",
        "generation_truncated",
        "provider_quota_or_token_exhausted",
        "low_confidence_or_repeated_failure",
    ],
)
def test_default_fallback_chains_validate(trigger: str) -> None:
    chains = default_fallback_chains()
    chain = chains[trigger]
    validate_fallback_chain(chain)


def test_unknown_fallback_action_fails_closed() -> None:
    chain = FallbackChain(trigger="context_overflow", actions=("compress_context", "teleport_away"))
    with pytest.raises(ValueError, match="unknown fallback action"):
        validate_fallback_chain(chain)


def test_unknown_fallback_trigger_fails_closed() -> None:
    chain = FallbackChain(trigger="alien_signal", actions=("ask_user",))
    with pytest.raises(ValueError, match="unknown fallback trigger"):
        validate_fallback_chain(chain)


def test_configured_targets_match_defaults() -> None:
    assert set(DEFAULT_EXTERNAL_TARGETS) == set(list_external_target_ids())
