"""Tests for role-target config validation and select_target."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from mac_llm.roles.config import (
    DEFAULT_ROLE_TARGETS,
    KNOWN_ROLES,
    RoleTargetMapping,
    validate_role_targets,
)
from mac_llm.roles.select import UnknownRoleError, select_target
from mac_llm.runtime.target import UnknownTargetError


def test_default_role_targets_match_project_mapping() -> None:
    assert set(DEFAULT_ROLE_TARGETS) == KNOWN_ROLES

    coding = DEFAULT_ROLE_TARGETS["coding"]
    assert coding.default_target == "local_fast"
    assert coding.deep_target == "local_deep_moe"
    assert coding.deep_threshold == "high"

    planning = DEFAULT_ROLE_TARGETS["planning"]
    assert planning.deep_threshold == "medium"

    debugging = DEFAULT_ROLE_TARGETS["debugging"]
    assert debugging.deep_threshold == "high_after_evidence"

    summarization = DEFAULT_ROLE_TARGETS["summarization"]
    assert summarization.deep_target == "disabled"
    assert summarization.deep_threshold == "disabled"

    tool_operator = DEFAULT_ROLE_TARGETS["tool_operator"]
    assert tool_operator.default_target == "local_small_or_local_fast"
    assert tool_operator.deep_target == "disabled"


def test_validate_role_targets_accepts_default_config() -> None:
    validate_role_targets(DEFAULT_ROLE_TARGETS)


def test_select_target_review_low_returns_local_fast() -> None:
    result = select_target("review", difficulty="low")

    assert result.target_id == "local_fast"
    assert result.deep_escalation is False
    assert result.cache_strategy == "role_prefix"


def test_select_target_review_medium_escalates_to_deep() -> None:
    result = select_target("review", difficulty="medium")

    assert result.target_id == "local_deep_moe"
    assert result.deep_escalation is True


def test_select_target_coding_high_escalates_to_deep() -> None:
    result = select_target("coding", difficulty="high")

    assert result.target_id == "local_deep_moe"
    assert result.deep_escalation is True


def test_select_target_coding_medium_stays_on_default() -> None:
    result = select_target("coding", difficulty="medium")

    assert result.target_id == "local_fast"
    assert result.deep_escalation is False


def test_select_target_summarization_never_escalates() -> None:
    result = select_target("summarization", difficulty="high")

    assert result.target_id == "local_fast"
    assert result.deep_escalation is False


def test_select_target_tool_operator_resolves_alias() -> None:
    result = select_target("tool_operator", difficulty="medium")

    assert result.target_id == "local_fast"
    assert result.deep_escalation is False


def test_select_target_unknown_role_fails_closed() -> None:
    with pytest.raises(UnknownRoleError, match="unknown role"):
        select_target("nonexistent", difficulty="medium")


def test_select_target_unknown_target_in_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mac_llm.roles import config as role_config
    import mac_llm.roles.select as select_module

    broken = dict(role_config.DEFAULT_ROLE_TARGETS)
    broken["coding"] = RoleTargetMapping(
        default_target="missing_target",
        deep_target="disabled",
        deep_threshold="high",
    )
    monkeypatch.setattr(role_config, "DEFAULT_ROLE_TARGETS", broken)
    monkeypatch.setattr(select_module, "DEFAULT_ROLE_TARGETS", broken)

    with pytest.raises(UnknownTargetError, match="unknown runtime target"):
        select_target("coding", difficulty="medium")


def test_validate_role_targets_unknown_target_fails_closed() -> None:
    broken = dict(DEFAULT_ROLE_TARGETS)
    broken["review"] = RoleTargetMapping(
        default_target="bogus_target",
        deep_target="local_deep_moe",
        deep_threshold="medium",
    )

    with pytest.raises(UnknownTargetError, match="unknown runtime target"):
        validate_role_targets(broken)


def test_cli_role_select_prints_resolved_target() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mac_llm.cli",
            "role",
            "select",
            "review",
            "--difficulty",
            "medium",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["role"] == "review"
    assert payload["target_id"] == "local_deep_moe"
    assert payload["deep_escalation"] is True
