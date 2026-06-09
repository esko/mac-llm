"""Tests for mac-llm ask --role manual role CLI (fake manager/target, no real model)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from mac_llm.bench.artifacts import BenchmarkArtifactWriter
from mac_llm.roles.ask import AskError, run_ask
from mac_llm.roles.select import UnknownRoleError, select_target
from mac_llm.runtime.completion import CompletionResult
from mac_llm.runtime.manager import RuntimeLifecycleError
from mac_llm.runtime.state import RuntimeState
from mac_llm.runtime.target import RuntimeTarget, UnknownTargetError, get_target, list_target_ids


def test_select_target_review_low_returns_local_fast() -> None:
    result = select_target("review", difficulty="low")

    assert result.target_id == "local_fast"
    assert result.deep_escalation is False
    assert result.cache_strategy == "role_prefix"


def test_select_target_review_medium_indicates_deep_escalation() -> None:
    result = select_target("review", difficulty="medium")

    assert result.target_id == "local_deep_moe"
    assert result.deep_escalation is True
    assert result.cache_strategy == "role_prefix"


def test_select_target_unknown_role_fails_closed() -> None:
    with pytest.raises(UnknownRoleError, match="unknown role"):
        select_target("nonexistent", difficulty="medium")


def test_select_target_unknown_target_in_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mac_llm.roles import config as role_config

    broken = dict(role_config.DEFAULT_ROLE_TARGETS)
    broken["coding"] = role_config.RoleTargetMapping(
        default_target="missing_target",
        deep_target="disabled",
        deep_threshold="high",
    )
    monkeypatch.setattr(role_config, "DEFAULT_ROLE_TARGETS", broken)
    import mac_llm.roles.select as select_module

    monkeypatch.setattr(select_module, "DEFAULT_ROLE_TARGETS", broken)

    with pytest.raises(UnknownTargetError, match="unknown runtime target"):
        select_target("coding", difficulty="medium")


@dataclass
class FakeManager:
    target: RuntimeTarget
    running: bool = False
    start_calls: int = 0
    stop_calls: int = 0
    orphan_has_orphan: bool = False

    def status(self) -> RuntimeState | None:
        if not self.running:
            return None
        return RuntimeState(
            target_id=self.target.target_id,
            pid=4242,
            port=self.target.port,
            start_time=time.time(),
            stop_timeout=self.target.stop_timeout,
            last_error=None,
            status="running",
        )

    def start(self, *, environ: dict[str, str] | None = None) -> RuntimeState:
        self.start_calls += 1
        self.running = True
        state = self.status()
        assert state is not None
        return state

    def stop(self) -> RuntimeState:
        self.stop_calls += 1
        self.running = False
        return RuntimeState(
            target_id=self.target.target_id,
            pid=None,
            port=self.target.port,
            start_time=None,
            stop_timeout=self.target.stop_timeout,
            last_error=None,
            status="stopped",
        )

    def orphan_check(self) -> Any:
        @dataclass(frozen=True)
        class Result:
            has_orphan: bool

        return Result(has_orphan=self.orphan_has_orphan)


def _make_fake_stack(
    tmp_path: Path,
    *,
    active_target_id: str | None = None,
    completion_result: CompletionResult | None = None,
) -> tuple[dict[str, FakeManager], Callable[..., CompletionResult]]:
    managers: dict[str, FakeManager] = {}
    for target_id in list_target_ids():
        target = get_target(target_id)
        managers[target_id] = FakeManager(
            target=target,
            running=target_id == active_target_id,
        )

    def manager_factory(target: RuntimeTarget) -> FakeManager:
        return managers[target.target_id]

    def completion_client(*, target: RuntimeTarget, prompt: str) -> CompletionResult:
        if completion_result is not None:
            return completion_result
        return CompletionResult(ok=True, text=f"answer for: {prompt}", error=None)

    return managers, manager_factory, completion_client  # type: ignore[return-value]


def test_run_ask_local_fast_when_already_active_writes_artifact(
    tmp_path: Path,
) -> None:
    managers, manager_factory, completion_client = _make_fake_stack(
        tmp_path, active_target_id="local_fast"
    )

    result = run_ask(
        "review",
        "review this diff",
        root=tmp_path,
        manager_factory=manager_factory,
        completion_client=completion_client,
        timestamp="20260109T120000Z",
    )

    assert result.success is True
    assert result.response_text == "answer for: review this diff"
    assert result.decision.role == "review"
    assert result.decision.target_id == "local_fast"
    assert result.swap is not None
    assert result.swap.requested is False
    assert managers["local_fast"].start_calls == 0
    assert managers["local_fast"].stop_calls == 0

    jsonl_path = result.artifact_path / "run.jsonl"
    assert jsonl_path.is_file()
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    event_names = [event["event"] for event in events]
    assert "ask.decision" in event_names
    assert "ask.complete" in event_names


def test_run_ask_requests_swap_when_selected_target_not_active(tmp_path: Path) -> None:
    managers, manager_factory, completion_client = _make_fake_stack(
        tmp_path, active_target_id="local_deep_moe"
    )

    result = run_ask(
        "coding",
        "fix this",
        root=tmp_path,
        manager_factory=manager_factory,
        completion_client=completion_client,
        timestamp="20260109T120001Z",
    )

    assert result.success is True
    assert result.swap is not None
    assert result.swap.requested is True
    assert result.swap.from_target_id == "local_deep_moe"
    assert result.swap.to_target_id == "local_fast"
    assert result.swap.duration_s >= 0
    assert managers["local_deep_moe"].stop_calls == 1
    assert managers["local_fast"].start_calls == 1


def test_run_ask_starts_target_when_none_active(tmp_path: Path) -> None:
    managers, manager_factory, completion_client = _make_fake_stack(
        tmp_path, active_target_id=None
    )

    result = run_ask(
        "planning",
        "plan this refactor",
        root=tmp_path,
        manager_factory=manager_factory,
        completion_client=completion_client,
        timestamp="20260109T120002Z",
    )

    assert result.success is True
    assert result.swap is not None
    assert result.swap.requested is True
    assert result.swap.from_target_id is None
    assert managers["local_fast"].start_calls == 1


def test_run_ask_fails_clearly_and_still_writes_artifact_on_completion_error(
    tmp_path: Path,
) -> None:
    _, manager_factory, _ = _make_fake_stack(tmp_path, active_target_id="local_fast")
    failing_client = lambda *, target, prompt: CompletionResult(  # noqa: E731
        ok=False,
        text=None,
        error="completion unavailable",
    )

    result = run_ask(
        "review",
        "review this diff",
        root=tmp_path,
        manager_factory=manager_factory,
        completion_client=failing_client,
        timestamp="20260109T120003Z",
    )

    assert result.success is False
    assert result.error == "completion unavailable"
    assert result.artifact_path.is_dir()
    events = [
        json.loads(line)
        for line in (result.artifact_path / "run.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "ask.failure" for event in events)


def test_run_ask_fails_clearly_on_swap_start_error(tmp_path: Path) -> None:
    managers, manager_factory, completion_client = _make_fake_stack(
        tmp_path, active_target_id=None
    )

    class FailingStartManager(FakeManager):
        def start(self, *, environ: dict[str, str] | None = None) -> RuntimeState:
            raise RuntimeLifecycleError("runtime command unavailable")

    managers["local_fast"] = FailingStartManager(
        target=get_target("local_fast"),
        running=False,
    )

    with pytest.raises(AskError, match="runtime command unavailable"):
        run_ask(
            "coding",
            "fix this",
            root=tmp_path,
            manager_factory=manager_factory,
            completion_client=completion_client,
            timestamp="20260109T120004Z",
        )

    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120004Z")
    events = [
        json.loads(line)
        for line in (writer.run_dir / "run.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "ask.failure" for event in events)


def test_cli_ask_role_help_lists_roles() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mac_llm.cli", "ask", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--role" in result.stdout
    assert "review" in result.stdout


def test_cli_ask_unknown_role_exits_nonzero() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mac_llm.cli",
            "ask",
            "--role",
            "invalid",
            "hello",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "unknown role" in result.stderr.lower() or "invalid" in result.stderr.lower()
