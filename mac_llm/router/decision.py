"""Strict-JSON RouteDecision schema and fail-closed validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mac_llm.artifacts.schemas import ARTIFACT_TYPES
from mac_llm.external.config import DEFAULT_EXTERNAL_TARGETS
from mac_llm.external.schemas import CONSULTATION_MODES, EXECUTION_MODES
from mac_llm.roles.config import KNOWN_ROLES
from mac_llm.runtime.target import list_target_ids
from mac_llm.tools.schema import KNOWN_TOOLS


class RouteDecisionValidationError(ValueError):
    """Raised when route decision JSON fails schema validation."""


KNOWN_TASK_DIFFICULTIES: frozenset[str] = frozenset(
    {"low", "medium", "high", "very_high"}
)
KNOWN_CACHE_STRATEGIES: frozenset[str] = frozenset(
    {"role_prefix", "task_prefix", "none"}
)
KNOWN_TOKEN_STRATEGIES: frozenset[str] = frozenset(
    {
        "compress_then_split_then_escalate",
        "standard",
        "minimal",
    }
)
FALLBACK_CHAIN_SPECIAL: frozenset[str] = frozenset({"ask_user"})

KNOWN_STRUCTURED_ARTIFACT_NAMES: frozenset[str] = frozenset(
    "".join(part.capitalize() for part in artifact_type.split("_"))
    for artifact_type in ARTIFACT_TYPES
)

KNOWN_ROUTE_TARGETS: frozenset[str] = (
    frozenset(list_target_ids())
    | frozenset(DEFAULT_EXTERNAL_TARGETS)
    | FALLBACK_CHAIN_SPECIAL
)


def _require_fields(data: dict[str, Any], required: set[str]) -> None:
    missing = sorted(required - data.keys())
    if missing:
        raise RouteDecisionValidationError(
            f"missing required field(s): {', '.join(missing)}"
        )


def _require_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RouteDecisionValidationError(f"{key} must be an object")
    return value


def _require_bool(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise RouteDecisionValidationError(f"{key} must be a boolean")
    return value


def _require_float(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RouteDecisionValidationError(f"{key} must be a number")
    return float(value)


def _require_str_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        raise RouteDecisionValidationError(f"{key} must be an array")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise RouteDecisionValidationError(
                f"{key}[{index}] must be a non-empty string"
            )
        items.append(item)
    return tuple(items)


def _assert_known_target(target_id: str, *, context: str) -> None:
    if target_id not in KNOWN_ROUTE_TARGETS:
        raise RouteDecisionValidationError(f"unknown target: {target_id} ({context})")


def _assert_execution_target(target_id: str) -> None:
    if target_id in list_target_ids():
        return
    external = DEFAULT_EXTERNAL_TARGETS.get(target_id)
    if external is not None and external.mode == "execution":
        return
    raise RouteDecisionValidationError(f"unknown target: {target_id} (execution_target)")


@dataclass(frozen=True)
class ConsultationSpec:
    """Optional external consultation indicated by the route decision."""

    target: str | None
    mode: str | None
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "mode": self.mode,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConsultationSpec:
        _require_fields(data, {"target", "mode", "required"})
        required = _require_bool(data, "required")
        target = data.get("target")
        mode = data.get("mode")
        if target is not None and not isinstance(target, str):
            raise RouteDecisionValidationError("consultation.target must be a string or null")
        if mode is not None and not isinstance(mode, str):
            raise RouteDecisionValidationError("consultation.mode must be a string or null")
        if target is None and mode is not None:
            raise RouteDecisionValidationError(
                "consultation.mode requires consultation.target"
            )
        if target is not None:
            _assert_known_target(target, context="consultation.target")
            if mode is None:
                raise RouteDecisionValidationError(
                    "consultation.mode required when consultation.target is set"
                )
            if mode not in CONSULTATION_MODES and mode not in EXECUTION_MODES:
                raise RouteDecisionValidationError(f"unknown consultation mode: {mode}")
        return cls(target=target, mode=mode, required=required)


@dataclass(frozen=True)
class ToolStrategy:
    """Tool permissions for the routed task."""

    tool_operator_allowed: bool
    brokered_tools_allowed: bool
    tools: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool_operator_allowed": self.tool_operator_allowed,
            "brokered_tools_allowed": self.brokered_tools_allowed,
        }
        if self.tools:
            payload["tools"] = list(self.tools)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolStrategy:
        _require_fields(data, {"tool_operator_allowed", "brokered_tools_allowed"})
        tool_operator_allowed = _require_bool(data, "tool_operator_allowed")
        brokered_tools_allowed = _require_bool(data, "brokered_tools_allowed")
        tools: tuple[str, ...] = ()
        if "tools" in data:
            tools = _require_str_list(data, "tools")
            for tool in tools:
                if tool not in KNOWN_TOOLS:
                    raise RouteDecisionValidationError(f"unknown tool: {tool}")
        return cls(
            tool_operator_allowed=tool_operator_allowed,
            brokered_tools_allowed=brokered_tools_allowed,
            tools=tools,
        )


@dataclass(frozen=True)
class RouteDecision:
    """Validated route decision emitted by the simple router."""

    role: str
    task_difficulty: str
    execution_target: str
    requires_swap: bool
    cache_strategy: str
    structured_artifacts: tuple[str, ...]
    consultation: ConsultationSpec
    fallback_chain: tuple[str, ...]
    token_strategy: str
    tool_strategy: ToolStrategy
    confidence: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "task_difficulty": self.task_difficulty,
            "execution_target": self.execution_target,
            "requires_swap": self.requires_swap,
            "cache_strategy": self.cache_strategy,
            "structured_artifacts": list(self.structured_artifacts),
            "consultation": self.consultation.to_dict(),
            "fallback_chain": list(self.fallback_chain),
            "token_strategy": self.token_strategy,
            "tool_strategy": self.tool_strategy.to_dict(),
            "confidence": self.confidence,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouteDecision:
        return validate_route_decision(data)


def validate_route_decision(data: dict[str, Any]) -> RouteDecision:
    """Validate a route decision payload; fail closed on unknown or malformed input."""
    if not isinstance(data, dict):
        raise RouteDecisionValidationError("route decision must be an object")

    _require_fields(
        data,
        {
            "role",
            "task_difficulty",
            "execution_target",
            "requires_swap",
            "cache_strategy",
            "structured_artifacts",
            "consultation",
            "fallback_chain",
            "token_strategy",
            "tool_strategy",
            "confidence",
            "rationale",
        },
    )

    role = data["role"]
    if not isinstance(role, str) or not role:
        raise RouteDecisionValidationError("role must be a non-empty string")
    if role not in KNOWN_ROLES:
        raise RouteDecisionValidationError(f"unknown role: {role}")

    task_difficulty = data["task_difficulty"]
    if not isinstance(task_difficulty, str) or task_difficulty not in KNOWN_TASK_DIFFICULTIES:
        raise RouteDecisionValidationError(
            f"unknown task_difficulty: {task_difficulty!r}"
        )

    execution_target = data["execution_target"]
    if not isinstance(execution_target, str) or not execution_target:
        raise RouteDecisionValidationError("execution_target must be a non-empty string")
    _assert_execution_target(execution_target)

    requires_swap = _require_bool(data, "requires_swap")

    cache_strategy = data["cache_strategy"]
    if cache_strategy not in KNOWN_CACHE_STRATEGIES:
        raise RouteDecisionValidationError(f"unknown cache_strategy: {cache_strategy!r}")

    structured_artifacts = _require_str_list(data, "structured_artifacts")
    for artifact in structured_artifacts:
        if artifact not in KNOWN_STRUCTURED_ARTIFACT_NAMES:
            raise RouteDecisionValidationError(
                f"unknown structured artifact: {artifact}"
            )

    consultation = ConsultationSpec.from_dict(_require_mapping(data, "consultation"))

    fallback_chain = _require_str_list(data, "fallback_chain")
    if not fallback_chain:
        raise RouteDecisionValidationError("fallback_chain must not be empty")
    for entry in fallback_chain:
        _assert_known_target(entry, context="fallback_chain")

    token_strategy = data["token_strategy"]
    if token_strategy not in KNOWN_TOKEN_STRATEGIES:
        raise RouteDecisionValidationError(f"unknown token_strategy: {token_strategy!r}")

    tool_strategy = ToolStrategy.from_dict(_require_mapping(data, "tool_strategy"))
    confidence = _require_float(data, "confidence")
    if not 0.0 <= confidence <= 1.0:
        raise RouteDecisionValidationError("confidence must be between 0 and 1")

    rationale = data["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise RouteDecisionValidationError("rationale must be a non-empty string")

    return RouteDecision(
        role=role,
        task_difficulty=task_difficulty,
        execution_target=execution_target,
        requires_swap=requires_swap,
        cache_strategy=cache_strategy,
        structured_artifacts=structured_artifacts,
        consultation=consultation,
        fallback_chain=fallback_chain,
        token_strategy=token_strategy,
        tool_strategy=tool_strategy,
        confidence=confidence,
        rationale=rationale,
    )


def parse_route_decision(text: str) -> RouteDecision:
    """Parse strict JSON into a validated route decision."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RouteDecisionValidationError(f"invalid JSON: {exc}") from exc
    return validate_route_decision(data)
