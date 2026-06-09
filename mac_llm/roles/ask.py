"""Manual role ask orchestration — target selection, swap, completion, artifacts."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from mac_llm.artifacts.schemas import make_user_task_summary
from mac_llm.bench.artifacts import BenchmarkArtifactWriter, RunRecord
from mac_llm.roles.config import DEFAULT_ROLE_TARGETS, KNOWN_ROLES, resolve_role_target
from mac_llm.roles.select import SelectionResult, UnknownRoleError, select_target
from mac_llm.runtime.completion import CompletionResult, run_completion
from mac_llm.runtime.manager import RuntimeLifecycleError, RuntimeManager
from mac_llm.runtime.state import RuntimeState
from mac_llm.runtime.target import RuntimeTarget, get_target, list_target_ids


class AskError(RuntimeError):
    """Raised when ask orchestration cannot complete."""


@dataclass(frozen=True)
class RoleDecision:
    """Logged role/target/cache decision for a manual ask."""

    role: str
    target_id: str
    cache_strategy: str
    deep_escalation: bool
    difficulty: str


@dataclass(frozen=True)
class SwapResult:
    """Measured swap request outcome."""

    requested: bool
    from_target_id: str | None
    to_target_id: str
    duration_s: float
    success: bool
    message: str | None = None


@dataclass(frozen=True)
class AskResult:
    """Outcome of a manual role ask."""

    success: bool
    response_text: str | None
    error: str | None
    decision: RoleDecision
    swap: SwapResult | None
    artifact_path: Path


class ManagerLike(Protocol):
    def status(self) -> RuntimeState | None: ...

    def start(self, *, environ: dict[str, str] | None = None) -> RuntimeState: ...

    def stop(self) -> RuntimeState: ...

    def orphan_check(self) -> Any: ...


ManagerFactory = Callable[[RuntimeTarget], ManagerLike]
CompletionClient = Callable[..., CompletionResult]


def _find_active_target_id(*, manager_factory: ManagerFactory) -> str | None:
    for target_id in list_target_ids():
        manager = manager_factory(get_target(target_id))
        state = manager.status()
        if state is not None and state.status == "running" and state.pid is not None:
            return target_id
    return None


def _manual_selection(role: str, *, difficulty: str) -> SelectionResult:
    if role not in KNOWN_ROLES:
        raise UnknownRoleError(f"unknown role: {role}")

    mapping = DEFAULT_ROLE_TARGETS[role]
    default_target_id = resolve_role_target(mapping.default_target)
    if mapping.deep_target != "disabled":
        resolve_role_target(mapping.deep_target)

    selection = select_target(role, difficulty=difficulty)
    return SelectionResult(
        target_id=default_target_id,
        deep_escalation=selection.deep_escalation,
        cache_strategy=selection.cache_strategy,
    )


def _ensure_target_active(
    target_id: str,
    *,
    manager_factory: ManagerFactory,
) -> SwapResult:
    active_target_id = _find_active_target_id(manager_factory=manager_factory)
    if active_target_id == target_id:
        return SwapResult(
            requested=False,
            from_target_id=active_target_id,
            to_target_id=target_id,
            duration_s=0.0,
            success=True,
        )

    started = time.perf_counter()
    if active_target_id is not None:
        active_manager = manager_factory(get_target(active_target_id))
        try:
            active_manager.stop()
        except RuntimeLifecycleError as exc:
            duration = time.perf_counter() - started
            return SwapResult(
                requested=True,
                from_target_id=active_target_id,
                to_target_id=target_id,
                duration_s=duration,
                success=False,
                message=str(exc),
            )

    selected_manager = manager_factory(get_target(target_id))
    try:
        selected_manager.start()
    except RuntimeLifecycleError as exc:
        duration = time.perf_counter() - started
        return SwapResult(
            requested=True,
            from_target_id=active_target_id,
            to_target_id=target_id,
            duration_s=duration,
            success=False,
            message=str(exc),
        )

    orphan = selected_manager.orphan_check()
    if getattr(orphan, "has_orphan", False):
        duration = time.perf_counter() - started
        return SwapResult(
            requested=True,
            from_target_id=active_target_id,
            to_target_id=target_id,
            duration_s=duration,
            success=False,
            message="orphan detected after swap",
        )

    duration = time.perf_counter() - started
    return SwapResult(
        requested=active_target_id != target_id or active_target_id is None,
        from_target_id=active_target_id,
        to_target_id=target_id,
        duration_s=duration,
        success=True,
    )


def run_ask(
    role: str,
    prompt: str,
    *,
    root: Path,
    difficulty: str = "medium",
    manager_factory: ManagerFactory | None = None,
    completion_client: CompletionClient | None = None,
    timestamp: str | None = None,
) -> AskResult:
    """Run a manual role ask with swap, completion, logging, and session artifact."""
    if manager_factory is None:
        manager_factory = RuntimeManager
    if completion_client is None:
        completion_client = lambda *, target, prompt: run_completion(  # noqa: E731
            target=target,
            prompt=prompt,
        )

    writer = BenchmarkArtifactWriter(root, timestamp=timestamp)
    writer.ensure_run_dir()

    try:
        selection = _manual_selection(role, difficulty=difficulty)
    except (UnknownRoleError, ValueError) as exc:
        _log_failure(writer, role=role, prompt=prompt, error=str(exc))
        raise AskError(str(exc)) from exc

    decision = RoleDecision(
        role=role,
        target_id=selection.target_id,
        cache_strategy=selection.cache_strategy,
        deep_escalation=selection.deep_escalation,
        difficulty=difficulty,
    )
    writer.append(
        RunRecord(
            event="ask.decision",
            status="ok",
            metadata={
                "role": decision.role,
                "target_id": decision.target_id,
                "cache_strategy": decision.cache_strategy,
                "deep_escalation": decision.deep_escalation,
                "difficulty": decision.difficulty,
            },
        )
    )
    writer.append_structured_artifact(
        make_user_task_summary(user_text=prompt, intent=role)
    )

    swap = _ensure_target_active(
        selection.target_id,
        manager_factory=manager_factory,
    )
    writer.append(
        RunRecord(
            event="ask.swap",
            status="ok" if swap.success else "error",
            message=swap.message,
            metadata={
                "requested": swap.requested,
                "from_target_id": swap.from_target_id,
                "to_target_id": swap.to_target_id,
                "duration_s": swap.duration_s,
            },
        )
    )
    if not swap.success:
        error = swap.message or "target swap failed"
        _log_failure(writer, role=role, prompt=prompt, error=error, decision=decision)
        raise AskError(error)

    target = get_target(selection.target_id)
    completion = completion_client(target=target, prompt=prompt)
    if not completion.ok:
        error = completion.error or "completion failed"
        _log_failure(writer, role=role, prompt=prompt, error=error, decision=decision)
        return AskResult(
            success=False,
            response_text=None,
            error=error,
            decision=decision,
            swap=swap,
            artifact_path=writer.run_dir,
        )

    writer.append(
        RunRecord(
            event="ask.complete",
            status="ok",
            metadata={
                "ttft_ms": completion.ttft_ms,
                "tokens_per_second": completion.tokens_per_second,
            },
        )
    )
    writer.write_summary()
    return AskResult(
        success=True,
        response_text=completion.text,
        error=None,
        decision=decision,
        swap=swap,
        artifact_path=writer.run_dir,
    )


def _log_failure(
    writer: BenchmarkArtifactWriter,
    *,
    role: str,
    prompt: str,
    error: str,
    decision: RoleDecision | None = None,
) -> None:
    metadata: dict[str, Any] = {"role": role, "prompt": prompt, "error": error}
    if decision is not None:
        metadata.update(
            {
                "target_id": decision.target_id,
                "cache_strategy": decision.cache_strategy,
            }
        )
    writer.append(
        RunRecord(
            event="ask.failure",
            status="error",
            message=error,
            metadata=metadata,
        )
    )
    writer.write_summary()
