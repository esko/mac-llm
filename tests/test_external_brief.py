"""Tests for external dry-run brief, brokered-only tools, redaction, and cost ledger."""

from __future__ import annotations

import json
import socket
from unittest.mock import patch

import pytest

from mac_llm.artifacts.schemas import ExternalConsultationBrief
from mac_llm.external.brief import (
    ExternalConsultationDryRun,
    ExternalBrokeredToolError,
    RenderedExternalConsultationBrief,
    assert_external_brokered_tool_allowed,
    render_dry_run_consultation_brief,
)
from mac_llm.external.config import get_external_target
from mac_llm.external.ledger import ExternalCostLedger
from mac_llm.external.policy import ExternalAgentsGate, ExternalPolicyError
from mac_llm.external.redaction import RedactionError, validate_context_refs
from mac_llm.external.schemas import ExternalCostLedgerEntry
from mac_llm.tools.schema import KNOWN_TOOLS


def test_render_dry_run_consultation_brief_without_network() -> None:
    with patch.object(socket, "create_connection", side_effect=AssertionError("network reached")):
        rendered = render_dry_run_consultation_brief(
            role="review",
            target_id="external_reviewer",
            mode="critique_consult",
            question="Is this API change safe?",
            context_refs=["src/api.py"],
        )

    assert isinstance(rendered, RenderedExternalConsultationBrief)
    assert rendered.brief.role == "review"
    assert rendered.brief.target == "external_reviewer"
    assert rendered.brief.mode == "critique_consult"
    assert rendered.brief.question == "Is this API change safe?"
    assert rendered.brief.context_refs == ["src/api.py"]
    assert rendered.policy_mode == "dry_run"
    assert "external_reviewer" in rendered.format_output()
    assert "critique_consult" in rendered.format_output()
    assert "Is this API change safe?" in rendered.format_output()


def test_rendered_brief_serializes_artifact() -> None:
    rendered = render_dry_run_consultation_brief(
        role="review",
        target_id="external_reviewer",
        mode="critique_consult",
        question="safe?",
    )
    payload = rendered.brief.to_dict()
    restored = ExternalConsultationBrief.from_dict(payload)
    assert restored.to_dict() == payload
    assert payload["artifact_type"] == "external_consultation_brief"


def test_brokered_tool_allowed_for_configured_target() -> None:
    target = get_external_target("external_reviewer")
    for tool in target.brokered_tools:
        assert_external_brokered_tool_allowed(target_id="external_reviewer", tool=tool)


@pytest.mark.parametrize(
    "tool",
    ["shell", "run_shell", "read_file", "write_file", "exec", "filesystem"],
)
def test_brokered_tool_rejects_raw_shell_and_filesystem(tool: str) -> None:
    with pytest.raises(ExternalBrokeredToolError, match="not brokered"):
        assert_external_brokered_tool_allowed(target_id="external_reviewer", tool=tool)


def test_brokered_tool_rejects_tool_not_on_target_allowlist() -> None:
    with pytest.raises(ExternalBrokeredToolError, match="not allowed for target"):
        assert_external_brokered_tool_allowed(
            target_id="external_reviewer",
            tool="propose_patch",
        )


def test_brokered_tool_rejects_unknown_broker_tool() -> None:
    with pytest.raises(ExternalBrokeredToolError, match="not brokered"):
        assert_external_brokered_tool_allowed(
            target_id="external_code_advisor",
            tool="totally_made_up",
        )


def test_all_target_brokered_tools_are_on_m10_allowlist() -> None:
    target = get_external_target("external_code_advisor")
    assert target.brokered_tools
    for tool in target.brokered_tools:
        assert tool in KNOWN_TOOLS


@pytest.mark.parametrize(
    "ref",
    [".env", "config/.env", ".ssh/id_rsa", ".gnupg/pubring.kbx", ".netrc", "secrets/id_rsa"],
)
def test_redaction_fails_closed_on_sensitive_paths(ref: str) -> None:
    with pytest.raises(RedactionError, match="sensitive"):
        validate_context_refs([ref])


@pytest.mark.parametrize("ref", [".", "./", "**", "**/*", "__FULL_REPO__", "repo://full_dump"])
def test_redaction_fails_closed_on_full_repo_dump_refs(ref: str) -> None:
    with pytest.raises(RedactionError, match="full.repo|full repo|repo dump"):
        validate_context_refs([ref])


def test_redaction_allows_safe_context_refs() -> None:
    refs = validate_context_refs(["src/api.py", "artifact:git_diff_summary"])
    assert refs == ("src/api.py", "artifact:git_diff_summary")


def test_render_brief_applies_redaction_before_construction() -> None:
    with pytest.raises(RedactionError, match="sensitive"):
        render_dry_run_consultation_brief(
            role="review",
            target_id="external_reviewer",
            mode="critique_consult",
            question="safe?",
            context_refs=[".env"],
        )


def test_cost_ledger_records_dry_run_entry() -> None:
    ledger = ExternalCostLedger()
    entry = ledger.record_dry_run(
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
        result="dry_run_rendered",
    )

    assert isinstance(entry, ExternalCostLedgerEntry)
    assert entry.result == "dry_run_rendered"
    assert entry.fallback_chain_step == 2
    assert entry.brokered_tools_used == ("git_diff", "read_file_range")
    assert len(ledger.entries) == 1
    assert ledger.entries[0] is entry


def test_cost_ledger_entry_round_trips_json() -> None:
    ledger = ExternalCostLedger()
    entry = ledger.record_dry_run(
        timestamp="2026-06-09T12:00:00Z",
        role="review",
        external_target="external_reviewer",
        mode="critique_consult",
        reason="dry run",
    )
    restored = ExternalCostLedgerEntry.from_dict(
        json.loads(json.dumps(entry.to_dict(), sort_keys=True))
    )
    assert restored.to_dict() == entry.to_dict()


def test_dry_run_service_render_and_ledger_without_network() -> None:
    service = ExternalConsultationDryRun()
    with patch.object(socket, "create_connection", side_effect=AssertionError("network reached")):
        rendered = service.render(
            role="review",
            target_id="external_reviewer",
            mode="critique_consult",
            question="safe?",
            reason="policy check",
        )
        entry = service.last_ledger_entry()

    assert rendered.brief.question == "safe?"
    assert entry is not None
    assert entry.external_target == "external_reviewer"
    assert entry.mode == "critique_consult"
    assert entry.result == "dry_run_rendered"


def test_dry_run_service_send_blocked_without_network() -> None:
    service = ExternalConsultationDryRun()
    rendered = service.render(
        role="review",
        target_id="external_reviewer",
        mode="critique_consult",
        question="safe?",
        reason="policy check",
    )
    with patch.object(socket, "create_connection", side_effect=AssertionError("network reached")):
        with pytest.raises(ExternalPolicyError, match="blocked"):
            service.send(rendered)


def test_default_gate_still_blocks_live_consultation_without_network() -> None:
    gate = ExternalAgentsGate()
    with patch.object(socket, "create_connection", side_effect=AssertionError("network reached")):
        with pytest.raises(ExternalPolicyError, match="blocked"):
            gate.request_consultation(
                target_id="external_reviewer",
                mode="critique_consult",
                role="review",
                question="safe?",
            )


def test_unknown_consultation_mode_fails_on_render() -> None:
    with pytest.raises(ExternalPolicyError, match="unknown consultation mode"):
        render_dry_run_consultation_brief(
            role="review",
            target_id="external_reviewer",
            mode="mystery_consult",
            question="safe?",
        )
