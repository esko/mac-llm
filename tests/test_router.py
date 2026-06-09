"""Tests for simple router — RouteDecision schema, heuristic dry-run, fail-closed."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from mac_llm.external.config import list_external_target_ids
from mac_llm.external.ledger import ExternalCostLedger
from mac_llm.external.policy import ExternalAgentsGate, ExternalAgentsPolicy
from mac_llm.roles.config import KNOWN_ROLES
from mac_llm.router.decision import (
    RouteDecision,
    RouteDecisionValidationError,
    parse_route_decision,
    validate_route_decision,
)
from mac_llm.router.router import (
    DeepTargetPolicy,
    HeuristicRouter,
    RouteDecisionLog,
    RoutePolicyError,
)
from mac_llm.runtime.target import list_target_ids
from mac_llm.tools.schema import KNOWN_TOOLS


def _minimal_decision_payload(**overrides: object) -> dict:
    payload = {
        "role": "review",
        "task_difficulty": "medium",
        "execution_target": "local_fast",
        "requires_swap": False,
        "cache_strategy": "role_prefix",
        "structured_artifacts": ["UserTaskSummary"],
        "consultation": {
            "target": None,
            "mode": None,
            "required": False,
        },
        "fallback_chain": ["local_fast", "ask_user"],
        "token_strategy": "compress_then_split_then_escalate",
        "tool_strategy": {
            "tool_operator_allowed": True,
            "brokered_tools_allowed": True,
        },
        "confidence": 0.7,
        "rationale": "test decision",
    }
    payload.update(overrides)
    return payload


def test_validate_route_decision_accepts_minimal_payload() -> None:
    decision = validate_route_decision(_minimal_decision_payload())

    assert decision.role == "review"
    assert decision.execution_target == "local_fast"
    assert decision.cache_strategy == "role_prefix"
    assert decision.structured_artifacts == ("UserTaskSummary",)
    assert decision.consultation.target is None
    assert decision.tool_strategy.tool_operator_allowed is True


def test_route_decision_round_trip_json() -> None:
    payload = _minimal_decision_payload(
        execution_target="local_deep_moe",
        requires_swap=True,
        structured_artifacts=["UserTaskSummary", "GitDiffSummary"],
        fallback_chain=["local_fast", "local_deep_moe", "external_reviewer", "ask_user"],
        consultation={
            "target": "external_reviewer",
            "mode": "critique_consult",
            "required": False,
        },
        tool_strategy={
            "tool_operator_allowed": True,
            "brokered_tools_allowed": True,
            "tools": ["git_diff", "read_file_range"],
        },
    )
    decision = validate_route_decision(payload)
    restored = validate_route_decision(decision.to_dict())
    assert restored == decision


def test_parse_route_decision_invalid_json_fails_closed() -> None:
    with pytest.raises(RouteDecisionValidationError, match="invalid JSON"):
        parse_route_decision("{not json")


def test_validate_route_decision_unknown_role_fails_closed() -> None:
    payload = _minimal_decision_payload(role="mystery_role")
    with pytest.raises(RouteDecisionValidationError, match="unknown role"):
        validate_route_decision(payload)


def test_validate_route_decision_unknown_execution_target_fails_closed() -> None:
    payload = _minimal_decision_payload(execution_target="no_such_target")
    with pytest.raises(RouteDecisionValidationError, match="unknown target"):
        validate_route_decision(payload)


def test_validate_route_decision_unknown_fallback_target_fails_closed() -> None:
    payload = _minimal_decision_payload(
        fallback_chain=["local_fast", "imaginary_target", "ask_user"]
    )
    with pytest.raises(RouteDecisionValidationError, match="unknown target"):
        validate_route_decision(payload)


def test_validate_route_decision_unknown_consultation_target_fails_closed() -> None:
    payload = _minimal_decision_payload(
        consultation={
            "target": "external_nope",
            "mode": "critique_consult",
            "required": False,
        }
    )
    with pytest.raises(RouteDecisionValidationError, match="unknown target"):
        validate_route_decision(payload)


def test_validate_route_decision_unknown_tool_fails_closed() -> None:
    payload = _minimal_decision_payload(
        tool_strategy={
            "tool_operator_allowed": True,
            "brokered_tools_allowed": True,
            "tools": ["git_diff", "made_up_tool"],
        }
    )
    with pytest.raises(RouteDecisionValidationError, match="unknown tool"):
        validate_route_decision(payload)


def test_validate_route_decision_unknown_structured_artifact_fails_closed() -> None:
    payload = _minimal_decision_payload(structured_artifacts=["UserTaskSummary", "FakeArtifact"])
    with pytest.raises(RouteDecisionValidationError, match="unknown structured artifact"):
        validate_route_decision(payload)


def test_validate_route_decision_missing_required_field_fails_closed() -> None:
    payload = _minimal_decision_payload()
    del payload["rationale"]
    with pytest.raises(RouteDecisionValidationError, match="missing required field"):
        validate_route_decision(payload)


def test_deep_target_requires_policy() -> None:
    decision = validate_route_decision(
        _minimal_decision_payload(execution_target="local_deep_moe")
    )
    router = HeuristicRouter(deep_policy=DeepTargetPolicy(deep_target_allowed=False))

    with pytest.raises(RoutePolicyError, match="deep target requires policy"):
        router.assert_policy_allows(decision)


def test_deep_target_allowed_when_policy_permits() -> None:
    decision = validate_route_decision(
        _minimal_decision_payload(execution_target="local_deep_moe")
    )
    router = HeuristicRouter(deep_policy=DeepTargetPolicy(deep_target_allowed=True))
    router.assert_policy_allows(decision)


def test_external_consultation_blocked_unless_policy_enabled() -> None:
    decision = validate_route_decision(
        _minimal_decision_payload(
            consultation={
                "target": "external_reviewer",
                "mode": "critique_consult",
                "required": False,
            }
        )
    )
    router = HeuristicRouter()

    with pytest.raises(RoutePolicyError, match="external consultation blocked"):
        router.assert_policy_allows(decision)


def test_external_consultation_allowed_when_policy_enabled() -> None:
    from dataclasses import replace

    from mac_llm.external.config import DEFAULT_EXTERNAL_TARGETS

    enabled_targets = {
        target_id: replace(target, enabled=True)
        for target_id, target in DEFAULT_EXTERNAL_TARGETS.items()
    }
    enabled_policy = ExternalAgentsPolicy(enabled=True, require_approval=False)
    gate = ExternalAgentsGate(
        policy=enabled_policy,
        targets=enabled_targets,
    )
    decision = validate_route_decision(
        _minimal_decision_payload(
            consultation={
                "target": "external_reviewer",
                "mode": "critique_consult",
                "required": False,
            }
        )
    )
    router = HeuristicRouter(external_gate=gate)
    router.assert_policy_allows(decision)


def test_heuristic_review_medium_selects_deep_target() -> None:
    router = HeuristicRouter(deep_policy=DeepTargetPolicy(deep_target_allowed=True))
    decision = router.decide("review", difficulty="medium")

    assert decision.role == "review"
    assert decision.task_difficulty == "medium"
    assert decision.execution_target == "local_deep_moe"
    assert decision.cache_strategy == "role_prefix"
    assert "GitDiffSummary" in decision.structured_artifacts


def test_heuristic_coding_medium_stays_on_local_fast() -> None:
    router = HeuristicRouter()
    decision = router.decide("coding", difficulty="medium")

    assert decision.execution_target == "local_fast"
    assert decision.task_difficulty == "medium"


def test_heuristic_unknown_role_fails_closed() -> None:
    router = HeuristicRouter()
    with pytest.raises(RouteDecisionValidationError, match="unknown role"):
        router.decide("not_a_role", difficulty="low")


def test_dry_run_logs_decision_without_acting() -> None:
    log = RouteDecisionLog()
    router = HeuristicRouter(log=log, deep_policy=DeepTargetPolicy(deep_target_allowed=True))

    with patch.object(socket, "create_connection", side_effect=AssertionError("network reached")):
        decision = router.dry_run("planning", difficulty="medium", timestamp="2026-06-09T12:00:00Z")

    assert decision.role == "planning"
    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.role == "planning"
    assert entry.execution_target == decision.execution_target
    assert entry.dry_run is True


def test_dry_run_records_ledger_when_consultation_indicated() -> None:
    ledger = ExternalCostLedger()
    router = HeuristicRouter(
        ledger=ledger,
        deep_policy=DeepTargetPolicy(deep_target_allowed=True),
    )

    with patch.object(socket, "create_connection", side_effect=AssertionError("network reached")):
        decision = router.dry_run(
            "review",
            difficulty="high",
            timestamp="2026-06-09T12:00:00Z",
        )

    assert decision.consultation.target is not None
    assert len(ledger.entries) == 1
    entry = ledger.entries[0]
    assert entry.role == "review"
    assert entry.external_target == decision.consultation.target
    assert entry.result == "dry_run_rendered"


def test_dry_run_does_not_record_ledger_without_consultation() -> None:
    ledger = ExternalCostLedger()
    router = HeuristicRouter(ledger=ledger)

    router.dry_run("summarization", difficulty="low", timestamp="2026-06-09T12:00:00Z")

    assert ledger.entries == []


def test_heuristic_respects_active_target_for_requires_swap() -> None:
    router = HeuristicRouter(deep_policy=DeepTargetPolicy(deep_target_allowed=True))
    decision = router.decide("review", difficulty="medium", active_target_id="local_fast")

    assert decision.execution_target == "local_deep_moe"
    assert decision.requires_swap is True

    same_target = router.decide(
        "review",
        difficulty="medium",
        active_target_id="local_deep_moe",
    )
    assert same_target.requires_swap is False


@pytest.mark.parametrize("role", sorted(KNOWN_ROLES))
def test_heuristic_produces_valid_decision_for_all_roles(role: str) -> None:
    router = HeuristicRouter(deep_policy=DeepTargetPolicy(deep_target_allowed=True))
    decision = router.decide(role, difficulty="low")
    assert decision.role == role
    validate_route_decision(decision.to_dict())


def test_fallback_chain_entries_are_known_targets() -> None:
    router = HeuristicRouter(deep_policy=DeepTargetPolicy(deep_target_allowed=True))
    decision = router.decide("debugging", difficulty="high")
    known = set(list_target_ids()) | set(list_external_target_ids()) | {"ask_user"}
    for entry in decision.fallback_chain:
        assert entry in known
