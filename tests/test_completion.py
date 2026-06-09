"""Tests for OpenAI-compatible completion client."""

from __future__ import annotations

from mac_llm.runtime.completion import (
    DEFAULT_MAX_TOKENS,
    CompletionResult,
    run_completion,
)
from mac_llm.runtime.target import get_target


def test_run_completion_sends_max_tokens_and_custom_timeout() -> None:
    captured: dict[str, object] = {}

    def fake_post_json(
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout_seconds"] = timeout_seconds
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"completion_tokens": 2},
        }

    result = run_completion(
        target=get_target("local_fast"),
        prompt="hello",
        max_tokens=64,
        timeout_seconds=90.0,
        post_json=fake_post_json,
    )

    assert result.ok is True
    assert result.text == "ok"
    assert captured["timeout_seconds"] == 90.0
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["max_tokens"] == 64


def test_run_completion_default_max_tokens() -> None:
    captured: dict[str, object] = {}

    def fake_post_json(
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "hi"}}]}

    run_completion(
        target=get_target("local_fast"),
        prompt="hello",
        post_json=fake_post_json,
        timeout_seconds=10.0,
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["max_tokens"] == DEFAULT_MAX_TOKENS


def test_run_completion_uses_reasoning_content_when_content_empty() -> None:
    def fake_post_json(
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "RuntimeManager.ensure_inactive stops any managed runtime.",
                    }
                }
            ],
            "usage": {"completion_tokens": 12},
        }

    result = run_completion(
        target=get_target("local_fast"),
        prompt="hello",
        post_json=fake_post_json,
        timeout_seconds=10.0,
    )

    assert result.ok is True
    assert "ensure_inactive" in (result.text or "")


def test_run_completion_fails_on_empty_content_and_reasoning() -> None:
    def fake_post_json(
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        return {"choices": [{"message": {"content": "", "reasoning_content": ""}}]}

    result = run_completion(
        target=get_target("local_fast"),
        prompt="hello",
        post_json=fake_post_json,
        timeout_seconds=10.0,
    )

    assert result.ok is False
    assert result.error == "completion returned empty content"
